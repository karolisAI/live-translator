import time
import unittest
from threading import Event, Thread

from live_translator.session import BidirectionalSession, Direction


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for background work")


class BidirectionalSessionTests(unittest.TestCase):
    def test_runs_all_directions_concurrently_until_stopped(self) -> None:
        running = {"out": Event(), "in": Event()}
        prepared: list[str] = []
        closed: list[str] = []

        def make_run(key: str):
            def run(stop: Event) -> None:
                running[key].set()
                stop.wait(timeout=2.0)

            return run

        directions = [
            Direction("out", run=make_run("out"), prepare=lambda: prepared.append("out"), close=lambda: closed.append("out")),
            Direction("in", run=make_run("in"), prepare=lambda: prepared.append("in"), close=lambda: closed.append("in")),
        ]
        session = BidirectionalSession(directions)
        runner = Thread(target=session.run)
        runner.start()
        try:
            # Both directions are live at the same time, not one-then-the-other.
            self.assertTrue(running["out"].wait(timeout=1.0))
            self.assertTrue(running["in"].wait(timeout=1.0))
            session.stop()
            runner.join(timeout=3.0)
            self.assertFalse(runner.is_alive())
        finally:
            session.stop()
            runner.join(timeout=3.0)

        self.assertEqual(sorted(prepared), ["in", "out"])
        self.assertEqual(sorted(closed), ["in", "out"])

    def test_prepare_runs_for_every_direction_before_any_runs(self) -> None:
        prepared: list[str] = []
        started_after: list[list[str]] = []

        def make_run(_key: str):
            def run(stop: Event) -> None:
                # Snapshot what was prepared by the time this direction starts.
                started_after.append(list(prepared))
                stop.wait(timeout=2.0)

            return run

        directions = [
            Direction("a", run=make_run("a"), prepare=lambda: prepared.append("a")),
            Direction("b", run=make_run("b"), prepare=lambda: prepared.append("b")),
        ]
        session = BidirectionalSession(directions)
        runner = Thread(target=session.run)
        runner.start()
        try:
            wait_until(lambda: len(started_after) == 2)
        finally:
            session.stop()
            runner.join(timeout=3.0)

        # Every direction saw both prepares already done before it began.
        for snapshot in started_after:
            self.assertEqual(sorted(snapshot), ["a", "b"])

    def test_one_direction_failure_is_isolated_and_others_keep_running(self) -> None:
        healthy_running = Event()
        warnings: list[str] = []

        def run_broken(_stop: Event) -> None:
            raise ValueError("model failed")

        def run_healthy(stop: Event) -> None:
            healthy_running.set()
            stop.wait(timeout=2.0)

        directions = [
            Direction("broken", run=run_broken),
            Direction("healthy", run=run_healthy),
        ]
        session = BidirectionalSession(directions, on_warning=warnings.append)
        runner = Thread(target=session.run)
        runner.start()
        try:
            self.assertTrue(healthy_running.wait(timeout=1.0))
            # The broken direction has failed by now, but the session is still
            # alive because the healthy one keeps running.
            wait_until(lambda: any("broken" in w and "ended early" in w for w in warnings))
            time.sleep(0.1)
            self.assertTrue(runner.is_alive())
            session.stop()
            runner.join(timeout=3.0)
            self.assertFalse(runner.is_alive())
        finally:
            session.stop()
            runner.join(timeout=3.0)

    def test_prepare_failure_still_closes_already_prepared_directions(self) -> None:
        closed: list[str] = []
        ran: list[str] = []

        def failing_prepare() -> None:
            raise RuntimeError("model load failed")

        directions = [
            Direction(
                "first",
                run=lambda _stop: ran.append("first"),
                prepare=lambda: None,
                close=lambda: closed.append("first"),
            ),
            Direction(
                "second",
                run=lambda _stop: ran.append("second"),
                prepare=failing_prepare,
                close=lambda: closed.append("second"),
            ),
        ]
        session = BidirectionalSession(directions)
        # The failure propagates, but cleanup must run first.
        with self.assertRaisesRegex(RuntimeError, "model load failed"):
            session.run()

        # "first" was prepared before "second" failed, so it must be closed even
        # though the session never got to run anything.
        self.assertIn("first", closed)
        self.assertEqual(ran, [])

    def test_returns_when_all_directions_finish_on_their_own(self) -> None:
        # A direction that returns immediately should not hang the session:
        # run() ends once the last thread exits, with no stop() call.
        directions = [
            Direction("a", run=lambda _stop: None),
            Direction("b", run=lambda _stop: None),
        ]
        session = BidirectionalSession(directions)
        runner = Thread(target=session.run)
        runner.start()
        runner.join(timeout=3.0)
        self.assertFalse(runner.is_alive())

    def test_requires_at_least_two_directions(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            BidirectionalSession([Direction("only", run=lambda _stop: None)])

    def test_rejects_duplicate_labels(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct label"):
            BidirectionalSession(
                [
                    Direction("same", run=lambda _stop: None),
                    Direction("same", run=lambda _stop: None),
                ]
            )


if __name__ == "__main__":
    unittest.main()

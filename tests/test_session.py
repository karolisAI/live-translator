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

    def test_healthy_direction_state_is_unaffected_by_the_other_failing(self) -> None:
        # Simulates each direction's own phrase counter and queue: separate
        # objects that a forced failure in "broken" must never touch.
        healthy_phrase_count = {"value": 0}
        healthy_queue: list[int] = []
        warnings: list[str] = []

        def run_broken(_stop: Event) -> None:
            raise RuntimeError("recognizer crashed")

        def run_healthy(stop: Event) -> None:
            for phrase in range(5):
                healthy_queue.append(phrase)
                healthy_phrase_count["value"] += 1
            stop.wait(timeout=2.0)

        directions = [
            Direction("broken", run=run_broken),
            Direction("healthy", run=run_healthy),
        ]
        session = BidirectionalSession(directions, on_warning=warnings.append)
        runner = Thread(target=session.run)
        runner.start()
        try:
            wait_until(lambda: healthy_phrase_count["value"] == 5)
            wait_until(lambda: any("broken" in w and "ended early" in w for w in warnings))
            # The failure in "broken" changed none of "healthy"'s own state.
            self.assertEqual(healthy_phrase_count["value"], 5)
            self.assertEqual(healthy_queue, [0, 1, 2, 3, 4])
            self.assertTrue(session.is_running("healthy"))
            self.assertFalse(session.is_running("broken"))
        finally:
            session.stop()
            runner.join(timeout=3.0)

    def test_failed_direction_is_closed_promptly_and_only_once(self) -> None:
        closed: list[str] = []
        warnings: list[str] = []

        directions = [
            Direction(
                "broken",
                run=lambda _stop: (_ for _ in ()).throw(RuntimeError("boom")),
                close=lambda: closed.append("broken"),
            ),
            Direction("healthy", run=lambda stop: stop.wait(timeout=2.0)),
        ]
        session = BidirectionalSession(directions, on_warning=warnings.append)
        runner = Thread(target=session.run)
        runner.start()
        try:
            # Closed while "healthy" is still running, well before the session
            # as a whole ends.
            wait_until(lambda: "broken" in closed)
            self.assertTrue(runner.is_alive())
        finally:
            session.stop()
            runner.join(timeout=3.0)

        # Not closed a second time during the session's own teardown.
        self.assertEqual(closed, ["broken"])

    def test_restart_brings_back_a_failed_direction_without_touching_the_other(self) -> None:
        healthy_running = Event()
        warnings: list[str] = []
        restarted_running = Event()

        directions = [
            Direction(
                "broken",
                run=lambda _stop: (_ for _ in ()).throw(RuntimeError("model crashed")),
            ),
            Direction(
                "healthy",
                run=lambda stop: (healthy_running.set(), stop.wait(timeout=5.0)),
            ),
        ]
        session = BidirectionalSession(directions, on_warning=warnings.append)
        runner = Thread(target=session.run)
        runner.start()
        try:
            self.assertTrue(healthy_running.wait(timeout=1.0))
            wait_until(lambda: not session.is_running("broken"))

            def run_recovered(stop: Event) -> None:
                restarted_running.set()
                stop.wait(timeout=5.0)

            session.restart(Direction("broken", run=run_recovered))

            self.assertTrue(restarted_running.wait(timeout=1.0))
            self.assertTrue(session.is_running("broken"))
            # "healthy" was never disturbed by the restart of its peer.
            self.assertTrue(session.is_running("healthy"))
            self.assertTrue(runner.is_alive())
        finally:
            session.stop()
            runner.join(timeout=3.0)
        self.assertFalse(runner.is_alive())

    def test_restart_refuses_a_direction_that_is_still_running(self) -> None:
        directions = [
            Direction("a", run=lambda stop: stop.wait(timeout=2.0)),
            Direction("b", run=lambda stop: stop.wait(timeout=2.0)),
        ]
        session = BidirectionalSession(directions)
        runner = Thread(target=session.run)
        runner.start()
        try:
            wait_until(lambda: session.is_running("a"))
            with self.assertRaisesRegex(RuntimeError, "still running"):
                session.restart(Direction("a", run=lambda _stop: None))
        finally:
            session.stop()
            runner.join(timeout=3.0)

    def test_restart_rejects_an_unknown_label(self) -> None:
        directions = [
            Direction("a", run=lambda _stop: None),
            Direction("b", run=lambda _stop: None),
        ]
        session = BidirectionalSession(directions)
        with self.assertRaisesRegex(ValueError, "No direction named"):
            session.restart(Direction("c", run=lambda _stop: None))

    def test_restarted_direction_is_still_closed_when_the_session_ends(self) -> None:
        closed: list[str] = []
        directions = [
            Direction(
                "a",
                run=lambda _stop: (_ for _ in ()).throw(RuntimeError("boom")),
                close=lambda: closed.append("a-first"),
            ),
            Direction("b", run=lambda stop: stop.wait(timeout=3.0)),
        ]
        session = BidirectionalSession(directions)
        runner = Thread(target=session.run)
        runner.start()
        try:
            wait_until(lambda: not session.is_running("a"))
            session.restart(
                Direction(
                    "a",
                    run=lambda stop: stop.wait(timeout=3.0),
                    close=lambda: closed.append("a-second"),
                )
            )
            wait_until(lambda: session.is_running("a"))
        finally:
            session.stop()
            runner.join(timeout=3.0)

        # The first instance was closed once (on failure); the replacement
        # installed by restart is closed once too (at session teardown).
        self.assertEqual(closed.count("a-first"), 1)
        self.assertEqual(closed.count("a-second"), 1)


if __name__ == "__main__":
    unittest.main()

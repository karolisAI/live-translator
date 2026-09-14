from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Callable, Iterable


@dataclass
class Direction:
    """One translation direction the session runs concurrently with the others.

    `run` receives this direction's stop event and must block until that event
    is set (or until it finishes/raises on its own). `prepare` loads models
    ahead of the concurrent run; `close` releases them afterwards. The pipeline
    supplies these as `prepare`, `run_prepared`, and `close`, but the indirection
    keeps the session testable without audio devices or models.
    """

    label: str
    run: Callable[[Event], None]
    prepare: Callable[[], None] = field(default=lambda: None)
    close: Callable[[], None] = field(default=lambda: None)


class BidirectionalSession:
    """Run several one-way translation directions at once, in one process.

    Each direction is an independent capture -> ASR -> MT -> TTS chain with its
    own workers and its own stop event, so a stall or a crash in one never
    blocks or ends another (that isolation is what US-1.3 builds on). The session
    prepares every direction, runs each on its own thread, and blocks until the
    user interrupts it or every direction has ended on its own.
    """

    def __init__(
        self,
        directions: Iterable[Direction],
        *,
        on_warning: Callable[[str], None] = print,
        join_timeout: float = 35.0,
    ) -> None:
        directions = list(directions)
        if len(directions) < 2:
            raise ValueError("A bidirectional session needs at least two directions")
        labels = [direction.label for direction in directions]
        if len(set(labels)) != len(labels):
            raise ValueError("Each direction needs a distinct label")
        self._directions = directions
        self._on_warning = on_warning
        # Generous over the 30s Piper timeout each direction's own shutdown
        # already waits out; this is only the outer safety net on the join.
        self._join_timeout = join_timeout
        self._session_stop = Event()
        self._stops: dict[str, Event] = {d.label: Event() for d in directions}
        self._threads: list[Thread] = []
        self._failures: dict[str, BaseException] = {}

    def stop(self) -> None:
        """Ask every direction to wind down. Idempotent; safe from any thread."""
        self._session_stop.set()
        for stop in self._stops.values():
            stop.set()

    def run(self) -> None:
        interrupted = False
        try:
            # Prepared one at a time, not concurrently: model loading is heavy
            # and its progress lines would interleave into noise. Inside the try
            # so that if a later prepare() raises, the finally below still closes
            # the directions already prepared -- a resident Piper started by an
            # earlier warm_up() would otherwise be orphaned.
            for direction in self._directions:
                direction.prepare()

            for direction in self._directions:
                thread = Thread(
                    target=self._supervise,
                    args=(direction,),
                    name=f"live-translator-direction-{direction.label}",
                    daemon=True,
                )
                self._threads.append(thread)
                thread.start()

            # Wake either when the user interrupts (session stop set) or when the
            # last direction has exited on its own.
            while any(thread.is_alive() for thread in self._threads):
                if self._session_stop.wait(timeout=0.2):
                    break
        except KeyboardInterrupt:
            interrupted = True
        finally:
            self.stop()
            for thread in self._threads:
                thread.join(timeout=self._join_timeout)
            for direction in self._directions:
                try:
                    direction.close()
                except Exception as exc:  # cleanup must not mask the real outcome
                    self._on_warning(f"[{direction.label}] cleanup failed: {exc}")

        self._report(interrupted)

    def _supervise(self, direction: Direction) -> None:
        stop = self._stops[direction.label]
        try:
            direction.run(stop)
        except BaseException as exc:  # isolate one direction's failure from the rest
            self._failures[direction.label] = exc
            self._on_warning(
                f"[{direction.label}] direction ended early: {exc}. "
                "Other directions continue."
            )
        finally:
            # A direction that returns or raises stops only itself, never its
            # peers -- the session ends when the user interrupts it.
            stop.set()

    def _report(self, interrupted: bool) -> None:
        if self._failures:
            failed = ", ".join(sorted(self._failures))
            self._on_warning(f"Conversation ended. Direction(s) that failed: {failed}.")
        elif interrupted:
            print("Conversation ended.")

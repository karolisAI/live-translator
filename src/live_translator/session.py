from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock, Thread
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
    own workers, its own stop event, and (via the pipeline the caller wires up)
    its own recognizer, translator, synthesizer, and queues -- nothing here is
    shared between directions except the session-wide stop signal. A stall or a
    crash in one direction's worker therefore never blocks, corrupts, or ends
    another: `_supervise` catches anything that escapes a direction's `run` and
    marks only that direction stopped (US-1.3). The session process itself
    keeps running as long as at least one direction is still alive, and a
    stopped direction can be brought back with `restart` without touching any
    other direction or ending the session -- restarting is the documented way
    to recover a direction, not automatic; the session does not retry on its
    own, since a model crash or device error is unlikely to be transient.

    The session prepares every direction, runs each on its own thread, and
    blocks until the user interrupts it or every direction has ended on its
    own.
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
        self._on_warning = on_warning
        # Generous over the 30s Piper timeout each direction's own shutdown
        # already waits out; this is only the outer safety net on the join.
        self._join_timeout = join_timeout
        self._session_stop = Event()
        # Guards the four dicts below: `restart` can be called from a control
        # thread (e.g. a console command) while `run` is concurrently polling
        # or tearing down threads on its own thread, so mutation and iteration
        # of this shared bookkeeping must not race.
        self._lock = Lock()
        self._directions: dict[str, Direction] = {d.label: d for d in directions}
        self._stops: dict[str, Event] = {d.label: Event() for d in directions}
        self._threads: dict[str, Thread] = {}
        self._failures: dict[str, BaseException] = {}
        # Labels whose *current* direction instance has already been closed,
        # so a direction closed early on failure (see `_supervise`) is not
        # closed a second time in `run()`'s teardown. `restart` discards a
        # label from here when it installs a fresh instance, since that new
        # instance's own resources have not been closed yet.
        self._closed: set[str] = set()

    def stop(self) -> None:
        """Ask every direction to wind down. Idempotent; safe from any thread."""
        self._session_stop.set()
        with self._lock:
            stops = list(self._stops.values())
        for stop in stops:
            stop.set()

    def labels(self) -> list[str]:
        """Every direction label this session knows about, prepared or not."""
        with self._lock:
            return list(self._directions.keys())

    def is_running(self, label: str) -> bool:
        """Whether `label`'s worker thread is currently alive."""
        with self._lock:
            thread = self._threads.get(label)
        return thread is not None and thread.is_alive()

    def run(self) -> None:
        interrupted = False
        try:
            # Prepared one at a time, not concurrently: model loading is heavy
            # and its progress lines would interleave into noise. Inside the try
            # so that if a later prepare() raises, the finally below still closes
            # the directions already prepared -- a resident Piper started by an
            # earlier warm_up() would otherwise be orphaned.
            with self._lock:
                directions = list(self._directions.items())
            for _label, direction in directions:
                direction.prepare()

            with self._lock:
                for label, direction in self._directions.items():
                    self._start_direction_thread(label, direction)

            # Wake either when the user interrupts (session stop set) or when
            # the last direction has exited on its own. Threads are
            # re-snapshotted each pass so a direction brought back with
            # `restart` while this loop is running keeps the session alive.
            while True:
                with self._lock:
                    threads = list(self._threads.values())
                if not any(thread.is_alive() for thread in threads):
                    break
                if self._session_stop.wait(timeout=0.2):
                    break
        except KeyboardInterrupt:
            interrupted = True
        finally:
            self.stop()
            with self._lock:
                threads = list(self._threads.values())
                directions = list(self._directions.values())
            for thread in threads:
                thread.join(timeout=self._join_timeout)
            for direction in directions:
                self._close_direction(direction.label, direction)

        self._report(interrupted)

    def restart(self, direction: Direction) -> None:
        """Replace a stopped direction with a freshly built one, in place.

        `direction` must reuse the label of a direction already in this
        session but should otherwise be a fresh build (a new pipeline, new ASR
        / translator / synthesizer instances) -- restarting is meant to
        recover from a model crash or device error, so reusing the same
        objects that just failed would likely just fail the same way again.

        Only the named direction is touched: its old thread is joined (it must
        already have exited -- a still-running direction refuses restart) and
        its resources are closed before the replacement is prepared and
        started on a new thread and stop `Event`. Every other direction's
        thread, queues, stop event, and failure record are left exactly as
        they were, so this can never disturb a healthy direction. Safe to call
        while `run()` is executing on another thread.
        """
        label = direction.label
        with self._lock:
            if label not in self._directions:
                raise ValueError(f"No direction named {label!r} in this session")
            thread = self._threads.get(label)
            old_direction = self._directions[label]
        if thread is not None and thread.is_alive():
            raise RuntimeError(f"Direction {label!r} is still running; stop it before restarting")

        # No-op if `_supervise` already closed it on failure; otherwise this is
        # the direction's first close (it stopped some other way, e.g. it
        # returned on its own before a restart was requested).
        self._close_direction(label, old_direction)

        direction.prepare()
        with self._lock:
            self._directions[label] = direction
            self._stops[label] = Event()
            self._failures.pop(label, None)
            # The new instance's resources have not been closed yet, even
            # though its label was just marked closed for the old instance.
            self._closed.discard(label)
            self._start_direction_thread(label, direction)
        self._on_warning(f"[{label}] direction restarted.")

    def _close_direction(self, label: str, direction: Direction) -> None:
        """Close `direction` at most once per (label, instance) lifetime.

        Both a failure (`_supervise`) and normal teardown (`run`'s finally)
        can reach the same still-live direction; without this guard a close
        callable that is not itself idempotent (unlike the pipeline's, which
        is) would run twice.
        """
        with self._lock:
            if label in self._closed:
                return
            self._closed.add(label)
        try:
            direction.close()
        except Exception as exc:  # cleanup must not mask the real outcome
            self._on_warning(f"[{label}] cleanup failed: {exc}")

    def _start_direction_thread(self, label: str, direction: Direction) -> None:
        """Start `direction`'s worker thread. Caller must hold `self._lock`."""
        thread = Thread(
            target=self._supervise,
            args=(direction,),
            name=f"live-translator-direction-{label}",
            daemon=True,
        )
        self._threads[label] = thread
        thread.start()

    def _supervise(self, direction: Direction) -> None:
        with self._lock:
            stop = self._stops[direction.label]
        try:
            direction.run(stop)
        except BaseException as exc:  # isolate one direction's failure from the rest
            with self._lock:
                self._failures[direction.label] = exc
            self._on_warning(
                f"[{direction.label}] direction ended early: {exc}. Other "
                "directions continue unaffected. Restart only this direction "
                "to resume it -- that does not require restarting the session."
            )
            # Release this direction's resources (e.g. a resident Piper
            # process) promptly rather than leaving them held until the whole
            # session ends, since the healthy direction may keep running
            # indefinitely and a restart needs them released first anyway.
            self._close_direction(direction.label, direction)
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

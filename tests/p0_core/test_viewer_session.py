import unittest
from datetime import datetime, timedelta, timezone

from src.p0_core.viewer_session import (
    SessionState,
    new_snapshot,
    on_tick,
    on_viewer_join,
    on_viewer_leave,
)


class ViewerSessionStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)

    def test_join_from_stopped_enters_resuming(self) -> None:
        snapshot = new_snapshot(self.t0)
        result = on_viewer_join(snapshot, self.t0)

        self.assertEqual(SessionState.RESUMING, result.state)
        self.assertEqual(1, result.viewer_count)
        self.assertEqual(self.t0 + timedelta(seconds=5), result.resume_deadline)

    def test_resuming_transitions_to_active_after_warmup(self) -> None:
        snapshot = on_viewer_join(new_snapshot(self.t0), self.t0)

        result = on_tick(snapshot, self.t0 + timedelta(seconds=6))

        self.assertEqual(SessionState.ACTIVE, result.state)
        self.assertEqual(1, result.viewer_count)

    def test_leave_to_zero_enters_idle_pending(self) -> None:
        snapshot = on_tick(on_viewer_join(new_snapshot(self.t0), self.t0), self.t0 + timedelta(seconds=6))

        result = on_viewer_leave(snapshot, self.t0 + timedelta(seconds=8))

        self.assertEqual(SessionState.IDLE_PENDING, result.state)
        self.assertEqual(0, result.viewer_count)
        self.assertEqual(self.t0 + timedelta(seconds=38), result.idle_deadline)

    def test_idle_pending_times_out_to_stopped(self) -> None:
        active = on_tick(on_viewer_join(new_snapshot(self.t0), self.t0), self.t0 + timedelta(seconds=6))
        idle = on_viewer_leave(active, self.t0 + timedelta(seconds=8))

        result = on_tick(idle, self.t0 + timedelta(seconds=40))

        self.assertEqual(SessionState.STOPPED, result.state)
        self.assertEqual(0, result.viewer_count)

    def test_join_during_idle_pending_returns_active(self) -> None:
        active = on_tick(on_viewer_join(new_snapshot(self.t0), self.t0), self.t0 + timedelta(seconds=6))
        idle = on_viewer_leave(active, self.t0 + timedelta(seconds=8))

        result = on_viewer_join(idle, self.t0 + timedelta(seconds=10))

        self.assertEqual(SessionState.ACTIVE, result.state)
        self.assertEqual(1, result.viewer_count)


if __name__ == "__main__":
    unittest.main()

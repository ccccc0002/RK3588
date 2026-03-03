import unittest
from datetime import datetime, timedelta, timezone

from src.p0_core.event_center import (
    initial_event_state,
    normalize_raw_event,
    process_event,
)


class EventCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.raw = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "source_id": "camera-1",
            "event_type": "line_crossing",
            "object_id": "person-1",
            "payload": {"confidence": 0.87},
        }

    def test_duplicate_within_window_is_rejected(self) -> None:
        state = initial_event_state()
        event = normalize_raw_event(self.raw, occurred_at=self.now)

        state2, accepted1 = process_event(state, event, now=self.now)
        _, accepted2 = process_event(state2, event, now=self.now + timedelta(seconds=10))

        self.assertTrue(accepted1)
        self.assertFalse(accepted2)

    def test_same_event_after_window_is_accepted(self) -> None:
        state = initial_event_state()
        event = normalize_raw_event(self.raw, occurred_at=self.now)

        state2, _ = process_event(state, event, now=self.now)
        _, accepted = process_event(state2, event, now=self.now + timedelta(seconds=65))

        self.assertTrue(accepted)

    def test_tenant_site_box_are_part_of_dedupe_scope(self) -> None:
        state = initial_event_state()
        e1 = normalize_raw_event(self.raw, occurred_at=self.now)
        raw2 = dict(self.raw)
        raw2["box_id"] = "b2"
        e2 = normalize_raw_event(raw2, occurred_at=self.now)

        state2, accepted1 = process_event(state, e1, now=self.now)
        _, accepted2 = process_event(state2, e2, now=self.now + timedelta(seconds=1))

        self.assertTrue(accepted1)
        self.assertTrue(accepted2)


if __name__ == "__main__":
    unittest.main()

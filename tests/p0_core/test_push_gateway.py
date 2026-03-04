import unittest
from datetime import datetime, timedelta, timezone

from src.p0_core.push_gateway import (
    initial_push_state,
    enqueue_push,
    due_tasks,
    mark_delivery_result,
)


class PushGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)

    def test_enqueue_with_same_idempotency_key_is_deduplicated(self) -> None:
        state = initial_push_state()
        state = enqueue_push(
            state,
            idempotency_key="evt-1",
            target_url="https://example.com/hook",
            bearer_token="token",
            payload={"id": "evt-1"},
            now=self.now,
        )
        state = enqueue_push(
            state,
            idempotency_key="evt-1",
            target_url="https://example.com/hook",
            bearer_token="token",
            payload={"id": "evt-1"},
            now=self.now,
        )

        self.assertEqual(1, len(state.tasks))

    def test_failed_tasks_move_to_dead_letter_after_max_retries(self) -> None:
        state = initial_push_state()
        state = enqueue_push(
            state,
            idempotency_key="evt-2",
            target_url="https://example.com/hook",
            bearer_token="token",
            payload={"id": "evt-2"},
            now=self.now,
        )
        task_id = state.tasks[0].task_id

        s1 = mark_delivery_result(state, task_id=task_id, success=False, now=self.now)
        s2 = mark_delivery_result(s1, task_id=task_id, success=False, now=self.now + timedelta(seconds=2))
        s3 = mark_delivery_result(s2, task_id=task_id, success=False, now=self.now + timedelta(seconds=6))

        self.assertEqual(0, len(s3.tasks))
        self.assertEqual(1, len(s3.dead_letters))

    def test_due_tasks_returns_only_ready_items(self) -> None:
        state = initial_push_state()
        state = enqueue_push(
            state,
            idempotency_key="evt-3",
            target_url="https://example.com/hook",
            bearer_token="token",
            payload={"id": "evt-3"},
            now=self.now,
        )

        self.assertEqual(1, len(due_tasks(state, now=self.now)))

    def test_force_dead_letter_short_circuits_retry(self) -> None:
        state = initial_push_state()
        state = enqueue_push(
            state,
            idempotency_key="evt-4",
            target_url="https://blocked.example.com/hook",
            bearer_token="token",
            payload={"id": "evt-4"},
            now=self.now,
        )
        task_id = state.tasks[0].task_id

        updated = mark_delivery_result(
            state,
            task_id=task_id,
            success=False,
            now=self.now,
            force_dead_letter=True,
            failure_reason="delivery_failed_policy_denied",
        )

        self.assertEqual(0, len(updated.tasks))
        self.assertEqual(1, len(updated.dead_letters))
        self.assertEqual("delivery_failed_policy_denied", updated.dead_letters[0].last_error)
        self.assertEqual(1, updated.dead_letters[0].attempt_count)


if __name__ == "__main__":
    unittest.main()

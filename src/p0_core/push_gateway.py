from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json


@dataclass(frozen=True)
class PushTask:
    task_id: str
    idempotency_key: str
    target_url: str
    bearer_token: str
    payload: dict
    attempt_count: int
    next_attempt_at: datetime
    last_error: str | None = None


@dataclass(frozen=True)
class PushState:
    tasks: tuple[PushTask, ...]
    dead_letters: tuple[PushTask, ...]


def initial_push_state() -> PushState:
    return PushState(tasks=tuple(), dead_letters=tuple())


def _task_id_for(idempotency_key: str, target_url: str) -> str:
    seed = f"{idempotency_key}:{target_url}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def enqueue_push(
    state: PushState,
    idempotency_key: str,
    target_url: str,
    bearer_token: str,
    payload: dict,
    now: datetime,
) -> PushState:
    has_existing = any(task.idempotency_key == idempotency_key for task in state.tasks) or any(
        task.idempotency_key == idempotency_key for task in state.dead_letters
    )
    if has_existing:
        return state

    serialized_payload = json.loads(json.dumps(payload))
    task = PushTask(
        task_id=_task_id_for(idempotency_key, target_url),
        idempotency_key=idempotency_key,
        target_url=target_url,
        bearer_token=bearer_token,
        payload=serialized_payload,
        attempt_count=0,
        next_attempt_at=now,
    )

    return PushState(tasks=state.tasks + (task,), dead_letters=state.dead_letters)


def due_tasks(state: PushState, now: datetime) -> tuple[PushTask, ...]:
    return tuple(task for task in state.tasks if task.next_attempt_at <= now)


def mark_delivery_result(
    state: PushState,
    task_id: str,
    success: bool,
    now: datetime,
    max_retries: int = 3,
) -> PushState:
    target = next((item for item in state.tasks if item.task_id == task_id), None)
    if target is None:
        return state

    remaining = tuple(item for item in state.tasks if item.task_id != task_id)
    if success:
        return PushState(tasks=remaining, dead_letters=state.dead_letters)

    attempts = target.attempt_count + 1
    if attempts >= max_retries:
        dead = PushTask(
            task_id=target.task_id,
            idempotency_key=target.idempotency_key,
            target_url=target.target_url,
            bearer_token=target.bearer_token,
            payload=target.payload,
            attempt_count=attempts,
            next_attempt_at=now,
            last_error="delivery_failed_max_retries",
        )
        return PushState(tasks=remaining, dead_letters=state.dead_letters + (dead,))

    updated = PushTask(
        task_id=target.task_id,
        idempotency_key=target.idempotency_key,
        target_url=target.target_url,
        bearer_token=target.bearer_token,
        payload=target.payload,
        attempt_count=attempts,
        next_attempt_at=now + timedelta(seconds=2**attempts),
        last_error="delivery_failed_retrying",
    )
    return PushState(tasks=remaining + (updated,), dead_letters=state.dead_letters)

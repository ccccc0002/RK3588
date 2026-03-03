from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class SessionState(str, Enum):
    ACTIVE = "ACTIVE"
    IDLE_PENDING = "IDLE_PENDING"
    STOPPED = "STOPPED"
    RESUMING = "RESUMING"


@dataclass(frozen=True)
class SessionSnapshot:
    state: SessionState
    viewer_count: int
    last_transition_at: datetime
    idle_deadline: datetime | None = None
    resume_deadline: datetime | None = None


def new_snapshot(at: datetime) -> SessionSnapshot:
    return SessionSnapshot(state=SessionState.STOPPED, viewer_count=0, last_transition_at=at)


def on_viewer_join(
    snapshot: SessionSnapshot,
    at: datetime,
    resume_warmup_seconds: int = 5,
) -> SessionSnapshot:
    count = snapshot.viewer_count + 1
    if snapshot.state == SessionState.STOPPED:
        return SessionSnapshot(
            state=SessionState.RESUMING,
            viewer_count=count,
            last_transition_at=at,
            resume_deadline=at + timedelta(seconds=resume_warmup_seconds),
        )

    if snapshot.state in (SessionState.IDLE_PENDING, SessionState.ACTIVE):
        return SessionSnapshot(
            state=SessionState.ACTIVE,
            viewer_count=count,
            last_transition_at=at,
        )

    return SessionSnapshot(
        state=SessionState.RESUMING,
        viewer_count=count,
        last_transition_at=snapshot.last_transition_at,
        resume_deadline=snapshot.resume_deadline,
    )


def on_viewer_leave(
    snapshot: SessionSnapshot,
    at: datetime,
    idle_timeout_seconds: int = 30,
) -> SessionSnapshot:
    if snapshot.viewer_count == 0:
        return snapshot

    count = snapshot.viewer_count - 1
    if count == 0 and snapshot.state != SessionState.STOPPED:
        return SessionSnapshot(
            state=SessionState.IDLE_PENDING,
            viewer_count=0,
            last_transition_at=at,
            idle_deadline=at + timedelta(seconds=idle_timeout_seconds),
        )

    return SessionSnapshot(
        state=snapshot.state,
        viewer_count=count,
        last_transition_at=snapshot.last_transition_at,
        idle_deadline=snapshot.idle_deadline,
        resume_deadline=snapshot.resume_deadline,
    )


def on_tick(snapshot: SessionSnapshot, at: datetime) -> SessionSnapshot:
    if snapshot.state == SessionState.RESUMING and snapshot.resume_deadline and at >= snapshot.resume_deadline:
        return SessionSnapshot(
            state=SessionState.ACTIVE,
            viewer_count=snapshot.viewer_count,
            last_transition_at=at,
        )

    if (
        snapshot.state == SessionState.IDLE_PENDING
        and snapshot.idle_deadline
        and at >= snapshot.idle_deadline
        and snapshot.viewer_count == 0
    ):
        return SessionSnapshot(
            state=SessionState.STOPPED,
            viewer_count=0,
            last_transition_at=at,
        )

    return snapshot

from dataclasses import dataclass


@dataclass(frozen=True)
class StreamLoad:
    stream_id: str
    fps_in: float
    complexity: float
    priority: int


@dataclass(frozen=True)
class StreamPlan:
    stream_id: str
    sample_fps: float
    estimated_cost: float


@dataclass(frozen=True)
class SchedulePlan:
    streams: tuple[StreamPlan, ...]
    degraded: bool
    total_cost: float


def _target_fps(stream: StreamLoad) -> float:
    return min(8.0, max(1.0, stream.fps_in))


def _priority_factor(priority: int) -> float:
    if priority >= 3:
        return 1.2
    if priority == 2:
        return 1.0
    return 0.8


def _min_fps(priority: int) -> float:
    if priority >= 3:
        return 3.0
    if priority == 2:
        return 2.0
    return 1.0


def build_schedule(
    streams: tuple[StreamLoad, ...],
    budget: float,
    previous: SchedulePlan | None = None,
) -> SchedulePlan:
    if not streams:
        return SchedulePlan(streams=tuple(), degraded=False, total_cost=0.0)

    targets: dict[str, float] = {item.stream_id: _target_fps(item) for item in streams}
    target_cost = sum(targets[item.stream_id] * item.complexity for item in streams)
    degraded = target_cost > budget

    prev_map: dict[str, StreamPlan] = {}
    if previous:
        prev_map = {item.stream_id: item for item in previous.streams}

    plans: list[StreamPlan] = []
    if not degraded:
        for item in streams:
            proposed = targets[item.stream_id]
            prev = prev_map.get(item.stream_id)
            if prev:
                proposed = min(proposed, prev.sample_fps + 4.0)
            plans.append(
                StreamPlan(
                    stream_id=item.stream_id,
                    sample_fps=round(proposed, 2),
                    estimated_cost=round(proposed * item.complexity, 2),
                )
            )
        total_cost = sum(item.estimated_cost for item in plans)
        return SchedulePlan(streams=tuple(plans), degraded=False, total_cost=round(total_cost, 2))

    scale = max(0.1, budget / max(0.001, target_cost))
    for item in streams:
        target = targets[item.stream_id]
        fps = target * scale * _priority_factor(item.priority)
        fps = min(target, max(_min_fps(item.priority), fps))
        plans.append(
            StreamPlan(
                stream_id=item.stream_id,
                sample_fps=round(fps, 2),
                estimated_cost=round(fps * item.complexity, 2),
            )
        )

    total_cost = sum(item.estimated_cost for item in plans)
    return SchedulePlan(streams=tuple(plans), degraded=True, total_cost=round(total_cost, 2))

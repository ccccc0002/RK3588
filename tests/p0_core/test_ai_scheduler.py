import unittest

from src.p0_core.ai_scheduler import StreamLoad, build_schedule


class AiSchedulerTests(unittest.TestCase):
    def test_within_budget_no_degradation(self) -> None:
        streams = (
            StreamLoad(stream_id="cam-1", fps_in=15.0, complexity=1.0, priority=3),
            StreamLoad(stream_id="cam-2", fps_in=12.0, complexity=1.2, priority=2),
        )

        plan = build_schedule(streams, budget=40.0)

        self.assertFalse(plan.degraded)
        self.assertGreaterEqual(plan.total_cost, 0.0)
        self.assertEqual(2, len(plan.streams))

    def test_overload_degrades_lower_priority_more(self) -> None:
        streams = (
            StreamLoad(stream_id="high", fps_in=20.0, complexity=1.5, priority=3),
            StreamLoad(stream_id="low", fps_in=20.0, complexity=1.5, priority=1),
        )

        plan = build_schedule(streams, budget=12.0)
        high = next(item for item in plan.streams if item.stream_id == "high")
        low = next(item for item in plan.streams if item.stream_id == "low")

        self.assertTrue(plan.degraded)
        self.assertGreaterEqual(high.sample_fps, low.sample_fps)

    def test_recovery_increases_fps_when_budget_recovers(self) -> None:
        streams = (
            StreamLoad(stream_id="cam-1", fps_in=20.0, complexity=1.2, priority=2),
        )

        degraded = build_schedule(streams, budget=3.0)
        recovered = build_schedule(streams, budget=20.0, previous=degraded)

        self.assertGreaterEqual(recovered.streams[0].sample_fps, degraded.streams[0].sample_fps)
        self.assertLessEqual(recovered.streams[0].sample_fps, 8.0)


if __name__ == "__main__":
    unittest.main()

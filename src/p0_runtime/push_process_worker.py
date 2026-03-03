from __future__ import annotations

import argparse
import time
from typing import Dict

from src.p0_runtime.dispatch_client import dispatch_once


class PushProcessWorker:
    def __init__(
        self,
        base_url: str,
        interval_seconds: float = 0.5,
        limit: int = 20,
        mode: str = "real",
        max_iterations: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.interval_seconds = float(interval_seconds)
        self.limit = int(limit)
        self.mode = str(mode)
        self.max_iterations = max_iterations

    def run_forever(self) -> Dict[str, int]:
        iterations = 0
        sent = 0
        failed = 0
        processed = 0

        while True:
            if self.max_iterations is not None and iterations >= self.max_iterations:
                break
            iterations += 1

            result = dispatch_once(self.base_url, limit=self.limit, mode=self.mode)
            sent += int(result.get("sent", 0))
            failed += int(result.get("failed", 0))
            processed += int(result.get("processed", 0))

            time.sleep(self.interval_seconds)

        return {
            "iterations": iterations,
            "sent": sent,
            "failed": failed,
            "processed": processed,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone push dispatch worker process")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mode", default="real", choices=["real", "always_success", "always_fail"])
    parser.add_argument("--max-iterations", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_iterations = args.max_iterations if args.max_iterations > 0 else None
    worker = PushProcessWorker(
        base_url=args.base_url,
        interval_seconds=max(0.01, args.interval_ms / 1000.0),
        limit=args.limit,
        mode=args.mode,
        max_iterations=max_iterations,
    )
    result = worker.run_forever()
    print(result)


if __name__ == "__main__":
    main()

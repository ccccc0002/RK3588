#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch RK3588 inference plan from the Python runtime")
    parser.add_argument("--runtime-url", required=True, help="Runtime endpoint root, e.g. http://127.0.0.1:18080")
    parser.add_argument("--budget", type=float, default=10.0, help="Scheduling budget passed to /api/v1/inference/plan")
    parser.add_argument("--token", default="", help="Bearer token for the runtime API")
    parser.add_argument("--output", required=True, help="Where to write the fetched JSON plan")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    body = json.dumps({"budget": float(args.budget)}).encode("utf-8")
    url = args.runtime_url.rstrip("/") + "/api/v1/inference/plan"
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    request = Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        sys.stderr.write(f"HTTP error {exc.code} while fetching {url}\n")
        sys.stderr.write(exc.read().decode("utf-8", "ignore") + "\n")
        return 1
    except URLError as exc:
        sys.stderr.write(f"Network error while fetching {url}: {exc}\n")
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    stream_count = data.get("stream_count")
    ready_stream_count = data.get("ready_stream_count")
    total_cost = data.get("total_cost")
    print(f"saved={output_path}")
    print(f"stream_count={stream_count}")
    print(f"ready_stream_count={ready_stream_count}")
    print(f"total_cost={total_cost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

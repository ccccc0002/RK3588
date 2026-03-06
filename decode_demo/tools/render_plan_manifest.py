#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render inference-plan JSON into a TSV manifest for rk_decode_demo")
    parser.add_argument("--input", required=True, help="Path to fetched inference-plan JSON")
    parser.add_argument("--output", required=True, help="Path to write the TSV manifest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    lines = ["# rk_decode_demo_manifest\tv1"]
    for key in ("budget", "degraded", "total_cost", "stream_count", "ready_stream_count"):
        value = data.get(key, "")
        lines.append(f"meta\t{key}\t{value}")

    for stream in data.get("streams", []):
        for workload in stream.get("workloads", []):
            parts = [
                "workload",
                str(stream.get("tenant_id", "")),
                str(stream.get("site_id", "")),
                str(stream.get("box_id", "")),
                str(stream.get("device_id", "")),
                str(stream.get("protocol", "")),
                str(stream.get("stream_url", "")),
                str(stream.get("fps_in", "")),
                str(stream.get("sample_fps", "")),
                str(stream.get("estimated_cost", "")),
                str(stream.get("priority", "")),
                str(stream.get("complexity", "")),
                str(workload.get("capability", "")),
                str(workload.get("algorithm_id", "") or ""),
                str(workload.get("algorithm_version", "") or ""),
                str(workload.get("base_library_id", "") or ""),
                str(workload.get("base_library_version", "") or ""),
                str(workload.get("binding_status", "")),
            ]
            lines.append("\t".join(parts))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved={output_path}")
    print(f"lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


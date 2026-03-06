#!/usr/bin/env python3
import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a decode_demo execution asset map TSV")
    parser.add_argument("--output", required=True, help="Output TSV path")
    parser.add_argument("--device-id", default="", help="Optional device_id match")
    parser.add_argument("--capability", default="", help="Optional capability match")
    parser.add_argument("--algorithm-id", default="", help="Optional algorithm_id match")
    parser.add_argument("--algorithm-version", default="", help="Optional algorithm_version match")
    parser.add_argument("--base-library-id", default="", help="Optional base_library_id match")
    parser.add_argument("--base-library-version", default="", help="Optional base_library_version match")
    parser.add_argument("--stream-path", required=True, help="Resolved local stream path for decode_demo")
    parser.add_argument("--model-path", required=True, help="Resolved local RKNN model path")
    parser.add_argument("--result-path", default="", help="Optional output result JSON path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# rk_decode_demo_asset_map\tv1",
        "# type\ttenant_id\tsite_id\tbox_id\tdevice_id\tcapability\talgorithm_id\talgorithm_version\tbase_library_id\tbase_library_version\tstream_path\tmodel_path\toutput_path",
        "\t".join(
            [
                "binding",
                "",
                "",
                "",
                args.device_id,
                args.capability,
                args.algorithm_id,
                args.algorithm_version,
                args.base_library_id,
                args.base_library_version,
                args.stream_path,
                args.model_path,
                args.result_path,
            ]
        ),
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

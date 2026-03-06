#!/usr/bin/env python3
import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = (
    "https://raw.githubusercontent.com/airockchip/rknn-toolkit2/master/"
    "rknpu2/examples/rknn_yolov5_demo/model/RK3588/yolov5s-640-640.rknn"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a sample RKNN model for RK3588 inference probing")
    parser.add_argument("--output", required=True, help="Destination .rknn path")
    parser.add_argument("--url", default=DEFAULT_URL, help="Raw model URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(args.url) as response:
        data = response.read()
    output.write_bytes(data)
    print(f"saved={output}")
    print(f"bytes={len(data)}")
    print(f"url={args.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

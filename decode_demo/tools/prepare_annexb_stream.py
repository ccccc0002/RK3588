#!/usr/bin/env python3
import argparse
import shutil
import subprocess
from pathlib import Path
from typing import List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare an Annex-B elementary stream for MPP decode testing")
    parser.add_argument("--input", required=True, help="Input video file, e.g. preview-clip.mp4")
    parser.add_argument("--output", required=True, help="Output elementary stream path, e.g. sample.h264")
    return parser.parse_args()


def run_cmd(cmd: List[str]) -> int:
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def main() -> int:
    args = parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg not found in PATH")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    copy_cmd = [
        ffmpeg,
        "-y",
        "-i",
        args.input,
        "-an",
        "-c:v",
        "copy",
        "-bsf:v",
        "h264_mp4toannexb",
        str(output),
    ]
    if run_cmd(copy_cmd) == 0 and output.exists() and output.stat().st_size > 0:
        print(f"saved={output}")
        print("mode=copy")
        return 0

    transcode_cmd = [
        ffmpeg,
        "-y",
        "-i",
        args.input,
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "h264",
        str(output),
    ]
    if run_cmd(transcode_cmd) != 0 or not output.exists() or output.stat().st_size == 0:
        raise SystemExit(1)

    print(f"saved={output}")
    print("mode=transcode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

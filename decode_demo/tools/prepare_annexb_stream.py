#!/usr/bin/env python3
import argparse
import shutil
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare an Annex-B elementary stream for MPP decode testing")
    parser.add_argument("--input", required=True, help="Input video file, e.g. preview-clip.mp4")
    parser.add_argument("--output", required=True, help="Output elementary stream path, e.g. sample.h264")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg not found in PATH")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
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
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    print(f"saved={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

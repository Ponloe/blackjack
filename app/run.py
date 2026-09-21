"""Optional recorded-video launch: python -m app.run --video practice.mp4."""

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local blackjack dashboard")
    parser.add_argument("--video", type=Path, help="Use a local video instead of the OpenCV webcam")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.video:
        if not args.video.is_file():
            parser.error("--video must point to an existing local video file")
        os.environ["BLACKJACK_VIDEO"] = str(args.video.resolve())
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

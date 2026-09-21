"""Single-owner OpenCV capture thread with condition-driven JPEG delivery."""

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

import cv2

from vision.detector import Frame, draw_detections


class Capture(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Frame | None]: ...
    def release(self) -> None: ...
    def get(self, property_id: int) -> float: ...
    def set(self, property_id: int, value: float) -> bool: ...


class Camera:
    def __init__(
        self,
        on_status: Callable[[dict[str, Any]], None] | None = None,
        video: str | None = None,
        capture_factory: Callable[[int | str], Capture] = cv2.VideoCapture,
    ) -> None:
        if video is not None and not Path(video).is_file():
            raise ValueError("Video source must be an existing local file")
        self.video = video
        self._factory = capture_factory
        self._on_status = on_status
        self._condition = threading.Condition(threading.RLock())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self._sequence = 0
        self._status = "stopped"
        self._message = "Camera is off"

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {"status": self._status, "message": self._message, "video_file": self.video is not None}

    def _change(self, status: str, message: str) -> None:
        with self._condition:
            self._status, self._message = status, message
            self._condition.notify_all()
        if self._on_status is not None:
            self._on_status(self.status())

    def start(self, index: int = 0) -> dict[str, Any]:
        if type(index) is not int or not 0 <= index <= 10:
            raise ValueError("Camera index must be between 0 and 10")
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                if self._status in ("starting", "running"):
                    return self.status()
                raise ValueError("The camera is still stopping; wait before restarting")
            self._stop.clear()
            self._jpeg = None
            self._change("starting", "Opening webcam; operating-system permission may be required")
            self._thread = threading.Thread(target=self._capture, args=(index,), name="blackjack-camera", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        if thread is not None and thread.is_alive():
            self._change("stopping", "Waiting for the camera driver to finish")
        else:
            self._change("stopped", "Camera is off")
        return self.status()

    def _capture(self, index: int) -> None:
        capture: Capture | None = None
        try:
            capture = self._factory(self.video if self.video is not None else index)
            if not capture.isOpened():
                self._change("error", "Could not open webcam. Allow camera access for the terminal running Python, close other camera apps, or try Browser webcam.")
                return
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            fps = capture.get(cv2.CAP_PROP_FPS)
            interval = 1 / (fps if 1 <= fps <= 120 and self.video is not None else 20)
            first = True
            while not self._stop.is_set():
                began = time.monotonic()
                ok, frame = capture.read()
                if not ok or frame is None:
                    status = "ended" if self.video is not None else "error"
                    message = "Recorded video finished. Start again to replay." if self.video is not None else "Webcam stopped delivering frames. Check the connection and camera permission."
                    self._change(status, message)
                    break
                if frame.shape[1] > 1280:
                    frame = cv2.resize(frame, (1280, round(frame.shape[0] * 1280 / frame.shape[1])))
                encoded, jpeg = cv2.imencode(".jpg", draw_detections(frame), [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not encoded:
                    raise RuntimeError("Could not encode the camera frame")
                with self._condition:
                    self._jpeg = jpeg.tobytes()
                    self._sequence += 1
                    self._condition.notify_all()
                if first:
                    first = False
                    self._change("running", "Camera preview is live")
                self._stop.wait(max(0, interval - (time.monotonic() - began)))
        except Exception:
            self._change("error", "Camera capture failed. Try Browser webcam or restart the preview.")
        finally:
            if capture is not None:
                capture.release()
            if self._stop.is_set():
                self._change("stopped", "Camera is off")

    def frames(self) -> Iterator[bytes]:
        sequence = -1
        while not self._stop.is_set():
            with self._condition:
                self._condition.wait_for(
                    lambda: (self._jpeg is not None and self._sequence != sequence) or self._status not in ("starting", "running"), timeout=1,
                )
                if self._status not in ("starting", "running"):
                    return
                jpeg = self._jpeg
                latest = self._sequence
            if jpeg is not None and latest != sequence:
                sequence = latest
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"

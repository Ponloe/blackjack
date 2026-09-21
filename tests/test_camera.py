import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app
from vision.camera import Camera
from vision.detector import Frame, detect_cards


class FakeCapture:
    def __init__(self, opened: bool = True) -> None:
        self.opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, Frame]:
        return True, np.zeros((240, 320, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True

    def get(self, property_id: int) -> float:
        return 20.0

    def set(self, property_id: int, value: float) -> bool:
        return True


def test_capture_lifecycle_and_mjpeg() -> None:
    ready = threading.Event()
    capture = FakeCapture()

    def changed(state: dict[str, Any]) -> None:
        if state["status"] == "running":
            ready.set()

    camera = Camera(on_status=changed, capture_factory=lambda index: capture)
    assert camera.status()["status"] == "stopped"
    try:
        camera.start()
        assert ready.wait(3)
        chunk = next(camera.frames())
        assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg")
        assert b"\xff\xd8" in chunk
        assert camera.start()["status"] == "running"
    finally:
        camera.stop()
    assert capture.released
    assert camera.status()["status"] == "stopped"
    assert list(camera.frames()) == []


def test_unavailable_camera_reports_error_and_releases() -> None:
    failed = threading.Event()
    capture = FakeCapture(opened=False)
    camera = Camera(on_status=lambda status: failed.set() if status["status"] == "error" else None, capture_factory=lambda index: capture)
    camera.start()
    assert failed.wait(3)
    assert "Allow camera access" in camera.status()["message"]
    assert camera.status()["status"] == "error"
    camera.stop()
    assert capture.released


def test_card_shape_detection_and_warp() -> None:
    image = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(image, (280, 120), (480, 420), (255, 255, 255), -1)
    detections = detect_cards(image)
    assert len(detections) == 1
    assert detections[0].warped.shape == (300, 200, 3)
    assert len(detect_cards(np.zeros_like(image))) == 0


def test_recorded_video_uses_real_opencv(tmp_path: Path) -> None:
    path = tmp_path / "practice.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (320, 240))
    assert writer.isOpened()
    for _ in range(5):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (110, 30), (210, 180), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    ready, ended = threading.Event(), threading.Event()

    def changed(status: dict[str, Any]) -> None:
        if status["status"] == "running":
            ready.set()
        if status["status"] == "ended":
            ended.set()

    camera = Camera(on_status=changed, video=str(path))
    try:
        camera.start()
        assert ready.wait(3)
        assert b"image/jpeg" in next(camera.frames())
        assert ended.wait(3)
        assert camera.status()["status"] == "ended"
    finally:
        camera.stop()


def test_camera_routes_never_auto_start_and_broadcast_status() -> None:
    capture = FakeCapture()

    def factory(**kwargs: Any) -> Camera:
        return Camera(**kwargs, capture_factory=lambda index: capture)

    with TestClient(create_app(":memory:", camera_factory=factory), base_url="http://localhost") as client:
        assert client.get("/video_feed").status_code == 503
        with client.websocket_connect("ws://localhost/ws") as ws:
            assert ws.receive_json()["camera"]["status"] == "stopped"
            assert client.post("/api/camera/start", json={"index": -1}).status_code == 422
            assert client.post("/api/camera/start", json={"index": 0}).status_code == 200
            status = ws.receive_json()["camera"]["status"]
            if status == "starting":
                status = ws.receive_json()["camera"]["status"]
            assert status == "running"
            assert client.get("/api/session/state").json()["cards_seen"] == 0
            assert client.post("/api/camera/stop").status_code == 200
        assert capture.released

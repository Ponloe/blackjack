"""Start locally with uvicorn app.main:app (one worker)."""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.routes import router
from app.session import Session
from vision.camera import Camera

ROOT = Path(__file__).resolve().parent.parent


class Service:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lock = asyncio.Lock()
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.camera: Camera | None = None

    def snapshot(self) -> dict[str, Any]:
        return {**self.session.state(), "camera": self.camera.status() if self.camera else {"status": "stopped"}}

    async def camera_changed(self) -> None:
        async with self.lock:
            self.publish(self.snapshot())

    async def mutate(self, mutation: Callable[[], None]) -> dict[str, Any]:
        async with self.lock:
            mutation()
            state = self.snapshot()
            self.publish(state)
            return state

    def publish(self, state: dict[str, Any]) -> None:
        # A slow tab receives the latest full state without blocking other tabs.
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(state)


def same_origin(origin: str | None, host: str | None) -> bool:
    return origin is None or (urlsplit(origin).scheme in ("http", "https") and urlsplit(origin).netloc == host)


class CameraInput(BaseModel):
    index: int = Field(default=0, ge=0, le=10, strict=True)


def create_app(database: str | Path | None = None, camera_factory: Callable[..., Camera] = Camera) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        session = Session(database or os.environ.get("BLACKJACK_DB", str(ROOT / "data" / "session.sqlite3")))
        service = Service(session)
        application.state.service = service
        loop = asyncio.get_running_loop()
        closing = False

        def camera_changed(status: dict[str, Any]) -> None:
            if not closing and not loop.is_closed():
                loop.call_soon_threadsafe(lambda: asyncio.create_task(service.camera_changed()) if not closing else None)

        service.camera = camera_factory(on_status=camera_changed, video=os.environ.get("BLACKJACK_VIDEO"))
        try:
            yield
        finally:
            closing = True
            await asyncio.to_thread(service.camera.stop)
            session.close()

    application = FastAPI(title="Count Lab · Blackjack Trainer", lifespan=lifespan)
    allowed_hosts = ["localhost", "127.0.0.1", "[::1]"]
    allowed_hosts += [host.strip() for host in os.environ.get("BLACKJACK_ALLOWED_HOSTS", "").split(",") if host.strip()]
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @application.middleware("http")
    async def local_requests(request: Request, call_next: Callable[..., Any]) -> Any:
        if not same_origin(request.headers.get("origin"), request.headers.get("host")):
            return JSONResponse({"detail": "Origin does not match host"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @application.exception_handler(ValueError)
    async def invalid_operation(request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    application.include_router(router)

    @application.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready")
    async def ready(request: Request) -> dict[str, str]:
        request.app.state.service.session.connection.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @application.post("/api/camera/start")
    async def camera_start(body: CameraInput, request: Request) -> dict[str, Any]:
        return request.app.state.service.camera.start(body.index)

    @application.post("/api/camera/stop")
    async def camera_stop(request: Request) -> dict[str, Any]:
        return await asyncio.to_thread(request.app.state.service.camera.stop)

    @application.get("/video_feed")
    async def video_feed(request: Request) -> Any:
        camera = request.app.state.service.camera
        if camera.status()["status"] not in ("starting", "running"):
            return JSONResponse({"detail": "Start the OpenCV camera from the dashboard first"}, status_code=503)
        return StreamingResponse(camera.frames(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})
    web = ROOT / "web"
    if web.exists():
        application.mount("/static", StaticFiles(directory=web), name="static")

    @application.get("/", response_class=FileResponse)
    async def index() -> FileResponse:
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-cache"})

    @application.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        if not same_origin(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        service: Service = websocket.app.state.service
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        async with service.lock:
            service.subscribers.add(queue)
            queue.put_nowait(service.snapshot())

        async def send() -> None:
            while True:
                await websocket.send_json(await queue.get())

        async def receive() -> None:
            while True:
                await websocket.receive_text()

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            service.subscribers.discard(queue)
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task

    return application


app = create_app()

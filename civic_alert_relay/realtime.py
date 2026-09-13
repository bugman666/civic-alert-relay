"""Long-lived WebSocket so dashboards can follow the live event feed.

Ingest publishes first-seen events here in-process, alongside Redis /
webhook / Telegram fan-out. The WebSocket path does not re-subscribe
from Redis.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

log = logging.getLogger(__name__)

STATUS = "ok"
WS_PATH = "/ws/events"
_QUEUE_MAX = 64

_hub: EventHub | None = None


class EventHub:
    """In-process broadcast to connected WebSocket clients."""

    def __init__(self) -> None:
        self._queues: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_id = 0

    @property
    def client_count(self) -> int:
        return len(self._queues)

    def snapshot(self) -> dict[str, Any]:
        """Client count and path, for ``GET /realtime/status``."""

        return {
            "path": WS_PATH,
            "clients": self.client_count,
        }

    def start(self) -> None:
        """Remember the process event loop so publish works from other threads."""

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def stop(self) -> None:
        self._queues.clear()
        self._loop = None

    def subscribe(self) -> tuple[int, asyncio.Queue[dict[str, Any]]]:
        self._next_id += 1
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._queues[self._next_id] = queue
        return self._next_id, queue

    def unsubscribe(self, ident: int) -> None:
        self._queues.pop(ident, None)

    def publish(self, event: object) -> None:
        """Queue ``event`` for every connected client. Safe from sync ingest."""

        payload = encode_event(event)
        loop = self._loop
        current = _current_loop()
        if loop is not None and loop.is_running() and loop is not current:
            loop.call_soon_threadsafe(self._enqueue, payload)
            return
        self._enqueue(payload)

    def _enqueue(self, payload: dict[str, Any]) -> None:
        for ident, queue in list(self._queues.items()):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("realtime: drop event for slow client %s", ident)


def configure(hub: EventHub | None) -> None:
    """Install the process-wide hub used by :func:`publish`."""

    global _hub
    _hub = hub


def publish(event: object) -> None:
    """Forward a newly seen event to connected WebSocket clients, if any."""

    hub = _hub
    if hub is None:
        return
    hub.publish(event)


def status() -> str:
    """Return the realtime subsystem state for ``/healthz``."""

    return STATUS


def log_ready() -> None:
    """Record that the WebSocket path is listening."""

    log.info("realtime: websocket %s", WS_PATH)


def hello_message() -> dict[str, Any]:
    """First frame sent after a client connects."""

    return {
        "type": "hello",
        "service": "civic-alert-relay",
        "path": WS_PATH,
    }


def encode_event(event: object) -> dict[str, Any]:
    """Wrap a normalized event as a WebSocket JSON frame."""

    if isinstance(event, BaseModel):
        body: Any = event.model_dump(mode="json")
    else:
        ident = getattr(event, "id", None)
        body = {"id": ident} if ident is not None else {"value": str(event)}
    return {"type": "event", "event": body}


async def handle_client(websocket: WebSocket, hub: EventHub) -> None:
    """Accept one client, send hello, then forward events until disconnect."""

    await websocket.accept()
    ident, outbound = hub.subscribe()
    log.info("realtime: client connected (%s)", hub.client_count)
    sender: asyncio.Task[None] | None = None
    receiver: asyncio.Task[None] | None = None
    try:
        await websocket.send_json(hello_message())
        sender = asyncio.create_task(_pump(websocket, outbound), name="ws-events-send")
        receiver = asyncio.create_task(_drain(websocket), name="ws-events-recv")
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            _log_task_error(task)
    except WebSocketDisconnect:
        pass
    finally:
        for task in (sender, receiver):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        hub.unsubscribe(ident)
        log.info("realtime: client disconnected (%s)", hub.client_count)


async def _pump(websocket: WebSocket, outbound: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        payload = await outbound.get()
        await websocket.send_json(payload)


async def _drain(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _log_task_error(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None or isinstance(exc, WebSocketDisconnect):
        return
    log.debug("realtime: client task ended: %s", exc)

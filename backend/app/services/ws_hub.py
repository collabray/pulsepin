"""
Real-time fan-out for the Emergency Dispatcher Dashboard (concept paper
Section 4.2). A single-process in-memory hub is sufficient for one backend
instance; `broadcast_*` also publishes to Redis pub/sub so the same events
reach dispatcher dashboards connected to *other* backend replicas behind a
load balancer — required for horizontal scaling in production.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

from app.services.otp_service import get_redis

logger = logging.getLogger("pulsepin.ws")

REDIS_CHANNEL_PREFIX = "pulsepin:dispatcher:"


class DispatcherHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._redis_listener_task: asyncio.Task | None = None

    async def connect(self, hospital_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.setdefault(hospital_id, set()).add(ws)
        await self._ensure_redis_listener()

    async def disconnect(self, hospital_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(hospital_id)
            if conns and ws in conns:
                conns.remove(ws)

    async def _send_local(self, hospital_id: str, message: dict) -> None:
        conns = self._connections.get(hospital_id, set())
        dead = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    async def _publish(self, hospital_id: str, message: dict) -> None:
        # Published to Redis only — the subscriber loop below (running in
        # every replica, including this one) delivers it to local
        # websocket connections. Sending locally here too would double-
        # deliver the event to clients connected to this replica.
        redis = await get_redis()
        await redis.publish(f"{REDIS_CHANNEL_PREFIX}{hospital_id}", json.dumps(message))

    async def broadcast_new_dispatch(self, hospital_id: str, dispatch_payload: dict) -> None:
        await self._publish(hospital_id, {"type": "new_dispatch", "data": dispatch_payload})

    async def broadcast_location_update(self, hospital_id: str, location_payload: dict) -> None:
        await self._publish(hospital_id, {"type": "location_update", "data": location_payload})

    async def broadcast_capability_update(self, hospital_id: str, capability_payload: dict) -> None:
        await self._publish(hospital_id, {"type": "capability_update", "data": capability_payload})

    async def broadcast_patient_tracking_update(self, dispatch_id: str, tracking_payload: dict) -> None:
        """
        Uber-style live tracking channel: keyed by dispatch_id (not
        hospital_id) and consumed by exactly one patient's app. Reuses the
        same connect/disconnect/_publish machinery with a distinct channel
        namespace so hospital-dispatcher and patient-tracking traffic never
        cross.
        """
        await self._publish(f"patient:{dispatch_id}", {"type": "tracking_update", "data": tracking_payload})

    async def _ensure_redis_listener(self) -> None:
        if self._redis_listener_task is not None:
            return
        self._redis_listener_task = asyncio.create_task(self._redis_listen_loop())

    async def _redis_listen_loop(self) -> None:
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.psubscribe(f"{REDIS_CHANNEL_PREFIX}*")
        try:
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                channel = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]
                hospital_id = channel.removeprefix(REDIS_CHANNEL_PREFIX)
                data = message["data"]
                payload = json.loads(data.decode() if isinstance(data, bytes) else data)
                await self._send_local(hospital_id, payload)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Redis pub/sub listener crashed; dispatcher real-time updates degraded.")


dispatcher_hub = DispatcherHub()

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from aiohttp import WSMsgType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class LarnitechConnectionError(Exception):
    pass


class LarnitechAuthError(Exception):
    pass


@dataclass
class DeviceInfo:
    addr: str
    type: str
    name: str
    area: str | None
    subType: str | None
    status: dict[str, Any] | None
    linked:  list[dict[str, Any]]
    automations:  list[str] | None

class LarnitechClient:
    """
    Один WS на entry:
    - authorize
    - get-devices (detailed)
    - status-subscribe per addr
    - push updates -> callbacks(addr, status)
    """

    def __init__(self, hass: HomeAssistant, url: str, api_key: str) -> None:
        self.hass = hass
        self.url = url
        self.api_key = api_key

        self._ws = None
        self._task: asyncio.Task | None = None
        self._rx_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

        self._ready = asyncio.Event()

        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

        self._status_listeners: list[Callable[[str, dict[str, Any]], None]] = []

        self.devices: dict[str, DeviceInfo] = {}
        self.states: dict[str, dict[str, Any]] = {}

    async def _reader_loop(self) -> None:
        """Читает WS и прокидывает в _handle_message."""
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type == WSMsgType.TEXT:
                self._handle_message(msg.data)
            elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                break

    def add_status_listener(self, cb: Callable[[str, dict[str, Any]], None]) -> Callable[[], None]:
        self._status_listeners.append(cb)

        def _unsub() -> None:
            try:
                self._status_listeners.remove(cb)
            except ValueError:
                pass

        return _unsub

    async def async_test_connection(self) -> None:
        """Используется в config_flow: подключиться, authorize, закрыться."""
        session = async_get_clientsession(self.hass)
        try:
            ws = await session.ws_connect(self.url, heartbeat=30)
        except Exception as e:
            raise LarnitechConnectionError(str(e)) from e

        try:
            _LOGGER.info("AUTHORIZE WS: %s", self.url)
            await ws.send_str(json.dumps({"request": "authorize", "key": self.api_key}))
            msg = await ws.receive(timeout=8)
            if msg.type != WSMsgType.TEXT:
                raise LarnitechConnectionError("No authorize response")

            payload = json.loads(msg.data)

            # На разных прошивках формат ответа отличается.
            # Считаем auth ок, если нет явной ошибки.
            if payload.get("error") or payload.get("result") in ("error", "failed"):
                raise LarnitechAuthError("Authorize failed")
        finally:
            await ws.close()

    async def async_start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._ready.clear()
        self._task = asyncio.create_task(self._run())

    async def async_stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
        if self._ws:
            await self._ws.close()

        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def async_wait_ready(self, timeout: float = 15) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def _run(self) -> None:
        session = async_get_clientsession(self.hass)
        backoff = 1

        while not self._stop.is_set():
            try:
                _LOGGER.info("Connect to Larnitech WS: %s", self.url)
                self._ws = await session.ws_connect(self.url, heartbeat=30)
                _LOGGER.info("Connected to Larnitech WS: %s", self.url)

                self._rx_task = asyncio.create_task(self._reader_loop())

                await self._authorize()
                await self._initial_sync_and_subscribe()

                self._ready.set()
                backoff = 1

                await self._rx_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.warning("WS error: %s. Reconnect in %ss", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                try:
                    if self._rx_task:
                        self._rx_task.cancel()
                        self._rx_task = None
                    if self._ws:
                        await self._ws.close()
                except Exception:
                    pass
                self._ws = None

    async def _authorize(self) -> None:
        resp = await self.request({"request": "authorize", "key": self.api_key})
        _LOGGER.debug("authorize: %s", resp)
        if resp.get("error") or resp.get("result") in ("error", "failed"):
            raise LarnitechAuthError("Authorize failed")

    async def _initial_sync_and_subscribe(self) -> None:
        devices = await self.get_devices(detailed=True)
        self.devices = {d.addr: d for d in devices}
        for d in devices:
            if d.status is not None:
                self.states[d.addr] = d.status

        for addr in self.devices.keys():
            await self.request({"request": "status-subscribe", "addr": addr})

        _LOGGER.info("Loaded devices: %d", len(self.devices))

    def _handle_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except Exception:
            _LOGGER.debug("Non-JSON: %s", raw)
            return

        _LOGGER.debug("RX: %s", payload)

        # 1) Ответ на request: если есть id — почти наверняка это ответ
        # (на некоторых прошивках может не быть поля "response")
        if "id" in payload:
            try:
                req_id = int(payload["id"])
            except (ValueError, TypeError):
                return
            fut = self._pending.pop(req_id, None)
            if fut and not fut.done():
                fut.set_result(payload)
            return

        # 2) Если id нет, но это выглядит как "ответ", а pending всего один — заберём его
        looks_like_response = any(k in payload for k in ("event", "addr", "devices", "status", "error"))
        if looks_like_response and len(self._pending) == 1:
            req_id, fut = next(iter(self._pending.items()))
            self._pending.pop(req_id, None)
            # self.states[d.addr] = d.status
            if fut and not fut.done():
                fut.set_result(payload)
            return


        # {'event': 'statuses', 'devices': [{'addr': '469:31', 'type': 'illumination-sensor', 'status': {'state': 35.33}}]}
        event = payload.get("event")
        devices = payload.get("devices", [])
        if event == "statuses":
            for d in devices:
                addr = d.get("addr")
                if addr:
                    self.states[addr] = d.get("status")
                    for cb in list(self._status_listeners):
                        cb(addr, d.get("status"))
            return

        _LOGGER.debug("Unhandled payload: %s", payload)

    async def request(self, body: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        if not self._ws:
            raise LarnitechConnectionError("WebSocket not connected")

        if self._rx_task and self._rx_task.done():
            raise LarnitechConnectionError("Reader task is not running")

        req_id = self._next_id
        self._next_id += 1

        msg = dict(body)
        msg["id"] = req_id

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        _LOGGER.debug("TX: %s", msg)
        await self._ws.send_str(json.dumps(msg))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            _LOGGER.error("Timeout waiting response for request=%s (id=%s)", body, req_id)
            raise
        finally:
            self._pending.pop(req_id, None)

    async def get_devices(self, detailed: bool = True) -> list[DeviceInfo]:
        req = {"request": "get-devices"}
        if detailed:
            req["status"] = "detailed"

        resp = await self.request(req)
        devices_raw = resp.get("devices", [])

        out: list[DeviceInfo] = []
        for d in devices_raw:
            addr = d.get("addr")
            if not addr:
                continue
            out.append(
                DeviceInfo(
                    addr=addr,
                    type=d.get("type", "unknown"),
                    subType=d.get("sub-type", None),
                    name=d.get("name") or addr,
                    area=d.get("area"),
                    status=d.get("status"),
                    linked=d.get("linked", []),
                    automations=d.get("automations", None),
                )
            )
        return out

    async def status_set(self, addr: str, status: dict[str, Any]) -> None:
        await self.request({"request": "status-set", "addr": addr, "status": status})

    async def status_get(self, addr: str) -> dict[str, Any] | None:
        resp = await self.request({"request": "status-get", "addr": addr})
        st = resp.get("status")
        if isinstance(st, dict):
            self.states[addr] = st
            return st
        return None
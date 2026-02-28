import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp


@dataclass
class Req:
    id: int
    body: dict[str, Any]


class LarnitechProbe:
    def __init__(self, url: str, api_key: str) -> None:
        self.url = url
        self.api_key = api_key
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    def _new_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    async def _send(self, ws: aiohttp.ClientWebSocketResponse, body: dict[str, Any]) -> Req:
        rid = self._new_id()
        msg = dict(body)
        msg["id"] = rid

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut

        raw = json.dumps(msg)
        print(f"\nTX: {raw}")
        await ws.send_str(raw)
        return Req(id=rid, body=msg)

    def _on_message(self, raw: str) -> None:
        # Печатаем ВСЁ сырьём, чтобы увидеть реальный формат
        print(f"RX(raw): {raw}")

        # Параллельно пытаемся распарсить JSON и матчить pending
        try:
            payload = json.loads(raw)
        except Exception:
            return

        print(f"RX(json): {payload}")

        if "id" in payload:
            try:
                rid = int(payload["id"])
            except (ValueError, TypeError):
                return
            fut = self._pending.pop(rid, None)
            if fut and not fut.done():
                fut.set_result(payload)

    async def _await_resp(self, req: Req, timeout: float = 10.0) -> dict[str, Any]:
        fut = self._pending.get(req.id)
        if fut is None:
            raise RuntimeError(f"Missing pending future for id={req.id}")
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting response for id={req.id}, request={req.body}") from None
        finally:
            self._pending.pop(req.id, None)

    async def run(self) -> None:
        async with aiohttp.ClientSession() as session:
            print(f"Connecting to: {self.url}")
            async with session.ws_connect(self.url, heartbeat=30) as ws:
                # отдельная таска читает входящие сообщения постоянно
                reader_task = asyncio.create_task(self._reader(ws))

                # 1) authorize
                req = await self._send(ws, {"request": "authorize", "key": self.api_key})
                auth = await self._await_resp(req, timeout=10)
                print(f"\nAUTH RESP: {auth}")

                # 2) get-devices (detailed)
                req = await self._send(ws, {"request": "get-devices", "status": "detailed"})
                devs = await self._await_resp(req, timeout=15)
                print(f"\nGET-DEVICES RESP keys: {list(devs.keys())}")

                devices = devs.get("devices")
                if isinstance(devices, list):
                    print(f"Devices count: {len(devices)}")
                    # покажем первые 2 устройства
                    for d in devices[:2]:
                        print("Device sample:", d)

                    # 3) subscribe по первым 2 (для примера)
                    for d in devices[:2]:
                        addr = d.get("addr")
                        if addr:
                            await self._send(ws, {"request": "status-subscribe", "addr": addr})
                    print("\nSubscribed to first 2 devices. Watching RX for 30s...")

                else:
                    print("No 'devices' list in response. Full response printed above.")

                # Подожди и посмотри push-сообщения
                await asyncio.sleep(30)

                reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader_task

    async def _reader(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._on_message(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                print(f"RX(binary): {msg.data!r}")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print("WS error:", ws.exception())
                break
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                print("WS closed.")
                break


if __name__ == "__main__":
    # Можно брать из окружения (удобно для .env + Run configuration)
    host = os.getenv("LT_HOST", "192.168.1.64")
    port = int(os.getenv("LT_PORT", "2041"))
    key = os.getenv("LT_KEY", "").strip()

    if not key:
        print("ERROR: LT_KEY is empty. Set env var LT_KEY or edit the script.")
        sys.exit(1)

    url = f"ws://{host}:{port}/api"

    import contextlib
    asyncio.run(LarnitechProbe(url=url, api_key=key).run())
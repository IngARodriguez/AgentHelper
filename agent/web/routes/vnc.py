"""WebSocket bridge /websockify → TCP a x11vnc:5900. Reemplaza al binario
`websockify` evitando una dependencia más en el contenedor.

El mount de los archivos estáticos noVNC (/vnc) lo hace `create_app()`
porque depende de StaticFiles y de la ruta absoluta de NOVNC_DIR.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ...config import VNC_PORT


def register(app: FastAPI) -> None:
    """Registra el WebSocket en la app."""

    @app.websocket("/websockify")
    async def websockify_bridge(websocket: WebSocket) -> None:
        requested = list(websocket.scope.get("subprotocols", []) or [])
        selected: str | None = None
        if "binary" in requested:
            selected = "binary"

        print(f"[ws] connect requested_protos={requested!r} selected={selected!r}", flush=True)

        try:
            await websocket.accept(subprotocol=selected)
        except Exception as e:
            print(f"[ws] accept failed: {e!r}", flush=True)
            return

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", VNC_PORT)
        except OSError as e:
            print(f"[ws] tcp connect to 127.0.0.1:{VNC_PORT} failed: {e!r}", flush=True)
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
            return

        print(f"[ws] tcp connected to x11vnc:{VNC_PORT}, bridging…", flush=True)

        async def ws_to_tcp() -> None:
            try:
                while True:
                    msg = await websocket.receive()
                    msg_type = msg.get("type")
                    if msg_type == "websocket.disconnect":
                        return
                    data = msg.get("bytes")
                    if data is None:
                        text = msg.get("text")
                        if text is None:
                            continue
                        data = text.encode("utf-8")
                    writer.write(data)
                    await writer.drain()
            except WebSocketDisconnect:
                pass
            except Exception as e:
                print(f"[ws] ws_to_tcp error: {e!r}", flush=True)

        async def tcp_to_ws() -> None:
            try:
                while True:
                    data = await reader.read(16384)
                    if not data:
                        return
                    await websocket.send_bytes(data)
            except Exception as e:
                print(f"[ws] tcp_to_ws error: {e!r}", flush=True)

        try:
            done, pending = await asyncio.wait(
                [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            try:
                await websocket.close()
            except Exception:
                pass
            print("[ws] bridge closed", flush=True)

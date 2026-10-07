"""Loopback-only local workbench server."""
import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import queue
from urllib.parse import urlparse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
from .runtime import Runtime

app = FastAPI(title="Modem Lab", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
current = None


def allowed_origin(socket):
    origin = socket.headers.get("origin")
    try:
        parsed = urlparse(origin or "")
        return parsed.scheme in ("http", "https") and parsed.hostname in ("localhost", "127.0.0.1", "::1") and parsed.port in (8000, 5173)
    except ValueError:
        return False


@app.get("/api/health")
def health():
    return dict(status="ok", profile="Bell 103A2-style", fidelity="functional", rate=300)


@app.websocket("/ws/control")
async def control_socket(socket: WebSocket):
    global current
    if not allowed_origin(socket) or current is not None:
        await socket.close(code=1008)
        return
    await socket.accept()
    runtime = Runtime()
    current = runtime
    await socket.send_json(dict(type="hello", version=1, session_id=runtime.session_id, generation=runtime.generation))

    async def outbound():
        while True:
            try:
                message = runtime.control.get_nowait()
            except queue.Empty:
                if runtime.stopped.is_set():
                    await socket.close(code=1011)
                    return
                await asyncio.sleep(0.005)
                continue
            await asyncio.wait_for(socket.send_json(message), timeout=1)

    sender = asyncio.create_task(outbound())
    try:
        while not sender.done():
            raw = await socket.receive_text()
            if len(raw.encode("utf-8")) > 16384:
                await socket.close(code=1009)
                break
            try:
                command = json.loads(raw)
                if not isinstance(command, dict):
                    raise ValueError("Command must be a JSON object")
                runtime.commands.put_nowait(command)
            except (ValueError, queue.Full):
                runtime.emit(dict(type="ack", command_id=None, ok=False, sample_index=runtime.engine.sample,
                                  error="Invalid JSON command or command queue full"))
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
        runtime.close()
        if current is runtime:
            current = None


@app.websocket("/ws/data/{session_id}")
async def data_socket(socket: WebSocket, session_id: str):
    runtime = current
    if not allowed_origin(socket) or runtime is None or runtime.session_id != session_id or runtime.data_connected:
        await socket.close(code=1008)
        return
    await socket.accept()
    runtime.data_connected = True
    pending = set()
    last_credit = asyncio.get_running_loop().time()

    async def credits():
        nonlocal last_credit
        while True:
            raw = await socket.receive_text()
            if len(raw) > 1024:
                raise ValueError("Invalid credit")
            credit = json.loads(raw)
            key = (credit.get("generation"), credit.get("sequence"))
            if credit.get("type") != "credit" or key not in pending:
                raise ValueError("Invalid credit")
            pending.remove(key)
            last_credit = asyncio.get_running_loop().time()

    receiver = asyncio.create_task(credits())
    try:
        while not runtime.stopped.is_set() and not receiver.done():
            if len(pending) >= 8:
                if asyncio.get_running_loop().time()-last_credit > 2:
                    break
                await asyncio.sleep(0.005)
                continue
            try:
                packet = runtime.data.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
            import struct
            generation, sequence = struct.unpack_from("<II", packet, 8)
            pending.add((generation, sequence))
            await asyncio.wait_for(socket.send_bytes(packet), timeout=0.25)
    except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
        pass
    finally:
        receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await receiver
        runtime.data_connected = False
        with contextlib.suppress(Exception):
            await socket.close()


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
# Editable checkout: backend/modem_lab/api.py -> repository root is parents[2].
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="workbench")
else:
    @app.get("/")
    def missing_build():
        return JSONResponse(dict(message="Build frontend first: cd frontend && npm install && npm run build"), status_code=503)


def main():
    parser = argparse.ArgumentParser(description="Start the local Modem Lab workbench")
    parser.add_argument("--port", type=int, default=8000, choices=[8000])
    args = parser.parse_args()
    uvicorn.run("modem_lab.api:app", host="127.0.0.1", port=args.port, ws_max_size=16384, ws_max_queue=16)


if __name__ == "__main__":
    main()

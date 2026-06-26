from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.parse
import urllib.request
from typing import Any

from agent_browser_skill.errors import ToolError


def cdp_tabs(port: int) -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise ToolError(f"manual desktop CDP is not reachable on 127.0.0.1:{port}: {exc}") from exc


def cdp_page_ws(port: int) -> str:
    tabs = cdp_tabs(port)
    for tab in tabs:
        if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
            return str(tab["webSocketDebuggerUrl"])
    raise ToolError("manual desktop has no debuggable Chrome page")


def ws_recv_frame(sock: socket.socket) -> str:
    header = sock.recv(2)
    if len(header) < 2:
        raise ToolError("CDP websocket closed")
    _fin_opcode, second = header
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ToolError("CDP websocket closed during frame read")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def ws_send_frame(sock: socket.socket, payload: str) -> None:
    data = payload.encode("utf-8")
    mask = os.urandom(4)
    length = len(data)
    if length < 126:
        header = struct.pack("!BB", 0x81, 0x80 | length)
    elif length < 65536:
        header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    sock.sendall(header + mask + masked)


def cdp_call(port: int, method: str, params: dict[str, Any] | None = None, timeout: int = 8) -> dict[str, Any]:
    ws_url = cdp_page_ws(port)
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    ws_port = parsed.port or port
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = "\r\n".join(
        [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{ws_port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            "",
            "",
        ]
    )
    expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    with socket.create_connection((host, ws_port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(request.encode("ascii"))
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in b"".join(chunks):
                break
        response = b"".join(chunks).decode("iso-8859-1", errors="replace")
        if " 101 " not in response or expected not in response:
            raise ToolError("CDP websocket handshake failed")
        message = {"id": 1, "method": method, "params": params or {}}
        ws_send_frame(sock, json.dumps(message, ensure_ascii=False))
        while True:
            frame = ws_recv_frame(sock)
            data = json.loads(frame)
            if data.get("id") == 1:
                if "error" in data:
                    raise ToolError(f"CDP {method} failed: {data['error']}")
                return data.get("result") or {}


def cdp_eval(port: int, expression: str, timeout: int = 8) -> Any:
    result = cdp_call(
        port,
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
        timeout=timeout,
    )
    if result.get("exceptionDetails"):
        text = result["exceptionDetails"].get("text") or "JavaScript evaluation failed"
        details = result["exceptionDetails"].get("exception", {}).get("description") or ""
        raise ToolError(f"{text}: {details}".strip())
    remote = result.get("result") or {}
    return remote.get("value")

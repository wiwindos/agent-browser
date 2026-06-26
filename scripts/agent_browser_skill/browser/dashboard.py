from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.core.args import timeout_from
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime.dependencies import require_agent_browser
from agent_browser_skill.runtime.process import run_process


def dashboard_port_from(args: dict[str, Any]) -> int:
    raw = args.get("dashboard_port")
    if raw is None:
        try:
            raw = int(os.getenv("PORT_BASE", "5550")) + 8
        except ValueError:
            raw = 5558
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("dashboard_port must be an integer") from exc
    if port < 1024 or port > 65535:
        raise ToolError("dashboard_port must be between 1024 and 65535")
    return port


def dashboard_internal_port_from(args: dict[str, Any]) -> int:
    raw = args.get("dashboard_internal_port") or 4848
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("dashboard_internal_port must be an integer") from exc
    if port < 1024 or port > 65535:
        raise ToolError("dashboard_internal_port must be between 1024 and 65535")
    return port


def public_host_from(args: dict[str, Any]) -> str:
    host = str(
        args.get("public_host")
        or os.getenv("AGENT_BROWSER_PUBLIC_HOST")
        or os.getenv("PUBLIC_HOST")
        or os.getenv("SERVER_HOST")
        or ""
    ).strip()
    if host:
        host = re.sub(r"^https?://", "", host).split("/", 1)[0]
        return host
    return "<server-host>"


def base_public_url(args: dict[str, Any], port: int) -> str:
    host = public_host_from(args)
    if host == "<server-host>":
        return f"http://{host}:{port}"
    if re.search(r":\d+$", host):
        return f"http://{host}"
    return f"http://{host}:{port}"


def dashboard_url(args: dict[str, Any], port: int) -> str:
    public_url = str(args.get("public_url") or "").strip()
    if public_url:
        return public_url
    return base_public_url(args, port)


def novnc_url(args: dict[str, Any], port: int) -> str:
    public_url = str(args.get("public_url") or "").strip()
    if public_url:
        return public_url
    return f"{base_public_url(args, port)}/vnc.html?autoconnect=1&resize=scale"


def dashboard_command(root: Path, args: dict[str, Any], command: str, port: int) -> tuple[int, str]:
    binary = require_agent_browser(root, args, timeout_from(args))
    if command == "start":
        return run_process([binary, "dashboard", "start", "--port", str(port)], timeout=30, cwd=root)
    return run_process([binary, "dashboard", command], timeout=20, cwd=root)


def stop_dashboard_proxy(root: Path, public_port: int) -> None:
    pid_file = root / ".agent-browser" / f"dashboard-proxy-{public_port}.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return
    try:
        os.kill(pid, 15)
    except Exception:
        pass
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass


def start_dashboard_proxy(root: Path, public_port: int, internal_port: int) -> str:
    if public_port == internal_port:
        return "proxy not needed"

    stop_dashboard_proxy(root, public_port)
    proxy_dir = root / ".agent-browser"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    pid_file = proxy_dir / f"dashboard-proxy-{public_port}.pid"
    log_file = proxy_dir / f"dashboard-proxy-{public_port}.log"
    proxy_code = r'''
import socket
import sys
import threading

listen_port = int(sys.argv[1])
target_port = int(sys.argv[2])

def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", listen_port))
server.listen(128)
print(f"proxy listening on 0.0.0.0:{listen_port} -> 127.0.0.1:{target_port}", flush=True)

while True:
    client, _addr = server.accept()
    upstream = socket.create_connection(("127.0.0.1", target_port), timeout=10)
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()
'''
    with log_file.open("ab", buffering=0) as log:
        proc = subprocess.Popen(
            [sys.executable or "python", "-u", "-c", proxy_code, str(public_port), str(internal_port)],
            cwd=str(root),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(0.3)
    if proc.poll() is not None:
        detail = log_file.read_text(encoding="utf-8", errors="replace")[-2000:] if log_file.exists() else ""
        raise ToolError(f"dashboard proxy failed to start: {detail}")
    return f"proxy listening on 0.0.0.0:{public_port} -> 127.0.0.1:{internal_port}"


def start_dashboard(root: Path, args: dict[str, Any]) -> tuple[int, str, int, str]:
    public_port = dashboard_port_from(args)
    internal_port = dashboard_internal_port_from(args)
    stop_dashboard_proxy(root, public_port)
    dashboard_command(root, args, "stop", internal_port)
    code, out = dashboard_command(root, args, "start", internal_port)
    proxy_note = ""
    if code == 0:
        proxy_note = start_dashboard_proxy(root, public_port, internal_port)
    combined = "\n".join(part for part in (out, proxy_note) if part)
    return code, combined, public_port, dashboard_url(args, public_port)

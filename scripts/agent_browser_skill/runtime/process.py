from __future__ import annotations

import os
import subprocess
import shutil
import time
from pathlib import Path

from agent_browser_skill.errors import ToolError


def run_process(
    command: list[str],
    *,
    timeout: int,
    cwd: Path,
    input_text: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str]:
    env = os.environ.copy()
    local_prefix = cwd / ".agent-browser" / "npm-global"
    local_bin = local_prefix / "bin"
    env["NPM_CONFIG_PREFIX"] = str(local_prefix)
    env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    output = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    combined = "\n".join(part for part in (output, stderr) if part)
    if len(combined) > 60000:
        combined = combined[:60000] + "\n...[truncated]"
    return proc.returncode, combined


def _desktop_dir(root: Path) -> Path:
    path = root / ".agent-browser" / "manual-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stop_pid_file(pid_file: Path) -> None:
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


def wait_profile_unlocked(profile: Path, timeout: float = 5.0) -> list[str]:
    lock_names = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        existing = [name for name in lock_names if (profile / name).exists()]
        if not existing:
            return []
        time.sleep(0.25)
    return [name for name in lock_names if (profile / name).exists()]


def start_bg(root: Path, pid_file: Path, log_file: Path, command: list[str], env_extra: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    local_prefix = root / ".agent-browser" / "npm-global"
    env["NPM_CONFIG_PREFIX"] = str(local_prefix)
    env["PATH"] = f"{local_prefix / 'bin'}:{env.get('PATH', '')}"
    if env_extra:
        env.update(env_extra)
    with log_file.open("ab", buffering=0) as log:
        proc = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(0.4)
    if proc.poll() is not None:
        detail = log_file.read_text(encoding="utf-8", errors="replace")[-3000:] if log_file.exists() else ""
        raise ToolError(f"process failed to start: {' '.join(command)}\n{detail}")
    return proc.pid


def pid_is_running(pid_file: Path) -> bool:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def unlock_profile(profile: Path) -> list[str]:
    removed = []
    lock_names = [
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
        "DevToolsActivePort",
        "chrome_debug.log",
    ]
    for name in lock_names:
        target = profile / name
        try:
            if target.is_symlink() or target.is_file():
                target.unlink()
                removed.append(str(target))
            elif target.is_dir():
                shutil.rmtree(target)
                removed.append(str(target))
        except FileNotFoundError:
            pass
        except Exception:
            pass
    return removed


def stop_manual_desktop(root: Path) -> str:
    desktop_dir = _desktop_dir(root)
    stopped = []
    for name in ("websockify.pid", "x11vnc.pid", "chrome.pid", "openbox.pid", "xvfb.pid"):
        pid_file = desktop_dir / name
        if pid_file.exists():
            stop_pid_file(pid_file)
            stopped.append(name[:-4])
    time.sleep(1.0)
    return f"stopped: {', '.join(stopped)}" if stopped else "no manual desktop processes found"


def stop_manual_access(root: Path) -> str:
    desktop_dir = _desktop_dir(root)
    stopped = []
    for name in ("websockify.pid", "x11vnc.pid"):
        pid_file = desktop_dir / name
        if pid_file.exists():
            stop_pid_file(pid_file)
            stopped.append(name[:-4])
    for pattern in ("websockify", "novnc_proxy", "x11vnc"):
        try:
            subprocess.run(["pkill", "-f", pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass
    time.sleep(0.5)
    return f"closed public manual access: {', '.join(stopped)}" if stopped else "public manual access already closed"

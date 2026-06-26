from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from agent_browser_skill.errors import BrowserBusyError

from .config import (
    LOCK_STALE_SECONDS,
    MANUAL_BROWSER_ACQUIRE_ACTIONS,
    MANUAL_BROWSER_LOCK_TTL_SECONDS,
    MANUAL_BROWSER_PROFILE_ACTIONS,
    MANUAL_BROWSER_RELEASE_ACTIONS,
    MANUAL_BROWSER_SAME_PROFILE_ALLOWED_ACTIONS,
)


class BrowserToolLock:
    def __init__(self, root: Path, action: str, timeout: float, pid_running: Callable[[int], bool]):
        self.root = root
        self.action = action
        self.timeout = timeout
        self.pid_running = pid_running
        self.lock_dir = root / ".agent-browser" / "browser_tool.lock"
        self.owner_file = self.lock_dir / "owner.json"

    def __enter__(self) -> "BrowserToolLock":
        self.lock_dir.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                self.lock_dir.mkdir()
                self.owner_file.write_text(
                    json.dumps(
                        {
                            "pid": __import__("os").getpid(),
                            "action": self.action,
                            "started": time.time(),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return self
            except FileExistsError:
                if self._break_stale_lock():
                    continue
                if time.time() >= deadline:
                    raise BrowserBusyError(self._owner())
                time.sleep(0.5)

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        try:
            self.owner_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            self.lock_dir.rmdir()
        except Exception:
            pass

    def _break_stale_lock(self) -> bool:
        owner = self._owner()
        try:
            pid = int(owner.get("pid") or 0)
        except Exception:
            pid = 0
        try:
            started = float(owner.get("started") or 0)
        except Exception:
            started = 0
        stale = (pid and not self.pid_running(pid)) or (started and time.time() - started > LOCK_STALE_SECONDS)
        if not stale:
            return False
        try:
            shutil.rmtree(self.lock_dir)
            return True
        except Exception:
            return False

    def _owner(self) -> dict[str, Any]:
        try:
            owner = json.loads(self.owner_file.read_text(encoding="utf-8"))
        except Exception:
            owner = {}
        return owner if isinstance(owner, dict) else {}


def manual_browser_lock_file(root: Path) -> Path:
    return root / ".agent-browser" / "manual-browser.lock.json"


def read_manual_browser_lock(root: Path) -> dict[str, Any] | None:
    path = manual_browser_lock_file(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def manual_browser_lock_is_stale(
    root: Path,
    lock: dict[str, Any] | None,
    *,
    manual_desktop_running: Callable[[Path], bool],
) -> bool:
    if not lock:
        return True
    try:
        updated_at = float(lock.get("updated_at") or lock.get("created_at") or 0)
    except Exception:
        updated_at = 0
    if updated_at and time.time() - updated_at > MANUAL_BROWSER_LOCK_TTL_SECONDS:
        return True
    if not manual_desktop_running(root):
        return True
    return False


def clear_manual_browser_lock(root: Path) -> None:
    try:
        manual_browser_lock_file(root).unlink(missing_ok=True)
    except Exception:
        pass


def write_manual_browser_lock(
    root: Path,
    paths: dict[str, Path],
    args: dict[str, Any],
    action: str,
    *,
    remembered_url: Callable[[Path, dict[str, Path]], str],
) -> dict[str, Any]:
    ctx = args.get("_context") if isinstance(args.get("_context"), dict) else {}
    lock = {
        "resource": "manual_browser",
        "profile": paths["site"].name,
        "profile_path": str(paths["profile"]),
        "action": action,
        "url": str(args.get("url") or remembered_url(root, paths) or ""),
        "user_id": ctx.get("user_id"),
        "chat_id": ctx.get("chat_id"),
        "session_id": ctx.get("session_id"),
        "source": ctx.get("source"),
        "state": "READY",
        "created_at": time.time(),
        "updated_at": time.time(),
        "expires_at": time.time() + MANUAL_BROWSER_LOCK_TTL_SECONDS,
    }
    path = manual_browser_lock_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return lock


def refresh_manual_browser_lock(root: Path, lock: dict[str, Any]) -> None:
    lock["updated_at"] = time.time()
    lock["expires_at"] = time.time() + MANUAL_BROWSER_LOCK_TTL_SECONDS
    try:
        manual_browser_lock_file(root).write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def manual_browser_busy_output(lock: dict[str, Any], requested_profile: str, action: str) -> tuple[str, dict[str, Any]]:
    try:
        created = float(lock.get("created_at") or 0)
    except Exception:
        created = 0
    try:
        expires = float(lock.get("expires_at") or 0)
    except Exception:
        expires = 0
    busy_profile = str(lock.get("profile") or "(unknown)")
    same_profile = busy_profile == requested_profile
    compatible_same_profile = same_profile and action in MANUAL_BROWSER_SAME_PROFILE_ALLOWED_ACTIONS
    lock_user = lock.get("user_id")
    lock_chat = lock.get("chat_id")
    replacement_allowed = False
    replacement_reason = ""
    if not same_profile and action in MANUAL_BROWSER_ACQUIRE_ACTIONS:
        replacement_allowed = True
        replacement_reason = "same sandbox user requested a new manual browser task on a different profile"
    lines = [
        "manual_browser_busy=true",
        f"busy_profile: {busy_profile}",
        f"requested_profile: {requested_profile}",
        f"same_profile: {str(same_profile).lower()}",
        f"compatible_same_profile_action: {str(compatible_same_profile).lower()}",
        f"busy_action: {lock.get('action') or '(unknown)'}",
        f"busy_url: {lock.get('url') or '(unknown)'}",
        f"requested_action: {action}",
        f"busy_since: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created)) if created else '(unknown)'}",
        f"expires_at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires)) if expires else '(unknown)'}",
        f"replacement_allowed: {str(replacement_allowed).lower()}",
        "retry_later=true",
        (
            "A new manual-browser task may safely replace the current same-user session."
            if replacement_allowed
            else "Do not start another noVNC/manual desktop or recover/close the current browser unless the user explicitly asks. Tell the user that the browser is busy and the task must wait."
        ),
    ]
    if replacement_reason:
        lines.append(f"replacement_reason: {replacement_reason}")
    return "\n".join(lines), {
        "manual_browser_busy": True,
        "busy_profile": busy_profile,
        "requested_profile": requested_profile,
        "same_profile": same_profile,
        "compatible_same_profile_action": compatible_same_profile,
        "replacement_allowed": replacement_allowed,
        "replacement_reason": replacement_reason or None,
        "manual_browser_lock": lock,
        "busy_user_id": lock_user,
        "busy_chat_id": lock_chat,
    }


def browser_tool_busy_output(owner: dict[str, Any], requested_action: str) -> tuple[str, dict[str, Any]]:
    try:
        started = float(owner.get("started") or 0)
    except Exception:
        started = 0
    owner_action = str(owner.get("action") or "(unknown)")
    lines = [
        "agent_browser_busy=true",
        f"busy_action: {owner_action}",
        f"requested_action: {requested_action}",
        f"busy_since: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started)) if started else '(unknown)'}",
        "retry_later=true",
        "Another browser skill action is still running in this sandbox. Do not call recover/close or start a second browser. Wait and retry the same action later.",
    ]
    return "\n".join(lines), {
        "agent_browser_busy": True,
        "busy_action": owner_action,
        "requested_action": requested_action,
        "browser_tool_lock": owner,
    }


def guard_manual_browser_resource(
    root: Path,
    paths: dict[str, Path],
    args: dict[str, Any],
    action: str,
    *,
    manual_desktop_running: Callable[[Path], bool],
    bool_arg: Callable[[dict[str, Any], str, bool], bool],
    remembered_url: Callable[[Path, dict[str, Path]], str],
) -> tuple[str, dict[str, Any]] | None:
    if action not in MANUAL_BROWSER_PROFILE_ACTIONS and action not in MANUAL_BROWSER_RELEASE_ACTIONS:
        return None

    lock = read_manual_browser_lock(root)
    if lock and manual_browser_lock_is_stale(root, lock, manual_desktop_running=manual_desktop_running):
        clear_manual_browser_lock(root)
        lock = None

    requested_profile = paths["site"].name
    if action in MANUAL_BROWSER_RELEASE_ACTIONS:
        if lock:
            busy_profile = str(lock.get("profile") or "")
            force = bool_arg(args, "force", False) or bool_arg(args, "interrupt", False)
            if busy_profile and busy_profile != requested_profile and not force:
                return manual_browser_busy_output(lock, requested_profile, action)
        return None

    if lock:
        busy_profile = str(lock.get("profile") or "")
        same_profile = busy_profile == requested_profile
        if same_profile and action in MANUAL_BROWSER_SAME_PROFILE_ALLOWED_ACTIONS:
            refresh_manual_browser_lock(root, lock)
            return None
        if action in MANUAL_BROWSER_ACQUIRE_ACTIONS or (busy_profile and busy_profile != requested_profile):
            return manual_browser_busy_output(lock, requested_profile, action)
        refresh_manual_browser_lock(root, lock)
        return None

    if action in MANUAL_BROWSER_ACQUIRE_ACTIONS:
        write_manual_browser_lock(root, paths, args, action, remembered_url=remembered_url)
    return None


def release_manual_browser_if_needed(root: Path, action: str, meta: dict[str, Any]) -> None:
    if action in MANUAL_BROWSER_RELEASE_ACTIONS:
        clear_manual_browser_lock(root)
        meta["manual_browser_lock_released"] = True
        return
    if action in {"continue_after_manual", "challenge_detected", "close_manual_access"} and meta.get("manual_access_closed"):
        clear_manual_browser_lock(root)
        meta["manual_browser_lock_released"] = True
        return
    if action == "saby_tenders_csv" and meta.get("release_manual_browser_lock"):
        clear_manual_browser_lock(root)
        meta["manual_browser_lock_released"] = True

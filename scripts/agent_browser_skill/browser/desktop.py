from __future__ import annotations

import json
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.browser.cdp import cdp_call, cdp_eval
from agent_browser_skill.core.paths import ensure_inside
from agent_browser_skill.core.patterns import CHALLENGE_RE, MANUAL_REQUIRED_RE, SENSITIVE_RE
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime.bootstrap import ab
from agent_browser_skill.runtime.process import pid_is_running


def desktop_dir(root: Path) -> Path:
    path = root / ".agent-browser" / "manual-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def manual_access_password(root: Path, reset: bool = False) -> str:
    desktop = desktop_dir(root)
    pass_file = desktop / "vnc.pass"
    if reset or not pass_file.exists():
        password = secrets.token_urlsafe(12)
        pass_file.write_text(password + "\n", encoding="utf-8")
        try:
            pass_file.chmod(0o600)
        except Exception:
            pass
        return password
    return pass_file.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()


def find_chrome_binary(root: Path) -> str:
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for path in candidates:
        if path:
            return path

    for base in (Path("/root/.agent-browser/browsers"), root / ".agent-browser" / "browsers"):
        if not base.exists():
            continue
        for chrome in sorted(base.glob("*/chrome")):
            if chrome.exists():
                return str(chrome)
    raise ToolError("Chrome binary not found. Run action=start with install=true first.")


def manual_desktop_running(root: Path) -> bool:
    return pid_is_running(desktop_dir(root) / "chrome.pid")


def manual_access_running(root: Path) -> bool:
    desktop = desktop_dir(root)
    return pid_is_running(desktop / "websockify.pid") and pid_is_running(desktop / "x11vnc.pid")


def desktop_cdp_port_from(args: dict[str, Any]) -> int:
    raw = args.get("desktop_cdp_port") or 9222
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("desktop_cdp_port must be an integer") from exc
    if port < 1024 or port > 65535:
        raise ToolError("desktop_cdp_port must be between 1024 and 65535")
    return port


def desktop_page_state(args: dict[str, Any]) -> dict[str, Any]:
    port = desktop_cdp_port_from(args)
    expression = """
(() => ({
  url: location.href,
  title: document.title,
  text: document.body ? document.body.innerText : "",
  htmlLength: document.documentElement ? document.documentElement.outerHTML.length : 0
}))()
"""
    value = cdp_eval(port, expression)
    if not isinstance(value, dict):
        raise ToolError("manual desktop returned an unexpected page state")
    return value


def state_snapshot(state: dict[str, Any]) -> str:
    return "\n".join(str(state.get(key) or "") for key in ("url", "title", "text"))


def state_has_usable_page(state: dict[str, Any]) -> bool:
    url = str(state.get("url") or "")
    text = str(state.get("text") or "")
    if not url or url == "about:blank" or url.startswith("chrome-error://"):
        return False
    return bool(text.strip())


def state_needs_manual_action(state: dict[str, Any]) -> bool:
    return snapshot_needs_manual_action(state_snapshot(state))


def snapshot_needs_manual_action(snapshot: str) -> bool:
    return bool(CHALLENGE_RE.search(snapshot or "") or MANUAL_REQUIRED_RE.search(snapshot or ""))


def wait_for_clear_desktop_page(args: dict[str, Any], seconds: float) -> tuple[dict[str, Any], bool]:
    deadline = time.time() + max(0.1, seconds)
    last_state: dict[str, Any] = {}
    last_detected = True
    last_error: ToolError | None = None

    while True:
        try:
            last_state = desktop_page_state(args)
            last_detected = state_needs_manual_action(last_state)
            if state_has_usable_page(last_state) and not last_detected:
                return last_state, False
        except ToolError as exc:
            last_error = exc

        if time.time() >= deadline:
            if last_state:
                return last_state, last_detected
            if last_error is not None:
                raise last_error
            return {}, True

        time.sleep(1.0)


def desktop_navigate(args: dict[str, Any], url: str) -> None:
    cdp_call(desktop_cdp_port_from(args), "Page.navigate", {"url": url})


def configure_chrome_downloads(profile: Path, downloads: Path) -> None:
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_file = default_dir / "Preferences"
    prefs: dict[str, Any] = {}
    if prefs_file.exists():
        try:
            loaded = json.loads(prefs_file.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                prefs = loaded
        except Exception:
            prefs = {}
    prefs.setdefault("download", {})
    prefs["download"].update(
        {
            "default_directory": str(downloads),
            "directory_upgrade": True,
            "prompt_for_download": False,
        }
    )
    prefs.setdefault("profile", {})
    prefs["profile"]["default_content_setting_values"] = {
        **prefs["profile"].get("default_content_setting_values", {}),
        "automatic_downloads": 1,
    }
    prefs_file.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def screenshot_path(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> Path:
    filename = str(args.get("filename") or "screenshot.png")
    if SENSITIVE_RE.search(filename):
        filename = "screenshot.png"
    filename = filename.replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith(".png"):
        filename += ".png"
    return ensure_inside(paths["screenshots"] / filename, root)


def write_challenge_checkpoint(
    paths: dict[str, Path],
    *,
    url: str,
    snapshot: str,
    screenshot: Path | None,
    detected: bool,
) -> Path:
    checkpoint = paths["artifact"] / "manual-challenge.json"
    payload = {
        "detected": detected,
        "url": url,
        "site_key": paths["site"].name,
        "profile": str(paths["profile"]),
        "artifact_dir": str(paths["artifact"]),
        "screenshot": str(screenshot) if screenshot else None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "matched": snapshot_needs_manual_action(snapshot or ""),
    }
    checkpoint.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return checkpoint


def save_challenge_screenshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> Path | None:
    shot_args = dict(args)
    shot_args["filename"] = str(args.get("filename") or "manual-challenge.png")
    target = screenshot_path(root, paths, shot_args)
    code, _out = ab(root, paths, args, ["screenshot", str(target)])
    if code != 0:
        return None
    return target


def current_snapshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> str:
    snap_args = dict(args)
    snap_args["json"] = False
    code, out = ab(root, paths, snap_args, ["snapshot", "-i"])
    if code != 0:
        raise ToolError(out or "snapshot failed")
    return out

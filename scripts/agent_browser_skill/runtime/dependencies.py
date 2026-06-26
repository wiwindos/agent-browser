from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.core.patterns import APT_LOCK_RE
from agent_browser_skill.errors import ToolError
from agent_browser_skill.core.helpers import safe_slug
from agent_browser_skill.runtime.constants import CHROME_DEPS_BASE, CHROME_DEPS_T64, DESKTOP_DEPS
from agent_browser_skill.runtime.process import run_process


def deps_marker(root: Path, name: str) -> Path:
    path = root / ".agent-browser" / "deps" / f"{safe_slug(name)}.ok"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_deps_marker(root: Path, name: str) -> None:
    deps_marker(root, name).write_text(str(time.time()), encoding="utf-8")


def clear_deps_marker(root: Path, name: str) -> None:
    marker = deps_marker(root, name)
    try:
        marker.unlink(missing_ok=True)
    except TypeError:
        if marker.exists():
            marker.unlink()


def apt_get_command(*args: str) -> list[str]:
    return ["apt-get", "-o", "DPkg::Lock::Timeout=60", *args]


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


def chrome_runtime_ready(root: Path) -> bool:
    try:
        chrome = find_chrome_binary(root)
    except ToolError:
        clear_deps_marker(root, "chrome-runtime")
        return False

    if shutil.which("ldd"):
        code, out = run_process(["ldd", chrome], timeout=10, cwd=root)
        if code != 0 or "not found" in out:
            clear_deps_marker(root, "chrome-runtime")
            return False

    code, _out = run_process([chrome, "--version"], timeout=10, cwd=root)
    if code == 0:
        write_deps_marker(root, "chrome-runtime")
        return True
    clear_deps_marker(root, "chrome-runtime")
    return False


def chrome_binary_exists(root: Path) -> bool:
    try:
        find_chrome_binary(root)
        return True
    except ToolError:
        return False


def install_agent_browser_chrome(root: Path, args: dict[str, Any], timeout: int) -> str:
    install_args = dict(args)
    install_args["install"] = True
    binary = require_agent_browser(root, install_args, timeout)
    code, out = run_process([binary, "install"], timeout=timeout, cwd=root)
    if code != 0:
        raise ToolError(f"agent-browser browser install failed: {out}")
    return "installed browser runtime via agent-browser install"


def missing_desktop_runtime_components() -> list[str]:
    from agent_browser_skill.runtime.constants import DESKTOP_RUNTIME_BINARIES

    missing = [label for binary, label in DESKTOP_RUNTIME_BINARIES if not shutil.which(binary)]
    novnc_ok = (
        Path("/usr/share/novnc").exists()
        or Path("/usr/share/novnc/html").exists()
        or bool(shutil.which("novnc_proxy"))
    )
    if not novnc_ok:
        missing.append("novnc")
    return missing


def desktop_runtime_ready(root: Path) -> bool:
    missing = missing_desktop_runtime_components()
    if not missing:
        write_deps_marker(root, "desktop-runtime")
        return True
    clear_deps_marker(root, "desktop-runtime")
    return False


def require_agent_browser(root: Path, args: dict[str, Any], timeout: int) -> str:
    local_binary = root / ".agent-browser" / "npm-global" / "bin" / "agent-browser"
    if local_binary.exists():
        return str(local_binary)

    binary = shutil.which("agent-browser")
    if binary:
        return binary
    if args.get("install"):
        from agent_browser_skill.runtime.bootstrap import bootstrap_runtime

        bootstrap_runtime(root, timeout)
        if local_binary.exists():
            return str(local_binary)
        binary = shutil.which("agent-browser")
        if binary:
            return binary
    raise ToolError(
        "agent-browser is not installed in this sandbox. "
        "Use action=start with install=true for best-effort bootstrap, "
        "or build a browser-ready sandbox image with node/npm and agent-browser preinstalled."
    )


def install_browser_dependencies(root: Path, timeout: int, args: dict[str, Any] | None = None) -> str:
    if chrome_runtime_ready(root):
        return "Chrome dependencies already available"
    notes: list[str] = []
    if args is not None and not chrome_binary_exists(root):
        notes.append(install_agent_browser_chrome(root, args, timeout))
        if chrome_runtime_ready(root):
            return "; ".join(notes + ["Chrome runtime available"])
    if not shutil.which("apt-get"):
        raise ToolError("Chrome dependencies are missing and apt-get is not available in this sandbox")

    update_code, update_out = run_process(apt_get_command("update"), timeout=timeout, cwd=root)
    if update_code != 0:
        if APT_LOCK_RE.search(update_out):
            raise ToolError(f"apt is already running in this sandbox; retry later:\n{update_out}")
        raise ToolError(f"failed to update apt package index: {update_out}")

    install_cmd = apt_get_command("install", "-y", "--no-install-recommends", *CHROME_DEPS_BASE)
    code, out = run_process(install_cmd, timeout=timeout, cwd=root)
    if code == 0:
        if chrome_runtime_ready(root):
            return "; ".join(notes + ["installed Chrome dependencies"])
        if args is not None:
            notes.append(install_agent_browser_chrome(root, args, timeout))
            if chrome_runtime_ready(root):
                return "; ".join(notes + ["installed Chrome dependencies"])
        raise ToolError("Chrome dependencies installed, but Chrome runtime verification still fails; no usable browser runtime was found")

    install_cmd = apt_get_command("install", "-y", "--no-install-recommends", *CHROME_DEPS_T64)
    code2, out2 = run_process(install_cmd, timeout=timeout, cwd=root)
    if code2 == 0:
        if chrome_runtime_ready(root):
            return "; ".join(notes + ["installed Chrome dependencies (t64 package set)"])
        if args is not None:
            notes.append(install_agent_browser_chrome(root, args, timeout))
            if chrome_runtime_ready(root):
                return "; ".join(notes + ["installed Chrome dependencies (t64 package set)"])
        raise ToolError("Chrome dependencies installed with t64 package set, but Chrome runtime verification still fails; no usable browser runtime was found")

    if APT_LOCK_RE.search(out) or APT_LOCK_RE.search(out2):
        raise ToolError(f"apt is already running in this sandbox; retry later:\n{out}\n\nfallback:\n{out2}")
    raise ToolError(f"failed to install Chrome dependencies:\n{out}\n\nfallback:\n{out2}")


def install_desktop_dependencies(root: Path, timeout: int) -> str:
    if desktop_runtime_ready(root):
        return "desktop/noVNC dependencies already available"
    if not shutil.which("apt-get"):
        raise ToolError("Desktop dependencies are missing and apt-get is not available in this sandbox")
    update_code, update_out = run_process(apt_get_command("update"), timeout=timeout, cwd=root)
    if update_code != 0:
        if APT_LOCK_RE.search(update_out):
            raise ToolError(f"apt is already running in this sandbox; retry later:\n{update_out}")
        raise ToolError(f"failed to update apt package index: {update_out}")
    code, out = run_process(
        apt_get_command("install", "-y", "--no-install-recommends", *DESKTOP_DEPS),
        timeout=timeout,
        cwd=root,
    )
    if code != 0:
        if APT_LOCK_RE.search(out):
            raise ToolError(f"apt is already running in this sandbox; retry later:\n{out}")
        raise ToolError(f"failed to install desktop/noVNC dependencies: {out}")
    missing = missing_desktop_runtime_components()
    if missing:
        raise ToolError(
            "desktop/noVNC dependencies installation finished, but required runtime components are still missing: "
            + ", ".join(missing)
        )
    write_deps_marker(root, "desktop-runtime")
    return "installed desktop/noVNC dependencies"


def close_agent_browser(root: Path, timeout: int) -> None:
    binary = root / ".agent-browser" / "npm-global" / "bin" / "agent-browser"
    command = [str(binary), "close"] if binary.exists() else ["agent-browser", "close"]
    if not binary.exists() and not shutil.which("agent-browser"):
        return
    run_process(command, timeout=min(timeout, 20), cwd=root)

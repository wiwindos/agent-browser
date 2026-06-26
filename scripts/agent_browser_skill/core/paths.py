from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_browser_skill.errors import ToolError

from .config import ARTIFACT_ACTIONS, NEW_ARTIFACT_ACTIONS
from .helpers import safe_slug
from .profiles import site_key_from


def ensure_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ToolError(f"path escapes workspace: {path}") from exc
    return resolved


def active_artifact_file(root: Path, site: str) -> Path:
    path = root / ".agent-browser" / "active-artifacts" / f"{safe_slug(site)}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def last_artifact(root: Path, site: str) -> Path | None:
    artifacts_root = ensure_inside(root / "browser-artifacts" / safe_slug(site), root)
    if not artifacts_root.exists():
        return None
    dirs = [p for p in artifacts_root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return sorted(dirs, key=lambda p: p.stat().st_mtime if p.exists() else 0)[-1]


def read_active_artifact(root: Path, site: str) -> Path | None:
    marker = active_artifact_file(root, site)
    if not marker.exists():
        return None
    try:
        artifact = ensure_inside(Path(marker.read_text(encoding="utf-8").strip()), root)
    except Exception:
        return None
    return artifact if artifact.is_dir() else None


def remember_artifact(root: Path, site: str, artifact: Path) -> None:
    active_artifact_file(root, site).write_text(str(artifact), encoding="utf-8")


def active_or_new_artifact(root: Path, site: str, action: str) -> Path:
    if action not in NEW_ARTIFACT_ACTIONS:
        current = read_active_artifact(root, site) or last_artifact(root, site)
        if current:
            return current
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    artifact = ensure_inside(root / "browser-artifacts" / site / timestamp, root)
    suffix = 1
    while artifact.exists() and action in NEW_ARTIFACT_ACTIONS:
        suffix += 1
        artifact = ensure_inside(root / "browser-artifacts" / site / f"{timestamp}-{suffix}", root)
    return artifact


def paths_for(root: Path, args: dict[str, Any]) -> dict[str, Path]:
    action = str(args.get("action") or "").strip()
    site = site_key_from(args, root)
    profile = ensure_inside(root / ".agent-browser" / "profiles" / site, root)
    profile.mkdir(parents=True, exist_ok=True)

    if action in ARTIFACT_ACTIONS:
        artifact = active_or_new_artifact(root, site, action)
    else:
        artifact = last_artifact(root, site) or ensure_inside(
            root / "browser-artifacts" / site / time.strftime("%Y%m%d-%H%M%S"),
            root,
        )

    screenshots = ensure_inside(artifact / "screenshots", root)
    logs = ensure_inside(artifact / "logs", root)
    downloads = ensure_inside(artifact / "downloads", root)

    if action in ARTIFACT_ACTIONS:
        for p in (artifact, screenshots, logs, downloads):
            p.mkdir(parents=True, exist_ok=True)
        remember_artifact(root, site, artifact)

    return {
        "site": Path(site),
        "profile": profile,
        "artifact": artifact,
        "screenshots": screenshots,
        "logs": logs,
        "downloads": downloads,
    }


def last_url_file(root: Path, paths: dict[str, Path]) -> Path:
    path = root / ".agent-browser" / "last-url" / f"{paths['site'].name}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def remember_url(root: Path, paths: dict[str, Path], url: str) -> None:
    if not url:
        return
    try:
        last_url_file(root, paths).write_text(url, encoding="utf-8")
    except Exception:
        pass


def remembered_url(root: Path, paths: dict[str, Path]) -> str:
    candidates = [last_url_file(root, paths)]
    if paths["site"].name != "saby":
        candidates.append(root / ".agent-browser" / "last-url" / "saby.txt")
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8", errors="replace").strip()
            if value:
                return value
        except Exception:
            pass
    return ""


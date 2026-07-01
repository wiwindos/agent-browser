from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from agent_browser_skill.core.config import KEEP_EMPTY_ARTIFACT_DIRS, WORKSPACE_SOFT_LIMIT_BYTES, WORKSPACE_TARGET_BYTES
from agent_browser_skill.core.paths import ensure_inside


def path_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for current, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                pass
    return total


def artifact_dirs(root: Path) -> list[Path]:
    artifacts_root = root / "browser-artifacts"
    if not artifacts_root.exists():
        return []
    dirs = [path for path in artifacts_root.glob("*/*") if path.is_dir()]
    return sorted(dirs, key=lambda path: path.stat().st_mtime if path.exists() else 0)


def active_artifact_paths(root: Path) -> set[Path]:
    markers_root = root / ".agent-browser" / "active-artifacts"
    if not markers_root.exists():
        return set()
    active: set[Path] = set()
    for marker in markers_root.glob("*.txt"):
        try:
            artifact = ensure_inside(Path(marker.read_text(encoding="utf-8").strip()), root)
        except Exception:
            continue
        if artifact.exists():
            active.add(artifact.resolve())
    return active



def artifact_dir_for_file(root: Path, path: Path) -> Path | None:
    artifacts_root = root / "browser-artifacts"
    try:
        resolved = ensure_inside(path, root).resolve()
        relative = resolved.relative_to(artifacts_root.resolve())
    except Exception:
        return None
    parts = relative.parts
    if len(parts) < 2:
        return None
    return (artifacts_root / parts[0] / parts[1]).resolve()


def last_artifact(root: Path, site: str) -> Path | None:
    site_dir = root / "browser-artifacts" / site
    if not site_dir.exists():
        return None
    candidates = [path for path in site_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0).resolve()


def protected_artifact_dirs(root: Path) -> set[Path]:
    protected: set[Path] = set(active_artifact_paths(root))
    workflow_root = root / ".agent-browser" / "workflow"
    if workflow_root.exists():
        for state_file in workflow_root.glob("*.json"):
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            for key in ("last_markdown_file", "last_elements_file", "last_text_file"):
                value = state.get(key)
                if not value:
                    continue
                artifact_dir = artifact_dir_for_file(root, Path(str(value)))
                if artifact_dir:
                    protected.add(artifact_dir)
            site = state_file.stem
            latest = last_artifact(root, site)
            if latest:
                protected.add(latest)
    artifacts_root = root / "browser-artifacts"
    if artifacts_root.exists():
        for site_dir in artifacts_root.glob("*"):
            if not site_dir.is_dir():
                continue
            latest = last_artifact(root, site_dir.name)
            if latest:
                protected.add(latest)
    return {path.resolve() for path in protected if path}

def cleanup_empty_artifacts(root: Path, keep_recent: int = KEEP_EMPTY_ARTIFACT_DIRS) -> list[str]:
    active = protected_artifact_dirs(root)
    empty_dirs = [
        artifact
        for artifact in artifact_dirs(root)
        if path_size(artifact) == 0 and artifact.resolve() not in active
    ]
    if len(empty_dirs) <= keep_recent:
        return []
    notes = []
    for artifact in empty_dirs[: len(empty_dirs) - keep_recent]:
        try:
            shutil.rmtree(artifact)
            notes.append(f"removed empty artifact {artifact.relative_to(root)}")
        except Exception as exc:
            notes.append(f"empty artifact cleanup skipped {artifact}: {exc}")
    return notes


def cleanup_browser_artifacts(root: Path, target_bytes: int = WORKSPACE_TARGET_BYTES) -> list[str]:
    notes = []
    size = path_size(root)
    if size <= target_bytes:
        return notes
    protected = protected_artifact_dirs(root)
    for artifact in artifact_dirs(root):
        if artifact.resolve() in protected:
            notes.append(f"kept active artifact {artifact.relative_to(root)}")
            continue
        try:
            artifact_size = path_size(artifact)
            shutil.rmtree(artifact)
            size -= artifact_size
            notes.append(f"removed artifact {artifact.relative_to(root)} ({artifact_size // 1024 // 1024}MB)")
        except Exception as exc:
            notes.append(f"cleanup skipped {artifact}: {exc}")
        if size <= target_bytes:
            break
    return notes



def top_workspace_dirs(root: Path, limit: int = 8) -> list[str]:
    rows: list[tuple[int, Path]] = []
    for child in root.iterdir() if root.exists() else []:
        if child.name in {".git"}:
            continue
        try:
            size = path_size(child) if child.is_dir() else child.stat().st_size
        except OSError:
            continue
        rows.append((size, child))
    rows.sort(reverse=True, key=lambda item: item[0])
    return [f"{path.relative_to(root)} ({size // 1024 // 1024}MB)" for size, path in rows[:limit]]


def cleanup_downloads_screenshots_logs(root: Path, *, include_runtime_env: bool = False) -> list[str]:
    notes: list[str] = []
    candidates: list[Path] = []
    artifacts_root = root / "browser-artifacts"
    if artifacts_root.exists():
        for name in ("downloads", "screenshots", "logs"):
            candidates.extend(path for path in artifacts_root.glob(f"*/*/{name}") if path.exists())
    candidates.append(root / ".agent-browser" / "logs")
    if include_runtime_env:
        candidates.append(root / "node_env")
    for target in candidates:
        try:
            if not target.exists():
                continue
            size = path_size(target) if target.is_dir() else target.stat().st_size
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            notes.append(f"removed browser runtime data {target.relative_to(root)} ({size // 1024 // 1024}MB)")
        except Exception as exc:
            notes.append(f"cleanup skipped {target}: {exc}")
    return notes

def cleanup_runtime_caches(root: Path) -> list[str]:
    notes = []
    candidates = [
        root / ".npm",
        root / ".cache",
        root / ".agent-browser" / "logs",
        root / ".agent-browser" / "manual-desktop" / "xvfb.log",
        root / ".agent-browser" / "manual-desktop" / "openbox.log",
        root / ".agent-browser" / "manual-desktop" / "x11vnc.log",
        root / ".agent-browser" / "manual-desktop" / "websockify.log",
        root / ".agent-browser" / "manual-desktop" / "chrome.log",
        root / ".agent-browser" / "npm-global" / "lib" / "node_modules" / ".cache",
    ]
    for target in candidates:
        try:
            if not target.exists():
                continue
            size = path_size(target) if target.is_dir() else target.stat().st_size
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            notes.append(f"removed cache {target.relative_to(root)} ({size // 1024 // 1024}MB)")
        except Exception as exc:
            notes.append(f"cleanup skipped {target}: {exc}")
    return notes


def cleanup_legacy_browser_use(root: Path) -> list[str]:
    """Remove legacy browser-use runtime data that is protected by this skill.

    Older browser runs can leave a large `.browser-use` directory in the
    workspace. Generic shell cleanup is blocked for protected browser-owned
    paths, so the skill cleanup action must reclaim this space itself. Saved
    agent-browser profiles live under `.agent-browser/profiles`, not here.
    """

    notes = []
    target = root / ".browser-use"
    try:
        if not target.exists():
            return notes
        size = path_size(target) if target.is_dir() else target.stat().st_size
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        notes.append(f"removed legacy browser-use data {target.relative_to(root)} ({size // 1024 // 1024}MB)")
    except Exception as exc:
        notes.append(f"cleanup skipped {target}: {exc}")
    return notes


def cleanup_profile_caches(root: Path) -> list[str]:
    notes = []
    profiles_root = root / ".agent-browser" / "profiles"
    if not profiles_root.exists():
        return notes
    cache_names = {
        "Cache",
        "Code Cache",
        "GPUCache",
        "ShaderCache",
        "GrShaderCache",
        "DawnCache",
        "Crashpad",
        "BrowserMetrics",
        "component_crx_cache",
        "optimization_guide_prediction_model_downloads",
        "Safe Browsing",
        "CertificateRevocation",
    }
    for profile in profiles_root.iterdir():
        if not profile.is_dir():
            continue
        for target in profile.rglob("*"):
            if target.name not in cache_names:
                continue
            try:
                size = path_size(target) if target.is_dir() else target.stat().st_size
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                notes.append(f"removed profile cache {target.relative_to(root)} ({size // 1024 // 1024}MB)")
            except Exception as exc:
                notes.append(f"profile cache cleanup skipped {target}: {exc}")
    return notes


def auto_cleanup_if_needed(root: Path, *, include_runtime_env: bool = False) -> list[str]:
    notes = cleanup_empty_artifacts(root)
    if path_size(root) <= WORKSPACE_SOFT_LIMIT_BYTES:
        return notes
    notes.extend(cleanup_browser_artifacts(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_downloads_screenshots_logs(root, include_runtime_env=include_runtime_env))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_runtime_caches(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_legacy_browser_use(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_profile_caches(root))
    return notes


def cleanup_note(root: Path, *, aggressive: bool = False, include_runtime_env: bool = False) -> str:
    include_runtime_env = include_runtime_env or aggressive
    notes = cleanup_empty_artifacts(root, keep_recent=0)
    notes.extend(cleanup_browser_artifacts(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_downloads_screenshots_logs(root, include_runtime_env=include_runtime_env))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_runtime_caches(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_legacy_browser_use(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_profile_caches(root))
    size_mb = path_size(root) // 1024 // 1024
    if not notes:
        return "\n".join([f"cleanup complete; workspace size: {size_mb}MB", "top directories:", *top_workspace_dirs(root)])
    return "\n".join(
        [
            "cleanup complete",
            f"removed entries: {len(notes)}",
            f"workspace size: {size_mb}MB",
            "top directories:",
            *top_workspace_dirs(root),
            *notes[:20],
            *([f"...and {len(notes) - 20} more"] if len(notes) > 20 else []),
        ]
    )


def artifact_download_files(root: Path, site: str, pattern: str = "*") -> list[Path]:
    artifacts_root = root / "browser-artifacts" / site
    files: list[Path] = []
    if artifacts_root.exists():
        for downloads_dir in artifacts_root.glob("*/downloads"):
            if downloads_dir.is_dir():
                files.extend(path for path in downloads_dir.glob(pattern) if path.is_file())
    files = [path for path in files if not path.name.endswith(".crdownload")]
    return sorted(files, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

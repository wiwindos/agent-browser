from __future__ import annotations

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


def cleanup_empty_artifacts(root: Path, keep_recent: int = KEEP_EMPTY_ARTIFACT_DIRS) -> list[str]:
    active = active_artifact_paths(root)
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
    for artifact in artifact_dirs(root):
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


def auto_cleanup_if_needed(root: Path) -> list[str]:
    notes = cleanup_empty_artifacts(root)
    if path_size(root) <= WORKSPACE_SOFT_LIMIT_BYTES:
        return notes
    notes.extend(cleanup_browser_artifacts(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_runtime_caches(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_legacy_browser_use(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_profile_caches(root))
    return notes


def cleanup_note(root: Path) -> str:
    notes = cleanup_empty_artifacts(root, keep_recent=0)
    notes.extend(cleanup_browser_artifacts(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_runtime_caches(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_legacy_browser_use(root))
    if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
        notes.extend(cleanup_profile_caches(root))
    size_mb = path_size(root) // 1024 // 1024
    if not notes:
        return f"cleanup complete; workspace size: {size_mb}MB"
    return "\n".join(
        [
            "cleanup complete",
            f"removed entries: {len(notes)}",
            f"workspace size: {size_mb}MB",
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

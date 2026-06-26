from __future__ import annotations

import re
from pathlib import Path


def read_int_file(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None
    if not text or text == "max":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def cgroup_pids_status() -> tuple[int | None, int | None]:
    current_paths = [
        Path("/sys/fs/cgroup/pids.current"),
        Path("/sys/fs/cgroup/pids/pids.current"),
    ]
    max_paths = [
        Path("/sys/fs/cgroup/pids.max"),
        Path("/sys/fs/cgroup/pids/pids.max"),
    ]
    current = next((value for path in current_paths if (value := read_int_file(path)) is not None), None)
    limit = next((value for path in max_paths if (value := read_int_file(path)) is not None), None)
    return current, limit


def zombie_process_count() -> int:
    proc = Path("/proc")
    if not proc.exists():
        return 0
    count = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if re.search(r"^State:\s+Z", status, re.M):
            count += 1
    return count


def resource_status_line() -> str:
    current, limit = cgroup_pids_status()
    zombies = zombie_process_count()
    if current is None or limit is None:
        return f"zombies={zombies}"
    return f"pids={current}/{limit}, zombies={zombies}"


def sandbox_resources_exhausted() -> bool:
    current, limit = cgroup_pids_status()
    if current is not None and limit is not None and current >= int(limit * 0.9):
        return True
    zombies = zombie_process_count()
    return zombies >= 50

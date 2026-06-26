#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = SKILL_ROOT / "CHANGELOG.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--bullet", action="append", default=[])
    ns = parser.parse_args()
    version = ns.version.strip()
    bullets = [item.strip() for item in ns.bullet if item.strip()]
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        raise SystemExit("version must match X.Y.Z")
    if not bullets:
        raise SystemExit("at least one --bullet is required")

    current = CHANGELOG.read_text(encoding="utf-8")
    section = "\n".join([f"## {version}", ""] + [f"- {bullet}" for bullet in bullets] + ["", ""])
    if f"## {version}\n" in current:
        raise SystemExit(f"changelog already contains version {version}")
    if not current.startswith("# Changelog\n"):
        raise SystemExit("unexpected changelog format")
    updated = "# Changelog\n\n" + section + current[len("# Changelog\n\n") :]
    CHANGELOG.write_text(updated, encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_JSON = SKILL_ROOT / "skill.json"
VERSION_PY = SKILL_ROOT / "scripts" / "agent_browser_skill" / "version.py"
COLLECTOR = SKILL_ROOT / "scripts" / "agent_browser_skill" / "domains" / "saby" / "collector.js"
SABY_COPY = SKILL_ROOT / "scripts" / "saby_tenders.js"


def replace_version(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"could not update version in {path}")
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    ns = parser.parse_args()
    version = ns.version.strip()
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        raise SystemExit("version must match X.Y.Z")

    skill_data = json.loads(SKILL_JSON.read_text(encoding="utf-8"))
    skill_data["version"] = version
    SKILL_JSON.write_text(json.dumps(skill_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_version(VERSION_PY, r'^SKILL_VERSION = "[^"]+"$', f'SKILL_VERSION = "{version}"')
    replace_version(COLLECTOR, r'const SCRIPT_VERSION = "[^"]+";', f'const SCRIPT_VERSION = "{version}";')
    SABY_COPY.write_text(COLLECTOR.read_text(encoding="utf-8"), encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

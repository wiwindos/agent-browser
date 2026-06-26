#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_browser_skill.runtime.diagnostics import collect_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--site-key", default="")
    ns = parser.parse_args()
    args = {"action": "status", "profile": ns.profile}
    if ns.site_key:
        args["site_key"] = ns.site_key
    report = collect_diagnostics(Path(ns.workspace).resolve(), args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

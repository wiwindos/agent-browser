from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.runner import run_request


def _run(tmp_path: Path, args: dict) -> dict:
    return run_request({"args": args, "context": {"cwd": str(tmp_path), "session_id": "browser-session", "source": "skill_agent-browser_browser"}})


def test_active_browser_blocks_generic_tools_with_normalized_result(tmp_path: Path) -> None:
    for action in ["run_command", "read_file", "list_directory"]:
        out = _run(tmp_path, {"action": action, "command": "echo should-not-run", "path": "/tmp"})
        assert out["success"] is False
        assert out["ok"] is False
        assert out["error_code"] == "BLOCKED"
        assert out["action"] == action
        assert out["session_id"] == "browser-session"
        assert out["state"]["session_id"] == "browser-session"
        assert out["suggested_next_action"] in out["next_allowed_actions"] or out["suggested_next_action"] in {"read_artifact_by_id", "search_artifact"}


def test_active_browser_blocks_protected_paths_and_command_like_requests(tmp_path: Path) -> None:
    blocked = [
        {"action": "run", "task": 'find /workspace -path "/browser-artifacts"'},
        {"action": "run", "task": "curl https://4pda.to/forum/index.php?showtopic=1"},
        {"action": "run", "task": "pip install requests"},
        {"action": "run", "task": "python3 << 'PYEOF'\nprint('x')\nPYEOF"},
        {"action": "open_page", "url": "file:///workspace/u/browser-artifacts/x.txt"},
        {"action": "open_page", "url": "file:///data/skills/agent-browser/SKILL.md"},
    ]
    for args in blocked:
        out = _run(tmp_path, args)
        assert out["error_code"] == "BLOCKED"
        assert out["ok"] is False
        assert out["suggested_next_action"] in {"wait_ready", "read_artifact_by_id", "search_artifact", "extract_forum_posts", "open_page"}


def test_debug_admin_can_bypass_active_browser_policy_to_existing_action(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_action(root, paths, args):
        calls.append(args["action"])
        return "ran", {}

    monkeypatch.setattr("agent_browser_skill.runner.ACTIONS", {"run": fake_action})
    out = _run(tmp_path, {"action": "run", "task": "pip install requests", "debug_admin": True})
    assert out["success"] is True
    assert calls == ["run"]

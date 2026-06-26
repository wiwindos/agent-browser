from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.actions_generic import action_snapshot
from agent_browser_skill.actions_manual import action_read_artifact
from agent_browser_skill.core.paths import paths_for
from agent_browser_skill.errors import ToolError


def _paths(tmp_path: Path, action: str = "snapshot") -> dict[str, Path]:
    return paths_for(tmp_path, {"action": action, "profile": "example", "url": "https://example.com"})


def test_empty_snapshot_returns_read_artifact_next_tool_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paths = _paths(tmp_path, "snapshot")

    def fake_ab(root: Path, paths: dict[str, Path], args: dict[str, object], cmd: list[str]) -> tuple[int, str]:
        assert cmd == ["snapshot", "-i", "--json"]
        return 0, json.dumps({"title": "", "refs": []})

    monkeypatch.setattr("agent_browser_skill.actions_generic.ab", fake_ab)

    output, meta = action_snapshot(tmp_path, paths, {"action": "snapshot", "profile": "example"})

    snapshot_file = meta["snapshot_file"]
    assert "refs_count: 0" in output
    assert "next_step: Snapshot is empty" in output
    assert "Do not pass the artifact directory" in output
    assert f'"path": "{snapshot_file}"' in output
    assert "fallback_after_read" in output


def test_read_artifact_directory_error_points_to_exact_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path, "snapshot")
    recent = paths["logs"] / "snapshot.json"
    recent.write_text('{"title":""}', encoding="utf-8")

    with pytest.raises(ToolError) as exc_info:
        action_read_artifact(tmp_path, paths, {"action": "read_artifact", "path": str(paths["artifact"])})

    message = str(exc_info.value)
    assert "requires a file path, not an artifact directory" in message
    assert "Use the exact snapshot_file/state_file/text_file path" in message
    assert "Do not use read_file for browser-artifacts" in message
    assert str(recent) in message

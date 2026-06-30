from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.core.page_markdown import build_page_markdown_artifact, build_snapshot_from_dom, selector_for_handle


def test_markdown_snapshot_has_content_ui_and_mapping():
    snap = build_snapshot_from_dom({
        "url": "https://example.test/search",
        "title": "Search",
        "blocks": [
            {"kind": "heading", "level": 1, "text": "Results"},
            {"kind": "paragraph", "text": "Useful content"},
            {"kind": "list_item", "text": "First item"},
        ],
        "elements": [
            {"handle": "input:1", "tag": "input", "role": "input", "label": "Date from", "selector": selector_for_handle("input:1"), "visible": True, "disabled": False, "input_type": "date", "placeholder": ""},
            {"handle": "button:1", "tag": "button", "role": "button", "text": "Find", "label": "Find", "selector": selector_for_handle("button:1"), "visible": True, "disabled": False},
            {"handle": "link:1", "tag": "a", "role": "link", "text": "Next", "href": "https://example.test/page/2", "selector": selector_for_handle("link:1"), "visible": True, "disabled": False},
        ],
    })

    assert snap["url"] == "https://example.test/search"
    assert "# Results" in snap["content_md"]
    assert "Useful content" in snap["markdown"]
    assert "[input:1] Date from" in snap["ui_md"]
    assert "[button:1] Find" in snap["ui_md"]
    assert "[link:1] Next -> https://example.test/page/2" in snap["ui_md"]
    assert snap["elements"][0]["selector"] == '[data-agent-browser-handle="input:1"]'
    assert snap["metadata"]["interactive_elements"] == 3


def test_page_markdown_artifact_exposes_revision_nodes_warnings_and_stability():
    artifact = build_page_markdown_artifact({
        "revision": 7,
        "url": "https://example.test",
        "title": "Example",
        "blocks": [{"kind": "paragraph", "text": "Readable"}],
        "elements": [{"handle": "button:1", "tag": "button", "role": "button", "label": "Go"}],
        "maxElements": 1,
        "stable": True,
    })

    assert artifact.revision == 7
    assert artifact.url == "https://example.test"
    assert "Readable" in artifact.markdown
    assert artifact.nodes[0]["node_id"] == "button:1"
    assert artifact.actionable_nodes[0]["node_id"] == "button:1"
    assert artifact.warnings == ["interactive element limit reached; action map may be incomplete"]
    assert artifact.stable is False


def test_selector_for_handle_uses_stable_data_attribute():
    assert selector_for_handle("button:17") == '[data-agent-browser-handle="button:17"]'

import json

from agent_browser_skill.actions_manual import action_click_handle, action_fill_handle, action_page_markdown_act, action_read_page_md
from agent_browser_skill.core.paths import paths_for
from agent_browser_skill.core.workflow import remember_pending_markdown_read


def test_click_and_fill_handle_resolve_latest_mapping(monkeypatch, tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "handles"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({"elements": [
        {"handle": "button:1", "selector": '[data-agent-browser-handle="button:1"]'},
        {"handle": "input:1", "selector": '[data-agent-browser-handle="input:1"]'},
    ]}), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"
    md.write_text("# Page", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping)

    calls = []
    monkeypatch.setattr("agent_browser_skill.actions_manual.action_click", lambda root, p, args: (calls.append(("click", args)) or ("clicked", {"ok": True})))
    monkeypatch.setattr("agent_browser_skill.actions_manual.action_fill", lambda root, p, args: (calls.append(("fill", args)) or ("filled", {"ok": True})))

    out, meta = action_click_handle(tmp_path, paths, {"action": "click_handle", "handle": "button:1"})
    assert "click_handle_ok=true" in out
    assert calls[-1][1]["selector"] == '[data-agent-browser-handle="button:1"]'
    assert meta["recommended_next_action"] == "page_markdown"

    out, meta = action_fill_handle(tmp_path, paths, {"action": "fill_handle", "handle": "input:1", "text": "abc"})
    assert "fill_handle_ok=true" in out
    assert calls[-1][1]["selector"] == '[data-agent-browser-handle="input:1"]'
    assert calls[-1][1]["text"] == "abc"
    assert meta["recommended_next_action"] == "page_markdown"


def test_read_page_md_reads_latest_markdown_artifact(tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "handles"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({"elements": []}), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"
    md.write_text("# Page\n\nUseful Markdown", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping, artifact_id="md_test")

    out, meta = action_read_page_md(tmp_path, paths, {"action": "read_page_md", "max_chars": 1000})

    assert "read_page_md_ok=true" in out
    assert "Useful Markdown" in out
    assert meta["read_page_md_used"] is True
    assert meta["artifact_id"] == "md_test"


def test_page_markdown_act_resolves_node_acts_and_refreshes_markdown(monkeypatch, tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "nodes"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({
        "metadata": {"revision": 3},
        "elements": [{"node_id": "button:1", "handle": "button:1", "selector": '[data-agent-browser-handle="button:1"]'}],
    }), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"
    md.write_text("# Page", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping)

    calls = []
    monkeypatch.setattr("agent_browser_skill.actions_manual.action_click", lambda root, p, args: (calls.append(args) or ("clicked", {"clicked": True})))
    monkeypatch.setattr("agent_browser_skill.actions_manual.action_page_markdown", lambda root, p, args: ("page_markdown_ok=true\n# Refreshed", {"revision": 4, "artifact_id": "md_refreshed"}))

    out, meta = action_page_markdown_act(tmp_path, paths, {"action": "page_markdown.act", "node_id": "button:1", "node_action": "click", "revision": 3, "settle_seconds": 0})

    assert "page_markdown_act_ok=true" in out
    assert "action_page_markdown:" in out
    assert "# Refreshed" in out
    assert calls[-1]["selector"] == '[data-agent-browser-handle="button:1"]'
    assert meta["page_markdown_act_used"] is True
    assert meta["revision"] == 4

import pytest
from agent_browser_skill.errors import ToolError


def test_page_markdown_act_blocks_stale_revision_with_code(tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "nodes"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({"metadata": {"revision": 5}, "elements": [{"node_id": "button:1", "handle": "button:1", "selector": "button"}]}), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"; md.write_text("# Page", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping)

    with pytest.raises(ToolError, match="BLOCKED_STALE_PAGE"):
        action_page_markdown_act(tmp_path, paths, {"action": "page_markdown.act", "node_id": "button:1", "node_action": "click", "revision": 4})


def test_page_markdown_act_blocks_not_actionable_node(tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "nodes"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({"metadata": {"revision": 1}, "elements": [{"node_id": "button:1", "handle": "button:1", "selector": "button", "disabled": True}]}), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"; md.write_text("# Page", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping)

    with pytest.raises(ToolError, match="BLOCKED_NOT_ACTIONABLE"):
        action_page_markdown_act(tmp_path, paths, {"action": "page_markdown.act", "node_id": "button:1", "node_action": "click", "revision": 1})


def test_page_markdown_act_blocks_ambiguous_rebind(tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "nodes"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({"metadata": {"revision": 1}, "elements": [
        {"node_id": "button:1", "handle": "button:1", "selector": "button:nth-of-type(1)"},
        {"node_id": "button:1", "handle": "button:1", "selector": "button:nth-of-type(2)"},
    ]}), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"; md.write_text("# Page", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping)

    with pytest.raises(ToolError, match="BLOCKED_AMBIGUOUS_REBIND"):
        action_page_markdown_act(tmp_path, paths, {"action": "page_markdown.act", "node_id": "button:1", "node_action": "click", "revision": 1})


def test_read_page_md_recommends_page_markdown_act_template(tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "handles"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({"metadata": {"revision": 9}, "elements": []}), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"
    md.write_text("# Page\n\n[button:1] Go", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping, artifact_id="md_test")

    _out, meta = action_read_page_md(tmp_path, paths, {"action": "read_page_md", "max_chars": 1000})

    assert meta["recommended_next_action"] == "page_markdown.act"
    assert meta["next_tool_call"] == {
        "action": "page_markdown.act",
        "node_id": "<choose_from_markdown>",
        "node_action": "click|fill|type|select|submit",
        "revision": "<current_revision>",
    }


def test_page_markdown_act_blocks_changed_live_signature(monkeypatch, tmp_path):
    paths = paths_for(tmp_path, {"action": "test", "profile": "nodes"})
    paths["logs"].mkdir(parents=True, exist_ok=True)
    mapping = paths["logs"] / "page-md-elements.json"
    mapping.write_text(json.dumps({
        "metadata": {
            "revision": 1,
            "live_signature": {"url": "https://example.test", "title": "Before", "readyState": "complete", "body_text_hash": "1", "dom_node_count": 10, "timestamp": 100},
        },
        "elements": [{"node_id": "button:1", "handle": "button:1", "selector": "button"}],
    }), encoding="utf-8")
    md = paths["logs"] / "page-md.txt"; md.write_text("# Page", encoding="utf-8")
    remember_pending_markdown_read(tmp_path, paths, markdown_file=md, elements_file=mapping)
    monkeypatch.setattr("agent_browser_skill.actions_manual.cdp.cdp_eval", lambda *a, **k: {"url": "https://example.test", "title": "After", "readyState": "complete", "body_text_hash": "2", "dom_node_count": 11, "timestamp": 200})

    with pytest.raises(ToolError, match="BLOCKED_STALE_PAGE"):
        action_page_markdown_act(tmp_path, paths, {"action": "page_markdown.act", "node_id": "button:1", "node_action": "click", "revision": 1})

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_browser_skill.actions_manual import action_read_artifact, _artifact_search_excerpt
from agent_browser_skill.core.action_schemas import opaque_id
from agent_browser_skill.core.output import cap_output, metadata
from agent_browser_skill.errors import ToolError
from agent_browser_skill.extractors import summarize_posts

READABLE = {".txt", ".json", ".html", ".htm", ".csv", ".md", ".png", ".jpg", ".jpeg"}


def _files(root: Path) -> list[Path]:
    base = root / "browser-artifacts"
    if not base.exists():
        return []
    return sorted([p for p in base.glob("*/*/**/*") if p.is_file() and p.suffix.lower() in READABLE], key=lambda p: p.stat().st_mtime, reverse=True)


def _resolve(root: Path, artifact_id: str) -> Path:
    for p in _files(root):
        if any(opaque_id(p, prefix) == artifact_id for prefix in ("art", "snap", "md", "map")):
            return p
    raise ToolError(f"artifact_id not found: {artifact_id}")


def _read_cache(root: Path) -> dict[str, Any]:
    p = root / ".agent-browser" / "artifact-read-cache.json"
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}


def _write_cache(root: Path, cache: dict[str, Any]) -> None:
    p = root / ".agent-browser" / "artifact-read-cache.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def action_list_artifacts(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    limit = int(args.get("limit") or 20)
    rows = []
    for p in _files(root)[:limit]:
        rel = p.relative_to(root / "browser-artifacts")
        prefix = "md" if p.name.startswith("page-md") and p.suffix.lower() in {".txt", ".md"} else ("snap" if "snapshot" in p.name.lower() or "state" in p.name.lower() else "art")
        rows.append({"artifact_id": opaque_id(p, prefix), "name": p.name, "kind": prefix, "size_bytes": p.stat().st_size, "relative_key": str(rel)})
    meta = metadata(paths); meta["artifacts"] = rows
    return "artifacts:\n" + json.dumps(rows, ensure_ascii=False, indent=2), meta


def action_read_artifact_by_id(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = _resolve(root, str(args.get("artifact_id")))
    key = json.dumps({k: args.get(k) for k in ("artifact_id", "mode", "max_chars", "query", "regex", "context_lines")}, sort_keys=True)
    cache = _read_cache(root)
    if key in cache:
        meta = metadata(paths); meta.update({"artifact_id": args.get("artifact_id"), "cached": True, "warnings": ["duplicate artifact read suppressed; returning cached summary"]})
        return "cached_artifact_read=true\n" + cache[key], meta
    read_args = dict(args); read_args["path"] = str(target)
    output, meta = action_read_artifact(root, paths, read_args)
    meta["artifact_id"] = args.get("artifact_id")
    cache[key] = f"artifact_id: {args.get('artifact_id')}\nsize_bytes: {target.stat().st_size}\nparams: {key}"
    _write_cache(root, cache)
    return output.replace(str(target), str(args.get("artifact_id"))), meta


def action_search_artifact(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    read_args = dict(args); read_args.setdefault("max_chars", 12000)
    return action_read_artifact_by_id(root, paths, read_args)


def action_read_artifact_slice(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = _resolve(root, str(args.get("artifact_id")))
    offset = int(args.get("offset") or 0); length = int(args.get("length") or args.get("limit") or 4000)
    post_ids = args.get("post_ids")
    if isinstance(post_ids, str):
        post_ids = [p.strip() for p in post_ids.split(",") if p.strip()]
    key = json.dumps({"artifact_id": args.get("artifact_id"), "offset": offset, "length": length, "post_ids": post_ids}, sort_keys=True)
    cache = _read_cache(root)
    if key in cache:
        meta = metadata(paths); meta.update({"artifact_id": args.get("artifact_id"), "cached": True, "warnings": ["duplicate artifact slice suppressed; returning cached summary"]})
        return "cached_artifact_read=true\n" + cache[key], meta
    text = target.read_text(encoding="utf-8", errors="replace")
    payload = text[offset:offset+length]
    if post_ids:
        try:
            parsed = json.loads(text)
            posts = parsed.get("posts", []) if isinstance(parsed, dict) else []
            selected = [p for p in posts if str(p.get("post_id")) in set(map(str, post_ids))]
            payload = json.dumps(selected, ensure_ascii=False, indent=2)
        except Exception:
            payload = "[]"
    meta = metadata(paths); meta.update({"artifact_id": args.get("artifact_id"), "offset": offset, "length": length, "artifact_size_bytes": target.stat().st_size})
    cache[key] = f"artifact_id: {args.get('artifact_id')}\noffset: {offset}\nlength: {length}\nsize_bytes: {target.stat().st_size}"
    _write_cache(root, cache)
    return f"artifact_slice_ok=true\nartifact_id: {args.get('artifact_id')}\noffset: {offset}\nlength: {len(payload)}\n\n{cap_output(payload, 12000)}", meta



def action_summarize_artifact(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = _resolve(root, str(args.get("artifact_id")))
    query = str(args.get("query") or "").strip().lower()
    try:
        parsed = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        raise ToolError(f"summarize_artifact requires a JSON artifact: {exc}") from exc
    posts = parsed.get("posts", []) if isinstance(parsed, dict) else []
    if not isinstance(posts, list):
        raise ToolError("summarize_artifact requires an artifact with a posts array")
    if query:
        posts = [p for p in posts if query in json.dumps(p, ensure_ascii=False).lower()]
    summary = summarize_posts(posts)
    out = {"artifact_id": args.get("artifact_id"), "query": query or None, **summary}
    f = root / ".agent-browser" / "last-summary.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = metadata(paths); meta.update({"artifact_id": args.get("artifact_id"), "count": len(posts), "goal_status": "answer_ready", "summary_file": str(f)})
    return "\n".join(["summarize_artifact_ok=true", f"artifact_id: {args.get('artifact_id')}", f"count: {len(posts)}", cap_output(json.dumps(out, ensure_ascii=False, indent=2), 5000)]), meta

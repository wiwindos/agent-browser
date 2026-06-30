from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _esc(text: Any) -> str:
    return _clean(text).replace("|", "\\|")


@dataclass(frozen=True)
class PageMarkdownArtifact:
    revision: int
    url: str
    title: str
    markdown: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    actionable_nodes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _revision_from_dom(dom: dict[str, Any]) -> int:
    raw = dom.get("revision")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _node_from_element(element: dict[str, Any]) -> dict[str, Any]:
    node_id = str(element.get("node_id") or element.get("handle") or "")
    node = dict(element)
    node["node_id"] = node_id
    node.setdefault("handle", node_id)
    node.setdefault("actionable", bool(node_id))
    return node


def selector_for_handle(handle: str) -> str:
    return f'[data-agent-browser-handle="{handle}"]'


def build_page_markdown_artifact(dom: dict[str, Any]) -> PageMarkdownArtifact:
    url = str(dom.get("url") or "")
    title = str(dom.get("title") or "")
    blocks = dom.get("blocks") if isinstance(dom.get("blocks"), list) else []
    elements = dom.get("elements") if isinstance(dom.get("elements"), list) else []
    nodes = [_node_from_element(e) for e in elements if isinstance(e, dict)]
    warnings = list(dom.get("warnings") or []) if isinstance(dom.get("warnings"), list) else []

    content_lines: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        kind = b.get("kind")
        text = _clean(b.get("text"))
        if not text:
            continue
        if kind == "heading":
            level = max(1, min(int(b.get("level") or 2), 6))
            content_lines.append(f"{'#' * level} {text}")
        elif kind == "list_item":
            content_lines.append(f"- {text}")
        elif kind == "link":
            href = str(b.get("href") or "")
            content_lines.append(f"[{text}]({href})" if href else text)
        elif kind == "table":
            rows = b.get("rows") if isinstance(b.get("rows"), list) else []
            if rows:
                header = [_esc(c) for c in rows[0]]
                content_lines.append("| " + " | ".join(header) + " |")
                content_lines.append("| " + " | ".join("---" for _ in header) + " |")
                for row in rows[1:8]:
                    content_lines.append("| " + " | ".join(_esc(c) for c in row) + " |")
            else:
                content_lines.append(text)
        else:
            content_lines.append(text)
    content_md = "\n\n".join(content_lines).strip()

    ui_lines = []
    for e in nodes:
        if not isinstance(e, dict):
            continue
        handle = str(e.get("handle") or "")
        label = _clean(e.get("label") or e.get("text") or e.get("placeholder") or e.get("role") or e.get("tag"))
        if not handle:
            continue
        suffix = ""
        if e.get("href"):
            suffix = f" -> {e.get('href')}"
        elif e.get("disabled"):
            suffix = " (disabled)"
        ui_lines.append(f"[{handle}] {label}{suffix}".strip())
    ui_md = "\n".join(ui_lines).strip()
    markdown = f"# {title or url or 'Page'}\n\n## Content\n\n{content_md or '_No readable content extracted._'}\n\n## UI elements\n\n{ui_md or '_No interactive elements found._'}\n"
    max_blocks = int(dom.get("maxBlocks") or 0)
    max_elements = int(dom.get("maxElements") or 0)
    if max_blocks and len(blocks) >= max_blocks:
        warnings.append("content block limit reached; page_markdown may be incomplete")
    if max_elements and len(nodes) >= max_elements:
        warnings.append("interactive element limit reached; action map may be incomplete")
    stable = not warnings and bool(dom.get("stable", True))
    return PageMarkdownArtifact(
        revision=_revision_from_dom(dom),
        url=url,
        title=title,
        markdown=markdown,
        nodes=nodes,
        actionable_nodes=[n for n in nodes if n.get("node_id")],
        warnings=warnings,
        stable=stable,
    )


def build_snapshot_from_dom(dom: dict[str, Any]) -> dict[str, Any]:
    artifact = build_page_markdown_artifact(dom)
    blocks = dom.get("blocks") if isinstance(dom.get("blocks"), list) else []
    content_md = artifact.markdown.split("## Content", 1)[-1].split("## UI elements", 1)[0].strip() if "## Content" in artifact.markdown else artifact.markdown
    ui_md = artifact.markdown.split("## UI elements", 1)[-1].strip() if "## UI elements" in artifact.markdown else ""
    data = artifact.to_dict()
    data.update({
        "content_md": content_md,
        "ui_md": ui_md,
        "elements": artifact.actionable_nodes,
        "metadata": {
            "source": "live_dom_cdp",
            "representation": "page_markdown",
            "content_blocks": len(blocks),
            "interactive_elements": len(artifact.actionable_nodes),
            "revision": artifact.revision,
            "stable": artifact.stable,
            "warnings": artifact.warnings,
            "live_signature": dom.get("live_signature") if isinstance(dom.get("live_signature"), dict) else {},
        },
    })
    return data


def live_signature_script() -> str:
    return """
(() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const text = clean((document.body && document.body.innerText) || '');
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  return {
    url: location.href,
    title: document.title,
    readyState: document.readyState,
    body_text_hash: String(hash >>> 0),
    dom_node_count: document.getElementsByTagName('*').length,
    timestamp: Date.now()
  };
})()
"""


def dom_extraction_script(max_blocks: int = 220, max_elements: int = 250) -> str:
    return rf"""
(() => {{
  const maxBlocks = {int(max_blocks)}; const maxElements = {int(max_elements)}; window.__agentBrowserPageMarkdownRevision = (window.__agentBrowserPageMarkdownRevision || 0) + 1;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const box = (el) => {{ const r = el.getBoundingClientRect(); return {{x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)}}; }};
  const cssPath = (el) => {{
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && parts.length < 5; n = n.parentElement) {{
      let part = n.tagName.toLowerCase();
      if (n.className && typeof n.className === 'string') part += '.' + n.className.trim().split(/\s+/).slice(0,2).map(CSS.escape).join('.');
      const parent = n.parentElement;
      if (parent) part += `:nth-of-type(${{Array.from(parent.children).filter(c => c.tagName === n.tagName).indexOf(n) + 1}})`;
      parts.unshift(part);
    }}
    return parts.join(' > ');
  }};
  const labelFor = (el) => {{
    const id = el.id ? document.querySelector(`label[for="${{CSS.escape(el.id)}}"]`) : null;
    const aria = el.getAttribute('aria-label') || el.getAttribute('title') || '';
    const wrap = el.closest('label');
    return clean(aria || (id && id.innerText) || (wrap && wrap.innerText) || el.placeholder || el.innerText || el.value || el.textContent);
  }};
  const blocks = [];
  const root = document.querySelector('main, article, [role="main"]') || document.body || document.documentElement;
  for (const el of root.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,table,a[href],blockquote,pre')) {{
    if (blocks.length >= maxBlocks) break; if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase(); const text = clean(el.innerText || el.textContent); if (!text) continue;
    if (/^h[1-6]$/.test(tag)) blocks.push({{kind:'heading', level:Number(tag[1]), text}});
    else if (tag === 'li') blocks.push({{kind:'list_item', text}});
    else if (tag === 'a') blocks.push({{kind:'link', text, href: el.href}});
    else if (tag === 'table') blocks.push({{kind:'table', text, rows:Array.from(el.rows).slice(0,12).map(r => Array.from(r.cells).slice(0,8).map(c => clean(c.innerText)))}});
    else blocks.push({{kind:'paragraph', text}});
  }}
  const counters = {{link:0, button:0, input:0, select:0, textarea:0}}; const elements = [];
  for (const el of document.querySelectorAll('a[href],button,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[onclick]')) {{
    if (elements.length >= maxElements) break; if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase(); const role = el.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'button' ? 'button' : tag);
    let kind = tag === 'a' ? 'link' : tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : tag === 'input' ? 'input' : role === 'link' ? 'link' : 'button';
    counters[kind] = (counters[kind] || 0) + 1; const handle = `${{kind}}:${{counters[kind]}}`; el.setAttribute('data-agent-browser-handle', handle);
    elements.push({{node_id: handle, handle, tag, role, text: clean(el.innerText || el.textContent), label: labelFor(el), href: el.href || null, selector: `[data-agent-browser-handle="${{handle}}"]`, fallback_selector: cssPath(el), bounding_box: box(el), visible: true, disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true', input_type: el.type || null, value: ('value' in el ? String(el.value).slice(0,200) : null), placeholder: el.placeholder || null}});
  }}
  const bodyText = clean((document.body && document.body.innerText) || '');
  let bodyHash = 0;
  for (let i = 0; i < bodyText.length; i++) bodyHash = ((bodyHash << 5) - bodyHash + bodyText.charCodeAt(i)) | 0;
  const live_signature = {{url: location.href, title: document.title, readyState: document.readyState, body_text_hash: String(bodyHash >>> 0), dom_node_count: document.getElementsByTagName('*').length, timestamp: Date.now()}};
  return {{revision: window.__agentBrowserPageMarkdownRevision, url: location.href, title: document.title, blocks, elements, maxBlocks, maxElements, warnings: [], stable: document.readyState === 'complete', live_signature}};
}})()
"""

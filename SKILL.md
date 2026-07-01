# Agent Browser Skill

Use this skill when the task needs browser automation inside the LocalTopSH per-user sandbox: opening sites, inspecting UI, filling forms, screenshots, persistent login sessions, classic noVNC/manual desktop, downloads, or Saby/SBIS tender export.

All browser work must go through `skill_agent-browser_browser`. Do not use raw shell browser commands.

If the user explicitly names `agent-browser` and asks for a concrete browser action, load `skill_agent-browser_browser` immediately and call the relevant `action`. Do not browse `/data/skills/...` or read local reference files first unless the tool response is ambiguous.

- If workspace is above limit, do not use `run_command`, `rm`, `du`, or `find`; use `skill_agent-browser_browser(action=cleanup, aggressive=true)` first.

## Choose Workflow

Primary browser workflow is universal and Markdown-node-first. Do not start by choosing a site-specific/date/forum/search extractor.

1. Open or attach to the page (`desktop_open` for interactive/live browser sessions; `open`/`wait_ready` only for simple non-interactive pages).
2. Call `page_markdown`.
3. Call `read_page_md` when the Markdown artifact is returned, then reason over the Markdown content and listed revision-scoped UI `node_id` values.
4. Choose the revision-scoped `node_id` that best advances the user task: a result link, table row control, forum page link, search result, account menu, filter, “next”, “show more”, “load more”, submit button, etc.
5. Call `page_markdown.act node_id=<id> node_action=click|fill|type|select|submit revision=<revision>` for page-changing actions. It performs the DOM action and returns refreshed `action_page_markdown`; use that as the next state.
6. Repeat the inspect -> decide -> act -> refreshed-Markdown loop until the task is solved or bounded attempts are exhausted.

This loop is the main workflow for catalogs, forums, search results, tables, personal accounts, SPAs, and pages with “more/next/show” controls. Specialized extractors (`extract_table`, `extract_search_results`, `extract_updates_by_date`, `extract_forum_posts`, etc.) are optional fast paths only after Markdown inspection shows they fit the page; they must not replace the general node-reasoning loop.

- Empty or unusable snapshot: if `snapshot_ok=true` but `refs_count=0`, `title=(unknown)`, or useful page text is missing, read the exact returned `snapshot_file` with `read_artifact`; if still unusable, use `desktop_open` -> `page_markdown` before trying `screenshot`.
- Authenticated site: use `login` with a stable `profile`; see `reference/auth-and-profiles.md`, then continue with `page_markdown`.
- Manual desktop or classic noVNC: use `manual_desktop` or `desktop_open`; see `reference/manual-desktop-and-novnc.md`, then continue with `page_markdown`.
- Captcha or Cloudflare handoff: use `challenge_detected`, wait for the user, then `continue_after_manual`; see `reference/manual-desktop-and-novnc.md`.
- Protected browser artifacts: use `read_artifact`/`read_page_md` instead of `read_file` or shell commands.
- Pagination, date, forum, table, and search-result tasks: first inspect Markdown and use visible controls through `page_markdown.act`. `navigate_pagination` and typed extractors are compatibility/fast-path helpers only when the Markdown loop indicates they are appropriate. Continue navigating/reading until you extract the requested data; do not stop after only opening the page or sending a screenshot.
- Saby/SBIS export: use `profile=saby`, `desktop_open`, and `saby_tenders_csv`; see `reference/saby-export.md`.
- Saby/SBIS subscription/sidebar filter: pass `subscription_text=...` to `saby_tenders_csv` so the collector selects the left-menu item in-page instead of slow manual clicking.
- Downloads or artifact retrieval: use `downloads`; see `reference/artifacts-and-downloads.md`.
- Busy state, cleanup, or crash recovery: use `status`, `cleanup`, `close`, or `recover`; see `reference/errors-and-recovery.md`.

## Fast Paths

- Explicit `agent-browser` request with one concrete site task: load `skill_agent-browser_browser` and call the relevant `action` immediately.
- Direct Saby export: `desktop_open profile=saby url=...` -> `saby_tenders_csv profile=saby mode=yesterday`.
- Manual confirmation follow-up after a browser handoff: call `continue_after_manual` on the same `profile` and `url`. Do not require an exact confirmation word.
- If `snapshot`, `desktop_snapshot`, `desktop_open`, or `evaluate` returns `*_file` paths, use `read_artifact`/`read_page_md` to inspect protected content instead of `read_file`, `run_command`, or large raw `evaluate` dumps. Prefer the `page_markdown`/`read_page_md` next call when present.
- An exact returned `text_file` has priority over the artifact run directory. Do not pass the artifact directory to `read_artifact` while a `text_file` path is present or pending. Directory reads are only a fallback when no exact `*_file` path is available.
- If you need to read/search the current page but do not have the exact Markdown artifact path in context, call `page_markdown` again or use `search_artifact`; `smart_read`/`find_text` remain legacy compatibility helpers for active text artifacts.
- If tool metadata contains `required_next_tool_call`, treat it as mandatory unless the user explicitly changes the task or the page shows a challenge. Do not substitute screenshot, raw evaluate, shell, repeated artifact-directory reads, or `max_chars` changes for that call.
- For date/forum/table/search extraction, inspect Markdown first, then use `page_markdown.act` on visible navigation/filter/search/show-more controls. Use artifact `query`/`regex`, `navigate_pagination`, or specialized extractors only as optional fast paths after Markdown shows they fit.
- When a manual desktop session is already active for the same profile, generic actions like `open`, `snapshot`, `click`, `fill`, and `wait` should stay on the live desktop session instead of starting a second Chrome daemon.

## Hard Rules

- Do not use `run_command` for Chrome, noVNC, x11vnc, websockify, or raw browser scripting.
- Do not ask the user to send passwords, OTPs, recovery codes, bearer tokens, or API keys in chat.
- Keep files inside the current workspace-managed paths only.
- Use `profile=saby` for `saby.ru`, `sso.saby.ru`, and `trade.saby.ru`.
- If `collection_complete=false`, report the CSV as partial and stop after sending it.
- If `agent_browser_busy=true` or `manual_browser_busy=true`, do not start a second browser flow through shell commands.
- If the tool output already contains `next_step:` or `next_tool_call`, follow that directly instead of searching for more tools or reading local skill files.
- Do not use `read_file` or shell tools to open files under `browser-artifacts/`; use `read_artifact`.
- Prefer exact file paths with `read_artifact`, especially returned `snapshot_file`, `state_file`, `text_file`, or another `*_file`. If only an artifact run directory is available, pass it to `read_artifact`; the tool will auto-select the best readable text/json artifact.
- Do not use `screenshot` as the first recovery step for an empty snapshot, and do not substitute a screenshot for requested textual extraction unless the user explicitly asked for an image or visual proof.
- Do not use raw `fetch_page`, `action=run`, or large raw `evaluate` dumps for page text or HTML. Use `page_markdown`/`read_page_md` and act with `page_markdown.act`; typed extractors and `navigate_pagination` are optional fast paths only after Markdown inspection.
- When the user explicitly asks to use agent-browser, do not use `fetch_page`, `curl`, `wget`, Python `requests`, BeautifulSoup/`bs4`, `lxml` parser scripts, `pip install`, `run_command`, or other shell/network fallbacks for page content. Use only `skill_agent-browser_browser` actions (`desktop_open` → `page_markdown` → `read_page_md` → `page_markdown.act`/`search_artifact`/typed extractors).
- Raw `evaluate` is forbidden for ordinary browsing tasks and the normal/happy path. Use the Markdown-node workflow instead. `evaluate` is only allowed when explicitly passed `allow_unsafe_eval=true`; otherwise it returns `RAW_EVAL_DISABLED`/`VALIDATION_ERROR` with a `suggested_next_action`.

## References

- `reference/operating-model.md`
- `reference/actions.md`
- `reference/auth-and-profiles.md`
- `reference/manual-desktop-and-novnc.md`
- `reference/saby-export.md`
- `reference/artifacts-and-downloads.md`
- `reference/errors-and-recovery.md`
- `reference/security.md`

## Examples

- `examples/open-and-snapshot.md`
- `examples/login-flow.md`
- `examples/saby-fresh-sandbox.md`
- `examples/saby-resume-partial.md`
- `examples/manual-challenge.md`

## Versioning

Update `skill.json.version` and `CHANGELOG.md` on every release.

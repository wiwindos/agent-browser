Use this skill only for explicit browser automation, live site interaction, Saby/SBIS export, UI testing, login flows, manual desktop/noVNC, or protected browser artifacts.
First tool: `skill_agent-browser_browser`.
Preferred starts:
- Generic site task: `action=open`, then `action=snapshot`.
- Saby/SBIS: `profile=saby`, then `action=desktop_open` or `action=saby_tenders_csv`.
- Saby subscription export: prefer `action=saby_tenders_csv profile=saby subscription_text=<left menu text> mode=yesterday`; do not manually click the sidebar if the text is known.
- Existing browser artifact path: `action=read_artifact`.
Snapshot artifact rule:
- When a browser action returns `snapshot_file`, `state_file`, `text_file`, or any `*_file`, pass that exact file path to `action=read_artifact`.
- Prefer exact `*_file` paths. If only an artifact run directory like `browser-artifacts/<site>/<timestamp>/` is available, pass it to `read_artifact`; it will auto-select a readable artifact.
Empty snapshot fallback:
- If `snapshot_ok=true` but `refs_count=0`, `title=(unknown)`, or useful page text is missing, first call `action=read_artifact` on the exact returned `snapshot_file`.
- If the artifact is still unusable, switch to `action=desktop_open` with the same `profile`/`url`, then `action=desktop_snapshot`.
- Do not call `screenshot` just to recover from an empty snapshot unless the user explicitly asked for an image or diagnostics.
Forum/date extraction:
- If the user asks what was new yesterday/on a specific date, keep navigating and reading artifacts until you extract dated posts/items for that date; do not answer with only "opened the page" or a screenshot.
- After `desktop_open`/`desktop_snapshot`, follow the exact `next_tool_call`/`text_file` path with `read_artifact`, then use `navigate_pagination`, links/buttons, or in-page search to reach the relevant date. Do not use screenshots, `read_file`, `run_command`, raw `fetch_page`, large raw `evaluate`, or `action=run` as substitutes for extracting page text.
Hard rules:
- Do not use shell commands for browser work.
- Do not use `read_file` on `browser-artifacts/`; use `read_artifact`.
- If tool output already contains `next_step:` or `next_tool_call`, follow it directly.

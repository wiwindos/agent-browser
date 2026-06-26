# Agent Browser Skill

Use this skill when the task needs browser automation inside the LocalTopSH per-user sandbox: opening sites, inspecting UI, filling forms, screenshots, persistent login sessions, classic noVNC/manual desktop, downloads, or Saby/SBIS tender export.

All browser work must go through `skill_agent-browser_browser`. Do not use raw shell browser commands.

If the user explicitly names `agent-browser` and asks for a concrete browser action, load `skill_agent-browser_browser` immediately and call the relevant `action`. Do not browse `/data/skills/...` or read local reference files first unless the tool response is ambiguous.

## Choose Workflow

- Normal webpage: `open` -> `snapshot` -> `click` / `fill` / `wait` -> `screenshot`.
- Generic multi-step browser task: call `action=skills skill=core full=true` first, then continue through the single `browser` tool.
- Authenticated site: use `login` with a stable `profile`; see `reference/auth-and-profiles.md`.
- Manual desktop or classic noVNC: use `manual_desktop` or `desktop_open`; see `reference/manual-desktop-and-novnc.md`.
- Captcha or Cloudflare handoff: use `challenge_detected`, wait for the user, then `continue_after_manual`; see `reference/manual-desktop-and-novnc.md`.
- Protected browser artifacts: use `read_artifact` instead of `read_file` or shell commands.
- Thread/forum pagination: use `navigate_pagination target=last|next|prev|first` instead of raw `evaluate` when possible.
- Saby/SBIS export: use `profile=saby`, `desktop_open`, and `saby_tenders_csv`; see `reference/saby-export.md`.
- Downloads or artifact retrieval: use `downloads`; see `reference/artifacts-and-downloads.md`.
- Busy state, cleanup, or crash recovery: use `status`, `cleanup`, `close`, or `recover`; see `reference/errors-and-recovery.md`.

## Fast Paths

- Explicit `agent-browser` request with one concrete site task: load `skill_agent-browser_browser` and call the relevant `action` immediately.
- Direct Saby export: `desktop_open profile=saby url=...` -> `saby_tenders_csv profile=saby mode=yesterday`.
- Manual confirmation follow-up after a browser handoff: call `continue_after_manual` on the same `profile` and `url`. Do not require an exact confirmation word.
- If `snapshot`, `desktop_snapshot`, `desktop_open`, or `evaluate` returns `*_file` paths, use `read_artifact` to inspect the protected full content instead of `read_file`, `run_command`, or large raw `evaluate` dumps.
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
- `read_artifact` requires a file path. Do not pass a directory path.
- Do not use large raw `evaluate` dumps for page text or HTML if `snapshot`, `desktop_snapshot`, `read_artifact`, or `navigate_pagination` can answer the question.

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

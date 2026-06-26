# Changelog

## 0.3.60

- Added a dedicated `AUTOLOAD.md` and linked it from `skill.json` so the current agent stack can inject a compact browser-specific prompt instead of falling back to the full `SKILL.md`.
- Kept the existing manifest triggers, tool schema, and browser runtime flow unchanged so the skill surface stays compatible with current LocalTopSH routing and admin/web listing behavior.

## 0.3.59

- Routed generic `open`, `snapshot`, `click`, `fill`, and `wait` actions onto the active live manual desktop session for the same profile so they no longer try to start a second Chrome daemon and hit `SingletonLock` conflicts.
- Treated numeric `wait text=...` values as sleep while a manual desktop session is active, which keeps chat-driven desktop flows from misusing browser-text waits as delays.
- Hardened `read_artifact` to require file paths only and clamp excerpts more aggressively.
- Changed `profile=default` with an explicit URL to resolve to the URL host profile instead of silently writing browser state into the `default` profile.

## 0.3.58

- Canonicalized follow-up browser profile resolution so shorthand profiles like `4pda` continue on the active `4pda.to` session instead of tripping false cross-profile busy locks.
- Added safe same-user manual-session replacement for new acquire actions, so a fresh browser task can replace an older conflicting manual desktop session inside the same sandbox instead of only stopping on `manual_browser_busy`.
- Expanded `manual_browser_busy` metadata with replacement hints and added regression coverage for both canonical follow-up profile matching and same-user session replacement.

## 0.3.57

- Added `read_artifact` so protected browser-artifact files can be inspected through the skill instead of `read_file`, `run_command`, or shell workarounds.
- Added `navigate_pagination` as a generic pagination helper for first/prev/next/last navigation in manual browser sessions without raw `evaluate` DOM scraping loops.
- Compactified `challenge_detected`, `continue_after_manual`, `manual_desktop`, and `evaluate` so they return short operational summaries while preserving full raw state and script results in artifact files.
- Reduced `evaluate` metadata/output bloat by moving full results into `evaluate-result` artifacts and returning only previews plus file paths.

## 0.3.56

- Changed heavy browser outputs to return compact operational summaries while preserving the full raw snapshot/state in artifact files under each run's `logs/` directory.
- Added `snapshot_file`, `state_file`, and `text_file` metadata for `open`, `snapshot`, `desktop_open`, and `desktop_snapshot` so agents can keep context without dragging full page dumps into chat context.
- Added regression coverage that verifies the compact outputs still persist full raw browser state to artifacts.

## 0.3.55

- Added a per-run `saby_tenders_trace.jsonl` artifact log with collector timing, pass budgets, pass results, and stop reasons so slow Saby exports can be diagnosed from the skill logs.
- Exposed the Saby trace log path in tool metadata and output for both prepared and collection flows.
- Added regression coverage that verifies the trace log is written and records collector pass events.

## 0.3.54

- Fixed a real `saby_tenders_csv` regression where partial collection could crash with `UnboundLocalError` before `complete` was assigned.
- Tightened the skill fast path so explicit `agent-browser` requests should load `skill_agent-browser_browser` immediately instead of reading local skill files first.
- Expanded skill and tool descriptions with concrete browser action names such as `desktop_open`, `continue_after_manual`, and `saby_tenders_csv` to improve action-name discovery.
- Added more directive `next_step:` output lines for manual desktop, challenge continuation, login handoff, and partial Saby export flows.
- Added a regression test that exercises partial Saby collection without the `complete` crash.

## 0.3.53

- Added generic browser workflow metadata for manual desktop, login, challenge continuation, and Saby export flows so the agent can continue browser work from structured state instead of site-specific heuristics.
- Removed exact trigger-word wording from manual browser handoff flows so follow-up confirmation can be phrased naturally instead of relying on a fixed reply like "готово".
- Added regression coverage for browser workflow metadata and updated snapshots to include the expanded machine-readable contract.

## 0.3.52

- Closed the remaining P0 contract snapshot gap by adding golden coverage for open, manual_desktop with and without URL, manual_browser_busy, and cleanup.
- Completed the implementation plan through P4 and updated IMPLEMENTATION_PLAN.md to reflect full completion.

## 0.3.51

- Completed P4 by adding persistent structured JSONL logs for browser tool runs under .agent-browser/logs/tool-runs.jsonl.
- Added a machine-readable diagnostics report via scripts/diagnostics_report.py and embedded diagnostics metadata on action=status.
- Added golden snapshot fixtures and tests plus a GitHub Actions workflow for the agent-browser skill test suite.
- Added release automation scripts for version bumps and changelog generation.

## 0.3.50

- Completed P3 by rewriting `SKILL.md` into a short router document with direct one-level links to the detailed docs.
- Added `reference/` documentation for operating model, actions, profiles, manual desktop, Saby export, artifacts, recovery, and security.
- Added focused workflow examples under `examples/`.
- Tightened `skill.json.description` so the skill advertises the product surface without embedding the full manual.

## 0.3.49

- Completed P2 by moving the active Saby collector into `scripts/agent_browser_skill/domains/saby/collector.js` and keeping `scripts/saby_tenders.js` as a synchronized compatibility copy.
- Added explicit Saby selector/config ownership in `domains/saby/selectors.json` plus dedicated CSV/state helpers in `domains/saby/csv.py` and `domains/saby/state.py`.
- Switched `actions_saby.py` to the new domain package so collector loading, continuation payloads, selector injection, and stabilized Saby metadata no longer live inline in the action module.
- Added an offline fixture runner in `domains/saby/fixture_runner.js` and coverage in `tests/test_agent_browser_skill_saby.py` that executes the real collector against saved HTML fixtures.

## 0.3.48

- Completed P1 by removing all active runtime/action imports of `legacy_impl.py`.
- Replaced the old monolithic `legacy_impl.py` with a compact compatibility shim that re-exports the refactored modules.
- Moved the remaining active dependency/process/artifact/output/path/profile helper usage onto the extracted module graph.
- Preserved the compatibility-facing `browser_tool.py` API and monkeypatch hooks while keeping the entrypoint thin.

## 0.3.47

- Continued P1 decomposition by extracting the active metadata/output/request/root/pid helper layer into `core/output.py`.
- Switched generic, batch, Saby, runner, and entrypoint imports to the new shared output helper module instead of `legacy_impl.py`.
- Updated manual challenge and auth flows to reuse extracted generic browser actions rather than calling legacy generic helpers directly.
- Updated `IMPLEMENTATION_PLAN.md` to mark the new completed shared-helper extraction work.

## 0.3.46

- Continued P1 decomposition by extracting active timeout/lock-wait parsing and boolean/integer argument coercion into `core/args.py`.
- Extracted the active sensitive/challenge/manual/recovery/resource/apt-lock regex set into `core/patterns.py`.
- Extracted Chrome and desktop dependency package lists into `runtime/constants.py`.
- Switched active dashboard, desktop, Saby, runner, and entrypoint imports away from the corresponding `legacy_impl.py` helpers/constants.
- Updated `IMPLEMENTATION_PLAN.md` so the new `+` markers reflect the completed args/patterns/constants extraction work.

## 0.3.45

- Continued P1 extraction by moving live sandbox PID/zombie/resource inspection into `runtime/sandbox_health.py`.
- Added the active artifact download listing helper to `core/artifacts.py` and switched `action_downloads` to use it.
- Switched maintenance `close` and `recover` flows to the extracted runtime/dashboard modules instead of the legacy implementations.
- Updated `IMPLEMENTATION_PLAN.md` to mark the new completed P1 extraction steps.

## 0.3.44

- Continued the remaining P1 runtime extraction by moving live dependency install/binary resolution logic into `runtime/dependencies.py`.
- Moved live sandbox bootstrap and the active browser-command recovery wrapper into `runtime/bootstrap.py`.
- Moved live dashboard URL/port/proxy orchestration into `browser/dashboard.py`.
- Switched generic, batch, manual desktop, and challenge flows to call the new runtime/dashboard modules instead of the legacy implementations.
- Updated `IMPLEMENTATION_PLAN.md` so the new `+` markers reflect the completed dashboard/bootstrap/dependency extraction work.

## 0.3.43

- Continued P1 decomposition by moving live CDP websocket/eval code into `browser/cdp.py`.
- Moved live manual-desktop helpers into `browser/desktop.py`, including page-state/navigation, screenshot/checkpoint helpers, VNC password handling, and Chrome download preference setup.
- Moved live background manual-desktop process helpers into `runtime/process.py`.
- Switched active manual desktop and Saby flows to use the new `browser/*` and `runtime/process.py` implementations while preserving the external tool contract and existing tests.
- Rewrote `IMPLEMENTATION_PLAN.md` so the `+` markers now reflect the actual completed decomposition state.

## 0.3.42

- Completed the P1 dispatcher split: `runner.py` now owns request execution and dispatches through `agent_browser_skill.actions.ACTIONS` instead of relying on `legacy_impl.run_request`.
- Added separate action modules for generic browser actions, batch/run, auth/session management, and maintenance/status/profile-alias flows.
- Kept compatibility shims in `browser_tool.py` so direct test patches and external callers still see the expected symbols while execution routes through the new registry.
- Synchronized runtime and Saby diagnostics to version `0.3.42`.

## 0.3.41

- Finished the P1 entrypoint decomposition: `scripts/browser_tool.py` is now a thin wrapper that re-exports the skill API and delegates execution to `agent_browser_skill.runner`.
- Preserved the full existing browser runtime in `agent_browser_skill/legacy_impl.py` to avoid semantic drift while finishing the module split.
- Added module boundaries for `core/artifacts.py`, `runtime/*`, `browser/*`, `actions.py`, and `runner.py`, so follow-up refactors can move implementation behind stable imports instead of editing the entrypoint directly.
- Kept existing unit-test helpers and public symbols available from `browser_tool.py` for compatibility.

## 0.3.40

- Started P1 decomposition of `browser_tool.py` into an internal `agent_browser_skill` package under `scripts/`.
- Extracted core error/result handling plus `helpers`, `profiles`, `paths`, and `locks` modules so browser/profile/artifact/manual-lease logic is no longer defined in only one file.
- Switched `browser_tool.py` to a compatibility layer that delegates runtime behavior to the new modules while preserving the existing action names, request schema, and output contract.
- Unified skill version reporting for Saby output through a shared `SKILL_VERSION` constant and bumped the collector script version to `0.3.40`.

## 0.3.39

- Started the P0 stabilization pass for `agent-browser` without changing the external `browser` tool contract.
- Added reusable request fixtures under `tests/fixtures/requests/` for `status`, alias management, cleanup, manual desktop, `open`, and fresh-sandbox `saby_tenders_csv`.
- Added initial Saby DOM fixtures under `tests/fixtures/saby/` to pin the collector's expected row/date/paging shape before deeper refactoring.
- Added runtime unit coverage for `safe_slug`, `ensure_inside`, redaction, profile aliases, manual browser lock behavior, cleanup preservation of profile cookies, and the `prepared_for_collection=true` Saby path.
- Introduced internal `ToolResult` serialization so future structured statuses/files can be added behind the current legacy JSON payload shape.

## 0.3.38

- Fixed manual browser lease compatibility. A lock created by `desktop_open`/`manual_desktop` for `profile=saby` no longer blocks same-profile automation such as `saby_tenders_csv`, `desktop_snapshot`, `desktop_screenshot`, or `evaluate`.
- `manual_browser_busy` output now reports `compatible_same_profile_action` so agents can distinguish a real cross-profile conflict from a same-profile action that should be allowed.
- Added structured `next_tool_call` to prepared and partial Saby export results. Continuation calls now explicitly use `resume_state=true` and avoid repeating `reset_state=true`.
- Manual browser lock records `state=READY` for successful leases to make status output easier to interpret.

## 0.3.37

- Fixed the Saby fresh-sandbox timeout path. `saby_tenders_csv` now starts manual desktop and returns `prepared_for_collection=true` instead of trying to bootstrap Chrome, open Saby, and collect a heavy CSV in one timed tool call.
- The Saby collection deadline is now established before any desktop startup work, so startup time is no longer invisible to the collector budget.
- Made `status` and `profile_aliases` lockless so they can report current locks/resources even while a long browser action is still running.
- Added `collect_after_start=true` as an explicit opt-in for one-call Saby startup plus collection.

## 0.3.36

- Made browser skill locking fail fast. Concurrent browser actions now return `agent_browser_busy=true` after a short wait instead of blocking until Telegram/core timeouts.
- Protected active noVNC/manual desktop sessions from accidental `recover`, `close`, or `stop_desktop` calls for a different profile. Cross-profile interruption now requires explicit `force=true`.
- `saby_tenders_csv` can start/open the manual desktop itself when `url` is provided, so a single `saby_tenders_csv profile=saby url=...` call is enough for Saby export.
- Added bounded in-tool auto-resume for Saby collection while timeout budget remains, plus an initial wait for list rows before parsing.
- Complete Saby exports release the manual browser lock by default so queued browser tasks for other profiles can run; pass `keep_manual_browser=true` to keep the session reserved.
- Saby completion now treats a stable end after older-than-target rows as a normal completion condition, while time-budget/max-click stops remain partial.
- Updated skill triggers/instructions so agents load `skill_agent-browser_browser` directly for `desktop_open`, `manual_desktop`, `noVNC`, `saby`, and `saby_tenders_csv` requests.

## 0.3.35

- Fixed fresh-sandbox Chrome bootstrap. When Chrome libraries are present but no browser binary exists yet, the skill now runs `agent-browser install` itself instead of failing with `Chrome dependencies installed, but Chrome runtime verification still fails`.
- `manual_desktop`, `start`, and recovery paths pass action context into Chrome bootstrap so a new sandbox can install both runtime libraries and the browser runtime without raw `run_command` workarounds.
- `desktop_open` now starts `manual_desktop` automatically when no desktop Chrome is running, so `desktop_open profile=... url=...` works as the first browser command in a fresh sandbox.

## 0.3.34

- Added a persistent per-sandbox manual browser lock. While one profile owns noVNC/manual desktop, another profile receives `manual_browser_busy=true` instead of starting a second Chrome/noVNC and corrupting the active session.
- `status` now reports the manual browser lock owner, action, and expiry.
- Documented that agents must not call `recover`, `close`, or another manual browser action when `manual_browser_busy=true` unless the user explicitly asks to interrupt the active browser.

## 0.3.33

- Fixed direct classic noVNC requests. `manual_desktop` now keeps public noVNC/VNC access open and returns `manual_desktop_url` plus `vnc_passcode` even when the page is already usable.
- Prevented `challenge_detected` from starting a second normal Chrome on a profile already held by manual desktop Chrome. When reusable noVNC access is running, it navigates the existing desktop Chrome through CDP instead.
- Clarified `SKILL.md`: use direct `manual_desktop` for classic noVNC/password requests; `share_session` is the agent-browser dashboard, and `challenge_detected` is only for temporary captcha/login handoff.

## 0.3.32

- Optimized Saby paging speed. Default `delay_after_click` is now 600ms instead of 2500ms, row-change polling runs every 250ms, and row-change waits are capped at 5s instead of 12s.
- Increased scroll fallback stride to about 1.8 viewports so virtualized lists advance faster when button paging is unavailable or inert.

## 0.3.31

- Strengthened incomplete Saby export instructions in tool output and `SKILL.md`: after an incomplete resumed pass, agents must send the partial CSV, stop the current agent run, and ask the user whether to continue again instead of launching another long pass in the same response.

## 0.3.30

- Fixed Saby paging activation after 0.3.29. `strongClick` now performs hover/down/up and one native `el.click()` instead of relying on a synthetic dispatched `click` event, which Saby may ignore.
- Added a scroll fallback when a detected Next button does not change rows, so misdetected or inert paging controls do not immediately end the run.

## 0.3.29

- Fixed Saby paging double-click risk: `strongClick` no longer dispatches a synthetic click and then calls `el.click()` again. This could skip batches and miss target-date tenders.
- Saby completion is now more conservative. A single newly loaded older-than-target batch no longer proves the export is complete; the collector requires multiple consecutive older batches (`older_batch_confirmations`, default `3`).
- Persisted the older-batch confirmation streak across resumed Saby runs so continuation calls do not lose completion evidence.

## 0.3.28

- `saby_tenders_csv` now preserves in-page collection state for the same target date/filter/template, so repeated calls can continue an incomplete Saby export instead of starting from scratch.
- Added `resume_state` and `reset_state` parameters. `resume_state=true` is the default; use `reset_state=true` for a fresh run.
- Added `resumed` and `next_action` diagnostics. When `collection_complete=false`, agents should report a partial CSV and ask the user whether to continue with another resumed pass.

## 0.3.27

- `saby_tenders_csv` now defaults to the maximum tool timeout for Saby collection when the caller does not pass `timeout`, giving the in-page collector about 112 seconds instead of about 52 seconds.
- Added explicit `complete` / `collection_complete` diagnostics. Time-budget, max-click, and repeated no-growth stops are marked incomplete, so agents must report partial CSVs instead of claiming the export is complete.

## 0.3.26

- `manual_desktop` now performs the same live CDP readiness check as `challenge_detected`. If the page is already usable and no known challenge text is visible, the tool returns `manual_desktop_already_clear=true`, closes public noVNC/VNC access, keeps Chrome alive internally, and tells the agent to continue with `desktop_*` actions instead of asking the user for captcha/login work.
- Manual readiness checks now treat common login/SSO screens as manual-action pages, so noVNC is not closed prematurely on an authorization form.
- `saby_tenders_csv` now passes an internal `maxRuntimeMs` budget into the in-page Saby collector. The collector stops before the outer tool timeout, returns `stopReason`, runtime diagnostics, and writes the CSV instead of failing with `TimeoutError`.
- Updated Saby diagnostics to report `skill=0.3.26`, script version, runtime budget, and elapsed runtime in the first output line.

## 0.3.25

- Chrome dependency readiness no longer trusts a persistent `chrome-runtime.ok` marker by itself. The skill now verifies the current sandbox with `ldd` and `chrome --version`, clears stale markers when runtime libraries are missing, and only writes the marker after verification passes.
- `install_browser_dependencies` now verifies Chrome after installing package sets instead of marking dependencies available blindly.

## 0.3.24

- Made Saby paging detect Next buttons through `aria-label`, broader button labels, and English `next/forward` markers.
- Added scroll fallback when no Next button is found, so virtualized Saby lists can continue loading older rows.
- Added a one-line `saby_diag` summary at the very top of `saby_tenders_csv` output for truncated logs.

## 0.3.23

- Moved Saby `stop_reason` and a compact `steps_summary` to the top of `saby_tenders_csv` output so truncated logs still show whether paging advanced.

## 0.3.22

- Added explicit `skill_version` and `script_version` lines to `saby_tenders_csv` output so logs show whether the running container picked up the latest skill files.

## 0.3.21

- Fixed Saby paging when the site reuses the same visible row count between pages. `saby_tenders_csv` now treats changed row content as a new batch instead of requiring the DOM row count to grow.
- Added Saby export `stop_reason` and per-step diagnostics to the tool output/metadata so paging failures are visible in logs.

## 0.3.20

- `challenge_detected` now polls the live noVNC/manual desktop page for up to 10 seconds before declaring that manual captcha work is required. This handles Cloudflare/Turnstile pages that auto-clear shortly after the real Chrome window starts.
- Added optional `live_check_seconds` for tuning that live desktop polling window, capped at 30 seconds.

## 0.3.19

- `challenge_detected` now verifies the live noVNC/manual desktop page immediately after starting it.
- If the live desktop is already past Cloudflare/captcha, the skill returns `manual_desktop_already_clear=true`, closes public noVNC access, keeps Chrome alive for CDP, and tells the agent to continue with `desktop_*` actions instead of asking the user to solve a captcha.

## 0.3.18

- Added generic base-domain profile canonicalization so `www.example.com`, subdomains, and short `site_key=example` with `url=https://example.com` reuse one profile without per-site hardcoding.
- Tightened manual challenge instructions: after the user replies that noVNC/captcha is done, agents must call `continue_after_manual` and continue through `desktop_*` actions instead of `curl`, `fetch_page`, or normal `open`.

## 0.3.17

- Serialized all `agent-browser` skill calls inside one sandbox to prevent overlapping scheduler/browser runs from fighting over one daemon, profile locks, ports, and `apt-get`.
- Recovery no longer starts package installation when Chrome fails because the sandbox is out of process/thread resources.
- Dependency bootstrap now skips `apt-get` when Chrome/noVNC runtime dependencies are already available, and reports apt lock contention instead of spawning more installs.
- `status` now reports process resource pressure (`pids` and zombie count) for faster diagnosis.

## 0.3.16

- Stopped creating a fresh `browser-artifacts/<site>/<timestamp>/` tree for every skill call.
- Follow-up actions now reuse the active artifact directory for the current profile/task.
- Read-only actions such as `status`, `downloads`, `profile_aliases`, and `cleanup` no longer create artifact directories.
- Automatic cleanup now removes old empty artifact directories even when the workspace is below the byte soft limit.

## 0.3.15

- Moved Saby tender collection JavaScript into `scripts/saby_tenders.js`.
- `saby_tenders_csv` now loads that JS file, supports yesterday paging by default, `mode=visible`, `target_date`, and paging controls.

## 0.3.14

- Added `saby_tenders_csv` to collect visible Saby Trade tender rows and write CSV directly from the skill.
- The Saby export no longer requires pasting large page-console scripts through `evaluate`.

## 0.3.13

- Added `downloads` to list/wait for generated files under skill-managed artifact download directories.
- Documented that agents must use `downloads` instead of generic file tools for protected `browser-artifacts/` paths.

## 0.3.12

- Added `evaluate` to execute JavaScript in the currently visible manual desktop Chrome page through CDP.
- Manual desktop Chrome now writes downloads to the skill-managed artifact `downloads/` directory, and `evaluate` reports newly created files.

## 0.3.11

- Follow-up actions such as `screenshot`, `snapshot`, `wait`, and `click` now reuse the active profile when no `profile`, `site_key`, or `url` is provided.
- This prevents the common `open profile=saby` followed by `screenshot` accidentally switching to the `default` profile and capturing a blank/wrong page.

## 0.3.10

- Fixed `status` alias formatting so `browser_tool.py` imports cleanly on Python 3.11.

## 0.3.9

- Added universal per-user profile alias groups via `.agent-browser/profile-aliases.json`.
- Added `profile_aliases` and `set_profile_alias` actions so product domains and SSO domains can share one persistent profile without code changes.
- Profile resolution now applies alias groups before falling back to hostname-derived profile names.

## 0.3.8

- Reused noVNC/manual desktop sessions now return the existing `vnc_passcode`, so the agent does not try to start a second raw noVNC proxy through shell commands.
- Tightened the Saby login handoff path: use one persistent `saby` profile and continue through desktop/CDP after the user completes login.

## 0.3.7

- `profile` now takes precedence over `site_key`, preventing accidental switches to a different Chrome profile.
- Added Saby/SBIS profile canonicalization: `saby.ru`, `sso.saby.ru`, and `trade.saby.ru` all resolve to profile `saby`.
- `login` now opens a password-protected noVNC manual session by default instead of asking the user to send passwords/OTP in chat.
- `manual_desktop` rejects/repairs accidental noVNC URLs as target URLs and falls back to the remembered target page.
- `status` now reports the remembered URL and whether the profile has a cookies database.

## 0.3.6

- Capped `open` and `batch` outputs so large SPA snapshots cannot exceed the sandbox output parser limit.
- Auto-cleanup no longer prepends a long deleted-file list to normal tool output; details are compressed into metadata.
- Cleanup now also removes runtime logs and Chrome profile caches while preserving cookies/localStorage.

## 0.3.5

- Added `cleanup` to remove old browser artifacts while preserving saved profiles/cookies.
- Added automatic browser-artifact cleanup when the workspace is above the soft limit, preventing sandbox size warnings from being appended after JSON skill output.
- Normal browser actions now close/restart the daemon when switching `site_key` profiles so `--profile ignored: daemon already running` does not silently reuse the wrong profile.
- Lowered default skill output caps to reduce context pressure on large SPA snapshots.

## 0.3.4

- noVNC manual handoff now requires a per-session VNC passcode instead of exposing an unauthenticated desktop.
- `continue_after_manual` now closes public noVNC/VNC access after the user completes the challenge while keeping Chrome alive internally for CDP-based agent actions.
- Added `close_manual_access` to explicitly close the public handoff port without killing the internal Chrome session.

## 0.3.3

- `manual_desktop` now starts Chrome with a local CDP port so the skill can inspect the exact noVNC browser session.
- Added `desktop_open`, `desktop_snapshot`, and `desktop_screenshot` for continuing Cloudflare-protected workflows inside the already-visible manual desktop.
- `continue_after_manual` now checks the live manual desktop before stopping it, avoiding false captcha loops caused by reopening the site in a separate agent-browser/headless session.
- Repeated `manual_desktop` calls without `url` now reuse the already-running live desktop instead of failing.

## 0.3.2

- `continue_after_manual` now stops the noVNC/manual desktop before reopening the profile with agent-browser.
- Added profile unlock wait before removing stale Chrome lock files.
- `recover` and `close` now stop manual desktop processes first to avoid Chrome profile contention.

## 0.3.1

- `challenge_detected` now defaults to `handoff=manual_desktop`, so Cloudflare/Turnstile handoff returns a noVNC URL instead of the agent-browser dashboard stream.
- Added `handoff` parameter to explicitly choose `manual_desktop` or `dashboard`.

## 0.3.0

- Added `manual_desktop` action: starts Xvfb, Openbox, real Chrome, x11vnc, and noVNC for server-side manual challenge completion.
- Added `stop_desktop` action to clean up noVNC/manual desktop processes.
- Added noVNC URL generation on the user's sandbox port (`PORT_BASE+8`) for cases where Cloudflare/Turnstile loops through the agent-browser dashboard.

## 0.2.2

- Fixed manual dashboard exposure by running agent-browser dashboard on internal port `4848` and exposing it through a skill-managed TCP proxy on `0.0.0.0:PORT_BASE+8`.
- Added `dashboard_internal_port` parameter.
- Updated instructions to avoid Docker-internal `172.x.x.x` addresses from `hostname -I`.

## 0.2.1

- Added `share_session` action to start the agent-browser dashboard/live viewport.
- `challenge_detected` now starts the dashboard and returns `dashboard_url`, `dashboard_port`, screenshot, and checkpoint metadata.
- Added `public_host`, `public_url`, and `dashboard_port` parameters for externally reachable manual-control links.

## 0.2.0

- Added manual challenge flow actions: `challenge_detected` and `continue_after_manual`.
- Challenge detection now saves a screenshot and `manual-challenge.json` checkpoint under the current artifact directory.
- Skill output is capped before returning JSON to avoid sandbox output truncation corrupting tool results.
- Updated instructions for Cloudflare/captcha/login handoff: detect, screenshot, ask user, wait for `готово`, verify, then continue with the same profile.

## 0.1.5

- Fixed locally installed `agent-browser` discovery across separate skill tool calls by always adding `.agent-browser/npm-global/bin` to PATH.
- Added stale Chrome profile lock cleanup after daemon crashes.
- Added `close` and `recover` actions; `clear_session` now closes the daemon before deleting the profile.

## 0.1.4

- Added self-healing for Chrome runtime failures inside the skill wrapper.
- `start install=true` now installs browser system dependencies even when `agent-browser` is already present.
- Browser commands now close a stale daemon, install Chrome dependencies, rerun `agent-browser install`, and retry once after shared-library/DevTools startup failures.

## 0.1.3

- Reverted the plan to touch core logging: this skill must stay self-contained.
- Clarified that sensitive login values should not be passed as normal tool args.

## 0.1.2

- Reserved for login safety notes; no core changes are required or expected.

## 0.1.1

- Added best-effort `agent-browser install` bootstrap after npm install.
- Removed an empty argument edge case from `open` snapshot handling.

## 0.1.0

- Added LocalTopSH `agent-browser` skill manifest.
- Added sandbox-only browser automation workflow.
- Added persistent per-user profile and artifact conventions.
- Added `browser` tool wrapper with start, skills, open, snapshot, click, fill, wait, screenshot, batch, run, login, clear_session, and status actions.

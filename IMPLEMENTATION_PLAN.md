# agent-browser Implementation Plan

Status snapshot for `workspace/_shared/skills/agent-browser` on 2026-06-06.

## P0 - Stabilization Before Refactor

+ Added request fixtures in `tests/fixtures/requests/`:
  `status.json`, `profile_aliases.json`, `set_profile_alias.json`, `cleanup.json`, `open.json`, `manual_desktop_no_url.json`, `manual_desktop_with_url.json`, `saby_prepared.json`.
+ Added Saby DOM fixtures in `tests/fixtures/saby/`:
  `saby_page_target.html`, `saby_page_older.html`.
+ Added `ToolResult` while preserving the legacy JSON payload shape.
+ Added runtime contract tests in `tests/test_agent_browser_skill_runtime.py`.
+ Covered `safe_slug`, `ensure_inside`, redaction, profile aliases, manual browser lock behavior, cleanup preserving cookies, and `saby_tenders_csv -> prepared_for_collection=true`.
+ Current targeted test command passes:
  `python -m unittest tests.test_agent_browser_skill_runtime`.
+ Added golden snapshot coverage in `tests/test_agent_browser_skill_snapshots.py` for:
  `status`, `open`, `manual_desktop` with and without `url`, `manual_browser_busy`, `cleanup`, `set_profile_alias`, and `saby_prepared`.
+ Added fixture-driven collector execution in `tests/test_agent_browser_skill_saby.py` through `domains/saby/fixture_runner.js`.
+ P0 is complete.

## P1 - Monolith Decomposition

+ `scripts/browser_tool.py` is now a thin entrypoint.
+ Created the internal package `scripts/agent_browser_skill/`.
+ Extracted core modules:
  `core/config.py`, `core/helpers.py`, `core/profiles.py`, `core/paths.py`, `core/locks.py`, `core/artifacts.py`.
+ Extracted runtime modules:
  `runtime/process.py`, `runtime/dependencies.py`, `runtime/bootstrap.py`, `runtime/sandbox_health.py`.
+ Extracted browser modules:
  `browser/cdp.py`, `browser/dashboard.py`, `browser/desktop.py`.
+ Added the dispatcher in `runner.py`.
+ Added the action registry in `actions.py`.
+ Split generic action handlers into dedicated modules:
  `actions_generic.py`, `actions_batch.py`, `actions_auth.py`, `actions_maintenance.py`.
+ Split manual/challenge/desktop/download flows into `actions_manual.py`.
+ Split Saby export flow into `actions_saby.py`.
+ `runner.py` dispatches through `agent_browser_skill.actions.ACTIONS`, not through `legacy_impl.run_request`.
+ `browser/cdp.py` now owns live CDP websocket and `Runtime.evaluate` implementations.
+ `browser/desktop.py` now owns live manual-desktop state/navigation helpers, screenshot path/checkpoint helpers, VNC password handling, and Chrome download preference setup.
+ `runtime/process.py` now owns live background-process start/stop helpers and public manual-access shutdown helpers.
+ `runtime/dependencies.py` now owns live browser dependency install, desktop dependency install, binary resolution, and `close_agent_browser`.
+ `runtime/bootstrap.py` now owns live sandbox bootstrap and the active `ab(...)` recovery wrapper used by generic and batch browser actions.
+ `browser/dashboard.py` now owns live dashboard URL/port resolution plus dashboard/proxy start-stop orchestration.
+ `runtime/sandbox_health.py` now owns live PID/zombie/resource inspection helpers.
+ `core/artifacts.py` now owns the active artifact download listing helper used by `action_downloads`.
+ Maintenance `close` and `recover` flows now call the extracted runtime/dashboard modules instead of the legacy implementations.
+ `core/args.py` now owns live timeout parsing, lock-wait parsing, and boolean/integer argument coercion helpers.
+ `core/patterns.py` now owns the active sensitive/challenge/manual/recovery/resource/apt-lock regex set.
+ `runtime/constants.py` now owns the active Chrome and desktop dependency package lists.
+ Active Saby, dashboard, desktop, runner, and entrypoint imports now use the extracted args/patterns/constants modules instead of `legacy_impl.py`.
+ `core/output.py` now owns the active metadata/output/request/root/pid helpers used by actions, runner, and the entrypoint.
+ Manual challenge and auth flows now reuse extracted `action_open`/shared helpers instead of calling legacy generic browser helpers directly.
+ Active runtime/action modules no longer import `legacy_impl.py`.
+ `legacy_impl.py` is now a compact compatibility shim instead of the old monolithic implementation.
+ `scripts/browser_tool.py` remains a thin entrypoint at 137 lines.
+ P1 is complete.

## P2 - Saby Extraction

+ Saby HTML fixtures already exist in `tests/fixtures/saby/`.
+ Active browser-side Saby collector now lives in `scripts/agent_browser_skill/domains/saby/collector.js`.
+ `scripts/saby_tenders.js` is kept as a synchronized compatibility copy.
+ Added explicit selector config in `scripts/agent_browser_skill/domains/saby/selectors.json`.
+ Added Saby domain helpers:
  `scripts/agent_browser_skill/domains/saby/csv.py`,
  `scripts/agent_browser_skill/domains/saby/state.py`,
  `scripts/agent_browser_skill/domains/saby/README.md`.
+ Added `scripts/agent_browser_skill/domains/saby/fixture_runner.js` to execute the real collector against saved HTML fixtures without a live browser.
+ Added offline collector tests in `tests/test_agent_browser_skill_saby.py`.
+ `actions_saby.py` now loads the collector, selectors, CSV serialization, continuation payloads, and stabilized Saby metadata from the dedicated domain package.
+ P2 is complete.

## P3 - Docs as Skill Product

+ `SKILL.md` is now a short router-only document.
+ Added planned reference docs:
  `reference/operating-model.md`,
  `reference/actions.md`,
  `reference/auth-and-profiles.md`,
  `reference/manual-desktop-and-novnc.md`,
  `reference/saby-export.md`,
  `reference/artifacts-and-downloads.md`,
  `reference/errors-and-recovery.md`,
  `reference/security.md`.
+ Added `examples/` with focused workflow examples.
+ `skill.json.description` now describes the skill surface without embedding the full manual.
+ P3 is complete.

## P4 - Production Hardening

+ Added persistent structured JSONL logs for tool runs in `.agent-browser/logs/tool-runs.jsonl`.
+ Added machine-readable diagnostics collection in `scripts/agent_browser_skill/runtime/diagnostics.py`.
+ Added standalone diagnostics reporting in `scripts/diagnostics_report.py`.
+ `action=status` now returns embedded diagnostics metadata.
+ Added golden snapshot tests in `tests/test_agent_browser_skill_snapshots.py`.
+ Added GitHub Actions coverage in `.github/workflows/agent-browser-skill.yml`.
+ Added version bump automation in `scripts/bump_version.py`.
+ Added changelog generation in `scripts/generate_changelog.py`.
+ P4 is complete.

## Next Practical Order

1. Current implementation plan is complete through P4.
2. Any next work should start from a new plan or a new production issue.

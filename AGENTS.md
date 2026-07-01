# AGENTS.md

This file is the root instruction set for AI agents working in this repository. Its scope is the entire repository unless a more deeply nested `AGENTS.md` overrides it.

## Mission

`agent-browser` is a Codex/agent skill that exposes safe browser automation through a single skill-owned browser tool. The repository contains the skill manifest and prompts, the Python browser-tool wrapper/runtime, domain-specific helpers, tests, examples, and reference documentation.

## Non-negotiable workflow rules

1. **Read this file first** before changing files in this repository.
2. **After every repository change, update this `AGENTS.md` when needed** so it continues to accurately describe the repository structure, file responsibilities, workflow, and agent rules.
3. **Every change must update the version and changelog.** If you modify anything in the repository, also update:
   - `skill.json` (`version` field),
   - `scripts/agent_browser_skill/version.py` (`SKILL_VERSION`),
   - `CHANGELOG.md` (new top entry describing the change).
4. Keep `skill.json.version`, `scripts/agent_browser_skill/version.py`, and the newest `CHANGELOG.md` section synchronized.
5. Prefer minimal, focused changes. Do not rewrite unrelated code or documentation.
6. Preserve backward compatibility for the public skill interface unless the task explicitly requires a breaking change. If a breaking change is unavoidable, document it in `CHANGELOG.md` and affected references.
7. Do not commit generated caches, temporary artifacts, browser profiles, secrets, or local diagnostics unless they are intentionally part of the task.
8. Do not put `try`/`except` blocks around imports.

## AI-agent development best practices

- **Plan before editing.** Identify the smallest set of files that need to change and the tests/docs/version updates required.
- **Respect existing patterns.** Match the repository's current module layout, action naming, JSON response style, and test-fixture conventions.
- **Use typed/high-level browser actions.** Browser automation guidance should favor the skill's safe typed actions over raw shell browser commands, raw CDP scripting, or large unbounded HTML dumps.
- **Keep outputs compact and artifact-backed.** New runtime behavior should return concise operational summaries and store large raw state in artifacts when appropriate.
- **Make changes observable.** Add or update tests, golden fixtures, examples, or reference docs whenever behavior changes.
- **Protect user data.** Do not expose passwords, tokens, cookies, OTPs, browser profile contents, or protected artifact paths in logs or docs.
- **Prefer deterministic tests.** Use fixtures and mocked inputs instead of live network/browser dependencies unless the task explicitly requires an integration check.
- **Fail with actionable guidance.** Error messages should explain the next safe action, especially for browser busy states, protected artifact reads, manual handoff, and validation failures.
- **Document new public actions.** If you add or change a browser action, update `skill.json`, `SKILL.md`/`AUTOLOAD.md` as applicable, `reference/actions.md`, tests, and this file if structure/responsibilities change.

## Required checks before committing

Run the narrowest meaningful checks for your change. For most repository changes, prefer:

```bash
python -m pytest tests
python -m json.tool skill.json >/dev/null
```

If you change JavaScript collectors or fixtures, also run targeted Node-based checks when available. If a check cannot run because of environment limitations, record that clearly in the final response.

## Versioning and changelog policy

- Use semantic-ish patch bumps for normal changes (for example, `0.3.68` -> `0.3.69`).
- The newest `CHANGELOG.md` entry must be at the top, directly below the `# Changelog` heading.
- Changelog entries should be concise bullets focused on user-visible or maintainer-visible behavior.
- Version-only changes are not enough: explain the actual repository change in the changelog.

## Repository structure and file responsibilities

### Root metadata and prompts

- `skill.json` — skill manifest: name, description, current version, prompt files, protected paths, exclusive browser tool, tool schema, action enum, parameters, and trigger phrases.
- `SKILL.md` — full user-facing/agent-facing operating instructions for the browser skill: workflows, fast paths, hard rules, references, examples, and release-version reminder.
- `AUTOLOAD.md` — compact autoload prompt injected by compatible agent stacks for lightweight browser-specific guidance.
- `CHANGELOG.md` — chronological release notes; newest version first.
- `README.md` — bilingual English/Russian repository overview, development workflow, and recommended checks.
- `AGENTS.md` — repository-level agent instructions, workflow rules, version/changelog policy, and structure map.
- `IMPLEMENTATION_PLAN.md` — planning notes for broader implementation work.

### Python entry points and maintenance scripts

- `scripts/browser_tool.py` — executable wrapper used by `skill.json` to run the skill-owned browser tool.
- `scripts/diagnostics_report.py` — helper for collecting diagnostics about the browser/runtime environment.
- `scripts/saby_tenders.js` — JavaScript helper for Saby/SBIS tender collection workflows.
- `scripts/bump_version.py` — version bump helper.
- `scripts/generate_changelog.py` — changelog generation/update helper.

### Core Python package: `scripts/agent_browser_skill/`

- `__init__.py` — package initialization/export surface.
- `version.py` — canonical Python `SKILL_VERSION`; must match `skill.json.version`.
- `runner.py` — command/action dispatch runner for the browser tool.
- `result.py` — result formatting/data structures returned by actions.
- `errors.py` — shared error types and error helpers.
- `legacy_impl.py` — compatibility layer for older implementation paths.
- `actions.py` — central action registry/dispatcher glue.
- `actions_generic.py` — generic page/browser actions such as open, snapshot, click, fill, wait, and extraction helpers.
- `actions_auth.py` — login/session/profile authentication actions.
- `actions_manual.py` — manual desktop/noVNC/challenge handoff actions, Markdown-node action cycle (`page_markdown.act`), and Markdown artifact reads.
- `actions_maintenance.py` — status, cleanup, close, recover, workflow-gate clearing, and maintenance actions.
- `actions_artifacts.py` — protected browser-artifact read/list/search helpers.
- `actions_extractors.py` — typed content extraction actions.
- `actions_batch.py` — batch command execution support.
- `actions_saby.py` — Saby/SBIS domain action integration.
- `extractors.py` — reusable extraction utilities.

### Core support modules: `scripts/agent_browser_skill/core/`

- `args.py` — CLI/action argument parsing and normalization.
- `action_schemas.py` — action schema definitions and validation helpers.
- `artifacts.py` — artifact path handling, artifact write/read support, workspace top-directory reporting, and browser-owned cleanup helpers.
- `config.py` — runtime configuration loading and defaults.
- `helpers.py` — shared small helper functions.
- `locks.py` — lock handling for browser/manual-session concurrency.
- `output.py` — output shaping, redaction, and compact response helpers.
- `page_markdown.py` — canonical page Markdown runtime representation (`PageMarkdownArtifact`), DOM-to-Markdown conversion, live signature capture, and revision-scoped node/action map generation.
- `paths.py` — repository/runtime path calculation.
- `patterns.py` — shared regex/string matching patterns.
- `profiles.py` — browser profile aliasing and canonical profile resolution, including built-in Saby and 4PDA aliases.
- `snapshot_artifacts.py` — snapshot artifact creation and metadata handling.
- `structured_logs.py` — structured log emission helpers.
- `tool_policy.py` — safety policy and validation for allowed/forbidden tool behavior.
- `workflow.py` — browser workflow state, next-step guidance, and continuation policy.

### Browser/runtime support: `scripts/agent_browser_skill/browser/` and `runtime/`

- `browser/cdp.py` — Chrome DevTools Protocol helpers.
- `browser/dashboard.py` — dashboard/live-session support.
- `browser/desktop.py` — manual desktop/noVNC process orchestration helpers.
- `runtime/bootstrap.py` — best-effort runtime dependency/bootstrap logic.
- `runtime/constants.py` — shared runtime constants.
- `runtime/dependencies.py` — dependency discovery and checks.
- `runtime/diagnostics.py` — diagnostics collection helpers.
- `runtime/process.py` — process execution and lifecycle helpers.
- `runtime/sandbox_health.py` — sandbox health checks.

### Domain-specific code: `scripts/agent_browser_skill/domains/`

- `domains/saby/README.md` — Saby/SBIS implementation notes.
- `domains/saby/selectors.json` — selector configuration for Saby pages.
- `domains/saby/collector.js` — in-page Saby/SBIS tender collector.
- `domains/saby/fixture_runner.js` — fixture runner for Saby collector tests/manual checks.
- `domains/saby/csv.py` — CSV formatting/export helpers for Saby tender rows.
- `domains/saby/state.py` — Saby collection state persistence/resume helpers.

### Tests and fixtures

- `tests/test_tool_policy.py` — policy/validation regression tests.
- `tests/test_extractors.py` — content extractor tests.
- `tests/test_page_markdown.py` — page markdown conversion tests.
- `tests/test_empty_snapshot_guidance.py` — empty snapshot and artifact-guidance tests.
- `tests/fixtures/requests/` — request fixture JSON inputs.
- `tests/fixtures/golden/` — expected/golden JSON outputs.
- `tests/fixtures/saby/` — Saby HTML fixtures for collector/extractor scenarios.

### Documentation and examples

- `reference/actions.md` — browser action reference.
- `reference/operating-model.md` — runtime/skill operating model.
- `reference/auth-and-profiles.md` — login and persistent profile guidance.
- `reference/manual-desktop-and-novnc.md` — manual desktop/noVNC workflow.
- `reference/saby-export.md` — Saby/SBIS tender export workflow.
- `reference/artifacts-and-downloads.md` — artifacts/download retrieval guidance.
- `reference/errors-and-recovery.md` — errors, busy states, cleanup, and recovery.
- `reference/security.md` — security and protected-path guidance.
- `examples/*.md` — runnable/user-facing workflow examples.
- `references/upstream-SKILL.md` — upstream skill reference material retained for comparison/context.

## Git hygiene

- Review `git status --short` before and after edits.
- Keep commits focused and include all required version/changelog/AGENTS updates.
- Do not include `__pycache__/`, browser artifacts, local logs, or dependency directories in new changes.

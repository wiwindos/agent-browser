# Artifacts And Downloads

Artifacts are stored under the current user workspace only.

Paths:

```text
browser-artifacts/<site-or-profile>/<timestamp>/
```

Typical contents:

```text
screenshots/
downloads/
logs/
report.md
```

Rules:

- New browser tasks create a new artifact directory.
- Follow-up actions reuse the active artifact directory for the same profile.
- Read-only follow-up actions should not create a new artifact directory by themselves.

Downloads:

- Use `downloads` to list or wait for files.
- Do not use shell discovery against `browser-artifacts/` when the skill already returned the path.

Cleanup:

- `cleanup` removes old `browser-artifacts/` runs and runtime logs.
- Saved browser profiles and cookies under `.agent-browser/profiles/` are preserved.

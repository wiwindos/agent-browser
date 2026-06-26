# Operating Model

`agent-browser` is a single skill-owned browser runtime manager for the current LocalTopSH user sandbox.

Key model:

- One external tool: `browser`.
- One protected profile store: `.agent-browser/profiles/<profile>/`.
- One protected artifact tree: `browser-artifacts/<profile-or-site>/<timestamp>/`.
- One browser runtime path controlled by the skill, not by shell commands.

Default flow:

1. Choose the action family.
2. Pass a stable `profile` for authenticated or multi-step work.
3. Let the skill create or reuse the active artifact directory.
4. Reuse follow-up state through the same profile instead of starting a new browser surface.
5. Use `downloads` and artifact paths returned by the skill instead of manual file discovery.

Operational notes:

- `action=start` is only for explicit runtime checks or bootstrap.
- `action=skills skill=core full=true` is for upstream generic browser guidance when the task is exploratory.
- `status` and `profile_aliases` are safe inspection actions.
- `cleanup` removes old artifacts while preserving profile cookies and session state.

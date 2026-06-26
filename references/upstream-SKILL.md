# Upstream agent-browser Skill Reference

Original source:

```text
https://github.com/vercel-labs/agent-browser/blob/main/skills/agent-browser/SKILL.md
```

The upstream skill is intentionally small. It tells the agent to load the real browser instructions through the CLI:

```bash
agent-browser skills get core
agent-browser skills get core --full
```

Useful specialized workflows:

```bash
agent-browser skills get dogfood
agent-browser skills get electron
agent-browser skills get vercel-sandbox
```

LocalTopSH adaptation:

- Use `skill_agent-browser_browser` instead of raw shell browser commands.
- Run only inside the current per-user Docker sandbox.
- Keep browser profiles under `.agent-browser/profiles/`.
- Keep task artifacts under `browser-artifacts/`.


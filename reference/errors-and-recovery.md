# Errors And Recovery

Busy states:

- `agent_browser_busy=true`: another browser action already owns the serialized runtime.
- `manual_browser_busy=true`: another profile already owns the manual desktop lease.

When busy:

- Wait and retry the same action later.
- Do not start a second browser flow through shell commands.
- Do not call `recover`, `close`, or `stop_desktop` for another profile unless the user explicitly wants interruption.

Recovery actions:

- `status`: inspect locks, profiles, artifacts, and resource state.
- `close`: stop the daemon and remove stale locks.
- `recover`: stronger cleanup path; can reinstall browser dependencies with `install=true`.
- `cleanup`: reclaim artifact space while preserving saved profile state.

Operational guidance:

- If Chrome crashes, the daemon is stale, or a profile lock is stuck, use `recover`.
- If PID or zombie counts are abnormally high, restart the sandbox/container rather than debugging the page itself.
- If Saby export returns a partial CSV, that is a normal resumable state, not necessarily a crash.

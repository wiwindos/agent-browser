from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] | None = None
    status: str | None = None
    files: list[str] = field(default_factory=list)

    @classmethod
    def ok(
        cls,
        output: str,
        metadata: dict[str, Any] | None = None,
        *,
        status: str | None = None,
        files: list[str] | None = None,
    ) -> "ToolResult":
        return cls(success=True, output=output, metadata=metadata, status=status, files=list(files or []))

    @classmethod
    def fail(cls, error: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(success=False, error=error, metadata=metadata)

    def to_payload(
        self,
        *,
        redact: Callable[[Any], str] | None = None,
        cap_output: Callable[[str], str] | None = None,
    ) -> dict[str, Any]:
        if redact is None:
            redact = lambda value: "" if value is None else str(value)
        if cap_output is None:
            cap_output = lambda value: value
        payload: dict[str, Any] = {"success": self.success}
        if self.success:
            payload["output"] = cap_output(redact(self.output))
        else:
            payload["error"] = redact(self.error)
        meta = dict(self.metadata or {})
        if self.status and "status" not in meta:
            meta["status"] = self.status
        if self.files and "files" not in meta:
            meta["files"] = list(self.files)
        if meta:
            payload["metadata"] = meta
        return payload

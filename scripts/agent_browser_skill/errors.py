from __future__ import annotations

from typing import Any


class ToolError(Exception):
    pass


class BrowserBusyError(ToolError):
    def __init__(self, owner: dict[str, Any]):
        super().__init__("agent-browser is busy in this sandbox")
        self.owner = owner


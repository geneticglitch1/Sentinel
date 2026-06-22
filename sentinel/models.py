"""Shared data shapes used across providers, tools, MCP, agent, and dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlannedChange(BaseModel):
    """What a mutating tool *would* do. Returned as-is on a dry run."""

    tool: str
    summary: str
    target: str | None = None
    destructive: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """The outcome of a tool call — applied or dry-run."""

    tool: str
    applied: bool
    summary: str
    planned: PlannedChange
    output: Any = None
    error: str | None = None
    ts: str = Field(default_factory=_now)

    @classmethod
    def dry_run(cls, planned: PlannedChange) -> "ActionResult":
        return cls(
            tool=planned.tool,
            applied=False,
            summary=f"DRY-RUN — {planned.summary} (pass confirm=true to apply)",
            planned=planned,
        )


class InfraStatus(BaseModel):
    """A flat snapshot the dashboard / status command renders."""

    proxmox: dict[str, Any] = Field(default_factory=dict)
    docker: dict[str, Any] = Field(default_factory=dict)
    opnsense: dict[str, Any] = Field(default_factory=dict)
    ts: str = Field(default_factory=_now)

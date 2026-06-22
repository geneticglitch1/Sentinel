"""Claude Agent SDK app + FastAPI backend.

Two things live here:

  * An in-process SDK MCP server that re-registers ``sentinel.tools`` so a Claude
    Agent SDK loop can call them — this powers one-sentence deploys and chat.
  * A small FastAPI app (``app``) the extended secdash dashboard calls for status,
    audit, security panels, and the deploy/chat console.

``claude_agent_sdk`` (and the ``claude`` CLI it drives) are imported lazily so the
rest of the package — MCP server, CLI status, tests — works without them installed.
"""

from __future__ import annotations

import inspect
import json
import typing
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from . import tools
from .config import get_settings

SYSTEM_PROMPT = """\
You are Sentinel, an operator for Aryan's homelab (Proxmox host, OPNsense firewall,
and a Docker host). You act only through the provided sentinel tools.

Rules:
- Safety first. Mutating tools default to a DRY RUN and return a plan. To actually
  apply a change you must pass confirm=true. Destructive actions (stop/reboot a VM,
  rm/stop a container, change a firewall rule, change IDS mode) REFUSE to run without
  confirm=true.
- Default behaviour: plan first. Call the tool WITHOUT confirm to show the user what
  would happen, then summarise the plan. Only pass confirm=true when the user (or the
  APPLY directive below) has authorised it.
- For a deploy request, translate the sentence into a single deploy_container call
  (and a firewall_rule only if a port must be opened). Show the rendered docker
  command in your summary.
- Be terse and concrete. Report what you did or would do; never invent results.
"""


# --------------------------------------------------------------------------
# Build SDK tools from sentinel.tools (one definition, reused)
# --------------------------------------------------------------------------
_PY_TO_JSON = {str: "string", int: "integer", bool: "boolean", float: "number", list: "array", dict: "object"}


def _json_schema(fn) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    hints = typing.get_type_hints(fn)
    for name, param in inspect.signature(fn).parameters.items():
        ann = hints.get(name, str)
        origin = typing.get_origin(ann)
        if origin is typing.Union:  # Optional[X] -> first non-None
            ann = next((a for a in typing.get_args(ann) if a is not type(None)), str)
            origin = typing.get_origin(ann)
        base = origin or ann
        props[name] = {"type": _PY_TO_JSON.get(base, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def build_sdk_server():
    """Create the in-process SDK MCP server wrapping every sentinel tool."""
    from claude_agent_sdk import create_sdk_mcp_server, tool  # lazy

    sdk_tools = []
    for name, fn in tools.ALL_TOOLS.items():
        schema = _json_schema(fn)

        def make_handler(f):
            async def handler(args: dict[str, Any]) -> dict[str, Any]:
                result = f(**args)
                return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

            return handler

        sdk_tools.append(tool(name, (fn.__doc__ or name).strip(), schema)(make_handler(fn)))

    return create_sdk_mcp_server(name="sentinel", version="0.1.0", tools=sdk_tools)


async def run_query(prompt: str, apply: bool = False, max_turns: int = 14) -> dict[str, Any]:
    """Run one agent turn. Returns collected text + the tool calls it made."""
    from claude_agent_sdk import (  # lazy
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        ToolUseBlock,
        query,
    )

    settings = get_settings()
    server = build_sdk_server()
    directive = (
        "\n\nAPPLY directive: the user has AUTHORISED changes — pass confirm=true on the "
        "tool call(s) needed to fulfil the request."
        if apply
        else "\n\nAPPLY directive: PLAN ONLY — do not pass confirm=true; show the dry-run plan."
    )
    options = ClaudeAgentOptions(
        mcp_servers={"sentinel": server},
        allowed_tools=[f"mcp__sentinel__{n}" for n in tools.ALL_TOOLS],
        system_prompt=SYSTEM_PROMPT + directive,
        model=settings.model,
        permission_mode="default",
        max_turns=max_turns,
    )

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls.append({"name": block.name, "input": block.input})
    return {"text": "\n".join(text_parts).strip(), "tool_calls": tool_calls}


# --------------------------------------------------------------------------
# FastAPI backend for the dashboard (sentinel-agent service on .217)
# --------------------------------------------------------------------------
app = FastAPI(title="sentinel-agent", version="0.1.0")


class DeployRequest(BaseModel):
    sentence: str
    confirm: bool = False


class ChatRequest(BaseModel):
    message: str
    confirm: bool = False


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return tools.infra_status()


@app.get("/api/infra")
def api_infra() -> dict[str, Any]:
    return {"vms": _safe(tools.vm_list), "containers": _safe(tools.container_list)}


@app.get("/api/audit")
def api_audit(limit: int = 50) -> list[dict[str, Any]]:
    return tools.audit_log(limit)


@app.get("/api/security")
def api_security() -> dict[str, Any]:
    return {
        "ids": _safe(tools.ids_status),
        "crowdsec": _safe(tools.crowdsec_status),
        "geo": _safe(lambda: tools.geo_attackers(10)),
        "traffic": _safe(lambda: tools.firewall_traffic(40)),
        "domains": _safe(tools.npm_domains),
    }


@app.post("/api/deploy")
async def api_deploy(req: DeployRequest) -> dict[str, Any]:
    result = await run_query(req.sentence, apply=req.confirm)
    return {**result, "audit": tools.audit_log(10)}


@app.post("/api/chat")
async def api_chat(req: ChatRequest) -> dict[str, Any]:
    result = await run_query(req.message, apply=req.confirm)
    return {**result, "audit": tools.audit_log(10)}


def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

"""One MCP client session per server, behind a single call(server, tool, args)."""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any, Optional, TextIO

import httpx2
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from mu2ebo_reporter.config import ServerSpec

SEP = "__"  # model-facing tool name: <server>__<tool>


class ToolHub:
    def __init__(self, specs: list[ServerSpec], errlog: TextIO):
        self.specs = {s.name: s for s in specs}
        self.errlog = errlog
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, Any] = {}          # model name -> mcp Tool
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "ToolHub":
        await self._stack.__aenter__()
        try:
            for spec in self.specs.values():
                await self._connect(spec)
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def _connect(self, spec: ServerSpec) -> None:
        if spec.kind == "stdio":
            params = StdioServerParameters(command=spec.command, args=spec.args, env=spec.env, cwd=spec.cwd)
            read, write = await self._stack.enter_async_context(stdio_client(params, errlog=self.errlog))
        else:
            http = httpx2.AsyncClient(headers=spec.headers, follow_redirects=True,
                                      timeout=httpx2.Timeout(30.0, read=spec.timeout))
            await self._stack.enter_async_context(http)
            read, write = await self._stack.enter_async_context(streamable_http_client(spec.url, http_client=http))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[spec.name] = session
        listed = {t.name: t for t in (await session.list_tools()).tools}
        missing = [t for t in spec.tools if t not in listed]
        if missing:
            raise RuntimeError(f"server {spec.name} lacks tools {missing}")
        for t in spec.tools:
            self.tools[f"{spec.name}{SEP}{t}"] = listed[t]

    async def call(self, server: str, tool: str, args: Optional[dict] = None) -> tuple[bool, Any]:
        """(ok, result): result is the structured content if any, else the joined text."""
        r = await self.sessions[server].call_tool(tool, args or {},
                                                  read_timeout_seconds=self.specs[server].timeout)
        if r.structured_content is not None:
            out = r.structured_content
        else:
            out = "\n".join(getattr(c, "text", "") for c in r.content)
        return (not r.is_error), out

    async def call_model_tool(self, name: str, args: dict) -> tuple[bool, Any]:
        if name not in self.tools:
            return False, f"unknown tool {name}"
        server, tool = name.split(SEP, 1)
        return await self.call(server, tool, args)

    def openai_tools(self) -> list[dict]:
        return [{"type": "function",
                 "function": {"name": n, "description": (t.description or "")[:1000],
                              "parameters": t.input_schema or {"type": "object", "properties": {}}}}
                for n, t in self.tools.items()]


def as_text(obj: Any, limit: int) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + f"... [truncated, {len(s)} chars]"

"""The model loop: OpenAI-compatible chat completions with MCP tools."""
from __future__ import annotations

import json
import time
from importlib import resources
from typing import Any, Callable

from openai import OpenAI

from mu2ebo_reporter.hub import ToolHub, as_text

TOOL_RESULT_LIMIT = 12000


def provenance(facts: dict[str, Any], model: str, trace_calls: list[dict]) -> str:
    lines = ["## Provenance", "",
             f"- Data root: `{facts.get('data_root')}` (snapshot {facts.get('snapshot_time') or 'time unknown'})",
             f"- Model: `{model}`; report written by mu2ebo-reporter from these MCP calls:"]
    lines += [f"  - `{p['server']}.{p['tool']}({json.dumps(p['args'])})`" for p in facts.get("provenance", [])]
    lines += [f"  - `{c['name'].replace('__', '.')}({json.dumps(c['args'], default=str)})` (requested by the model)"
              for c in trace_calls]
    return "\n".join(lines)


def prompt(name: str) -> str:
    return resources.files("mu2ebo_reporter.prompts").joinpath(name).read_text()


async def write_report(hub: ToolHub, client: OpenAI, model: str, facts: dict[str, Any],
                       max_turns: int, temperature: float, trace: Callable[[dict], None]) -> tuple[str, dict]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt("system.md")},
        {"role": "user", "content": prompt("report.md").format(
            prefix=facts["prefix"], study=facts["study"],
            facts=json.dumps({k: v for k, v in facts.items() if k != "provenance"}, indent=1, default=str))}]
    tools = hub.openai_tools()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "turns": 0, "tool_calls": 0}
    model_calls: list[dict] = []
    for turn in range(max_turns):
        t0 = time.time()
        resp = client.chat.completions.create(model=model, messages=messages, tools=tools or None,
                                              temperature=temperature)
        usage["turns"] += 1
        if resp.usage:
            usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            usage["completion_tokens"] += resp.usage.completion_tokens or 0
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        trace({"event": "llm", "turn": turn, "seconds": round(time.time() - t0, 2),
               "tool_calls": [c.function.name for c in calls], "usage": resp.usage.model_dump() if resp.usage else None})
        if not calls:
            return (msg.content or "").strip() + "\n\n" + provenance(facts, model, model_calls), usage
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                        for c in calls]})
        for c in calls:
            usage["tool_calls"] += 1
            try:
                args = json.loads(c.function.arguments or "{}")
                ok, out = await hub.call_model_tool(c.function.name, args)
            except Exception as e:  # a bad call is reported to the model, not fatal
                args, ok, out = c.function.arguments, False, f"{type(e).__name__}: {e}"
            model_calls.append({"name": c.function.name, "args": args})
            trace({"event": "tool", "name": c.function.name, "args": args, "ok": ok,
                   "result_chars": len(as_text(out, 10 ** 9))})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": as_text(out, TOOL_RESULT_LIMIT)})
    raise RuntimeError(f"no final report after {max_turns} turns")

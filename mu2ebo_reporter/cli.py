"""mu2ebo-report: report | facts | check | mcp-config."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import anyio

from mu2ebo_reporter import __version__, config, facts as facts_mod
from mu2ebo_reporter.check import check, render
from mu2ebo_reporter.hub import ToolHub


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--prefix", required=True, help="campaign name prefix (e.g. bpzq01)")
    p.add_argument("--study", required=True, help="study name (e.g. foilspfbpz_ax)")
    p.add_argument("--data-root", type=Path, help="Mu2eBO data root (default $AUTORESEARCH_DATA_ROOT, else yours)")
    p.add_argument("--python", default=os.environ.get("AUTORESEARCH_PYTHON", sys.executable),
                   help="interpreter for Mu2eBO's servers (default $AUTORESEARCH_PYTHON, else this one)")
    p.add_argument("--no-kb", action="store_true", help="skip DocDB context (no kb server, no MIKEY_TOKEN needed)")
    p.add_argument("--kb-query", action="append", help="kb_search query (repeatable; default: two foil queries)")
    p.add_argument("--registry", default=config.REGISTRY_URL, help="aitools MCP registry URL")
    p.add_argument("--trigger", choices=("manual", "milestone", "exit"), default="manual",
                   help="why the report is made: exit = Mu2eBO's closed_loop at loop exit, "
                        "milestone = the driving agent mid-campaign")
    p.add_argument("--note", default="", help="free text from the caller (e.g. the driver's reason), quoted in the report")


def _specs(a: argparse.Namespace, need_memory: bool = False) -> list[config.ServerSpec]:
    token = config.mikey_token()
    if not a.no_kb and not token:
        print("mu2ebo-report: MIKEY_TOKEN unset: no DocDB context (pass --no-kb to silence)", file=sys.stderr)
    if need_memory and not token:
        raise SystemExit("mu2ebo-report: --writeback needs MIKEY_TOKEN")
    return config.mu2ebo_servers(a.data_root, a.python) + \
        config.collab_servers(token, not a.no_kb, need_memory, a.registry)


async def _facts(a, specs, errlog):
    async with ToolHub(specs, errlog) as hub:
        f = await facts_mod.collect(hub, a.prefix, a.study, a.data_root,
                                    tuple(a.kb_query or facts_mod.DEFAULT_KB_QUERIES))
    f.update(trigger=a.trigger, note=a.note)
    return f


async def _report(a, specs, out: Path, errlog) -> int:
    from openai import OpenAI
    from mu2ebo_reporter.agent import write_report

    base_url, model, key_env, label = config.resolve_endpoint(a.endpoint, a.base_url, a.model)
    if not model:
        raise SystemExit(f"mu2ebo-report: endpoint {label} has no default model; pass --model")
    client = OpenAI(base_url=base_url, api_key=config.resolve_api_key(key_env, a.api_key_env, a.api_key_cmd),
                    timeout=a.llm_timeout)
    trace_f = (out / "trace.jsonl").open("a")

    def trace(ev: dict) -> None:
        ev["t"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        trace_f.write(json.dumps(ev, default=str) + "\n")
        trace_f.flush()

    run = {"version": __version__, "prefix": a.prefix, "study": a.study, "data_root": str(a.data_root),
           "trigger": a.trigger, "note": a.note,
           "endpoint": label, "base_url": base_url, "model": model, "servers": [s.redacted() for s in specs]}
    async with ToolHub(specs, errlog) as hub:
        f = await facts_mod.collect(hub, a.prefix, a.study, a.data_root,
                                    tuple(a.kb_query or facts_mod.DEFAULT_KB_QUERIES))
        f.update(trigger=a.trigger, note=a.note)
        (out / "facts.json").write_text(json.dumps(f, indent=1, default=str))
        trace({"event": "facts", "keys": sorted(f), "errors": f["errors"]})
        if f["errors"]:
            print(f"mu2ebo-report: tool errors while collecting facts: {list(f['errors'])}", file=sys.stderr)
        report, usage = await write_report(hub, client, model, {**facts_mod.compact(f), "provenance": f["provenance"]}, a.max_turns,
                                           a.temperature, trace)
        (out / "report.md").write_text(report + "\n")
        result = check(report, f)
        (out / "check.json").write_text(json.dumps(result, indent=1))
        (out / "check.txt").write_text(render(result) + "\n")
        run.update(usage=usage, check_ok=result["ok"], unsupported=len(result["unsupported"]))
        if a.writeback:
            if result["ok"] or a.writeback_unchecked:
                ok, res = await hub.call("memory", "put_document", {
                    "project": a.memory_project, "name": f"{a.prefix}-report", "content": report,
                    "keywords": f"mu2ebo,{a.study},{a.prefix}",
                    "description": f"Mu2eBO campaign report ({model}, mu2ebo-reporter {__version__})"})
                run["writeback"] = {"ok": ok, "result": res}
            else:
                run["writeback"] = {"ok": False, "result": "skipped: report failed the number check"}
    (out / "run.json").write_text(json.dumps(run, indent=1, default=str))
    trace_f.close()
    print(render(result))
    print(f"report: {out / 'report.md'}")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mu2ebo-report", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="collect facts, have the model write the report, check it")
    _common(r)
    r.add_argument("--out", type=Path, help="output dir (default <data-root>/reports/<prefix>/<UTC>)")
    r.add_argument("--endpoint", choices=sorted(config.ENDPOINTS), default=os.environ.get("MU2EBO_REPORT_ENDPOINT") or None,
                   help=f"preset (default $MU2EBO_REPORT_ENDPOINT, else $OPENAI_BASE_URL, else {config.DEFAULT_ENDPOINT})")
    r.add_argument("--base-url", help="any OpenAI-compatible /v1 URL (key from $OPENAI_API_KEY)")
    r.add_argument("--model", default=os.environ.get("MU2EBO_REPORT_MODEL") or None,
                   help="model id (default $MU2EBO_REPORT_MODEL, else per endpoint)")
    r.add_argument("--api-key-env", help="env var holding the key (default per endpoint)")
    r.add_argument("--api-key-cmd", default=os.environ.get("MU2EBO_REPORT_API_KEY_CMD") or None,
                   help="command printing the key (default $MU2EBO_REPORT_API_KEY_CMD)")
    r.add_argument("--temperature", type=float, default=0.2)
    r.add_argument("--max-turns", type=int, default=12)
    r.add_argument("--llm-timeout", type=float, default=600)
    r.add_argument("--writeback", action="store_true", help="store the report in the memory server if it passes the check")
    r.add_argument("--writeback-unchecked", action="store_true", help="store it even if the check flags numbers")
    r.add_argument("--memory-project", default="mu2ebo-reports")

    f = sub.add_parser("facts", help="only the deterministic tool reads, as JSON")
    _common(f)
    f.add_argument("--out", type=Path, help="write here instead of stdout")

    c = sub.add_parser("check", help="check an existing report against a facts.json")
    c.add_argument("report", type=Path)
    c.add_argument("facts", type=Path)

    m = sub.add_parser("mcp-config", help="print an mcpServers JSON for another harness (token as ${MIKEY_TOKEN})")
    sub.add_parser("prompt", help="print the system prompt, read-only tool lists and report outline for another harness")
    m.add_argument("--data-root", type=Path)
    m.add_argument("--python", default=os.environ.get("AUTORESEARCH_PYTHON", sys.executable))
    m.add_argument("--registry", default=config.REGISTRY_URL)

    a = ap.parse_args(argv)
    if a.cmd == "prompt":
        from mu2ebo_reporter.agent import prompt
        print(prompt("system.md"))
        print("Read-only tools to allow:", ", ".join(
            [f"autoresearch.{t}" for t in config.AUTORESEARCH_TOOLS] + [f"surrogate.{t}" for t in config.SURROGATE_TOOLS]
            + [f"kb.{t}" for t in config.KB_TOOLS]))
        print("\n" + prompt("report.md").split("FACTS:")[0].replace("{prefix}", "<prefix>").replace("{study}", "<study>"))
        return 0
    if a.cmd == "check":
        res = check(a.report.read_text(), json.loads(a.facts.read_text()))
        print(render(res))
        return 0 if res["ok"] else 1
    a.data_root = (a.data_root or config.default_data_root()).resolve()
    if a.cmd == "mcp-config":
        print(json.dumps(mcp_config(a), indent=2))
        return 0
    errlog = open(os.devnull, "w") if os.environ.get("MU2EBO_REPORT_QUIET") else sys.stderr
    if a.cmd == "facts":
        f = anyio.run(_facts, a, _specs(a), errlog)
        s = json.dumps(f, indent=1, default=str)
        a.out.write_text(s) if a.out else print(s)
        return 1 if f["errors"] else 0
    out = a.out or a.data_root / "reports" / a.prefix / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    return anyio.run(_report, a, _specs(a, need_memory=a.writeback), out, errlog)


def mcp_config(a) -> dict:
    """Claude Code / Cursor style mcpServers; tokens stay as ${MIKEY_TOKEN} for the harness to expand."""
    servers = {}
    for s in config.mu2ebo_servers(a.data_root, a.python):
        servers[s.name] = {"type": "stdio", "command": s.command, "args": s.args,
                           "env": {k: v for k, v in s.env.items() if k.startswith("AUTORESEARCH_")}}
    urls = {**config.FALLBACK_URLS, **config.registry_urls(a.registry)}
    for name in ("kb", "memory"):
        servers[name] = {"type": "http", "url": urls[name], "headers": {"Authorization": "Bearer ${MIKEY_TOKEN}"}}
    return {"mcpServers": servers}

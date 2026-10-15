"""The deterministic part: the same reads every run, no model involved."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mu2ebo_reporter.hub import ToolHub

DEFAULT_KB_QUERIES = ("stopping target foil optimization Bayesian",
                      "Genesis optimization stopping target S/sqrt(B) radiation damage")


async def collect(hub: ToolHub, prefix: str, study: str, data_root: Path,
                  kb_queries: tuple[str, ...], top: int = 10) -> dict[str, Any]:
    facts: dict[str, Any] = {"prefix": prefix, "study": study, "data_root": str(data_root)}
    rec = data_root / "autoresearch_graph_data" / prefix / "campaign.json"
    if rec.is_file():
        r = json.loads(rec.read_text())
        facts["campaign_record"] = {k: r.get(k) for k in
                                    ("study", "q", "max_evals", "picker", "executor", "context", "exit_code")}
    snap = data_root / "SNAPSHOT_TIME"
    facts["snapshot_time"] = snap.read_text().strip() if snap.is_file() else None
    calls = [("campaign_status", "autoresearch", "campaign_status", {"name_prefix": prefix}),
             ("board_campaign", "autoresearch", "leaderboard", {"study": study, "name_prefix": prefix, "top": top}),
             ("board_all", "autoresearch", "leaderboard", {"study": study, "top": 5}),
             ("surrogate_stats", "surrogate", "stats", {"problem": study})]
    if "kb" in hub.sessions:
        calls += [(f"kb_search_{i + 1}", "kb", "kb_search", {"query": q, "max_results": 5})
                  for i, q in enumerate(kb_queries)]
    errors = {}
    for key, server, tool, args in calls:
        ok, out = await hub.call(server, tool, args)
        facts[key] = out
        if not ok:
            errors[key] = out
    facts["errors"] = errors
    facts["child_states"] = _child_states(facts.get("campaign_status"))
    facts["counts"] = {"campaign_rows": _rows(facts.get("board_campaign"), prefix),
                       "board_rows_all_campaigns": (facts.get("board_all") or {}).get("n_rows")
                       if isinstance(facts.get("board_all"), dict) else None}
    facts["provenance"] = [{"server": s, "tool": t, "args": a} for _, s, t, a in calls]
    return facts


def _rows(board: Any, prefix: str) -> Any:
    st = board if isinstance(board, dict) else {}
    return sum(1 for r in st.get("rows", []) if str(r.get("config", "")).startswith(prefix)) or None


def _child_states(status: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if isinstance(status, dict):
        for c in status.get("children", []) or []:
            s = c.get("state", "unknown") if isinstance(c, dict) else "unknown"
            counts[s] = counts.get(s, 0) + 1
    return counts


def compact(facts: dict[str, Any]) -> dict[str, Any]:
    """What the model sees: status without per-child logs, boards, stats, kb text."""
    out = {k: v for k, v in facts.items() if k != "provenance"}
    st = facts.get("campaign_status")
    if isinstance(st, dict):
        st = dict(st)
        parent = dict(st.get("parent") or {})
        tail = (parent.get("log_tail") or "").splitlines()
        parent["log_tail"] = "\n".join(tail[-3:])
        st["parent"] = parent
        st["children"] = [{k: c.get(k) for k in ("name", "state", "outcome", "values")}
                          for c in st.get("children", []) or [] if isinstance(c, dict)]
        out["campaign_status"] = st
    return out

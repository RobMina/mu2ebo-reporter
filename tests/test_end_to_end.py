"""Hub + facts + agent loop against fake stdio servers and a stub LLM client."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from mu2ebo_reporter import facts as facts_mod
from mu2ebo_reporter.agent import write_report
from mu2ebo_reporter.check import check
from mu2ebo_reporter.config import AUTORESEARCH_TOOLS, SURROGATE_TOOLS, ServerSpec
from mu2ebo_reporter.hub import ToolHub

FAKE = str(Path(__file__).with_name("fake_mu2ebo_server.py"))


def specs():
    return [ServerSpec("autoresearch", "stdio", AUTORESEARCH_TOOLS, command=sys.executable, args=[FAKE, "autoresearch"]),
            ServerSpec("surrogate", "stdio", SURROGATE_TOOLS, command=sys.executable, args=[FAKE, "surrogate"])]


class StubLLM:
    """First turn calls one tool; second turn returns a report built from the tool result."""

    def __init__(self, report: str):
        self.report, self.calls = report, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            call = SimpleNamespace(id="c1", function=SimpleNamespace(
                name="autoresearch__leaderboard", arguments=json.dumps({"study": "toy", "top": 1})))
            msg = SimpleNamespace(content="", tool_calls=[call])
        else:
            msg = SimpleNamespace(content=self.report, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def run(coro_fn):
    return anyio.run(coro_fn)


def test_only_allowlisted_tools_exposed():
    async def go():
        async with ToolHub(specs(), sys.stderr) as hub:
            return sorted(hub.tools)
    names = run(go)
    assert "autoresearch__start_campaign" not in names and "surrogate__suggest" not in names
    assert "autoresearch__leaderboard" in names and "surrogate__stats" in names


def test_facts_report_and_check(tmp_path):
    (tmp_path / "SNAPSHOT_TIME").write_text("2026-10-15T20:39:07Z\n")
    good = "Best tq01R01_00: sob 1.41513, edep 7.58519e-06; k_0 = 1.25. Snapshot 2026-10-15T20:39:07Z."
    llm = StubLLM(good)

    async def go():
        async with ToolHub(specs(), sys.stderr) as hub:
            f = await facts_mod.collect(hub, "tq01", "toy", tmp_path, ())
            report, usage = await write_report(hub, llm, "m", facts_mod.compact(f), 4, 0.0, lambda e: None)
            return f, report, usage
    f, report, usage = run(go)
    assert f["errors"] == {} and f["child_states"] == {"scored": 2} and f["snapshot_time"].startswith("2026")
    assert usage["tool_calls"] == 1 and report.startswith(good)
    assert "## Provenance" in report and "autoresearch.leaderboard" in report and "(requested by the model)" in report
    assert f["counts"]["campaign_rows"] == 2
    assert 'FACTS.trigger' in llm.calls[0]["messages"][1]["content"]
    assert llm.calls[1]["messages"][-1]["role"] == "tool"
    assert check(report, f)["ok"]
    assert not check(report + " Correlation 0.89.", f)["ok"]


def test_turn_limit():
    class Looper(StubLLM):
        def create(self, **kw):
            self.calls.append(kw)
            call = SimpleNamespace(id="c", function=SimpleNamespace(name="nope", arguments="{}"))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[call]))],
                                   usage=None)

    async def go():
        async with ToolHub(specs(), sys.stderr) as hub:
            await write_report(hub, Looper(""), "m", {"prefix": "p", "study": "s"}, 2, 0.0, lambda e: None)
    with pytest.raises(RuntimeError, match="no final report"):
        run(go)

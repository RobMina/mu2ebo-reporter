"""Stand-in for Mu2eBO's autoresearch and surrogate stdio servers (tests only)."""
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

ROWS = [{"config": "tq01R01_00", "x": {"k_0": 1.25, "k_1": 0.5}, "values": {"sob": 1.41513, "edep": 7.58519e-06}},
        {"config": "tq01R00_00", "x": {"k_0": 2.5, "k_1": 0.75}, "values": {"sob": 1.30002, "edep": 6.1e-06}}]

which = sys.argv[1]
server = MCPServer(which)

if which == "autoresearch":
    @server.tool(structured_output=True)
    def campaign_status(name_prefix: str | None = None) -> dict[str, Any]:
        """status"""
        return {"prefix": name_prefix, "study": "toy", "parent": {"exit_code": 0, "log_tail": "a\nb\nc\nd"},
                "children": [{"name": r["config"], "state": "scored", "values": r["values"]} for r in ROWS]}

    @server.tool(structured_output=True)
    def leaderboard(study: str, name_prefix: str | None = None, top: int = 20) -> dict[str, Any]:
        """board"""
        return {"study": study, "n_rows": 2, "objective": {"name": "sob", "direction": "max"}, "rows": ROWS[:top]}

    @server.tool(structured_output=True)
    def list_studies() -> list[dict[str, Any]]:
        """studies"""
        return [{"name": "toy"}]

    @server.tool(structured_output=True)
    def show_study(name: str) -> dict[str, Any]:
        """study"""
        return {"name": name}

    @server.tool(structured_output=True)
    def start_campaign(study: str) -> dict[str, Any]:
        """must never be exposed"""
        return {"launched": True}
else:
    @server.tool(structured_output=True)
    def stats(problem: str) -> dict[str, Any]:
        """stats"""
        return {"problem": problem, "n_rows": 2,
                "objectives": [{"name": "sob", "direction": "max"}, {"name": "edep", "direction": "min"}],
                "knobs": [{"name": "k_0", "min": 0.0, "max": 3.0}, {"name": "k_1", "min": 0.0, "max": 1.0}]}

    @server.tool(structured_output=True)
    def list_problems() -> dict[str, Any]:
        """problems"""
        return {"toy": {"dims": 2}}

    @server.tool(structured_output=True)
    def predict(problem: str) -> dict[str, Any]:
        """predict"""
        return {"problem": problem}

    @server.tool(structured_output=True)
    def suggest(problem: str) -> dict[str, Any]:
        """must never be exposed"""
        return {"problem": problem}

server.run("stdio")

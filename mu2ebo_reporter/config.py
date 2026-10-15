"""Where the MCP servers and the LLM endpoint come from.

Mu2eBO's own stdio servers (service/server.py, surrogate/mcp_server.py) are
started from the Mu2eBO checkout this repo sits beside (a sibling checkout,
as surrokit, prodtools, anakit and beamkit are). The Mu2e
collaboration servers (kb, memory) are looked up in the aitools MCP registry,
with the bearer key taken from MIKEY_TOKEN as aitools' harness does.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REGISTRY_URL = "http://mu2eaigpvm01.fnal.gov:8000/registry"
FALLBACK_URLS = {"kb": "http://mu2eaigpvm01.fnal.gov:8008/mcp",
                 "memory": "http://mu2eaigpvm01.fnal.gov:8007/mcp"}

# Read-only tool allow-lists: nothing that launches, checks, stops, refits or writes.
AUTORESEARCH_TOOLS = ("list_studies", "show_study", "campaign_status", "leaderboard")
SURROGATE_TOOLS = ("list_problems", "stats", "predict")
KB_TOOLS = ("kb_search", "kb_get")

# OpenAI-compatible endpoints: (base_url, default model, env var holding the key or None if keyless).
# fnal-vllm is the aitools harness default; fnal-litellm is what Mu2eBO's first drivers used.
ENDPOINTS = {
    "fnal-vllm": ("https://vllm.fnal.gov/v1", "gpt-oss:120b", None),
    "fnal-litellm": ("https://litellm.fnal.gov/v1", None, "LITELLM_KEY"),
    "alcf-sophia": ("https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1", "openai/gpt-oss-120b", None),
    "alcf-metis": ("https://inference-api.alcf.anl.gov/resource_server/metis/api/v1", "gpt-oss-120b", None),
    "amsc-mag": ("https://mag.genesis.americansciencecloud.org/v1", "gpt-oss-120b@cborg", "AMSC_TOKEN"),
}
DEFAULT_ENDPOINT = "fnal-vllm"


@dataclass
class ServerSpec:
    name: str
    kind: str                      # "stdio" or "http"
    tools: tuple[str, ...]         # allow-list exposed to the model ("" = driver only)
    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 300.0

    def redacted(self) -> dict:
        d = dict(self.__dict__)
        d["headers"] = {k: "<redacted>" for k in self.headers}
        return d


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


MU2EBO_SIBLINGS = ("autoresearch", "Mu2eBO")  # QUICKSTART clones Mu2eBO as autoresearch


def mu2ebo_root() -> Path:
    """MU2EBO_ROOT, else a sibling checkout named autoresearch or Mu2eBO."""
    env = os.environ.get("MU2EBO_ROOT")
    cands = [Path(env)] if env else [repo_root().parent / n for n in MU2EBO_SIBLINGS]
    for root in cands:
        if (root / "service" / "server.py").is_file():
            return root
    raise SystemExit(f"mu2ebo-report: no Mu2eBO checkout at {' or '.join(map(str, cands))} "
                     "(clone this repo beside Mu2eBO, or set MU2EBO_ROOT)")


def default_data_root() -> Path:
    env = os.environ.get("AUTORESEARCH_DATA_ROOT")
    return Path(env) if env else Path("/exp/mu2e/data/users") / os.environ.get("USER", "")


def mikey_token() -> str:
    tok = os.environ.get("MIKEY_TOKEN", "").strip()
    f = os.environ.get("MIKEY_TOKEN_FILE")
    if not tok and f and Path(f).is_file():
        tok = Path(f).read_text().strip()
    return tok


def registry_urls(url: str = REGISTRY_URL, timeout: float = 10) -> dict[str, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            servers = json.load(r).get("mcpServers", {})
        return {k: v["url"] for k, v in servers.items() if "url" in v}
    except Exception as e:  # registry down: fall back to the known ports
        print(f"mu2ebo-report: registry {url} unreadable ({e}); using fallback URLs", file=sys.stderr)
        return {}


def mu2ebo_servers(data_root: Path, python: str) -> list[ServerSpec]:
    root = mu2ebo_root()
    env = {k: v for k, v in os.environ.items() if k.startswith("AUTORESEARCH_")}
    env.update(AUTORESEARCH_DATA_ROOT=str(data_root), PYTHONPATH="")
    common = dict(kind="stdio", command=python, env=env, cwd=str(root))
    return [ServerSpec("autoresearch", tools=AUTORESEARCH_TOOLS, args=[str(root / "service/server.py")], **common),
            ServerSpec("surrogate", tools=SURROGATE_TOOLS, args=[str(root / "surrogate/mcp_server.py")],
                       timeout=600.0, **common)]


def collab_servers(token: str, use_kb: bool, need_memory: bool, registry: str) -> list[ServerSpec]:
    if not token or not (use_kb or need_memory):
        return []
    urls = {**FALLBACK_URLS, **registry_urls(registry)}
    hdr = {"Authorization": f"Bearer {token}"}
    out = []
    if use_kb:
        out.append(ServerSpec("kb", kind="http", tools=KB_TOOLS, url=urls["kb"], headers=hdr))
    if need_memory:
        out.append(ServerSpec("memory", kind="http", tools=(), url=urls["memory"], headers=hdr))
    return out


def resolve_endpoint(endpoint: Optional[str], base_url: Optional[str],
                     model: Optional[str]) -> tuple[str, Optional[str], Optional[str], str]:
    """(base_url, model, key env, label): --base-url, else OPENAI_BASE_URL, else the preset."""
    if base_url or (not endpoint and os.environ.get("OPENAI_BASE_URL")):
        return base_url or os.environ["OPENAI_BASE_URL"], model, "OPENAI_API_KEY", "custom"
    name = endpoint or DEFAULT_ENDPOINT
    url, default_model, key_env = ENDPOINTS[name]
    return url, model or default_model, key_env, name


def resolve_api_key(key_env: Optional[str], override_env: Optional[str], cmd: Optional[str]) -> str:
    """--api-key-cmd, else --api-key-env, else the endpoint's own variable; keyless endpoints get a dummy."""
    if cmd:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not r.stdout.strip():
            raise SystemExit(f"mu2ebo-report: --api-key-cmd failed (rc {r.returncode}): {r.stderr.strip()[-300:]}")
        return r.stdout.strip().splitlines()[-1]
    env = override_env or key_env
    if env is None:
        return os.environ.get("OPENAI_API_KEY") or "none"
    key = os.environ.get(env, "")
    if not key:
        raise SystemExit(f"mu2ebo-report: no API key: set {env}, or pass --api-key-env/--api-key-cmd")
    return key


def quote(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)

# mu2ebo-reporter

A reporting agent for [Mu2eBO](https://github.com/Mu2e/Mu2eBO) campaigns, the "reporting agent" item of the Mu2e
Genesis Mission phase 1 optimization workflow (docdb-58092). Mu2eBO's `graph.closed_loop` starts it at every loop
exit, and the agent driving a campaign can ask for interim reports through the `start_report` MCP tool (Mu2eBO
`core/report.py`). Run by hand, it works on any campaign. It reads one campaign through Mu2eBO's own MCP servers,
adds DocDB context from the Mu2e `kb` server, has an LLM write a Markdown report, and checks every number in the
report against the tool outputs. If the check passes, it can also store the report in the Mu2e `memory` server.

It is a sibling checkout of Mu2eBO, like surrokit, prodtools, anakit and beamkit. It needs nothing beyond Mu2eBO and
the Mu2e ana 2.8.0 environment on `/cvmfs`, which already provides `mcp` 2.0, `openai` and `anyio`. It is not tied to
an agent harness: it talks to the MCP servers itself and to any OpenAI-compatible chat endpoint. By default that is
the Fermilab vLLM server the aitools harness uses. See [Using it from an agent harness](#using-it-from-an-agent-harness).

## How it works

```
Mu2eBO service/server.py   (stdio) ─┐
Mu2eBO surrogate/mcp_server.py (stdio) ─┤   1. facts: fixed read-only calls  ──> facts.json
kb      (aitools registry, HTTP)   ─┤   2. LLM writes the report (may call the read-only tools)
memory  (aitools registry, HTTP)   ─┘   3. check: every number must appear in the facts ──> check.txt
                                        4. optional write-back to memory, only if the check passed
```

- **Read-only by construction.** The model only sees allow-listed tools: `autoresearch.{list_studies, show_study,
  campaign_status, leaderboard}`, `surrogate.{list_problems, stats, predict}` and `kb.{kb_search, kb_get}`. It never
  sees `start_check`, `start_campaign`, `stop_campaign`, `suggest`, `refit` or any memory tool. The write-back is a
  call the program makes, not one the model chooses.
- **Provenance comes from the program.** The `## Provenance` section is appended from the actual calls, not written
  by the model.
- **The number check** (`mu2ebo_reporter/check.py`) flags any number in the report that no tool output contains.
  Numbers on lines citing DocDB are listed separately for a manual look. The check cannot see wrong *claims* that
  carry no new number, such as a document's conclusion transferred to the campaign, so read the report.

## Install

Clone it beside Mu2eBO, in the same directory as the other checkouts (QUICKSTART section 1):

```bash
cd /exp/mu2e/app/users/$USER
git clone https://github.com/RobMina/mu2ebo-reporter.git mu2ebo-reporter
cd autoresearch && source ./activate.sh       # sets AUTORESEARCH_PYTHON (ana 2.8.0)
../mu2ebo-../mu2ebo-reporter/bin/mu2ebo-report --help
```

The launcher finds Mu2eBO as `../autoresearch` or `../Mu2eBO`. `MU2EBO_ROOT` points it at a checkout elsewhere,
which is the same pattern as `AUTORESEARCH_SURROKIT`.

## Model endpoints

The client is the `openai` package, which is how Mu2eBO's first LLM driver called `litellm.fnal.gov`. The presets
are the endpoints the [aitools harness](https://github.com/Mu2e/aitools) offers:

| `--endpoint` | URL | Default model | Key |
|---|---|---|---|
| `fnal-vllm` (default) | `https://vllm.fnal.gov/v1` | `gpt-oss:120b` | none (on-site) |
| `fnal-litellm` | `https://litellm.fnal.gov/v1` | none, pass `--model` | `LITELLM_KEY` (aitools' variable) |
| `alcf-sophia` | ALCF inference, Sophia vLLM | `openai/gpt-oss-120b` | `--api-key-cmd`, below |
| `alcf-metis` | ALCF inference, Metis | `gpt-oss-120b` | `--api-key-cmd` |
| `amsc-mag` | AmSC Model Access Gateway | `gpt-oss-120b@cborg` | `AMSC_TOKEN` |

`--base-url URL --model ID` (key in `OPENAI_API_KEY`) reaches any other OpenAI-compatible server. When Mu2eBO
starts the reporter (at loop exit, or through its `start_report` tool) no flags are passed, so the choice goes in the
environment: `MU2EBO_REPORT_ENDPOINT`, `MU2EBO_REPORT_MODEL`, `MU2EBO_REPORT_API_KEY_CMD`. A set
`OPENAI_BASE_URL` replaces the default preset, as in the `openai` client. `--api-key-env VAR` and `--api-key-cmd CMD`
(a command that prints the key) override the key source.

ALCF tokens come from the official script, [argonne-lcf/inference-endpoints](https://github.com/argonne-lcf/inference-endpoints)
`inference_auth_token.py`. It needs `globus_sdk`, and the 30-day Globus login is interactive:

```bash
git clone https://github.com/argonne-lcf/inference-endpoints
python inference-endpoints/inference_auth_token.py authenticate      # once, interactive
export ALCF_KEYCMD="python $PWD/inference-endpoints/inference_auth_token.py get_access_token"
```

The Mu2e `kb` and `memory` MCP servers need a mikey key in `MIKEY_TOKEN` (or in a file named by `MIKEY_TOKEN_FILE`),
the variable the aitools harness uses. Without it the report has no DocDB context, and `--writeback` refuses.

## Usage

```bash
# a campaign in your own data root, on the default endpoint (vllm.fnal.gov)
../mu2ebo-reporter/bin/mu2ebo-report report --prefix bpzq01 --study foilspfbpz_ax

# another operator's campaign: snapshot it first (Mu2eBO's readers take flocks that need write access)
../mu2ebo-reporter/scripts/snapshot-campaign.sh bpzq01 /exp/mu2e/data/users/<them> /exp/mu2e/data/users/$USER/mu2ebo_snapshots/bpzq01
../mu2ebo-reporter/bin/mu2ebo-report report --prefix bpzq01 --study foilspfbpz_ax \
  --data-root /exp/mu2e/data/users/$USER/mu2ebo_snapshots/bpzq01

# ALCF Sophia instead
../mu2ebo-reporter/bin/mu2ebo-report report ... --endpoint alcf-sophia --api-key-cmd "$ALCF_KEYCMD"

# store the report in the memory server (project mu2ebo-reports) if it passes the check
../mu2ebo-reporter/bin/mu2ebo-report report ... --writeback
```

Output in `<data-root>/reports/<prefix>/<UTC>/` (or `--out`):

| File | Content |
|---|---|
| `report.md` | the report |
| `facts.json` | every deterministic tool output the report is checked against |
| `check.txt`, `check.json` | the number check; exit code 1 if any number is unsupported |
| `trace.jsonl` | one line per LLM turn and tool call (timing, token usage) |
| `run.json` | model, endpoint, servers (keys redacted), token totals, write-back result |

`--trigger exit|milestone|manual` and `--note TEXT` say why a report was asked for; Mu2eBO passes them. A milestone
report is marked interim.

Other subcommands: `facts` (only the deterministic reads), `check REPORT FACTS` (re-check an edited report),
`mcp-config` and `prompt` (for other harnesses, below).

## Using it from an agent harness

The pieces are independent of any harness. The servers are standard MCP (stdio and streamable HTTP), the
instructions are plain Markdown, and the check is a separate command.

- **Recommended:** run `mu2ebo-report report` as a shell command from goose, Claude Code, Codex or a cron job.
  The harness then only needs a shell tool, and you get the deterministic facts, the allow-list and the check.
- **Interactive:** `mu2ebo-report mcp-config --data-root ROOT` prints a `mcpServers` JSON (stdio entries for
  Mu2eBO, HTTP entries for kb and memory with `Bearer ${MIKEY_TOKEN}`) in the format Claude Code and Cursor read.
  goose and Codex take the same fields in their own config syntax (a goose `stdio` or `streamable_http`
  extension with `headers`, a Codex `[mcp_servers.<name>]` table). `mu2ebo-report prompt` prints the instructions
  and the tool allow-list. Each harness has its own way of restricting tools (goose `available_tools`, Claude Code
  permission rules), and you must apply the allow-list there. Afterwards, save the report and run
  `mu2ebo-report facts ... --out facts.json && mu2ebo-report check report.md facts.json`.

## Tests

```bash
cd ../mu2ebo-reporter && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m pytest -q
```

The tests use fake Mu2eBO stdio servers and a stub LLM client. They need no data, endpoint or network.

## License

Apache-2.0.

# PR Review Agent

AI-powered GitHub PR review agent that reads pull requests, analyzes code changes with an LLM, and takes real action — approving safe PRs or escalating to human reviewers with specific, line-cited guidance.

## Live Demo PRs

The agent was tested end-to-end against real PRs in this repo. Click any link to see the bot's actual review comments on GitHub:

| PR | Content | Conservative | Aggressive |
|----|---------|-------------|------------|
| [#1 — Auth service + API handler](https://github.com/p-sumann/numeo-github-agent/pull/1) | SQL injection, RCE, hardcoded secrets | REQUEST_CHANGES 99% | — |
| [#2 — String utilities](https://github.com/p-sumann/numeo-github-agent/pull/2) | Clean helper functions | — | APPROVE 90% |
| [#3 — LRU cache + rate limiter](https://github.com/p-sumann/numeo-github-agent/pull/3) | Thread-safety bugs, ZeroDivisionError | ESCALATE 90% | ESCALATE 90% |
| [#4 — Config loader + logger](https://github.com/p-sumann/numeo-github-agent/pull/4) | Minor .env parser issues | **ESCALATE 85%** | **APPROVE 85%** |

PR #4 demonstrates the mode difference: same code, conservative escalates while aggressive auto-approves.

## Architecture

```
main.py (CLI)
    │
    ▼
PRReviewer (orchestrator)
    │
    ├── Phase 1: Fetch PR data (metadata, files, collaborators)
    ├── Phase 2: File-level LLM review (parallelized, chunked for large PRs)
    ├── Phase 3: PR-level decision (approve vs escalate, mode-aware)
    ├── Phase 4: GitHub execution (reviews, inline comments, reviewer assignments)
    └── Phase 5: Observability report (console + JSON log)
```

**Key design decisions:**

- **Two-pass LLM pipeline** — file-level analysis produces findings with confidence scores, then a PR-level synthesis makes the approve/escalate decision. Inspired by [CodeRabbit's architecture](https://cloud.google.com/blog/products/ai-machine-learning/how-coderabbit-built-its-ai-code-review-agent-with-google-cloud-run).
- **Instructor for structured output** — Pydantic models enforced on every LLM response via [instructor](https://github.com/jxnl/instructor). No fragile JSON parsing.
- **Confidence-scored findings** — each finding gets a 0.0–1.0 confidence score. Low-confidence findings are filtered before posting to optimize for precision (insight from the [Martian Code Review Benchmark](https://github.com/withmartian/code-review-benchmark)).
- **Smart chunking** — large PRs (5K+ lines) are split into chunks ≤120K chars. Single large files are split by diff hunks.
- **GitHub App auth** — reviews posted as `numeo-gh[bot]` via GitHub App JWT auth. Falls back to personal token.
- **Full LLM observability** — every call logged with prompt, response, tokens, latency to both console and JSON file.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A GitHub App or personal access token with `repo` scope
- An OpenAI-compatible LLM endpoint

### Install

```bash
git clone https://github.com/p-sumann/numeo-github-agent.git
cd numeo-github-agent
uv sync
```

### Configure

```bash
cp .env.example .env
```

**Option A — GitHub App (bot identity):**
```env
GITHUB_APP_ID=your_app_id
GITHUB_APP_PRIVATE_KEY_PATH=path/to/private-key.pem
GITHUB_APP_INSTALLATION_ID=your_installation_id
```

**Option B — Personal token:**
```env
GITHUB_TOKEN=ghp_your_token_here
```

**LLM endpoint:**
```env
LLM_BASE_URL=http://127.0.0.1:3456/v1
LLM_API_KEY=your_api_key
LLM_MODEL=claude-opus-4-6
```

## Usage

```bash
# Conservative mode (default — biased toward escalation)
python main.py https://github.com/owner/repo/pull/123 --mode conservative

# Aggressive mode (biased toward auto-approval)
python main.py https://github.com/owner/repo/pull/123 --mode aggressive

# Dry run — analyze without writing to GitHub
python main.py https://github.com/owner/repo/pull/123 --dry-run
```

### Mode behavior

| Aspect | Conservative | Aggressive |
|--------|-------------|------------|
| Escalation threshold | Any medium+ finding | Only high/critical findings |
| Confidence filter | ≥0.5 (post more) | ≥0.8 (only high-confidence) |
| LLM temperature | 0.1 (deterministic) | 0.3 (flexible) |
| Prompt tone | Flag anything concerning | Focus on clear bugs/security |

## What the agent does

1. **Fetches PR data** — metadata, changed files with diffs, repo collaborators
2. **Reviews each file chunk** — sends diffs to the LLM with a structured review prompt
3. **Makes a decision** — synthesizes findings, applies mode thresholds, decides approve or escalate
4. **Executes on GitHub:**
   - **If APPROVE:** submits an approving review with a summary + inline comments
   - **If ESCALATE:** posts a summary review, assigns 1–3 reviewers, leaves each a targeted @-mention comment citing specific files/lines/findings

## Observability

Every LLM call is logged with:
- Prompt sent and response received
- Model used
- Token usage (prompt/completion/total)
- Latency in ms

Logs are displayed in the terminal via rich tables and saved to `logs/llm_calls.json`.

## Project structure

```
├── main.py                  # CLI entry point
├── pyproject.toml           # Dependencies and tool config
├── .env.example             # Environment variable template
├── SYSTEM-DESIGN.md         # Architecture decisions and trade-offs
└── agent/
    ├── schemas.py            # Pydantic models (findings, decisions, observability)
    ├── llm.py                # OpenAI SDK + instructor wrapper with observability
    ├── github_client.py      # GitHub REST API client with App auth (httpx + PyJWT)
    ├── prompts.py            # LLM prompt templates
    └── reviewer.py           # Core review pipeline orchestrator
```

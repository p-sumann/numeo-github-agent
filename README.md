# PR Review Agent

AI-powered GitHub PR review agent that reads pull requests, analyzes code changes with an LLM, and takes real action — approving safe PRs or escalating to human reviewers with specific, line-cited guidance.

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

- **Two-pass LLM pipeline** — file-level analysis produces findings with confidence scores, then a PR-level synthesis makes the approve/escalate decision. Inspired by CodeRabbit's architecture.
- **Confidence-scored findings** — each finding gets a 0.0–1.0 confidence score. Low-confidence findings are filtered before posting to optimize for precision (insight from the [Martian Code Review Benchmark](https://github.com/withmartian/code-review-benchmark)).
- **Smart chunking** — large PRs (5K+ lines) are split into chunks ≤120K chars. Single large files are split by diff hunks, never mid-function.
- **Mode-specific behavior** — conservative/aggressive modes differ in escalation threshold, confidence filtering, LLM temperature, and prompt tone.
- **Full LLM observability** — every call logged with prompt, response, tokens, latency to both console (rich tables) and a JSON file.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A GitHub personal access token with `repo` scope
- An OpenAI-compatible LLM endpoint (e.g., [cmappy](https://github.com/anthropics/cmappy) proxy for Claude)

### Install

```bash
git clone https://github.com/your-username/numeo-github-agent.git
cd numeo-github-agent
uv sync
```

### Configure

```bash
cp .env.example .env
# Edit .env with your tokens:
#   GITHUB_TOKEN  — GitHub PAT with repo scope
#   LLM_BASE_URL  — OpenAI-compatible endpoint (default: http://127.0.0.1:3456/v1)
#   LLM_API_KEY   — API key for the LLM endpoint
#   LLM_MODEL     — Model name (default: claude-opus-4-6)
```

## Usage

```bash
# Review a PR in conservative mode (default — biased toward escalation)
python main.py https://github.com/owner/repo/pull/123 --mode conservative

# Review in aggressive mode (biased toward auto-approval)
python main.py https://github.com/owner/repo/pull/123 --mode aggressive

# Dry run — analyze without writing to GitHub
python main.py https://github.com/owner/repo/pull/123 --mode conservative --dry-run
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
   - **If APPROVE:** submits an approving review with a structured summary + inline comments
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
└── agent/
    ├── schemas.py            # Pydantic models (findings, decisions, observability)
    ├── llm.py                # OpenAI SDK wrapper with per-call observability
    ├── github_client.py      # GitHub REST API client (httpx)
    ├── prompts.py            # LLM prompt templates
    └── reviewer.py           # Core review pipeline orchestrator
```

## AI tools used

- **Claude Code** (Claude Opus 4.6) — architecture design, code generation, research
- **cmappy** — local OpenAI-compatible proxy for Claude models

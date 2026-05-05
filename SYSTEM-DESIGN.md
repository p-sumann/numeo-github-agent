# System Design — PR Review Agent

## Problem Statement

Given a GitHub PR URL, automatically review the code changes and either auto-approve (if safe) or escalate to specific human reviewers with targeted, line-cited guidance. Must handle PRs up to 5K additions/deletions, support conservative/aggressive review modes, and provide full LLM observability.

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           CLI (main.py)                              │
│  argparse: pr_url (positional) + --mode conservative|aggressive      │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    PRReviewer (orchestrator)                          │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ GitHubClient │  │  LLMClient   │  │     Prompt Templates      │  │
│  │  (httpx)     │  │ (OpenAI SDK) │  │  (file review, decision)  │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────────────────┘  │
│         │                 │                                          │
│  ┌──────▼─────────────────▼──────────────────────────────────────┐  │
│  │                   Review Pipeline                              │  │
│  │                                                                │  │
│  │  Phase 1: Data Collection                                      │  │
│  │  ├─ GET /repos/{o}/{r}/pulls/{n}          → PR metadata        │  │
│  │  ├─ GET /repos/{o}/{r}/pulls/{n}/files    → changed files      │  │
│  │  └─ GET /repos/{o}/{r}/assignees          → collaborators      │  │
│  │                                                                │  │
│  │  Phase 2: File-Level Analysis (ThreadPoolExecutor)             │  │
│  │  ├─ Chunk files (≤120K chars per group)                        │  │
│  │  ├─ Per chunk: LLM call → structured FileReview[]              │  │
│  │  └─ Filter findings by confidence threshold                    │  │
│  │                                                                │  │
│  │  Phase 3: PR-Level Decision                                    │  │
│  │  ├─ Synthesize all findings                                    │  │
│  │  ├─ LLM call → PRDecision (approve|escalate)                   │  │
│  │  └─ Generate reviewer assignments if escalating                │  │
│  │                                                                │  │
│  │  Phase 4: GitHub Execution                                     │  │
│  │  ├─ POST review (APPROVE or COMMENT event)                     │  │
│  │  ├─ POST inline diff comments (line-specific findings)         │  │
│  │  ├─ POST requested_reviewers (assign humans)                   │  │
│  │  └─ POST issue comments (@-mention per reviewer)               │  │
│  │                                                                │  │
│  │  Phase 5: Observability                                        │  │
│  │  ├─ Rich console tables per LLM call                           │  │
│  │  └─ JSON log → logs/llm_calls.json                             │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
PR URL
  │
  ▼
Parse → (owner, repo, pr_number)
  │
  ▼
GitHub API ──────────────────────────────────────────────┐
  │                                                      │
  ├─ PR metadata (title, body, author, stats)            │
  ├─ Changed files[] (filename, status, patch, +/-)      │
  └─ Collaborators[] (potential reviewers)               │
  │                                                      │
  ▼                                                      │
Chunk files into groups ≤ 120K chars                     │
  │                                                      │
  ├─ Chunk 1 ──→ LLM ──→ FileReview[] ─┐                │
  ├─ Chunk 2 ──→ LLM ──→ FileReview[] ─┤  (parallel)    │
  └─ Chunk N ──→ LLM ──→ FileReview[] ─┤                │
                                        │                │
                                        ▼                │
                              All FileReview[]           │
                                        │                │
                                        ▼                │
                              LLM Decision Call          │
                              (mode-aware)               │
                                        │                │
                          ┌─────────────┴──────────┐     │
                          ▼                        ▼     │
                      APPROVE                  ESCALATE  │
                          │                        │     │
                          ▼                        ▼     │
                  POST /reviews            POST /reviews │
                  event=APPROVE            event=COMMENT │
                  + inline comments        + inline comments
                                           + assign reviewers
                                           + @-mention comments
```

---

## Key Design Decisions

### 1. Why two LLM passes instead of one?

A single LLM call with the entire PR would:
- Hit context limits on large PRs (5K+ lines)
- Produce lower quality reviews (attention dilution)
- Make it impossible to parallelize

The two-pass approach:
- **File-level pass**: focused analysis with confidence scoring per finding
- **PR-level pass**: synthesis + decision using structured findings (not raw diffs)

This mirrors how CodeRabbit and Claude Code /review handle reviews.

### 2. Why OpenAI SDK instead of direct HTTP?

- Standard interface — works with any OpenAI-compatible endpoint
- Clean streaming support if needed later
- Automatic retry/timeout handling
- Type-safe message construction

We point the SDK at a cmappy proxy (`localhost:3456`) that routes to Claude Opus 4.6.

### 3. Why httpx for GitHub instead of PyGithub?

- Lighter dependency (~50KB vs ~2MB)
- Full control over which API endpoints we call
- No hidden abstractions — easier to debug and defend in interview
- Async-capable if we need it later (httpx supports both sync and async)

### 4. Why ThreadPoolExecutor instead of asyncio?

- File chunk reviews are independent — pure parallelism, not I/O multiplexing
- Simpler code that's easier to reason about
- The bottleneck is LLM inference time, not Python overhead
- Avoids async contagion through the entire codebase

### 5. Why confidence scoring?

From the [Martian Code Review Benchmark](https://github.com/withmartian/code-review-benchmark): review tools are judged on **precision** (useful comments / total comments) and **recall** (issues caught / total real issues).

Low-confidence findings tank precision. By filtering at configurable thresholds:
- Conservative mode: threshold=0.5 (catch more, accept some noise)
- Aggressive mode: threshold=0.8 (high precision, may miss some)

### 6. Why inline diff comments?

GitHub's review API supports posting comments on specific diff lines:
```json
{
  "path": "src/auth.py",
  "line": 42,
  "side": "RIGHT",
  "body": "🔴 **CRITICAL** — JWT audience claim removed..."
}
```

This is vastly more useful than a wall-of-text summary. Reviewers see findings exactly where they matter. BugViper demonstrated this approach effectively.

---

## Mode Behavior — How Conservative vs Aggressive Differ

The modes aren't just a prompt change — they affect four system parameters:

| Parameter | Conservative | Aggressive |
|-----------|-------------|------------|
| Confidence threshold | 0.5 | 0.8 |
| LLM temperature | 0.1 | 0.3 |
| Escalation prompt | "Flag anything concerning" | "Only clear bugs/security" |
| Decision threshold | Any medium+ → escalate | Only high/critical → escalate |

This ensures visibly different behavior: the same PR reviewed in both modes should produce different decisions and different comment volumes.

---

## Large PR Handling Strategy

For PRs with 5K additions / 5K deletions:

1. **Paginated fetch**: GitHub returns max 100 files per page — we paginate until all files are retrieved
2. **Filter non-reviewable**: skip binary files, removed files, files without patches
3. **Chunk by size**: group files so total patch text ≤ 120K chars (~30K tokens)
4. **Split oversized files**: if a single file exceeds 120K chars, split by `@@` hunk markers
5. **Parallel review**: process chunks via ThreadPoolExecutor (max 4 workers)
6. **Synthesize, don't concatenate**: the decision LLM call receives structured findings (type, severity, confidence, line), not raw diffs

This keeps each LLM call focused and within context limits regardless of PR size.

---

## Observability Design

Every LLM call records:

```python
class LLMCallRecord:
    call_id: str           # unique identifier
    timestamp: str         # ISO 8601
    purpose: str           # "file_review_chunk_1", "pr_decision"
    model: str             # "claude-opus-4-6"
    messages: list[dict]   # full prompt (system + user messages)
    response_text: str     # full LLM response
    prompt_tokens: int     # input tokens
    completion_tokens: int # output tokens
    total_tokens: int      # total
    latency_ms: float      # wall clock time
```

**Console output**: rich table per call showing model, tokens, latency, truncated prompt/response.

**JSON log**: full records saved to `logs/llm_calls.json` — reviewable after the run.

**Summary panel**: total calls, tokens, latency printed at the end.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid PR URL | Fail fast with clear error message |
| GitHub API 404 | Raise with status code and response |
| GitHub API 403 (auth) | Suggest checking token permissions |
| LLM returns invalid JSON | Retry parse with fallback extractors, skip chunk if all fail |
| LLM decision parse fails | Default to ESCALATE (safe fallback) |
| Inline comment rejected (line not in diff) | Comment still in summary, skip inline |
| Reviewer assignment fails (permissions) | Log warning, continue with comments only |
| No collaborators found | Skip reviewer assignment, leave summary only |

---

## What I'd Add With More Time

1. **AST-aware chunking** — use Tree-sitter to split by function/class boundaries instead of raw character count
2. **Git blame context** — identify who recently touched changed files to better assign reviewers
3. **Codebase indexing** — pre-index the repo (like Greptile) for cross-file dependency analysis
4. **Verification pass** — re-check findings against actual code behavior before posting (Claude Code pattern)
5. **Webhook integration** — trigger on PR open/update events instead of manual CLI invocation
6. **Feedback loop** — thumbs up/down on posted comments to tune confidence thresholds
7. **Caching** — skip re-reviewing unchanged files when a PR is updated

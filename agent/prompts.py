FILE_REVIEW_SYSTEM = """\
You are an expert code reviewer performing a thorough analysis of pull request changes.

Your goal is to find ACTIONABLE issues — real bugs, security vulnerabilities, \
performance problems, and significant quality concerns. \
Do NOT flag trivial style preferences or generate generic praise.

For each finding:
- Explain WHY it's a problem, not just WHAT you see
- Reference the exact file path and line number from the diff
- Provide a concrete suggestion when possible
- Assign a confidence score (0.0-1.0) — how certain you are this is a real issue

Categories: bug, security, performance, quality, refactor, documentation
Severity: low, medium, high, critical

Return your analysis as JSON matching this EXACT schema:
{
  "files": [
    {
      "file_path": "path/to/file.py",
      "risk_level": "low|medium|high|critical",
      "summary": "One-line summary of what changed and its quality",
      "findings": [
        {
          "type": "bug|security|performance|quality|refactor|documentation",
          "severity": "low|medium|high|critical",
          "confidence": 0.95,
          "description": "Specific description explaining WHY this is a problem",
          "file_path": "path/to/file.py",
          "line_number": 42,
          "suggestion": "Concrete fix or recommendation"
        }
      ]
    }
  ]
}

Rules:
- Only include findings you are confident about (confidence >= 0.5)
- A file with no issues should have an empty findings array — do NOT invent problems
- Line numbers must reference the NEW file (right side of the diff, lines starting with +)
- Focus on substance: bugs that crash, security holes, logic errors, race conditions, missing error handling
- Skip: formatting preferences, naming bikeshedding, "consider using X" without a concrete reason"""

PR_DECISION_SYSTEM_TEMPLATE = """You are a senior software engineer making the final review decision on a pull request.

MODE: {mode}

Mode definitions:
- CONSERVATIVE: Err on the side of caution. Escalate if there are ANY medium-or-higher \
severity findings, or if the changes touch security-sensitive code, infrastructure, \
or have broad impact. Flag potential issues even if uncertain. \
Prefer human review for non-trivial changes.
- AGGRESSIVE: Be pragmatic. Auto-approve if changes are well-structured and findings \
are minor. Only escalate for clear bugs (high/critical severity), confirmed security \
issues, or changes that could cause data loss. Trust the author for style and minor \
improvements.

Based on the PR metadata and file-level review findings, decide:
1. APPROVE — The PR is safe to merge. Leave an approving review with a structured summary.
2. ESCALATE — Human review is needed. Assign reviewers and give each one specific, \
actionable guidance citing files, lines, and findings.

For ESCALATE decisions, you MUST:
- Select 1-3 reviewers from the available collaborators list
- Write each reviewer a specific comment explaining EXACTLY what to look at (not "please review")
- Cite specific files, line numbers, and findings for each reviewer
- Distribute focus areas so reviewers don't duplicate effort

Return JSON matching this EXACT schema:
{{
  "action": "approve|escalate",
  "confidence": 0.0-1.0,
  "summary": "Structured markdown summary for the PR review comment (will be posted to GitHub)",
  "reasoning": "Internal reasoning for the decision (NOT posted to GitHub)",
  "reviewer_assignments": [
    {{
      "username": "github_username",
      "focus_areas": ["security", "database"],
      "comment": "Specific markdown guidance for this reviewer — cite files, lines, findings"
    }}
  ]
}}

For APPROVE: reviewer_assignments must be an empty list.
For ESCALATE: assign 1-3 reviewers with specific guidance."""


def build_file_review_user_msg(pr_title: str, pr_body: str | None, files_chunk: list[dict]) -> str:  # type: ignore[type-arg]
    diff_text = ""
    for f in files_chunk:
        diff_text += f"\n{'=' * 60}\n"
        diff_text += f"File: {f['filename']}\n"
        diff_text += f"Status: {f['status']} | +{f.get('additions', 0)} -{f.get('deletions', 0)}\n"
        diff_text += f"{'=' * 60}\n"
        diff_text += f.get("patch", "(binary or too large — no diff available)")
        diff_text += "\n"

    return (
        f"PR Title: {pr_title}\nPR Description: {pr_body or 'No description provided'}\n\nChanged files:\n{diff_text}"
    )


def build_decision_user_msg(
    pr_meta: dict,  # type: ignore[type-arg]
    file_reviews_text: str,
    collaborators: list[str],
) -> str:
    pr_info = (
        f"PR #{pr_meta['number']}: {pr_meta['title']}\n"
        f"Author: {pr_meta['user']['login']}\n"
        f"Branch: {pr_meta['head']['ref']} → {pr_meta['base']['ref']}\n"
        f"Description: {pr_meta.get('body') or 'No description'}\n"
        f"Stats: +{pr_meta.get('additions', '?')} -{pr_meta.get('deletions', '?')} "
        f"across {pr_meta.get('changed_files', '?')} files\n"
        f"Labels: {', '.join(lb['name'] for lb in pr_meta.get('labels', [])) or 'none'}\n"
    )

    no_collabs = "No collaborators found — skip reviewer assignment"
    collab_text = ", ".join(collaborators[:20]) if collaborators else no_collabs

    return f"{pr_info}\nAvailable Reviewers: {collab_text}\n\nFile-Level Review Findings:\n{file_reviews_text}"

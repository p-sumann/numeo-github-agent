FILE_REVIEW_SYSTEM = """\
You are a concise code reviewer. Find real bugs, security holes, and logic errors. \
Skip style nits, naming opinions, and generic suggestions.

Rules:
- MAX 5 findings per file. Only the most important issues.
- Each finding: 1-2 sentences max. Say WHAT is wrong and WHY it breaks.
- Include file_path, line_number, and a short suggestion.
- Confidence 0.0-1.0. Only report findings with confidence >= 0.7.
- Files with no real issues get an empty findings array.

Return JSON:
{
  "files": [
    {
      "file_path": "path/to/file.py",
      "risk_level": "low|medium|high|critical",
      "summary": "One-line summary",
      "findings": [
        {
          "type": "bug|security|performance|quality|refactor|documentation",
          "severity": "low|medium|high|critical",
          "confidence": 0.95,
          "description": "What is wrong and why it matters (1-2 sentences)",
          "file_path": "path/to/file.py",
          "line_number": 42,
          "suggestion": "Short fix recommendation"
        }
      ]
    }
  ]
}"""

PR_DECISION_SYSTEM_TEMPLATE = """\
IMPORTANT: This is a NEW, INDEPENDENT request. Respond ONLY with JSON.

You are deciding whether to approve or escalate a pull request.

MODE: {mode}
- CONSERVATIVE: Escalate if ANY medium+ finding exists. Prefer human review.
- AGGRESSIVE: Only escalate for high/critical bugs or security issues. \
Auto-approve routine changes.

The summary you write will be posted as a GitHub review comment. Keep it SHORT:
- 2-3 sentence overview
- Bullet list of top findings (max 5) with file:line references
- No walls of text. Developers skim, not read.

Return JSON:
{{
  "action": "approve|escalate|request_changes",
  "confidence": 0.0-1.0,
  "summary": "Short markdown summary (posted to GitHub). Max 10 lines.",
  "reasoning": "One sentence why (NOT posted)",
  "reviewer_assignments": [
    {{
      "username": "github_username",
      "focus_areas": ["area"],
      "comment": "2-3 bullet points citing file:line"
    }}
  ]
}}"""


def build_file_review_user_msg(
    pr_title: str, pr_body: str | None, files_chunk: list[dict],  # type: ignore[type-arg]
) -> str:
    diff_text = ""
    for f in files_chunk:
        diff_text += f"\n--- {f['filename']} ({f['status']}, +{f.get('additions', 0)}"
        diff_text += f" -{f.get('deletions', 0)}) ---\n"
        diff_text += f.get("patch", "(no diff)") + "\n"

    return f"PR: {pr_title}\n\n{diff_text}"


def build_decision_user_msg(
    pr_meta: dict,  # type: ignore[type-arg]
    file_reviews_text: str,
    collaborators: list[str],
) -> str:
    adds = pr_meta.get("additions", "?")
    dels = pr_meta.get("deletions", "?")
    changed = pr_meta.get("changed_files", "?")

    no_collabs = "No collaborators found — skip reviewer assignment"
    collab_text = ", ".join(collaborators[:20]) if collaborators else no_collabs

    return (
        f"PR #{pr_meta['number']}: {pr_meta['title']}\n"
        f"Author: {pr_meta['user']['login']} | "
        f"+{adds} -{dels} across {changed} files\n\n"
        f"Reviewers: {collab_text}\n\n"
        f"Findings:\n{file_reviews_text}"
    )

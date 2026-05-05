from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from agent.github_client import GitHubClient
from agent.llm import LLMClient
from agent.prompts import (
    FILE_REVIEW_SYSTEM,
    PR_DECISION_SYSTEM_TEMPLATE,
    build_decision_user_msg,
    build_file_review_user_msg,
)
from agent.schemas import (
    Decision,
    FileReview,
    Finding,
    PRDecision,
    ReviewerAssignment,
    ReviewMode,
    Severity,
)

console = Console()

MAX_CHUNK_CHARS = 120_000
CONFIDENCE_THRESHOLDS = {
    ReviewMode.CONSERVATIVE: 0.5,
    ReviewMode.AGGRESSIVE: 0.8,
}
TEMPERATURE = {
    ReviewMode.CONSERVATIVE: 0.1,
    ReviewMode.AGGRESSIVE: 0.3,
}


class PRReviewer:
    def __init__(self, llm: LLMClient, github: GitHubClient, mode: ReviewMode, dry_run: bool = False):
        self.llm = llm
        self.github = github
        self.mode = mode
        self.dry_run = dry_run

    def review(self, pr_url: str) -> PRDecision:
        console.print(
            Panel(
                f"[bold]Reviewing PR:[/bold] {pr_url}\n[bold]Mode:[/bold] {self.mode.value}",
                title="PR Review Agent",
                border_style="blue",
            )
        )

        owner, repo, pr_number = self.github.parse_pr_url(pr_url)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching PR data from GitHub...", total=None)
            pr_meta = self.github.get_pr(owner, repo, pr_number)
            files = self.github.get_pr_files(owner, repo, pr_number)
            collaborators = self.github.get_collaborators(owner, repo, pr_meta["user"]["login"])
            progress.update(task, description=f"Fetched: {len(files)} files, {len(collaborators)} collaborators")

        console.print(f"[bold]PR #{pr_number}:[/bold] {pr_meta['title']}")
        console.print(f"[bold]Author:[/bold] {pr_meta['user']['login']}")
        adds = pr_meta.get("additions", "?")
        dels = pr_meta.get("deletions", "?")
        changed = pr_meta.get("changed_files", "?")
        console.print(f"[bold]Stats:[/bold] +{adds} -{dels} across {changed} files")
        console.print()

        reviewable = [f for f in files if f.get("patch") and f.get("status") != "removed"]
        if not reviewable:
            console.print("[yellow]No reviewable files found (all binary or removed)[/yellow]")
            decision = PRDecision(
                action=Decision.APPROVE,
                confidence=0.95,
                summary="No reviewable code changes found. All changes are binary files or deletions.",
                reasoning="Nothing to review — auto-approve.",
                file_reviews=[],
                reviewer_assignments=[],
            )
            if not self.dry_run:
                self._execute(owner, repo, pr_number, decision)
            return decision

        chunks = self._chunk_files(reviewable)
        console.print(f"[dim]Split {len(reviewable)} files into {len(chunks)} review chunks[/dim]\n")

        all_file_reviews = self._review_all_chunks(chunks, pr_meta)

        decision = self._make_decision(pr_meta, all_file_reviews, collaborators)

        console.print(
            Panel(
                f"[bold]Action:[/bold] {decision.action.value.upper()}\n"
                f"[bold]Confidence:[/bold] {decision.confidence:.0%}\n"
                f"[bold]Reasoning:[/bold] {decision.reasoning}",
                title="Decision",
                border_style="green" if decision.action == Decision.APPROVE else "red",
            )
        )

        if self.dry_run:
            console.print("[yellow]DRY RUN — skipping GitHub writes[/yellow]")
        else:
            self._execute(owner, repo, pr_number, decision)

        return decision

    def _chunk_files(self, files: list[dict]) -> list[list[dict]]:  # type: ignore[type-arg]
        chunks: list[list[dict]] = []  # type: ignore[type-arg]
        current_chunk: list[dict] = []  # type: ignore[type-arg]
        current_size = 0

        for f in sorted(files, key=lambda x: len(x.get("patch", "")), reverse=True):
            patch_size = len(f.get("patch", ""))

            if patch_size > MAX_CHUNK_CHARS:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_size = 0
                for hunk_chunk in self._split_large_file(f):
                    chunks.append([hunk_chunk])
            elif current_size + patch_size > MAX_CHUNK_CHARS:
                chunks.append(current_chunk)
                current_chunk = [f]
                current_size = patch_size
            else:
                current_chunk.append(f)
                current_size += patch_size

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [[]]

    def _split_large_file(self, file: dict) -> list[dict]:  # type: ignore[type-arg]
        patch = file.get("patch", "")
        parts = patch.split("\n@@")

        result: list[dict] = []  # type: ignore[type-arg]
        current_patch = ""
        part_num = 1

        for i, part in enumerate(parts):
            hunk = ("@@" + part) if i > 0 else part

            if len(current_patch) + len(hunk) > MAX_CHUNK_CHARS and current_patch:
                result.append({**file, "patch": current_patch, "filename": f"{file['filename']} (part {part_num})"})
                current_patch = hunk
                part_num += 1
            else:
                current_patch += ("\n" if current_patch else "") + hunk

        if current_patch:
            suffix = f" (part {part_num})" if part_num > 1 else ""
            result.append({**file, "patch": current_patch, "filename": f"{file['filename']}{suffix}"})

        return result

    def _review_all_chunks(self, chunks: list[list[dict]], pr_meta: dict) -> list[FileReview]:  # type: ignore[type-arg]
        all_reviews: list[FileReview] = []

        if len(chunks) == 1:
            reviews = self._review_chunk(chunks[0], pr_meta, 1, 1)
            all_reviews.extend(reviews)
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as executor:
                futures = {
                    executor.submit(self._review_chunk, chunk, pr_meta, i + 1, len(chunks)): i
                    for i, chunk in enumerate(chunks)
                }
                for future in as_completed(futures):
                    reviews = future.result()
                    all_reviews.extend(reviews)

        return all_reviews

    def _review_chunk(  # type: ignore[type-arg]
        self,
        chunk: list[dict],
        pr_meta: dict,
        chunk_num: int,
        total_chunks: int,  # type: ignore[type-arg]
    ) -> list[FileReview]:
        file_names = [f["filename"] for f in chunk]
        names_str = ", ".join(file_names[:5])
        suffix = "..." if len(file_names) > 5 else ""
        console.print(f"[dim]Reviewing chunk {chunk_num}/{total_chunks}: {names_str}{suffix}[/dim]")

        user_msg = build_file_review_user_msg(pr_meta["title"], pr_meta.get("body"), chunk)
        messages = [
            {"role": "system", "content": FILE_REVIEW_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        temperature = TEMPERATURE[self.mode]
        response = self.llm.chat(messages, purpose=f"file_review_chunk_{chunk_num}", temperature=temperature)

        try:
            data = self.llm.extract_json(response)
        except ValueError:
            console.print(f"[red]Failed to parse JSON from chunk {chunk_num} — skipping[/red]")
            return []

        reviews: list[FileReview] = []
        for file_data in data.get("files", []):
            findings = []
            for f in file_data.get("findings", []):
                try:
                    finding = Finding(**f)
                    if finding.confidence >= CONFIDENCE_THRESHOLDS[self.mode]:
                        findings.append(finding)
                except Exception:
                    continue

            reviews.append(
                FileReview(
                    file_path=file_data.get("file_path", "unknown"),
                    risk_level=file_data.get("risk_level", "low"),
                    summary=file_data.get("summary", ""),
                    findings=findings,
                )
            )

        return reviews

    def _make_decision(self, pr_meta: dict, file_reviews: list[FileReview], collaborators: list[str]) -> PRDecision:  # type: ignore[type-arg]
        findings_text = ""
        for fr in file_reviews:
            findings_text += f"\n### {fr.file_path} (Risk: {fr.risk_level})\n"
            findings_text += f"{fr.summary}\n"
            if fr.findings:
                for finding in fr.findings:
                    line_ref = f" (line {finding.line_number})" if finding.line_number else ""
                    findings_text += (
                        f"- [{finding.severity.upper()}] [{finding.type}] "
                        f"confidence={finding.confidence:.0%}: {finding.description}{line_ref}\n"
                    )
            else:
                findings_text += "- No issues found\n"

        system_prompt = PR_DECISION_SYSTEM_TEMPLATE.format(mode=self.mode.value.upper())
        user_msg = build_decision_user_msg(pr_meta, findings_text, collaborators)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        temperature = TEMPERATURE[self.mode]
        response = self.llm.chat(messages, purpose="pr_decision", temperature=temperature)

        try:
            data = self.llm.extract_json(response)
        except ValueError:
            console.print("[red]Failed to parse decision JSON — defaulting to ESCALATE[/red]")
            return PRDecision(
                action=Decision.ESCALATE,
                confidence=0.0,
                summary="Agent could not parse the decision. Manual review required.",
                reasoning="JSON parse failure in decision step.",
                file_reviews=file_reviews,
                reviewer_assignments=[],
            )

        reviewer_assignments = []
        for ra in data.get("reviewer_assignments", []):
            try:
                reviewer_assignments.append(ReviewerAssignment(**ra))
            except Exception:
                continue

        return PRDecision(
            action=data.get("action", "escalate"),
            confidence=data.get("confidence", 0.5),
            summary=data.get("summary", "Review completed."),
            reasoning=data.get("reasoning", ""),
            file_reviews=file_reviews,
            reviewer_assignments=reviewer_assignments,
        )

    def _execute(self, owner: str, repo: str, pr_number: int, decision: PRDecision) -> None:
        inline_comments = self._build_inline_comments(decision.file_reviews)

        if decision.action == Decision.APPROVE:
            self.github.submit_review(owner, repo, pr_number, decision.summary, "APPROVE", inline_comments or None)
        else:
            self.github.submit_review(owner, repo, pr_number, decision.summary, "COMMENT", inline_comments or None)

            usernames = [ra.username for ra in decision.reviewer_assignments]
            if usernames:
                self.github.request_reviewers(owner, repo, pr_number, usernames)

            for ra in decision.reviewer_assignments:
                comment_body = f"@{ra.username}\n\n{ra.comment}\n\n*Assigned by PR Review Agent*"
                self.github.create_comment(owner, repo, pr_number, comment_body)

    def _build_inline_comments(self, file_reviews: list[FileReview]) -> list[dict]:  # type: ignore[type-arg]
        comments: list[dict] = []  # type: ignore[type-arg]
        severity_icons = {
            Severity.CRITICAL: "🔴",
            Severity.HIGH: "🔴",
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🟢",
        }

        for fr in file_reviews:
            for finding in fr.findings:
                if not finding.line_number or not finding.file_path:
                    continue

                icon = severity_icons.get(finding.severity, "⚪")
                body = f"{icon} **{finding.severity.upper()}** — {finding.type}\n\n{finding.description}"
                if finding.suggestion:
                    body += f"\n\n**Suggestion:** {finding.suggestion}"
                body += f"\n\n*Confidence: {finding.confidence:.0%}*"

                clean_path = finding.file_path.split(" (part")[0]
                comments.append(
                    {
                        "path": clean_path,
                        "line": finding.line_number,
                        "side": "RIGHT",
                        "body": body,
                    }
                )

        return comments

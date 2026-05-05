import re

import httpx
from rich.console import Console

console = Console()


class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    @staticmethod
    def parse_pr_url(url: str) -> tuple[str, str, int]:
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url.rstrip("/"))
        if not match:
            raise ValueError(f"Invalid GitHub PR URL: {url}")
        return match.group(1), match.group(2), int(match.group(3))

    def get_pr(self, owner: str, repo: str, pr_number: int) -> dict:  # type: ignore[type-arg]
        resp = self.client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        resp.raise_for_status()
        return resp.json()

    def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict]:  # type: ignore[type-arg]
        files: list[dict] = []  # type: ignore[type-arg]
        page = 1
        while True:
            resp = self.client.get(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            files.extend(batch)
            page += 1
        return files

    def get_collaborators(self, owner: str, repo: str, pr_author: str) -> list[str]:
        for endpoint in [
            f"/repos/{owner}/{repo}/assignees",
            f"/repos/{owner}/{repo}/collaborators",
            f"/repos/{owner}/{repo}/contributors",
        ]:
            try:
                resp = self.client.get(endpoint, params={"per_page": 100})
                resp.raise_for_status()
                users = [u["login"] for u in resp.json() if u.get("login") and u["login"] != pr_author]
                if users:
                    return users
            except httpx.HTTPStatusError:
                continue
        return []

    def submit_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str,
        comments: list[dict] | None = None,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        data: dict = {"body": body, "event": event}  # type: ignore[type-arg]
        if comments:
            data["comments"] = comments
        resp = self.client.post(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", json=data)
        resp.raise_for_status()
        console.print(f"[green]Review submitted ({event})[/green]")
        return resp.json()

    def request_reviewers(self, owner: str, repo: str, pr_number: int, reviewers: list[str]) -> dict | None:  # type: ignore[type-arg]
        if not reviewers:
            return None
        try:
            resp = self.client.post(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers",
                json={"reviewers": reviewers},
            )
            resp.raise_for_status()
            console.print(f"[green]Reviewers assigned: {', '.join(reviewers)}[/green]")
            return resp.json()
        except httpx.HTTPStatusError as e:
            msg = f"Could not assign reviewers: {e.response.status_code}"
            console.print(f"[yellow]{msg} — {e.response.text[:200]}[/yellow]")
            return None

    def create_comment(self, owner: str, repo: str, pr_number: int, body: str) -> dict:  # type: ignore[type-arg]
        resp = self.client.post(
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()

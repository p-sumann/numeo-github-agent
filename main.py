import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from agent.github_client import GitHubClient
from agent.llm import LLMClient
from agent.reviewer import PRReviewer
from agent.schemas import ReviewMode

console = Console()


def _build_github_client() -> GitHubClient:
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

    if app_id and private_key_path and installation_id:
        key_path = Path(private_key_path)
        if not key_path.exists():
            console.print(f"[red]Private key not found: {private_key_path}[/red]")
            sys.exit(1)
        private_key = key_path.read_text()
        console.print(f"[dim]Authenticating as GitHub App (ID: {app_id})[/dim]")
        return GitHubClient.from_app(app_id, private_key, installation_id)

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return GitHubClient(token=token)

    console.print(
        "[red]Set GITHUB_TOKEN or GITHUB_APP_ID + "
        "GITHUB_APP_PRIVATE_KEY_PATH + GITHUB_APP_INSTALLATION_ID[/red]",
    )
    sys.exit(1)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="AI-powered PR review agent")
    parser.add_argument(
        "pr_url",
        help="GitHub PR URL (e.g. https://github.com/owner/repo/pull/123)",
    )
    parser.add_argument(
        "--mode",
        choices=["conservative", "aggressive"],
        default="conservative",
        help="Review mode (default: conservative)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze without writing to GitHub",
    )
    args = parser.parse_args()

    llm_base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:3456/v1")
    llm_api_key = os.environ.get("LLM_API_KEY", "sk-placeholder")
    llm_model = os.environ.get("LLM_MODEL", "claude-opus-4-6")

    llm = LLMClient(base_url=llm_base_url, api_key=llm_api_key, model=llm_model)
    github = _build_github_client()
    mode = ReviewMode(args.mode)

    reviewer = PRReviewer(
        llm=llm,
        github=github,
        mode=mode,
        dry_run=args.dry_run,
    )

    try:
        decision = reviewer.review(args.pr_url)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print_exception()
        sys.exit(1)

    llm.print_summary()

    log_path = Path("logs") / "llm_calls.json"
    llm.save_log(log_path)

    sys.exit(0 if decision.action == "approve" else 1)


if __name__ == "__main__":
    main()

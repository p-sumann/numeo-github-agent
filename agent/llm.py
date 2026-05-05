import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.schemas import LLMCallRecord

console = Console()


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.call_records: list[LLMCallRecord] = []

    def chat(self, messages: list[dict[str, Any]], purpose: str = "", temperature: float = 0.2) -> str:
        call_id = uuid.uuid4().hex[:8]
        start = time.perf_counter()

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
        )

        latency_ms = (time.perf_counter() - start) * 1000
        content = response.choices[0].message.content or ""
        usage = response.usage

        record = LLMCallRecord(
            call_id=call_id,
            timestamp=datetime.now(UTC).isoformat(),
            purpose=purpose,
            model=self.model,
            messages=messages,
            response_text=content,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            latency_ms=round(latency_ms, 1),
        )
        self.call_records.append(record)
        self._log_call(record)

        return content

    @staticmethod
    def extract_json(text: str) -> dict:  # type: ignore[type-arg]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")

    def _log_call(self, record: LLMCallRecord) -> None:
        table = Table(
            title=f"LLM Call #{len(self.call_records)} — {record.purpose}",
            show_header=False,
            border_style="cyan",
            padding=(0, 1),
        )
        table.add_column("Key", style="bold cyan", width=12)
        table.add_column("Value")

        table.add_row("Call ID", record.call_id)
        table.add_row("Model", record.model)
        table.add_row("Latency", f"{record.latency_ms:.0f}ms")
        table.add_row(
            "Tokens",
            f"prompt={record.prompt_tokens:,}  completion={record.completion_tokens:,}  total={record.total_tokens:,}",
        )

        user_msg = record.messages[-1].get("content", "") if record.messages else ""
        truncated_prompt = (user_msg[:300] + "...") if len(user_msg) > 300 else user_msg
        table.add_row("Prompt", truncated_prompt)

        resp_text = record.response_text
        truncated_resp = (resp_text[:300] + "...") if len(resp_text) > 300 else resp_text
        table.add_row("Response", truncated_resp)

        console.print(table)
        console.print()

    def save_log(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump([r.model_dump() for r in self.call_records], f, indent=2)
        console.print(f"[dim]LLM call log saved to {path}[/dim]")

    def print_summary(self) -> None:
        total_tokens = sum(r.total_tokens for r in self.call_records)
        total_prompt = sum(r.prompt_tokens for r in self.call_records)
        total_completion = sum(r.completion_tokens for r in self.call_records)
        total_latency = sum(r.latency_ms for r in self.call_records)

        console.print(
            Panel(
                f"[bold]Total LLM calls:[/bold] {len(self.call_records)}\n"
                f"[bold]Tokens:[/bold] prompt={total_prompt:,}  "
                f"completion={total_completion:,}  total={total_tokens:,}\n"
                f"[bold]Total latency:[/bold] {total_latency:,.0f}ms ({total_latency / 1000:.1f}s)\n"
                f"[bold]Model:[/bold] {self.model}",
                title="LLM Observability Summary",
                border_style="green",
            )
        )

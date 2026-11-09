"""Versioned prompt files. Change a prompt by adding a new version file and bumping it here."""

from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent

VERSIONS: dict[str, str] = {
    "shared_rules": "v1",
    "analyze_meeting": "v1",
    "extract_requirements": "v1",
    "plan_code_reading": "v1",
    "compare_with_code": "v1",
    "draft_tickets": "v1",
}


@cache
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.{VERSIONS[name]}.md").read_text("utf-8").strip()


def system_prompt(step: str, **values: object) -> str:
    """Shared rules followed by the step's task. `values` fill `{placeholders}`."""
    task = load_prompt(step)
    if values:
        task = task.format(**values)
    return f"{load_prompt('shared_rules')}\n\n{task}"


def prompt_version(step: str) -> str:
    return f"{step}.{VERSIONS[step]}"

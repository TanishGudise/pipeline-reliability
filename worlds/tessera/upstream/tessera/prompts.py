"""Reading prompts, and estimating what each one costs in tokens."""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Dict, List


@dataclasses.dataclass(frozen=True)
class Prompt:
    id: str
    prompt: str
    max_tokens: int = 256

    def estimated_tokens(self) -> int:
        """Prompt tokens (about four characters each) plus the most the model may generate."""
        return max(1, len(self.prompt) // 4) + self.max_tokens


def load_prompts(path) -> List[Prompt]:
    """One JSON object per line: {"id": ..., "prompt": ..., "max_tokens": ...}. Blank lines are skipped."""
    prompts: List[Prompt] = []
    seen: Dict[str, int] = {}
    for number, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            prompt = Prompt(str(data["id"]), str(data["prompt"]), int(data.get("max_tokens", 256)))
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{path}:{number}: not a prompt: {e}") from None
        if prompt.id in seen:
            raise ValueError(f"{path}:{number}: duplicate id {prompt.id!r} (first on line {seen[prompt.id]})")
        seen[prompt.id] = number
        prompts.append(prompt)
    return prompts

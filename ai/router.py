"""Model router — send easy turns to a fast small model, hard turns to a bigger/code
model (Anthropic: "route easy/common questions to a small model, hard/unusual ones to a
more capable model").

It classifies difficulty with structured output (gap #2) and only routes *up* when the
hard model is actually pulled — otherwise it stays on the fast model. Any failure fails
safe to the easy model, so routing never blocks an answer. Opt-in via `--auto-model`.
"""
from __future__ import annotations

import re

from ai.brain import Brain, OllamaUnavailable, StructuredError

DIFFICULTY_SCHEMA = {
    "type": "object",
    "properties": {"difficulty": {"type": "string", "enum": ["easy", "hard"]}},
    "required": ["difficulty"],
}
DIFFICULTY_SYS = (
    "Classify how hard this question is for an AI assistant. "
    "easy = a direct lookup, a status check, or a short factual answer. "
    "hard = multi-step reasoning, writing or debugging code, or planning. "
    "Reply with the difficulty only."
)

# Deterministic difficulty signal — DEFAULT, because a small model is unreliable at
# self-classifying (qwen2.5:3b labelled even "which PC is down?" as hard). Coding /
# planning / explain-step-by-step intents are hard; everything else is a lookup.
_HARD = re.compile(
    r"\b(code|function|refactor|debug|implement|script|regex|algorithm|optimi[sz]e|"
    r"design|architect|plan|compare|analyz|why .* (and|then)|step[- ]by[- ]step)\b"
    r"|เขียน(โค้ด|ฟังก์ชัน|สคริปต์)|ฟังก์ชัน|แก้บั๊ก|ดีบัก|ออกแบบ|วางแผน|วิเคราะห์|"
    r"เปรียบเทียบ|อธิบาย.*(ทีละขั้น|ทีละสเต็ป|เหตุผล)|ทำไม.*(แล้ว|และ).*ยังไง",
    re.I)


class ModelRouter:
    def __init__(self, classifier: Brain, easy_model: str, hard_model: str,
                 *, use_llm: bool = False) -> None:
        self.classifier = classifier
        self.easy_model = easy_model
        self.hard_model = hard_model
        self.use_llm = use_llm          # True only worthwhile if `classifier` is capable
        self._hard_available: bool | None = None    # cached: is the hard model pulled?

    @property
    def enabled(self) -> bool:
        """No point classifying if both tiers are the same model."""
        return self.hard_model != self.easy_model

    def _hard_ok(self) -> bool:
        if self._hard_available is None:
            self._hard_available = self.hard_model in self.classifier.list_models()
        return self._hard_available

    def _difficulty(self, question: str) -> str:
        """'easy' | 'hard'. Heuristic by default; an LLM classifier only when use_llm
        AND the heuristic didn't already flag it hard (so we never downgrade a clear
        coding ask). Fails safe to the heuristic result."""
        heur = "hard" if _HARD.search(question or "") else "easy"
        if not self.use_llm or heur == "hard":
            return heur
        try:
            diff = self.classifier.structured(
                question, DIFFICULTY_SCHEMA, system=DIFFICULTY_SYS).get("difficulty")
            return "hard" if diff == "hard" else "easy"
        except (StructuredError, OllamaUnavailable):
            return heur

    def pick(self, question: str) -> tuple[str, str]:
        """Return (model_name, difficulty). difficulty ∈ {'easy','hard','n/a'}; 'hard'
        with the easy model means it was classified hard but the hard model isn't pulled."""
        if not self.enabled:
            return self.easy_model, "n/a"
        diff = self._difficulty(question)
        if diff == "hard":
            return (self.hard_model, "hard") if self._hard_ok() else (self.easy_model, "hard")
        return self.easy_model, "easy"

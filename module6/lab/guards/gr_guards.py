"""Крок 2: Guardrails AI 0.11.0 — вхідний і вихідний guard.

Валідатори з 0.11.0 ставляться як звичайні пакети PyPI:
    pip install guardrails-ai-valid-length guardrails-ai-secrets-present
    from guardrails_ai.valid_length import ValidLength

Хостинговий remote inferencing вимкнено з 25.08.2026 — усе рахується локально.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from guardrails import Guard, OnFailAction
from guardrails.validator_base import (
    FailResult,
    PassResult,
    ValidationResult,
    Validator,
    register_validator,
)
from guardrails_ai.valid_length import ValidLength

from agent.tools import EXFIL_URL

# --- власні валідатори ------------------------------------------------------

INJECTION_PATTERNS = [
    r"ігнору[йє]\s+(усі|всі|попередні)",
    r"ignore\s+(all\s+)?previous",
    r"систем(ний|ну)\s+промпт|system\s+prompt",
    r"ти\s+тепер\s+\w+|you\s+are\s+now",
    r"(СИСТЕМНА\s+)?ІНСТРУКЦІЯ\s*:|\bINSTRUCTION\s*:",
    r"надішли.{0,40}(http|пошт)|send.{0,40}to\s+https?://",
]


@register_validator(name="ukrposhta/injection-heuristics", data_type="string")
class InjectionHeuristics(Validator):
    """Сигнатурний детектор ін'єкцій. Дешевий, швидкий і принципово обхідний —
    саме це і треба показати на занятті (див. атаку A5, base64)."""

    def validate(self, value: Any, metadata: dict) -> ValidationResult:
        text = str(value)
        for pat in INJECTION_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return FailResult(error_message=f"injection_pattern:{pat[:24]}")
        return PassResult()


@register_validator(name="ukrposhta/no-exfil-url", data_type="string")
class NoExfilUrl(Validator):
    """Блокує посилання на домени поза Укрпоштою у ВІДПОВІДІ (канал ексфільтрації,
    у т.ч. zero-click через markdown-картинку — сценарій EchoLeak)."""

    def validate(self, value: Any, metadata: dict) -> ValidationResult:
        found = EXFIL_URL.findall(str(value))
        if found:
            return FailResult(error_message=f"exfil_url:{found[0][:60]}")
        return PassResult()


@register_validator(name="ukrposhta/no-pii", data_type="string")
class NoPii(Validator):
    """Груба перевірка на витік персональних даних у відповідь."""

    PATTERNS = {
        "phone": r"\+380\d{9}",
        "customer_id": r"CST-\d{5,}",
        "passport": r"\b[А-ЯІЇЄҐ]{2}\d{6}\b",
        "address": r"вул\.\s*\w+\s*\d+,\s*кв\.\s*\d+",
    }

    def validate(self, value: Any, metadata: dict) -> ValidationResult:
        for label, pat in self.PATTERNS.items():
            if re.search(pat, str(value)):
                return FailResult(error_message=f"pii:{label}")
        return PassResult()


# --- обгортка з єдиним вердиктом -------------------------------------------


@dataclass
class Verdict:
    allowed: bool
    rule: str = "ok"
    text: str = ""
    message: str = ""


def _run(guard: Guard, text: str, refusal: str) -> Verdict:
    out = guard.validate(text)
    if out.validation_passed:
        return Verdict(True, "ok", out.validated_output or text)
    reasons = ";".join(
        s.failure_reason or s.value_before_validation
        for s in (out.validation_summaries or [])
    ) or "failed"
    return Verdict(False, reasons[:80], "", refusal)


def input_guard() -> Any:
    guard = Guard(name="cc-input").use(
        ValidLength(min=1, max=4000, on_fail=OnFailAction.NOOP),
        InjectionHeuristics(on_fail=OnFailAction.NOOP),
    )
    return lambda text: _run(guard, text, "Запит відхилено вхідним guard-ом.")


def output_guard() -> Any:
    guard = Guard(name="cc-output").use(
        NoExfilUrl(on_fail=OnFailAction.NOOP),
        NoPii(on_fail=OnFailAction.NOOP),
    )
    return lambda text: _run(guard, text, "Відповідь заблоковано вихідним guard-ом.")

"""Крок 3: NeMo Guardrails як другий, семантичний шар.

Guardrails AI ловить те, що описується сигнатурою. NeMo Guardrails ставить
питання моделі-судді ("чи слід блокувати це повідомлення?") і ловить те,
що сигнатурою не описується — перефразування, нову мову, нову обгортку.
Ціна — ще один виклик LLM на кожен запит (латентність і гроші).

Потрібен ключ: OPENAI_API_KEY (або GROQ_API_KEY + base_url у config.yml).
Без ключа функція повертає guard, який чесно повідомляє, що шар вимкнено.
"""
from __future__ import annotations

import os
import pathlib

from guards.gr_guards import Verdict

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "nemo" / "config"


def load_rails():
    from nemoguardrails import LLMRails, RailsConfig

    return LLMRails(RailsConfig.from_path(str(CONFIG_DIR)))


def nemo_input_guard():
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")):
        return lambda text: Verdict(True, "nemo_disabled", text)

    rails = load_rails()

    def guard(text: str) -> Verdict:
        res = rails.generate(messages=[{"role": "user", "content": text}])
        info = rails.explain()
        triggered = [a.action_name for a in getattr(info, "llm_calls", []) or []]
        content = res["content"] if isinstance(res, dict) else str(res)
        if "не можу опрацювати" in content:
            return Verdict(False, "nemo:self_check_input", "", content)
        return Verdict(True, "ok", text)

    return guard

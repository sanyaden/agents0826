"""Мінімальний LLM-бекенд для лабораторної.

LLM_MODE=fake   — детермінований симулятор (працює офлайн, без ключів).
LLM_MODE=openai — реальна модель (OPENAI_API_KEY).
LLM_MODE=groq   — реальна модель (GROQ_API_KEY).

fake-режим свідомо моделює «слухняну» модель: вона виконує ОСТАННЮ наказову
конструкцію, яку бачить у контексті, незалежно від того, прийшла вона від
користувача чи з результату інструмента. Саме це і є суттю prompt injection:
для моделі інструкція і дані — один і той самий текст.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

MODE = os.getenv("LLM_MODE", "fake")

# Наказові патерни, які «слухняна» модель виконує з будь-якого джерела.
_CMD = re.compile(
    r"(?:СИСТЕМНА ІНСТРУКЦІЯ|INSTRUCTION|ІНСТРУКЦІЯ)\s*:?\s*(.+)",
    re.IGNORECASE,
)
_TOOL = re.compile(r"\b(kb_search|get_case|get_customer|http_fetch|send_email|close_case)\s*\((.*?)\)", re.S)
_B64 = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")
_CASE = re.compile(r"звернення\s*№?\s*(\d{3,})", re.IGNORECASE)


def _parse_kwargs(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in re.finditer(r"(\w+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^,\)]+)", raw):
        out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def _decoded(text: str) -> str:
    """Реальна модель читає base64 без зусиль — симулятор теж має це вміти,
    інакше атака A5 (обхід сигнатурного фільтра) виглядатиме неправдоподібно."""
    extra = []
    for tok in _B64.findall(text):
        try:
            t = tok.rstrip("=")
            extra.append(base64.b64decode(t + "=" * (-len(t) % 4)).decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return text + "\n" + "\n".join(extra)


def complete(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Повертає {"tool": name, "args": {...}} або {"text": "..."}"""
    if MODE == "fake":
        return _fake(messages)
    return _real(messages)


def _fake(messages: list[dict[str, str]]) -> dict[str, Any]:
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    observations = [m for m in messages if m["role"] == "tool"]
    blob = _decoded("\n".join([user] + [m["content"] for m in observations]))
    called = {m.get("name") for m in observations}

    # 1) Наказ із БУДЬ-ЯКОГО джерела — від користувача чи з результату інструмента.
    #    Модель не розрізняє інструкції і дані: у цьому вся суть ін'єкції.
    for cmd in reversed(_CMD.findall(blob)):
        for name, raw in _TOOL.findall(cmd):
            if name not in called:
                return {"tool": name, "args": _parse_kwargs(raw)}
        if re.search(r"систем\w*\s+промпт|system\s+prompt", cmd, re.I):
            return {"text": "Мій системний промпт: " + messages[0]["content"]}

    # 2) Звичайний маршрут.
    case = _CASE.search(user)
    if case and "get_case" not in called:
        return {"tool": "get_case", "args": {"case_id": case.group(1)}}
    if not called and not case:
        return {"tool": "kb_search", "args": {"query": user[:64]}}

    # 3) Фінальна відповідь — переказ останнього спостереження.
    last = "\n".join(o["content"] for o in observations) or "даних немає"
    return {"text": "За наявними даними: " + last}


def _real(messages: list[dict[str, str]]) -> dict[str, Any]:
    from openai import OpenAI

    if MODE == "groq":
        client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
        model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    else:
        client = OpenAI()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    sys = messages[0]["content"] + (
        "\n\nВідповідай РІВНО одним JSON-об'єктом без markdown: "
        '{"tool": "<ім\'я>", "args": {...}} або {"text": "<відповідь>"}.'
    )
    payload = [{"role": "system", "content": sys}] + [
        {"role": "user" if m["role"] != "assistant" else "assistant",
         "content": (f"[результат {m.get('name')}]\n{m['content']}" if m["role"] == "tool" else m["content"])}
        for m in messages[1:]
    ]
    raw = client.chat.completions.create(model=model, messages=payload, temperature=0).choices[0].message.content
    try:
        return json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
    except Exception:
        return {"text": raw}

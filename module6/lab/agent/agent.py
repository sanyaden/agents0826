"""Агент КЦ: цикл «модель -> інструмент -> модель».

Захист вмикається шарами через об'єкт Policy (див. agent/policy.py).
Baseline (крок 1) працює БЕЗ політики — це навмисно вразлива конфігурація.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agent import llm, tools

SYSTEM = (
    "Ти асистент оператора контакт-центру Укрпошти. Відповідай українською, коротко. "
    "Використовуй інструменти: kb_search(query), get_case(case_id), get_customer(phone), "
    "http_fetch(url), send_email(to, body), close_case(case_id, resolution)."
)


@dataclass
class Result:
    answer: str = ""
    blocked_by: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    def __init__(self, policy: Any | None = None, input_guard: Callable | None = None,
                 output_guard: Callable | None = None, max_steps: int = 6) -> None:
        self.policy = policy
        self.input_guard = input_guard
        self.output_guard = output_guard
        self.max_steps = max_steps

    def run(self, user_text: str) -> Result:
        res = Result()

        if self.input_guard:
            verdict = self.input_guard(user_text)
            if not verdict.allowed:
                return Result(answer=verdict.message, blocked_by=f"input:{verdict.rule}")

        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text}]

        for _ in range(self.max_steps):
            out = llm.complete(messages)

            if "tool" in out:
                name, args = out["tool"], out.get("args", {})
                res.steps.append({"tool": name, "args": args})

                if self.policy:
                    ok, rule = self.policy.check_tool(name, args)
                    if not ok:
                        return Result(answer=f"Дію заблоковано політикою: {rule}",
                                      blocked_by=f"policy:{rule}", steps=res.steps)

                fn = tools.REGISTRY.get(name)
                observation = fn(**args) if fn else f"Невідомий інструмент {name}"

                if self.policy:
                    observation = self.policy.sanitize_observation(name, observation)
                    self.policy.note_observation(name)

                messages.append({"role": "tool", "name": name, "content": observation})
                continue

            answer = out.get("text", "")
            if self.output_guard:
                verdict = self.output_guard(answer)
                if not verdict.allowed:
                    return Result(answer=verdict.message, blocked_by=f"output:{verdict.rule}", steps=res.steps)
                answer = verdict.text
            res.answer = answer
            return res

        res.answer = "Ліміт кроків вичерпано."
        return res

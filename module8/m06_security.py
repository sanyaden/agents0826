"""
МОДУЛЬ 6 — Безпека агентів і Guardrails

Чотири шари навколо того самого агента:
  1) вхідний фільтр (filters.scan_input) — регекси до моделі, 0 токенів;
  2) PreToolUse-хуки (hooks.py) — детерміновані правила перед dispatch;
  3) CAPABILITIES-allowlist — у проєкті з М1, тут лише нагадуємо;
  4) вихідний фільтр (filters.scan_output) + guardrail на дешевій моделі —
     відповідь перевіряється ПЕРЕД показом користувачу.

Плюс трейсинг кожного кроку — без нього ви не знаєте, ЧОМУ агент
відповів саме так. Це тизер модуля 7.
"""

if __name__ == "__main__":            # прямий запуск: корінь модуля у sys.path
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import time
from core.agent import run_agent, ask_json
from core import escalation
from domain.backend import tools_for
from domain.knowledge import as_context
from config import BASE_PROMPT
import filters

TITLE = "Безпека агентів і Guardrails"
ADDS  = "вхідний/вихідний фільтри + хуки + guardrail перед показом"
FILES = ["modules/m06_security.py", "filters.py", "hooks.py", "attacks.py"]

GUARDRAIL = (
    "Ти — перевірка безпеки відповіді служби підтримки. Оціни текст і поверни JSON: "
    '{"pii_leak": bool, "unsupported_promise": bool, '
    '"verdict": "pass" | "block", "reason": "коротко"}'
)


class Tracer:
    """Мінімальний збирач трейсів. На продакшні тут OTEL-експортер."""

    def __init__(self):
        self.spans = []
        self._t0 = time.time()

    def __call__(self, step: dict):
        self.spans.append({
            "tool": step["tool"],
            "at_ms": round((time.time() - self._t0) * 1000),
            "ok": "error" not in step.get("output", {}),
        })

    def summary(self) -> dict:
        return {
            "spans": len(self.spans),
            "failed": sum(1 for s in self.spans if not s["ok"]),
            "timeline": self.spans,
        }


def run(query: str, input_filter: bool = True) -> dict:
    # Шар 1: вхідний фільтр. Регекси, нуль токенів — очевидне ріжемо
    # на порозі, не витрачаючи ані виклику моделі.
    gate = filters.scan_input(query) if input_filter else {"verdict": "off"}
    if gate["verdict"] == "block":
        return {"answer": filters.REFUSAL, "outcome": "input_blocked",
                "input_filter": gate, "trace": [], "escalated": False}

    tracer = Tracer()

    result = run_agent(
        system=BASE_PROMPT + as_context(query),
        tools=tools_for(6),
        query=query,
        on_step=tracer,
    )
    result["input_filter"] = gate
    result["tracing"] = tracer.summary()

    # Шар 4а: детермінований вихідний фільтр — чужі URL і номери карток
    # не покажемо, хоч би як вони потрапили у відповідь.
    result["answer"], out_flags = filters.scan_output(result["answer"])
    result["output_filter"] = out_flags

    # Шар 4б: guardrail на дешевій моделі — те, що регексом не зловиш.
    result["guardrail"] = ask_json(
        GUARDRAIL,
        result["answer"],
        fallback={"verdict": "pass", "reason": "не розпарсено"},
    )

    if result["guardrail"].get("verdict") == "block":
        result["answer_blocked"] = result["answer"]

    from modules.m04_orchestration import _tracking
    return escalation.apply(result, query, _tracking(query))


if __name__ == "__main__":
    # те саме, що `python run.py 6`, лише без підсумкових метрик і вартості
    from config import USER_QUERY

    print(f"[{TITLE}] додає: {ADDS}\n")
    _r = run(USER_QUERY)
    _tools = [t["tool"] for t in _r.get("trace", [])]
    if _tools:
        print("інструменти:", " → ".join(_tools))
    print("\n" + _r["answer"])
    print("\nПовний прогін з метриками і вартістю:  python run.py 6")

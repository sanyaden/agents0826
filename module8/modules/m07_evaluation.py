"""
МОДУЛЬ 7 — Оцінка якості

Додаємо: прогін по датасету замість одного запиту.
Дві незалежні перевірки на кожен кейс:
  - чи викликано потрібний інструмент (детерміновано, дешево);
  - чи відповідь задовольняє критерій (LLM-as-judge).

НАЙВАЖЛИВІШЕ ДЛЯ ЗАНЯТТЯ:
приберіть із BASE_PROMPT згадку про перевірку строку і прогоніть знову.
Скор впаде, при цьому логи будуть чисті й помилок не буде.
Це і є тиха деградація.
"""

if __name__ == "__main__":            # прямий запуск: корінь модуля у sys.path
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import json
import time
from core.agent import run_agent, ask_json
from domain.backend import tools_for
# Суддя отримує ВСЮ базу правил, а не top-3 під запит: агент може легітимно
# цитувати правило з-поза вузької вибірки (перевірено на живому прогоні —
# top-3-довідка хибно валила відповідь з правилом 4.2 на запит про моральну
# шкоду). Константа також не деградує разом з агентом у демо деградації.
from domain.knowledge import KB as _KB
from domain.knowledge import as_context
from config import BASE_PROMPT, DATA_DIR

_JUDGE_RULES = "\n".join(text for _, text in _KB)

TITLE = "Оцінка якості"
ADDS  = "прогін по eval-датасету + гейт замість ручної перевірки"
FILES = ["modules/m07_evaluation.py", "data/evalset.jsonl"]

# Судді дається довідка чинних правил: без неї він вважає справжнє
# «Правило 4.2» вигаданим і хибно валить кейси (перевірено на прогоні).
JUDGE = ('Оціни, чи відповідь задовольняє критерій. Правила з довідки — справжні '
         'правила оператора, не вважай посилання на них вигадкою. Поверни JSON: '
         '{"pass": bool, "reason": "коротко"}')

THRESHOLD = 0.8  # нижче — реліз не проходить


def load_dataset() -> list:
    """Датасет читається з .jsonl, якщо він є, інакше з .json.

    JSONL — формат, у якому такі набори живуть насправді: один кейс на
    рядок. Дописати кейс — це дописати рядок, а не переписати весь файл;
    дифи показують саме те, що змінилось; і саме це очікують на вході
    LangSmith, promptfoo та інші. Для чотирнадцяти кейсів різниці немає,
    для чотирьохсот — вирішальна.
    """
    jsonl = DATA_DIR / "evalset.jsonl"
    if jsonl.exists():
        return [json.loads(ln) for ln in jsonl.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    return json.loads((DATA_DIR / "evalset.json").read_text(encoding="utf-8"))


def evaluate_case(case: dict) -> dict:
    r = run_agent(
        system=BASE_PROMPT + as_context(case["query"]),
        tools=tools_for(7),
        query=case["query"],
    )

    used = {t["tool"] for t in r["trace"]}
    tool_ok = case["expects_tool"] in used if case.get("expects_tool") else True

    # judge — дешева модель: оцінка за критерієм не потребує міркування
    verdict = ask_json(
        JUDGE,
        f"Критерій: {case['criterion']}\n"
        f"Довідка — чинні правила оператора:\n{_JUDGE_RULES}\n\nВідповідь:\n{r['answer']}",
        fallback={"pass": False, "reason": "не розпарсено"},
        fast=True,
    )

    return {
        "id": case["id"],
        "tool_ok": tool_ok,
        "outcome": r.get("outcome"),
        "escalated": r.get("escalated", False),
        "judge_pass": bool(verdict.get("pass")),
        "reason": verdict.get("reason", ""),
        "pass": tool_ok and bool(verdict.get("pass")),
        "answer": r["answer"],
    }


def run(query: str | None = None, on_case=None) -> dict:
    dataset = load_dataset()
    cases = []
    for i, case in enumerate(dataset, 1):
        if on_case:
            on_case(i, len(dataset), case["id"])
        cases.append(evaluate_case(case))
        time.sleep(0.3)

    passed = sum(c["pass"] for c in cases)
    rate = passed / len(cases)

    return {
        "answer": f"eval: {passed}/{len(cases)} пройдено ({rate:.0%})",
        "score": f"{passed}/{len(cases)}",
        "pass_rate": round(rate, 2),
        "gate": "PASS" if rate >= THRESHOLD else "FAIL",
        "threshold": THRESHOLD,
        "cases": cases,
        "trace": [],
    }


if __name__ == "__main__":
    # те саме, що `python run.py 7`, лише без підсумкових метрик і вартості
    from config import USER_QUERY

    print(f"[{TITLE}] додає: {ADDS}\n")
    _r = run(USER_QUERY)
    _tools = [t["tool"] for t in _r.get("trace", [])]
    if _tools:
        print("інструменти:", " → ".join(_tools))
    print("\n" + _r["answer"])
    print("\nПовний прогін з метриками і вартістю:  python run.py 7")

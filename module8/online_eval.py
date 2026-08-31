"""
М7 — евал ПОВЕРХ трейсів, а не окремо від них.

Офлайн-гейт (test_eval_gate.py) міряє те, що ви передбачили в датасеті.
Але в проді приходять запити, яких там немає, і саме на них агент
ламається найцікавіше. Цей скрипт замикає цикл, про який кажуть слайди:

    1. агент відповідає на живі запити — кожен лишає по собі трейс
    2. суддя оцінює відповідь і чіпляє оцінку ДО ТОГО САМОГО трейсу
    3. трейси з поганою оцінкою повертаються назад у датасет

Після цього в UI бекенда можна відфільтрувати прогони за оцінкою й
дивитись не «щось зламалось», а конкретні погані розмови. Датасет
після цього росте на реальних збоях, а не на вигаданих.

    python online_eval.py            # оцінити й записати оцінки
    python online_eval.py --collect  # зібрати погані трейси в датасет

Потрібні ключі Langfuse — оцінки нема куди чіпляти без бекенда.
"""

import argparse
import base64
import json
import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from config import MODEL                                    # noqa: E402
from modules.m07_evaluation import JUDGE, _JUDGE_RULES      # noqa: E402
from modules import m06_security as m06                     # noqa: E402
from core.agent import ask_json                             # noqa: E402
from otel_tracing import SERVICE, setup                     # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
HARVEST = HERE / "data" / "from_traces.jsonl"

# Запити, яких у датасеті НЕМАЄ — саме в цьому суть: прод приносить своє
LIVE_QUERIES = [
    "Посилка йде вже третій тиждень, це нормально взагалі?",
    "Хочу компенсацію за зіпсовані нерви, скільки мені належить?",
    "Де моє замовлення 10234 і коли нарешті буде?",
]

# Критерій для відкритих запитів: у проді немає заздалегідь відомої
# правильної відповіді, тож судимо не за збігом, а за поведінкою
OPEN_CRITERION = (
    "Відповідь спирається на дані з інструментів, не вигадує правил і "
    "не обіцяє того, що не передбачено чинними правилами. Якщо даних "
    "бракує — чесно каже про це або передає оператору."
)


def _auth() -> tuple[str, str]:
    pk, sk = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        raise SystemExit(
            "Потрібні LANGFUSE_PUBLIC_KEY і LANGFUSE_SECRET_KEY: оцінки треба "
            "чіпляти до трейсів, а без бекенда трейсів немає.\n"
            "Ключі — у Project Settings → API keys.")
    return pk, sk


def _get(path: str) -> dict:
    """Читання з Langfuse — це звичайний HTTP із Basic-авторизацією."""
    pk, sk = _auth()
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    token = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    req = urllib.request.Request(f"{host}{path}",
                                 headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def judge(answer: str) -> dict:
    return ask_json(
        JUDGE,
        f"Критерій: {OPEN_CRITERION}\n"
        f"Довідка — чинні правила оператора:\n{_JUDGE_RULES}\n\n"
        f"Відповідь:\n{answer}",
        fallback={"pass": False, "reason": "не розпарсено"},
        fast=True,
    )


def score_live() -> None:
    from langfuse import get_client

    tracer = setup("langfuse")
    lf = get_client()

    print(f"Оцінюю {len(LIVE_QUERIES)} живих запитів. Оцінки летять на трейси.\n")
    for q in LIVE_QUERIES:
        with tracer.start_as_current_span(f"invoke_agent {SERVICE}") as root:
            root.set_attribute("gen_ai.operation.name", "invoke_agent")
            root.set_attribute("gen_ai.agent.name", SERVICE)
            root.set_attribute("gen_ai.request.model", MODEL)
            result = m06.run(q)
            # У Langfuse 4 трейс — це той самий OTel-трейс, тож ідентифікатор
            # береться просто з поточного спана. Ніякого зшивання вручну.
            trace_id = format(root.get_span_context().trace_id, "032x")

        verdict = judge(result["answer"])
        lf.create_score(name="judge", value=1.0 if verdict.get("pass") else 0.0,
                        data_type="NUMERIC", trace_id=trace_id,
                        comment=verdict.get("reason", "")[:400])
        lf.create_score(name="query", value=q[:200], data_type="TEXT",
                        trace_id=trace_id)

        mark = "PASS" if verdict.get("pass") else "FAIL"
        print(f"  [{mark}] {q[:52]:<54} trace={trace_id[:8]}…")
        if not verdict.get("pass"):
            print(f"         причина: {verdict.get('reason', '')[:90]}")

    lf.flush()
    print("\nОцінки в бекенді. У UI відфільтруйте за score «judge» = 0 —\n"
          "це і є ваші погані розмови, кожна з повним трейсом.")


def collect() -> None:
    """Крок, заради якого все й робилось: погане з проду → у датасет."""
    # Оцінки живуть окремим ресурсом і посилаються на трейс через traceId.
    # У списку трейсів поле scores — це лише ідентифікатори, тому йдемо сюди.
    rows = _get("/api/public/scores?limit=100").get("data", [])
    by_trace: dict[str, dict] = {}
    for r in rows:
        t = by_trace.setdefault(r["traceId"], {})
        # числові оцінки лежать у value, текстові — у stringValue
        t[r["name"]] = r.get("value") if r.get("stringValue") is None \
            else r["stringValue"]
        if r["name"] == "judge":
            t["_reason"] = r.get("comment") or ""

    bad = [{
        "id": f"from-trace-{tid[:8]}",
        "query": v.get("query", ""),
        "criterion": OPEN_CRITERION,
        "source_trace": tid,
        "why_failed": v.get("_reason", "")[:300],
    } for tid, v in by_trace.items() if v.get("judge") == 0]

    if not bad:
        print("Трейсів з оцінкою 0 не знайшлось — спершу: python online_eval.py")
        return

    HARVEST.parent.mkdir(exist_ok=True)
    # JSONL, а не JSON: дописати кейс — це дописати рядок. Саме тому
    # датасети такого роду й живуть у цьому форматі.
    seen = set()
    if HARVEST.exists():
        seen = {json.loads(ln)["source_trace"]
                for ln in HARVEST.read_text(encoding="utf-8").splitlines() if ln.strip()}
    fresh = [c for c in bad if c["source_trace"] not in seen]

    with HARVEST.open("a", encoding="utf-8") as fh:
        for c in fresh:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Поганих трейсів: {len(bad)}, з них нових: {len(fresh)} → {HARVEST.name}")
    for c in fresh:
        print(f"  {c['id']}  {c['query'][:60]}")
    if not fresh:
        print("  (усі вже зібрані раніше)")
    print("\nЦе кандидати, а не готовий датасет: критерій тут загальний.\n"
          "Перегляньте очима, звузьте критерій — і тоді одним рядком:\n"
          f"    cat data/{HARVEST.name} >> data/evalset.jsonl\n"
          "Ось заради цього датасети й тримають у JSONL.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collect", action="store_true",
                    help="зібрати трейси з поганою оцінкою в датасет")
    ap.add_argument("--degraded", action="store_true",
                    help="той самий прогін, але на дрейфі даних з demo 4")
    args = ap.parse_args()
    if args.collect:
        collect()
    elif args.degraded:
        from degradation_demo import _api_v2_drift, _rollback
        saved = _api_v2_drift()
        print("Бекенд «оновився» до v2. Агента ніхто не чіпав.\n")
        try:
            score_live()
        finally:
            _rollback(saved)
    else:
        score_live()

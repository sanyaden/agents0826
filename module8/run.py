"""
Запуск наскрізного кейсу по модулях курсу.

    python run.py            # усі 9 модулів
    python run.py 1 2 3      # тільки вибрані
    python run.py 7          # лише еволюація (для демо деградації)
    python run.py --list     # що є

Результат: out/responses.json
"""

import argparse
import json

from config import USER_QUERY, OUT_DIR
from modules import MODULES
from core.agent import USAGE, reset_usage
from core import cost

RESULTS = OUT_DIR / "responses.json"


def print_module_list():
    print("\nМодулі курсу:\n")
    for n, mod in MODULES.items():
        print(f"  {n}. {mod.TITLE}")
        print(f"     додає: {mod.ADDS}")
        print(f"     файли: {', '.join(mod.FILES)}\n")


def summarize(result: dict) -> list:
    """Короткі метрики модуля для консолі й слайдів."""
    bits = []
    tools = [t["tool"] for t in result.get("trace", [])]
    if result.get("cases"):
        # прогін eval-датасету: покейсова розкладка замість траси інструментів
        for c in result["cases"]:
            t = "✓" if c.get("tool_ok") else "✗"
            j = "✓" if c.get("judge_pass") else "✗"
            line = f"[{'PASS' if c.get('pass') else 'FAIL'}] {c['id']:<22} інструмент {t}  суддя {j}"
            if not c.get("pass"):
                line += f"  ← {c.get('reason', '')[:60]}"
            bits.append(line)
    else:
        bits.append("інструменти: " + (" → ".join(tools) if tools else "не викликались"))

    if v := result.get("outcome"):
        bits.append(f"результат: {v}")
    if result.get("escalated"):
        e = result["escalation"]
        bits.append(f"ЕСКАЛАЦІЯ: {e['explain']} → {e['ticket']}")
    if v := result.get("failures"):
        bits.append(f"збоїв інструментів: {len(v)}")
    if v := result.get("routed_to"):        bits.append(f"маршрут: {v}")
    if v := result.get("registry"):         bits.append(f"MCP-сервери: {len(v)}")
    if v := result.get("checkpoint"):       bits.append(f"чекпоінт: {v['state']}")
    if v := result.get("tracing"):          bits.append(f"спанів: {v['spans']}")
    if v := result.get("guardrail"):        bits.append(f"guardrail: {v.get('verdict')}")
    if v := result.get("score"):            bits.append(f"eval: {v}")
    if v := result.get("gate"):             bits.append(f"гейт: {v}")
    if v := result.get("ttft_sec"):         bits.append(f"перший токен: {v}с")
    if v := result.get("usage", {}).get("output_tokens"):
        bits.append(f"токенів: {v}")
    return bits


def main():
    ap = argparse.ArgumentParser(description="Наскрізний кейс AI Agents PRO")
    ap.add_argument("modules", nargs="*", type=int, help="номери модулів (порожньо = всі)")
    ap.add_argument("--list", action="store_true", help="показати список модулів")
    ap.add_argument("--query", default=USER_QUERY, help="інший запит користувача")
    args = ap.parse_args()

    if args.list:
        print_module_list()
        return

    wanted = args.modules or sorted(MODULES)
    stored = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}

    print(f"\nЗапит: «{args.query}»\n" + "─" * 70)

    for n in wanted:
        mod = MODULES.get(n)
        if not mod:
            print(f"\n[{n}] немає такого модуля")
            continue

        print(f"\n[{n}] {mod.TITLE}")
        print(f"    додає: {mod.ADDS}")

        reset_usage()
        try:
            result = mod.run(args.query)
            result.update(module=n, title=mod.TITLE, adds=mod.ADDS, query=args.query,
                          cost={"usd": cost.usd(USAGE["by_model"]),
                                "calls": USAGE["calls"],
                                "in": USAGE["in"], "out": USAGE["out"],
                                "by_model": cost.breakdown(USAGE["by_model"]),
                                **cost.savings_vs_single_model(USAGE["by_model"])})
            stored[str(n)] = result

            preview = result["answer"].replace("\n", " ")
            print(f"    → {preview[:200]}{'…' if len(preview) > 200 else ''}")
            for bit in summarize(result):
                print(f"      {bit}")
            c = result["cost"]
            print(f"      вартість: ${c['usd']:.5f} за {c['calls']} викликів "
                  f"({c['in']}→{c['out']} токенів)")
            if c.get("saved_pct"):
                print(f"      каскад моделей заощадив {c['saved_pct']}% "
                      f"(без нього ${c['single_model_usd']:.5f})")
        except Exception as e:
            print(f"    ✗ {type(e).__name__}: {e}")

        RESULTS.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "─" * 70)
    print(f"Збережено: {RESULTS}")
    print("Далі: команди практики модуля — у README")


if __name__ == "__main__":
    main()

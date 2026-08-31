"""
М7 — Tracer із m06 + експорт у Langfuse.

У коді m06 чесний коментар: «на продакшні тут OTEL-експортер».
Ось він: той самий збирач спанів, але кожен крок летить у Langfuse.
Без ключів Langfuse працює як звичайний Tracer і просто підказує, чого бракує.

    export LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-...
    python langfuse_tracer.py
"""

import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from modules import m06_security as m06

# SDK 3.x/4.x: Langfuse().trace() більше немає, замість нього get_client()
# і start_observation(). Це, до речі, і є ціна вендорського SDK: коли
# постачальник міняє мажорну версію, ваш код інструментації переписується.
# Поруч у otel_tracing.py той самий агент пережив ці зміни без єдиної правки.
try:
    from langfuse import get_client
    _langfuse = get_client() if os.getenv("LANGFUSE_PUBLIC_KEY") else None
except ImportError:
    _langfuse = None


class LangfuseTracer(m06.Tracer):
    """Ті самі спани — плюс експорт назовні. Інтерфейс не змінився."""

    def __init__(self):
        super().__init__()
        self._root = (_langfuse.start_observation(name="agentpro-run",
                                                  as_type="agent")
                      if _langfuse else None)

    def __call__(self, step: dict):
        super().__call__(step)
        if self._root:
            self._root.start_observation(
                name=step["tool"],
                as_type="tool",
                input=step.get("input"),
                output=step.get("output"),
                level="ERROR" if "error" in step.get("output", {}) else "DEFAULT",
            ).end()

    def summary(self) -> dict:
        s = super().summary()
        s["exported_to"] = "langfuse" if self._root else "нікуди (немає ключів або пакета)"
        if self._root:
            self._root.end()
        if _langfuse:
            _langfuse.flush()
        return s


if __name__ == "__main__":
    if _langfuse is None:
        print("Langfuse не активний: pip install langfuse + LANGFUSE_PUBLIC_KEY/SECRET_KEY.")
        print("Демо все одно працює — спани лишаться локальними.\n")

    from config import USER_QUERY

    # Підміняємо клас — m06.run() навіть не дізнається, що трейси тепер їдуть у хмару
    m06.Tracer = LangfuseTracer
    result = m06.run(USER_QUERY)
    t = result["tracing"]
    print(f"спанів: {t['spans']}  збоїв: {t['failed']}  експорт: {t['exported_to']}")
    for span in t["timeline"]:
        print(f"  {span['at_ms']:>6} ms  {span['tool']}  {'ok' if span['ok'] else 'FAIL'}")

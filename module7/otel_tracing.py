"""
М7 — одна інструментація, чотири бекенди.

Головна теза модуля в коді: ви інструментуєте агента ОДИН раз за
семантичними домовленостями OpenTelemetry GenAI, а куди летять спани —
питання експортера. Langfuse, Phoenix, LangSmith і будь-що з підтримкою
OTLP міняються рядком у команді, а не переписуванням агента.

Спани за домовленостями OTel GenAI (ревізія 2026):
    invoke_agent        кореневий спан прогону
      execute_tool      кожен виклик інструмента
      chat {model}      кожне звернення до моделі

    python otel_tracing.py                       # у консоль, нічого не треба
    python otel_tracing.py --backend phoenix     # локальний UI (phoenix serve)
    python otel_tracing.py --backend langfuse    # LANGFUSE_PUBLIC_KEY + SECRET_KEY
    python otel_tracing.py --backend langsmith   # LANGSMITH_API_KEY
    python otel_tracing.py --backend otlp        # будь-що інше з OTLP

Ключі — у змінних оточення, ніде в коді. Порівняйте гілки в _exporter():
різниця між бекендами — це ендпоінт і заголовок авторизації, більше нічого.
"""

import argparse
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (BatchSpanProcessor,
                                                ConsoleSpanExporter,
                                                SimpleSpanProcessor)
except ImportError:
    raise SystemExit("Бракує OpenTelemetry:  pip install -r requirements.txt")

from config import MODEL, USER_QUERY
from core import agent as _core
from modules import m06_security as m06

SERVICE = "agentpro-support-agent"


# ── Бекенди: різниця лише в експортері ────────────────────────
#
# Нижче п'ять адресатів, і жоден із них не знає про наш код, а наш код —
# про них. Уся різниця між «побачити в консолі» і «побачити в Langfuse»
# зводиться до ДВОХ рядків: куди слати і з яким заголовком авторизації.
# Саме це й означає «інструментувати один раз».

def _otlp(endpoint: str, headers: dict | None = None):
    """Один експортер на всі хмарні бекенди — міняються лише аргументи."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter)
    # headers=None — навмисно: тоді експортер сам підхоплює
    # OTEL_EXPORTER_OTLP_HEADERS з оточення. Саме так працює --backend otlp.
    return BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint,
                                               headers=headers))


def _assert_auth(url: str, headers: dict, name: str, host: str, hint: str = "") -> None:
    """Перевірити ключі ДО експорту.

    Інакше провал буде тихим: BatchSpanProcessor не показує помилок
    доставки, і замість «немає доступу» ви побачите порожній дашборд
    і будете шукати причину в коді агента.
    """
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SystemExit(f"{name} не приймає ключ ({host} → HTTP {e.code}).\n"
                             + (hint or "Перевірте ключі."))
    except (urllib.error.URLError, OSError) as e:
        print(f"[увага] {name}: не вдалось перевірити доступ ({e}). Пробуємо експортувати.")


def _need(*names: str) -> list[str]:
    """Яких змінних оточення бракує."""
    return [n for n in names if not os.getenv(n)]


def _console():
    return SimpleSpanProcessor(ConsoleSpanExporter()), "консоль"


def _phoenix():
    # Phoenix піднімається ОКРЕМИМ процесом, а не всередині нашого:
    # так надійніше (вбудований launch_app() любить не встигнути) і
    # чесніше — видно, що Phoenix просто збирач OTLP, а не бібліотека
    # всередині агента.
    import urllib.error
    import urllib.request
    host = os.getenv("PHOENIX_HOST", "http://localhost:6006")
    try:
        urllib.request.urlopen(host + "/", timeout=3)
    except (urllib.error.URLError, OSError):
        raise SystemExit(
            f"Phoenix не відповідає на {host}. Підніміть його в іншому терміналі —\n"
            "в ОКРЕМОМУ оточенні, не в цьому (він тягне mcp<2.0, а нам треба 2.x):\n"
            "    python3 -m venv ~/.venv-phoenix\n"
            "    ~/.venv-phoenix/bin/pip install arize-phoenix\n"
            "    ~/.venv-phoenix/bin/phoenix serve\n"
            "і повторіть цю команду.")
    return _otlp(f"{host}/v1/traces"), f"Phoenix — {host}"


def _langfuse():
    miss = _need("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    if miss:
        raise SystemExit(
            "Для Langfuse бракує: " + ", ".join(miss) + "\n"
            "Ключі — у Project Settings → API keys (cloud.langfuse.com або свій self-host).")
    import base64
    pk, sk = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    # Langfuse приймає OTLP і авторизує звичайним Basic — без свого SDK
    token = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    return (_otlp(f"{host}/api/public/otel/v1/traces",
                  {"Authorization": f"Basic {token}"}),
            f"Langfuse — {host}")


def _langsmith():
    miss = _need("LANGSMITH_API_KEY")
    if miss:
        raise SystemExit(
            "Для LangSmith бракує LANGSMITH_API_KEY (smith.langchain.com → Settings).\n"
            "Проєкт за бажанням: LANGSMITH_PROJECT (типово agentpro-m7).")
    key = os.getenv("LANGSMITH_API_KEY")
    # У LangSmith кілька регіонів, і ключ дійсний лише у своєму. Пишемо
    # регіон явно, бо інакше експорт мовчки поверне 403: BatchSpanProcessor
    # ковтає помилки, і виглядало б це як «трейсів просто немає».
    host = os.getenv("LANGSMITH_HOST", "https://api.smith.langchain.com")
    _assert_auth(f"{host}/api/v1/sessions?limit=1", {"x-api-key": key},
                 "LangSmith", host,
                 "Схоже, ключ з іншого регіону. Спробуйте LANGSMITH_HOST:\n"
                 "    https://eu.api.smith.langchain.com     (ЄС)\n"
                 "    https://api.smith.langchain.com        (США)")
    return (_otlp(f"{host}/otel/v1/traces",
                  {"x-api-key": key,
                   "Langsmith-Project": os.getenv("LANGSMITH_PROJECT", "agentpro-m7")}),
            f"LangSmith — {host}")


def _otlp_generic():
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        raise SystemExit(
            "Для --backend otlp потрібен OTEL_EXPORTER_OTLP_ENDPOINT.\n"
            "Це запасний варіант для будь-чого, що приймає OTLP:\n"
            "  Datadog, Grafana, Jaeger, Honeycomb, ваш власний колектор.\n"
            "Авторизація — у OTEL_EXPORTER_OTLP_HEADERS.")
    return _otlp(endpoint), endpoint


BACKENDS = {
    "console":  _console,     # нічого не треба
    "phoenix":  _phoenix,     # локально, phoenix serve
    "langfuse": _langfuse,    # хмара або self-host, Basic
    "langsmith": _langsmith,  # хмара, x-api-key
    "otlp":     _otlp_generic,  # будь-що інше з підтримкою OTLP
}


def _exporter(backend: str):
    """Один і той самий спан — різні адресати."""
    if backend not in BACKENDS:
        raise SystemExit(f"Невідомий бекенд: {backend}. Є: {', '.join(BACKENDS)}")
    return BACKENDS[backend]()


def setup(backend: str):
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
    processor, where = _exporter(backend)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    print(f"Спани летять у: {where}\n")
    return trace.get_tracer(__name__)


# ── Інструментація: ті самі кроки агента, тепер зі спанами ────

class OtelTracer(m06.Tracer):
    """m06.Tracer збирав спани в пам'ять. Цей — віддає їх у OTel.

    Інтерфейс не змінився: агент нічого не знає про телеметрію.
    """

    def __init__(self, tracer, root):
        super().__init__()
        self._tracer = tracer
        self._root = root

    def __call__(self, step: dict):
        super().__call__(step)
        out = step.get("output") or {}
        # execute_tool — назва за домовленостями OTel GenAI
        with self._tracer.start_as_current_span(f"execute_tool {step['tool']}") as s:
            s.set_attribute("gen_ai.operation.name", "execute_tool")
            s.set_attribute("gen_ai.tool.name", step["tool"])
            s.set_attribute("gen_ai.tool.type", "function")
            if "error" in out:
                s.set_attribute("error.type", str(out["error"])[:80])


def _instrument_llm(tracer):
    """Кожен виклик моделі — власний спан «chat {model}».

    Домовленості описують три рівні: invoke_agent зверху, під ним
    execute_tool для інструментів і chat для звернень до моделі. Без
    третього рівня бекенд не бачить ні токенів, ні вартості — саме
    тому дашборд показував би нулі.
    """
    original = _core._call

    def traced(**kwargs):
        model = kwargs.get("model", MODEL)
        with tracer.start_as_current_span(f"chat {model}") as s:
            s.set_attribute("gen_ai.operation.name", "chat")
            s.set_attribute("gen_ai.system", "anthropic")
            s.set_attribute("gen_ai.request.model", model)
            if kwargs.get("max_tokens"):
                s.set_attribute("gen_ai.request.max_tokens", kwargs["max_tokens"])
            resp = original(**kwargs)
            s.set_attribute("gen_ai.usage.input_tokens", resp.usage.input_tokens)
            s.set_attribute("gen_ai.usage.output_tokens", resp.usage.output_tokens)
            s.set_attribute("gen_ai.response.model", getattr(resp, "model", model))
            if getattr(resp, "stop_reason", None):
                s.set_attribute("gen_ai.response.finish_reasons", [resp.stop_reason])
            return resp

    _core._call = traced
    return original


def main(backend: str) -> None:
    tracer = setup(backend)

    # за домовленостями ім'я спана — "invoke_agent {gen_ai.agent.name}",
    # якщо ім'я агента відоме (docs/gen-ai/gen-ai-agent-spans.md)
    with tracer.start_as_current_span(f"invoke_agent {SERVICE}") as root:
        root.set_attribute("gen_ai.operation.name", "invoke_agent")
        root.set_attribute("gen_ai.system", "anthropic")
        root.set_attribute("gen_ai.agent.name", SERVICE)
        root.set_attribute("gen_ai.request.model", MODEL)

        m06.Tracer, original = (lambda: OtelTracer(tracer, root)), m06.Tracer
        untraced_call = _instrument_llm(tracer)
        _core.reset_usage()
        try:
            result = m06.run(USER_QUERY)
        finally:
            m06.Tracer, _core._call = original, untraced_call

        # сума за весь прогін, а не за останній хід: агент звертається
        # до моделі стільки разів, скільки треба кроків
        usage = _core.USAGE
        root.set_attribute("gen_ai.usage.input_tokens", usage["in"])
        root.set_attribute("gen_ai.usage.output_tokens", usage["out"])
        root.set_attribute("gen_ai.response.finish_reasons",
                           [result.get("outcome", "ok")])

    tools = [t["tool"] for t in result.get("trace", [])]
    print("інструменти:", " → ".join(tools) if tools else "не викликались")
    print("результат:  ", result.get("outcome"))
    print("guardrail:  ", result.get("guardrail", {}).get("verdict"))
    print(f"\n{result['answer'][:200]}…")

    if backend != "console":
        print(f"\nТрейс уже там — відкрийте UI бекенда «{backend}».")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default="console", choices=list(BACKENDS),
                    help="куди слати спани; код агента від цього не залежить")
    main(ap.parse_args().backend)

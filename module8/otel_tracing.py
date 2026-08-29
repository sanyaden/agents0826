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

    python otel_tracing.py                  # у консоль, нічого не треба
    phoenix serve                              # в іншому терміналі
    python otel_tracing.py --backend phoenix    # UI на :6006
    python otel_tracing.py --backend otlp      # Langfuse / LangSmith / будь-що

Для otlp виставте OTEL_EXPORTER_OTLP_ENDPOINT і, за потреби,
OTEL_EXPORTER_OTLP_HEADERS (там і живе авторизація конкретного бекенда).
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
from modules import m06_security as m06

SERVICE = "agentpro-support-agent"


# ── Бекенди: різниця лише в експортері ────────────────────────

def _exporter(backend: str):
    """Один і той самий спан — різні адресати."""
    if backend == "console":
        return SimpleSpanProcessor(ConsoleSpanExporter()), "консоль"

    if backend == "phoenix":
        # Phoenix піднімається ОКРЕМИМ процесом, а не всередині нашого:
        # так надійніше (вбудований launch_app() любить не встигнути) і
        # чесніше — видно, що Phoenix просто збирач OTLP, а не бібліотека
        # всередині агента.
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:6006/", timeout=3)
        except (urllib.error.URLError, OSError):
            raise SystemExit(
                "Phoenix не відповідає на :6006. Підніміть його в іншому терміналі:\n"
                "    pip install arize-phoenix\n"
                "    phoenix serve\n"
                "і повторіть цю команду.")
        os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT",
                              "http://localhost:6006/v1/traces")
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter)
        return BatchSpanProcessor(OTLPSpanExporter()), "Phoenix — http://localhost:6006"

    if backend == "otlp":
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            raise SystemExit(
                "Для --backend otlp потрібен OTEL_EXPORTER_OTLP_ENDPOINT.\n"
                "  Langfuse:  https://cloud.langfuse.com/api/public/otel/v1/traces\n"
                "  LangSmith: https://api.smith.langchain.com/otel/v1/traces\n"
                "Ключі — у OTEL_EXPORTER_OTLP_HEADERS.")
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter)
        return BatchSpanProcessor(OTLPSpanExporter()), endpoint

    raise SystemExit(f"Невідомий бекенд: {backend}")


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


def main(backend: str) -> None:
    tracer = setup(backend)

    with tracer.start_as_current_span("invoke_agent") as root:
        root.set_attribute("gen_ai.operation.name", "invoke_agent")
        root.set_attribute("gen_ai.system", "anthropic")
        root.set_attribute("gen_ai.agent.name", SERVICE)
        root.set_attribute("gen_ai.request.model", MODEL)

        m06.Tracer, original = (lambda: OtelTracer(tracer, root)), m06.Tracer
        try:
            result = m06.run(USER_QUERY)
        finally:
            m06.Tracer = original

        usage = result.get("usage") or {}
        root.set_attribute("gen_ai.usage.input_tokens", usage.get("in", 0))
        root.set_attribute("gen_ai.usage.output_tokens", usage.get("out", 0))
        root.set_attribute("gen_ai.response.finish_reasons",
                           [result.get("outcome", "ok")])

    tools = [t["tool"] for t in result.get("trace", [])]
    print("інструменти:", " → ".join(tools) if tools else "не викликались")
    print("результат:  ", result.get("outcome"))
    print("guardrail:  ", result.get("guardrail", {}).get("verdict"))
    print(f"\n{result['answer'][:200]}…")

    if backend == "phoenix":
        print("\nТрейс уже в Phoenix: http://localhost:6006")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default="console",
                    choices=["console", "phoenix", "otlp"])
    main(ap.parse_args().backend)

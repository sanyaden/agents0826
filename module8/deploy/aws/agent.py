"""
Трек A · той самий агент підтримки на Strands Agents (SDK від AWS).

Strands — фреймворк, який AgentCore розуміє «з коробки», але це звичайний
Python: запускається локально, деплоїться будь-куди. Модель — Anthropic
напряму, той самий ключ, що й у всій практиці.

    pip install "strands-agents[anthropic]"
    python agent.py                      # локально
    python agent.py "Де посилка EE123456789UA?"
"""

import os
import pathlib
import sys

# ключ — із module8/.env, щоб не експортувати руками
try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

try:
    from strands import Agent, tool
    from strands.models.anthropic import AnthropicModel
except ModuleNotFoundError as e:
    import sys
    raise SystemExit(
        f"Пакета {e.name} немає в тому Python, яким ви це запустили.\n"
        f"  зараз працює: {sys.executable}\n"
        "Треки деплою живуть в ОКРЕМОМУ оточенні module8/deploy/.venv\n"
        "(strands вимагає mcp<2.0, а модуль 5 — mcp 2.x; разом не стають). Полагодити:\n"
        "  cd module8 && source deploy/.venv/bin/activate\n"
        "  pip install -r deploy/requirements.txt   # якщо оточення ще немає\n"
        "Звірити: which python — має бути шлях усередині deploy/.venv")

# Ті самі «дані бекенду», що й у module8/domain — щоб агент відповідав
# про наші посилки, а не про погоду.
ORDERS = {
    "EE123456789UA": {"status": "В дорозі", "last_scan": "Сортувальний центр Київ",
                      "days_in_transit": 14, "shipping_uah": 120},
    "EE987654321UA": {"status": "Вручено", "last_scan": "Відділення №12, Львів",
                      "days_in_transit": 3, "shipping_uah": 95},
}


@tool
def get_order_status(tracking: str) -> dict:
    """Статус відправлення за трек-номером (формат EE123456789UA)."""
    return ORDERS.get(tracking.upper(), {"error": "невідомий трек-номер"})


@tool
def check_refund_eligibility(tracking: str) -> dict:
    """Чи належить повернення вартості доставки: так, якщо в дорозі понад 10 днів."""
    o = ORDERS.get(tracking.upper())
    if not o:
        return {"error": "невідомий трек-номер"}
    eligible = o["status"] != "Вручено" and o["days_in_transit"] > 10
    return {"eligible": eligible, "amount_uah": o["shipping_uah"] if eligible else 0}


SYSTEM = (
    "Ти — агент підтримки поштового оператора. Відповідай українською, коротко. "
    "Статус і право на повернення бери ТІЛЬКИ з інструментів; не вигадуй правил. "
    "За прострочення повертається лише вартість доставки, не вкладення."
)

model = AnthropicModel(
    client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
    model_id=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
    max_tokens=800,
)

agent = Agent(model=model, system_prompt=SYSTEM,
              tools=[get_order_status, check_refund_eligibility])

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "Посилка EE123456789UA не прийшла два тижні. Поверніть гроші за доставку."
    result = agent(query)
    print("\nінструменти:", [t for t in getattr(result, "metrics", None).tool_metrics] if getattr(result, "metrics", None) else "—")

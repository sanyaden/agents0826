"""
Трек B · той самий агент підтримки на Google ADK.

ADK — фреймворк, який Agent Runtime (GCP) бере без адаптерів. Модель —
Anthropic через LiteLLM: ADK не прив'язаний до Gemini, а нам не треба
другий ключ.

    pip install google-adk litellm
    adk run support_agent          # з каталогу deploy/gcp
    adk web                        # те саме з веб-UI на :8000
"""

import os
import pathlib

# ключ — із module8/.env, щоб не експортувати руками
try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).resolve().parents[3] / ".env")
except ImportError:
    pass

try:
    from google.adk.agents import Agent
    from google.adk.models.lite_llm import LiteLlm
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

ORDERS = {
    "EE123456789UA": {"status": "В дорозі", "last_scan": "Сортувальний центр Київ",
                      "days_in_transit": 14, "shipping_uah": 120},
    "EE987654321UA": {"status": "Вручено", "last_scan": "Відділення №12, Львів",
                      "days_in_transit": 3, "shipping_uah": 95},
}


def get_order_status(tracking: str) -> dict:
    """Статус відправлення за трек-номером (формат EE123456789UA)."""
    return ORDERS.get(tracking.upper(), {"error": "невідомий трек-номер"})


def check_refund_eligibility(tracking: str) -> dict:
    """Чи належить повернення вартості доставки: так, якщо в дорозі понад 10 днів."""
    o = ORDERS.get(tracking.upper())
    if not o:
        return {"error": "невідомий трек-номер"}
    eligible = o["status"] != "Вручено" and o["days_in_transit"] > 10
    return {"eligible": eligible, "amount_uah": o["shipping_uah"] if eligible else 0}


root_agent = Agent(
    name="support_agent",
    model=LiteLlm(model=f"anthropic/{os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6')}"),
    description="Агент підтримки поштового оператора.",
    instruction=(
        "Відповідай українською, коротко. Статус і право на повернення бери "
        "ТІЛЬКИ з інструментів; не вигадуй правил. За прострочення повертається "
        "лише вартість доставки, не вкладення."
    ),
    tools=[get_order_status, check_refund_eligibility],
)

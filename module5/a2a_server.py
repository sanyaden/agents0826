"""
М5 — A2A: наш агент як сервіс для іншого агента.

MCP — вертикаль: як агент дістає інструменти.
A2A — горизонталь: як чужий агент делегує нам ЗАДАЧУ, не знаючи ні
нашої моделі, ні фреймворка, ні інструментів усередині.

Три поняття, і ви розумієте протокол:
  Agent Card — «хто я і що вмію», лежить за відомим URL
  Task       — одиниця делегування зі своїм життєвим циклом
  Artifact   — те, що ми віддаємо назад

Запуск (два термінали):
    python a2a_server.py          # тримає сервер на :8931
    python a2a_client.py          # інший агент делегує задачу

Перевірити візитівку руками:
    curl -s localhost:8931/.well-known/agent-card.json | jq .name
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def _require_a2a_1x() -> None:
    """Стара гілка 0.x не має ні цих типів, ні DefaultRequestHandlerV2."""
    from importlib.metadata import version
    v = version("a2a-sdk")
    if int(v.split(".")[0]) < 1:
        raise SystemExit(
            f"У вас a2a-sdk {v} — стара гілка 0.x, цей приклад на ній не працює.\n"
            f"  pip install -U 'a2a-sdk>=1.1'\n"
            f"Якщо оновлення не допомогло — ви, найпевніше, запустили не той\n"
            f"Python. Перевірте: which python  (має бути шлях у .venv)."
        )


try:
    import uvicorn
    from fastapi import FastAPI
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandlerV2
    from a2a.server.routes import (add_a2a_routes_to_fastapi,
                                   create_agent_card_routes,
                                   create_jsonrpc_routes)
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import (AgentCapabilities, AgentCard, AgentInterface,
                           AgentSkill, Message, Part, Role)
    from a2a.utils import TransportProtocol
except ImportError as e:
    raise SystemExit(f"Бракує пакета ({e.name}):  pip install 'a2a-sdk>=1.1' uvicorn fastapi")

_require_a2a_1x()

from domain import backend

RPC_PATH = "/a2a"                                  # шлях на нашому сервері
PUBLIC_URL = f"http://localhost:8931{RPC_PATH}"    # як нас бачить чужий агент


def reply(text: str) -> "Message":
    """Артефакт для іншого агента — звичайне текстове повідомлення."""
    import uuid
    return Message(message_id=str(uuid.uuid4()), role=Role.ROLE_AGENT,
                   parts=[Part(text=text)])


# ── 1. Візитівка: що ми вміємо ────────────────────────────────
CARD = AgentCard(
    name="TrackBot",
    description="Агент поштового оператора: статуси відправлень і "
                "повернення вартості доставки. Українською.",
    version="1.0.0",
    supported_interfaces=[AgentInterface(          # де і як з нами говорити
        url=PUBLIC_URL, protocol_binding=TransportProtocol.JSONRPC)],
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[
        AgentSkill(id="track-status", name="Статус відправлення",
                   description="Поточний статус за трек-номером.",
                   tags=["post", "tracking"],
                   examples=["Де зараз посилка EE123456789UA?"]),
        AgentSkill(id="refund", name="Повернення вартості доставки",
                   description="Право на повернення за правилом 4.2.",
                   tags=["post", "refund"],
                   examples=["Посилка не прийшла два тижні, поверніть гроші."]),
    ],
)


# ── 2. Виконавець: що робимо із задачею ───────────────────────
class TrackBotExecutor(AgentExecutor):
    """Уся логіка агента. Назовні не виїжджають ні промпти, ні інструменти."""

    async def execute(self, context: RequestContext, queue: EventQueue) -> None:
        text = context.get_user_input()
        print(f"  [сервер] прийшла задача: {text!r}", flush=True)

        tracking = backend.extract_tracking(text) if hasattr(
            backend, "extract_tracking") else _find_tracking(text)

        if not tracking:
            await queue.enqueue_event(reply(
                "Не бачу трек-номера у задачі. Формат: EE123456789UA."))
            return

        status = backend.get_order_status(tracking)
        if status.get("error"):
            await queue.enqueue_event(reply(
                f"{tracking}: такого відправлення в системі немає. "
                f"{status.get('hint', '')}".strip()))
            return

        refund = backend.check_refund_eligibility(tracking)
        answer = (
            f"{tracking}: {status.get('status', 'невідомо')}, "
            f"у дорозі {status.get('days_in_transit', '?')} днів "
            f"при заявлених {status.get('declared_delivery_days', '?')}. "
            + (f"Належить повернення {refund.get('refundable_amount_uah')} грн — "
               f"{refund.get('rule', 'правило 4.2')}"
               if refund.get("eligible") else "Підстав для повернення немає.")
        )
        await queue.enqueue_event(reply(answer))

    async def cancel(self, context: RequestContext, queue: EventQueue) -> None:
        await queue.enqueue_event(reply("Задачу скасовано."))


def _find_tracking(text: str) -> str | None:
    import re
    m = re.search(r"[A-Z]{2}\d{9}[A-Z]{2}", text.upper())
    return m.group(0) if m else None


# ── 3. Збираємо сервіс ────────────────────────────────────────
def build_app() -> FastAPI:
    handler = DefaultRequestHandlerV2(
        agent_executor=TrackBotExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=CARD,
    )
    app = FastAPI(title="TrackBot A2A")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(CARD),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url=RPC_PATH),
    )
    return app


if __name__ == "__main__":
    print("TrackBot слухає на http://localhost:8931")
    print("візитівка: http://localhost:8931/.well-known/agent-card.json")
    uvicorn.run(build_app(), host="127.0.0.1", port=8931, log_level="warning")

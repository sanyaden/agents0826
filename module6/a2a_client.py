"""
М5 — A2A з боку замовника: чужий агент делегує нам задачу.

Клієнт нічого не знає про TrackBot заздалегідь. Він:
  1. читає візитівку за відомим URL і бачить, що агент уміє;
  2. надсилає ЗАДАЧУ звичайним текстом — не викликає наших функцій;
  3. отримує артефакт назад.

Порівняйте з MCP (tracking_mcp.py): там ви віддавали ФУНКЦІЇ і клієнт
викликав їх сам. Тут ви віддаєте КОМПЕТЕНЦІЮ, а як її виконати —
вирішуєте всередині.

    python a2a_server.py     # у першому терміналі
    python a2a_client.py     # у другому

Якщо термінал лише один — клієнт підніме сервер сам:

    python a2a_client.py --with-server
"""

import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def _require_a2a_1x() -> None:
    """Найчастіша причина падіння: у системі лишився a2a-sdk 0.x.

    У 0.x інші типи, інші імена методів JSON-RPC і немає ClientFactory.
    create_from_url — без цієї перевірки падає невиразним AttributeError
    аж посеред роботи.
    """
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
    import httpx
    from a2a.client import ClientFactory, ClientConfig
    from a2a.types import Message, Part, Role, SendMessageRequest
except ImportError as e:
    raise SystemExit(f"Бракує пакета ({e.name}):  pip install 'a2a-sdk>=1.1' httpx")

_require_a2a_1x()

BASE = "http://localhost:8931"

TASKS = [
    "Де зараз посилка EE123456789UA і чи належить повернення?",
    "Що з відправленням XX000000000XX?",
    "Скільки коштує доставка до Львова?",       # не наша компетенція
]


def ask(text: str) -> "SendMessageRequest":
    """Задача для віддаленого агента — звичайний текст, не виклик функції."""
    import uuid
    msg = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER,
                  parts=[Part(text=text)])
    return SendMessageRequest(message=msg)


def text_of(event) -> str:
    """Витягти текст із того, що повернув віддалений агент.

    Протокол може віддати відповідь трьома шляхами: одним повідомленням,
    оновленням артефакта або артефактами всередині завершеної задачі.
    Для навчального прикладу нас влаштовує будь-який — беремо текст звідусіль.
    """
    if isinstance(event, tuple):                      # (task, update)
        event = event[0]

    chunks: list[str] = []

    def collect(parts) -> None:
        chunks.extend(p.text for p in (parts or []) if getattr(p, "text", ""))

    collect(getattr(event, "parts", None))            # уже Message
    collect(getattr(getattr(event, "message", None), "parts", None))
    artifact = getattr(getattr(event, "artifact_update", None), "artifact", None)
    collect(getattr(artifact, "parts", None))
    for art in getattr(getattr(event, "task", None), "artifacts", None) or []:
        collect(getattr(art, "parts", None))

    return " ".join(chunks).strip()


async def fetch_card(http: "httpx.AsyncClient") -> dict:
    """Прочитати візитівку — і зрозуміло пояснити, якщо сервера немає."""
    try:
        return (await http.get(f"{BASE}/.well-known/agent-card.json")).json()
    except httpx.ConnectError:
        raise SystemExit(
            f"TrackBot не відповідає на {BASE}.\n"
            f"A2A — це два процеси: клієнт нічого не вміє сам, він лише\n"
            f"делегує задачі чужому агенту. Тому спершу підніміть сервер:\n"
            f"\n"
            f"    python a2a_server.py        # в іншому терміналі\n"
            f"\n"
            f"Або, якщо термінал лише один:\n"
            f"\n"
            f"    python a2a_client.py --with-server\n"
        )


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        # 1. Читаємо візитівку — до цього моменту ми про агента нічого не знали
        card = await fetch_card(http)
        print(f"Знайшов агента: {card['name']} — {card['description'][:60]}…")
        print("вміє:")
        for s in card.get("skills", []):
            print(f"  · {s['name']} ({s['id']})")

        # 2. Делегуємо задачі
        factory = ClientFactory(ClientConfig(httpx_client=http, streaming=False))
        client = await factory.create_from_url(BASE)

        for task in TASKS:
            print(f"\n→ делегую: «{task}»")
            async for event in client.send_message(ask(task)):
                answer = text_of(event)
                if answer:
                    print(f"← артефакт: {answer}")

    print("\nПуант: ми не викликали жодної функції TrackBot і не знаємо,")
    print("чи є в нього LLM усередині. Ми надіслали задачу — отримали результат.")


def serve_in_background():
    """Підняти сервер підпроцесом — для тих, у кого один термінал.

    Навчально чесніше запускати його окремо: видно, що це два незалежні
    процеси. Але коли треба просто побачити результат — так швидше.
    """
    import subprocess
    import time

    here = pathlib.Path(__file__).resolve().parent
    proc = subprocess.Popen([sys.executable, str(here / "a2a_server.py")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(40):                       # чекаємо, поки почне слухати
        time.sleep(0.25)
        try:
            httpx.get(f"{BASE}/.well-known/agent-card.json", timeout=1)
            print(f"[сам підняв сервер, pid {proc.pid}]\n")
            return proc
        except httpx.HTTPError:
            continue
    proc.terminate()
    raise SystemExit("Сервер не піднявся за 10 секунд. Запустіть його окремо "
                     "й подивіться, що він пише: python a2a_server.py")


if __name__ == "__main__":
    server = serve_in_background() if "--with-server" in sys.argv else None
    try:
        asyncio.run(main())
    finally:
        if server:
            server.terminate()
            print("\n[сервер зупинено]")

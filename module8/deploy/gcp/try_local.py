"""Виклик ADK-агента з коду — те, що робить `adk run`, але без REPL."""
import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from support_agent.agent import root_agent


async def main(query: str) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="support")
    session = await runner.session_service.create_session(app_name="support", user_id="u1")
    msg = types.Content(role="user", parts=[types.Part(text=query)])
    tools = []
    async for ev in runner.run_async(user_id="u1", session_id=session.id, new_message=msg):
        for part in (ev.content.parts if ev.content else []):
            if part.function_call:
                tools.append(part.function_call.name)
            elif part.text and ev.is_final_response():
                print(part.text)
    print("\nінструменти:", tools)


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or
                     "Посилка EE123456789UA не прийшла два тижні. Поверніть гроші за доставку."))

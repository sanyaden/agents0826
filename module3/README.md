# Модуль 3 — Фреймворки і Agent SDK

Продовження модуля 2. **Додається:** явні стани + чекпоінт — спершу руками,
потім те саме на LangGraph і langchain 1.x `create_agent`.

Право діяти ще НЕ з'явилось: `CAPABILITIES[3]` дає статус і перевірку
права (read-only). Претензія вперше буде оформлена на модулі 4 — і це
свідомо: фреймворк — про структуру, не про повноваження.

## Нове відносно модуля 2

- `modules/m03_framework.py` — стани VERIFY → DECIDE → CONFIRM + чекпоінт
  у `out/checkpoint.json`. Все — 50 рядків: фреймворк це не магія.
- `run_langgraph.py` — ті самі стани як вузли графа, checkpointer з
  коробки, `--pause` = interrupt після DECIDE + resume (готовий HITL).
- `run_adk.py` — той самий агент на Google ADK 2.0: інструменти-функції,
  callback-ліміт (аналог hooks), sub_agents із transfer_to_agent. Моделі —
  Claude через LiteLLM, щоб не заводити другий ключ.
- `run_agent_sdk.py` — той самий агент на Claude Agent SDK: свої
  інструменти як in-process MCP, hook блокує Bash кодом, чесна відмова
  на невідомому треку. Порівняйте вартість зі стеком B.
- `run_create_agent.py` — фішки langchain 1.x: `create_agent`, `@tool`
  (type hints = схема, docstring = опис), middleware. Наш MAX_TURNS з М1
  виявляється штатним `ModelCallLimitMiddleware`.

## Запуск

```bash
pip install -r requirements.txt
python run.py 3                     # стани + чекпоінт руками
python run_langgraph.py --pause     # LangGraph: interrupt + resume
python run_create_agent.py          # create_agent + middleware
```

Живе демо відновлення: `Ctrl+C` посеред `run.py 3` → перезапуск з
`resume=True` у коді → продовжує з CONFIRM, а не з «Доброго дня».

## Нюанси заняття

- Чекпоінт зберігає стан, але не ідемпотентність — тема повернеться на М8.
- Фреймворк додає шари в стектрейс: дебаг вимагає трейсів (аргумент до М7).
- Deprecated-мінне поле LangChain: AgentExecutor / LLMChain /
  ConversationBufferMemory ще живі у старих туторіалах — не вчіть мертві API.

## Як запустити (з нуля, 5 хвилин)

```bash
git clone https://github.com/sanyaden/agents0826.git
cd agents0826/module3

python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt        # усі чотири стеки одразу, ~3 хв
cp .env.example .env                   # і впишіть свій ANTHROPIC_API_KEY
```

**Ключ потрібен рівно один — `ANTHROPIC_API_KEY`.** Він живить усі чотири
стеки: LangGraph і `create_agent` через `langchain-anthropic`, Claude Agent
SDK напряму, Google ADK — через LiteLLM (тому другий ключ, гугловий, не
потрібен). `.env` читає `config.py` на старті, окремо експортувати змінні
не треба.

Перевірити, що все стало на місце:

```bash
python -c "import langchain, langgraph, claude_agent_sdk, google.adk; print('ok')"
```

| Файл | Що потрібно понад базу |
|---|---|
| `run.py 3`, `run_langgraph.py` | нічого, лише ключ |
| `run_create_agent.py` | `langchain-anthropic` (є в requirements) |
| `run_agent_sdk.py` | `claude-agent-sdk` — Node.js НЕ потрібен, CLI усередині пакета |
| `run_adk.py` | `google-adk[extensions]` — тягне `litellm`, найдовше ставиться |

Якщо не хочете важких стеків — приберіть два останні рядки з
`requirements.txt`: перші три команди практики працюватимуть.

## Практика заняття: один агент — чотири стеки

```bash
python run.py 3                  # руками: стани + чекпоінт (50 рядків)
python run_langgraph.py          # стек A: стани як вузли графа
python run_langgraph.py --pause  # пауза після DECIDE + resume (HITL)
python run_create_agent.py       # стек B: create_agent + middleware
python run_agent_sdk.py          # стек C: Claude Agent SDK — три сцени зі слайдів
python run_adk.py                # стек D: Google ADK 2.0 — callback + sub_agents
```

Перевірено з чистого venv 26.08: усі шість команд працюють після одного
`pip install -r requirements.txt`.

Порівнюйте чесно: рядки коду · що видно в стектрейсі · що робити при
падінні посеред діалогу · вартість.

**Лабораторна (з колоди):** перенесіть свого агента з модуля 1 на
**третій** стек — CrewAI, Claude Agent SDK або Google ADK. Здати:
посилання на репо + п'ять рядків «що виявилось простішим, а що
складнішим, ніж очікували».

**Далі (модуль 4):** три заняття поспіль ми відмовляємо клієнту.
Час дати агенту право діяти.

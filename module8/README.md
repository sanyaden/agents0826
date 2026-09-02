# Модуль 8 — Продакшн, деплой та AIOps

## Як почати

```bash
git clone https://github.com/sanyaden/agents0826.git      # або git pull, якщо вже є
cd agents0826/module8

cp .env.example .env                                       # вписати ANTHROPIC_API_KEY

# оточення 1 — агент курсу, як у всіх модулях
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# оточення 2 — треки деплою (Strands, ADK, LiteLLM). ОКРЕМЕ: strands
# вимагає mcp<2.0, а модуль 5 — mcp 2.x; разом вони не стають
python3 -m venv deploy/.venv && source deploy/.venv/bin/activate
pip install -r deploy/requirements.txt                     # ~100 с

python deploy/aws/agent.py                                 # ~10 с: агент відповів, взяв 2 інструменти
```

Якщо останній рядок вивів `інструменти: ['get_order_status', 'check_refund_eligibility']` —
усе стоїть. Далі — **[WORKSHOP.md](WORKSHOP.md)**: три треки деплою на вибір,
AWS AgentCore (Strands), GCP Agent Runtime (ADK) і Kubernetes на ноутбуці (k3d),
з реальними таймінгами. Код треків — у `deploy/`.

Що потрібно понад Python: для AWS — акаунт, Node 20+, `npm i -g @aws/agentcore`;
для GCP — проєкт із billing і `gcloud`; для Kubernetes — Docker і `brew install k3d`.
Хмарні акаунти не обов'язкові: трек C працює без них.
Продовження модуля 7. **Додається:** керований runtime, стрімінг,
HTTP-обгортка, контейнер і SLO. Головна думка — прямо в коді модуля:
логіка агента не змінюється, змінюється спосіб запуску.

## Нове відносно модуля 7

- `modules/m08_cloud.py` — обгортає модуль 6 і мапить кожен наш шар на
  керований сервіс AWS/GCP (`CLOUD_MAPPING`). Вся схема курсу = прайс-лист хмари.
- `modules/m09_client.py` — стрімінг: TTFT проти повного часу відповіді
  (з обліком вартості — стрім оминає звичайний виклик).
- `api.py` — FastAPI: `POST /ask` (повний цикл + вартість запиту),
  `GET /stream` (SSE: спершу фаза інструментів з подіями прогресу,
  стрімиться фінальна генерація — наївний стрім без tools чесно каже,
  що не бачить трекінгу).
- `Dockerfile` — python:3.12-slim, ключ тільки через env.
- `slo.py` — чотири метрики AIOps з даних, які курс уже виробляє:
  p95 · task success rate · вартість на УСПІШНУ задачу · escalation rate.

## Запуск

```bash
python run.py                  # всі 9 шарів
uvicorn api:app --port 8000
curl -s localhost:8000/ask -X POST -H 'content-type: application/json' \
     -d '{"query": "Посилка EE123456789UA не прийшла два тижні. Поверніть гроші."}'
python slo.py                  # офлайн, після run.py + eval_history
```

**Контейнер** (основа треку C і шляху Cloud Run; AgentCore і Agent Runtime
збирають його за вас):

```bash
docker build --provenance=false --sbom=false -t agentpro-m8 .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... agentpro-m8
```

Прапорці `--provenance=false --sbom=false` потрібні, якщо образ піде в
локальний Kubernetes: Docker Desktop додає атестації, які kubelet не
розпаковує.

Зверніть увагу: ключа в образі немає — тільки через `-e` у runtime
(у проді — Secret Manager). І чекпоінт у контейнері вмирає з рестартом —
живий аргумент за «стан поза процесом».

## Продакшн-нотатки

- Стан поза процесом: чекпоінт М3 у контейнері має жити в Redis/Firestore.
- Ідемпотентність повертається: retry черги + create_claim без ключа =
  дубльовані претензії.
- Деградація як дизайн: «складний агент → простий режим → людина» —
  наша ескалація і є нижній щабель.
- Kill switch, бюджети, відкат промптів як коду (git), online-евали.

**Далі — вайбатон:** README кореневого проєкту, розділ «Під свій домен»:
4 заміни (USER_QUERY, ORDERS, KB, evalset) — і кейс перестає бути навчальним.

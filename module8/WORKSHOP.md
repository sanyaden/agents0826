# Воркшоп М8 — деплой агента у хмару

Два шляхи на вибір і запасний без акаунта. Шлях A перевірено НАСКРІЗЬ
на живому AWS 02.09.2026 (CLI v0.28.1, eu-central-1): деплой пройшов,
хмарний агент відповів. Шлях B — за офіційним quickstart нової
платформи, без живого прогону.

## Що потрібно ДО заняття

**Нічого з цього не робиться за 30 хв воркшопу — тільки заздалегідь.**

| | Шлях A (AWS) | Шлях B (GCP) | Шлях C (без акаунта) |
|---|---|---|---|
| Акаунт | AWS-акаунт + IAM-user з AdministratorAccess | GCP-проєкт з увімкненим billing | не треба |
| CLI | `aws configure` з access-ключами | `gcloud auth login` | Docker |
| Локально | Node 20+, uv | Python 3.10+ | — |
| Гроші | центи за виклики; CDK-стек безкоштовний | центи + $0.25/1000 подій памʼяті | 0 |

Ключ моделі: підійде той самий `ANTHROPIC_API_KEY`, що й у всій практиці
(шлях A підтримує Anthropic напряму; Bedrock не обовʼязковий).

⚠️ Якщо колись ставили старий Python-CLI — приберіть, інакше конфлікт
імен команди: `pip uninstall bedrock-agentcore-starter-toolkit`.

---

## Шлях A · AWS Bedrock AgentCore

```bash
# 1) CLI (пакет називається БЕЗ -cli на кінці)
npm install -g @aws/agentcore

# 2) проєкт — майстер спитає фреймворк, модель, памʼять.
#    Наш вибір: Strands · Anthropic · памʼять none · протокол HTTP
agentcore create

cd <імʼя-проєкту>

# 3) локально, ще без хмари
agentcore dev              # dev-сервер (порт зайнятий? -p 8090)
agentcore dev "Де посилка 0500123456789?"

# 4) у хмару (потрібні креденшели; -y читає їх з профілю без питань)
agentcore deploy -y

# 5) перевірка
agentcore invoke "Де посилка 0500123456789?"
agentcore logs             # логи runtime
agentcore status           # що розгорнуто
```

Створений проєкт — звичайний код: агент у `app/<name>/`, інфраструктура
в `agentcore/` (CDK). Промпт і інструменти правляться прямо там.

**Реальні таймінги** (акаунт `ai_ws_lab`, eu-central-1, 02.09.2026):
`agentcore create` — секунди · `agentcore deploy` — **187 с** (перший
раз, з CDK bootstrap і збіркою) · `agentcore invoke` — **12 с**.
Тобто на живий деплой у воркшопі закладайте ~4 хвилини, і це якщо
акаунт уже налаштований. Розгортається CloudFormation-стек
`AgentCore-<проєкт>-default`, у ньому runtime + IAM-роль агента.

Після деплою CLI попереджає: індексація трейсів вмикається ще ~10 хв —
не лякайтесь, що трейс не одразу видно в CloudWatch.

**Підводні камені, перевірені на собі:**
- порт 8080 часто зайнятий Docker'ом — dev сам піде на 8081, але
  інвок теж треба слати з `-p`;
- `agentcore deploy` без налаштованої цілі скаже «Target "default"
  not found» — це нормально, перший інтерактивний `agentcore deploy`
  проведе через вибір акаунта й регіону;
- `--dry-run` показує, що буде створено, без деплою — добре для показу
  на екрані.

---

## Шлях B · GCP Agent Runtime (Gemini Enterprise Agent Platform)

До Next '26 це називалось Vertex AI Agent Engine — у старих статтях
шукайте стару назву, старі URL редіректять.

```bash
pip install --upgrade "google-cloud-aiplatform[agent_engines,adk]>=1.112"
gcloud auth application-default login
gsutil mb -l europe-west1 gs://<ваш-staging-bucket>
```

```python
import vertexai
from vertexai import agent_engines

client = vertexai.Client(project="my-proj", location="europe-west1")

app = agent_engines.AdkApp(agent=root_agent)   # ваш ADK-агент з модуля 3

remote = client.agent_engines.create(
    agent=app,
    config={"requirements": ["google-cloud-aiplatform[agent_engines,adk]"],
            "staging_bucket": "gs://<ваш-staging-bucket>"},
)
print(remote.resource_name)                    # готовий endpoint
```

Сесії та Memory Bank підключаються самі. IAM: `roles/aiplatform.user`
і `roles/storage.admin`; API `aiplatform.googleapis.com` увімкнене.

Альтернатива на Cloud Run зі спільною памʼяттю:

```bash
adk deploy cloud_run --project=$PROJECT --region=europe-west1 \
    --memory_service_uri=agentengine://<ENGINE_ID> ./my_agent
```

---

## Шлях C · без акаунта: той самий контейнер локально

«Деплой» — це контейнер плюс секрети зовні. Обидві хмари беруть на
вхід рівно те, що ви зараз зберете руками:

```bash
cd module8
docker build -t agentpro-m8 .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY agentpro-m8
curl -s localhost:8000/ask -X POST -H 'Content-Type: application/json' \
     -d '{"query": "Де посилка 0500123456789?"}'
```

Зверніть увагу: ключа немає ні в образі, ні в коді — лише в env.
Це та сама модель секретів, що в Secrets Manager, просто без хмари.

---

## Лабораторна (після будь-якого шляху)

1. **Секрети**: перекладіть ключ з env у Secrets Manager (AWS) чи
   Secret Manager (GCP) і дайте агенту роль на читання самого лише
   цього секрету.
2. **Ліміти**: max-instances (Cloud Run) або ліміт конкурентності
   (AgentCore) — щоб сплеск трафіку не став сплеском рахунку.
3. **Бюджет-алерт**: AWS Budgets / GCP Billing budget на $5 із
   нотифікацією. Це найдешевший guardrail усього курсу. Одним рядком,
   якщо не хочеться клікати в консолі:

```bash
aws budgets create-budget --account-id <ID> \
  --budget '{"BudgetName":"agentpro-guard","BudgetLimit":{"Amount":"5","Unit":"USD"},
             "TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL",
     "ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},
     "Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]}]'
```

## Прибрати за собою

Стек живий коштує копійки, але хай не висить:

```bash
aws cloudformation delete-stack --stack-name AgentCore-<проєкт>-default \
    --region eu-central-1
```

## Коли зробите

У картку Trello М8:

```
Шлях: A / B / C
Endpoint або скрін виклику: ...
Що в лабораторній вийшло: секрети / ліміти / бюджет
```

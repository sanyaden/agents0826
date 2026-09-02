# Воркшоп М8 — той самий агент у хмару трьома шляхами

Три треки на вибір, усі приводять до одного: агент підтримки, який ми
збирали вісім занять, працює не на ноутбуці. Що перевірено запуском
(02.09.2026), написано в кожному треку окремо; де не перевірено — теж.

| Трек | Куди | Що потрібно | Перевірено |
|---|---|---|---|
| A | AWS Bedrock AgentCore | AWS-акаунт, Node 20+, uv | наскрізь, на живому AWS |
| B | GCP Agent Runtime / Cloud Run | GCP-проєкт із billing, gcloud | локально так; хмара — за quickstart |
| C | Kubernetes на ноутбуці | Docker, kubectl, k3d | наскрізь, на k3d |

**Нічого з колонки «Що потрібно» не робиться за 30 хвилин воркшопу —
тільки заздалегідь.** Ключ моделі всюди той самий `ANTHROPIC_API_KEY`.

```bash
cd module8
python3 -m venv deploy/.venv && source deploy/.venv/bin/activate
pip install -r deploy/requirements.txt        # Strands, ADK, LiteLLM, ~100 с
```

Оточення для треків **окреме** від оточення агента курсу: `strands-agents`
вимагає `mcp<2.0`, а модуль 5 — `mcp 2.x`, разом вони не стають. Ключ
береться з `module8/.env` автоматично.

---

## Трек A · AWS: Strands → AgentCore

**Крок 1 — агент локально.** `deploy/aws/agent.py` — той самий агент
підтримки на Strands Agents (SDK від AWS) з моделлю Anthropic:

```bash
cd deploy/aws
python agent.py "Посилка EE123456789UA не прийшла два тижні. Поверніть гроші за доставку."
```

Побачите відповідь і `інструменти: ['get_order_status', 'check_refund_eligibility']`.
Це звичайний Python — жодної інфраструктури.

**Крок 2 — CLI і проєкт.** Пакет називається БЕЗ `-cli` на кінці, такого
пакета в npm просто немає:

```bash
npm install -g @aws/agentcore
agentcore create          # майстер: Strands · Anthropic · памʼять none · протокол HTTP
cd <імʼя-проєкту>
```

Скаффолд кладе агента в `app/<name>/main.py`. Замініть його готовим
`deploy/aws/agentcore_main.py` (або перенесіть руками дві функції з `@tool`
і `SYSTEM` з `agent.py`) — і в хмару поїде той самий агент підтримки.
Без цього кроку в хмарі відповідатиме скаффолдний «помічник з
калькулятором», і теза «той самий агент» буде неправдою.

**Крок 3 — локально, ще без хмари.**

```bash
agentcore dev -p 8090                                 # dev-сервер
agentcore dev -p 8090 "Де посилка EE123456789UA?"     # виклик
```

Порт 8080 часто зайнятий Docker'ом — тому явний `-p` в обох командах.

**Крок 4 — у хмару.** Потрібні креденшели (`aws configure` з
access-ключами IAM-користувача з `AdministratorAccess` — CDK створює ролі).

```bash
agentcore deploy -y       # -y бере креденшели з профілю без питань
agentcore invoke "Де посилка EE123456789UA?"
agentcore status · agentcore logs
```

**Реальні таймінги** (eu-central-1): `deploy` — **187 с** перший раз
(CDK bootstrap і збірка), **52 с** повторний; `invoke` — **12–16 с**. Тобто деплой робіть ДО
заняття, на сцені показуйте invoke. Розгортається стек
`AgentCore-<проєкт>-default`: runtime + окрема IAM-роль агента.
Індексація трейсів у CloudWatch вмикається ще ~10 хв після деплою.

Прибрати за собою: `aws cloudformation delete-stack --stack-name AgentCore-<проєкт>-default`.

---

## Трек B · GCP: ADK → Agent Runtime

До квітня 2026 це називалось Vertex AI Agent Engine — у старих статтях
шукайте стару назву, старі URL редіректять.

**Крок 1 — агент локально.** `deploy/gcp/support_agent/` — той самий агент
на Google ADK; модель Anthropic через LiteLLM, тож другий ключ не потрібен:

```bash
cd deploy/gcp
adk run support_agent                 # REPL у терміналі
adk web                               # веб-UI на :8000 з трасою кожного кроку
python try_local.py                   # те саме з коду, без REPL
```

Перевірено: агент бере обидва інструменти.

**Крок 2 — у хмару (за офіційним quickstart, без живого прогону).**
Потрібні: проєкт із billing, `gcloud auth application-default login`,
увімкнений `aiplatform.googleapis.com`, ролі `aiplatform.user` +
`storage.admin`, staging-bucket.

```bash
pip install --upgrade "google-cloud-aiplatform[agent_engines,adk]>=1.112"
gsutil mb -l europe-west1 gs://<ваш-staging-bucket>
```

```python
import vertexai
from vertexai import agent_engines
from support_agent.agent import root_agent

client = vertexai.Client(project="my-proj", location="europe-west1")
app = agent_engines.AdkApp(agent=root_agent)
remote = client.agent_engines.create(
    agent=app,
    config={"requirements": ["google-cloud-aiplatform[agent_engines,adk]", "litellm"],
            "staging_bucket": "gs://<ваш-staging-bucket>"},
)
print(remote.resource_name)
```

Сесії та Memory Bank підключаються самі. Ключ Anthropic для LiteLLM —
через змінну оточення runtime, не в коді.

**Альтернатива — Cloud Run** (serverless, з тією самою памʼяттю):

```bash
adk deploy cloud_run --project=$PROJECT --region=europe-west1 \
    --memory_service_uri=agentengine://<ENGINE_ID> ./support_agent
```

---

## Трек C · Kubernetes на ноутбуці — без жодного акаунта

«Деплой» — це контейнер плюс секрети зовні; Kubernetes лише запускає
його і тримає живим. Усе, що ви тут зробите, один в один переноситься
на EKS чи GKE.

```bash
brew install k3d                       # k3s у Docker
export ANTHROPIC_API_KEY=sk-ant-...
./deploy/k8s/up.sh                     # образ → кластер → секрет → деплой
```

Скрипт робить п'ять кроків і кожен називає. **Реальні таймінги:** кластер
з нуля — 44 с, `up.sh` при живому кластері — 22 с до Running.

```bash
kubectl port-forward svc/agentpro 8080:80          # в іншому терміналі
curl -s localhost:8080/ask -X POST -H 'content-type: application/json' \
     -d '{"query":"Де посилка EE123456789UA?"}'
kubectl get pods,hpa                                # HPA бачить CPU
```

Виклик — 12 с, у відповіді `tools` і `cost_usd`.

**Що подивитись у `deploy/k8s/`:** `deployment.yaml` — ключ із Secret,
readiness-проба, ліміти; `hpa.yaml` — автоскейл за CPU, і чому це поганий
сигнал для агентів; `keda-scaledobject.yaml` — як масштабують у проді,
за чергою.

**Три пастки, знайдені на прогоні** (усі вже враховані в скрипті):
- kind і minikube на Docker Desktop з ядром 7.x падають на cgroup v2 у
  kubelet — тому k3d;
- Docker Desktop додає в образ атестації, які kubelet не розпаковує —
  «pull access denied» на локальному образі; тому `--provenance=false`;
- Dockerfile не копіював `filters.py`, і контейнер падав на імпорті —
  образ, який ніколи не запускали, ніколи не працював.

Прибрати за собою: `k3d cluster delete agentpro`.

---

## Лабораторна (після будь-якого треку)

1. **Секрети**: ключ із env → Secrets Manager (AWS) / Secret Manager
   (GCP) / External Secrets (K8s); агенту — роль лише на читання цього
   секрету.
2. **Ліміти**: max-instances (Cloud Run), ліміт конкурентності
   (AgentCore), `maxReplicas` (HPA/KEDA) — щоб сплеск трафіку не став
   сплеском рахунку.
3. **Бюджет-алерт** на $5 — одна команда, найдешевший guardrail курсу:

```bash
aws budgets create-budget --account-id <ID> \
  --budget '{"BudgetName":"agentpro-guard","BudgetLimit":{"Amount":"5","Unit":"USD"},
             "TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL",
     "ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},
     "Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]}]'
```

## Коли зробите

У картку Trello М8:

```
Трек: A / B / C
Endpoint або вивід curl: ...
Лабораторна: секрети / ліміти / бюджет — що вийшло
```

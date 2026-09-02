#!/usr/bin/env bash
# Трек C наскрізь: образ → локальний кластер → секрет → деплой → виклик.
# Потрібні Docker, kubectl і k3d (brew install k3d). Хмара не потрібна.
#
# Чому k3d, а не kind/minikube: на Docker Desktop з ядром 7.x (осінь 2026)
# обидва падають на cgroup v2 у kubelet; k3d (k3s у Docker) — ні. Якщо у
# вас kind уже працює — замініть два рядки нижче, решта та сама.
set -euo pipefail
cd "$(dirname "$0")/../.."                       # корінь module8
: "${ANTHROPIC_API_KEY:?export ANTHROPIC_API_KEY=... перед запуском}"

echo "1/5 образ";           docker build -q --provenance=false --sbom=false -t agentpro-m8:local . >/dev/null
echo "2/5 кластер";         k3d cluster list 2>/dev/null | grep -q '^agentpro' \
                              || k3d cluster create agentpro --agents 0 --wait >/dev/null 2>&1
echo "3/5 образ у кластер"; k3d image import agentpro-m8:local -c agentpro >/dev/null 2>&1
echo "4/5 секрет";          kubectl create secret generic agent-secrets \
                              --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
                              --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "5/5 деплой";          kubectl apply -f deploy/k8s/deployment.yaml -f deploy/k8s/hpa.yaml >/dev/null
kubectl rollout status deployment/agentpro --timeout=180s
echo
echo "Готово. В іншому терміналі:  kubectl port-forward svc/agentpro 8080:80"
echo "і тоді:  curl -s localhost:8080/ask -X POST -H 'content-type: application/json' \\"
echo "            -d '{\"query\":\"Де посилка EE123456789UA?\"}'"

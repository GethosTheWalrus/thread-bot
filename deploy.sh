#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== ThreadBot Kubernetes Deployment Script ===${NC}"
echo -e "This script builds, pushes, and deploys ThreadBot to Kubernetes."
echo -e "Postgres, Temporal, and Redis are assumed to be external services.\n"

# ── Helper ────────────────────────────────────────────────────────────────────
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local result
    echo -en "${prompt} [${GREEN}${default}${NC}]: "
    read -r result
    echo "${result:-$default}"
}

# ── 1. Container Registry ────────────────────────────────────────────────────
echo -e "${BLUE}── Container Registry ──${NC}"
REGISTRY=$(prompt_with_default "Registry prefix" "git.home:5050/mike/thread-bot")

echo -e "\n${BLUE}── Image Pull Secret ──${NC}"
IMAGE_PULL_SECRET=$(prompt_with_default "imagePullSecrets name (leave empty for none)" "gitlab-registry-secret")

# ── 2. External Infrastructure ────────────────────────────────────────────────
echo -e "\n${BLUE}── PostgreSQL (external) ──${NC}"
PG_HOST=$(prompt_with_default "Postgres host" "192.168.69.11")
PG_PORT=$(prompt_with_default "Postgres port" "5432")
PG_USER=$(prompt_with_default "Postgres user" "postgres")
PG_PASS=$(prompt_with_default "Postgres password" "postgres")
PG_DB=$(prompt_with_default "Postgres database" "threadbot")
DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@${PG_HOST}:${PG_PORT}/${PG_DB}"

echo -e "\n${BLUE}── Temporal (external) ──${NC}"
TEMPORAL_HOST=$(prompt_with_default "Temporal host" "temporal-frontend.temporal.svc.cluster.local")
TEMPORAL_PORT=$(prompt_with_default "Temporal port" "7233")
TEMPORAL_NAMESPACE=$(prompt_with_default "Temporal namespace" "default")
TEMPORAL_TASK_QUEUE=$(prompt_with_default "Temporal task queue" "chatbot-task-queue")

echo -e "\n${BLUE}── Redis (external) ──${NC}"
REDIS_HOST=$(prompt_with_default "Redis host" "192.168.69.11")
REDIS_PORT=$(prompt_with_default "Redis port" "6379")
REDIS_DB=$(prompt_with_default "Redis DB number" "0")
REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}"

echo -e "\n${BLUE}── LLM Defaults (overridable via Settings UI) ──${NC}"
LLM_API_URL=$(prompt_with_default "LLM API URL" "http://192.168.69.11:11434/v1")
LLM_API_KEY=$(prompt_with_default "LLM API key" "ollama")
LLM_MODEL=$(prompt_with_default "LLM model" "llama3.1")

# ── 3. Generate ConfigMap ─────────────────────────────────────────────────────
echo -e "\n${BLUE}Generating k8s/configmap.yaml...${NC}"
cat > k8s/configmap.yaml <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: threadbot-config
  namespace: threadbot
data:
  # Database — external Postgres
  DATABASE_URL: "${DATABASE_URL}"
  # Temporal — external service
  TEMPORAL_HOST: "${TEMPORAL_HOST}"
  TEMPORAL_PORT: "${TEMPORAL_PORT}"
  TEMPORAL_NAMESPACE: "${TEMPORAL_NAMESPACE}"
  TEMPORAL_TASK_QUEUE: "${TEMPORAL_TASK_QUEUE}"
  # LLM defaults (overridable via Settings UI)
  LLM_API_URL: "${LLM_API_URL}"
  LLM_API_KEY: "${LLM_API_KEY}"
  LLM_MODEL: "${LLM_MODEL}"
  LLM_TEMPERATURE: "0.7"
  LLM_MAX_TOKENS: "2048"
  # Server
  HOST: "0.0.0.0"
  PORT: "8000"
  # Redis — external instance
  REDIS_URL: "${REDIS_URL}"
  REDIS_DB: "${REDIS_DB}"
EOF
echo -e "${GREEN}ConfigMap generated.${NC}"

# ── 4. Update image references in deployment.yaml ────────────────────────────
echo -e "\n${BLUE}Updating k8s/deployment.yaml with registry: ${GREEN}${REGISTRY}${NC}"
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' -E "s|image: .*/backend:latest|image: ${REGISTRY}/backend:latest|" k8s/deployment.yaml
    sed -i '' -E "s|image: .*/worker:latest|image: ${REGISTRY}/worker:latest|" k8s/deployment.yaml
    sed -i '' -E "s|image: .*/frontend:latest|image: ${REGISTRY}/frontend:latest|" k8s/deployment.yaml
else
    sed -i -E "s|image: .*/backend:latest|image: ${REGISTRY}/backend:latest|" k8s/deployment.yaml
    sed -i -E "s|image: .*/worker:latest|image: ${REGISTRY}/worker:latest|" k8s/deployment.yaml
    sed -i -E "s|image: .*/frontend:latest|image: ${REGISTRY}/frontend:latest|" k8s/deployment.yaml
fi

# Update imagePullSecrets
if [ -n "$IMAGE_PULL_SECRET" ]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' -E "s|name: .*-registry-secret|name: ${IMAGE_PULL_SECRET}|" k8s/deployment.yaml
    else
        sed -i -E "s|name: .*-registry-secret|name: ${IMAGE_PULL_SECRET}|" k8s/deployment.yaml
    fi
fi

# ── 5. Build & Push ──────────────────────────────────────────────────────────
echo -e "\n${BLUE}Setting up Docker Buildx for multi-arch builds...${NC}"
docker buildx create --use --name threadbot-builder 2>/dev/null || true
docker buildx inspect --bootstrap

echo -e "\n${BLUE}Building and pushing Backend / Worker (linux/amd64, linux/arm64)...${NC}"
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${REGISTRY}/backend:latest" \
  -t "${REGISTRY}/worker:latest" \
  --push \
  ./backend

echo -e "\n${BLUE}Building and pushing Frontend (linux/amd64, linux/arm64)...${NC}"
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile.frontend \
  -t "${REGISTRY}/frontend:latest" \
  --push \
  ./frontend

# ── 6. Deploy to Kubernetes ──────────────────────────────────────────────────
echo -e "\n${BLUE}Applying Kubernetes manifests...${NC}"
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml

# Force pull latest images
echo -e "\n${BLUE}Restarting deployments to pull new images...${NC}"
kubectl rollout restart deployment threadbot-backend -n threadbot
kubectl rollout restart deployment threadbot-worker -n threadbot
kubectl rollout restart deployment threadbot-frontend -n threadbot
kubectl rollout restart deployment threadbot-proxy -n threadbot

echo -e "\n${GREEN}Deployment complete!${NC}"
echo -e "Monitor pods:  ${BLUE}kubectl get pods -n threadbot -w${NC}"
echo -e "View logs:     ${BLUE}kubectl logs -f deployment/threadbot-worker -n threadbot${NC}"
echo -e "Backend health: ${BLUE}kubectl exec -n threadbot deploy/threadbot-backend -- curl -s http://localhost:8000/health${NC}"

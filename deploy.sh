#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== ThreadBot Interactive Deployment Script ===${NC}"

# 1. Ask for registry prefix
echo -e "Enter container registry prefix (e.g., git.home:5050/mike/thread-bot)."
echo -e "Leave empty to use the default (git.home:5050/mike/thread-bot):"
read -r REGISTRY

if [ -z "$REGISTRY" ]; then
    REGISTRY="git.home:5050/mike/thread-bot"
    echo -e "Using default registry: ${GREEN}${REGISTRY}${NC}"
fi

# Ask to replace registry prefix in k8s/deployment.yaml just in case it differs
echo -e "\n${BLUE}Updating k8s/deployment.yaml with the selected registry prefix...${NC}"
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' -E "s|image: .*/backend:latest|image: ${REGISTRY}/backend:latest|" k8s/deployment.yaml
    sed -i '' -E "s|image: .*/worker:latest|image: ${REGISTRY}/worker:latest|" k8s/deployment.yaml
    sed -i '' -E "s|image: .*/frontend:latest|image: ${REGISTRY}/frontend:latest|" k8s/deployment.yaml
else
    sed -i -E "s|image: .*/backend:latest|image: ${REGISTRY}/backend:latest|" k8s/deployment.yaml
    sed -i -E "s|image: .*/worker:latest|image: ${REGISTRY}/worker:latest|" k8s/deployment.yaml
    sed -i -E "s|image: .*/frontend:latest|image: ${REGISTRY}/frontend:latest|" k8s/deployment.yaml
fi

# 2. Setup buildx
echo -e "\n${BLUE}Setting up Docker Buildx for multi-arch builds...${NC}"
docker buildx create --use --name threadbot-builder 2>/dev/null || true
docker buildx inspect --bootstrap

# 3. Build & Push Multi-Arch backend/worker
echo -e "\n${BLUE}Building and Pushing Backend / Worker (linux/amd64, linux/arm64)...${NC}"
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${REGISTRY}/backend:latest" \
  -t "${REGISTRY}/worker:latest" \
  --push \
  ./backend

# 4. Build & Push Multi-Arch frontend
echo -e "\n${BLUE}Building and Pushing Frontend (linux/amd64, linux/arm64)...${NC}"
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile.frontend \
  -t "${REGISTRY}/frontend:latest" \
  --push \
  ./frontend

# 5. Update and deploy to k8s
echo -e "\n${BLUE}Applying Kubernetes manifests...${NC}"
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/configmap.yaml -f k8s/deployment.yaml

# Since we use :latest, we should rollout restart to force nodes to pull the latest images
echo -e "\n${BLUE}Restarting deployments to pull new images...${NC}"
kubectl rollout restart deployment threadbot-backend -n threadbot
kubectl rollout restart deployment threadbot-worker -n threadbot
kubectl rollout restart deployment threadbot-frontend -n threadbot
kubectl rollout restart deployment threadbot-proxy -n threadbot

echo -e "\n${GREEN}Deployment Complete! Monitor pod status with: kubectl get pods -n threadbot -w${NC}"

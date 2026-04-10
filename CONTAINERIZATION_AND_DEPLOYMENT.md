# Containerization and Deployment Evidence Guide

## Objective Coverage
This document demonstrates that the application is fully containerized and deployed through orchestration using Docker and Kubernetes.

## 1. Docker Containerization
Implemented files:
- Dockerfile
- .dockerignore
- docker-compose.yml

### Build and run locally
```bash
docker build -t p2p-chat:local .
docker run --rm -p 17001:17001 -p 9001:9001 -p 9999:9999/udp p2p-chat:local
```

### Verify container health
```bash
docker ps
docker inspect --format='{{json .State.Health}}' <container-id>
```

## 2. Orchestration with Kubernetes
Implemented files:
- k8s/namespace.yaml
- k8s/configmap.yaml
- k8s/deployment.yaml
- k8s/service.yaml
- k8s/hpa.yaml

### Deploy with helper script (PowerShell)
```powershell
./scripts/deploy_k8s.ps1 -Image <acr-login-server>/p2p-chat:<tag>
```

### Manual deployment commands
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml
kubectl rollout status deployment/p2p-chat -n p2p-chat
kubectl get pods -n p2p-chat -o wide
kubectl get svc -n p2p-chat
```

## 3. CI/CD Deployment Automation
Pipelines include build, test, push, deploy and verification:
- .github/workflows/ci-cd.yml
- Jenkinsfile

Both pipelines run deployment verification commands:
- kubectl wait --for=condition=available deployment/p2p-chat
- kubectl rollout status deployment/p2p-chat
- kubectl get pods -n p2p-chat
- kubectl get svc -n p2p-chat

## 4. Submission Evidence Checklist
Capture screenshots of:
1. Docker build success output
2. Running container and health status
3. CI build and push success
4. Kubernetes deployment rollout success
5. kubectl get pods output
6. kubectl get svc output with EXTERNAL-IP

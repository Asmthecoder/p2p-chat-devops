# Phased Implementation Checklist

This checklist maps directly to the required phases.

## Phase 1 Source Code and Version Control
Status: Implemented
- Web application implemented in Python with NiceGUI.
- Git repository initialized and pushed to GitHub.
- Branch and PR workflow documented in CONTRIBUTING.md.

Evidence files:
- main.py
- ui.py
- CONTRIBUTING.md

## Phase 2 Containerization
Status: Implemented
- Dockerfile added.
- docker-compose added for local run.
- CI/CD pushes container image to ACR.

Commands:
- docker build -t p2p-chat:local .
- docker run --rm -p 17001:17001 -p 9001:9001 -p 9999:9999/udp p2p-chat:local

Evidence files:
- Dockerfile
- docker-compose.yml
- .github/workflows/ci-cd.yml

## Phase 3 Infrastructure Provisioning IaC
Status: Implemented
Terraform provisions:
- Resource Group
- ACR
- AKS
- Log Analytics Workspace for Azure Monitor

Commands:
- terraform init
- terraform apply

Evidence files:
- infra/terraform/main.tf
- infra/terraform/variables.tf
- infra/terraform/outputs.tf

## Phase 4 Configuration Management
Status: Implemented
- Ansible playbook deploys Kubernetes manifests.
- Automates kubectl apply for namespace, configmap, deployment, service, hpa.

Command:
- ansible-playbook -i ansible/inventory.ini ansible/site.yml

Evidence files:
- ansible/site.yml
- k8s/deployment.yaml
- k8s/service.yaml

## Phase 5 CI/CD Pipeline Setup
Status: Implemented
- GitHub Actions pipeline automates test, build, push to ACR, deploy to AKS.
- Jenkins pipeline automates build, push, deploy.
- Trigger on push configured.
- Rollout verification included.

Evidence files:
- .github/workflows/ci-cd.yml
- Jenkinsfile

## Phase 6 Deployment and Validation
Status: Ready to execute in AKS after secrets setup
Validation commands:
- kubectl get pods -n p2p-chat
- kubectl get svc -n p2p-chat

Access:
- Use EXTERNAL-IP from p2p-chat-service LoadBalancer service.

## Phase 7 Documentation and Submission
Status: Implemented template
- Document commands and screenshots for each phase.
- Add architecture and pipeline diagrams.

Submission artifacts:
- README.md
- DEVOPS_PIPELINE.md
- AZURE_MONITOR_SETUP.md
- This checklist

## Suggested screenshot checklist
1. GitHub repo with branches and pull request.
2. Docker image build locally.
3. GitHub Actions successful run.
4. Terraform apply success output.
5. AKS kubectl get pods and get svc output.
6. Azure Monitor logs and metrics view.

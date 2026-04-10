# DevOps Pipeline Blueprint for P2P Chat

## Why this was added
This repository originally focused on distributed systems features. This document and related DevOps files extend it into a complete DevOps lifecycle project with automation, containerization, CI/CD, cloud deployment, and self-healing behavior.

## Toolchain in this project
- Git and GitHub for source control and collaboration
- GitHub Actions CI/CD in .github/workflows/ci-cd.yml
- Jenkins pipeline in Jenkinsfile
- Docker image build in Dockerfile
- Kubernetes deployment and autoscaling in k8s/
- Azure IaC with Terraform in infra/terraform/
- Configuration and deployment automation with Ansible in ansible/

## Final decisions used in this project
- Registry choice: Azure Container Registry (ACR)
- Final image name: <acr-login-server>/p2p-chat
- CI/CD engines: GitHub Actions and Jenkins
- Monitoring: Azure Monitor (via AKS + Log Analytics integration)

## Course objective mapping
1. Principles and practices of DevOps
- Documented and implemented via source control, CI, CD, IaC, and orchestration.

2. Streamlined processes and configuration management
- Automated build/test/deploy via pipelines.
- Kubernetes manifests and ConfigMap centralize runtime config.
- Ansible playbook standardizes deployment host setup and release.

3. Toolchain effectiveness demonstration
- Same app is deployable through GitHub Actions or Jenkins.
- Kubernetes with probes and HPA demonstrates resilience and scalability.

## Course outcome mapping
1. Fundamentals of DevOps
- Covered by combined use of SCM, CI, CD, containers, IaC, and monitoring-ready deployment manifests.

2. Ansible playbooks and provisioning workflow
- ansible/site.yml provisions host dependencies and applies manifests.

3. Task automation with Git, Docker, Ansible, Jenkins, Kubernetes
- Implemented using Jenkinsfile, Dockerfile, ansible/site.yml, and k8s manifests.

4. Comparative tool pipeline
- GitHub Actions and Jenkins are both present for CI/CD comparison.

5. Kubernetes and Jenkins CI/CD integration
- Jenkinsfile includes Kubernetes deployment stages with kubeconfig credential usage.

6. Self-healing mechanisms
- Kubernetes liveness and readiness probes restart unhealthy containers and remove non-ready pods from service routing.
- HPA enables scaling under load.

## Local workflow
1. Build image
- docker build -t p2p-chat:local .

2. Run container
- docker run --rm -p 17001:17001 -p 9001:9001 -p 9999:9999/udp p2p-chat:local

3. Open app
- http://localhost:17001

## GitHub Actions setup
Create these repository secrets before AKS deployment:
- AZURE_CREDENTIALS
- AKS_RESOURCE_GROUP
- AKS_CLUSTER_NAME
- ACR_NAME
- ACR_LOGIN_SERVER

Notes:
- ci-cd workflow builds and pushes:
	- <acr-login-server>/p2p-chat:<git-sha>
	- <acr-login-server>/p2p-chat:latest
- Deployment step auto-injects the exact SHA image into Kubernetes deployment.
- Use provision-aks workflow to create AKS first when cluster does not exist.

## Jenkins setup
Set these Jenkins environment values or credentials:
- ACR_CREDENTIALS_ID
- ACR_LOGIN_SERVER
- KUBE_CONFIG_CREDENTIALS_ID

## Terraform workflow
From infra/terraform:
1. terraform init
2. terraform plan -out tfplan
3. terraform apply tfplan

After apply, configure kubectl context to AKS and then deploy manifests in k8s/.

AKS provisioning from GitHub Actions:
- Run .github/workflows/provision-aks.yml using workflow_dispatch.
- It creates AKS, ACR, and Log Analytics workspace, then prints outputs.

## Ansible workflow
From ansible:
1. Copy inventory.ini.example to inventory.ini and edit host/IP.
2. Run: ansible-playbook -i inventory.ini site.yml

## Kubernetes self-healing checks
1. Confirm probes and pods
- kubectl describe deployment p2p-chat -n p2p-chat

2. Delete a pod to test replacement
- kubectl delete pod -l app=p2p-chat -n p2p-chat --grace-period=0 --force

3. Watch self-healing recreation
- kubectl get pods -n p2p-chat -w

## Azure Monitor checks
1. Verify monitoring addon is enabled
- az aks show --resource-group <rg> --name <aks-name> --query addonProfiles.omsagent.enabled

2. Query logs for container events in workspace
- Use Azure Portal > Monitor > Logs > select Log Analytics workspace output by Terraform.

3. Create alerts
- Configure alert rules on pod restarts, CPU, and memory from Azure Monitor metrics.

# Infrastructure as Code Automation Guide

This project provides fully reproducible infrastructure and deployment automation using Terraform and Ansible.

## Terraform (Infra Provisioning)
Resources provisioned:
- Azure Resource Group
- Azure Container Registry (ACR)
- Azure Kubernetes Service (AKS)
- Log Analytics Workspace (Azure Monitor)

Key files:
- infra/terraform/providers.tf
- infra/terraform/variables.tf
- infra/terraform/main.tf
- infra/terraform/outputs.tf

### Automated local provisioning
```powershell
./scripts/provision_infra.ps1 -AutoApprove
```

### Automated local destroy
```powershell
./scripts/destroy_infra.ps1 -AutoApprove
```

## Ansible (Configuration and Deployment)
Ansible playbook automates:
- Deployment host prep
- Kubernetes manifest apply
- Dynamic deployment image rendering
- Deployment wait and verification

Key file:
- ansible/site.yml

### Example run
```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e "app_image=<acr-login-server>/p2p-chat:latest"
```

## CI Validation for IaC
GitHub workflow validates both Terraform and Ansible syntax on changes.

Workflow file:
- .github/workflows/iac-validate.yml

Validation includes:
- terraform fmt -check
- terraform init -backend=false
- terraform validate
- ansible-playbook --syntax-check

## Reproducibility Evidence Checklist
1. Run scripts/provision_infra.ps1 and capture outputs.
2. Capture terraform validate success in CI logs.
3. Run ansible deployment with app_image and capture pod/service outputs.
4. Capture kubectl get pods and kubectl get svc for deployed stack.

# Azure Monitor Setup for AKS

## What is already configured
Terraform creates:
- Resource group
- ACR
- AKS
- Log Analytics workspace
- AKS oms_agent integration to Log Analytics

This gives container insights telemetry for AKS workloads.

## Verify monitoring is enabled
1. Azure CLI login
- az login

2. Check AKS monitoring addon
- az aks show --resource-group <resource-group> --name <aks-name> --query addonProfiles.omsagent.enabled

Expected output: true

## View logs and metrics
1. Open Azure Portal
2. Go to Monitor > Logs
3. Select the Log Analytics workspace output by Terraform
4. Use queries for Kubernetes workloads and container health

## Suggested alert rules
1. Pod restart spikes
- Metric: kube_pod_container_status_restarts_total
- Condition: increase over threshold in 5 min

2. CPU high usage
- Metric: node or pod CPU utilization
- Condition: average > 80 percent for 10 min

3. Memory pressure
- Metric: pod memory working set
- Condition: average > 85 percent for 10 min

## Optional: Managed Prometheus and Grafana
If you want Azure managed Prometheus and managed Grafana, enable the relevant AKS monitoring profile and create Azure Managed Grafana resources in Terraform as an extension.

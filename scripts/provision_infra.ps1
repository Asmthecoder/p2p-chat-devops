param(
    [string]$TfDir = "infra/terraform",
    [string]$Prefix = "p2pchat",
    [string]$Location = "Central India",
    [string]$KubernetesVersion = "1.34.4",
    [switch]$AutoApprove
)

Push-Location $TfDir
try {
    terraform init
    terraform fmt -recursive
    terraform validate
    terraform plan -out tfplan -var "prefix=$Prefix" -var "location=$Location" -var "kubernetes_version=$KubernetesVersion"

    if ($AutoApprove) {
        terraform apply -auto-approve tfplan
    } else {
        terraform apply tfplan
    }

    Write-Host "Resource Group: $(terraform output -raw resource_group_name)"
    Write-Host "AKS Cluster:   $(terraform output -raw aks_cluster_name)"
    Write-Host "ACR Name:      $(terraform output -raw acr_name)"
    Write-Host "ACR Login:     $(terraform output -raw acr_login_server)"
} finally {
    Pop-Location
}

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
    if ($AutoApprove) {
        terraform destroy -auto-approve -var "prefix=$Prefix" -var "location=$Location" -var "kubernetes_version=$KubernetesVersion"
    } else {
        terraform destroy -var "prefix=$Prefix" -var "location=$Location" -var "kubernetes_version=$KubernetesVersion"
    }
} finally {
    Pop-Location
}

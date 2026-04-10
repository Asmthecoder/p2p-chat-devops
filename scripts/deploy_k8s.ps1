param(
    [string]$Namespace = "p2p-chat",
    [string]$Image,
    [string]$KubeContext = ""
)

if (-not $Image) {
    Write-Error "Provide -Image <acr-login-server>/p2p-chat:<tag>"
    exit 1
}

if ($KubeContext -ne "") {
    kubectl config use-context $KubeContext
}

$tempFile = Join-Path $env:TEMP "p2p-chat-deployment.yaml"
(Get-Content "k8s/deployment.yaml") -replace "IMAGE_PLACEHOLDER", $Image | Set-Content $tempFile

kubectl apply -f "k8s/namespace.yaml"
kubectl apply -f "k8s/configmap.yaml"
kubectl apply -f $tempFile
kubectl apply -f "k8s/service.yaml"
kubectl apply -f "k8s/hpa.yaml"

kubectl wait --for=condition=available deployment/p2p-chat -n $Namespace --timeout=180s
kubectl rollout status deployment/p2p-chat -n $Namespace --timeout=180s
kubectl get pods -n $Namespace -o wide
kubectl get svc -n $Namespace

Write-Host "Deployment completed. Use External-IP from service output to access the app." -ForegroundColor Green

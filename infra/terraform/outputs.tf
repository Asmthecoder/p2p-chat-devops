output "resource_group_name" {
  value = local.resource_group_name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.aks.name
}

output "acr_login_server" {
  value = local.acr_login_server
}

output "acr_name" {
  value = local.acr_name
}

output "log_analytics_workspace_name" {
  value = local.law_name
}

output "log_analytics_workspace_id" {
  value = local.law_id
}

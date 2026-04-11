resource "azurerm_resource_group" "rg" {
  count    = var.create_resource_group ? 1 : 0
  name     = "${var.prefix}-rg"
  location = var.location
}

data "azurerm_resource_group" "existing_rg" {
  count = var.create_resource_group ? 0 : 1
  name  = "${var.prefix}-rg"
}

locals {
  resource_group_name     = var.create_resource_group ? azurerm_resource_group.rg[0].name : data.azurerm_resource_group.existing_rg[0].name
  resource_group_location = var.create_resource_group ? azurerm_resource_group.rg[0].location : data.azurerm_resource_group.existing_rg[0].location
  acr_name                = var.create_resource_group ? azurerm_container_registry.acr[0].name : data.azurerm_container_registry.acr[0].name
  acr_login_server        = var.create_resource_group ? azurerm_container_registry.acr[0].login_server : data.azurerm_container_registry.acr[0].login_server
  law_name                = var.create_resource_group ? azurerm_log_analytics_workspace.law[0].name : data.azurerm_log_analytics_workspace.law[0].name
  law_id                  = var.create_resource_group ? azurerm_log_analytics_workspace.law[0].id : data.azurerm_log_analytics_workspace.law[0].id
}

resource "azurerm_container_registry" "acr" {
  count               = var.create_resource_group ? 1 : 0
  name                = replace("${var.prefix}acr", "-", "")
  resource_group_name = local.resource_group_name
  location            = local.resource_group_location
  sku                 = "Basic"
  admin_enabled       = false
}

data "azurerm_container_registry" "acr" {
  count               = var.create_resource_group ? 0 : 1
  name                = replace("${var.prefix}acr", "-", "")
  resource_group_name = local.resource_group_name
}

resource "azurerm_log_analytics_workspace" "law" {
  count               = var.create_resource_group ? 1 : 0
  name                = "${var.prefix}-law"
  location            = local.resource_group_location
  resource_group_name = local.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

data "azurerm_log_analytics_workspace" "law" {
  count               = var.create_resource_group ? 0 : 1
  name                = "${var.prefix}-law"
  resource_group_name = local.resource_group_name
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "${var.prefix}-aks"
  location            = local.resource_group_location
  resource_group_name = local.resource_group_name
  dns_prefix          = "${var.prefix}-dns"
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Free"
  support_plan        = "KubernetesOfficial"

  default_node_pool {
    name       = "system"
    node_count = var.node_count
    vm_size    = var.vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  oms_agent {
    log_analytics_workspace_id = local.law_id
  }

  network_profile {
    network_plugin    = "azure"
    load_balancer_sku = "standard"
  }
}


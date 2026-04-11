variable "prefix" {
  description = "Prefix for all Azure resources"
  type        = string
  default     = "p2pchat"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "centralindia"
}

variable "create_resource_group" {
  description = "Create the resource group in Terraform. Set false to use an existing group."
  type        = bool
  default     = true
}

variable "kubernetes_version" {
  description = "AKS Kubernetes version"
  type        = string
  default     = "1.34.4"
}

variable "node_count" {
  description = "Default node count"
  type        = number
  default     = 2
}

variable "vm_size" {
  description = "AKS node size"
  type        = string
  default     = "Standard_D2s_v3"
}

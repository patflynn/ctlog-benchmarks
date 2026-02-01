variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP Zone"
  type        = string
  default     = "us-central1-a"
}

variable "github_repo" {
  description = "GitHub Repository (owner/name)"
  type        = string
  default     = "patflynn/ctlog-benchmarks"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro"
}

variable "spanner_processing_units" {
  description = "Spanner processing units"
  type        = number
  default     = 100
}

variable "gke_node_count" {
  description = "Number of GKE nodes in benchmark pool"
  type        = number
  default     = 2
}

variable "gke_machine_type" {
  description = "GKE node machine type"
  type        = string
  default     = "e2-standard-2"
}

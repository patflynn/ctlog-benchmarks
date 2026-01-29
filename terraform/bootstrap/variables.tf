variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "github_repo" {
  description = "GitHub Repository (owner/name)"
  type        = string
  default     = "patflynn/ctlog-benchmarks"
}

# Cloud SQL for Trillian
resource "google_sql_database_instance" "trillian_db" {
  name             = "trillian-mysql"
  database_version = "MYSQL_8_0"
  region           = var.region
  project          = var.project_id

  settings {
    tier = "db-f1-micro" # Smallest for initial setup
    ip_configuration {
      ipv4_enabled = true
      # No authorized networks - we use Cloud SQL Proxy
    }
  }
  deletion_protection = false # For benchmarking ease
}

resource "google_sql_database" "trillian" {
  name     = "trillian"
  instance = google_sql_database_instance.trillian_db.name
  project  = var.project_id
}

# Service Account for Trillian Log Server/Signer
resource "google_service_account" "trillian_sa" {
  account_id   = "trillian-sa"
  display_name = "Trillian Service Account"
  project      = var.project_id
}

resource "google_project_iam_member" "trillian_db_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.trillian_sa.email}"
}

# Workload Identity for Trillian (K8s Namespace: trillian)
resource "google_service_account_iam_member" "trillian_wi" {
  service_account_id = google_service_account.trillian_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[trillian/trillian-sa]"
}

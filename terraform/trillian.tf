# Cloud SQL for Trillian
resource "google_sql_database_instance" "trillian_db" {
  name             = "trillian-mysql"
  database_version = "MYSQL_8_0"
  region           = var.region
  project          = var.project_id

  settings {
    tier = var.cloud_sql_tier
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

# Database User & Password
resource "random_password" "db_password" {
  length  = 16
  special = false
}

resource "google_sql_user" "trillian_user" {
  name     = "trillian"
  instance = google_sql_database_instance.trillian_db.name
  password = random_password.db_password.result
  project  = var.project_id
}

resource "google_secret_manager_secret" "db_pass_secret" {
  secret_id = "trillian-db-password"
  replication {
    auto {}
  }
  project = var.project_id
}

resource "google_secret_manager_secret_version" "db_pass_version" {
  secret = google_secret_manager_secret.db_pass_secret.id
  secret_data = random_password.db_password.result
}

# Allow CI/CD SA to read this secret (so deploy script can inject it)
resource "google_secret_manager_secret_iam_member" "ci_sa_secret_access" {
  secret_id = google_secret_manager_secret.db_pass_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:github-actions-sa@${var.project_id}.iam.gserviceaccount.com"
}

# Workload Identity for Trillian (K8s Namespace: trillian)
resource "google_service_account_iam_member" "trillian_wi" {
  service_account_id = google_service_account.trillian_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[trillian/trillian-sa]"
}

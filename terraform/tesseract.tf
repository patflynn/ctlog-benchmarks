# Service Account for TesseraCT
resource "google_service_account" "tesseract_sa" {
  account_id   = "tesseract-sa"
  display_name = "TesseraCT Service Account"
  project      = var.project_id
}

# Workload Identity for TesseraCT (Namespace: tesseract)
resource "google_service_account_iam_member" "tesseract_wi" {
  service_account_id = google_service_account.tesseract_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[tesseract/tesseract-sa]"
}

# --- Storage (GCS) ---
resource "google_storage_bucket" "tesseract_bucket" {
  name          = "tesseract-storage-${var.project_id}"
  location      = var.region
  project       = var.project_id
  force_destroy = true # Simplify cleanup for benchmarks

  uniform_bucket_level_access = true
}

resource "google_storage_bucket_iam_member" "tesseract_gcs_admin" {
  bucket = google_storage_bucket.tesseract_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.tesseract_sa.email}"
}

# --- Database (Spanner) ---
resource "google_spanner_instance" "tesseract_instance" {
  name         = "tesseract-instance"
  config       = "regional-${var.region}"
  display_name = "TesseraCT Instance"
  project      = var.project_id
  
  processing_units = 100 # Minimum for benchmark start
}

resource "google_spanner_database" "tesseract_db" {
  instance = google_spanner_instance.tesseract_instance.name
  name     = "tesseract-db"
  project  = var.project_id
  
  deletion_protection = false
}

resource "google_spanner_database_iam_member" "tesseract_spanner_user" {
  instance = google_spanner_instance.tesseract_instance.name
  database = google_spanner_database.tesseract_db.name
  role     = "roles/spanner.databaseUser"
  member   = "serviceAccount:${google_service_account.tesseract_sa.email}"
}

# --- Secrets (Signer Keys) ---
# Note: The actual key content must be populated manually or via a setup script.
resource "google_secret_manager_secret" "signer_priv" {
  secret_id = "tesseract-signer-priv"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "signer_pub" {
  secret_id = "tesseract-signer-pub"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "signer_priv_access" {
  secret_id = google_secret_manager_secret.signer_priv.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.tesseract_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "signer_pub_access" {
  secret_id = google_secret_manager_secret.signer_pub.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.tesseract_sa.email}"
}

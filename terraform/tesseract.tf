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

  processing_units = var.spanner_processing_units
  force_destroy    = true
}

resource "google_spanner_database" "tesseract_db" {
  instance = google_spanner_instance.tesseract_instance.name
  name     = "tesseract-db"
  project  = var.project_id
  
  deletion_protection = false

  ddl = [
    "CREATE TABLE Tessera (id INT64 NOT NULL, compatibilityVersion INT64 NOT NULL) PRIMARY KEY (id)",
    "CREATE TABLE SeqCoord (id INT64 NOT NULL, next INT64 NOT NULL) PRIMARY KEY (id)",
    "CREATE TABLE Seq (id INT64 NOT NULL, seq INT64 NOT NULL, v BYTES(MAX)) PRIMARY KEY (id, seq)",
    "CREATE TABLE IntCoord (id INT64 NOT NULL, seq INT64 NOT NULL, rootHash BYTES(32)) PRIMARY KEY (id)",
    "CREATE TABLE FollowCoord (id INT64 NOT NULL, nextIdx INT64 NOT NULL) PRIMARY KEY (id)",
    "CREATE TABLE IDSeq (h BYTES(32) NOT NULL, idx INT64 NOT NULL) PRIMARY KEY (h)",
  ]
}

resource "google_spanner_database_iam_member" "tesseract_spanner_user" {
  instance = google_spanner_instance.tesseract_instance.name
  database = google_spanner_database.tesseract_db.name
  role     = "roles/spanner.databaseUser"
  member   = "serviceAccount:${google_service_account.tesseract_sa.email}"
}

# --- Secrets (Signer Keys) ---
resource "tls_private_key" "tesseract_signer" {
  algorithm = "ECDSA"
  ecdsa_curve = "P256"
}

resource "google_secret_manager_secret" "signer_priv" {
  secret_id = "tesseract-signer-priv"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "signer_priv_version" {
  secret = google_secret_manager_secret.signer_priv.id
  secret_data = tls_private_key.tesseract_signer.private_key_pem
}

resource "google_secret_manager_secret" "signer_pub" {
  secret_id = "tesseract-signer-pub"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "signer_pub_version" {
  secret = google_secret_manager_secret.signer_pub.id
  secret_data = tls_private_key.tesseract_signer.public_key_pem
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

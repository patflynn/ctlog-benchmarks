resource "google_container_cluster" "primary" {
  name     = "ctlog-cluster"
  location = var.zone
  project  = var.project_id

  # We can't create a cluster with no node pool defined, but we want to only use
  # separately managed node pools. So we create the smallest possible default
  # node pool and immediately delete it.
  remove_default_node_pool = true
  initial_node_count       = 1

  deletion_protection = false

  network    = google_compute_network.vpc.name
  subnetwork = google_compute_subnetwork.subnet.name

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Enable Workload Identity
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "benchmark_pool" {
  name       = "benchmark-pool"
  location   = var.zone
  cluster    = google_container_cluster.primary.name
  project    = var.project_id
  node_count = 2

  node_config {
    preemptible  = false
    machine_type = "e2-standard-2" # 2 vCPU, 8GB RAM

    # Google recommends custom service accounts that have cloud-platform scope and permissions granted via IAM.
    service_account = google_service_account.node_sa.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
    
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}

resource "google_service_account" "node_sa" {
  account_id   = "gke-node-sa"
  display_name = "GKE Node Service Account"
  project      = var.project_id
}

resource "google_project_iam_member" "node_sa_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.admin" # Upgraded from objectViewer to ensure access
  member  = "serviceAccount:${google_service_account.node_sa.email}"
}

resource "google_project_iam_member" "node_sa_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.node_sa.email}"
}

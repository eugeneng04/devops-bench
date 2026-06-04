terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
  zone    = var.location
}

# 1. GKE Cluster Provisioning
module "gke" {
  source       = "../../modules/gke"
  project_id   = var.project_id
  cluster_name = var.cluster_name
  location     = var.location
  node_count   = var.node_count
  machine_type = var.machine_type
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

# 3. GCS Bucket for etcd Backups
resource "google_storage_bucket" "etcd_backup" {
  name                        = "cpr-${var.project_id}-${var.namespace}"
  location                    = "US"
  force_destroy               = true
  project                     = var.project_id
  uniform_bucket_level_access = true
}

# 4. GCP IAM & GSA Configuration
locals {
  gke_node_sa_email = "gke-nodes-${trim(substr(var.cluster_name, 0, 15), "-")}@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_service_account" "cp_recovery_sa" {
  account_id   = "cp-recovery-sa"
  display_name = "GSA for GKE Control Plane Recovery access"
  project      = var.project_id
}

resource "google_storage_bucket_iam_member" "gsa_bucket_access" {
  bucket = google_storage_bucket.etcd_backup.name
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.cp_recovery_sa.email}"
}

# Grant storage access to OpenClaw VM Service Account so agent can download backups
resource "google_storage_bucket_iam_member" "openclaw_vm_bucket_access" {
  bucket = google_storage_bucket.etcd_backup.name
  role   = "roles/storage.admin"
  member = "serviceAccount:openclaw-vm-sa@${var.project_id}.iam.gserviceaccount.com"
}

# Grant storage access to GKE Nodes Service Account since the setup Job pod runs as GKE Node SA
resource "google_storage_bucket_iam_member" "gke_nodes_bucket_access" {
  bucket = google_storage_bucket.etcd_backup.name
  role   = "roles/storage.admin"
  member = "serviceAccount:${local.gke_node_sa_email}"
}

resource "google_service_account_iam_member" "setup_workload_identity" {
  service_account_id = google_service_account.cp_recovery_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/cp-recovery-setup-sa]"
}

# 5. Kubernetes Namespace
resource "kubernetes_namespace" "cp_recovery" {
  metadata {
    name = var.namespace
  }
}

# 6. Service Account for setup Job
resource "kubernetes_service_account" "setup_sa" {
  metadata {
    name      = "cp-recovery-setup-sa"
    namespace = var.namespace
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.cp_recovery_sa.email
    }
  }
  depends_on = [kubernetes_namespace.cp_recovery]
}

# 7. Render Manifests
resource "local_file" "manifests_yaml" {
  content = replace(
    replace(file("${path.module}/manifests.yaml"), "{{NAMESPACE}}", var.namespace),
    "{{APISERVER_PYTHON_CODE}}",
    indent(4, file("${path.module}/apiserver.py"))
  )
  filename = "${path.module}/manifests-rendered.yaml"
}

resource "local_file" "setup_job_yaml" {
  content = replace(
    replace(
      replace(
        replace(file("${path.module}/setup-job.yaml"), "{{NAMESPACE}}", var.namespace),
        "{{GCS_BUCKET_NAME}}",
        google_storage_bucket.etcd_backup.name
      ),
      "{{SETUP_SCRIPT_CODE}}",
      indent(4, replace(file("${path.module}/setup-and-corrupt.sh"), "{{GCS_BUCKET_NAME}}", google_storage_bucket.etcd_backup.name))
    ),
    "{{CORRUPTOR_YAML_CODE}}",
    indent(4, replace(file("${path.module}/corruptor.yaml"), "{{NAMESPACE}}", var.namespace))
  )
  filename = "${path.module}/setup-job-rendered.yaml"
}

# 8. Apply Manifests
resource "null_resource" "kubernetes_manifests" {
  depends_on = [
    module.gke,
    kubernetes_namespace.cp_recovery,
    kubernetes_service_account.setup_sa,
    local_file.manifests_yaml,
    local_file.setup_job_yaml
  ]

  triggers = {
    namespace              = var.namespace
    cluster_name           = module.gke.cluster_name
    cluster_location       = module.gke.cluster_location
    project_id             = var.project_id
    manifests_path         = local_file.manifests_yaml.filename
    setup_job_path         = local_file.setup_job_yaml.filename
  }

  provisioner "local-exec" {
    command = <<EOT
      gcloud container clusters get-credentials ${module.gke.cluster_name} --location ${module.gke.cluster_location} --project ${var.project_id}
      kubectl apply -f ${local_file.manifests_yaml.filename}
      kubectl apply -f ${local_file.setup_job_yaml.filename}
      
      echo "Waiting for setup-and-corrupt Job to complete..."
      kubectl wait --for=condition=complete job/setup-and-corrupt --namespace ${var.namespace} --timeout=240s
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      gcloud container clusters get-credentials ${self.triggers.cluster_name} --location ${self.triggers.cluster_location} --project ${self.triggers.project_id}
      [ -n "${lookup(self.triggers, "setup_job_path", "")}" ] && kubectl delete -f ${lookup(self.triggers, "setup_job_path", "")} --ignore-not-found=true || true
      [ -n "${lookup(self.triggers, "manifests_path", "")}" ] && kubectl delete -f ${lookup(self.triggers, "manifests_path", "")} --ignore-not-found=true || true
      [ -n "${lookup(self.triggers, "apiserver_path", "")}" ] && kubectl delete -f ${lookup(self.triggers, "apiserver_path", "")} --ignore-not-found=true || true
      [ -n "${lookup(self.triggers, "etcd_path", "")}" ] && kubectl delete -f ${lookup(self.triggers, "etcd_path", "")} --ignore-not-found=true || true
      [ -n "${lookup(self.triggers, "configmaps_path", "")}" ] && kubectl delete -f ${lookup(self.triggers, "configmaps_path", "")} --ignore-not-found=true || true
      [ -n "${lookup(self.triggers, "rbac_path", "")}" ] && kubectl delete -f ${lookup(self.triggers, "rbac_path", "")} --ignore-not-found=true || true
    EOT
  }
}

# 9. Grant permissions to OpenClaw VM Service Account
resource "google_project_iam_member" "openclaw_vm_container_admin" {
  project = var.project_id
  role    = "roles/container.admin"
  member  = "serviceAccount:openclaw-vm-sa@${var.project_id}.iam.gserviceaccount.com"
}

output "cluster_name" {
  value = module.gke.cluster_name
}

output "cluster_location" {
  value = module.gke.cluster_location
}

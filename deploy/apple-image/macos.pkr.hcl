# Packer template for the macOS build image used by the Mac builder (see docs/apple-image.md).
# Build: packer init . && packer build -var base_image=<ghcr.io/...@sha256:...> .

packer {
  required_plugins {
    tart = {
      version = "= 1.14.0"
      source  = "github.com/cirruslabs/tart"
    }
  }
}

variable "base_image" {
  type        = string
  description = "Pinned base macOS image with the Xcode to build with (name@sha256:digest, admin user with passwordless sudo)"

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.base_image))
    error_message = "The base_image must be pinned by digest (name@sha256:<64 hex characters>)."
  }
}

variable "vm_name" {
  type    = string
  default = "palabre-macos"
}

source "tart-cli" "palabre" {
  from_ociimage = var.base_image
  vm_name       = var.vm_name
  cpu_count     = 4
  memory_gb     = 8
  disk_size_gb  = 80
  ssh_username  = "admin"
  ssh_password  = "admin"
  ssh_timeout   = "180s"
}

build {
  sources = ["source.tart-cli.palabre"]

  provisioner "file" {
    source      = "palabre-job-runner.sh"
    destination = "/tmp/palabre-job-runner"
  }

  provisioner "shell" {
    script = "provision.sh"
  }
}

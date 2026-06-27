#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
# Usage: docker-run.sh <build|verify|run CMD...|shell|doc-html [trm|integrator]|doc-pdf [trm|integrator]>
#   build     build firmware image        verify    gcc version + multilibs
#   run CMD   run in firmware image       shell     interactive firmware shell
#   doc-html  build HTML with Antora image doc-pdf  build PDF with Asciidoctor image
# Env: OCAH_DOCKER_IMAGE       firmware image tag (default: ocah-toolchain)
#      OCAH_DOC_HTML_IMAGE     prebuilt Antora image
#      OCAH_DOC_PDF_IMAGE      prebuilt Asciidoctor image
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${OCAH_DOCKER_IMAGE:-ocah-toolchain}"
DOC_HTML_IMAGE="${OCAH_DOC_HTML_IMAGE:-docker.io/antora/antora:3.1.10}"
DOC_PDF_IMAGE="${OCAH_DOC_PDF_IMAGE:-docker.io/asciidoctor/docker-asciidoctor:latest}"

if command -v podman >/dev/null 2>&1; then ENGINE=podman VOL=":Z"
elif command -v docker >/dev/null 2>&1; then ENGINE=docker VOL=""
else echo "error: podman or docker is required" >&2; exit 1; fi

# run_image IMAGE [-it] CMD... : engine flags before the image, command after it
run_image() {
    local image="$1"; shift
    local f=(); [[ "${1:-}" == "-it" ]] && { f=(-it); shift; }
    "$ENGINE" run --rm "${f[@]}" -v "${ROOT}:/work${VOL}" -w /work "$image" "$@"
}

run() {
    run_image "$IMAGE" "$@"
}

doc_product_paths() {
    case "${1:-trm}" in
        trm)        echo "doc/trm antora-trm-playbook.yml ocah-doc-trm-setup ocah-doc-trm-pdf" ;;
        integrator) echo "doc/integrator antora-integrator-playbook.yml ocah-doc-integrator-setup ocah-doc-integrator-pdf" ;;
        *) echo "error: unknown doc product '$1' (expected trm or integrator)" >&2; exit 1 ;;
    esac
}

doc_setup() {
    local product="${1:-trm}" basedir playbook setup_target pdf_target
    read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
    run_image "$DOC_PDF_IMAGE" env OCAH_DOC_REGEN_REGS=0 make "$setup_target"
}

doc_html() {
    local product="${1:-trm}" basedir playbook setup_target pdf_target
    read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
    doc_setup "$product"
    "$ENGINE" run --rm -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
        --attribute "basedir=${basedir}" "$playbook"
}

doc_pdf() {
    local product="${1:-trm}" basedir playbook setup_target pdf_target
    read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
    run_image "$DOC_PDF_IMAGE" env OCAH_DOC_REGEN_REGS=0 make "$pdf_target"
}

case "${1:-}" in
    build)  "$ENGINE" build -t "$IMAGE" "${ROOT}/tools/docker" ;;
    verify) run riscv64-unknown-elf-gcc --version; echo ---; run riscv64-unknown-elf-gcc -print-multi-lib ;;
    run)    shift; [[ $# -gt 0 ]] || { echo "error: run requires a command" >&2; exit 1; }; run "$@" ;;
    shell)  run -it bash ;;
    doc-html) shift; doc_html "${1:-trm}" ;;
    doc-pdf)  shift; doc_pdf "${1:-trm}" ;;
    ""|-h|--help|help) sed -n '2,10p' "$0" ;;
    *)      echo "error: unknown command '$1'" >&2; exit 1 ;;
esac

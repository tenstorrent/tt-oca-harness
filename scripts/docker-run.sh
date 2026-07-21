#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
# Usage: docker-run.sh <build|verify|run CMD...|run-here CMD...|shell|doc-html [trm|integrator]|doc-pdf [trm|integrator]|eda-run CMD...|eda-shell>
#   build     build firmware image        verify    gcc version + multilibs
#   run CMD   run in firmware image       shell     interactive firmware shell
#   run-here  like run, but mount the repo at its host path (for CMDs that use
#             absolute host paths, e.g. the TTEM `make -C $OCH_ROOT ...` cgen flow)
#   doc-html  build HTML with Antora image doc-pdf  build PDF with Asciidoctor image
#   eda-run   run in the open EDA image    eda-shell interactive EDA shell
# Env: OCAH_DOCKER_IMAGE       firmware image tag (default: ocah-toolchain)
#      OCAH_DOC_HTML_IMAGE     prebuilt Antora image
#      OCAH_DOC_PDF_IMAGE      prebuilt Asciidoctor image
#      OCAH_EDA_IMAGE          prebuilt yosys/slang/verible image (see flows/)
#      OCAH_DOCKER_UIDGID      container --user (default: caller's uid:gid; set
#                               empty to run as each image's own default user)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${OCAH_DOCKER_IMAGE:-ocah-toolchain}"
DOC_HTML_IMAGE="${OCAH_DOC_HTML_IMAGE:-docker.io/antora/antora:3.1.10}"
DOC_PDF_IMAGE="${OCAH_DOC_PDF_IMAGE:-docker.io/asciidoctor/docker-asciidoctor:1.106.0@sha256:6266e05784c2d8ece9d9fe5e593b12c3beebebbc467135fd6f4a56269c93cea3}"
EDA_IMAGE="${OCAH_EDA_IMAGE:-hpretl/iic-osic-tools:2025.12}"

if command -v podman >/dev/null 2>&1; then ENGINE=podman VOL=":Z"
elif command -v docker >/dev/null 2>&1; then ENGINE=docker VOL=""
else echo "error: podman or docker is required" >&2; exit 1; fi

# Run as the caller's uid:gid so bind-mounted output stays owned by the
# caller. Override with OCAH_DOCKER_UIDGID (empty runs as the image default).
UIDGID="${OCAH_DOCKER_UIDGID-$(id -u):$(id -g)}"
USER_FLAGS=(); [[ -n "$UIDGID" ]] && USER_FLAGS=(--user "$UIDGID" -e HOME=/tmp)

# run_image IMAGE [-it] CMD... : engine flags before the image, command after it
run_image() {
    local image="$1"; shift
    local f=(); [[ "${1:-}" == "-it" ]] && { f=(-it); shift; }
    "$ENGINE" run --rm "${f[@]}" "${USER_FLAGS[@]}" -v "${ROOT}:/work${VOL}" -w /work "$image" "$@"
}

run() {
    run_image "$IMAGE" "$@"
}

# Like run, but mount the repo at its own host-absolute path (see
# run_image_1to1) so commands that reference absolute host paths - such as the
# TTEM cgen flow's `make -C $OCH_ROOT -f ocah.mk ...` - resolve inside the
# container. Uses the firmware image.
run_here() {
    run_image_1to1 "$IMAGE" "$@"
}

# run_image_1to1 IMAGE [-it] CMD... : like run_image, but mounts the repo at
# its own host-absolute path instead of /work. Used by the EDA flows, whose
# bender-generated `.f` filelists already contain host-absolute paths.
run_image_1to1() {
    local image="$1"; shift
    local f=(); [[ "${1:-}" == "-it" ]] && { f=(-it); shift; }
    "$ENGINE" run --rm "${f[@]}" "${USER_FLAGS[@]}" -v "${ROOT}:${ROOT}${VOL}" -w "$PWD" "$image" "$@"
}

# hpretl/iic-osic-tools's entrypoint launches a UI (X11/VNC) by default;
# `--skip` (must come first) tells it to exec the given command instead.
eda_run() {
    local f=(); [[ "${1:-}" == "-it" ]] && { f=(-it); shift; }
    run_image_1to1 "$EDA_IMAGE" "${f[@]}" --skip "$@"
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
    "$ENGINE" run --rm "${USER_FLAGS[@]}" -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
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
    run-here) shift; [[ $# -gt 0 ]] || { echo "error: run-here requires a command" >&2; exit 1; }; run_here "$@" ;;
    shell)  run -it bash ;;
    doc-html) shift; doc_html "${1:-trm}" ;;
    doc-pdf)  shift; doc_pdf "${1:-trm}" ;;
    eda-run)  shift; [[ $# -gt 0 ]] || { echo "error: eda-run requires a command" >&2; exit 1; }; eda_run "$@" ;;
    eda-shell) eda_run -it bash ;;
    ""|-h|--help|help) sed -n '7,19p' "$0" ;;
    *)      echo "error: unknown command '$1'" >&2; exit 1 ;;
esac

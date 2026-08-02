#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
# Usage: docker-run.sh <build|verify|run CMD...|shell|doc-html [trm|integrator|programmer|appnotes|all]|doc-pdf [trm|integrator|programmer|appnotes]|doc-stage|eda-run CMD...|eda-shell>
#   'doc-html all' builds the real combined multi-book site (antora-playbook.yml) -- this is what gets deployed
#   'doc-stage' adds PDFs + .nojekyll on top of an already-built combined site -- pure file copying, no Docker/Node needed. Run after doc-html all + doc-pdf.
#   build     build firmware image        verify    gcc version + multilibs
#   run CMD   run in firmware image       shell     interactive firmware shell
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
        trm)         echo "doc/trm antora-trm-playbook.yml ocah-doc-trm-setup ocah-doc-trm-pdf" ;;
        integrator)  echo "doc/integrator antora-integrator-playbook.yml ocah-doc-integrator-setup ocah-doc-integrator-pdf" ;;
        programmer)  echo "doc/programmer antora-programmer-playbook.yml ocah-doc-programmer-setup ocah-doc-programmer-pdf" ;;
        appnotes)    echo "doc/appnotes antora-appnotes-playbook.yml ocah-doc-appnotes-setup ocah-doc-appnotes-pdf" ;;
        *) echo "error: unknown doc product '$1' (expected trm, integrator, programmer, or appnotes)" >&2; exit 1 ;;
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

doc_html_all() {
    # This is the combined-architecture build.
    doc_setup trm
    doc_setup integrator
    doc_setup programmer
    doc_setup appnotes
    # The prebuilt antora/antora:3.1.10 image has Antora pre-installed but
    # NOT @antora/lunr-extension (that's only added to the npx-based
    # OCAH_ANTORA path in doc/doc.mk, which real CI uses via `make
    # ocah-doc-combined-html` -- this direct-image path is separate and
    # needs its own install). `npm install` here writes into the
    # bind-mounted repo root, so it only needs to happen once per checkout
    # (harmless to repeat). Make sure node_modules/ is gitignored.
    "$ENGINE" run --rm -e SITE_SEARCH_PROVIDER=lunr -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
        sh -c 'npm install --no-save --no-package-lock @antora/lunr-extension@1.0.0-alpha.13 && antora antora-playbook.yml'
}

doc_pdf() {
    local product="${1:-trm}" basedir playbook setup_target pdf_target
    read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
    run_image "$DOC_PDF_IMAGE" env OCAH_DOC_REGEN_REGS=0 make "$pdf_target"
}

# doc_stage: add PDFs + .nojekyll on top of the already-built combined
# Antora output. No Docker/Make/Node involved --
# this is just file copying, so it doesn't need a container at all, and
# avoids re-triggering the Node-based HTML build a second time.
# Run this AFTER `doc-html all` and `doc-pdf trm`/`doc-pdf integrator`.
doc_stage() {
    local ghpages_dir="${OCAH_GHPAGES_DIR:-doc/_build/html_antora}"
    local trm_dist="${OCAH_TRM_DIST:-doc/trm/dist}" trm_pdf="${OCAH_TRM_PDF:-ocah-trm.pdf}"
    local integrator_dist="${OCAH_INTEGRATOR_DIST:-doc/integrator/dist}" integrator_pdf="${OCAH_INTEGRATOR_PDF:-ocah-integrator-guide.pdf}"
    local programmer_dist="${OCAH_PROGRAMMER_DIST:-doc/programmer/dist}" programmer_pdf="${OCAH_PROGRAMMER_PDF:-ocah-programmer-guide.pdf}"
    local appnotes_dist="${OCAH_APPNOTES_DIST:-doc/appnotes/dist}" appnotes_pdf="${OCAH_APPNOTES_PDF:-ocah-appnotes.pdf}"

    if [[ ! -d "$ROOT/$ghpages_dir" ]]; then
        echo "error: missing combined HTML output at $ghpages_dir" >&2
        echo "run: ./scripts/docker-run.sh doc-html all" >&2
        exit 1
    fi

    mkdir -p "$ROOT/$ghpages_dir/downloads"
    touch "$ROOT/$ghpages_dir/.nojekyll"

    if [[ -f "$ROOT/$trm_dist/$trm_pdf" ]]; then
        cp "$ROOT/$trm_dist/$trm_pdf" "$ROOT/$ghpages_dir/downloads/"
    else
        echo "warning: TRM PDF not found at $trm_dist/$trm_pdf, skipping (run: ./scripts/docker-run.sh doc-pdf trm)"
    fi

    if [[ -f "$ROOT/$integrator_dist/$integrator_pdf" ]]; then
        cp "$ROOT/$integrator_dist/$integrator_pdf" "$ROOT/$ghpages_dir/downloads/"
    else
        echo "warning: Integrator Guide PDF not found at $integrator_dist/$integrator_pdf, skipping (run: ./scripts/docker-run.sh doc-pdf integrator)"
    fi

    if [[ -f "$ROOT/$programmer_dist/$programmer_pdf" ]]; then
        cp "$ROOT/$programmer_dist/$programmer_pdf" "$ROOT/$ghpages_dir/downloads/"
    else
        echo "warning: Programmer's Guide PDF not found at $programmer_dist/$programmer_pdf, skipping (run: ./scripts/docker-run.sh doc-pdf programmer)"
    fi

    if [[ -f "$ROOT/$appnotes_dist/$appnotes_pdf" ]]; then
        cp "$ROOT/$appnotes_dist/$appnotes_pdf" "$ROOT/$ghpages_dir/downloads/"
    else
        echo "warning: Application Notes PDF not found at $appnotes_dist/$appnotes_pdf, skipping (run: ./scripts/docker-run.sh doc-pdf appnotes)"
    fi

    echo "Staged GitHub Pages tree at $ghpages_dir"
    echo "Preview locally with: cd $ghpages_dir && python3 -m http.server 8000"
}

case "${1:-}" in
    build)  "$ENGINE" build -t "$IMAGE" "${ROOT}/tools/docker" ;;
    verify) run riscv64-unknown-elf-gcc --version; echo ---; run riscv64-unknown-elf-gcc -print-multi-lib ;;
    run)    shift; [[ $# -gt 0 ]] || { echo "error: run requires a command" >&2; exit 1; }; run "$@" ;;
    shell)  run -it bash ;;
	doc-html) shift; [[ "${1:-trm}" == "all" ]] && doc_html_all || doc_html "${1:-trm}" ;;
    doc-pdf)  shift; doc_pdf "${1:-trm}" ;;
    doc-stage) doc_stage ;;
    eda-run)  shift; [[ $# -gt 0 ]] || { echo "error: eda-run requires a command" >&2; exit 1; }; eda_run "$@" ;;
    eda-shell) eda_run -it bash ;;
    ""|-h|--help|help) sed -n '2,19p' "$0" ;;
    *)      echo "error: unknown command '$1'" >&2; exit 1 ;;
esac
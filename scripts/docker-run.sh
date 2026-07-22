#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
# Usage: docker-run.sh <build|ensure|verify|run CMD...|run-here CMD...|shell|doc-html [trm|integrator]|doc-pdf [trm|integrator]|eda-run CMD...|eda-shell>
#   build     (re)build firmware image + publish to shared tarball cache
#   ensure    make firmware image available (local -> cache -> build); auto-run
#             by run/run-here/shell/verify, so bare `run` works on a fresh host
#   verify    gcc version + multilibs      shell     interactive firmware shell
#   run CMD   run in firmware image
#   run-here  like run, but mount the repo at its host path (for CMDs that use
#             absolute host paths, e.g. the TTEM `make -C $OCH_ROOT ...` cgen flow)
#   doc-html  build HTML with Antora image doc-pdf  build PDF with Asciidoctor image
#   eda-run   run in the open EDA image    eda-shell interactive EDA shell
# Env: OCAH_DOCKER_IMAGE       firmware image tag (default: ocah-toolchain)
#      OCAH_DOCKER_CACHE_DIR   shared tarball cache dir for the firmware image
#                               (default: /proj_soc_scratch_ps/socinfra/ocah-docker-cache)
#      OCAH_DOC_HTML_IMAGE     prebuilt Antora image
#      OCAH_DOC_PDF_IMAGE      prebuilt Asciidoctor image
#      OCAH_EDA_IMAGE          prebuilt yosys/slang/verible image (see flows/)
#      OCAH_DOCKER_UIDGID      container --user (default: empty for rootless
#                               podman, caller's uid:gid for docker; set empty to
#                               run as each image's own default user)
#      OCAH_PODMAN_DIR         base for podman runtime+storage when the default
#                               /run/user/<uid> is unwritable (default:
#                               /tmp/ocah-podman-<uid>); used by CI accounts
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${OCAH_DOCKER_IMAGE:-ocah-toolchain}"
DOC_HTML_IMAGE="${OCAH_DOC_HTML_IMAGE:-docker.io/antora/antora:3.1.10}"
DOC_PDF_IMAGE="${OCAH_DOC_PDF_IMAGE:-docker.io/asciidoctor/docker-asciidoctor:1.106.0@sha256:6266e05784c2d8ece9d9fe5e593b12c3beebebbc467135fd6f4a56269c93cea3}"
EDA_IMAGE="${OCAH_EDA_IMAGE:-hpretl/iic-osic-tools:2025.12}"

# Firmware image provisioning. The ocah-toolchain image is built locally and
# published to no registry, so bare `run` on a fresh host would try (and fail)
# to pull it. To avoid every CI runner rebuilding it - and to avoid depending on
# registry/internet access at job time - a built image is cached as a tarball on
# shared storage, keyed by the Dockerfile hash. Hosts reuse a matching local
# image, else load the tarball, else build once and publish it for the rest.
DOCKER_CTX="${ROOT}/tools/docker"
DOCKER_CACHE_DIR="${OCAH_DOCKER_CACHE_DIR:-/proj_soc_scratch_ps/socinfra/ocah-docker-cache}"

if command -v podman >/dev/null 2>&1; then ENGINE=podman VOL=":Z"
elif command -v docker >/dev/null 2>&1; then ENGINE=docker VOL=""
else echo "error: podman or docker is required" >&2; exit 1; fi

# Rootless podman keeps its runtime state under $XDG_RUNTIME_DIR (default
# /run/user/<uid>), which is created by pam_systemd on interactive login.
# Non-login accounts - notably the CI service account under the shell runner -
# have no such dir and can't create it ("mkdir /run/user/<uid>: permission
# denied"), so podman won't even start. When that runtime dir is missing or
# unwritable, redirect podman's runtime (XDG_RUNTIME_DIR) and image storage
# (XDG_DATA_HOME) to a node-local, per-uid dir under /tmp: world-writable, fast
# local disk, and - keyed by uid - stable so a loaded image persists across jobs
# on the same runner. Hosts with a proper session (writable /run/user/<uid>) are
# left untouched. Override the base dir with OCAH_PODMAN_DIR.
if [[ "$ENGINE" == podman ]]; then
    _rt="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [[ ! -w "$_rt" ]]; then
        _base="${OCAH_PODMAN_DIR:-${TMPDIR:-/tmp}/ocah-podman-$(id -u)}"
        export XDG_RUNTIME_DIR="${_base}/run" XDG_DATA_HOME="${_base}/share"
        mkdir -p "$XDG_RUNTIME_DIR" "$XDG_DATA_HOME"
        chmod 700 "$XDG_RUNTIME_DIR"
        echo "docker-run: default podman runtime dir '$_rt' unwritable; using $_base" >&2
    fi
fi

# Container --user. Rootless podman already maps the container's root to the
# caller's uid (so bind-mounted output comes out caller-owned without --user),
# and passing --user on these RHEL8 hosts trips a runc "setgroups: invalid
# argument" failure - so podman defaults to no --user. Rootful docker needs
# --user to avoid root-owned output. Override either default with
# OCAH_DOCKER_UIDGID (empty = the image's own default user).
if [[ "$ENGINE" == podman ]]; then UIDGID="${OCAH_DOCKER_UIDGID-}"
else UIDGID="${OCAH_DOCKER_UIDGID-$(id -u):$(id -g)}"; fi
USER_FLAGS=(); [[ -n "$UIDGID" ]] && USER_FLAGS=(--user "$UIDGID" -e HOME=/tmp)

# Short hash of the Dockerfile; a change forces a rebuild / new cache entry.
image_hash() { sha256sum "${DOCKER_CTX}/Dockerfile" | cut -c1-16; }
image_cache_tar() { echo "${DOCKER_CACHE_DIR}/${IMAGE##*/}-$(image_hash).tar"; }

# Build the firmware image (labeled with the Dockerfile hash) and publish it to
# the shared tarball cache when that storage is writable. A publish failure is
# a warning, not a build failure.
build_image() {
    local hash; hash="$(image_hash)"
    "$ENGINE" build --label "ocah.dockerfile.sha=${hash}" -t "$IMAGE" "$DOCKER_CTX"
    local tar; tar="$(image_cache_tar)"
    if mkdir -p "$DOCKER_CACHE_DIR" 2>/dev/null; then
        local tmp="${tar}.$$.tmp"
        if "$ENGINE" save -o "$tmp" "$IMAGE" 2>/dev/null && mv -f "$tmp" "$tar" 2>/dev/null; then
            echo "docker-run: published image cache $tar" >&2
        else
            rm -f "$tmp" 2>/dev/null || true
            echo "docker-run: warning: could not publish image cache to $tar" >&2
        fi
    else
        echo "docker-run: warning: cache dir $DOCKER_CACHE_DIR not writable; not publishing" >&2
    fi
}

# Ensure $IMAGE is available locally: reuse a matching local image (verified by
# the Dockerfile-hash label), else load the shared tarball cache, else build and
# publish. Use `build` to force a rebuild regardless of what is already present.
ensure_image() {
    local hash tar
    hash="$(image_hash)"
    if [ "$("$ENGINE" image inspect --format '{{ index .Config.Labels "ocah.dockerfile.sha" }}' "$IMAGE" 2>/dev/null)" = "$hash" ]; then
        return 0
    fi
    tar="$(image_cache_tar)"
    if [ -r "$tar" ]; then
        echo "docker-run: loading $IMAGE from cache $tar" >&2
        "$ENGINE" load -i "$tar"
        return 0
    fi
    echo "docker-run: $IMAGE (hash $hash) absent locally and in cache; building" >&2
    build_image
}

# run_image IMAGE [-it] CMD... : engine flags before the image, command after it
run_image() {
    local image="$1"; shift
    local f=(); [[ "${1:-}" == "-it" ]] && { f=(-it); shift; }
    "$ENGINE" run --rm "${f[@]}" "${USER_FLAGS[@]}" -v "${ROOT}:/work${VOL}" -w /work "$image" "$@"
}

run() {
    ensure_image
    run_image "$IMAGE" "$@"
}

# Like run, but mount the repo at its own host-absolute path (see
# run_image_1to1) so commands that reference absolute host paths - such as the
# TTEM cgen flow's `make -C $OCH_ROOT -f ocah.mk ...` - resolve inside the
# container. Uses the firmware image.
run_here() {
    ensure_image
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
    build)  build_image ;;
    ensure) ensure_image ;;
    verify) run riscv64-unknown-elf-gcc --version; echo ---; run riscv64-unknown-elf-gcc -print-multi-lib ;;
    run)    shift; [[ $# -gt 0 ]] || { echo "error: run requires a command" >&2; exit 1; }; run "$@" ;;
    run-here) shift; [[ $# -gt 0 ]] || { echo "error: run-here requires a command" >&2; exit 1; }; run_here "$@" ;;
    shell)  run -it bash ;;
    doc-html) shift; doc_html "${1:-trm}" ;;
    doc-pdf)  shift; doc_pdf "${1:-trm}" ;;
    eda-run)  shift; [[ $# -gt 0 ]] || { echo "error: eda-run requires a command" >&2; exit 1; }; eda_run "$@" ;;
    eda-shell) eda_run -it bash ;;
    ""|-h|--help|help) sed -n '7,28p' "$0" ;;
    *)      echo "error: unknown command '$1'" >&2; exit 1 ;;
esac

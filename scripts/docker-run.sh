#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
# Usage: docker-run.sh <build|ensure|verify|run CMD...|run-here CMD...|shell|doc-html [trm|integrator|programmer|appnotes|all]|doc-pdf [trm|integrator|programmer|appnotes]|doc-stage|eda-run CMD...|eda-shell>
#   'doc-html all' builds the real combined multi-book site (antora-playbook.yml) -- this is what gets deployed
#   'doc-stage' adds PDFs + .nojekyll on top of an already-built combined site -- pure file copying, no Docker/Node needed. Run after doc-html all + doc-pdf.
#   build     (re)build firmware image + publish to shared tarball cache
#   ensure    make firmware image available (local -> cache -> build); auto-run
#             by run/run-here/shell/verify, so bare `run` works on a fresh host
#   verify    gcc version + multilibs      shell     interactive firmware shell
#   run CMD   run in firmware image
#   run-here CMD  firmware image, 1:1 host paths and caller's cwd (nonfree DV cgen)
#   doc-html  build HTML with Antora image doc-pdf  build PDF with Asciidoctor image
#   eda-run   run in the open EDA image    eda-shell interactive EDA shell
# Env: OCAH_DOCKER_IMAGE       firmware image tag (default: ocah-toolchain)
#      OCAH_DOCKER_CACHE_DIR   optional shared tarball cache dir for the
#                               firmware image; unset disables the cache
#                               (site CI sets this, e.g. in its env setup)
#      OCAH_DOC_HTML_IMAGE     prebuilt Antora image
#      OCAH_DOC_PDF_IMAGE      prebuilt Asciidoctor image
#      OCAH_EDA_IMAGE          prebuilt yosys/slang/verible image (see flows/)
#      OCAH_DOCKER_UIDGID      container --user (default: empty for rootless
#                               podman, caller's uid:gid for docker; set empty to
#                               run as each image's own default user)
#      OCAH_PODMAN_DIR         base for podman runtime+storage when the default
#                               /run/user/<uid> is unwritable (default:
#                               /tmp/ocah-podman-<uid>); used by CI accounts
#      OCAH_SKIP_GID_FIXUP     set to 1 to skip re-running under the passwd
#                               primary group for rootless podman (see below)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${OCAH_DOCKER_IMAGE:-ocah-toolchain}"
DOC_HTML_IMAGE="${OCAH_DOC_HTML_IMAGE:-docker.io/antora/antora:3.1.10}"
DOC_PDF_IMAGE="${OCAH_DOC_PDF_IMAGE:-docker.io/asciidoctor/docker-asciidoctor:1.106.0@sha256:6266e05784c2d8ece9d9fe5e593b12c3beebebbc467135fd6f4a56269c93cea3}"
EDA_IMAGE="${OCAH_EDA_IMAGE:-hpretl/iic-osic-tools:2025.12}"

# Firmware image provisioning. The ocah-toolchain image is built locally and
# published to no registry, so bare `run` on a fresh host would try (and fail)
# to pull it. To avoid every CI runner rebuilding it - and to avoid depending on
# registry/internet access at job time - a built image can be cached as a
# tarball on shared storage, keyed by the Dockerfile hash: hosts reuse a
# matching local image, else load the tarball, else build once and publish it
# for the rest. The cache is only active when OCAH_DOCKER_CACHE_DIR is set
# (site-specific; e.g. exported by the adopter's CI environment setup).
DOCKER_CTX="${ROOT}/tools/docker"
DOCKER_CACHE_DIR="${OCAH_DOCKER_CACHE_DIR:-}"

if command -v podman >/dev/null 2>&1; then ENGINE=podman VOL=":Z"
elif command -v docker >/dev/null 2>&1; then ENGINE=docker VOL=""
else echo "error: podman or docker is required" >&2; exit 1; fi

# Rootless podman's newuidmap/newgidmap helpers refuse to set up the user
# namespace unless the process's primary GID matches the account's registered
# primary GID in /etc/passwd ("newuidmap: Target process ... is owned by a
# different user"). Some CI/LSF nodes launch the job under a different primary
# group (e.g. inherited from an SGID scratch dir), which trips this check. If so,
# re-exec this script under the passwd primary group so the GIDs line up.
#
# Switching to the account's passwd *login* group is permitted by newgrp/sg
# without a password even when that group is not in the supplementary set
# (id -G) - which is exactly the case on these nodes (a user-private group).
# So don't gate on id -G membership; instead probe whether `sg` is allowed,
# reading stdin from /dev/null so an unexpected password prompt fails fast
# instead of hanging CI, and only re-exec on success. A one-shot guard var
# prevents looping. Opt out with OCAH_SKIP_GID_FIXUP=1.
if [[ "$ENGINE" == podman && "${OCAH_SKIP_GID_FIXUP:-0}" != 1 && -z "${_OCAH_GID_FIXED:-}" ]]; then
    _pw_gid="$(getent passwd "$(id -u)" | cut -d: -f4)"
    if [[ -n "$_pw_gid" && "$_pw_gid" != "$(id -g)" ]]; then
        _pw_grp="$(getent group "$_pw_gid" | cut -d: -f1)"; _pw_grp="${_pw_grp:-$_pw_gid}"
        if sg "$_pw_grp" -c 'true' </dev/null >/dev/null 2>&1; then
            export _OCAH_GID_FIXED=1
            echo "docker-run: primary GID $(id -g) != passwd GID $_pw_gid; re-running under group '$_pw_grp' for rootless podman" >&2
            exec sg "$_pw_grp" -c "$(printf '%q ' "$0" "$@")" </dev/null
        else
            echo "docker-run: warning: primary GID $(id -g) != passwd GID $_pw_gid and 'sg $_pw_grp' is not permitted; rootless podman may fail" >&2
        fi
    fi
fi

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
# the shared tarball cache when one is configured and writable. A publish
# failure is a warning, not a build failure.
build_image() {
    local hash; hash="$(image_hash)"
    "$ENGINE" build --label "ocah.dockerfile.sha=${hash}" -t "$IMAGE" "$DOCKER_CTX"
    [[ -n "$DOCKER_CACHE_DIR" ]] || return 0
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
    if [[ -n "$DOCKER_CACHE_DIR" ]]; then
        tar="$(image_cache_tar)"
        if [ -r "$tar" ]; then
            echo "docker-run: loading $IMAGE from cache $tar" >&2
            "$ENGINE" load -i "$tar"
            return 0
        fi
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

# Firmware image with 1:1 paths and the caller's cwd, for callers that pass
# host-absolute paths. The nonfree SMC DV cgen stage needs this: it drives the
# picolibc firmware builds with absolute `make -C` paths spanning both this repo
# and nonfree/, which would not resolve under `run`'s /work remap.
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

    echo "Staged GitHub Pages tree at $ghpages_dir"
    echo "Preview locally with: cd $ghpages_dir && python3 -m http.server 8000"
}

case "${1:-}" in
    build)  build_image ;;
    ensure) ensure_image ;;
    verify) run riscv64-unknown-elf-gcc --version; echo ---; run riscv64-unknown-elf-gcc -print-multi-lib ;;
    run)    shift; [[ $# -gt 0 ]] || { echo "error: run requires a command" >&2; exit 1; }; run "$@" ;;
    run-here) shift; [[ $# -gt 0 ]] || { echo "error: run-here requires a command" >&2; exit 1; }; run_here "$@" ;;
    shell)  run -it bash ;;
    doc-html) shift; [[ "${1:-trm}" == "all" ]] && doc_html_all || doc_html "${1:-trm}" ;;
    doc-pdf)  shift; doc_pdf "${1:-trm}" ;;
    doc-stage) doc_stage ;;
    eda-run)  shift; [[ $# -gt 0 ]] || { echo "error: eda-run requires a command" >&2; exit 1; }; eda_run "$@" ;;
    eda-shell) eda_run -it bash ;;
    ""|-h|--help|help) sed -n '7,31p' "$0" ;;
    *)      echo "error: unknown command '$1'" >&2; exit 1 ;;
esac

#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
#   Usage: docker-run.sh <build|ensure|verify|run CMD...|run-here CMD...|shell|build-nix|nixos-shell|doc-html [trm|integrator|programmer|appnotes|home|contributing|all]|doc-pdf [trm|integrator|programmer|appnotes]|doc-stage|eda-run CMD...|eda-shell>#   'doc-html all' builds the real combined multi-book site (antora-playbook.yml) -- this is what gets deployed
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
#      OCAH_USE_NIX_IMAGE      Use a nix-build image containing all tooling required,
#                               rather than the above images
#      OCAH_NIX_IMAGE_WITH_UV  Bundle uv-installed dependencies into nix-built image
#                               (true/false, default: false)
#      OCAH_DOCKER_UIDGID      container --user (default: empty for rootless
#                               podman, caller's uid:gid for docker; set empty to
#                               run as each image's own default user)
#      OCAH_PODMAN_DIR         base for podman runtime+storage when the default
#                               /run/user/<uid> is unwritable (default:
#                               /tmp/ocah-podman-<uid>); used by CI accounts
#      OCAH_SKIP_GID_FIXUP     set to 1 to skip re-running under the passwd
#                               primary group for rootless podman (see below)
#      OCAH_TOOLCHAIN_ROOTFS   extracted firmware-image rootfs; when set (and
#                               bwrap is present) `run`/`run-here` use
#                               bubblewrap instead of podman/docker (see below)
#      OCAH_BWRAP_EXTRA_BINDS  extra host paths to bind into the bwrap sandbox
#                               (space-separated; each bound at its own path)
set -euo pipefail

# -P: the physical path. A checkout reached through a symlinked parent would
# otherwise be bound at a path that resolves under one of the read-only rootfs
# mounts, where bwrap cannot create the mount point.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

NIXOS_IMAGE="${OCAH_NIX_IMAGE:-docker.io/nixos/nix:latest}"

NIX_IMAGE_NAME=$([[ "${OCAH_NIX_IMAGE_WITH_UV:-false}" == true ]] && echo "ocah-uv-container" || echo "ocah-container")
USE_NIX_IMAGE="${OCAH_USE_NIX_IMAGE:-false}" # Set to true to make default
NIX_IMAGE_WITH_UV="${OCAH_NIX_IMAGE_WITH_UV:-false}"

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

# Will this invocation actually need a container engine? The toolchain
# subcommands can be served by the bubblewrap backend (see below), in which case
# no engine - and none of the rootless-podman preparation underneath - is needed.
# The doc/EDA subcommands use pulled images and always need an engine.
NEEDS_ENGINE=1
case "${1:-}" in
run | run-here | verify | shell)
  if [[ -n "${OCAH_TOOLCHAIN_ROOTFS:-}" ]] &&
    [[ -x "${OCAH_TOOLCHAIN_ROOTFS}/usr/bin/riscv64-unknown-elf-gcc" ]] &&
    command -v bwrap >/dev/null 2>&1; then
    NEEDS_ENGINE=0
  fi
  ;;
esac

if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
  VOL=":Z"
  PODMAN_STORAGE_FLAGS="--storage-opt=ignore_chown_errors=true \
        --storage-opt=mount_program=$(which fuse-overlayfs)"
  PODMAN_RUN_FLAGS="--userns=keep-id"
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
  VOL=""
  PODMAN_STORAGE_FLAGS=""
  PODMAN_RUN_FLAGS=""
elif [[ "$NEEDS_ENGINE" == 0 ]]; then
  ENGINE=none VOL=""
else
  echo "error: podman or docker is required" >&2
  exit 1
fi

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
if [[ "$ENGINE" == podman && "$NEEDS_ENGINE" == 1 && "${OCAH_SKIP_GID_FIXUP:-0}" != 1 && -z "${_OCAH_GID_FIXED:-}" ]]; then
  _pw_gid="$(getent passwd "$(id -u)" | cut -d: -f4)"
  if [[ -n "$_pw_gid" && "$_pw_gid" != "$(id -g)" ]]; then
    _pw_grp="$(getent group "$_pw_gid" | cut -d: -f1)"
    _pw_grp="${_pw_grp:-$_pw_gid}"
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
if [[ "$ENGINE" == podman && "$NEEDS_ENGINE" == 1 ]]; then
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
if [[ "$ENGINE" == podman ]]; then
  UIDGID="${OCAH_DOCKER_UIDGID-}"
else UIDGID="${OCAH_DOCKER_UIDGID-$(id -u):$(id -g)}"; fi
USER_FLAGS=()
[[ -n "$UIDGID" ]] && USER_FLAGS=(--user "$UIDGID" -e HOME=/tmp)

# Short hash of the Dockerfile; a change forces a rebuild / new cache entry.
image_hash() { sha256sum "${DOCKER_CTX}/Dockerfile" | cut -c1-16; }
image_cache_tar() { echo "${DOCKER_CACHE_DIR}/${IMAGE##*/}-$(image_hash).tar"; }

# Run a command in an environment with a nix binary. This will run locally if it
# detects a nix binary, to be able to make use of cached files in the store. On
# hosts without nix installed, it will use NIXOS_IMAGE, which defaults to
# docker.io/nixos/nix
nixos_run() {
    # Nix Flakes and Nix-Command are required for this - enable them
    local NIX_CONFIG="experimental-features = nix-command flakes"
    if command -v nix >/dev/null 2>&1; then
        NIX_CONFIG="$NIX_CONFIG" bash -c "$*"
    else
        # The repo in the container is owned by root, so nix/git will by default give untrusted errors when interacting with it.
        local GIT_ALLOW_CMD="git config --global --add safe.directory \$(pwd) &&
            git config --global --add safe.directory \$(pwd)/hw/sys/sep/bootrom/prod/tools/tt-boot-manifest &&"
        run_image $NIXOS_IMAGE -it sh -c "
            export NIX_CONFIG=\"$NIX_CONFIG\"
            export PS1=\"\[\e[1;36m\]NixOS >\[\e[0m\] \"
            $GIT_ALLOW_CMD
            $@
        "
    fi
}

# Open a shell in the Nix Container - even on a nix-enabled host
nixos_shell() {
    local NIX_CONFIG="experimental-features = nix-command flakes"
    local GIT_ALLOW_CMD="git config --global --add safe.directory \$(pwd) &&
        git config --global --add safe.directory \$(pwd)/hw/sys/sep/bootrom/prod/tools/tt-boot-manifest &&"
    run_image $NIXOS_IMAGE -it sh -c "
        export NIX_CONFIG=\"$NIX_CONFIG\"
        export PS1=\"\[\e[1;36m\]NixOS >\[\e[0m\] \"
        $GIT_ALLOW_CMD
        bash
    "
}

# Build the firmware image (labeled with the Dockerfile hash) and publish it to
# the shared tarball cache when one is configured and writable. A publish
# failure is a warning, not a build failure.
build_image() {
    if [[ "${USE_NIX_IMAGE:-false}" == true ]]; then
        local hash
        hash="$(image_hash)"
        "$ENGINE" ${PODMAN_STORAGE_FLAGS} build --label "ocah.dockerfile.sha=${hash}" \
            -t "$IMAGE" "$DOCKER_CTX"
        [[ -n "$DOCKER_CACHE_DIR" ]] || return 0
        local tar
        tar="$(image_cache_tar)"
        if mkdir -p "$DOCKER_CACHE_DIR" 2>/dev/null; then
            local tmp="${tar}.$$.tmp"
            if "$ENGINE" ${PODMAN_STORAGE_FLAGS} save -o "$tmp" "$IMAGE" 2>/dev/null &&
            mv -f "$tmp" "$tar" 2>/dev/null; then
            echo "docker-run: published image cache $tar" >&2
            else
            rm -f "$tmp" 2>/dev/null || true
            echo "docker-run: warning: could not publish image cache to $tar" >&2
            fi
        else
            echo "docker-run: warning: cache dir $DOCKER_CACHE_DIR not writable; not publishing" >&2
        fi
    else
        local flake_output image_location
        flake_output=$([[ "${NIX_IMAGE_WITH_UV:-false}" == true ]] && echo "with_uv_deps" || echo "without_uv_deps")
        if [[ -n "$DOCKER_CACHE_DIR" ]]; then
            image_location="$(nix_image_cache_tar)"
        else
            image_location="local/nix-container-image.tar.gz"
        fi
        nixos_run "nix build \$(pwd)#dockerContainers.x86_64-linux.$flake_output &&
            cp -f --update=all \$(readlink result) $image_location &&
            echo \"Built Container Image\" &&
            rm -f result ||
            {
                echo \"Container Image Build Failed\" >&2;
                rm -f result;
                exit 1;
            }
        "
        "$ENGINE" ${PODMAN_STORAGE_FLAGS} load -i "$image_location"
    fi
}

nix_image_hash() {
    local flake_output
    flake_output=$([[ "${NIX_IMAGE_WITH_UV:-false}" == true ]] && echo "with_uv_deps" || echo "without_uv_deps")
    nixos_run "nix eval \$(pwd)#containerHashes.$flake_output 2> /dev/null" | tr -d '"'
}
nix_image_cache_tar() {
    echo "${DOCKER_CACHE_DIR}/${NIX_IMAGE_NAME##*/}-$(nix_image_hash).tar.gz"
}

# Ensure $IMAGE is available locally: reuse a matching local image (verified by
# the Dockerfile-hash label), else load the shared tarball cache, else build and
# publish. Use `build` to force a rebuild regardless of what is already present.
ensure_image() {
    if [[ "${USE_NIX_IMAGE:-false}" == false ]]; then
        local hash tar
        hash="$(image_hash)"
        if [ "$("$ENGINE" ${PODMAN_STORAGE_FLAGS} image ${PODMAN_RUN_FLAGS} inspect \
            --format '{{ index .Config.Labels "ocah.dockerfile.sha" }}' "$IMAGE" 2>/dev/null)" = "$hash" ]; then
            return 0
        fi
        if [[ -n "$DOCKER_CACHE_DIR" ]]; then
            tar="$(image_cache_tar)"
            if [ -r "$tar" ]; then
            echo "docker-run: loading $IMAGE from cache $tar" >&2
            "$ENGINE" ${PODMAN_STORAGE_FLAGS} load -i "$tar"
            return 0
            fi
        fi
        echo "docker-run: $IMAGE (hash $hash) absent locally and in cache; building" >&2
        build_image
    else
        local flake_hash
        flake_hash=$(nix_image_hash)
        # Test for loaded image in podman
        if "$ENGINE" ${PODMAN_STORAGE_FLAGS} images | grep -qE "${NIX_IMAGE_NAME} *${flake_hash}"; then
            return 0
        fi
        # Check Cache or local image file
        if [[ -n "$DOCKER_CACHE_DIR" ]]; then
            local tar
            tar="$(nix_image_cache_tar)"
            if [ -r "$tar" ]; then
                echo "docker-run: loading $NIX_IMAGE from cache $tar" >&2
                "$ENGINE" ${PODMAN_STORAGE_FLAGS} load -i "$tar"
                return 0
            fi
        else
            local_tar="local/nix-container-image.tar.gz"
            tar_repotag=$(nixos_run "tar -xOf $local_tar manifest.json | nix run nixpkgs#jq -- -r '.[0].RepoTags[0]'")
            if [[ "$tar_repotag" == "$NIX_IMAGE" ]]; then
                echo "docker-run: loading $NIX_IMAGE from $local_tar" >&2
                "$ENGINE" ${PODMAN_STORAGE_FLAGS} load -i "$local_tar"
                return 0
            fi
        fi
        echo "docker-run: $NIX_IMAGE (hash $flake_hash) absent locally and in cache; building" >&2
        build_image
    fi
}

# run_image IMAGE [-it] CMD... : engine flags before the image, command after it
run_image() {
  local image="$1"
  shift
  local f=()
  [[ "${1:-}" == "-it" ]] && {
    f=(-it)
    shift
  }
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm "${f[@]}" \
    "${USER_FLAGS[@]}" -v "${ROOT}:/work${VOL}" -w /work "$image" "$@"
}

# --- bubblewrap backend -----------------------------------------------------
# The firmware image only supplies a toolchain (riscv64-unknown-elf-gcc,
# picolibc, make, python3-pyelftools) - it needs no daemon, no network and no
# persistent state. Rootless podman, by contrast, keeps a per-user pause process
# and user-namespace bookkeeping in XDG_RUNTIME_DIR, which on shared CI/LSF
# nodes fails in ways we do not control: `newuidmap` refuses a job-specific
# primary group, and `podman system migrate` run before a group change leaves a
# namespace the later process cannot join ("cannot re-exec process to join the
# existing user namespace").
#
# Bubblewrap avoids that whole class: it is a single stateless binary that
# creates a fresh unprivileged user namespace per invocation, with no pause
# process, no image store and no group-matching requirement. Point
# OCAH_TOOLCHAIN_ROOTFS at a rootfs extracted from the firmware image (the
# `docker save` layers untarred in order) to run the *same* toolchain binaries
# locally, in CI and on Jenkins without a container engine.
#
# Paths are 1:1 (the repo is bound at its own host path), which is what the
# nonfree DV cgen stage needs, so this backend serves `run` and `run-here`
# identically; `run` just starts in the repo root.
TOOLCHAIN_ROOTFS="${OCAH_TOOLCHAIN_ROOTFS:-}"

use_bwrap() {
  [[ -n "$TOOLCHAIN_ROOTFS" ]] || return 1
  if [[ ! -x "${TOOLCHAIN_ROOTFS}/usr/bin/riscv64-unknown-elf-gcc" ]]; then
    echo "docker-run: warning: OCAH_TOOLCHAIN_ROOTFS='$TOOLCHAIN_ROOTFS' has no" \
      "usr/bin/riscv64-unknown-elf-gcc; falling back to $ENGINE" >&2
    return 1
  fi
  if ! command -v bwrap >/dev/null 2>&1; then
    echo "docker-run: warning: OCAH_TOOLCHAIN_ROOTFS set but bwrap is not installed;" \
      "falling back to $ENGINE" >&2
    return 1
  fi
  return 0
}

# bwrap_run WORKDIR CMD... : run CMD in the extracted rootfs, with host paths 1:1.
#
# The sandbox root is a tmpfs with the image's top-level directories bound
# read-only underneath it, rather than the rootfs bound directly over /. That
# matters because binding the workspace at its host-absolute path requires bwrap
# to create the mount point: with the rootfs as root it would mkdir that path
# chain *inside the shared rootfs*, which only its owner can do (CI runners hit
# "Can't mkdir parents ...: Permission denied") and which pollutes the image with
# one directory tree per workspace path. Against a tmpfs root the mount points
# are free, so any account and any checkout path work and the rootfs stays
# read-only and pristine.
bwrap_run() {
  local workdir="$1"
  shift
  [[ "${1:-}" == "-it" ]] && shift # no TTY plumbing needed; bwrap inherits it
  local binds=(--tmpfs /)
  local entry name
  for entry in "$TOOLCHAIN_ROOTFS"/*; do
    name="${entry##*/}"
    # /dev, /proc and /run are provided fresh below; /tmp is shared from the host.
    case "$name" in dev | proc | sys | run | tmp) continue ;; esac
    [[ -d "$entry" ]] && binds+=(--ro-bind "$entry" "/$name")
  done
  binds+=(--dev /dev --proc /proc --tmpfs /run)
  # /tmp is shared (not --tmpfs) so build temporaries and any caller-provided
  # scratch paths stay visible to the host, matching the container's -v mounts.
  binds+=(--bind /tmp /tmp)
  # The repo (and, under it, nonfree/) at its real path so absolute -C paths,
  # bender filelists and generated collateral all resolve unchanged.
  binds+=(--bind "$ROOT" "$ROOT")
  local extra
  for extra in ${OCAH_BWRAP_EXTRA_BINDS:-}; do
    [[ -e "$extra" ]] && binds+=(--bind "$extra" "$extra")
  done
  # HOME may sit outside the bound trees; give it a writable stand-in.
  # PYTHONHOME/PYTHONPATH are dropped for the same reason PATH is replaced: the
  # sandbox runs its own interpreter, and a caller's values point at host trees
  # that are not bound here. A leaked PYTHONHOME makes python3 abort before it
  # can import 'encodings', which the firmware post-process steps run into.
  bwrap "${binds[@]}" --chdir "$workdir" \
    --setenv PATH /usr/local/bin:/usr/bin:/bin \
    --setenv HOME /tmp \
    --unsetenv PYTHONHOME \
    --unsetenv PYTHONPATH \
    "$@"
}

run() {
  if use_bwrap; then
    bwrap_run "$ROOT" "$@"
    return
  fi
  ensure_image
  run_image "$IMAGE" "$@"
}

# Firmware image with 1:1 paths and the caller's cwd, for callers that pass
# host-absolute paths. The nonfree SMC DV cgen stage needs this: it drives the
# picolibc firmware builds with absolute `make -C` paths spanning both this repo
# and nonfree/, which would not resolve under `run`'s /work remap.
run_here() {
  if use_bwrap; then
    bwrap_run "$PWD" "$@"
    return
  fi
  ensure_image
  run_image_1to1 "$IMAGE" "$@"
}

# run_image_1to1 IMAGE [-it] CMD... : like run_image, but mounts the repo at
# its own host-absolute path instead of /work. Used by the EDA flows, whose
# bender-generated `.f` filelists already contain host-absolute paths.
run_image_1to1() {
  local image="$1"
  shift
  local f=()
  [[ "${1:-}" == "-it" ]] && {
    f=(-it)
    shift
  }
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm "${f[@]}" \
    "${USER_FLAGS[@]}" -v "${ROOT}:${ROOT}${VOL}" -w "$PWD" "$image" "$@"
}

if [[ "${USE_NIX_IMAGE:-false}" == true ]]; then
    NIX_IMAGE=$NIX_IMAGE_NAME:$(nix_image_hash)
    EDA_IMAGE=$NIX_IMAGE
    IMAGE=$NIX_IMAGE
    DOC_HTML_IMAGE=$NIX_IMAGE
    DOC_PDF_IMAGE=$NIX_IMAGE
fi

# hpretl/iic-osic-tools's entrypoint launches a UI (X11/VNC) by default;
# `--skip` (must come first) tells it to exec the given command instead.
eda_run() {
  local f=()
  [[ "${1:-}" == "-it" ]] && {
    f=(-it)
    shift
  }
  run_image_1to1 "$EDA_IMAGE" "${f[@]}" --skip "$@"
  exit 0
}

doc_product_paths() {
  case "${1:-trm}" in
  trm) echo "doc/trm antora-trm-playbook.yml ocah-doc-trm-setup ocah-doc-trm-pdf" ;;
  integrator) echo "doc/integrator antora-integrator-playbook.yml ocah-doc-integrator-setup ocah-doc-integrator-pdf" ;;
  programmer) echo "doc/programmer antora-programmer-playbook.yml ocah-doc-programmer-setup ocah-doc-programmer-pdf" ;;
  appnotes) echo "doc/appnotes antora-appnotes-playbook.yml ocah-doc-appnotes-setup ocah-doc-appnotes-pdf" ;;
  contributing) echo "doc/contributing antora-contributing-playbook.yml ocah-doc-contributing-setup ocah-doc-contributing-pdf" ;;
  home) echo "doc/home antora-home-playbook.yml ocah-doc-home-setup" ;;
  *)
    echo "error: unknown doc product '$1' (expected trm, integrator, programmer, appnotes, home or contributing)" >&2
    exit 1
    ;;
  esac
}

doc_release_enabled() {
  case "${OCAH_DOC_RELEASE:-1}" in
  1 | yes | true) return 0 ;;
  *) return 1 ;;
  esac
}

doc_setup() {
  local product="${1:-trm}" basedir playbook setup_target pdf_target
  read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
  run_image "$DOC_PDF_IMAGE" env \
    OCAH_DOC_REGEN_REGS=0 \
    OCAH_DOC_RELEASE="${OCAH_DOC_RELEASE:-1}" \
    make "$setup_target"
}

# Stage verification dashboard JSON into a built site tree. doc/trm/src/
# dashboard.adoc fetches this at page load; without it the page renders its
# unavailable state.
doc_stage_dashboard_data() {
  OCAH_ROOT="$ROOT" bash "${ROOT}/tools/doc/stage_dashboard_data.sh" "$1"
}

doc_html() {
  local product="${1:-trm}" basedir playbook setup_target pdf_target
  local release_args=()
  read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
  doc_setup "$product"
  doc_release_enabled && release_args=(--attribute release)
  local npm_cmd=''
  [[ -z "${OCAH_NO_INSTALL_NPM_DEPS:-}" ]] && npm_cmd='npm install --no-save --no-package-lock asciidoctor-kroki@0.18.1 &&'
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm "${USER_FLAGS[@]}" \
    --entrypoint sh \
    -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
    -c '${npm_cmd} antora "$@"' \
    sh "${release_args[@]}" --attribute "basedir=${basedir}" "$playbook"
  # Only the TRM carries the dashboard page; staging elsewhere would leave a
  # stray ocah-docs/ tree inside another book's site.
  if [ "$product" = trm ]; then
    doc_stage_dashboard_data "${ROOT}/${basedir}/_build/html_antora"
  fi
}

doc_html_all() {
  local release_arg=""
  doc_release_enabled && release_arg="--attribute release"
  # This is the combined-architecture build.
  doc_setup trm
  doc_setup integrator
  doc_setup programmer
  doc_setup appnotes
  doc_setup home
  doc_setup contributing
  # The prebuilt antora/antora:3.1.10 image has Antora pre-installed but
  # NOT the Node extensions used by the npx-based OCAH_ANTORA path in
  # doc/doc.mk, which real CI uses via `make ocah-doc-combined-html`.
  # This direct-image path is separate and needs its own install.
  # `npm install` here writes into the
  # bind-mounted repo root, so it only needs to happen once per checkout
  # (harmless to repeat). Make sure node_modules/ is gitignored.
  local npm_cmd=''
  [[ -z "${OCAH_NO_INSTALL_NPM_DEPS:-}" ]] && npm_cmd='npm install --no-save --no-package-lock @antora/lunr-extension@1.0.0-alpha.13 asciidoctor-kroki@0.18.1 &&'
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm \
    -e SITE_SEARCH_PROVIDER=lunr -e OCAH_DOC_RELEASE_ARG="$release_arg" \
    -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
    sh -c '${npm_cmd} antora $OCAH_DOC_RELEASE_ARG antora-playbook.yml'
}

doc_pdf() {
  local product="${1:-trm}" basedir playbook setup_target pdf_target
  read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
  run_image "$DOC_PDF_IMAGE" env \
    OCAH_DOC_REGEN_REGS=0 \
    OCAH_DOC_RELEASE="${OCAH_DOC_RELEASE:-1}" \
    make "$pdf_target"
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
  local contributing_dist="${OCAH_CONTRIBUTING_DIST:-doc/contributing/dist}" contributing_pdf="${OCAH_CONTRIBUTING_PDF:-ocah-contributing.pdf}"

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

  if [[ -f "$ROOT/$contributing_dist/$contributing_pdf" ]]; then
    cp "$ROOT/$contributing_dist/$contributing_pdf" "$ROOT/$ghpages_dir/downloads/"
  else
    echo "warning: Contributing PDF not found at $contributing_dist/$contributing_pdf, skipping (run: ./scripts/docker-run.sh doc-pdf contributing)"
  fi

  doc_stage_dashboard_data "$ROOT/$ghpages_dir"

  echo "Staged GitHub Pages tree at $ghpages_dir"
  echo "Preview locally with: cd $ghpages_dir && python3 -m http.server 8000"
}

case "${1:-}" in
build) build_image ;;
nixos-shell) nixos_shell ;;
nix-fmt) nixos_run "nix fmt" ;;
ensure) ensure_image ;;
verify)
  run riscv64-unknown-elf-gcc --version
  echo ---
  run riscv64-unknown-elf-gcc -print-multi-lib
  ;;
run)
  shift
  [[ $# -gt 0 ]] || {
    echo "error: run requires a command" >&2
    exit 1
  }
  run "$@"
  ;;
run-here)
  shift
  [[ $# -gt 0 ]] || {
    echo "error: run-here requires a command" >&2
    exit 1
  }
  run_here "$@"
  ;;
shell) run -it bash ;;
doc-html)
  shift
  [[ "${1:-trm}" == "all" ]] && doc_html_all || doc_html "${1:-trm}"
  ;;
doc-pdf)
  shift
  doc_pdf "${1:-trm}"
  ;;
doc-stage) doc_stage ;;
eda-run)
  shift
  [[ $# -gt 0 ]] || {
    echo "error: eda-run requires a command" >&2
    exit 1
  }
  eda_run "$@"
  ;;
eda-shell) eda_run -it bash ;;
"" | -h | --help | help) sed -n '7,31p' "$0" ;;
*)
  echo "error: unknown command '$1'" >&2
  exit 1
  ;;
esac

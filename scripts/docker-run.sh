#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH nix-built container.
#
#   Usage: docker-run.sh <build|ensure|verify|run CMD...|run-here CMD...|shell|nixos-shell|doc-html [trm|integrator|programmer|appnotes|home|starting|all]|doc-pdf [trm|integrator|programmer|appnotes]|doc-stage>
#   'doc-html all'  builds the real combined multi-book site (antora-playbook.yml) -- this
#                   is what gets deployed
#   'doc-stage'     adds PDFs + .nojekyll on top of an already-built combined site -- pure
#                   file copying, no Docker/Node needed. Run after doc-html all + doc-pdf.
#   build           (re)build nix container image + publish to shared tarball cache
#   ensure          make nix container image available (cache -> build); auto-run
#                   by run/run-here/shell/verify, so bare `run` works on a fresh host
#   verify          gcc version + multilibs
#   shell           interactive shell
#   nixos-shell     Open an interactive shell in the NixOS build container - useful
#                   for debugging the container build
#   run CMD         run in nix container
#   run-here CMD    1:1 host paths and caller's cwd (nonfree DV cgen)
#   doc-html        build HTML with Antora
#   doc-pdf         build PDF with Asciidoctor-pdf
# Env: OCAH_NIXOS_IMAGE        base NixOS image for building on nix-less hosts
#                               (default: docker.io/nixos/nix:latest)
#      OCAH_IMAGE_WITH_UV      bundle uv-installed dependencies into nix-built
#                               image (true/false, default: false)
#      OCAH_DOCKER_CACHE_DIR   optional shared tarball cache dir for the nix
#                               container image; unset disables the cache
#                               (site CI sets this, e.g. in its env setup)
#      OCAH_ENGINE             force `podman` or `docker` instead of preferring
#                               whichever is found first (CI pins this so a
#                               runner image shipping both is deterministic)
#      OCAH_PODMAN_KEEP_ID     1/0 to force --userns=keep-id on or off; default
#                               enables it only when /etc/subuid grants a range
#                               wider than the caller's uid
#      OCAH_DOCKER_UIDGID      container --user (default: empty for rootless
#                               podman, caller's uid:gid for docker; set empty to
#                               run as the image's own default user)
#      OCAH_PODMAN_DIR         optional base for podman runtime+storage; also
#                               used when /run/user/<uid> is unwritable, with
#                               default /tmp/ocah-podman-<uid>
#      OCAH_SKIP_GID_FIXUP     set to 1 to skip re-running under the passwd
#                               primary group for rootless podman (see below)
#      OCAH_TOOLCHAIN_ROOTFS   rootfs extracted from the nix container image;
#                               when set (and bwrap is present) `run`/`run-here`
#                               use bubblewrap instead of podman/docker (see below)
#      OCAH_BWRAP_EXTRA_BINDS  extra host paths to bind into the bwrap sandbox
#                               (space-separated; each bound at its own path)
set -euo pipefail

[[ -n ${OCAH_DOCKER_RUN_CI:-} ]] && set -x

# -P: the physical path, so symlinked checkout parents don't produce a path
# that fails to resolve inside the container's bind mount.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

NIXOS_IMAGE="${OCAH_NIXOS_IMAGE:-docker.io/nixos/nix:latest}"
IMAGE_WITH_UV="${OCAH_IMAGE_WITH_UV:-false}"
NETWORK="${OCAH_NETWORK:-ocah-docs-net}"
MANIFEST_SUBMODULE="hw/sys/sep/bootrom/prod/tools/tt-oca-manifest"

# Private submodules, as "<path>:<repository name>". A flake input is fetched
# with submodules=1, so nix resolves every one of these from .gitmodules -- over
# SSH, which no hosted runner has a key for. Each is rewritten below to the copy
# already checked out on disk, so the build reads them locally and needs no
# credential. A submodule that is not checked out is skipped rather than
# rewritten to a path that does not exist.
PRIVATE_SUBMODULES=(
  "${MANIFEST_SUBMODULE}:tt-oca-manifest"
  "virtual_platform/tt-oca-harness-model:tt-oca-harness-model"
)

# Emit GIT_CONFIG_* assignments, one line each, rewriting every checked-out
# private submodule. $1 is the repository root as nix will see it: the host path
# when nix runs locally, /work when it runs in the container. Returns non-zero
# when none are checked out, so callers can skip the env entirely.
submodule_git_config() {
  local base="$1" entry path repo st i=1
  local out=(GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always)
  for entry in "${PRIVATE_SUBMODULES[@]}"; do
    path="${entry%%:*}"
    repo="${entry##*:}"
    st="$(git -C "$ROOT" submodule status -- "$path" 2>/dev/null || true)"
    # A leading "-" means registered but not checked out.
    [[ -n "$st" && "$st" != -* ]] || continue
    out+=("GIT_CONFIG_KEY_${i}=url.file://${base}/${path}.insteadOf"
      "GIT_CONFIG_VALUE_${i}=git@github.com:tenstorrent/${repo}.git")
    i=$((i + 1))
    out+=("GIT_CONFIG_KEY_${i}=url.file://${base}/${path}.insteadOf"
      "GIT_CONFIG_VALUE_${i}=ssh://git@github.com/tenstorrent/${repo}.git")
    i=$((i + 1))
  done
  [[ $i -gt 1 ]] || return 1
  printf '%s\n' "GIT_CONFIG_COUNT=${i}" "${out[@]}"
}

# safe.directory lines for the container branch: the repo is owned by root
# there, so git refuses to read it or any submodule without them.
submodule_safe_dirs() {
  local entry path
  printf '%s' 'git config --global --add safe.directory $(pwd) &&'
  for entry in "${PRIVATE_SUBMODULES[@]}"; do
    path="${entry%%:*}"
    printf '\n            %s' "git config --global --add safe.directory \$(pwd)/${path} &&"
  done
}

NIX_IMAGE_NAME=$([[ "${IMAGE_WITH_UV:-false}" == true ]] && echo "ocah-uv-container" || echo "ocah-container")

# The nix container image is built locally and published to no registry. A built
# image can be cached as a tarball on shared storage, keyed by the flake output
# hash: hosts reuse a matching local image, else load the tarball, else build.
# The cache is only active when OCAH_DOCKER_CACHE_DIR is set (site-specific;
# e.g. exported by the adopter's CI environment setup).
DOCKER_CACHE_DIR="${OCAH_DOCKER_CACHE_DIR:-}"

# Will this invocation actually need a container engine? run/run-here/verify/shell
# can be served by the bubblewrap backend (see below), in which case no engine -
# and none of the rootless-podman preparation underneath - is needed.
NEEDS_ENGINE=1
case "${1:-}" in
run | run-here | verify | shell)
  if [[ -n "${OCAH_TOOLCHAIN_ROOTFS:-}" ]] &&
    [[ -x "${OCAH_TOOLCHAIN_ROOTFS}/bin/riscv64-unknown-elf-gcc" ]] &&
    command -v bwrap >/dev/null 2>&1; then
    NEEDS_ENGINE=0
  fi
  ;;
nix-fmt | nix-fmt-check | nixos-shell)
  if command -v nix >/dev/null 2>&1; then
    NEEDS_ENGINE=0
  fi
  ;;
esac

# OCAH_ENGINE pins the engine; otherwise podman is preferred over docker. A
# host with both installed otherwise changes engine depending on PATH order,
# and CI pins this so a runner image shipping both stays deterministic.
ENGINE="${OCAH_ENGINE:-}"
if [[ -n "$ENGINE" ]]; then
  case "$ENGINE" in
  podman | docker) ;;
  *)
    echo "error: OCAH_ENGINE must be 'podman' or 'docker', not '$ENGINE'" >&2
    exit 1
    ;;
  esac
  if ! command -v "$ENGINE" >/dev/null 2>&1; then
    # Only fatal when an engine is actually going to be used: a pinned engine
    # that is absent must not break a request bwrap can serve.
    [[ "$NEEDS_ENGINE" == 0 ]] ||
      {
        echo "error: OCAH_ENGINE=$ENGINE but $ENGINE is not on PATH" >&2
        exit 1
      }
    ENGINE=none
  fi
elif command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
elif [[ "$NEEDS_ENGINE" == 0 ]]; then
  ENGINE=none
else
  echo "error: podman or docker is required" >&2
  exit 1
fi

if [[ "$ENGINE" == podman ]]; then
  VOL=":Z"
  PODMAN_STORAGE_FLAGS="--storage-opt=ignore_chown_errors=true"
  # Only pass mount_program when fuse-overlayfs is actually installed: an empty
  # value is not "unset", and podman rejects the malformed flag.
  if _fuse_overlayfs="$(command -v fuse-overlayfs 2>/dev/null)"; then
    PODMAN_STORAGE_FLAGS+=" --storage-opt=mount_program=${_fuse_overlayfs}"
  fi
  # --userns=keep-id makes the container see the caller's own uid rather than
  # root. It needs the account's subuid allocation to be wide enough to map that
  # uid inside the namespace: podman maps container uids 0..uid-1 onto the
  # subuid range before pinning container uid == host uid. A large
  # (LDAP/AD-assigned) uid with the customary 65536-wide range therefore does
  # not fit, and podman fails before the container starts:
  #   chowning container workdir to container root:
  #   chown .../merged/work: invalid argument
  # Rootless podman's DEFAULT mapping already maps container root to the
  # caller's uid, so bind-mounted output comes out caller-owned either way --
  # the same reason --user is not passed below -- so drop the flag instead of
  # failing. Force it either way with OCAH_PODMAN_KEEP_ID=1/0.
  PODMAN_RUN_FLAGS=""
  if [[ -n "${OCAH_PODMAN_KEEP_ID:-}" ]]; then
    [[ "$OCAH_PODMAN_KEEP_ID" == 1 ]] && PODMAN_RUN_FLAGS="--userns=keep-id"
  else
    _uid="$(id -u)"
    # Sum every range granted to this account (by name or by uid); absent
    # /etc/subuid or no entry yields 0, which correctly disables the flag.
    _subuids="$(awk -F: -v u="$(id -un)" -v n="$_uid" \
      '$1 == u || $1 == n { c += $3 } END { print c + 0 }' \
      /etc/subuid 2>/dev/null)"
    if [[ "${_subuids:-0}" -gt "$_uid" ]]; then
      PODMAN_RUN_FLAGS="--userns=keep-id"
    fi
  fi
else
  VOL=""
  PODMAN_STORAGE_FLAGS=""
  PODMAN_RUN_FLAGS=""
fi

# Create a named network if it does not already exist. Both Docker and Podman
# support the same syntax; neither auto-removes the network when containers
# leave, so trap removal on exit
ensure_network() {
  local net="$1"
  if ! "$ENGINE" network ls --format '{{.Name}}' 2>/dev/null | grep -qx "$net"; then
    "$ENGINE" network create "$net" >/dev/null
    echo "docker-run: created network '$net'" >&2
  fi
  trap '"$ENGINE" network rm "$NETWORK" 2>/dev/null || true' EXIT
}

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
# (XDG_DATA_HOME) to a node-local, per-uid directory. OCAH_PODMAN_DIR selects
# that directory explicitly when the default image store is unsuitable even
# though the runtime directory itself is writable.
if [[ "$ENGINE" == podman && "$NEEDS_ENGINE" == 1 ]]; then
  _rt="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  if [[ -n "${OCAH_PODMAN_DIR:-}" || ! -w "$_rt" ]]; then
    _base="${OCAH_PODMAN_DIR:-${TMPDIR:-/tmp}/ocah-podman-$(id -u)}"
    export XDG_RUNTIME_DIR="${_base}/run" XDG_DATA_HOME="${_base}/share"
    mkdir -p "$XDG_RUNTIME_DIR" "$XDG_DATA_HOME"
    chmod 700 "$XDG_RUNTIME_DIR"
    echo "docker-run: using podman runtime and storage under $_base" >&2
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

# run_image IMAGE [-it] CMD... : engine flags before the image, command after it
run_image() {
  local image="$1"
  shift
  local f=() net_flags=()
  [[ "${1:-}" == "--net" ]] && {
    net_flags=(--network "$2" ${NETWORK_NAME:+--name "$NETWORK_NAME"})
    ensure_network "$2"
    shift
    shift
  }
  [[ "${1:-}" == "-it" ]] && {
    f=(-it)
    shift
  }
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm "${f[@]}" \
    "${net_flags[@]}" "${USER_FLAGS[@]}" -v "${ROOT}:/work${VOL}" -w /work "$image" "$@"
}

# Run a command in an environment with a nix binary. This will run locally if it
# detects a nix binary, to be able to make use of cached files in the store. On
# hosts without nix installed, it will use NIXOS_IMAGE, which defaults to
# docker.io/nixos/nix
nixos_run() {
  # Nix Flakes and Nix-Command are required for this - enable them
  local NIX_CONFIG="experimental-features = nix-command flakes"
  local -a sub_env=()
  mapfile -t sub_env < <(submodule_git_config "$ROOT" || true)
  if command -v nix >/dev/null 2>&1; then
    if [[ ${#sub_env[@]} -gt 0 ]]; then
      NIX_CONFIG="$NIX_CONFIG" env "${sub_env[@]}" bash -c "$*"
    else
      NIX_CONFIG="$NIX_CONFIG" bash -c "$*"
    fi
  else
    # The repo in the container is owned by root, so nix/git will by default give untrusted errors when interacting with it.
    local GIT_ALLOW_CMD
    GIT_ALLOW_CMD="$(submodule_safe_dirs)"
    local -a ctr_sub_env=()
    mapfile -t ctr_sub_env < <(submodule_git_config /work || true)
    local nix_git_env=()
    if [[ ${#ctr_sub_env[@]} -gt 0 ]]; then
      nix_git_env=(env "${ctr_sub_env[@]}")
    fi
    run_image "$NIXOS_IMAGE" "${nix_git_env[@]}" sh -c "
            export NIX_CONFIG=\"$NIX_CONFIG\"
            export PS1=\"\[\e[1;36m\]NixOS >\[\e[0m\] \"
            $GIT_ALLOW_CMD
            $*
        "
  fi
}

image_hash() {
  local flake_output
  flake_output=$([[ "${IMAGE_WITH_UV:-false}" == true ]] && echo "with_uv_deps" || echo "without_uv_deps")
  nixos_run "nix eval \$(pwd)#containerHashes.$flake_output" | tr -d '"'
}

# Open a shell in the Nix Container - even on a nix-enabled host
nixos_shell() {
  local NIX_CONFIG="experimental-features = nix-command flakes"
  local GIT_ALLOW_CMD="git config --global --add safe.directory \$(pwd) &&
        git config --global --add safe.directory \$(pwd)/hw/sys/sep/bootrom/prod/tools/tt-oca-manifest &&"
  run_image $NIXOS_IMAGE -it sh -c "
        export NIX_CONFIG=\"$NIX_CONFIG\"
        export HISTFILE=/dev/null
        export PS1=\"\[\e[1;36m\]NixOS >\[\e[0m\] \"
        $GIT_ALLOW_CMD
        bash
    "
}

image_cache_tar() {
  echo "${DOCKER_CACHE_DIR}/${NIX_IMAGE_NAME##*/}-$(image_hash).tar.gz"
}

# Build the nix container image and publish it to the shared tarball cache when
# one is configured.
build_image() {
  local flake_output image_location
  flake_output=$([[ "${IMAGE_WITH_UV:-false}" == true ]] && echo "with_uv_deps" || echo "without_uv_deps")
  if [[ -n "$DOCKER_CACHE_DIR" ]]; then
    image_location="$(image_cache_tar)"
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
}

# Ensure $IMAGE is available locally: reuse a matching local image (verified by
# the flake hash), else load the shared tarball cache, else build. Use `build`
# to force a rebuild regardless of what is already present.
ensure_image() {
  local flake_hash
  flake_hash=$(image_hash)
  IMAGE="${NIX_IMAGE_NAME}:${flake_hash}"
  # Test for loaded image in podman
  if "$ENGINE" ${PODMAN_STORAGE_FLAGS} images | grep -qE "${NIX_IMAGE_NAME} *${flake_hash}"; then
    return 0
  fi
  # Check Cache or local image file
  if [[ -n "$DOCKER_CACHE_DIR" ]]; then
    local tar
    tar="$(image_cache_tar)"
    if [ -r "$tar" ]; then
      echo "docker-run: loading $IMAGE from cache $tar" >&2
      "$ENGINE" ${PODMAN_STORAGE_FLAGS} load -i "$tar"
      return 0
    fi
  else
    local_tar="local/nix-container-image.tar.gz"
    if [[ -f "$local_tar" ]]; then
      tar_repotag=$(nixos_run "tar -xOf $local_tar manifest.json | nix run nixpkgs#jq -- -r '.[0].RepoTags[0]'")
      if [[ "$tar_repotag" == "$IMAGE" ]]; then
        echo "docker-run: loading $IMAGE from $local_tar" >&2
        "$ENGINE" ${PODMAN_STORAGE_FLAGS} load -i "$local_tar"
        return 0
      fi
    fi
  fi
  echo "docker-run: $IMAGE (hash $flake_hash) absent locally and in cache; building" >&2
  build_image
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
  if [[ ! -x "${TOOLCHAIN_ROOTFS}/bin/riscv64-unknown-elf-gcc" ]]; then
    echo "docker-run: warning: OCAH_TOOLCHAIN_ROOTFS='$TOOLCHAIN_ROOTFS' has no" \
      "bin/riscv64-unknown-elf-gcc; falling back to $ENGINE" >&2
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
  local f=() net_flags=()
  [[ "${1:-}" == "--net" ]] && {
    net_flags=(--network "$2" ${NETWORK_NAME:+--name "$NETWORK_NAME"})
    ensure_network "$2"
    shift
    shift
  }
  [[ "${1:-}" == "-it" ]] && {
    f=(-it)
    shift
  }
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm "${f[@]}" \
    "${net_flags[@]}" "${USER_FLAGS[@]}" -v "${ROOT}:${ROOT}${VOL}" -w "$PWD" "$image" "$@"
}

doc_product_paths() {
  case "${1:-trm}" in
  trm) echo "doc/trm antora-trm-playbook.yml ocah-doc-trm-setup ocah-doc-trm-pdf" ;;
  integrator) echo "doc/integrator antora-integrator-playbook.yml ocah-doc-integrator-setup ocah-doc-integrator-pdf" ;;
  programmer) echo "doc/programmer antora-programmer-playbook.yml ocah-doc-programmer-setup ocah-doc-programmer-pdf" ;;
  appnotes) echo "doc/appnotes antora-appnotes-playbook.yml ocah-doc-appnotes-setup ocah-doc-appnotes-pdf" ;;
  starting) echo "doc/starting antora-starting-playbook.yml ocah-doc-starting-setup ocah-doc-starting-pdf" ;;
  home) echo "doc/home antora-home-playbook.yml ocah-doc-home-setup" ;;
  *)
    echo "error: unknown doc product '$1' (expected trm, integrator, programmer, appnotes, home or starting)" >&2
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
  run env \
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
  local product="${1:-trm}" basedir playbook setup_target pdf_target companion
  local release_args=() kroki_args=()
  read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
  doc_setup "$product"
  if [ "$product" = trm ]; then
    for companion in home integrator programmer appnotes starting; do
      doc_setup "$companion"
    done
  fi
  doc_release_enabled && release_args=(--attribute release)
  [[ "${OCAH_ANTORA_KROKI_OFFLINE:-}" == true ]] && kroki_args=(--attribute "kroki-server-url=http://kroki:8001")
  run --net "$NETWORK" antora --cache-dir /tmp/antora "${release_args[@]}" "${kroki_args[@]}" --attribute "basedir=${basedir}" "$playbook"
  # Only the TRM carries the dashboard page; staging elsewhere would leave a
  # stray ocah-docs/ tree inside another book's site.
  if [ "$product" = trm ]; then
    doc_stage_dashboard_data "${ROOT}/${basedir}/_build/html_antora"
  fi
}

doc_html_all() {
  local release_args=() kroki_args=() net_args=()
  doc_release_enabled && release_args=(--attribute release)
  if [[ "${OCAH_ANTORA_KROKI_OFFLINE:-}" == true ]]; then
    kroki_args=(--attribute "kroki-server-url=http://kroki:8001")
    net_args=(--net "$NETWORK")
  fi
  # This is the combined-architecture build.
  doc_setup trm
  doc_setup integrator
  doc_setup programmer
  doc_setup appnotes
  doc_setup home
  doc_setup starting
  run "${net_args[@]}" env \
    SITE_SEARCH_PROVIDER=lunr \
    antora --cache-dir /tmp/antora "${release_args[@]}" "${kroki_args[@]}" antora-playbook.yml
}

doc_pdf() {
  local product="${1:-trm}" basedir playbook setup_target pdf_target
  read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
  run_image "$IMAGE" env \
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
  local starting_dist="${OCAH_STARTING_DIST:-doc/starting/dist}" starting_pdf="${OCAH_STARTING_PDF:-ocah-starting.pdf}"

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

  if [[ -f "$ROOT/$starting_dist/$starting_pdf" ]]; then
    cp "$ROOT/$starting_dist/$starting_pdf" "$ROOT/$ghpages_dir/downloads/"
  else
    echo "warning: Getting Started PDF not found at $starting_dist/$starting_pdf, skipping (run: ./scripts/docker-run.sh doc-pdf starting)"
  fi

  doc_stage_dashboard_data "$ROOT/$ghpages_dir"

  echo "Staged GitHub Pages tree at $ghpages_dir"
  echo "Preview locally with: cd $ghpages_dir && python3 -m http.server 8000"
}

doc_kroki() {
  ensure_network "$NETWORK"
  KROKI_PORT="${OCAH_KROKI_PORT:-8001}"
  echo "docker-run: Kroki listening on http://localhost:${KROKI_PORT}; antora containers reach it at http://kroki:8001" >&2
  PODMAN_RUN_FLAGS="$PODMAN_RUN_FLAGS -p ${KROKI_PORT}:8001" NETWORK_NAME=kroki run --net "$NETWORK" -it kroki
}

case "${1:-}" in
build) build_image ;;
nixos-shell) nixos_shell ;;
nix-fmt)
  nixos_run "nix fmt"
  ;;
nix-fmt-check)
  nixos_run "nix fmt -- -f check"
  ;;
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
shell) run -it env HISTFILE=/tmp/bash_history bash ;;
shell-here) run_here -it env HISTFILE=/tmp/bash_history bash ;;
doc-html)
  shift
  [[ "${1:-trm}" == "all" ]] && doc_html_all || doc_html "${1:-trm}"
  ;;
doc-pdf)
  shift
  doc_pdf "${1:-trm}"
  ;;
doc-stage) doc_stage ;;
doc-kroki) doc_kroki ;;
"" | -h | --help | help) sed -n '7,35p' "$0" ;;
*)
  echo "error: unknown command '$1'" >&2
  exit 1
  ;;
esac

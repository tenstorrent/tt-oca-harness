#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Helper for running repo commands in the OCAH toolchain container. See tools/docker/README.md.
#
#   Usage: docker-run.sh <build|ensure|verify|run CMD...|run-here CMD...|shell|doc-html [trm|integrator|programmer|appnotes|home|starting|all]|doc-pdf [trm|integrator|programmer|appnotes]|doc-stage|eda-run CMD...|eda-shell|vp-build|vp-run CMD...|vp-shell|vp-verify>#   'doc-html all' builds the real combined multi-book site (antora-playbook.yml) -- this is what gets deployed
#   'doc-stage' adds PDFs + .nojekyll on top of an already-built combined site -- pure file copying, no Docker/Node needed. Run after doc-html all + doc-pdf.
#   build     (re)build the toolchain image + publish to shared tarball cache
#             (vp-build is an alias: one image serves firmware and the VP)
#   ensure    make the toolchain image available (local -> cache -> build);
#             auto-run by run/run-here/shell/verify, so bare `run` works on a
#             fresh host
#   verify    gcc version + multilibs      shell     interactive shell
#   run CMD   run in the toolchain image
#   run-here CMD  toolchain image, 1:1 host paths and caller's cwd (nonfree DV cgen)
#   doc-html  build HTML with Antora image doc-pdf  build PDF with Asciidoctor image
#   eda-run   run in the open EDA image    eda-shell interactive EDA shell
#   vp-run CMD  same image, 1:1 host paths -- an alias of run-here, spelled for
#               the VP (build AND run sep-vp in here: a container-built sep-vp
#               links the container glibc and cannot run on older hosts)
#   vp-shell    interactive shell with 1:1 host paths
#   vp-verify   native compiler + cmake versions (the VP side of `verify`)
# Env: OCAH_DOCKER_IMAGE       toolchain image tag (default: ocah-toolchain)
#      OCAH_DOCKER_CACHE_DIR   optional shared tarball cache dir for the
#                               toolchain image; unset disables the cache
#                               (site CI sets this, e.g. in its env setup)
#      OCAH_ENGINE             force `podman` or `docker` instead of preferring
#                               whichever is found first (CI pins this so a
#                               runner image shipping both is deterministic)
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
#      OCAH_TOOLCHAIN_ROOTFS   extracted toolchain-image rootfs; when set (and
#                               bwrap is present) `run`/`run-here`/`vp-run` use
#                               bubblewrap instead of podman/docker (see below).
#                               Must come from the merged image: both the RISC-V
#                               and the native compiler are probed for
#      OCAH_BWRAP_EXTRA_BINDS  extra host paths to bind into the bwrap sandbox
#                               (space-separated; each bound at its own path)
set -euo pipefail

# -P: the physical path. A checkout reached through a symlinked parent would
# otherwise be bound at a path that resolves under one of the read-only rootfs
# mounts, where bwrap cannot create the mount point.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
IMAGE="${OCAH_DOCKER_IMAGE:-ocah-toolchain}"
DOC_HTML_IMAGE="${OCAH_DOC_HTML_IMAGE:-docker.io/antora/antora:3.1.10}"
DOC_PDF_IMAGE="${OCAH_DOC_PDF_IMAGE:-docker.io/asciidoctor/docker-asciidoctor:1.106.0@sha256:6266e05784c2d8ece9d9fe5e593b12c3beebebbc467135fd6f4a56269c93cea3}"
EDA_IMAGE="${OCAH_EDA_IMAGE:-hpretl/iic-osic-tools:2025.12}"

# Toolchain image provisioning. The ocah-toolchain image is built locally and
# published to no registry, so bare `run` on a fresh host would try (and fail)
# to pull it. To avoid every CI runner rebuilding it - and to avoid depending on
# registry/internet access at job time - a built image can be cached as a
# tarball on shared storage, keyed by the Dockerfile hash: hosts reuse a
# matching local image, else load the tarball, else build once and publish it
# for the rest. The cache is only active when OCAH_DOCKER_CACHE_DIR is set
# (site-specific; e.g. exported by the adopter's CI environment setup).
DOCKER_CTX="${ROOT}/tools/docker"
DOCKER_CACHE_DIR="${OCAH_DOCKER_CACHE_DIR:-}"

DOCKERFILE="${DOCKER_CTX}/Dockerfile"
ROOTFS_ENV="${OCAH_TOOLCHAIN_ROOTFS:-}"

# One image now carries both toolchains, so an extracted rootfs must too. Probe
# for both: a rootfs extracted from an older firmware-only image would satisfy a
# RISC-V-only check and then fail deep inside a VP build instead of here.
ROOTFS_PROBES=(usr/bin/riscv64-unknown-elf-gcc usr/bin/g++)

# rootfs_missing DIR : echo the first absent probe binary and return 0;
#                      return 1 when every probe is present.
rootfs_missing() {
  local p
  for p in "${ROOTFS_PROBES[@]}"; do
    [[ -x "${1}/${p}" ]] || {
      echo "$p"
      return 0
    }
  done
  return 1
}

# Will this invocation actually need a container engine? The toolchain
# subcommands can be served by the bubblewrap backend (see below), in which case
# no engine - and none of the rootless-podman preparation underneath - is needed.
# The doc/EDA subcommands use pulled images and always need an engine.
NEEDS_ENGINE=1
case "${1:-}" in
run | run-here | verify | shell | vp-run | vp-shell | vp-verify)
  if [[ -n "$ROOTFS_ENV" ]] &&
    ! rootfs_missing "$ROOTFS_ENV" >/dev/null &&
    command -v bwrap >/dev/null 2>&1; then
    NEEDS_ENGINE=0
  fi
  ;;
esac

# OCAH_ENGINE pins the engine; otherwise podman is preferred over docker.
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
    # Only fatal when an engine is actually going to be used: a pinned
    # engine that is absent must not break a request bwrap can serve.
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
  # Only pass mount_program when fuse-overlayfs is actually installed: an
  # empty value is not "unset", and podman rejects the malformed flag.
  if _fuse_overlayfs="$(command -v fuse-overlayfs 2>/dev/null)"; then
    PODMAN_STORAGE_FLAGS+=" --storage-opt=mount_program=${_fuse_overlayfs}"
  fi
  # --userns=keep-id makes the container see the caller's own uid rather than
  # root. It needs the account's subuid allocation to be wide enough to map
  # that uid inside the namespace: podman maps container uids 0..uid-1 onto
  # the subuid range before pinning container uid == host uid. A large
  # (LDAP/AD-assigned) uid with the customary 65536-wide range therefore does
  # not fit, and podman fails before the container starts:
  #   chowning container workdir to container root:
  #   chown .../merged/work: invalid argument
  # Rootless podman's DEFAULT mapping already maps container root to the
  # caller's uid, so bind-mounted output comes out caller-owned either way
  # (that is the same reason --user is not passed below) - so drop the flag
  # instead of failing. Force it either way with OCAH_PODMAN_KEEP_ID=1/0.
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
image_hash() { sha256sum "$DOCKERFILE" | cut -c1-16; }
image_cache_tar() { echo "${DOCKER_CACHE_DIR}/${IMAGE##*/}-$(image_hash).tar"; }

# Build the firmware image (labeled with the Dockerfile hash) and publish it to
# the shared tarball cache when one is configured and writable. A publish
# failure is a warning, not a build failure.
build_image() {
  local hash
  hash="$(image_hash)"
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} build --label "ocah.dockerfile.sha=${hash}" \
    -f "$DOCKERFILE" -t "$IMAGE" "$DOCKER_CTX"
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
}

# Ensure $IMAGE is available locally: reuse a matching local image (verified by
# the Dockerfile-hash label), else load the shared tarball cache, else build and
# publish. Use `build` to force a rebuild regardless of what is already present.
ensure_image() {
  local hash tar
  hash="$(image_hash)"
  if [ "$("$ENGINE" ${PODMAN_STORAGE_FLAGS} image inspect \
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
TOOLCHAIN_ROOTFS="$ROOTFS_ENV"

use_bwrap() {
  [[ -n "$TOOLCHAIN_ROOTFS" ]] || return 1
  local missing
  if missing="$(rootfs_missing "$TOOLCHAIN_ROOTFS")"; then
    echo "docker-run: warning: rootfs '$TOOLCHAIN_ROOTFS' has no" \
      "${missing}; falling back to $ENGINE" >&2
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
  # --die-with-parent: killing the outer bwrap (e.g. a test harness
  # terminating a spawned simulator) must not orphan the sandboxed process,
  # which may never exit on its own.
  # RISCV_TOOLCHAIN is unset for the same reason PATH is replaced: it names a
  # host toolchain path that is not bound here; the sandbox's own toolchain
  # (on the reset PATH) is the one to use.
  # OCAH_IN_CONTAINER lets sandboxed makes detect containment (bwrap creates
  # neither /run/.containerenv nor /.dockerenv, the usual markers).
  bwrap "${binds[@]}" --chdir "$workdir" \
    --die-with-parent \
    --setenv PATH /usr/local/bin:/usr/bin:/bin \
    --setenv HOME /tmp \
    --setenv OCAH_IN_CONTAINER 1 \
    --unsetenv PYTHONHOME \
    --unsetenv PYTHONPATH \
    --unsetenv RISCV_TOOLCHAIN \
    --unsetenv TMPDIR \
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
  local product="${1:-trm}" basedir playbook setup_target pdf_target companion
  local release_args=()
  read -r basedir playbook setup_target pdf_target < <(doc_product_paths "$product")
  doc_setup "$product"
  if [ "$product" = trm ]; then
    for companion in home integrator programmer appnotes starting; do
      doc_setup "$companion"
    done
  fi
  doc_release_enabled && release_args=(--attribute release)
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm "${USER_FLAGS[@]}" \
    --entrypoint sh \
    -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
    -c 'npm install --no-save --no-package-lock asciidoctor-kroki@0.18.1 && antora "$@"' \
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
  doc_setup starting
  # The prebuilt antora/antora:3.1.10 image has Antora pre-installed but
  # NOT the Node extensions used by the npx-based OCAH_ANTORA path in
  # doc/doc.mk, which real CI uses via `make ocah-doc-combined-html`.
  # This direct-image path is separate and needs its own install.
  # `npm install` here writes into the
  # bind-mounted repo root, so it only needs to happen once per checkout
  # (harmless to repeat). Make sure node_modules/ is gitignored.
  "$ENGINE" ${PODMAN_STORAGE_FLAGS} run ${PODMAN_RUN_FLAGS} --rm \
    -e SITE_SEARCH_PROVIDER=lunr -e OCAH_DOC_RELEASE_ARG="$release_arg" \
    -v "${ROOT}:/work${VOL}" -w /work "$DOC_HTML_IMAGE" \
    sh -c 'npm install --no-save --no-package-lock @antora/lunr-extension@1.0.0-alpha.13 asciidoctor-kroki@0.18.1 && antora $OCAH_DOC_RELEASE_ARG antora-playbook.yml'
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

case "${1:-}" in
build) build_image ;;
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
# One image serves both toolchains, so these are aliases spelled for the VP:
# vp-build == build, vp-run == run-here. Kept so virtual_platform/ and its
# README keep working, and because vp-verify checks the other compiler.
vp-build) build_image ;;
vp-run)
  shift
  [[ $# -gt 0 ]] || {
    echo "error: vp-run requires a command" >&2
    exit 1
  }
  run_here "$@"
  ;;
vp-shell) run_here -it bash ;;
vp-verify)
  run_here g++ --version
  echo ---
  run_here cmake --version
  ;;
"" | -h | --help | help) sed -n '7,48p' "$0" ;;
*)
  echo "error: unknown command '$1'" >&2
  exit 1
  ;;
esac

#!/usr/bin/env bash
# Helper for the OCAH DV firmware toolchain container. See tools/docker/README.md.
#
# Usage: fw-toolchain-docker.sh <build|verify|run CMD...|shell>
#   build   build the image          run CMD  run CMD in container (repo at /work)
#   verify  gcc version + multilibs   shell    interactive bash
# Env: OCAH_FW_DOCKER_IMAGE  image tag (default: ocah-fw-toolchain)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${OCAH_FW_DOCKER_IMAGE:-ocah-fw-toolchain}"

if command -v podman >/dev/null 2>&1; then ENGINE=podman VOL=":Z"
elif command -v docker >/dev/null 2>&1; then ENGINE=docker VOL=""
else echo "error: podman or docker is required" >&2; exit 1; fi

# run [-it] CMD... : engine flags before the image, in-container command after it
run() {
    local f=(); [[ "${1:-}" == "-it" ]] && { f=(-it); shift; }
    "$ENGINE" run --rm "${f[@]}" -v "${ROOT}:/work${VOL}" -w /work "$IMAGE" "$@"
}

case "${1:-}" in
    build)  "$ENGINE" build -t "$IMAGE" "${ROOT}/tools/docker" ;;
    verify) run riscv64-unknown-elf-gcc --version; echo ---; run riscv64-unknown-elf-gcc -print-multi-lib ;;
    run)    shift; [[ $# -gt 0 ]] || { echo "error: run requires a command" >&2; exit 1; }; run "$@" ;;
    shell)  run -it bash ;;
    ""|-h|--help|help) sed -n '2,7p' "$0" ;;
    *)      echo "error: unknown command '$1'" >&2; exit 1 ;;
esac

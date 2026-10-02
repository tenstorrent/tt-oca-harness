#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Wait for this tree's toolchain image tag. On push and schedule, an unfinished
# container run on main may still publish it; the job timeout bounds the wait.
set -euo pipefail
ref="${OCAH_CONTAINER_REGISTRY_IMAGE}:$(./scripts/docker-run.sh image-hash)"
while :; do
  pending=0
  if [[ $GITHUB_EVENT_NAME == push || $GITHUB_EVENT_NAME == schedule ]]; then
    pending=$(gh run list -w container.yml -b main -L 20 --json status \
      --jq 'map(select(.status != "completed")) | length')
  fi
  docker manifest inspect "$ref" >/dev/null 2>&1 && exit 0
  if ((pending == 0)); then
    echo "::error::$ref is not published, and no container run on main is publishing it"
    exit 1
  fi
  echo "waiting for $ref"
  sleep 60
done

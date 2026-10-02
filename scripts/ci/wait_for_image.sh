#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# wait_for_image.sh [--wait] REF
#
# Succeeds once the registry holds REF. Without --wait it checks once. With
# --wait it polls until the tag appears, giving up when the deadline passes or
# when no `container` workflow run on main is queued or in progress, since then
# nothing is left to publish it.
#
# Any active run on main counts, not only one for the same commit: a merge that
# leaves the image inputs alone starts no build yet needs the image an earlier
# merge is still building, and the concurrency group can cancel a run whose hash
# another run then publishes.
#
# --wait needs GH_TOKEN with actions:read and GITHUB_REPOSITORY.
# OCAH_IMAGE_WAIT_MINUTES (default 180) and OCAH_IMAGE_POLL_SECONDS (default 300)
# set the deadline and the polling interval.

set -euo pipefail

wait=0
if [[ ${1:-} == --wait ]]; then
  wait=1
  shift
fi
ref=${1:?usage: wait_for_image.sh [--wait] REF}

wait_minutes=${OCAH_IMAGE_WAIT_MINUTES:-180}
poll_seconds=${OCAH_IMAGE_POLL_SECONDS:-300}

published() {
  docker manifest inspect "$ref" >/dev/null 2>&1
}

# Prints the number of container runs on main that have not completed, or
# nothing when the API cannot be read.
active_builds() {
  gh api "repos/${GITHUB_REPOSITORY}/actions/workflows/container.yml/runs?branch=main&per_page=30" \
    --jq '[.workflow_runs[] | select(.status != "completed")] | length' 2>/dev/null || true
}

summary() {
  local reason=$1
  echo "::error::$ref is not published: $reason"
  if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
    {
      echo "### Toolchain image not published"
      echo
      echo "\`$ref\` is not in the registry: $reason."
      echo
      echo "The container workflow publishes it. It runs on changes to the flake,"
      echo "\`nix/\`, \`ocah_deps.nix\` and the uv workspace; if it has not run for this"
      echo "tree, run it before dispatching this one."
    } >>"$GITHUB_STEP_SUMMARY"
  fi
  exit 1
}

if published; then
  exit 0
fi
if ((!wait)); then
  summary "this run does not wait for it"
fi

deadline=$((SECONDS + wait_minutes * 60))
while :; do
  active=$(active_builds)
  if [[ $active == 0 ]]; then
    # A build that finished between the two checks has published by now.
    published && exit 0
    summary "no container run on main is queued or in progress"
  fi
  if ((SECONDS >= deadline)); then
    summary "still absent after ${wait_minutes} minutes"
  fi
  echo "waiting for $ref (${active:-unknown} container run(s) active on main)"
  sleep "$poll_seconds"
  if published; then
    echo "$ref is published"
    exit 0
  fi
done

#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Wait until this tree's toolchain image tag is in the registry.
#
# On push and schedule, poll for up to three hours while any container
# workflow run on main is queued or in progress. The tag this tree needs may
# be one an earlier run is still publishing. A manual dispatch fails at the
# first miss. A miss with no such run fails after a short grace, because the
# container workflow is dispatched with this one and may not be listed yet.

set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

registry=${OCAH_CONTAINER_REGISTRY_IMAGE:?OCAH_CONTAINER_REGISTRY_IMAGE is unset}
hash=$(./scripts/docker-run.sh image-hash)
ref="${registry}:${hash}"

# The container workflow is dispatched with this one and may not be listed yet.
grace_secs=180
wait_secs=$((3 * 60 * 60))
poll_secs=60

export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

fail() {
    echo "::error::$1"
    {
        echo "### Toolchain image not published"
        echo
        printf '%s\n' "$2"
    } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    exit 1
}

publish_pending() {
    local status count
    for status in queued in_progress; do
        count=$(gh run list \
            --workflow container.yml \
            --branch main \
            --status "$status" \
            --limit 1 \
            --json databaseId \
            --jq 'length') || fail \
            "cannot list container workflow runs" \
            "Listing container workflow runs on main failed, so this leg cannot tell whether the tag will be published."
        if [[ "${count:-0}" -gt 0 ]]; then
            return 0
        fi
    done
    return 1
}

if docker manifest inspect "$ref" >/dev/null 2>&1; then
    echo "await_toolchain_image: ${ref} is published"
    exit 0
fi

case "${GITHUB_EVENT_NAME:-}" in
    push|schedule) ;;
    *)
        fail "${ref} is not published" \
            "This tree resolves to \`${hash}\`, which the container workflow has not published. It runs on changes to the flake, \`nix/\`, \`ocah_deps.nix\` and the uv workspace; if it has not run for this commit, run it before dispatching this one."
        ;;
esac

deadline=$((SECONDS + wait_secs))
missing_since=$SECONDS
while ! docker manifest inspect "$ref" >/dev/null 2>&1; do
    if publish_pending; then
        missing_since=$SECONDS
    elif (( SECONDS - missing_since >= grace_secs )); then
        fail "${ref} is not published" \
            "\`${ref}\` is not in the registry, and no container workflow run on main is queued or in progress, so nothing will publish it."
    fi
    if (( SECONDS >= deadline )); then
        fail "${ref} is not published" \
            "Waited 3 hours for \`${ref}\`. A container run on main was still queued or in progress, but the tag was not published."
    fi
    echo "await_toolchain_image: ${ref} is not published yet; retrying in ${poll_secs}s"
    sleep "$poll_secs"
done

echo "await_toolchain_image: ${ref} is published"

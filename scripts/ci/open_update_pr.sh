#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Commit a dirty automatic-refresh tree and open or refresh its pull request.
# The scheduled workflows (filelists, container dependencies, contributors)
# share this so the branch, bot identity, and pull-request shape stay one
# implementation; each workflow only chooses its schedule and the command
# that dirties the tree. A clean tree is a no-op.
#
# UPDATE_PATHS is a whitespace-separated list of paths to inspect and stage.
# The other UPDATE_* variables are set by .github/actions/open-update-pr.
set -euo pipefail

: "${UPDATE_PATHS:?}"
: "${UPDATE_BRANCH:?}"
: "${UPDATE_MESSAGE:?}"
: "${UPDATE_BODY:?}"
: "${UPDATE_CURRENT:?}"
: "${UPDATE_REVIEWER:?}"

# Paths are repository-relative and contain no whitespace.
read -r -a paths <<<"$UPDATE_PATHS"

if [ -z "$(git status --porcelain -- "${paths[@]}")" ]; then
  echo "$UPDATE_CURRENT"
  exit 0
fi

git fetch origin "$UPDATE_BRANCH:refs/remotes/origin/$UPDATE_BRANCH" || true
git switch -C "$UPDATE_BRANCH"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -- "${paths[@]}"
git commit -m "$UPDATE_MESSAGE"
git push --force-with-lease origin "HEAD:$UPDATE_BRANCH"

pr="$(gh pr list --head "$UPDATE_BRANCH" --state open --json number --jq '.[0].number')"
if [ -z "$pr" ]; then
  gh pr create \
    --base main \
    --head "$UPDATE_BRANCH" \
    --reviewer "$UPDATE_REVIEWER" \
    --title "$UPDATE_MESSAGE" \
    --body "$UPDATE_BODY"
else
  gh pr edit "$pr" --add-reviewer "$UPDATE_REVIEWER"
fi

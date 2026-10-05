#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Print the version of nixpkgs package <attr> that the ocah-container image
# ships: the one from the nixpkgs revision flake.lock pins. Needs nix and jq.
set -euo pipefail
if (($# != 1)); then
  echo "usage: $0 <nixpkgs attribute>" >&2
  exit 2
fi
rev=$(jq -r '.nodes[.nodes.root.inputs.nixpkgs].locked.rev' "$(dirname "$0")/../../flake.lock")
nix eval --raw "github:nixos/nixpkgs/${rev}#$1.version"

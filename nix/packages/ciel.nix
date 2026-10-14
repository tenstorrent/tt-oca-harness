# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  pdk-ciel,
  fetchFromGitHub,
  ...
}:
# Upstream nix package is pdk-ciel
# This was updated to version 3.0.0 recently, which breaks compatibility with the older version of IHP used for OCAH - revert the update here.
pdk-ciel.overrideAttrs (prev: rec {
  version = "2.6.1";
  src = fetchFromGitHub {
    owner = "fossi-foundation";
    repo = "ciel";
    tag = version;
    hash = "sha256-rPsbit/VQ/bTAuRnuaTKQInztJHFhTBofqnrUzYyDKs=";
  };
})

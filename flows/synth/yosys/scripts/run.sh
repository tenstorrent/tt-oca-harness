#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

set -euo pipefail

: "${OCAH_YOSYS_SYNTH_TCL:?OCAH_YOSYS_SYNTH_TCL is required}"
: "${TOP_DESIGN:?TOP_DESIGN is required}"
: "${SV_FLIST:?SV_FLIST is required}"
: "${OUT_DIR:?OUT_DIR is required}"
: "${TIMESCALE:?TIMESCALE is required}"

# OCAH-Nix provisioned Yosys already loads slang, but from a different path, the
# default -m slang results in a load error
yosys_args=()
[[ -z "${OCAH_YOSYS_BUNDLED_SLANG:-}" ]] && yosys_args+=(-m slang)

exec yosys "${yosys_args[@]}" -c "$OCAH_YOSYS_SYNTH_TCL"

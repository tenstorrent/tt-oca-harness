#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Derive a per-run SMC eFuse configuration from a base one.

    randomize_efuse.py <base.toml> --output_file <path> --seed <N>
                       [--transport-timeout <cycles>]

Reads a configuration TOML, rewrites the fields listed below as a function of
`--seed`, and writes a new configuration. Deterministic in the seed: the same
seed always produces the same configuration, so a failing run is reproducible
from its RANDOM_SEED alone.

Feed the result to generate_efuse_preload.py.

WHAT IS RANDOMIZED
------------------
OCCP_TRANSPORT_TIMEOUT -- the OCCP transport timeout.

  The boot ROM reads SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT and treats bits
  [31:0] as the transport timeout in cycles, substituting a 10000-cycle
  default when the fuse reads 0 (bootrom/prod/lib/src/occp.c, bootrom/prod/
  drivers/src/smc_efuse.c). Both branches are worth exercising, so this
  script picks:

      50% of runs   0            -> ROM default path
      50% of runs   400..1000    -> programmed-fuse path

  --transport-timeout pins the value instead, which is what a test wants when
  it needs the shortest timeout deterministically rather than a random one.

HELD FIXED
----------
The fields below keep the base configuration's values: no OSS test observes
them, and the reference environment's randomization of them has no equivalent
here.

  rom_flip_endianness    ROM image endianness swap, paired with the matching
                         fuse; the fuse bit means nothing unless the ROM build
                         emits both endiannesses.
  sram_auto_zero_disable SRAM auto-zero on/off. Strap-controlled in the
                         OSS flow.
  rom_bank_swap          ROM bank swap select.
  mbist_enable /         MBIST enable and its timeout value. The OSS flow has
  mbist_timeout          no MBIST agent, so these have no observable effect
                         until one exists.
  ignore_mbist           DFT_IGNORE_ERROR at SMC_CONFIG[15] in the current layout.

A field is randomized only together with a test that can tell the two settings
apart: a randomized field nothing observes makes runs differ without making
them prove anything.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

# OCCP_TRANSPORT_TIMEOUT is its own 64-bit block; bits [31:0] hold the timeout
# value the boot ROM reads, bits [63:32] are reserved.
TIMEOUT_FIELD_BITS = 32

# Matches the reference environment's range, so a value programmed here means
# the same thing on both sides.
TIMEOUT_MIN = 400
TIMEOUT_MAX = 1000


def _pick_transport_timeout(rng: random.Random, forced: int | None) -> int:
    if forced is not None:
        return forced
    # Half the runs leave the fuse unprogrammed so the ROM's own default path
    # is exercised too -- see the module docstring.
    if rng.choice((True, False)):
        return 0
    return rng.randint(TIMEOUT_MIN, TIMEOUT_MAX)


def _rewrite(text: str, block: str, field: str, value: int) -> str:
    """Replace one `value = ...` line, scoped to [block.fields.field].

    Line-oriented: the output stays a readable diff against the base
    configuration, and comments and ordering survive. A TOML round-trip would
    discard both.
    """
    header = f"[{block}.fields.{field}]"
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != header:
            continue
        for follow in range(idx + 1, len(lines)):
            if re.match(r"\s*value\s*=", lines[follow]):
                indent = re.match(r"\s*", lines[follow]).group(0)
                lines[follow] = f"{indent}value = {value:#x}"
                return "\n".join(lines) + "\n"
        sys.exit(f"error: {header} has no 'value =' line")
    sys.exit(f"error: {header} not found in the base configuration")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", type=Path, help="base configuration TOML")
    parser.add_argument("--output_file", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--transport-timeout",
        type=int,
        default=None,
        help=f"pin OCCP_TRANSPORT_TIMEOUT to this value instead of drawing it "
        f"(0, or {TIMEOUT_MIN}..{TIMEOUT_MAX})",
    )
    args = parser.parse_args()

    if args.transport_timeout is not None:
        if not (0 <= args.transport_timeout < (1 << TIMEOUT_FIELD_BITS)):
            sys.exit("error: --transport-timeout does not fit in 32 bits")

    # Seeded with a string, not the bare integer: random.Random(n) for small n
    # leaves the first draws correlated across neighbouring seeds, and testlists
    # pin small seeds, so a bare-integer seed would bias the 50/50 branch above.
    rng = random.Random(f"smc-efuse-{args.seed}")
    timeout = _pick_transport_timeout(rng, args.transport_timeout)

    text = args.base.read_text()
    # OCCP_TRANSPORT_TIMEOUT is a dedicated 64-bit block; the timeout value sits
    # in bits [31:0] and is written directly as the 64-bit field value.
    text = _rewrite(text, "OCCP_TRANSPORT_TIMEOUT", "transport_timeout", timeout)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(text)
    print(
        f"seed={args.seed}: OCCP_TRANSPORT_TIMEOUT transport_timeout={timeout}"
        f"{' (ROM default path)' if timeout == 0 else ''} -> {args.output_file}"
    )


if __name__ == "__main__":
    main()

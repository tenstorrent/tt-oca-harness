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
RESERVED[1] -- the OCCP transport timeout.

  The boot ROM reads SMC_EFUSE_MAP_RESERVED_1 and treats it as the OCCP
  transport timeout in cycles, substituting a 10000-cycle default when the
  fuse reads 0 (bootrom/prod/lib/src/occp.c, bootrom/prod/drivers/src/
  smc_efuse.c). Both branches are worth exercising, so this script picks:

      50% of runs   0            -> ROM default path
      50% of runs   400..1000    -> programmed-fuse path

  --transport-timeout pins the value instead, which is what a test wants when
  it needs the shortest timeout deterministically rather than a random one.

NOT RANDOMIZED
--------------
The reference environment also varies the fields below; none is implemented
here, and no OSS test depends on them.

  rom_flip_endianness    ROM image endianness swap, paired with the matching
                         fuse. Needs the ROM build to emit both endiannesses
                         before the fuse bit means anything, so it is a
                         two-part change.
  sram_auto_zero_disable SRAM auto-zero on/off. Strap-controlled in the
                         OSS flow; the fuse path is untested.
  rom_bank_swap          ROM bank swap select.
  mbist_enable /         MBIST enable and its timeout value. The OSS flow has
  mbist_timeout          no MBIST agent, so these have no observable effect
                         until one exists.
  ignore_mbist           RESERVED[2] bit 0 in the reference layout.

  Adding one means: extend the argument list, rewrite the matching block in
  _rewrite(), and -- most importantly -- add a test that can tell the two
  settings apart. A randomized field nothing observes is worse than a fixed
  one, because it makes runs differ without making them prove anything.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

# RESERVED[1] is the second 32-bit word of the RESERVED block, so bits 63:32
# of the flattened 2080-bit value the schema declares.
RESERVED_WORD_BITS = 32
TRANSPORT_TIMEOUT_WORD = 1
TRANSPORT_TIMEOUT_LO = TRANSPORT_TIMEOUT_WORD * RESERVED_WORD_BITS

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
        help=f"pin RESERVED[1] to this value instead of drawing it "
        f"(0, or {TIMEOUT_MIN}..{TIMEOUT_MAX})",
    )
    args = parser.parse_args()

    if args.transport_timeout is not None:
        if not (0 <= args.transport_timeout < (1 << RESERVED_WORD_BITS)):
            sys.exit("error: --transport-timeout does not fit in 32 bits")

    # Seeded with a string, not the bare integer. random.Random(n) for small n
    # leaves the first few draws correlated across neighbouring seeds -- over
    # seeds 1..20 the branch below came out 12:8 instead of 10:10, and every
    # seed in 1..4 picked the same branch. Testlists pin small seeds, so that
    # bias would have made the "50% of runs" claim above false in practice.
    rng = random.Random(f"smc-efuse-{args.seed}")
    timeout = _pick_transport_timeout(rng, args.transport_timeout)

    text = args.base.read_text()
    # RESERVED[1] occupies bits 63:32 of the flattened RESERVED value; every
    # other reserved word stays 0, which is what the base configuration has.
    text = _rewrite(text, "RESERVED", "reserved_data", timeout << TRANSPORT_TIMEOUT_LO)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(text)
    print(
        f"seed={args.seed}: RESERVED[1] transport_timeout={timeout}"
        f"{' (ROM default path)' if timeout == 0 else ''} -> {args.output_file}"
    )


if __name__ == "__main__":
    main()

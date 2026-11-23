#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Derive a per-run SMC eFuse configuration from a base one.

Rewrites OCCP_TRANSPORT_TIMEOUT, and I2C_I3C_ID slots 6 and 7 under --i2c-ids, as a
deterministic function of --seed; --dft-ignore-error sets SMC_CONFIG.dft_ignore_error. Feed
the output to generate_efuse_preload.py.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

# The ROM reads only bits [31:0] of the 64-bit timeout field; bits [63:32] are reserved.
TIMEOUT_FIELD_BITS = 32

TIMEOUT_MIN = 400
TIMEOUT_MAX = 1000

I2C_I3C_ID_SLOT_BITS = 64
I2C_ID_SLOTS = (6, 7)

# The ROM falls back to address 0x55 for a slot outside this range.
I2C_ADDR_MIN = 0x08
I2C_ADDR_MAX = 0x77

SMC_CONFIG_DFT_IGNORE_ERROR = 1 << 15


def _pick_i2c_ids(rng: random.Random) -> tuple[int, int]:
    first = rng.randint(I2C_ADDR_MIN, I2C_ADDR_MAX)
    second = rng.randint(I2C_ADDR_MIN, I2C_ADDR_MAX - 1)
    # Equal addresses would make the two OCCP targets indistinguishable on a shared bus.
    if second >= first:
        second += 1
    return first, second


def _pick_transport_timeout(rng: random.Random, forced: int | None) -> int:
    if forced is not None:
        return forced
    if rng.choice((True, False)):
        return 0
    return rng.randint(TIMEOUT_MIN, TIMEOUT_MAX)


def _value_line(lines: list[str], block: str, field: str) -> int:
    header = f"[{block}.fields.{field}]"
    for idx, line in enumerate(lines):
        if line.strip() != header:
            continue
        for follow in range(idx + 1, len(lines)):
            if re.match(r"\s*value\s*=", lines[follow]):
                return follow
        sys.exit(f"error: {header} has no 'value =' line")
    sys.exit(f"error: {header} not found in the base configuration")


def _read(text: str, block: str, field: str) -> int:
    lines = text.splitlines()
    return int(lines[_value_line(lines, block, field)].split("=", 1)[1].strip(), 0)


# Edits text in place because a TOML round-trip would drop comments and key order.
def _rewrite(text: str, block: str, field: str, value: int) -> str:
    lines = text.splitlines()
    idx = _value_line(lines, block, field)
    indent = re.match(r"\s*", lines[idx]).group(0)
    lines[idx] = f"{indent}value = {value:#x}"
    return "\n".join(lines) + "\n"


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
    parser.add_argument(
        "--i2c-ids",
        action="store_true",
        help="program I2C_I3C_ID slots 6 and 7 with two distinct addresses the "
        "ROM accepts, instead of leaving them unprogrammed",
    )
    parser.add_argument(
        "--dft-ignore-error",
        type=int,
        choices=(0, 1),
        default=None,
        help="set SMC_CONFIG.dft_ignore_error (bit 15) to this value; without it the base "
        "configuration's value is kept",
    )
    args = parser.parse_args()

    if args.transport_timeout is not None:
        if not (0 <= args.transport_timeout < (1 << TIMEOUT_FIELD_BITS)):
            sys.exit("error: --transport-timeout does not fit in 32 bits")

    rng = random.Random(f"smc-efuse-{args.seed}")
    timeout = _pick_transport_timeout(rng, args.transport_timeout)

    text = args.base.read_text()
    text = _rewrite(text, "OCCP_TRANSPORT_TIMEOUT", "transport_timeout", timeout)

    i2c_note = ""
    if args.i2c_ids:
        i2c_ids = _pick_i2c_ids(rng)
        packed = 0
        for slot, addr in zip(I2C_ID_SLOTS, i2c_ids):
            packed |= addr << (slot * I2C_I3C_ID_SLOT_BITS)
        text = _rewrite(text, "I2C_I3C_ID", "interface_id", packed)
        i2c_note = (
            f", I2C_I3C_ID[{I2C_ID_SLOTS[0]}]={i2c_ids[0]:#04x} "
            f"I2C_I3C_ID[{I2C_ID_SLOTS[1]}]={i2c_ids[1]:#04x}"
        )

    dft_note = ""
    if args.dft_ignore_error is not None:
        config = _read(text, "SMC_CONFIG", "smc_config") & ~SMC_CONFIG_DFT_IGNORE_ERROR
        if args.dft_ignore_error:
            config |= SMC_CONFIG_DFT_IGNORE_ERROR
        text = _rewrite(text, "SMC_CONFIG", "smc_config", config)
        dft_note = f", SMC_CONFIG.dft_ignore_error={args.dft_ignore_error}"

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(text)
    print(
        f"seed={args.seed}: OCCP_TRANSPORT_TIMEOUT transport_timeout={timeout}"
        f"{' (ROM default path)' if timeout == 0 else ''}"
        f"{i2c_note}{dft_note} -> {args.output_file}"
    )


if __name__ == "__main__":
    main()

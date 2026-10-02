#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write an SMC eFuse configuration that fills every schema field to full width.

Usage:

    pattern_efuse.py --pattern {alt55,altaa,random} [--seed N] --output_file OUT.toml

Feed the output to generate_efuse_preload.py to get the hex image.

Patterns:

* ``alt55`` -- every field holds 0x5555... over its whole width.
* ``altaa`` -- every field holds 0xAAAA... over its whole width.
* ``random`` -- every field holds a value drawn uniformly over its whole width
  from ``--seed`` (required for this pattern); the same seed gives the same file.

Lock flags. generate_efuse_preload.py derives LOCKS from each block's
``write_locked`` / ``read_locked`` flags, slot ``i`` being the ``i``-th block
after LOCKS in schema order, write lock at LOCKS bit ``2i`` and read lock at bit
``2i+1``. ``read_locked`` is always ``"False"`` so every word of the image stays
readable through the SMC_EFUSE_MAP window. ``write_locked`` is never clear on
every block, so LOCKS is never zero:

* ``alt55`` -- bit ``2i`` of 0x5555...: every block is write-locked.
* ``altaa`` -- bit ``2i`` of 0x4444...: the odd slots are write-locked, since
  0xAAAA... has no even bit set.
* ``random`` -- a seeded subset of the blocks, never empty and never all of them.

The schema carries one lock pair per block, so SPARE has the single slot 4 here;
slots 5 and above stay clear in every image this tool writes.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    import tomli as tomllib  # type: ignore[no-redef]

SCHEMA_PATH = Path(__file__).resolve().parent / "efuse_schema.toml"

PATTERNS = ("alt55", "altaa", "random")
_NIBBLE = {"alt55": 0x5, "altaa": 0xA}
_LOCK_NIBBLE = {"alt55": 0x5, "altaa": 0x4}


def _repeat_nibble(nibble: int, width: int) -> int:
    value = 0
    for _ in range((width + 3) // 4):
        value = (value << 4) | nibble
    return value & ((1 << width) - 1)


def _field_width(bits: str) -> int:
    hi, lo = (int(x) for x in bits.split(":"))
    return hi - lo + 1


def build_config(schema: dict, pattern: str, seed: int | None) -> str:
    """Return the configuration TOML text for ``pattern``."""
    rng = random.Random(f"smc-efuse-pattern-{seed}") if pattern == "random" else None
    lines = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "#",
        f"# Written by pattern_efuse.py --pattern {pattern}"
        + (f" --seed {seed}" if seed is not None else "")
        + "; read by generate_efuse_preload.py.",
    ]
    blocks = [b for b in schema if b != "LOCKS"]
    if rng is not None:
        locked_slots = set(rng.sample(range(len(blocks)), rng.randint(1, len(blocks) - 1)))
    else:
        lock_word = _repeat_nibble(_LOCK_NIBBLE[pattern], 2 * len(blocks))
        locked_slots = {i for i in range(len(blocks)) if (lock_word >> (2 * i)) & 1}
    for slot, block in enumerate(blocks):
        block_schema = schema[block]
        write_locked = slot in locked_slots
        lines += [
            "",
            f"[{block}]",
            f'    write_locked = "{write_locked}"',
            '    read_locked = "False"',
        ]
        for field, field_schema in block_schema["fields"].items():
            width = _field_width(field_schema["bits"])
            if rng is not None:
                value = rng.getrandbits(width)
            else:
                value = _repeat_nibble(_NIBBLE[pattern], width)
            lines += [f"    [{block}.fields.{field}]", f"    value = {value:#x}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pattern", choices=PATTERNS, required=True)
    parser.add_argument("--seed", type=int, default=None, help="required for --pattern random")
    parser.add_argument("--output_file", type=Path, required=True)
    args = parser.parse_args()
    if args.pattern == "random" and args.seed is None:
        sys.exit("error: --pattern random needs --seed")

    with SCHEMA_PATH.open("rb") as handle:
        schema = tomllib.load(handle)
    text = build_config(schema, args.pattern, args.seed if args.pattern == "random" else None)
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(text)
    print(f"pattern={args.pattern} seed={args.seed} -> {args.output_file}")


if __name__ == "__main__":
    main()

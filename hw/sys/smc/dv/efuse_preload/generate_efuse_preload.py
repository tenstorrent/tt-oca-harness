#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Turn an SMC eFuse configuration TOML into a simulator preload image.

Blocks from efuse_schema.toml are concatenated in schema order, LSB first, into one
8192-bit image; hex output is one 32-bit word per line for $readmemh.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    import tomli as tomllib  # type: ignore[no-redef]

# Must match smc_efuse_pkg::ShadowRegBits.
EFUSE_SIZE_BITS = 8192
EFUSE_WORD_SIZE_BITS = 32

SCHEMA_PATH = Path(__file__).resolve().parent / "efuse_schema.toml"


def _load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        sys.exit(f"error: {path} not found")
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"error: {path} is not valid TOML: {exc}")


def _coerce_int(value, where: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
        except ValueError:
            pass
    sys.exit(f"error: {where}: value must be an integer or a '0x...' string")


def build_image(config: dict, schema: dict) -> int:
    if "LOCKS" not in schema:
        sys.exit("error: schema has no LOCKS block")

    image = 0
    offset = 0
    locks = 0
    lock_index = 0

    for block, block_schema in schema.items():
        width = block_schema["regwidth"]

        if block == "LOCKS":
            # Built from the blocks' lock flags; any LOCKS value in the configuration is ignored.
            lock_offset, lock_width = offset, width
            offset += width
            continue

        if block not in config:
            sys.exit(f"error: configuration is missing block '{block}'")
        entry = config[block]
        for key in ("write_locked", "read_locked", "fields"):
            if key not in entry:
                sys.exit(f"error: block '{block}' is missing '{key}'")

        if str(entry["write_locked"]).lower() == "true":
            locks |= 1 << (lock_index * 2)
        if str(entry["read_locked"]).lower() == "true":
            locks |= 1 << (lock_index * 2 + 1)
        lock_index += 1

        block_value = 0
        for field, field_cfg in entry["fields"].items():
            if field not in block_schema["fields"]:
                sys.exit(f"error: '{field}' is not a field of '{block}' in the schema")
            hi, lo = (int(x) for x in block_schema["fields"][field]["bits"].split(":"))
            span = hi - lo + 1
            value = _coerce_int(field_cfg.get("value", 0), f"{block}.{field}")
            if value < 0:
                sys.exit(f"error: {block}.{field}: value must not be negative")
            if value >= (1 << span):
                sys.exit(f"error: {block}.{field}: value does not fit in {span} bits")
            block_value |= value << lo

        image |= block_value << offset
        offset += width

    if offset != EFUSE_SIZE_BITS:
        sys.exit(
            f"error: schema totals {offset} bits, expected {EFUSE_SIZE_BITS} "
            "(smc_efuse_pkg::ShadowRegBits). Schema and "
            "smc_efuse_map.rdl have diverged."
        )
    if locks >= (1 << lock_width):
        sys.exit("error: more lockable blocks than the LOCKS field can address")
    image |= locks << lock_offset
    return image


# Every image reader skips `//` lines; a header in any other syntax is read as data.
_SPDX_HEADER = (
    "// SPDX-License-Identifier: Apache-2.0",
    "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
)


def write_image(image: int, path: Path, notation: str) -> None:
    lines = list(_SPDX_HEADER)
    if notation == "hex":
        for word in range(EFUSE_SIZE_BITS // EFUSE_WORD_SIZE_BITS):
            shift = word * EFUSE_WORD_SIZE_BITS
            lines.append(f"{(image >> shift) & 0xFFFF_FFFF:08x}")
    elif notation == "binary":
        lines.extend(str((image >> bit) & 1) for bit in range(EFUSE_SIZE_BITS))
    else:
        sys.exit(f"error: unknown notation '{notation}'")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines) - len(_SPDX_HEADER)} {notation} entries to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path, help="eFuse configuration TOML")
    parser.add_argument("--output_file", type=Path, required=True, help="image to write")
    parser.add_argument(
        "--notation",
        choices=("hex", "binary"),
        default="hex",
        help="hex: one 32-bit word per line (default). binary: one bit per line.",
    )
    args = parser.parse_args()

    schema = _load_toml(SCHEMA_PATH)
    config = _load_toml(args.config)
    write_image(build_image(config, schema), args.output_file, args.notation)


if __name__ == "__main__":
    main()

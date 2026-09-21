#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Check register addresses cited in the SEP docs against the register map.

Two stages, because trusting the generated header alone leaves a gap:

  1. RDL -> generated header. sep_addr.h is generated from the .rdl sources; if
     regeneration has not been run, every later check validates against a stale
     map. This stage catches that.
  2. Generated header -> docs. Every `NAME` ... `0x10xxxxxx` pair in the SEP
     AsciiDoc chapters is compared with the map.

Why this exists: inserting LOCKS_SPARE (32-bit @0x8) into sep_efuse_map.rdl
shifted every eFuse register after LOCKS by 4. rom.adoc's fuse table kept the
pre-insertion addresses, so each documented address named the *previous*
register -- the documented BL1_VERSION address was CHIPLET_PUBK_REVOKE's. A spec
address that is one slot low reads the neighbouring fuse.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
# rom.adoc lives with the ROM it documents, so the doc set is two directories.
# Both are scanned: rom.adoc cites more registers than every other SEP doc
# combined, and this check exists because a documented address once named the
# wrong register.
DOC_DIRS = (
    ROOT / "hw/sys/sep/doc",
    ROOT / "hw/sys/sep/bootrom/prod/doc",
)
HEADER = ROOT / "hw/sys/sep/regs/gen/c/sep_addr.h"
RDL_DIR = ROOT / "hw/sys/sep/regs/blocks"

# Block instance -> its base address symbol in sep_addr.h. Extend as needed.
RDL_BLOCKS = {"sep_efuse_map": "SEP_EFUSE_MAP"}

# Prefixes stripped so doc shorthand (`LC_STATE`) matches the full symbol
# (SEP_EFUSE_MAP_LC_STATE).
PREFIXES = (
    "SEP_EFUSE_MAP_",
    "SEP_CPU_CTRL_",
    "SEP_RESET_CTRL_",
    "SEP_SCRATCH_",
    "SEP_LIFECYCLE_CTRL_",
)


def load_header():
    text = HEADER.read_text()
    return {
        m.group(1): int(m.group(2), 16)
        for m in re.finditer(
            r"#define\s+SEP_TOP_([A-Z0-9_]+)_BASE_ADDR\s+(0x[0-9A-Fa-f]+)", text
        )
    }


def check_rdl_vs_header(gen):
    """Stage 1: every RDL instantiation matches the generated header."""
    problems = 0
    checked = 0
    for block, prefix in RDL_BLOCKS.items():
        rdl = RDL_DIR / block / f"{block}.rdl"
        if not rdl.exists():
            print(f"  ! {rdl} not found; skipping RDL cross-check")
            continue
        base = gen.get(prefix)
        if base is None:
            print(f"  ! no base address for {prefix}; skipping")
            continue
        # `TYPE  INSTANCE  @0xOFFSET;`
        for m in re.finditer(
            r"^\s+[A-Za-z][A-Za-z0-9_]*\s+([A-Z][A-Z0-9_]*)\s*@\s*(0x[0-9A-Fa-f]+)\s*;",
            rdl.read_text(),
            re.M,
        ):
            inst, off = m.group(1), int(m.group(2), 16)
            sym = f"{prefix}_{inst}"
            if sym not in gen:
                continue
            checked += 1
            if gen[sym] != base + off:
                problems += 1
                print(
                    f"  STALE HEADER  {sym}: rdl @{off:#x} -> {base + off:#010x}, "
                    f"header {gen[sym]:#010x}"
                )
    print(
        f"stage 1: {checked} RDL instantiations checked against sep_addr.h, {problems} out of sync"
    )
    return problems


def check_docs(gen):
    """Stage 2: addresses cited in the docs match the generated header."""
    short = dict(gen)
    for k, v in gen.items():
        for pre in PREFIXES:
            if k.startswith(pre):
                short.setdefault(k[len(pre) :], v)

    total = problems = 0
    for f in sorted(f for d in DOC_DIRS for f in d.glob("*.adoc")):
        for i, line in enumerate(f.read_text().split("\n"), 1):
            if not re.search(r"0x10[0-9A-Fa-f]{6}", line):
                continue
            names = re.findall(r"`?\b([A-Z][A-Z0-9_]{2,})\b`?", line)
            addrs = re.findall(r"`?(0x10[0-9A-Fa-f]{6})`?", line)
            for name, addr in zip(names, addrs):
                if name not in short:
                    continue
                total += 1
                if short[name] != int(addr, 16):
                    problems += 1
                    print(f"  MISMATCH  {f.name}:{i}  {name}: doc {addr}, map {short[name]:#010x}")
    print(f"stage 2: {total} name+address pairs in the docs, {problems} stale")
    return problems


def main():
    gen = load_header()
    print(f"{len(gen)} base addresses in {HEADER.relative_to(ROOT)}\n")
    problems = check_rdl_vs_header(gen) + check_docs(gen)
    if problems == 0:
        print("\nOK: RDL, generated header and docs all agree")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

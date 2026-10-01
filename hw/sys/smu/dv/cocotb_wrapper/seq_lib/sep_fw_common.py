# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared helpers for booting real SEP DV firmware under the OSS SMU wrapper.

The SEP DV images in hw/sys/sep/dv/fw/tests report their verdict in one of two
ways, and both are the firmware's own judgement rather than a TB inference:

  * terminal loops -- the image parks in a named `*_pass_loop` / `*_fail_loop`,
    and the run is classified by which loop PC the SEP settles on;
  * the STDOUT mailbox handshake -- TEST_MAGIC0 then TEST_MAGIC_PASS/FAIL.

This module carries the pieces both styles need: symbol-table lookup (so a
contract survives a firmware relink) and PC attribution for diagnosis.
"""

from __future__ import annotations

import re

_NM_LINE = re.compile(r"^([0-9a-fA-F]+)\s+(\S)\s+(\S+)\s*$")


def load_syms(path: str, *, include_weak: bool = False) -> list[tuple[int, str]]:
    """Parse an `nm -B -n` dump into a sorted (addr, name) list of text symbols.

    Data and absolute symbols are dropped: keeping them would mis-attribute PCs
    to whichever constant happened to sit below the address. ``include_weak``
    adds the W/w entries: picolibc exports several weak entry points that are
    the only name a PC inside them has, which matters for backtraces but not
    for the exact-name contract lookups.
    """
    types = ("T", "t", "W", "w") if include_weak else ("T", "t")
    out: list[tuple[int, str]] = []
    try:
        with open(path, "r", encoding="ascii", errors="replace") as stream:
            for line in stream:
                match = _NM_LINE.match(line.strip())
                if match and match.group(2) in types:
                    out.append((int(match.group(1), 16), match.group(3)))
    except OSError:
        return []
    return sorted(out)


def addr_of(syms: list[tuple[int, str]], name: str) -> int:
    """Exact address of `name`, or raise -- a missing contract symbol is fatal."""
    for addr, sym in syms:
        if sym == name:
            return addr
    raise AssertionError(
        f"symbol {name!r} not in the firmware symbol table; "
        "the image and the test contract are out of step"
    )


def sym_for(syms: list[tuple[int, str]], pc: int) -> str:
    """Nearest preceding text symbol plus offset, for PC attribution."""
    best = None
    for addr, name in syms:
        if addr <= pc:
            best = (addr, name)
        else:
            break
    if best is None:
        return "?"
    return f"{best[1]}+0x{pc - best[0]:x}"


def format_pc_profile(
    syms: list[tuple[int, str]], pc_hist, traces: int, top: int = 12
) -> list[str]:
    """Render the hottest PCs with symbol attribution.

    This is what separates "the firmware never got there" from "it got there and
    the access failed": a hot trap handler or a hot crt0 `_finish` means the
    image aborted early, whatever the top-level symptom looks like.
    """
    if not pc_hist:
        return ["SEP PC profile: no retirements observed"]
    lines = [f"SEP PC profile (hottest {top} of {len(pc_hist)} distinct, {traces} retires):"]
    for pc, count in pc_hist.most_common(top):
        pct = 100.0 * count / max(traces, 1)
        lines.append(f"  0x{pc:08x}  {count:7d}  {pct:5.1f}%  {sym_for(syms, pc)}")
    lines.append(f"SEP PC span: 0x{min(pc_hist):08x} .. 0x{max(pc_hist):08x}")
    return lines


def sep_boot_order_from_hw(dut, rd) -> tuple[int | None, bool, bool]:
    """Return the SEP boot facts the wrapper latched from its first cycle.

    ``(first_pc, boot_rom_seen, iccm_seen)``: the first retired PC (None while
    the SEP has not retired anything) and whether a retirement fell in the
    boot-ROM and ICCM windows. A sequence that starts sampling the trace only
    after bring-up seeds its own bookkeeping from these, since the SEP can
    boot and reach its ICCM entry before that point.
    """
    first_pc = None
    if rd(dut.sep_first_pc_valid_o, "sep_first_pc_valid_o"):
        first_pc = rd(dut.sep_first_pc_o, "sep_first_pc_o") & 0xFFFF_FFFF
    return (
        first_pc,
        bool(rd(dut.sep_boot_rom_fetch_seen_o, "sep_boot_rom_fetch_seen_o")),
        bool(rd(dut.sep_iccm_fetch_seen_o, "sep_iccm_fetch_seen_o")),
    )

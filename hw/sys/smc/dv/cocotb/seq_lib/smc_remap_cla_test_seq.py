# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ALIAS_REMAP translation + MMODE_REMAP/ALIAS reset sweep + CLA
(TC_SMC_P1CG_16/17/18).

Three surfaces, each with a fail-capable expectation:

* **ALIAS_REMAP address translation** -- entry 0 is programmed
  (``REGION_START`` / ``REGION_END`` / ``REGION_ATTRS.offset|valid``) and a JTAG
  AXI write issued at the source address is observed **landing at the translated
  address** on the SYS_OUT responder (``tb_output_axi_last_addr``). The
  un-programmed identity case is the same-run positive control and the
  entry-disabled re-read is the same-run negative control, so "the remap moved
  the access" is distinguishable from "nothing happened".
* **SMC_MMODE_REMAP_0..7 / SMC_ALIAS_REMAP_0..7** -- per-entry decode *and* the
  RDL reset content (``expected=`` on every read, not merely an OKAY response).
* **SMC_CLA_REG** -- the Cluster Local Aggregator window: an allow leg on real
  CLA registers (RDL reset values + a scratch write/readback) paired with the
  in-window-hole leg. Unallocated offsets inside the map complete OKAY with
  data 0; the five non-zero reset rows and the scratch write/readback are
  what distinguish a live aperture from a hole.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import _field_mask, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_responder_counts,
)

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_END_REG_DEFAULT,
    REMAP_REGION_REGION_START_REG_DEFAULT,
    SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_0__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_1__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_1__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_2__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_2__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_3__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_3__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_4__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_4__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_5__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_5__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_6__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_6__REGION_REGION_START_REG_ADDR,
    SMC_ALIAS_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_7__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_7__REGION_REGION_START_REG_ADDR,
    SMC_CLA_CLA_0__SCRATCH_REG_ADDR,
    SMC_CLA_DST_0__TRDSTIMPL_REG_ADDR,
    SMC_CLA_DST_SINK_TRDSTRAMIMPL_REG_ADDR,
    SMC_CLA_REG_MAP_BASE_ADDR,
    SMC_MMODE_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
    DFD_CLA_Scratch_REG_DEFAULT,
    DFD_DST_SINK_Trdstramimpl_REG_DEFAULT,
    DFD_DST_Trdstimpl_REG_DEFAULT,
)

# Per-entry ATTRS addresses from the generated map. Reset value comes from the
# same generated map (output_remap.rdl offset[55:0] = 0x0), never hand-copied.
XVISOR_REMAP_ENTRIES = 8
# Inside the 56-bit `offset` field; bits [63:56] stay 0.
XVISOR_PROBE = 0x00A5_A55A_5AC3_C33C

MMODE_REMAP_ATTRS_ADDRS = (
    SMC_MMODE_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
)

# Per-entry START/END/ATTRS from the generated map, each paired with the
# generated RDL reset value for that register type (alias_remap.rdl:
# start_addr/end_addr/offset[55:12] = 0x0, cacheable/valid = 0x0).
ALIAS_REMAP_REGS = (
    (
        "ALIAS_REMAP_0_START",
        SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_0_END",
        SMC_ALIAS_REMAP_0__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_0_ATTRS",
        SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_1_START",
        SMC_ALIAS_REMAP_1__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_1_END",
        SMC_ALIAS_REMAP_1__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_1_ATTRS",
        SMC_ALIAS_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_2_START",
        SMC_ALIAS_REMAP_2__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_2_END",
        SMC_ALIAS_REMAP_2__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_2_ATTRS",
        SMC_ALIAS_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_3_START",
        SMC_ALIAS_REMAP_3__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_3_END",
        SMC_ALIAS_REMAP_3__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_3_ATTRS",
        SMC_ALIAS_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_4_START",
        SMC_ALIAS_REMAP_4__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_4_END",
        SMC_ALIAS_REMAP_4__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_4_ATTRS",
        SMC_ALIAS_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_5_START",
        SMC_ALIAS_REMAP_5__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_5_END",
        SMC_ALIAS_REMAP_5__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_5_ATTRS",
        SMC_ALIAS_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_6_START",
        SMC_ALIAS_REMAP_6__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_6_END",
        SMC_ALIAS_REMAP_6__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_6_ATTRS",
        SMC_ALIAS_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_7_START",
        SMC_ALIAS_REMAP_7__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_7_END",
        SMC_ALIAS_REMAP_7__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS_REMAP_7_ATTRS",
        SMC_ALIAS_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
)

# --- CLA aperture --------------------------------------------------------
# Allow leg: real CLA registers with their generated RDL reset values. Both are
# discriminating: 0x01003901 and 0x41010101 are values no error slave and no
# unmapped read can produce. Both are `regwidth = 32`, so both are read at 4.
CLA_RESET_READS = (
    (
        "CLA_TRDSTRAMIMPL",
        SMC_CLA_DST_SINK_TRDSTRAMIMPL_REG_ADDR,
        DFD_DST_SINK_Trdstramimpl_REG_DEFAULT,
        4,
    ),
    ("CLA_TRDSTIMPL", SMC_CLA_DST_0__TRDSTIMPL_REG_ADDR, DFD_DST_Trdstimpl_REG_DEFAULT, 4),
)
# dfd_cla.rdl `Scratch @ 0xFF8`: "Additional scratch register for DV", sw=rw,
# reset 0x0. Written and read back so the allow leg proves a live register, not
# just a decodable address.
CLA_SCRATCH_PATTERN = 0xA5A5_5A5A_C3C3_3C3C


# Registers are keyed BLOCK.Name: smc_cla.rdl instantiates four sub-blocks
# (dst_sink, funnel, cla[], dst[]) and a bare register name is not unique across
# them -- ScratchLo/ScratchHi appear in three.

# CLA registers whose value the HARDWARE drives (at least one field with
# `hw = w` or `hw = rw` in the vendored block RDLs under
# vendor/tenstorrent/tt-hw-debug/overlay/regs/dfd/regs/include/). Their read
# value is not required to equal the RDL reset once time has advanced (the
# free-running `CDbgClaTimestamp` counter reads non-zero against a generated
# reset of 0x0), so they are EXCLUDED from the reset sweep. Derived from the
# RDL, 55 of the 137 registers; the remaining 82 are `hw = r` software-owned
# config/scratch and are the ones the sweep can hold to a reset.
CLA_HW_DRIVEN = (
    "CLA.CDbgClaCounter0Cfg",
    "CLA.CDbgClaCounter1Cfg",
    "CLA.CDbgClaCounter2Cfg",
    "CLA.CDbgClaCounter3Cfg",
    "CLA.CDbgClaCtrlStatus",
    "CLA.CDbgClaTimestamp",
    "CLA.CDbgClaTimestampConfig",
    "CLA.CDbgEapStatus",
    "CLA.CDbgLfsr",
    "CLA.CDbgSignalSnapshotNode0Eap0Hi",
    "CLA.CDbgSignalSnapshotNode0Eap0Lo",
    "CLA.CDbgSignalSnapshotNode0Eap1Hi",
    "CLA.CDbgSignalSnapshotNode0Eap1Lo",
    "CLA.CDbgSignalSnapshotNode0Eap2Hi",
    "CLA.CDbgSignalSnapshotNode0Eap2Lo",
    "CLA.CDbgSignalSnapshotNode0Eap3Hi",
    "CLA.CDbgSignalSnapshotNode0Eap3Lo",
    "CLA.CDbgSignalSnapshotNode1Eap0Hi",
    "CLA.CDbgSignalSnapshotNode1Eap0Lo",
    "CLA.CDbgSignalSnapshotNode1Eap1Hi",
    "CLA.CDbgSignalSnapshotNode1Eap1Lo",
    "CLA.CDbgSignalSnapshotNode1Eap2Hi",
    "CLA.CDbgSignalSnapshotNode1Eap2Lo",
    "CLA.CDbgSignalSnapshotNode1Eap3Hi",
    "CLA.CDbgSignalSnapshotNode1Eap3Lo",
    "CLA.CDbgSignalSnapshotNode2Eap0Hi",
    "CLA.CDbgSignalSnapshotNode2Eap0Lo",
    "CLA.CDbgSignalSnapshotNode2Eap1Hi",
    "CLA.CDbgSignalSnapshotNode2Eap1Lo",
    "CLA.CDbgSignalSnapshotNode2Eap2Hi",
    "CLA.CDbgSignalSnapshotNode2Eap2Lo",
    "CLA.CDbgSignalSnapshotNode2Eap3Hi",
    "CLA.CDbgSignalSnapshotNode2Eap3Lo",
    "CLA.CDbgSignalSnapshotNode3Eap0Hi",
    "CLA.CDbgSignalSnapshotNode3Eap0Lo",
    "CLA.CDbgSignalSnapshotNode3Eap1Hi",
    "CLA.CDbgSignalSnapshotNode3Eap1Lo",
    "CLA.CDbgSignalSnapshotNode3Eap2Hi",
    "CLA.CDbgSignalSnapshotNode3Eap2Lo",
    "CLA.CDbgSignalSnapshotNode3Eap3Hi",
    "CLA.CDbgSignalSnapshotNode3Eap3Lo",
    "CLA.CDbgTimestampCapture",
    "DST.Trdstcontrol",
    "DST_SINK.Trdstramcontrol",
    "DST_SINK.Trdstramdata",
    "DST_SINK.Trdstramlimithigh",
    "DST_SINK.Trdstramlimitlow",
    "DST_SINK.Trdstramrphigh",
    "DST_SINK.Trdstramrplow",
    "DST_SINK.Trdstramstarthigh",
    "DST_SINK.Trdstramstartlow",
    "DST_SINK.Trdstramwphigh",
    "DST_SINK.Trdstramwplow",
    "FUNNEL.Trfunnelcontrol",
    "FUNNEL.Trfunneldisinput",
)

# Registers declared `regwidth = 32` (from the generated JSON model's `regsize`).
# The aperture MIXES 32- and 64-bit registers (113 are 64-bit, 24 are 32-bit);
# an 8-byte read of a 32-bit register spans past it and answers non-OKAY, so
# each row is read at its declared width.
CLA_REG32 = (
    "DST.CDbgDebugTraceCfg",
    "DST.ScratchHi",
    "DST.ScratchLo",
    "DST.Trdstcontrol",
    "DST.Trdstimpl",
    "DST.Trdstinstfeatures",
    "DST_SINK.ScratchHi",
    "DST_SINK.ScratchLo",
    "DST_SINK.Trdstramcontrol",
    "DST_SINK.Trdstramdata",
    "DST_SINK.Trdstramimpl",
    "DST_SINK.Trdstramlimithigh",
    "DST_SINK.Trdstramlimitlow",
    "DST_SINK.Trdstramrphigh",
    "DST_SINK.Trdstramrplow",
    "DST_SINK.Trdstramstarthigh",
    "DST_SINK.Trdstramstartlow",
    "DST_SINK.Trdstramwphigh",
    "DST_SINK.Trdstramwplow",
    "FUNNEL.ScratchHi",
    "FUNNEL.ScratchLo",
    "FUNNEL.Trfunnelcontrol",
    "FUNNEL.Trfunneldisinput",
    "FUNNEL.Trfunnelimpl",
)


# (address-symbol instance prefix, short block key, reset-symbol block type).
# `DST_0__` and `DST_SINK_` are distinct prefixes, so the order here is not
# load-bearing.
_CLA_BLOCKS = (
    ("CLA_0__", "CLA", "DFD_CLA"),
    ("DST_0__", "DST", "DFD_DST"),
    ("DST_SINK_", "DST_SINK", "DFD_DST_SINK"),
    ("FUNNEL_", "FUNNEL", "DFD_FUNNEL"),
)


def _cla_reset_sweep() -> tuple[tuple[str, int, int, int], ...]:
    """Every CLA register with its generated reset value, from generated symbols.

    Built by introspecting ``smc_reg`` at import time rather than transcribing a
    137-row table, so the expectations cannot drift from the generated register
    map ([ADDRESS-FROM-AUTHORITATIVE-MAP]).

    A reset compare is a real check here: of the 82 software-owned rows the
    sweep keeps, 5 have NON-ZERO resets (``Trdstimpl`` 0x41010101,
    ``Trdstinstfeatures`` 0x40000000, ``Trdstramimpl`` 0x01003901,
    ``CDbgDebugTraceCfg`` 0x00102810, ``Trfunnelimpl`` 0x0801) -- values no
    error slave and no unmapped read can fabricate. In-window holes also
    complete OKAY with data 0, so the 77 zero-reset rows are not distinguished
    from a hole by response; the five non-zero rows and the scratch
    write/readback carry that discrimination.

    Reading the whole aperture is side-effect free: the vendored block RDLs
    carry no ``onread`` property on any field.
    """
    import smc_reg as _r

    defaults = {c[: -len("_REG_DEFAULT")].upper(): c for c in dir(_r) if c.endswith("_REG_DEFAULT")}
    hw_driven = frozenset(CLA_HW_DRIVEN)
    reg32 = frozenset(CLA_REG32)
    out = []
    for sym in dir(_r):
        if not sym.startswith("SMC_CLA_") or not sym.endswith("_REG_ADDR"):
            continue
        stem = sym[len("SMC_CLA_") : -len("_REG_ADDR")]
        # The address symbol carries the sub-block INSTANCE prefix (`CLA_0__`)
        # while the reset symbol carries the block TYPE (`DFD_CLA_`), so the two
        # halves of a row are bridged by name, case-insensitively.
        for prefix, short, blocktype in _CLA_BLOCKS:
            if stem.startswith(prefix):
                break
        else:
            continue
        default_sym = defaults.get(f"{blocktype}_{stem[len(prefix) :]}".upper())
        if default_sym is None:
            continue
        qual = f"{short}.{default_sym[len(blocktype) + 1 : -len('_REG_DEFAULT')]}"
        if qual in hw_driven:
            continue
        length = 4 if qual in reg32 else 8
        row = f"CLA_SWEEP_{qual.replace('.', '_')}"
        out.append((row, getattr(_r, sym), getattr(_r, default_sym), length))
    out.sort(key=lambda row: row[1])
    return tuple(out)


CLA_RESET_SWEEP = _cla_reset_sweep()
# Non-zero-reset rows carry the discrimination; asserted below so a generated
# map that lost them cannot silently turn the sweep into 82 reads of zero.
CLA_SWEEP_NONZERO = tuple(r for r in CLA_RESET_SWEEP if r[2] != 0)


def _cla_unmapped_probes(count: int = 3) -> tuple[tuple[str, int], ...]:
    """In-window offsets that map to no register, taken from the generated map.

    The aperture is not densely packed, and which offsets are holes moves every
    time the map is rebuilt. Derived here so the hole leg cannot go stale into
    a silent pass. Each hole completes OKAY with data 0.
    """
    import smc_reg as _r

    mapped = {
        getattr(_r, n) for n in dir(_r) if n.startswith("SMC_CLA_") and n.endswith("_REG_ADDR")
    }
    assert mapped, (
        "generated smc_reg has no SMC_CLA_*_REG_ADDR symbols; the hole-leg "
        "derivation would treat every offset as a hole"
    )
    out = []
    for off in range(0, 0x3000, 4):
        addr = SMC_CLA_REG_MAP_BASE_ADDR + off
        if addr in mapped:
            continue
        # A 4-byte hole inside a 64-bit register's span is still decoded.
        if (addr - 4) in mapped or (addr - 8) in mapped:
            continue
        out.append((f"CLA_WINDOW_OFF{off:X}", addr))
        if len(out) == count:
            break
    assert len(out) == count, (
        f"only found {len(out)} unmapped in-window offsets; the hole leg needs "
        f"{count} to show an unallocated in-window offset completes OKAY+0"
    )
    return tuple(out)


CLA_UNMAPPED_PROBES = _cla_unmapped_probes()

# --- ALIAS_REMAP translation ---------------------------------------------
# Field positions come from the generated alias_remap header, never hand-packed.
_ALIAS_REMAP_H = (
    Path(__file__).resolve().parents[6]
    / "hw"
    / "ip"
    / "axi_alias_remap"
    / "regs"
    / "gen"
    / "c"
    / "alias_remap.h"
)
ATTRS_VALID_BM = _field_mask(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__VALID_bm")
ATTRS_OFFSET_BP = _field_mask(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bp")
START_ADDR_BP = _field_mask(
    _ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_START__START_ADDR_bp"
)

# Region granularity is 1 << START_ADDR_BP bytes (alias_remap.rdl: the low
# START_ADDR_BP address bits are "preserved unchanged").
_PAGE = 1 << START_ADDR_BP
# Two pages inside the SYS_OUT fabric window served by the TB SYS_OUT
# responder (same window smc_output_filter_remap_security_test uses).
REMAP_SRC = 0x0200_2000
REMAP_DST = REMAP_SRC + _PAGE
# alias_remap.rdl REGION_ATTRS.offset: "added to bits [55:12] of the input
# address when it falls within the remap region", so one page of offset moves
# the access from REMAP_SRC to REMAP_DST.
REMAP_OFFSET_PAGES = 1
REMAP_ATTRS_ON = ATTRS_VALID_BM | (REMAP_OFFSET_PAGES << ATTRS_OFFSET_BP)

IDENTITY_DATA = 0x1111_2222_3333_4444
REMAPPED_DATA = 0xAAAA_BBBB_CCCC_DDDD

ALIAS0_START = SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR
ALIAS0_END = SMC_ALIAS_REMAP_0__REGION_REGION_END_REG_ADDR
ALIAS0_ATTRS = SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR

# CSR accesses this sequence issues, written out per phase so the number is a
# statement of the stimulus rather than a restatement of the loops below.
_RESET_SWEEP_ACCESSES = 8 + 24 + 8 + 4  # MMODE + ALIAS + XVISOR resets + XVISOR probe
# resets + scratch wr/rd/restore + in-window holes + the full-aperture reset
# sweep. The sweep length is taken from the table built off the generated
# register map (82 software-owned rows of the 137 in the generated CLA map);
# it is guarded by an explicit `len(CLA_RESET_SWEEP) >= 82` assert in
# `_cla_window`, so a generated map that lost rows fails loudly instead of
# silently lowering this floor.
_CLA_ACCESSES = 2 + 4 + 3 + len(CLA_RESET_SWEEP)
_REMAP_ACCESSES = 6 + 6 + 2 + 4  # filters + program/readback + off + restore
_EXPECTED_ACCESSES = _RESET_SWEEP_ACCESSES + _CLA_ACCESSES + _REMAP_ACCESSES
# JTAG-AXI (non-CSR) accesses: identity write+read, remapped write, read at the
# landing site, read back at the source with the entry disabled.
EXPECTED_JTAG_ACCESSES = 5

# Reads on this path that carry an `expected` and therefore book a scoreboard
# value check. Written out per group rather than derived from the tables the
# body walks, so it cannot shrink together with the stimulus.
_EXPECTED_VALUE_CHECKS = (
    32  # 8 MMODE ATTRS + 24 ALIAS START/END/ATTRS reset values
    + 8  # 8 XVISOR ATTRS reset values
    + 2  # XVISOR probe readback + restore readback
    + 2  # CLA Trdstramimpl + Trdstimpl reset values
    + 2  # CLA Scratch write readback + restore readback
    + len(CLA_RESET_SWEEP)  # full-aperture reset compares, every row carries expected=
    + 6  # ALIAS_REMAP_0 START/END/ATTRS programming + off + 2 restore readbacks
    + 3  # in-window CLA holes, each expected=0
    + 3  # JTAG AXI: identity read, landing-site read, source read after off
)


class smc_remap_cla_test_seq(SmcCsrSeq):
    async def _sweep_reset_values(self) -> None:
        """Per-entry decode AND the generated reset content of every entry."""
        # XVISOR_REMAP mirrors the MMODE table: 8 entries, one 64-bit
        # `offset[55:0]` field, plain rw storage with no lock and reset 0.
        # Addresses come from the generated indexed macro
        # `SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR(idx)
        #  = 0xC0014000 + idx * 0x8` (smc_addr.h:879), so base and stride are
        # both map-sourced. Entry 7 is written and restored as the live-register
        # proof; a reset-only compare on eight zero registers would be satisfied
        # by an unmapped window just as well.
        for i in range(XVISOR_REMAP_ENTRIES):
            addr = smc_indexed_addr("SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR", i)
            await self.csr_read(
                f"XVISOR_REMAP_{i}_ATTRS",
                addr,
                expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=8,
            )
        xv_probe_addr = smc_indexed_addr(
            "SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR",
            XVISOR_REMAP_ENTRIES - 1,
        )
        await self.csr_write("XVISOR_REMAP_PROBE", xv_probe_addr, XVISOR_PROBE, length=8)
        await self.csr_read(
            "XVISOR_REMAP_PROBE_RB",
            xv_probe_addr,
            expected=XVISOR_PROBE,
            length=8,
        )
        await self.csr_write(
            "XVISOR_REMAP_RESTORE",
            xv_probe_addr,
            OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
            length=8,
        )
        await self.csr_read(
            "XVISOR_REMAP_RESTORE_RB",
            xv_probe_addr,
            expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
            length=8,
        )
        for i, addr in enumerate(MMODE_REMAP_ATTRS_ADDRS):
            await self.csr_read(
                f"MMODE_REMAP_{i}_ATTRS",
                addr,
                expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=8,
            )
        for name, addr, expected in ALIAS_REMAP_REGS:
            await self.csr_read(name, addr, expected=expected, length=8)
        cocotb.log.info(
            "CHK-REMAP-TABLE-RESET: 8 MMODE_REMAP ATTRS + 24 ALIAS_REMAP "
            "START/END/ATTRS all decoded and matched their generated RDL reset "
            "value (MMODE=0x%016x, ALIAS start/end/attrs=0x%016x/0x%016x/0x%016x)",
            OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
            REMAP_REGION_REGION_START_REG_DEFAULT,
            REMAP_REGION_REGION_END_REG_DEFAULT,
            REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
        )

    async def _cla_window(self) -> None:
        """Allow leg + in-window-hole leg on the CLA aperture, in the same run."""
        for name, addr, expected, length in CLA_RESET_READS:
            await self.csr_read(name, addr, expected=expected, length=length)
        # Live-register proof: the DV scratch register is sw=rw with reset 0.
        await self.csr_write(
            "CLA_SCRATCH", SMC_CLA_CLA_0__SCRATCH_REG_ADDR, CLA_SCRATCH_PATTERN, length=8
        )
        await self.csr_read(
            "CLA_SCRATCH_RB",
            SMC_CLA_CLA_0__SCRATCH_REG_ADDR,
            expected=CLA_SCRATCH_PATTERN,
            length=8,
        )
        await self.csr_write(
            "CLA_SCRATCH_RESTORE",
            SMC_CLA_CLA_0__SCRATCH_REG_ADDR,
            DFD_CLA_Scratch_REG_DEFAULT,
            length=8,
        )
        await self.csr_read(
            "CLA_SCRATCH_RESTORE_RB",
            SMC_CLA_CLA_0__SCRATCH_REG_ADDR,
            expected=DFD_CLA_Scratch_REG_DEFAULT,
            length=8,
        )
        cocotb.log.info(
            "CHK-CLA-WINDOW-ALLOW: Trdstramimpl=0x%08x and Trdstimpl=0x%08x "
            "match their generated RDL reset values, and Scratch took "
            "0x%016x -> 0x%016x on a write/readback/restore -- the CLA aperture "
            "answers with live registers (positive control for the hole leg)",
            DFD_DST_SINK_Trdstramimpl_REG_DEFAULT,
            DFD_DST_Trdstimpl_REG_DEFAULT,
            CLA_SCRATCH_PATTERN,
            DFD_CLA_Scratch_REG_DEFAULT,
        )
        # Full-aperture reset sweep. Every CLA register is compared against its
        # generated reset value; the non-zero rows are the discriminating ones.
        assert len(CLA_RESET_SWEEP) >= 82, (
            f"CLA reset sweep built only {len(CLA_RESET_SWEEP)} rows from the "
            f"generated map; smc_cla.rdl declares 137 registers of which 55 are "
            f"hardware-driven and excluded, so 82 are expected -- fewer means "
            f"the introspection lost rows and the sweep under-reports coverage"
        )
        assert len(CLA_SWEEP_NONZERO) >= 5, (
            f"only {len(CLA_SWEEP_NONZERO)} CLA registers have a non-zero "
            f"generated reset; without those rows this sweep would be 82 reads "
            f"of zero, which an unmapped aperture also produces"
        )
        for name, addr, expected, length in CLA_RESET_SWEEP:
            await self.csr_read(name, addr, expected=expected, length=length)
        cocotb.log.info(
            "CHK-CLA-RESET-SWEEP: %d CLA registers read over the aperture and "
            "compared against their generated RDL reset values, %d of them with "
            "a NON-ZERO reset (the discriminating rows -- no error slave and no "
            "unmapped read can fabricate %s). In-window holes below complete "
            "OKAY with data 0, so the non-zero rows carry the discrimination.",
            len(CLA_RESET_SWEEP),
            len(CLA_SWEEP_NONZERO),
            "a non-zero reset value",
        )
        hole_offs = "/".join(
            f"+0x{addr - SMC_CLA_REG_MAP_BASE_ADDR:X}" for _, addr in CLA_UNMAPPED_PROBES
        )
        for name, addr in CLA_UNMAPPED_PROBES:
            await self.csr_read(name, addr, expected=0, length=4)
        cocotb.log.info(
            "CHK-CLA-WINDOW-DENY: the %d unmapped in-window offsets %s "
            "(holes derived from the generated CLA map) each completed OKAY "
            "with rdata=0, while the live registers around them answered with "
            "their generated values in the same run",
            len(CLA_UNMAPPED_PROBES),
            hole_offs,
        )

    async def _program_pass_all_filters(self) -> None:
        """Inbound/outbound filters wide open so the remap is what is tested."""
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )

    async def _prove_alias_remap_landing(self) -> None:
        """Program ALIAS_REMAP_0 and observe where the access actually lands."""
        await self._program_pass_all_filters()
        start_writes, start_reads = output_responder_counts()

        # (1) Positive control: with entry 0 still at its reset (valid=0) an
        # access must land where it was issued.
        await jtag_axi_write(self, REMAP_SRC, IDENTITY_DATA)
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            last_addr=REMAP_SRC,
            last_wdata=IDENTITY_DATA,
        )
        ident = await jtag_axi_read(self, REMAP_SRC, expected=IDENTITY_DATA)
        cocotb.log.info(
            "CHK-REMAP-ALIAS0-IDENTITY: ALIAS_REMAP_0 invalid -> JTAG AXI write "
            "at 0x%x landed at tb_output_axi_last_addr=0x%x with wdata=0x%016x "
            "and read back 0x%016x (positive control: the path works untranslated)",
            REMAP_SRC,
            REMAP_SRC,
            IDENTITY_DATA,
            ident.rdata,
        )

        # (2) Program the entry and prove the landing site moved.
        await self.csr_write("ALIAS0_START_PROG", ALIAS0_START, REMAP_SRC, length=8)
        await self.csr_read("ALIAS0_START_PROG_RB", ALIAS0_START, expected=REMAP_SRC, length=8)
        await self.csr_write("ALIAS0_END_PROG", ALIAS0_END, REMAP_DST, length=8)
        await self.csr_read("ALIAS0_END_PROG_RB", ALIAS0_END, expected=REMAP_DST, length=8)
        await self.csr_write("ALIAS0_ATTRS_PROG", ALIAS0_ATTRS, REMAP_ATTRS_ON, length=8)
        await self.csr_read("ALIAS0_ATTRS_PROG_RB", ALIAS0_ATTRS, expected=REMAP_ATTRS_ON, length=8)

        mid_writes, mid_reads = output_responder_counts()
        await jtag_axi_write(self, REMAP_SRC, REMAPPED_DATA)
        await check_output_responder_delta(
            start_writes=mid_writes,
            start_reads=mid_reads,
            write_delta=1,
            read_delta=0,
            last_addr=REMAP_DST,
            last_wdata=REMAPPED_DATA,
        )
        landed = await jtag_axi_read(self, REMAP_DST, expected=REMAPPED_DATA)
        cocotb.log.info(
            "CHK-REMAP-ALIAS0-LANDING: ALIAS_REMAP_0 START=0x%x END=0x%x "
            "ATTRS=0x%016x (offset=%d page(s), valid=1) -> the JTAG AXI write "
            "issued at 0x%x reached the SYS_OUT responder at "
            "tb_output_axi_last_addr=0x%x (= source + %d * 0x%x, the programmed "
            "translation) carrying wdata=0x%016x, and a read at the landing site "
            "returns 0x%016x",
            REMAP_SRC,
            REMAP_DST,
            REMAP_ATTRS_ON,
            REMAP_OFFSET_PAGES,
            REMAP_SRC,
            REMAP_DST,
            REMAP_OFFSET_PAGES,
            _PAGE,
            REMAPPED_DATA,
            landed.rdata,
        )

        # (3) Negative control: disable the entry and read the source address.
        # It must still hold the identity-phase data, i.e. the translated write
        # did NOT also land at the source.
        await self.csr_write(
            "ALIAS0_ATTRS_OFF", ALIAS0_ATTRS, REMAP_REGION_REGION_ATTRS_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "ALIAS0_ATTRS_OFF_RB",
            ALIAS0_ATTRS,
            expected=REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
            length=8,
        )
        src_after = await jtag_axi_read(self, REMAP_SRC, expected=IDENTITY_DATA)
        cocotb.log.info(
            "CHK-REMAP-ALIAS0-OFF: with ALIAS_REMAP_0.valid cleared the read at "
            "0x%x returns 0x%016x -- the identity-phase data, unchanged by the "
            "translated write, so the remap moved the access instead of "
            "duplicating it",
            REMAP_SRC,
            src_after.rdata,
        )
        await self.csr_write(
            "ALIAS0_START_RESTORE", ALIAS0_START, REMAP_REGION_REGION_START_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "ALIAS0_START_RESTORE_RB",
            ALIAS0_START,
            expected=REMAP_REGION_REGION_START_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "ALIAS0_END_RESTORE", ALIAS0_END, REMAP_REGION_REGION_END_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "ALIAS0_END_RESTORE_RB",
            ALIAS0_END,
            expected=REMAP_REGION_REGION_END_REG_DEFAULT,
            length=8,
        )

    async def body(self) -> None:
        await self._sweep_reset_values()
        await self._cla_window()
        await self._prove_alias_remap_landing()
        # Loop integrity PLUS the scoreboard cross-check: `self.accesses` alone
        # is a self-count that cannot see a mis-bound analysis path.
        self.assert_all_reachable(_EXPECTED_ACCESSES, "MMODE+ALIAS+CLA+REMAP")
        sb = self.env.scoreboard
        # Fail-capable floor on the MEASURED value compares: the scoreboard books
        # one only after an exact rdata compare passed, so a leg that lost its
        # `expected` fails here instead of counting as a bare access.
        assert sb.sys_axi_value_checks_seen >= _EXPECTED_VALUE_CHECKS, (
            f"expected at least {_EXPECTED_VALUE_CHECKS} value-checked reads "
            f"(32 remap reset values, 2 CLA reset values, 2 CLA scratch "
            f"readbacks, 3 in-window CLA holes, 6 ALIAS_REMAP_0 programming "
            f"readbacks, 3 JTAG AXI data compares), scoreboard measured "
            f"{sb.sys_axi_value_checks_seen}"
        )

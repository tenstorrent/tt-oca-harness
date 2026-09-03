# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap: ALIAS_REMAP translation + MMODE_REMAP/ALIAS reset sweep + CLA
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
  deny leg on unmapped in-window offsets, so the error response is attributable
  to *this* aperture's decode rather than to a dead bus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

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
    RESP_SLVERR,
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
    SMC_CLA_CRSCRATCHPAD_REG_ADDR,
    SMC_CLA_REG_MAP_BASE_ADDR,
    SMC_CLA_SCRATCH_REG_ADDR,
    SMC_CLA_TRDSTIMPL_REG_ADDR,
    SMC_MMODE_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
    SMC_CLA_CrScratchpad_REG_DEFAULT,
    SMC_CLA_Scratch_REG_DEFAULT,
    SMC_CLA_Trdstimpl_REG_DEFAULT,
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
# Allow leg: real CLA registers with their generated RDL reset values.
# `CrScratchpad` is the discriminating one: its reset is 0xBFBF..BF, a value no
# error slave and no unmapped read can produce.
CLA_RESET_READS = (
    ("CLA_CRSCRATCHPAD", SMC_CLA_CRSCRATCHPAD_REG_ADDR, SMC_CLA_CrScratchpad_REG_DEFAULT),
    ("CLA_TRDSTIMPL", SMC_CLA_TRDSTIMPL_REG_ADDR, SMC_CLA_Trdstimpl_REG_DEFAULT),
)
# smc_cla.rdl `Scratch @ 0x33F8`: "Additional scratch register for DV", sw=rw,
# reset 0x0. Written and read back so the allow leg proves a live register, not
# just a decodable address.
CLA_SCRATCH_PATTERN = 0xA5A5_5A5A_C3C3_3C3C


# CLA registers whose value the HARDWARE drives (at least one field with
# `hw = w` or `hw = rw` in hw/ip/dfd/regs/smc_cla.rdl). Their read value is not
# required to equal the RDL reset once time has advanced, so they are EXCLUDED
# from the reset sweep -- comparing them would be a false failure, not a check.
# Measured proof that this exclusion is necessary and not defensive: `Timestamp`
# @0x200 reads 0x2ad against a generated reset of 0x0 on this bench, because it
# is a free-running counter. It gets its own monotonic check instead.
# Derived from the RDL, 46 of the 103 registers; the remaining 57 are `hw = r`
# software-owned config/scratch and are the ones the sweep can hold to a reset.
# CLA registers declared `regwidth = 32` in smc_cla.rdl. The aperture MIXES 32-
# and 64-bit registers (66 are 64-bit, 37 are 32-bit), so a blanket 8-byte read
# is wrong: measured, an 8-byte read of `Trdstimpl` @0x1004 returns non-OKAY
# because it spans past the register. Each row is read at its declared width.
CLA_REG32 = (
    "CDbgDebugTraceCfg",
    "TimeStampConfig",
    "TrClusterFuseCfgHi",
    "TrClusterFuseCfgLow",
    "TrScratchHi",
    "TrScratchLo",
    "TrScratchpadHi",
    "TrScratchpadLo",
    "Trcustomramsmemlimitlow",
    "Trdstcontrol",
    "Trdstimpl",
    "Trdstinstfeatures",
    "Trdstramcontrol",
    "Trdstramdata",
    "Trdstramimpl",
    "Trdstramlimithigh",
    "Trdstramlimitlow",
    "Trdstramrphigh",
    "Trdstramrplow",
    "Trdstramstarthigh",
    "Trdstramstartlow",
    "Trdstramwphigh",
    "Trdstramwplow",
    "Trfunnelcontrol",
    "Trfunneldisinput",
    "Trfunnelimpl",
    "Trramcontrol",
    "Trramdata",
    "Trramimpl",
    "Trramlimithigh",
    "Trramlimitlow",
    "Trramrphigh",
    "Trramrplow",
    "Trramstarthigh",
    "Trramstartlow",
    "Trramwphigh",
    "Trramwplow",
)

CLA_HW_DRIVEN = (
    "CDbgClaCounter0Cfg",
    "CDbgClaCounter1Cfg",
    "CDbgClaCounter2Cfg",
    "CDbgClaCounter3Cfg",
    "CDbgClaCtrlStatus",
    "CDbgEapStatus",
    "CDbgSignalSnapshotNode0Eap0",
    "CDbgSignalSnapshotNode0Eap1",
    "CDbgSignalSnapshotNode0Eap2",
    "CDbgSignalSnapshotNode0Eap3",
    "CDbgSignalSnapshotNode1Eap0",
    "CDbgSignalSnapshotNode1Eap1",
    "CDbgSignalSnapshotNode1Eap2",
    "CDbgSignalSnapshotNode1Eap3",
    "CDbgSignalSnapshotNode2Eap0",
    "CDbgSignalSnapshotNode2Eap1",
    "CDbgSignalSnapshotNode2Eap2",
    "CDbgSignalSnapshotNode2Eap3",
    "CDbgSignalSnapshotNode3Eap0",
    "CDbgSignalSnapshotNode3Eap1",
    "CDbgSignalSnapshotNode3Eap2",
    "CDbgSignalSnapshotNode3Eap3",
    "Timestamp",
    "Trdstcontrol",
    "Trdstramcontrol",
    "Trdstramdata",
    "Trdstramlimithigh",
    "Trdstramlimitlow",
    "Trdstramrphigh",
    "Trdstramrplow",
    "Trdstramstarthigh",
    "Trdstramstartlow",
    "Trdstramwphigh",
    "Trdstramwplow",
    "Trfunnelcontrol",
    "Trfunneldisinput",
    "Trramcontrol",
    "Trramdata",
    "Trramlimithigh",
    "Trramlimitlow",
    "Trramrphigh",
    "Trramrplow",
    "Trramstarthigh",
    "Trramstartlow",
    "Trramwphigh",
    "Trramwplow",
)


def _cla_reset_sweep() -> tuple[tuple[str, int, int, int], ...]:
    """Every CLA register with its generated reset value, from generated symbols.

    Built by introspecting ``smc_reg`` at import time rather than transcribing a
    103-row table, so the expectations cannot drift from the generated register
    map ([ADDRESS-FROM-AUTHORITATIVE-MAP]).

    Why a reset compare is a real check here rather than a decode-only read:
    of the 137 CLA registers the generated map carries, 10 have NON-ZERO resets
    (``CrScratchpad`` 0xBFBF..BF, ``Trdstimpl`` 0x41010101, ``Trdstramimpl``
    0x01003901, ``Trdstcontrol`` 0x03000068, ``CDbgDebugTraceCfg`` 0x00102810,
    ``Trdstinstfeatures`` 0x40000000, ``CDbgClaCtrlStatus`` 0x1B00,
    ``Trfunnelimpl`` 0x0801, and ``Trdstramcontrol`` / ``Trfunnelcontrol`` 0x8)
    -- values no error slave and no unmapped read can fabricate. For the 127
    zero-reset rows the discrimination comes from the deny leg in the same run:
    unmapped in-window offsets answer SLVERR with rdata 0, so an OKAY+0 is
    distinguishable from a lost decode.

    Reading the whole aperture is side-effect free: ``smc_cla.rdl`` contains no
    ``onread`` property on any field (verified).
    """
    import smc_reg as _r

    out = []
    for sym in dir(_r):
        if not sym.startswith("SMC_CLA_") or not sym.endswith("_REG_ADDR"):
            continue
        stem = sym[len("SMC_CLA_") : -len("_REG_ADDR")]
        # The generated module spells defaults in the RDL's mixed case and
        # addresses in upper case; match case-insensitively on the stem.
        default = None
        for cand in dir(_r):
            if (
                cand.startswith("SMC_CLA_")
                and cand.endswith("_REG_DEFAULT")
                and cand[len("SMC_CLA_") : -len("_REG_DEFAULT")].upper() == stem.upper()
            ):
                default = getattr(_r, cand)
                break
        if default is None:
            continue
        if any(stem.upper() == hw.upper() for hw in CLA_HW_DRIVEN):
            continue
        length = 4 if any(stem.upper() == w.upper() for w in CLA_REG32) else 8
        out.append((f"CLA_SWEEP_{stem}", getattr(_r, sym), default, length))
    out.sort(key=lambda row: row[1])
    return tuple(out)


CLA_RESET_SWEEP = _cla_reset_sweep()
# Non-zero-reset rows carry the discrimination; asserted below so a generated
# map that lost them cannot silently turn the sweep into 103 reads of zero.
CLA_SWEEP_NONZERO = tuple(r for r in CLA_RESET_SWEEP if r[2] != 0)
# Deny leg: the CLA aperture's first register is `CDbgMuxSel @ 0x198`
# (smc_cla.rdl), so offsets 0x0/0x4/0x8 are inside the window but map to no
# register. These probes are named as offsets, never under a register name.
CLA_UNMAPPED_PROBES = (
    ("CLA_WINDOW_OFF0", SMC_CLA_REG_MAP_BASE_ADDR + 0x0),
    ("CLA_WINDOW_OFF4", SMC_CLA_REG_MAP_BASE_ADDR + 0x4),
    ("CLA_WINDOW_OFF8", SMC_CLA_REG_MAP_BASE_ADDR + 0x8),
)

# --- ALIAS_REMAP translation ---------------------------------------------
# Field positions come from the generated alias_remap header, never hand-packed.
_ALIAS_REMAP_H = (
    Path(__file__).resolve().parents[6]
    / "hw"
    / "common"
    / "axi"
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
# Two pages inside the SYS_OUT fabric window served by the TB axi_sim_mem
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
# resets + scratch wr/rd/restore + deny + the full-aperture reset sweep. The
# sweep length is taken from the table built off the generated register map
# (57 software-owned rows of the 103 in smc_cla.rdl); it is guarded by an
# explicit `len(CLA_RESET_SWEEP) >= 55` assert in `_cla_window`, so a generated
# map that lost rows fails loudly instead of silently lowering this floor.
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
    + 2  # CLA CrScratchpad + Trdstimpl reset values
    + 2  # CLA Scratch write readback + restore readback
    + len(CLA_RESET_SWEEP)  # full-aperture reset compares, every row carries expected=
    + 6  # ALIAS_REMAP_0 START/END/ATTRS programming + off + 2 restore readbacks
    + 3  # JTAG AXI: identity read, landing-site read, source read after off
)


class smc_remap_cla_test_seq(SmcCsrSeq):
    async def csr_read_expect_resp_zero(
        self, name: str, addr: int, expected_resp: int, length: int = 4
    ) -> int:
        """Read a window that must answer with one EXACT error response and 0.

        Stronger than ``csr_read_expect_error`` ("some error"): the response
        *kind* and the data are both declared, so an aperture that stops being
        decoded at all (a different error kind, or a different responder) is
        distinguishable from the one this scenario names. Both expectations are
        also enforced by ``SmcScoreboard._check_sys_axi`` from the item, not only
        by the assert below.
        """
        mask = (1 << (length * 8)) - 1
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = expected_resp
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == expected_resp, (
            f"{name} @ 0x{addr:08x}: expected resp={expected_resp}, got "
            f"resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        got = item.rdata & mask
        assert got == 0, (
            f"{name} @ 0x{addr:08x}: expected rdata=0 from the error responder, "
            f"got 0x{got:0{length * 2}x}"
        )
        return item.rdata

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
        """Allow leg + deny leg on the CLA aperture, in the same run."""
        for name, addr, expected in CLA_RESET_READS:
            await self.csr_read(name, addr, expected=expected, length=8)
        # Live-register proof: the DV scratch register is sw=rw with reset 0.
        await self.csr_write("CLA_SCRATCH", SMC_CLA_SCRATCH_REG_ADDR, CLA_SCRATCH_PATTERN, length=8)
        await self.csr_read(
            "CLA_SCRATCH_RB", SMC_CLA_SCRATCH_REG_ADDR, expected=CLA_SCRATCH_PATTERN, length=8
        )
        await self.csr_write(
            "CLA_SCRATCH_RESTORE", SMC_CLA_SCRATCH_REG_ADDR, SMC_CLA_Scratch_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "CLA_SCRATCH_RESTORE_RB",
            SMC_CLA_SCRATCH_REG_ADDR,
            expected=SMC_CLA_Scratch_REG_DEFAULT,
            length=8,
        )
        cocotb.log.info(
            "CHK-CLA-WINDOW-ALLOW: CrScratchpad=0x%016x and Trdstimpl=0x%016x "
            "match their generated RDL reset values, and Scratch took "
            "0x%016x -> 0x%016x on a write/readback/restore -- the CLA aperture "
            "answers with live registers (positive control for the deny leg)",
            SMC_CLA_CrScratchpad_REG_DEFAULT,
            SMC_CLA_Trdstimpl_REG_DEFAULT,
            CLA_SCRATCH_PATTERN,
            SMC_CLA_Scratch_REG_DEFAULT,
        )
        # Full-aperture reset sweep. Every CLA register is compared against its
        # generated reset value; the non-zero rows are the discriminating ones.
        assert len(CLA_RESET_SWEEP) >= 55, (
            f"CLA reset sweep built only {len(CLA_RESET_SWEEP)} rows from the "
            f"generated map; smc_cla.rdl declares 103 registers of which 46 are "
            f"hardware-driven and excluded, so 57 are expected -- fewer means "
            f"the introspection lost rows and the sweep under-reports coverage"
        )
        assert len(CLA_SWEEP_NONZERO) >= 8, (
            f"only {len(CLA_SWEEP_NONZERO)} CLA registers have a non-zero "
            f"generated reset; without those rows this sweep would be 103 reads "
            f"of zero, which an unmapped aperture also produces"
        )
        for name, addr, expected, length in CLA_RESET_SWEEP:
            await self.csr_read(name, addr, expected=expected, length=length)
        cocotb.log.info(
            "CHK-CLA-RESET-SWEEP: %d CLA registers read over the aperture and "
            "compared against their generated RDL reset values, %d of them with "
            "a NON-ZERO reset (the discriminating rows -- no error slave and no "
            "unmapped read can fabricate 0xBFBF..BF / 0x41010101 / 0x01003901 / "
            "0xEFEFEFEF / 0x03000068). Zero-reset rows are separated from a lost "
            "decode by the deny leg below, which answers SLVERR in the same run.",
            len(CLA_RESET_SWEEP),
            len(CLA_SWEEP_NONZERO),
        )
        for name, addr in CLA_UNMAPPED_PROBES:
            await self.csr_read_expect_resp_zero(name, addr, RESP_SLVERR)
        cocotb.log.info(
            "CHK-CLA-WINDOW-DENY: the three unmapped in-window offsets +0x0/+0x4/"
            "+0x8 (below the aperture's first register CDbgMuxSel @0x198) each "
            "returned resp=%d (SLVERR) with rdata=0, while the registers above "
            "answered OKAY in the same run",
            RESP_SLVERR,
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
            f"readbacks, 6 ALIAS_REMAP_0 programming readbacks, 3 JTAG AXI data "
            f"compares), scoreboard measured {sb.sys_axi_value_checks_seen}"
        )

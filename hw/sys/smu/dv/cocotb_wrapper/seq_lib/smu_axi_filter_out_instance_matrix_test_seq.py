# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: outbound filter instance CSR DECODE (FAB_SMC_025 S1).

SEP=1 honest scope (no sep_in / no Force / no ext_out peer):
  S1  J2A program then readback on instances 0/1/8/15 (DECODE independence)
  S2  not covered: identical_struct_in_vs_out needs an ext_out peer
  S3  not covered: outbound pairwise isolation needs an ext_out peer

Distinct signature ranges stand in for the SPM/global egress windows;
S1 proves CSR addressing/aliasing only, not egress traffic.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
    smc_indexed_addr,
)
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)

_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_BUS_WIDTH = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
_CFG_CMP_MASK = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | _F_ALLOW_NS
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
)

_OUT_CFG = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_OUT_START = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_OUT_END = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

FILTER_SRC_ID = 1

# SRC_ID is 4-bit — keep every programmed value in 0..15 and distinct.
# DECODE-only signature windows (need not hit LIVE egress consumers).
S1_SIGNATURES = {
    0: (0xC020_0000, 0xC020_00FF, FILTER_SRC_ID, False),
    1: (0xC020_1000, 0xC020_10FF, 2, False),
    8: (0xC020_8000, 0xC020_80FF, 9, True),
    15: (0xC020_F000, 0xC020_F0FF, 3, True),
}

DEFERRED_S2_TEXT = (
    "SMCF-FILTER-OUT-INSTANCES.S2 (identical_struct_in_vs_out) "
    "NOT-REACHABLE-AT-THIS-LEVEL. identical_struct_in_vs_out LIVE "
    "requires ext_out consumer — do not invent DECODE substitute."
)

DEFERRED_S3_TEXT = (
    "SMCF-FILTER-OUT-INSTANCES.S3 (outbound_instance_isolation_pairwise) "
    "NOT-REACHABLE-AT-THIS-LEVEL. outbound_instance_isolation_pairwise "
    "LIVE requires ext_out beats."
)


def _pack_cfg(*, allow_ns: bool, src_id: int) -> int:
    if not 0 <= int(src_id) <= 0xF:
        raise AssertionError(f"SRC_ID out of 4-bit range: {src_id}")
    return (
        _F_READ
        | _F_WRITE
        | _F_ENTRY
        | _F_BUS_WIDTH
        | (_F_ALLOW_NS if allow_ns else 0)
        | filter_ctrl_field_encode("SRC_ID", src_id)
    )


class smu_axi_filter_out_instance_matrix_test_seq:
    """Outbound filter instance matrix S1; S2/S3 logged as needing an ext_out peer."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_deferred = False
        self.s3_deferred = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:08x} status={st}")
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:x}")

    async def _j2a_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:08x} status={st}")
        return int(rdata)

    async def _write_inst(
        self,
        jtag,
        inst: int,
        *,
        lo: int,
        hi: int,
        src_id: int,
        allow_ns: bool,
        tag: str,
    ) -> int:
        """Program one outbound instance; return packed CFG (no readback)."""
        cfg = _pack_cfg(allow_ns=allow_ns, src_id=src_id)
        await self._j2a_wr(jtag, smc_indexed_addr(_OUT_START, inst), lo, f"{tag}_START")
        await self._j2a_wr(jtag, smc_indexed_addr(_OUT_END, inst), hi, f"{tag}_END")
        await self._j2a_wr(jtag, smc_indexed_addr(_OUT_CFG, inst), cfg, f"{tag}_CONFIG")
        return cfg

    async def _readback_inst(
        self,
        jtag,
        inst: int,
        *,
        lo: int,
        hi: int,
        cfg: int,
        tag: str,
    ) -> None:
        rb = await self._j2a_rd(jtag, smc_indexed_addr(_OUT_CFG, inst), f"{tag}_RB")
        if (rb & _CFG_CMP_MASK) != (cfg & _CFG_CMP_MASK):
            raise AssertionError(f"{tag} CONFIG rb mismatch want=0x{cfg:x} got=0x{rb:x}")
        rb_lo = await self._j2a_rd(jtag, smc_indexed_addr(_OUT_START, inst), f"{tag}_START_RB")
        rb_hi = await self._j2a_rd(jtag, smc_indexed_addr(_OUT_END, inst), f"{tag}_END_RB")
        if (rb_lo & 0xFFF_FFFF_FFFF_FFFF) != (lo & 0xFFF_FFFF_FFFF_FFFF):
            raise AssertionError(f"{tag} START rb 0x{rb_lo:x} want 0x{lo:x}")
        if (rb_hi & 0xFFF_FFFF_FFFF_FFFF) != (hi & 0xFFF_FFFF_FFFF_FFFF):
            raise AssertionError(f"{tag} END rb 0x{rb_hi:x} want 0x{hi:x}")

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-FILTER-OUT-J2A-READY", idcode, 0x1)

        stride = smc_indexed_addr(_OUT_CFG, 1) - smc_indexed_addr(_OUT_CFG, 0)
        if stride != 0x20:
            raise AssertionError(f"outbound filter stride want 0x20 got 0x{stride:x}")

        # Program every instance first, then read all back (aliasing detection).
        programmed: dict[int, tuple[int, int, int]] = {}
        for inst, (lo, hi, src_id, allow_ns) in S1_SIGNATURES.items():
            cfg = await self._write_inst(
                jtag,
                inst,
                lo=lo,
                hi=hi,
                src_id=src_id,
                allow_ns=allow_ns,
                tag=f"S1_O{inst}",
            )
            programmed[inst] = (lo, hi, cfg)

        for inst, (lo, hi, src_id, allow_ns) in S1_SIGNATURES.items():
            p_lo, p_hi, cfg = programmed[inst]
            await self._readback_inst(
                jtag,
                inst,
                lo=p_lo,
                hi=p_hi,
                cfg=cfg,
                tag=f"S1_O{inst}",
            )
            self._log(
                f"S1 out_filter_inst={inst} readback OK "
                f"lo=0x{lo:08x} hi=0x{hi:08x} src_id={src_id} "
                f"allow_ns={int(allow_ns)}"
            )

        self.s1_ok = True
        self._log(
            "CHK-FILTER-OUT-INSTANCES-S1: out_filter_inst=0,1,8,15 DECODE bases=smc_indexed_addr"
        )
        sb.expect_eq(
            "CHK-FILTER-OUT-INSTANCES-S1", True, True, evidence="CHK-FILTER-OUT-INSTANCES-S1"
        )

        # S2/S3 need an ext_out peer: log the not-reachable notes without a CHK token.
        self._log(f"DEFERRED-NOTE(S2): {DEFERRED_S2_TEXT}")
        self.s2_deferred = True
        self._log(f"DEFERRED-NOTE(S3): {DEFERRED_S3_TEXT}")
        self.s3_deferred = True

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: inbound filter instance independence (FAB_SMC_023 subset).

SEP=0 honest scope (no sep_in / no Force):
  S4  post-reset BlockByDefault DECERR on VERSION_LO (captured before CSR writes)
  S1  J2A program+readback on instances 0/1/7/14/15 (DECODE independence)
  S2  pairwise isolation: inst0 WDT page vs inst1 VERSION page + src_id
  S3  address AND src_id AND prot on inst3 CPU_SCRATCH page
  S5  clear then configure admission on VERSION_LO

Local-alias CSR pages stand in for the SPM/global-aperture windows.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import PROT_NONSECURE, PROT_PRIVILEGED, RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master, resp_name
from seq_lib.smu_filter_helpers import (
    page_align_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)
from seq_lib.smu_tb_pins import smc_primary_reset

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

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

AXI_TIMEOUT_NS = 200_000
FILTER_READY_POLLS = 64
FILTER_READY_STEP = 4
SECURE_PROT = PROT_PRIVILEGED  # 0x1 — prot[1]=0
NS_PROT = PROT_PRIVILEGED | PROT_NONSECURE  # 0x3

PROBE_WDT = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
PROBE_VERSION = SMC_CHIP_CONFIG_VERSION_LO
PROBE_CPU_SCRATCH = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

# Distinct pages for LIVE isolation (local-alias CSR consumers).
INST0_LO, INST0_HI = page_align_window(PROBE_WDT, PROBE_WDT)
INST1_LO, INST1_HI = page_align_window(PROBE_VERSION, PROBE_VERSION)
INST3_LO, INST3_HI = page_align_window(PROBE_CPU_SCRATCH, PROBE_CPU_SCRATCH)

FILTER_SRC_ID = 1
INST1_SRC = 2
INST3_SRC = 5

# S1 DECODE signatures (CSR readback only; ranges need not hit LIVE consumers).
# SRC_ID is 4-bit — keep every programmed value in 0..15 and distinct.
S1_SIGNATURES = {
    0: (INST0_LO, INST0_HI, FILTER_SRC_ID, False),
    1: (INST1_LO, INST1_HI, INST1_SRC, False),
    7: (0xC010_7000, 0xC010_70FF, 8, True),
    14: (0xC010_E000, 0xC010_E0FF, 15, False),
    15: (0xC010_F000, 0xC010_F0FF, 3, True),
}


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


class smu_axi_filter_in_instance_matrix_test_seq:
    """Inbound filter instance matrix S1–S5 on SEP=0 J2A + s_axi."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False
        self.s5_ok = False
        self.default_block_rd = None
        self.default_block_wr = None

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _axi_rw(
        self,
        master,
        addr: int,
        *,
        prot: int,
        user: int,
        write: bool,
        wdata: int = 0,
    ):
        async def _do():
            if write:
                result = await master.write_bytes_result(
                    addr,
                    wdata.to_bytes(4, "little"),
                    prot=prot,
                    user=user,
                    check_response=False,
                )
                return None, result.resp
            result = await master.read_bytes_result(
                addr, 4, prot=prot, user=user, check_response=False
            )
            return result.data, result.resp

        try:
            return await with_timeout(_do(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(
                f"TIMEOUT axi {'wr' if write else 'rd'} addr=0x{addr:08x} "
                f"prot=0x{prot:x} user=0x{user:x}: {exc}"
            ) from exc

    async def _await_resp(
        self,
        master,
        addr: int,
        *,
        prot: int,
        user: int,
        want,
        label: str,
        write: bool = False,
        wdata: int = 0,
    ):
        last = None
        for poll in range(FILTER_READY_POLLS):
            _val, resp = await self._axi_rw(
                master, addr, prot=prot, user=user, write=write, wdata=wdata
            )
            last = resp
            if resp == want:
                self._log(f"FILTER_READY {label} want={resp_name(want)} poll={poll}")
                return _val, resp
            await ClockCycles(self.dut.clk_smu_i, FILTER_READY_STEP)
        raise AssertionError(
            f"TIMEOUT FILTER_READY {label}: want={resp_name(want)} "
            f"last={resp_name(last) if last is not None else None}"
        )

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

    async def _program_inst(
        self,
        jtag,
        inst: int,
        *,
        lo: int,
        hi: int,
        src_id: int,
        allow_ns: bool,
        tag: str,
    ) -> None:
        cfg = _pack_cfg(allow_ns=allow_ns, src_id=src_id)
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_START, inst), lo, f"{tag}_START")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_END, inst), hi, f"{tag}_END")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, inst), cfg, f"{tag}_CONFIG")
        rb = await self._j2a_rd(jtag, smc_indexed_addr(_IN_CFG, inst), f"{tag}_RB")
        if (rb & _CFG_CMP_MASK) != (cfg & _CFG_CMP_MASK):
            raise AssertionError(f"{tag} CONFIG rb mismatch want=0x{cfg:x} got=0x{rb:x}")
        rb_lo = await self._j2a_rd(jtag, smc_indexed_addr(_IN_START, inst), f"{tag}_START_RB")
        rb_hi = await self._j2a_rd(jtag, smc_indexed_addr(_IN_END, inst), f"{tag}_END_RB")
        if (rb_lo & 0xFFF_FFFF_FFFF_FFFF) != (lo & 0xFFF_FFFF_FFFF_FFFF):
            raise AssertionError(f"{tag} START rb 0x{rb_lo:x} want 0x{lo:x}")
        if (rb_hi & 0xFFF_FFFF_FFFF_FFFF) != (hi & 0xFFF_FFFF_FFFF_FFFF):
            raise AssertionError(f"{tag} END rb 0x{rb_hi:x} want 0x{hi:x}")

    async def _disable_inst(self, jtag, inst: int, tag: str) -> None:
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, inst), 0, f"{tag}_DIS_I{inst}")

    async def _disable_all(self, jtag, tag: str) -> None:
        for inst in range(16):
            await self._disable_inst(jtag, inst, tag)

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        # SEP=1 wrapper: route ext_in local addresses through the crossbar.
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-FILTER-IN-J2A-READY", idcode, 0x1)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        # ---- S4 capture: default block before any inbound filter CSR ----
        _rd, rd_resp = await self._axi_rw(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=0,
            write=False,
        )
        _wr, wr_resp = await self._axi_rw(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=0,
            write=True,
            wdata=0x0230_A001,
        )
        self.default_block_rd = rd_resp
        self.default_block_wr = wr_resp
        if rd_resp != RESP_DECERR or wr_resp != RESP_DECERR:
            raise AssertionError(
                f"S4 pre-CSR default block want DECERR/DECERR "
                f"got {resp_name(rd_resp)}/{resp_name(wr_resp)}"
            )
        self.s4_ok = True
        self._log(
            f"CHK-FILTER-IN-DEFAULT-BLOCK-S1: post_reset inbound blocked @0x{PROBE_VERSION:08x}"
        )
        sb.expect_eq("CHK-FILTER-IN-DEFAULT-BLOCK-S1", True, True)

        # ---- S1 DECODE: independent instance CSR readback ----
        for inst, (lo, hi, src_id, allow_ns) in S1_SIGNATURES.items():
            await self._program_inst(
                jtag,
                inst,
                lo=lo,
                hi=hi,
                src_id=src_id,
                allow_ns=allow_ns,
                tag=f"S1_I{inst}",
            )
            self._log(
                f"S1 in_filter_inst={inst} readback OK "
                f"lo=0x{lo:08x} hi=0x{hi:08x} src_id={src_id} allow_ns={int(allow_ns)}"
            )
        self.s1_ok = True
        self._log("CHK-FILTER-IN-INSTANCES-S1: inst=0,1,7,14,15 DECODE bases=smc_indexed_addr")
        sb.expect_eq("CHK-FILTER-IN-INSTANCES-S1", True, True)

        # ---- S2 isolation pairwise ----
        for inst in (7, 14, 15, 1):
            await self._disable_inst(jtag, inst, "S2_clear")
        await self._program_inst(
            jtag,
            0,
            lo=INST0_LO,
            hi=INST0_HI,
            src_id=FILTER_SRC_ID,
            allow_ns=False,
            tag="S2_I0",
        )
        await self._await_resp(
            master,
            PROBE_WDT,
            prot=SECURE_PROT,
            user=FILTER_SRC_ID,
            want=RESP_OKAY,
            label="S2_inst0_admit",
        )
        _v, bad = await self._axi_rw(
            master,
            PROBE_WDT,
            prot=SECURE_PROT,
            user=FILTER_SRC_ID + 9,
            write=False,
        )
        if bad != RESP_DECERR:
            raise AssertionError(f"S2 inst0 wrong src want DECERR got {resp_name(bad)}")
        await self._program_inst(
            jtag,
            1,
            lo=INST1_LO,
            hi=INST1_HI,
            src_id=INST1_SRC,
            allow_ns=False,
            tag="S2_I1",
        )
        await self._await_resp(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=INST1_SRC,
            want=RESP_OKAY,
            label="S2_inst1_admit",
        )
        _v, cross = await self._axi_rw(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=FILTER_SRC_ID,
            write=False,
        )
        if cross != RESP_DECERR:
            raise AssertionError(
                f"S2 cross (inst0 src on inst1 window) want DECERR got {resp_name(cross)}"
            )
        self.s2_ok = True
        self._log(
            "CHK-FILTER-IN-INSTANCES-S2: instance_isolation_pairwise "
            "inst0_only=OKAY inst1_only=OKAY cross_blocked=DECERR"
        )
        sb.expect_eq("CHK-FILTER-IN-INSTANCES-S2", True, True)

        # ---- S3 three dimensions ----
        await self._disable_all(jtag, "S3_clear")
        await self._program_inst(
            jtag,
            3,
            lo=INST3_LO,
            hi=INST3_HI,
            src_id=INST3_SRC,
            allow_ns=False,
            tag="S3_I3",
        )
        await self._await_resp(
            master,
            PROBE_CPU_SCRATCH,
            prot=SECURE_PROT,
            user=INST3_SRC,
            want=RESP_OKAY,
            label="S3_all_match",
        )
        _v, addr_fail = await self._axi_rw(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=INST3_SRC,
            write=False,
        )
        if addr_fail != RESP_DECERR:
            raise AssertionError(f"S3 addr_fail want DECERR got {resp_name(addr_fail)}")
        _v, src_fail = await self._axi_rw(
            master,
            PROBE_CPU_SCRATCH,
            prot=SECURE_PROT,
            user=INST3_SRC + 3,
            write=False,
        )
        if src_fail != RESP_DECERR:
            raise AssertionError(f"S3 srcid_fail want DECERR got {resp_name(src_fail)}")
        _v, prot_fail = await self._axi_rw(
            master,
            PROBE_CPU_SCRATCH,
            prot=NS_PROT,
            user=INST3_SRC,
            write=False,
        )
        if prot_fail != RESP_DECERR:
            raise AssertionError(f"S3 prot_fail want DECERR got {resp_name(prot_fail)}")
        self.s3_ok = True
        self._log(
            "CHK-FILTER-IN-INSTANCES-S3: all_three_match,addr_fail_only,"
            "srcid_fail_only,prot_fail_only inst=3"
        )
        sb.expect_eq("CHK-FILTER-IN-INSTANCES-S3", True, True)

        # ---- S5 configured admission ----
        await self._disable_all(jtag, "S5_clear")
        await self._program_inst(
            jtag,
            0,
            lo=INST1_LO,
            hi=INST1_HI,
            src_id=0,  # src_id=0 disables src gating
            allow_ns=False,
            tag="S5_I0",
        )
        await self._await_resp(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=0,
            want=RESP_OKAY,
            label="S5_admit_rd",
        )
        await self._await_resp(
            master,
            PROBE_VERSION,
            prot=SECURE_PROT,
            user=0,
            want=RESP_OKAY,
            label="S5_admit_wr",
            write=True,
            wdata=0x0230_A002,
        )
        self.s5_ok = True
        self._log(
            f"CHK-FILTER-IN-DEFAULT-BLOCK-S2: configured_then_admitted @0x{PROBE_VERSION:08x}"
        )
        sb.expect_eq("CHK-FILTER-IN-DEFAULT-BLOCK-S2", True, True)

        all_ok = self.s1_ok and self.s2_ok and self.s3_ok and self.s4_ok and self.s5_ok
        sb.expect_eq("CHK-FILTER-IN-INSTANCES-BASIC", all_ok, True)
        self._log(
            "CHK-FILTER-IN-INSTANCES-BASIC: "
            f"s1={self.s1_ok} s2={self.s2_ok} s3={self.s3_ok} "
            f"s4={self.s4_ok} s5={self.s5_ok} (SEP=0 J2A+s_axi; no Force)"
        )

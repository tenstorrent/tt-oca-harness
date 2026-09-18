# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: LOCAL_BASE vs GLOBAL_BASE equivalence (FAB_SMC_007 subset).

SEP=0 honest scope (no sep_in / no Force):
  S1  Program GLOBAL_BASE/REGION_SIZE via J2A; open inbound filters; prove
      write_local(J2A)→read_global(s_axi) and write_global→read_local on SPM.
  S2  Move GLOBAL_BASE; prove offset preservation on the same SPM offset.

Local-side traffic goes over J2A and global-side traffic over s_axi.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import PROT_PRIVILEGED, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master, resp_name
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
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

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

LOCAL_BASE = 0xC000_0000
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
REP_OFFSET = SPM_BASE - LOCAL_BASE
LOCAL_ADDR = LOCAL_BASE + REP_OFFSET

GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")

GLOBAL_BASE_1 = 0x0200_0000
GLOBAL_BASE_2 = 0x0400_0000
REGION_SIZE = 0x0200_0000

PATTERN_L2G = 0xA5A51234
PATTERN_G2L = 0x5A5A5678
PATTERN_S2 = 0xDEADBEEF

AXI_TIMEOUT_NS = 200_000
SECURE_PROT = PROT_PRIVILEGED
FILTER_READY_POLLS = 64
FILTER_READY_STEP = 4

_WIDE_CFG = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | _F_BUS_WIDTH
    | _F_ALLOW_NS
    | filter_ctrl_field_encode("SRC_ID", 0)  # src_id=0 disables src gating
)


class smu_ext_axi_global_addr_smoke_test_seq:
    """LOCAL↔GLOBAL SPM equivalence via J2A + s_axi."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _j2a_wr32(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data & 0xFFFF_FFFF,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:08x} status={st}")
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:08x}")

    async def _j2a_rd32(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:08x} status={st}")
        return int(rdata) & 0xFFFF_FFFF

    async def _axi_rw32(self, master, addr: int, *, write: bool, wdata: int = 0):
        async def _do():
            if write:
                result = await master.write_bytes_result(
                    addr,
                    wdata.to_bytes(4, "little"),
                    prot=SECURE_PROT,
                    check_response=False,
                )
                return None, result.resp
            result = await master.read_bytes_result(addr, 4, prot=SECURE_PROT, check_response=False)
            return result.data & 0xFFFF_FFFF, result.resp

        try:
            return await with_timeout(_do(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(
                f"TIMEOUT axi {'wr' if write else 'rd'} @0x{addr:08x}: {exc}"
            ) from exc

    async def _await_axi_ok(self, master, addr: int, *, write: bool, wdata: int, label: str):
        last = None
        last_val = None
        for poll in range(FILTER_READY_POLLS):
            val, resp = await self._axi_rw32(master, addr, write=write, wdata=wdata)
            last, last_val = resp, val
            if resp == RESP_OKAY:
                self._log(f"FILTER_READY {label} poll={poll}")
                return val, resp
            await ClockCycles(self.dut.clk_smu_i, FILTER_READY_STEP)
        raise AssertionError(
            f"TIMEOUT FILTER_READY {label}: last={resp_name(last)} data={last_val!r}"
        )

    async def _open_inbound_wide(self, jtag) -> None:
        for inst in range(16):
            await self._j2a_wr32(
                jtag,
                smc_indexed_addr(_IN_START, inst),
                0,
                f"IN{inst}_START",
            )
            await self._j2a_wr32(
                jtag,
                smc_indexed_addr(_IN_END, inst),
                0xFFFF_FFFF,
                f"IN{inst}_END",
            )
            await self._j2a_wr32(
                jtag,
                smc_indexed_addr(_IN_CFG, inst),
                _WIDE_CFG,
                f"IN{inst}_CFG",
            )

    async def _program_aperture(self, jtag, global_base: int) -> None:
        await self._j2a_wr32(jtag, GLOBAL_BASE_REG, global_base, "GLOBAL_BASE")
        await self._j2a_wr32(jtag, REGION_SIZE_REG, REGION_SIZE, "REGION_SIZE")
        rb = await self._j2a_rd32(jtag, GLOBAL_BASE_REG, "GLOBAL_BASE_RB")
        if rb != global_base:
            raise AssertionError(f"GLOBAL_BASE rb 0x{rb:08x} want 0x{global_base:08x}")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-BASE-EQ-J2A-READY", idcode, 0x1)

        master = await make_smu_axi_master(
            self.dut, self.dut.clk_smu_i, smc_primary_reset(self.dut)
        )

        await self._program_aperture(jtag, GLOBAL_BASE_1)
        await self._open_inbound_wide(jtag)
        self._log(
            f"S1 SETUP GLOBAL_BASE=0x{GLOBAL_BASE_1:08x} "
            f"REGION_SIZE=0x{REGION_SIZE:08x} LOCAL=0x{LOCAL_ADDR:08x} "
            f"offset=0x{REP_OFFSET:x}"
        )

        global_addr_1 = GLOBAL_BASE_1 + REP_OFFSET

        # write_local (J2A) → read_global (s_axi)
        await self._j2a_wr32(jtag, LOCAL_ADDR, PATTERN_L2G, "S1_L2G_LOCAL")
        val, resp = await self._await_axi_ok(
            master,
            global_addr_1,
            write=False,
            wdata=0,
            label="S1_L2G_GLOBAL_RD",
        )
        if resp != RESP_OKAY or val != PATTERN_L2G:
            raise AssertionError(
                f"write_local_read_global got=0x{val:08x}/{resp_name(resp)} "
                f"want=0x{PATTERN_L2G:08x}/OKAY"
            )
        self._log("CHK-BASE-EQ-S1-L2G: write_local_read_global match")
        sb.expect_eq("CHK-BASE-EQ-S1-L2G", val, PATTERN_L2G)

        # write_global (s_axi) → read_local (J2A)
        await self._await_axi_ok(
            master,
            global_addr_1,
            write=True,
            wdata=PATTERN_G2L,
            label="S1_G2L_GLOBAL_WR",
        )
        got = await self._j2a_rd32(jtag, LOCAL_ADDR, "S1_G2L_LOCAL_RD")
        if got != PATTERN_G2L:
            raise AssertionError(
                f"write_global_read_local got=0x{got:08x} want=0x{PATTERN_G2L:08x}"
            )
        self._log("CHK-BASE-EQ-S1-G2L: write_global_read_local match")
        sb.expect_eq("CHK-BASE-EQ-S1-G2L", got, PATTERN_G2L)
        self.s1_ok = True

        # S2: move GLOBAL_BASE; offset preserved
        await self._program_aperture(jtag, GLOBAL_BASE_2)
        global_addr_2 = GLOBAL_BASE_2 + REP_OFFSET
        await self._j2a_wr32(jtag, LOCAL_ADDR, PATTERN_S2, "S2_LOCAL_WR")
        val2, resp2 = await self._await_axi_ok(
            master,
            global_addr_2,
            write=False,
            wdata=0,
            label="S2_GLOBAL_RD",
        )
        if resp2 != RESP_OKAY or val2 != PATTERN_S2:
            raise AssertionError(
                f"S2 offset_preserved got=0x{val2:08x}/{resp_name(resp2)} "
                f"want=0x{PATTERN_S2:08x}/OKAY @0x{global_addr_2:08x}"
            )
        self._log(
            f"CHK-BASE-EQ-S2: offset_preserved after GLOBAL_BASE move base2=0x{GLOBAL_BASE_2:08x}"
        )
        sb.expect_eq("CHK-BASE-EQ-S2", val2, PATTERN_S2)
        self.s2_ok = True

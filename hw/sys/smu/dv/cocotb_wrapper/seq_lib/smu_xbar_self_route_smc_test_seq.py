# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xbar_self_route_smc_test. No Force.

``hw/sys/smu/doc/index.adoc`` ("AXI Crossbar", the routing table by initiator
and decoded aperture) answers an ``smc_out`` request that matches the SMC
aperture with DECERR. ``hw/sys/smc/doc/fabric.adoc`` ("SMC input fabric")
sends an SMC-internal initiator's address inside the SMC window, at either the
local or the global base and REGION_SIZE long, to the local fabric rebased
onto LOCAL_BASE, so a request for the global window reaches the same register
as one for the local window and never leaves on ``smc_out``. The SMC master
the bench drives without firmware is the JTAG2AXI bridge.

With the outbound filter passing everything and GLOBAL_BASE and REGION_SIZE at
their reset values, a SINGLE_OP read at GLOBAL_BASE plus the VERSION_LO offset
answers SUCCESS with the VERSION_LO reset value, a write there answers SUCCESS,
and the crossbar's ``smc_out`` port (``smc_smn_out_*_count_o``) and the
``smc_in``, ``sep_in`` and ``ext_out`` taps do not move: the crossbar's
``smc_out`` self-route cell is unreachable from the built SMC. The controls in
the same run: the VERSION_LO read at the local alias answers SUCCESS with its
reset value before and after, and a write and read outside both apertures
leave on ``smu_axi_out`` with SUCCESS and return the written word, so the
outbound path is open, the ``smc_out`` taps count it, and the global-window
access stayed local by decode.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, SMC_CHIP_CONFIG_VERSION_LO_RESET
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_filter_helpers import (
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
    SMC_APERTURE_REGION_SIZE_REG,
    program_outbound0_pass_all,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

EVIDENCE = "CHK-XBAR-SELF-SMC-LOCAL"
GLOBAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
VERSION_LO_OFFSET = SMC_CHIP_CONFIG_VERSION_LO - SMC_APERTURE_LOCAL_BASE
SELF_ADDR = GLOBAL_BASE_RESET + VERSION_LO_OFFSET
# A word outside both apertures at their reset values (SEP: 0 to 16 MiB, SMC:
# GLOBAL_BASE to GLOBAL_BASE + 16 MiB), answered by the bench responder.
EGRESS_ADDR = 0x0200_0000
EGRESS_WORD = 0x5E1F_0C1D
SELF_WORD = 0xDEC0_DE5E
# smc_in, sep_in and ext_out taps that a global-window access must not move.
SUBORDINATE_TAPS = (
    "smc_xbar_in_aw_count_o",
    "smc_xbar_in_ar_count_o",
    "sep_xbar_in_aw_count_o",
    "sep_xbar_in_ar_count_o",
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
)
SMC_OUT_TAPS = ("smc_smn_out_aw_count_o", "smc_smn_out_ar_count_o")
EGRESS_TAPS = ("smu_axi_out_write_count_o", "smu_axi_out_read_count_o")
TAP_SETTLE_CYCLES = 64
EGRESS_POLL_CYCLES = 4000


class smu_xbar_self_route_smc_test_seq:
    """An SMC access into its own global aperture stays local and never reaches smc_out."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.done = False

    def _tap(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    def _taps(self, names: tuple[str, ...]) -> dict[str, int]:
        return {name: self._tap(name) for name in names}

    def _deltas(self, names: tuple[str, ...], before: dict[str, int]) -> dict[str, int]:
        return {name: self._tap(name) - before[name] for name in names}

    async def _rd32(self, addr: int, what: str) -> tuple[int, int]:
        status, rdata = await jtag2axi_single_read(
            self.jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        return status, axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> int:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        return status

    async def _version_lo(self, when: str) -> None:
        status, data = await self._rd32(SMC_CHIP_CONFIG_VERSION_LO, f"VERSION_LO {when}")
        self.sb.expect_eq(
            f"the local alias read of VERSION_LO answers SUCCESS with its reset value {when}",
            (status, data),
            (J2A_STATUS_SUCCESS, SMC_CHIP_CONFIG_VERSION_LO_RESET),
            evidence=EVIDENCE,
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._tap("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI gated; no access can run")

        # S1: the SMC aperture at its reset values, the outbound path open.
        st_base, base = await self._rd32(SMC_APERTURE_GLOBAL_BASE_REG, "GLOBAL_BASE")
        st_size, size = await self._rd32(SMC_APERTURE_REGION_SIZE_REG, "REGION_SIZE")
        sb.expect_eq(
            "GLOBAL_BASE and REGION_SIZE read their reset values, the SMC aperture under test",
            (st_base, base, st_size, size),
            (J2A_STATUS_SUCCESS, GLOBAL_BASE_RESET, J2A_STATUS_SUCCESS, REGION_SIZE_RESET),
        )
        await program_outbound0_pass_all(self.jtag, scoreboard=sb)
        await self._version_lo("before the global-window accesses")

        # S2: control, a word outside both apertures crosses smc_out and leaves on
        # smu_axi_out.
        before = self._taps(EGRESS_TAPS)
        before_out = self._taps(SMC_OUT_TAPS)
        st_wr = await self._wr32(EGRESS_ADDR, EGRESS_WORD, "egress")
        st_rd, word = await self._rd32(EGRESS_ADDR, "egress")
        for _ in range(EGRESS_POLL_CYCLES // TAP_SETTLE_CYCLES):
            if all(delta >= 1 for delta in self._deltas(EGRESS_TAPS, before).values()):
                break
            await ClockCycles(dut.clk_smu_i, TAP_SETTLE_CYCLES)
        egress = self._deltas(EGRESS_TAPS, before)
        smc_out = self._deltas(SMC_OUT_TAPS, before_out)
        self.log.info(
            "control: JTAG2AXI write/read at 0x%08x status=%d/%d data=0x%08x smc_out %s "
            "smu_axi_out %s",
            EGRESS_ADDR,
            st_wr,
            st_rd,
            word,
            smc_out,
            egress,
        )
        sb.expect_eq(
            f"a JTAG2AXI write and read at 0x{EGRESS_ADDR:08x}, outside both apertures, answer "
            "SUCCESS, return the written word, and each cross the crossbar's smc_out port and "
            "smu_axi_out once",
            (st_wr, st_rd, word, smc_out, egress),
            (
                J2A_STATUS_SUCCESS,
                J2A_STATUS_SUCCESS,
                EGRESS_WORD,
                dict.fromkeys(SMC_OUT_TAPS, 1),
                dict.fromkeys(EGRESS_TAPS, 1),
            ),
            evidence=EVIDENCE,
        )

        # S3: the SMC's own global window, GLOBAL_BASE plus the VERSION_LO offset.
        before_sub = self._taps(SUBORDINATE_TAPS)
        before_out = self._taps(SMC_OUT_TAPS)
        st_wr = await self._wr32(SELF_ADDR, SELF_WORD, "global window")
        st_rd, data = await self._rd32(SELF_ADDR, "global window")
        await ClockCycles(dut.clk_smu_i, TAP_SETTLE_CYCLES)
        subordinate = self._deltas(SUBORDINATE_TAPS, before_sub)
        smc_out = self._deltas(SMC_OUT_TAPS, before_out)
        self.log.info(
            "CHK-XBAR-SELF-SMC-LOCAL: write/read at 0x%08x (GLOBAL_BASE 0x%08x + VERSION_LO "
            "offset 0x%08x) status=%d/%d rdata=0x%08x; crossbar smc_out port %s; smc_in, sep_in "
            "and ext_out taps %s",
            SELF_ADDR,
            GLOBAL_BASE_RESET,
            VERSION_LO_OFFSET,
            st_wr,
            st_rd,
            data,
            smc_out,
            subordinate,
        )
        sb.expect_eq(
            f"CHK-XBAR-SELF-SMC-LOCAL the SINGLE_OP write and read at 0x{SELF_ADDR:08x} in the "
            "SMC's own global window answer SUCCESS, the read returns the VERSION_LO reset value, "
            "and neither reaches the crossbar's smc_out port nor the smc_in, sep_in and ext_out "
            "taps",
            (st_wr, st_rd, data, smc_out, subordinate),
            (
                J2A_STATUS_SUCCESS,
                J2A_STATUS_SUCCESS,
                SMC_CHIP_CONFIG_VERSION_LO_RESET,
                dict.fromkeys(SMC_OUT_TAPS, 0),
                dict.fromkeys(SUBORDINATE_TAPS, 0),
            ),
            evidence=EVIDENCE,
        )

        # S4: the bridge and the local alias recover.
        await self._version_lo("after the global-window accesses")
        self.done = True

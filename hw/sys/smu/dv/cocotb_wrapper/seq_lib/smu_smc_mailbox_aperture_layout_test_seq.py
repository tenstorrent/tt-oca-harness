# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_mailbox_aperture_layout_test.

Contract: SMU_SMC_MAILBOX_WDT_008   ANCHOR: smu_smc_mailbox_aperture_layout_test
Spec: axil_mailbox.rdl:46-244 (offsets, resets, rclr, ocah_hole_resp); axil_mailbox_smc_wrap.rdl:17-23
  (outbound_mailbox_N @N*0x1000, inbound_mailbox_N @N*0x1000+0x800); memmap.adoc; interface.adoc
  Access Results; smc.rdl smc_mailbox; cpu_ctrl.rdl SMC_ATTRIBUTES; periphs.adoc (32 mailboxes, depth 2).

Outbound mailbox 0 answers each of its ten offsets as its own register, WIRQT and IRQEN of mailboxes
0, 1 and 31 and of the inbound aperture of pair 0 are independent, SMC_ATTRIBUTES reports 32
mailboxes of depth 2 (the high word is read with a 4-byte upper-lane access; an 8-byte read and
slice replaces it when that access does not answer SUCCESS). The response above the registers is
observe-only (SF-019): only a resolved, non-BUSY status is compared. No force/deposit; all stimulus
is JTAG2AXI MMIO.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, tb_pin

J2A_POLL = 128
PRIMARY_RELEASE_CLK = 2000
RESET_DONE_NS = 10_000_000
MASK32 = 0xFFFF_FFFF
FEED_C0DE = 0xFEED_C0DE
FEED_DEAD = 0xFEED_DEAD
SC = {J2A_STATUS_SUCCESS: "SUCCESS", J2A_STATUS_SLVERR: "SLVERR", J2A_STATUS_BUSY: "BUSY"}

OFF = {
    "WRITE_DATA": 0x0,
    "READ_DATA": 0x8,
    "STATUS": 0x10,
    "ERROR_FLAGS": 0x18,
    "WIRQT": 0x20,
    "RIRQT": 0x28,
    "IRQS": 0x30,
    "IRQEN": 0x38,
    "IRQP": 0x40,
    "CTRL": 0x48,
}


def _out(idx: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_{idx}_{reg}_BASE_ADDR")


MBX0 = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
INB0_WIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_WIRQT_BASE_ADDR")
INB0_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
ATTR_LO = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
ATTR_HI = ATTR_LO + 4
HOLE_LOW = MBX0 + 0x50
HOLE_HIGH = MBX0 + 0x7F8


class smu_smc_mailbox_aperture_layout_test_seq:
    """SMU_SMC_MAILBOX_WDT_008: aperture layout, stride, independence and attributes."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.jtag = None
        self.j2a_count = 0
        self.j2a_last = "none"
        self.j2a_expired = False
        self.sites: list[tuple[str, str, str, str]] = []
        self.step_ts: dict[str, float] = {}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    @staticmethod
    def _sample(signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    async def _j2a(
        self, write: bool, addr: int, data: int = 0, size: int = SMC_DBG_AXSIZE_4B
    ) -> tuple[int, int]:
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    data & MASK32,
                    wstrb=0x0F,
                    size=size,
                    poll_limit=J2A_POLL,
                    require_complete=True,
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag,
                    addr,
                    size=size,
                    poll_limit=J2A_POLL,
                    require_complete=True,
                )
        except (TimeoutError, AssertionError) as exc:
            self.j2a_expired = True
            self.j2a_last = f"EXPIRED {exc}"
            raise
        require_jtag_tdo_resolved(f"MBX {'WR' if write else 'RD'} @0x{addr:08x}")
        self.j2a_count += 1
        self.j2a_last = f"status={status}"
        return status, int(raw)

    async def _wr(self, cell: str, addr: int, value: int) -> int:
        status, _ = await self._j2a(True, addr, value)
        self._log(
            f"CELL {cell} addr=0x{addr:08x} status={SC.get(status, status)} value=0x{value:08x}"
        )
        return status

    async def _rd(self, cell: str, addr: int) -> tuple[int, int]:
        status, raw = await self._j2a(False, addr)
        value = raw & MASK32
        self._log(
            f"CELL {cell} addr=0x{addr:08x} status={SC.get(status, status)} value=0x{value:08x}"
        )
        return status, value

    async def _rd_hi(self, cell: str, addr: int) -> tuple[int, int]:
        status, raw = await self._j2a(False, addr)
        value = (raw >> 32) & MASK32
        self._log(
            f"CELL {cell} addr=0x{addr:08x} status={SC.get(status, status)} value=0x{value:08x}"
        )
        return status, value

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        # S1 SETUP
        try:
            await with_timeout(self.cfg.reset_done.wait(), RESET_DONE_NS, "ns")
        except TimeoutError:
            self.sites.append(("reset_done", f"{RESET_DONE_NS} ns", "not set", "EXPIRED"))
            raise
        self.sites.append(("reset_done", f"{RESET_DONE_NS} ns", "set", "ok"))
        self._mark("S1", "SETUP: reset_done, primary reset released, TAP reset, IDCODE, J2A gate")
        primary = smc_primary_reset(dut)
        last = None
        for waited in range(PRIMARY_RELEASE_CLK):
            last = self._sample(primary, "rst_primary_smc_clk_n_o")
            if last == 1:
                self.sites.append(
                    (
                        "primary_release",
                        f"{PRIMARY_RELEASE_CLK} clk_smu_i cycles",
                        f"rst_primary_smc_clk_n_o=1 after {waited} cycles",
                        "ok",
                    )
                )
                break
            await ClockCycles(dut.clk_smu_i, 1)
        else:
            self.sites.append(
                (
                    "primary_release",
                    f"{PRIMARY_RELEASE_CLK} clk_smu_i cycles",
                    f"rst_primary_smc_clk_n_o={last}",
                    "EXPIRED",
                )
            )
            raise AssertionError(f"TIMEOUT s1_primary_release: bound={PRIMARY_RELEASE_CLK}")
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample(tb_pin(dut, "tb_smc_jtag2axi_security_disable"), "security_disable")
        if gate & 1:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")

        # S2 outbound mailbox 0 offsets
        self._mark("S2", "outbound mailbox 0: ten offsets, WIRQT and IRQEN round trips")
        wd = await self._rd("ten_offsets_distinct.WRITE_DATA", MBX0 + OFF["WRITE_DATA"])
        rd = await self._rd("ten_offsets_distinct.READ_DATA", MBX0 + OFF["READ_DATA"])
        _, status = await self._rd("ten_offsets_distinct.STATUS", MBX0 + OFF["STATUS"])
        _, err = await self._rd("ten_offsets_distinct.ERROR_FLAGS", MBX0 + OFF["ERROR_FLAGS"])
        _, rirqt = await self._rd("ten_offsets_distinct.RIRQT", MBX0 + OFF["RIRQT"])
        _, irqs = await self._rd("ten_offsets_distinct.IRQS", MBX0 + OFF["IRQS"])
        _, irqp = await self._rd("ten_offsets_distinct.IRQP", MBX0 + OFF["IRQP"])
        ctrl = await self._rd("ten_offsets_distinct.CTRL", MBX0 + OFF["CTRL"])
        await self._wr("wirqt_roundtrip.write", MBX0 + OFF["WIRQT"], 0x1)
        _, wirqt_rb = await self._rd("wirqt_roundtrip.read", MBX0 + OFF["WIRQT"])
        await self._wr("irqen_roundtrip.write", MBX0 + OFF["IRQEN"], 0x5)
        _, irqen_rb = await self._rd("irqen_roundtrip.read", MBX0 + OFF["IRQEN"])
        sb.expect_eq(
            "CHK-MBX-OFFSET-MAP (WRITE_DATA, READ_DATA, STATUS, ERROR_FLAGS, RIRQT, IRQS, IRQP, "
            "CTRL, WIRQT rb, IRQEN rb)",
            (wd, rd, status, err, rirqt, irqs, irqp, ctrl, wirqt_rb, irqen_rb),
            (
                (J2A_STATUS_SUCCESS, FEED_C0DE),
                (J2A_STATUS_SLVERR, FEED_DEAD),
                0x1,
                0x1,
                0,
                0x4,
                0,
                (J2A_STATUS_SUCCESS, 0),
                0x1,
                0x5,
            ),
            evidence="MBX_OFFSET_MAP",
        )

        # S3 WIRQT stride
        self._mark("S3", "WIRQT of mailbox 1 and 31 against mailbox 0")
        _, w1 = await self._rd("mbx1.WIRQT", _out(1, "WIRQT"))
        _, w31 = await self._rd("mbx31.WIRQT", _out(31, "WIRQT"))
        await self._wr("mbx31.WIRQT_write", _out(31, "WIRQT"), 0x1)
        _, w31_rb = await self._rd("mbx31.WIRQT_readback", _out(31, "WIRQT"))
        _, w1_after = await self._rd("independent_wirqt.mbx1", _out(1, "WIRQT"))
        _, w0_after = await self._rd("independent_wirqt.mbx0", _out(0, "WIRQT"))
        sb.expect_eq(
            "CHK-MBX-STRIDE-WIRQT (mbx1, mbx31, mbx31 rb, mbx1 after, mbx0 after)",
            (w1, w31, w31_rb, w1_after, w0_after),
            (0, 0, 0x1, 0, 0x1),
            evidence="MBX_STRIDE_WIRQT",
        )

        # S4 IRQEN independence
        self._mark("S4", "IRQEN of mailbox 1 and 31 against mailbox 0")
        _, e1 = await self._rd("mbx0_vs_mbx1.mbx1_IRQEN", _out(1, "IRQEN"))
        _, e31 = await self._rd("mbx0_vs_mbx31.mbx31_IRQEN", _out(31, "IRQEN"))
        await self._wr("mbx0_vs_mbx1.mbx1_IRQEN_write", _out(1, "IRQEN"), 0x2)
        _, e1_rb = await self._rd("mbx0_vs_mbx1.mbx1_IRQEN_readback", _out(1, "IRQEN"))
        _, e0_after = await self._rd("mbx0_vs_mbx1.mbx0_IRQEN", _out(0, "IRQEN"))
        _, e31_after = await self._rd("mbx0_vs_mbx31.mbx31_IRQEN_after", _out(31, "IRQEN"))
        sb.expect_eq(
            "CHK-MBX-IRQEN-INDEP (mbx1, mbx31, mbx1 rb, mbx0 after, mbx31 after)",
            (e1, e31, e1_rb, e0_after, e31_after),
            (0, 0, 0x2, 0x5, 0),
            evidence="MBX_IRQEN_INDEP",
        )

        # S5 inbound aperture
        self._mark("S5", "inbound aperture of pair 0 against outbound mailbox 0")
        _, i_irqen = await self._rd("inbound_independent_of_outbound.IRQEN", INB0_IRQEN)
        _, i_wirqt = await self._rd("inbound_independent_of_outbound.WIRQT", INB0_WIRQT)
        await self._wr("inbound_independent_of_outbound.IRQEN_write", INB0_IRQEN, 0x1)
        _, i_rb = await self._rd("inbound_independent_of_outbound.IRQEN_readback", INB0_IRQEN)
        _, o_irqen = await self._rd("inbound_independent_of_outbound.out_IRQEN", _out(0, "IRQEN"))
        _, o_wirqt = await self._rd("inbound_independent_of_outbound.out_WIRQT", _out(0, "WIRQT"))
        sb.expect_eq(
            "CHK-MBX-INBOUND-INDEP (in IRQEN, in WIRQT, in IRQEN rb, out IRQEN, out WIRQT)",
            (i_irqen, i_wirqt, i_rb, o_irqen, o_wirqt),
            (0, 0, 0x1, 0x5, 0x1),
            evidence="MBX_INBOUND_INDEP",
        )

        # S6 SMC_ATTRIBUTES
        self._mark("S6", "SMC_ATTRIBUTES low and high word")
        await self._rd("attributes_32_mailboxes_depth_2.low", ATTR_LO)
        hi_status, hi = await self._rd_hi("attributes_32_mailboxes_depth_2.high", ATTR_HI)
        if hi_status != J2A_STATUS_SUCCESS:
            hi_status, raw64 = await self._j2a(False, ATTR_LO, size=SMC_DBG_AXSIZE_8B)
            hi = (raw64 >> 32) & MASK32
            self._log(
                f"CELL attributes_32_mailboxes_depth_2.read64 addr=0x{ATTR_LO:08x} "
                f"status={SC.get(hi_status, hi_status)} value=0x{raw64:016x}"
            )
        sb.expect_eq(
            "CHK-MBX-SMC-ATTRIBUTES (status, num_mailboxes, mailbox_depth)",
            (hi_status, (hi >> 8) & 0x3F, (hi >> 4) & 0xF),
            (J2A_STATUS_SUCCESS, 32, 2),
            evidence="MBX_SMC_ATTRIBUTES",
        )

        # S7 above the registers (observe-only)
        self._mark("S7", "offsets 0x50 and 0x7F8 read, offset 0x50 write")
        s_a, d_a = await self._rd("above_registers_response_recorded.rd_0x50", HOLE_LOW)
        s_b, d_b = await self._rd("above_registers_response_recorded.rd_0x7f8", HOLE_HIGH)
        s_c = await self._wr("above_registers_response_recorded.wr_0x50", HOLE_LOW, 0x0)
        self._log(
            f"CHK-MBX-APERTURE-HOLE-LOG: off=0x50 rd status={SC.get(s_a, s_a)} data=0x{d_a:08x} ; "
            f"wr status={SC.get(s_c, s_c)}; off=0x7f8 rd status={SC.get(s_b, s_b)} data=0x{d_b:08x}"
        )
        sb.expect_eq(
            "CHK-MBX-APERTURE-HOLE-LOG (rd 0x50, rd 0x7f8, wr 0x50 resolved non-BUSY)",
            (s_a != J2A_STATUS_BUSY, s_b != J2A_STATUS_BUSY, s_c != J2A_STATUS_BUSY),
            (True, True, True),
            evidence="MBX_APERTURE_HOLE_LOG",
        )

        # S8 timeout inventory
        self._mark("S8", "TIMEOUT: bounded waits with last state")
        self.sites.append(
            (
                "j2a",
                f"{J2A_POLL} polls x {self.j2a_count} accesses",
                self.j2a_last,
                "EXPIRED" if self.j2a_expired else "ok",
            )
        )
        for site, bound, last_state, outcome in self.sites:
            self._log(f"TIMEOUT-PATH {site}: bound={bound} {outcome} last={last_state}")
        expired = sum(1 for s in self.sites if s[3] != "ok")
        names = [s[0] for s in self.sites]
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={names} expired={expired} j2a_accesses={self.j2a_count}"
        )
        sb.expect_eq("CHK-TIMEOUT-PATHS expired", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("CHK-TIMEOUT-PATHS sites", names, ["reset_done", "primary_release", "j2a"])
        sb.expect_eq("CHK-TIMEOUT-PATHS j2a accesses", self.j2a_count, 35)

        lane_vector = self._sample(dut.ext_mailbox_interrupts_o, "ext_mailbox_interrupts_o")
        self._log(
            f"CELL final lane_vector=0x{lane_vector:08x} mbx0_irqen=0x{e0_after:x} "
            f"mbx1_irqen=0x{e1_rb:x} inbound0_irqen=0x{i_rb:x}"
        )
        self.step_ts["PASS"] = time.monotonic()

        order = [f"S{i}" for i in range(1, 9)] + ["PASS"]
        for step in order:
            if step not in self.step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step}")
        advancing = sum(1 for a, b in zip(order, order[1:]) if self.step_ts[b] >= self.step_ts[a])
        self._log(f"CHK-NONVAC: Ordered fence {'<'.join(order)} advancing={advancing}")
        sb.expect_eq(
            "CHK-NONVAC ordered step count", advancing, len(order) - 1, evidence="CHK-NONVAC"
        )

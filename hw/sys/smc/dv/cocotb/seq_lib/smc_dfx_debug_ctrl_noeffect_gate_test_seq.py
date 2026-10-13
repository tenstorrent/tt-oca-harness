# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DEBUG_CTRL no-effect fields, bit 31, DFD observables and register access around cg_en.

Contract SMC_JTAG_DM_021, anchor smc_dfx_debug_ctrl_noeffect_gate_test.
Scenarios JDM-DFX-DEBUGCTRL-NOEFFECT.S1 .. S4, JDM-DFX-CLKGATE.S5 and S7.
Spec: dfx_ctrl_status.rdl DEBUG_CTRL, dfd.adoc Design-for-Debug,
memmap.adoc Base Config and DFX Status.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import DFX_STATUS_IDLE, dfx_status_u32, smc_addr
from .smc_csr_seq_utils import ALL_ONES_WORD, SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
OBSERVE_CYCLES = 256
OVERLAP_POLL_MAX_CYCLES = 4096
DEBUG_CTRL = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR")
STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
DEBUG_BUS_MUX = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR")
BIT31 = 1 << 31
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_TERMS = (
    "BRINGUP_BASELINE",
    "FIELDS_HOLD",
    "EFFECT_FIELDS_CLEAR",
    "COLD_RESET_BIT31",
    "NO_OBSERVABLE_256",
    "INFLIGHT_OVERLAP_MEASURED",
    "STATUS_ACCESS_WITH_CG_EN",
)
CHK_ORDER = (
    ("CHK-DEBUGCTRL-FIELD-HOLD", "S2"),
    ("CHK-DEBUGCTRL-EFFECT-CLEAR", "S3"),
    ("CHK-DEBUGCTRL-RESET-BIT31", "S4"),
    ("CHK-DEBUGCTRL-NO-OBSERVABLE", "S5"),
    ("CHK-CLKGATE-INFLIGHT", "S6"),
    ("CHK-CLKGATE-STATUS-ACCESS", "S7"),
    ("CHK-TIMEOUT-PATHS", "S8"),
)
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}
PROBES = ("tb_cla_clock_stop", "tb_cla_halt_clock_global")


def _field(name: str) -> tuple[int, int, int]:
    prefix = f"DFX_CTRL_STATUS__DEBUG_CTRL__{name}"
    mask = dfx_status_u32(f"{prefix}_bm")
    lsb = dfx_status_u32(f"{prefix}_bp")
    return mask, lsb, mask >> lsb


FIELDS = {
    name: _field(name)
    for name in (
        "CHIPLET_ENABLE",
        "GPIO_EN",
        "CG_EN",
        "FORCE_CLK_EN",
        "DTB_NS_EN",
        "DTB_EW_EN",
        "XTRIG_CLK_HALT_MASK",
        "DEBUG_MARKER",
    )
}
XTRIG_MASK, XTRIG_LSB, _ = FIELDS["XTRIG_CLK_HALT_MASK"]
XTRIG_BIT0 = 1 << XTRIG_LSB
CG_EN_MASK = FIELDS["CG_EN"][0]
FORCE_MASK = FIELDS["FORCE_CLK_EN"][0]
DEBUG_MARKER_VALUE = 0xA5
NOEFFECT_VALUES = {
    "CHIPLET_ENABLE": 0x3 << FIELDS["CHIPLET_ENABLE"][1],
    "GPIO_EN": FIELDS["GPIO_EN"][0],
    "DTB_NS_EN": FIELDS["DTB_NS_EN"][0],
    "DTB_EW_EN": FIELDS["DTB_EW_EN"][0],
    "XTRIG_BITS_15_1": XTRIG_MASK & ~XTRIG_BIT0,
    "DEBUG_MARKER": DEBUG_MARKER_VALUE << FIELDS["DEBUG_MARKER"][1],
}
ALL_NOEFFECT = sum(NOEFFECT_VALUES.values())


class _OverlapWatch:
    """Records the SEP_IN handshake cycles of one read and one write in flight."""

    def __init__(self) -> None:
        self.stop = False
        self.cycle = 0
        self.ar_hs: int | None = None
        self.aw_hs: int | None = None
        self.r_done: int | None = None
        self.b_done: int | None = None

    @staticmethod
    def _bit(name: str) -> int:
        assert hasattr(cocotb.top, name), f"{name} is not a signal of the testbench top"
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    async def run(self) -> None:
        clk = cocotb.top.clk_smc_i
        while not self.stop:
            await FallingEdge(clk)
            self.cycle += 1
            if self.ar_hs is None and self._bit("s_axi_arvalid") and self._bit("s_axi_arready"):
                self.ar_hs = self.cycle
            if self.aw_hs is None and self._bit("s_axi_awvalid") and self._bit("s_axi_awready"):
                self.aw_hs = self.cycle
            if self.r_done is None and self._bit("s_axi_rvalid") and self._bit("s_axi_rready"):
                if self._bit("s_axi_rlast"):
                    self.r_done = self.cycle
            if self.b_done is None and self._bit("s_axi_bvalid") and self._bit("s_axi_bready"):
                self.b_done = self.cycle

    def overlap(self) -> int:
        """Cycles during which both accesses were admitted and neither had answered."""
        marks = (self.ar_hs, self.aw_hs, self.r_done, self.b_done)
        assert None not in marks, f"group handshakes incomplete: {self.state()}"
        return min(self.r_done, self.b_done) - max(self.ar_hs, self.aw_hs)

    def state(self) -> str:
        return (
            f"ar_hs={self.ar_hs} aw_hs={self.aw_hs} r_done={self.r_done} b_done={self.b_done} "
            f"cycles={self.cycle}"
        )


class smc_dfx_debug_ctrl_noeffect_gate_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """DEBUG_CTRL no-effect readback, cold reset, bit 31, probes and cg_en access liveness."""

    def __init__(self, name: str = "smc_dfx_debug_ctrl_noeffect_gate_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _dispatch_reset_item(self, item) -> None:
        await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

    @staticmethod
    def _probes() -> tuple[int, int]:
        dut = cocotb.top
        for name in PROBES:
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
            value = getattr(dut, name).value
            assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(dut.tb_cla_clock_stop.value), int(dut.tb_cla_halt_clock_global.value)

    async def _sense_wait(self, label: str) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(cocotb.top.tb_fuse_sense_done.value)
        assert sense == 1, f"{label}: tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                f"{label}_fuse_sense",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )

    async def _read(self, name: str) -> int:
        got = await self.csr_read(name, DEBUG_CTRL, length=4)
        assert isinstance(got, int), f"{name}: read data not resolvable"
        self._last_access = f"{name}@0x{DEBUG_CTRL:08x} rdata=0x{got:08x}"
        return got & ALL_ONES_WORD

    async def _write_expect(self, name: str, data: int) -> int:
        await self.csr_write(name, DEBUG_CTRL, data, length=4)
        got = await self._read(f"{name}_RB")
        assert got == data, f"{name}: wrote 0x{data:08x}, read 0x{got:08x} ({self._last_access})"
        return got

    async def _cold_reset(self) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        item = await self._wait_state(
            "cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        assert int(cocotb.top.tb_fuse_sense_done.value) == 0, (
            "tb_fuse_sense_done is still 1 with the cold reset asserted"
        )
        self._waits.append(
            (
                "cold_assert",
                f"{self.ASSERT_BOUND_REF_CYCLES}ref_cyc(enforced-by=smc_reset_seq_base.py)",
                f"matched after {item.wait_ref_cycles}ref_cyc",
            )
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        item = await self._wait_released("cold release")
        self._waits.append(
            (
                "cold_release",
                f"{self.RELEASE_BOUND_REF_CYCLES}ref_cyc(enforced-by=smc_reset_seq_base.py)",
                f"matched after {item.wait_ref_cycles}ref_cyc",
            )
        )
        await self._sense_wait("post_cold_reset")

    async def body(self) -> None:
        axi_bound = self.env.cfg.axi_timeout_ns

        # S1
        await self._sense_wait("bringup")
        base = await self._read("DEBUG_CTRL_BASELINE")
        assert base == 0, f"DEBUG_CTRL baseline 0x{base:08x}, expected 0 ({self._last_access})"
        base_stop, base_halt = self._probes()
        cocotb.log.info(
            "BASELINE: DEBUG_CTRL=0x%08x tb_cla_clock_stop=%d tb_cla_halt_clock_global=%d",
            base,
            base_stop,
            base_halt,
        )
        self._stamp("S1")

        # S2
        cells = []
        for fname, value in NOEFFECT_VALUES.items():
            await self._write_expect(f"{fname}_ALONE", value)
            cells.append(f"{fname}=0x{value:08x}")
        await self._write_expect("ALL_NOEFFECT", ALL_NOEFFECT)
        cells.append(f"ALL=0x{ALL_NOEFFECT:08x}")
        self._stamp("S2")
        self._chk(
            "CHK-DEBUGCTRL-FIELD-HOLD",
            f"{len(cells)} cells read back exactly (every other field 0), OKAY: {','.join(cells)}",
        )

        # S3
        held = await self._read("DEBUG_CTRL_ALL_SET")
        assert held == ALL_NOEFFECT, f"all-set read 0x{held:08x} want 0x{ALL_NOEFFECT:08x}"
        effect = held & (CG_EN_MASK | FORCE_MASK | XTRIG_BIT0)
        assert effect == 0, (
            f"effect bits set with every no-effect field set: cg_en={held & CG_EN_MASK != 0} "
            f"force_clk_en={held & FORCE_MASK != 0} xtrig_bit0={held & XTRIG_BIT0 != 0} "
            f"(read 0x{held:08x})"
        )
        self._stamp("S3")
        self._chk(
            "CHK-DEBUGCTRL-EFFECT-CLEAR",
            f"DEBUG_CTRL=0x{held:08x} with every no-effect field set: cg_en=0 force_clk_en=0 "
            "xtrig_clk_halt_mask bit 0=0",
        )

        # S4
        await self._cold_reset()
        after_reset = await self._read("DEBUG_CTRL_AFTER_COLD")
        assert after_reset == 0, (
            f"DEBUG_CTRL read 0x{after_reset:08x} after the cold reset, expected 0"
        )
        await self.csr_write("DEBUG_CTRL_ONES", DEBUG_CTRL, ALL_ONES_WORD, length=4)
        ones_back = await self._read("DEBUG_CTRL_ONES_RB")
        assert ones_back & BIT31 == 0, (
            f"register bit 31 read 1 after 0x{ALL_ONES_WORD:08x} was written "
            f"(read 0x{ones_back:08x})"
        )
        await self._write_expect("DEBUG_CTRL_RESTORE", 0)
        self._stamp("S4")
        self._chk(
            "CHK-DEBUGCTRL-RESET-BIT31",
            f"DEBUG_CTRL=0x{after_reset:08x} after a cold reset; write 0x{ALL_ONES_WORD:08x} read "
            f"back 0x{ones_back:08x} with bit 31 = 0; restored to 0 (which reset restores the "
            "field is SF-030)",
        )

        # S5
        await self._write_expect("ALL_NOEFFECT_AGAIN", ALL_NOEFFECT)
        stop_hi = halt_hi = 0
        for _ in range(OBSERVE_CYCLES):
            await RisingEdge(cocotb.top.clk_smc_i)
            stop, halt = self._probes()
            stop_hi += stop
            halt_hi += halt
        assert stop_hi == 0 and halt_hi == 0, (
            f"probe rose in {OBSERVE_CYCLES} clk_smc cycles with every no-effect field set: "
            f"tb_cla_clock_stop high {stop_hi}, tb_cla_halt_clock_global high {halt_hi}"
        )
        self._waits.append(
            ("probe_window", f"{OBSERVE_CYCLES}clk_smc(enforced-by=leaf loop)", "both probes 0")
        )
        self._stamp("S5")
        self._chk(
            "CHK-DEBUGCTRL-NO-OBSERVABLE",
            f"tb_cla_clock_stop and tb_cla_halt_clock_global stayed 0 for {OBSERVE_CYCLES} "
            f"clk_smc cycles with DEBUG_CTRL=0x{ALL_NOEFFECT:08x}; xtrigger_ss_o lanes are not "
            "exported (SF-038)",
        )

        # S6
        await self._write_expect("S6_RESTORE_ZERO", 0)
        rd = SmcSysAxiItem("rd_DEBUG_BUS_MUX_GROUP")
        rd.op = SmcSysAxiOp.READ
        rd.addr = DEBUG_BUS_MUX
        rd.length = 8
        rd.allow_error = True
        wr = SmcSysAxiItem("wr_DEBUG_CTRL_CG_EN_GROUP")
        wr.op = SmcSysAxiOp.WRITE
        wr.addr = DEBUG_CTRL
        wr.length = 4
        wr.wdata = CG_EN_MASK
        wr.allow_error = True
        group = SmcSysAxiGroupItem("dfx_cg_en_inflight_group", [rd, wr])
        watch = _OverlapWatch()
        watcher = cocotb.start_soon(watch.run())
        await _OneShot(group, "dfx_cg_en_inflight_os").start(self.env.sys_axi_agent.sequencer)
        await RisingEdge(cocotb.top.clk_smc_i)
        watch.stop = True
        await watcher
        self.accesses += 2
        for member in (rd, wr):
            assert member.resp_code is not None, f"{member.get_name()}: no response code"
        overlap = watch.overlap()
        assert overlap > 0, f"the read and write group never overlapped ({watch.state()})"
        self._last_access = (
            f"group rd resp={RESP_NAMES.get(rd.resp_code)} wr resp={RESP_NAMES.get(wr.resp_code)} "
            f"{watch.state()}"
        )
        self._waits.append(
            ("inflight_group", f"{axi_bound}ns(enforced-by=env cfg)", self._last_access)
        )
        await self._write_expect("S6_CG_EN_RESTORE", 0)
        self._stamp("S6")
        self._chk(
            "CHK-CLKGATE-INFLIGHT",
            f"DEBUG_BUS_MUX 8-byte read resp={RESP_NAMES.get(rd.resp_code)} "
            f"rdata=0x{rd.rdata:x} and DEBUG_CTRL cg_en write resp={RESP_NAMES.get(wr.resp_code)} "
            f"both completed within {axi_bound}ns, overlapped {overlap} clk_smc cycles "
            f"({watch.state()}); clock effect is SF-033; cg_en restored to 0",
        )

        # S7
        await self.csr_write("S7_CG_EN_ON", DEBUG_CTRL, CG_EN_MASK, length=4)
        status = await self.csr_read("STATUS_SMU", STATUS_SMU, expected=DFX_STATUS_IDLE, length=8)
        assert status == DFX_STATUS_IDLE, f"STATUS_SMU=0x{status:x} want 0x{DFX_STATUS_IDLE:x}"
        cg_on = CG_EN_MASK | NOEFFECT_VALUES["DEBUG_MARKER"]
        await self._write_expect("S7_CG_EN_WRITE", cg_on)
        await self._write_expect("S7_CG_EN_RESTORE", 0)
        self._stamp("S7")
        self._chk(
            "CHK-CLKGATE-STATUS-ACCESS",
            f"with cg_en=1 force_clk_en=0 STATUS_SMU=0x{status:x} (DFX_STATUS_IDLE) OKAY and "
            f"DEBUG_CTRL write 0x{cg_on:08x} read back exactly; cg_en restored to 0",
        )

        # S8
        self._waits.append(
            ("sep_in_access", f"{axi_bound}ns(enforced-by=env cfg)", self._last_access)
        )
        await RisingEdge(cocotb.top.clk_smc_i)
        self._stamp("S8")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert tuple(steps) == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")

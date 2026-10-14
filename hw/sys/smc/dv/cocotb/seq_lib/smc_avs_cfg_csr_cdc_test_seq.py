# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CFG_0, AVS_CFG_1 and AVS_CONFIG behaviour across the AVSBus CDC bridge.

Sources: hw/ip/avsbus_controller/regs/avsbus_controller.rdl, hw/sys/smc/doc/clk_rst.adoc.

Every AVS_CFG_1 clock-configuration change follows the programmer's order: set
TURN_OFF_ALL_PREMUX_CLOCKS, write the fields, clear it. AVS_CFG_1 and AVS_CFG_0 are
returned to the words read at the start.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Edge, First, Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_avsbus_protocol_utils import AVS_CFG_0, AVS_CFG_1, avs_field
from .smc_csr_seq_utils import SmcCsrSeq

AVS_CONFIG = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CONFIG_BASE_ADDR")

_F = "AVSBUS_CONTROLLER__AVS_CFG_1__"
SELECT_BM = avs_field(_F + "AVS_CLOCK_SELECT_bm")
SELECT_RESET = avs_field(_F + "AVS_CLOCK_SELECT_reset")
STOP_BM = avs_field(_F + "STOP_AVS_CLOCK_ON_IDLE_bm")
FORCE_BM = avs_field(_F + "FORCE_SLAVE_RESYNC_OPERATION_bm")
TURN_OFF_BM = avs_field(_F + "TURN_OFF_ALL_PREMUX_CLOCKS_bm")
DIVIDER_BM = avs_field(_F + "CLK_DIVIDER_VALUE_bm")
DIVIDER_BP = avs_field(_F + "CLK_DIVIDER_VALUE_bp")
NUMERATOR_BM = avs_field(_F + "CLK_DIVIDER_DUTY_CYCLE_NUMERATOR_bm")
NUMERATOR_BP = avs_field(_F + "CLK_DIVIDER_DUTY_CYCLE_NUMERATOR_bp")
GPIO_ENABLE_RESET = avs_field("AVSBUS_CONTROLLER__AVS_CONFIG__AVS_GPIO_ENABLE_reset")
GPIO_ENABLE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CONFIG__AVS_GPIO_ENABLE_bm")
MAX_RETRIES_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__MAX_RETRIES_bm")
RESYNC_INTERVAL_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__RESYNC_INTERVAL_bm")

DEFINED_BM = SELECT_BM | STOP_BM | FORCE_BM | TURN_OFF_BM | DIVIDER_BM | NUMERATOR_BM
WORD_MASK = 0xFFFF_FFFF
UNALLOCATED_BM = WORD_MASK & ~DEFINED_BM

SELECT_REFCLK = 0b10
DIVIDER_S3 = 0x08
NUMERATOR_S3 = 0x40
DIVIDER_LANE2 = 0x10
LANE2_STROBE = 0x4
FORCE_WAIT_PERIPH_CYCLES = 64
MEASURE_PERIODS = 8
ACCESS_TIMEOUT_NS = 50_000
EDGE_TIMEOUT_NS = 100_000
OKAY = 0

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_TERMS = (
    "RESET_WORDS_READ",
    "FIELDS_WRITTEN",
    "BYTE_LANE_WRITTEN",
    "FORCE_WRITTEN",
    "UNALLOCATED_WRITTEN",
    "DIVIDER_RT",
    "ORDER_CHECKED",
    "AVS_CFG_1_RESTORED",
)
CHECKER_STEPS = (
    ("CHK-AVS-CSR-RESET", "S2"),
    ("CHK-AVS-CSR-FIELDS", "S3"),
    ("CHK-AVS-CSR-BYTE-LANE-2", "S4"),
    ("CHK-AVS-CSR-FORCE-PULSE", "S5"),
    ("CHK-AVS-CSR-UNALLOCATED", "S6"),
    ("CHK-CDC-AVS-RT", "S7"),
    ("CHK-CDC-AVS-ORDER", "S8"),
)


def _field(word: int, mask: int, pos: int) -> int:
    return (word & mask) >> pos


class smc_avs_cfg_csr_cdc_test_seq(SmcCsrSeq):
    """AVS_CFG_1 and AVS_CONFIG fields, strobes, pulse and ordering through the CDC bridge."""

    def __init__(self, name: str = "smc_avs_cfg_csr_cdc_test_seq") -> None:
        super().__init__(name)
        self.stamps: dict[str, int] = {}
        self.chk_stamps: dict[str, int] = {}
        self.chk_order: list[str] = []
        self.last_resp: int | None = None
        self.edge_waits = 0
        self.last_edge_state = "no edge wait yet"
        self.force_wait_state = "no periph wait yet"

    async def _access(
        self, label: str, op: SmcSysAxiOp, addr: int, data: int = 0, wstrb: int | None = None
    ) -> int:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.timeout_ns = ACCESS_TIMEOUT_NS
        if op == SmcSysAxiOp.WRITE:
            item.wdata = data
            if wstrb is not None:
                item.wstrb = wstrb
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.last_resp = item.resp_code
        assert item.resp_code == OKAY, (
            f"{label} @ 0x{addr:08x}: response code {item.resp_code}, expected OKAY ({OKAY})"
        )
        return item.rdata

    async def _rd(self, label: str, addr: int, expected: int | None = None) -> int:
        got = await self._access(label, SmcSysAxiOp.READ, addr)
        if expected is not None:
            assert got == expected, f"{label}: read 0x{got:08x}, expected 0x{expected:08x}"
        return got

    async def _wr(self, label: str, addr: int, data: int, wstrb: int | None = None) -> None:
        await self._access(label, SmcSysAxiOp.WRITE, addr, data, wstrb)

    async def _gated_write(self, label: str, current: int, new: int) -> int:
        """Change clock-configuration fields in the programmer's gated order."""
        assert not (current | new) & TURN_OFF_BM, f"{label}: gated change needs TURN_OFF clear"
        await self._wr(f"{label}_GATE_ON", AVS_CFG_1, current | TURN_OFF_BM)
        await self._wr(f"{label}_FIELDS", AVS_CFG_1, new | TURN_OFF_BM)
        await self._wr(f"{label}_GATE_OFF", AVS_CFG_1, new)
        return await self._rd(f"{label}_RB", AVS_CFG_1, expected=new)

    @staticmethod
    def _clk() -> int:
        raw = cocotb.top.tb_avs_clk_from_dut.value
        assert raw.is_resolvable, f"the AVS clock at the pad is not resolvable: {raw}"
        return int(raw)

    async def _next_edge(self, label: str) -> None:
        self.edge_waits += 1
        result = await First(
            Edge(cocotb.top.tb_avs_clk_from_dut), Timer(EDGE_TIMEOUT_NS, unit="ns")
        )
        self.last_edge_state = f"{label} level={self._clk()}"
        if not isinstance(result, Edge):
            raise AssertionError(
                f"{label}: the AVS clock at the pad did not change in {EDGE_TIMEOUT_NS} ns; "
                f"it reads {self._clk()}"
            )

    async def _period_ps(self, label: str) -> int:
        """Span of MEASURE_PERIODS AVS clock periods at the pad, in ps."""
        while self._clk() != 0:
            await self._next_edge(f"{label} align low")
        await self._next_edge(f"{label} first rise")
        start = get_sim_time("ps")
        for period in range(MEASURE_PERIODS):
            await self._next_edge(f"{label} fall {period}")
            await self._next_edge(f"{label} rise {period}")
        span = get_sim_time("ps") - start
        assert span > 0, f"{label}: {MEASURE_PERIODS} AVS clock periods measured 0 ps"
        return span

    def _stamp(self, step: str) -> None:
        now = int(get_sim_time("ps"))
        self.stamps[step] = now
        cocotb.log.info("STEP %s: complete at %d ps", step, now)

    def _chk(self, chk_id: str, text: str) -> None:
        self.chk_order.append(chk_id)
        self.chk_stamps[chk_id] = int(get_sim_time("ps"))
        cocotb.log.info("%s: %s", chk_id, text)

    def _assert_fence(self) -> tuple[list[int], str]:
        assert list(self.stamps) == list(STEPS), f"step order {list(self.stamps)} != {STEPS}"
        times = [self.stamps[s] for s in STEPS]
        for prev, cur, step in zip(times, times[1:], STEPS[1:]):
            assert cur > prev, f"step {step} stamp {cur} ps is not after {prev} ps"
        expected = [c for c, _ in CHECKER_STEPS]
        assert self.chk_order == expected, f"checker lines {self.chk_order} != {expected}"
        for chk_id, step in CHECKER_STEPS:
            assert self.chk_stamps[chk_id] >= self.stamps[step], (
                f"{chk_id} printed at {self.chk_stamps[chk_id]} ps before {step} "
                f"completed at {self.stamps[step]} ps"
            )
        return times, ", ".join(f"{s}@{t}" for s, t in zip(STEPS, times))

    async def body(self) -> None:
        assert hasattr(cocotb.top, "tb_avs_clk_from_dut"), "tb_avs_clk_from_dut not exported"
        assert hasattr(cocotb.top, "clk_periph"), "clk_periph not exported"

        # S1: setup is the base bring-up at the default triple; the words to restore are read.
        saved0 = await self._rd("AVS_CFG_0_SAVE", AVS_CFG_0)
        saved1 = await self._rd("AVS_CFG_1_SAVE", AVS_CFG_1)
        self._stamp("S1")

        # S2: reset words.
        reset1 = SELECT_RESET
        reset_cfg = await self._rd("AVS_CFG_1_RESET", AVS_CFG_1, expected=reset1)
        reset_config = await self._rd("AVS_CONFIG_RESET", AVS_CONFIG, expected=GPIO_ENABLE_RESET)
        assert saved1 == reset_cfg, (
            f"AVS_CFG_1 saved 0x{saved1:08x} != reset read 0x{reset_cfg:08x}"
        )
        self._stamp("S2")
        self._chk(
            "CHK-AVS-CSR-RESET",
            f"AVS_CFG_1=0x{reset_cfg:08x} (reset 0x{reset1:08x}) and "
            f"AVS_CONFIG=0x{reset_config:08x} (reset 0x{GPIO_ENABLE_RESET:08x}), both OKAY; "
            f"AVS_CFG_0=0x{saved0:08x} (MAX_RETRIES and RESYNC_INTERVAL fields "
            f"0x{saved0 & (MAX_RETRIES_BM | RESYNC_INTERVAL_BM):08x})",
        )

        # S3: each field alone through the gated sequence.
        cur = saved1
        notes: list[str] = []
        new = (cur & ~SELECT_BM) | SELECT_REFCLK
        cur = await self._gated_write("SELECT_10", cur, new)
        notes.append(f"select=0x{_field(cur, SELECT_BM, 0):x}")
        new = (cur & ~SELECT_BM) | SELECT_RESET
        cur = await self._gated_write("SELECT_11", cur, new)
        new = cur | STOP_BM
        cur = await self._gated_write("STOP_1", cur, new)
        notes.append(f"stop={_field(cur, STOP_BM, 8)}")
        new = cur & ~STOP_BM
        cur = await self._gated_write("STOP_0", cur, new)
        notes.append(f"stop={_field(cur, STOP_BM, 8)}")
        await self._wr("TURN_OFF_1", AVS_CFG_1, cur | TURN_OFF_BM)
        got = await self._rd("TURN_OFF_1_RB", AVS_CFG_1, expected=cur | TURN_OFF_BM)
        notes.append(f"turn_off={_field(got, TURN_OFF_BM, 10)}")
        await self._wr("TURN_OFF_0", AVS_CFG_1, cur)
        got = await self._rd("TURN_OFF_0_RB", AVS_CFG_1, expected=cur)
        notes.append(f"turn_off={_field(got, TURN_OFF_BM, 10)}")
        new = (cur & ~DIVIDER_BM) | (DIVIDER_S3 << DIVIDER_BP)
        cur = await self._gated_write("DIVIDER", cur, new)
        notes.append(f"divider=0x{_field(cur, DIVIDER_BM, DIVIDER_BP):02x}")
        new = (cur & ~NUMERATOR_BM) | (NUMERATOR_S3 << NUMERATOR_BP)
        cur = await self._gated_write("NUMERATOR", cur, new)
        notes.append(f"numerator=0x{_field(cur, NUMERATOR_BM, NUMERATOR_BP):02x}")
        self._stamp("S3")
        self._chk(
            "CHK-AVS-CSR-FIELDS",
            "each single-field write read back as written with every other field held: "
            f"{', '.join(notes)}; AVS_CFG_1=0x{cur:08x}",
        )

        # S4: byte-lane-2-only write.
        pre = await self._rd("BYTE_LANE_PRE", AVS_CFG_1)
        await self._wr("BYTE_LANE_GATE_ON", AVS_CFG_1, pre | TURN_OFF_BM)
        gated_pre = await self._rd("BYTE_LANE_GATED_PRE", AVS_CFG_1, expected=pre | TURN_OFF_BM)
        data = 0xA5 << 24 | DIVIDER_LANE2 << 16 | 0x5A << 8 | 0xC3
        assert (data >> 24) & 0xFF != (gated_pre >> 24) & 0xFF
        assert (data >> 8) & 0xFF != (gated_pre >> 8) & 0xFF
        assert data & 0xFF != gated_pre & 0xFF
        await self._wr("BYTE_LANE_2", AVS_CFG_1, data, wstrb=LANE2_STROBE)
        post = await self._rd("BYTE_LANE_POST", AVS_CFG_1)
        want = (gated_pre & ~DIVIDER_BM) | (DIVIDER_LANE2 << DIVIDER_BP)
        assert post == want, (
            f"byte-lane-2 write of data 0x{data:08x}: read 0x{post:08x}, expected 0x{want:08x} "
            f"(pre-write 0x{gated_pre:08x})"
        )
        await self._wr("BYTE_LANE_GATE_OFF", AVS_CFG_1, want & ~TURN_OFF_BM)
        cur = await self._rd("BYTE_LANE_RB", AVS_CFG_1, expected=want & ~TURN_OFF_BM)
        self._stamp("S4")
        self._chk(
            "CHK-AVS-CSR-BYTE-LANE-2",
            f"strobe 0x{LANE2_STROBE:x} data 0x{data:08x}: CLK_DIVIDER_VALUE="
            f"0x{_field(post, DIVIDER_BM, DIVIDER_BP):02x}, bytes 0,1,3 read "
            f"0x{post & 0xFF:02x},0x{(post >> 8) & 0xFF:02x},0x{(post >> 24) & 0xFF:02x} "
            f"= pre-write 0x{gated_pre & 0xFF:02x},0x{(gated_pre >> 8) & 0xFF:02x},"
            f"0x{(gated_pre >> 24) & 0xFF:02x}",
        )

        # S5: single-pulse force bit.
        await self._wr("FORCE_1", AVS_CFG_1, cur | FORCE_BM)
        first = await self._rd("FORCE_IMMEDIATE", AVS_CFG_1)
        self.force_wait_state = f"waiting {FORCE_WAIT_PERIPH_CYCLES} clk_periph_i periods"
        await ClockCycles(cocotb.top.clk_periph, FORCE_WAIT_PERIPH_CYCLES)
        self.force_wait_state = f"{FORCE_WAIT_PERIPH_CYCLES} clk_periph_i periods elapsed"
        second = await self._rd("FORCE_LATER", AVS_CFG_1)
        for label, value in (("immediate", first), ("after 64 periods", second)):
            assert value & FORCE_BM == 0, f"FORCE bit reads 1 on the {label} read: 0x{value:08x}"
            assert value == cur, f"{label} read 0x{value:08x} differs from held word 0x{cur:08x}"
        self._stamp("S5")
        self._chk(
            "CHK-AVS-CSR-FORCE-PULSE",
            f"after write of bit 9: immediate read 0x{first:08x} bit9={_field(first, FORCE_BM, 9)}"
            f", read after {FORCE_WAIT_PERIPH_CYCLES} clk_periph_i periods 0x{second:08x} "
            f"bit9={_field(second, FORCE_BM, 9)}",
        )

        # S6: bits that carry no field.
        before = await self._rd("UNALLOC_BEFORE", AVS_CFG_1)
        period_before = await self._period_ps("UNALLOC_BEFORE")
        await self._wr("UNALLOC_ONES", AVS_CFG_1, before | UNALLOCATED_BM)
        after = await self._rd("UNALLOC_AFTER", AVS_CFG_1)
        period_after = await self._period_ps("UNALLOC_AFTER")
        assert after & DEFINED_BM == before & DEFINED_BM, (
            f"defined fields changed: before 0x{before & DEFINED_BM:08x} "
            f"after 0x{after & DEFINED_BM:08x}"
        )
        assert period_after == period_before, (
            f"AVS clock span over {MEASURE_PERIODS} periods changed: "
            f"{period_before} ps -> {period_after} ps"
        )
        await self._wr("UNALLOC_CLEAR", AVS_CFG_1, before & DEFINED_BM)
        cleared = await self._rd("UNALLOC_CLEARED", AVS_CFG_1)
        assert cleared & DEFINED_BM == before & DEFINED_BM, (
            f"defined fields 0x{cleared & DEFINED_BM:08x} after clearing, "
            f"expected 0x{before & DEFINED_BM:08x}"
        )
        cur = cleared
        self._stamp("S6")
        self._chk(
            "CHK-AVS-CSR-UNALLOCATED",
            f"unallocated mask 0x{UNALLOCATED_BM:08x}: read before 0x{before & UNALLOCATED_BM:08x}"
            f", after writing ones 0x{after & UNALLOCATED_BM:08x}, after writing zeros "
            f"0x{cleared & UNALLOCATED_BM:08x} (owner value pending); defined fields unchanged "
            f"0x{before & DEFINED_BM:08x}; AVS clock span {MEASURE_PERIODS} periods "
            f"{period_before} ps before, {period_after} ps after",
        )

        # S7: divider round trip.
        new = (cur & ~DIVIDER_BM) | (DIVIDER_S3 << DIVIDER_BP)
        rt = await self._gated_write("RT", cur, new)
        self._stamp("S7")
        self._chk(
            "CHK-CDC-AVS-RT",
            f"read at 0x{AVS_CFG_1:08x} after write: CLK_DIVIDER_VALUE="
            f"0x{_field(rt, DIVIDER_BM, DIVIDER_BP):02x}, other fields "
            f"0x{rt & ~DIVIDER_BM & WORD_MASK:08x} = before 0x{cur & ~DIVIDER_BM & WORD_MASK:08x}",
        )
        cur = rt

        # S8: write then read, then two back-to-back writes and two reads.
        imm = (cur & ~DIVIDER_BM) | (0x06 << DIVIDER_BP)
        got_imm = await self._gated_write("IMM", cur, imm)
        new0 = saved0 ^ (MAX_RETRIES_BM & (1 << 16)) ^ (RESYNC_INTERVAL_BM & 1)
        assert new0 != saved0
        pair1 = (imm & ~DIVIDER_BM) | (DIVIDER_S3 << DIVIDER_BP) | TURN_OFF_BM
        await self._wr("PAIR_GATE_ON", AVS_CFG_1, imm | TURN_OFF_BM)
        await self._wr("PAIR_CFG_0", AVS_CFG_0, new0)
        await self._wr("PAIR_CFG_1", AVS_CFG_1, pair1)
        read0 = await self._rd("PAIR_RD_CFG_0", AVS_CFG_0, expected=new0)
        read1 = await self._rd("PAIR_RD_CFG_1", AVS_CFG_1, expected=pair1)
        await self._wr("PAIR_GATE_OFF", AVS_CFG_1, pair1 & ~TURN_OFF_BM)
        cur = await self._rd("PAIR_GATE_OFF_RB", AVS_CFG_1, expected=pair1 & ~TURN_OFF_BM)
        self._stamp("S8")
        self._chk(
            "CHK-CDC-AVS-ORDER",
            f"write then read returned 0x{got_imm:08x} (wrote 0x{imm:08x}); back-to-back writes "
            f"AVS_CFG_0=0x{new0:08x}, AVS_CFG_1=0x{pair1:08x} read back in order "
            f"0x{read0:08x}, 0x{read1:08x}",
        )

        # Restore.
        await self._wr("AVS_CFG_0_RESTORE", AVS_CFG_0, saved0)
        await self._rd("AVS_CFG_0_RESTORE_RB", AVS_CFG_0, expected=saved0)
        restored = await self._gated_write("AVS_CFG_1_RESTORE", cur, saved1)
        assert restored == saved1
        self.restored_stamp = int(get_sim_time("ps"))

        waits = (
            f"SEP_IN_access={ACCESS_TIMEOUT_NS}ns last_resp={self.last_resp} "
            f"fail=AssertionError(access timeout or non-OKAY) accesses={self.accesses}",
            f"avs_clk_edge={EDGE_TIMEOUT_NS}ns last={self.last_edge_state} "
            f"fail=AssertionError(no edge) edge_waits={self.edge_waits}",
            f"clk_periph_cycles={FORCE_WAIT_PERIPH_CYCLES}periods last={self.force_wait_state} "
            f"fail=n/a(counted wait, read compared after)",
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %d bounded waits: %s", len(waits), " ".join(waits))

        times, stamp_text = self._assert_fence()
        assert self.restored_stamp > times[-1]
        terms = " < ".join(FENCE_TERMS)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s, AVS_CFG_1_RESTORED@%d",
            terms,
            ", ".join(c for c, _ in CHECKER_STEPS),
            stamp_text,
            self.restored_stamp,
        )

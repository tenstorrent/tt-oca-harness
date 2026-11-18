# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The FLR cool pulse on the BP_COOL_RESET_N_O pad and the ISOLATE_REQ_VIS levels.

``clk_rst.adoc`` "Isolation Connections": the FLR cool reset also drives the open-drain
``BP_COOL_RESET_N_O`` pad, GPIO 62, which pulls the line low while the reset is asserted and
leaves it undriven otherwise. "Timing and Recovery": ``ISOLATE_REQ_VIS`` reports synchronized
pin and cool-reset levels; it is not an isolation-completion handshake.

Every probe is sampled on ``clk_ref_i`` rises: ``tb_rst_cool_from_flr`` (``rst_cool_no``) and
``tb_core2pad_en_o`` and ``tb_core2pad_o`` at the Cool Reset Out index of the integrator pad
table. Two FLR legs run, a short hold and a hold long enough for a bounded CSR read; on every
sample of both the pad enable must equal the inverted cool reset and the pad data must be 0
whenever the enable is 1. ``ISOLATE_REQ_VIS`` is read with the isolation pin low and high while
``ISOLATE_REQ_PINEN_REG`` is 0, so the pin bit follows the pad without any isolation request;
the cool-reset bits are read at their released level. The reset unit's register block is on the
primary reset, so the read made during the long hold is bounded and recorded, not graded.
"""

from __future__ import annotations

import csv

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import _REPO, reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_isolate_pin_utils import (
    ISOLATE_REQ_PINEN_REG,
    await_skip_mem_repair,
    drive_isolate_pin,
)

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
VIS_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_VIS_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
VIS_PIN = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__ISOLATE_REQ_PIN_bm")
VIS_COOL_IN = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_I_bm")
VIS_COOL_OUT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_O_bm")
_PAD_TABLE = _REPO / "doc" / "integrator" / "meta" / "ocah_gpio_table.csv"

#: Pre-reset count and hold count of the short leg, in clk_ref_i cycles.
FLR_N, FLR_M = 64, 64
#: Pre-reset count and hold count of the long leg; the hold outlasts a bounded CSR read.
LONG_N, LONG_M = 4, 2000
#: Reference-clock edges the counter values are given to cross into the reference domain.
CDC_REF = 64
#: Synchroniser allowance on top of a programmed count, in clk_ref_i cycles.
SYNC_ALLOWANCE = 64
#: Ceiling in clk_smc_i rises for a register or output to follow; expiry fails.
_BOUND = 128
#: Consecutive rises on which a held level must agree.
_HOLD = 32
_RECOVERY_SMC = 50_000
_WARM_LOW_BOUND_SMC = 20_000
#: Timeout of the one bounded ISOLATE_REQ_VIS read made during the long hold.
_IN_HOLD_READ_NS = 5_000

FLR_IDLE, FLR_COUNT_DOWN, FLR_EQUAL_ZERO = 0, 1, 2
FLR_NAME = {0: "IDLE", 1: "COUNT_DOWN", 2: "EQUAL_ZERO"}

CHK_PAD62 = "CHK-COOL-RESET-PAD62-OPEN-DRAIN"
CHK_VIS = "CHK-ISOLATE-VIS-LIVE-LEVELS"


def _int(sig) -> int:
    assert sig.value.is_resolvable, f"X/Z on {sig._name}: {sig.value}"
    return int(sig.value)


def _pad_index(function: str) -> int:
    with _PAD_TABLE.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("Function") == function]
    if len(rows) != 1:
        raise AssertionError(f"{_PAD_TABLE}: expected one pad with Function {function!r}")
    return int(rows[0]["Index"])


#: GPIO pad index of BP_COOL_RESET_N_O, from the pad table.
COOL_RESET_OUT_PAD = _pad_index("Cool Reset Out")


class RefMon:
    """clk_ref_i sampler of the FLR request edge, counter state, rst_cool_no and pad 62.

    A second sampler on clk_smc_i counts falls of the warm smc-clock reset, so a leg armed
    before its request edge sees the warm reset the cool pulse causes.
    """

    def __init__(self) -> None:
        self._tasks: list = []
        self.arm()

    def arm(self) -> None:
        dut = cocotb.top
        self.edge = 0
        self.posedges: list[tuple[int, int]] = []
        self.falls: list[int] = []
        self.rises: list[int] = []
        self.warm_falls = 0
        self.pad_samples = 0
        self.pad_mismatch = 0
        self.pad_data_high = 0
        self.pad_driven = 0
        self._prev_cool = _int(dut.tb_rst_cool_from_flr) & 1
        self._prev_warm = _int(dut.tb_rst_warm_smc_clk_n) & 1

    def start(self) -> None:
        self._tasks = [cocotb.start_soon(self._run()), cocotb.start_soon(self._run_warm())]

    def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []

    def posedge_text(self) -> str:
        return ",".join(f"{e}:{FLR_NAME.get(s, s)}" for e, s in self.posedges)

    async def _run_warm(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            warm = _int(dut.tb_rst_warm_smc_clk_n) & 1
            if self._prev_warm and not warm:
                self.warm_falls += 1
            self._prev_warm = warm

    async def _run(self) -> None:
        dut = cocotb.top
        pad = COOL_RESET_OUT_PAD
        while True:
            await RisingEdge(dut.clk_ref_i)
            self.edge += 1
            if _int(dut.tb_flr_posedge_ref):
                self.posedges.append((self.edge, _int(dut.tb_flr_counter_state)))
            cool = _int(dut.tb_rst_cool_from_flr) & 1
            if self._prev_cool and not cool:
                self.falls.append(self.edge)
            elif cool and not self._prev_cool:
                self.rises.append(self.edge)
            self._prev_cool = cool
            oe = (_int(dut.tb_core2pad_en_o) >> pad) & 1
            data = (_int(dut.tb_core2pad_o) >> pad) & 1
            self.pad_samples += 1
            if oe != (1 - cool):
                self.pad_mismatch += 1
            if oe:
                self.pad_driven += 1
                if data:
                    self.pad_data_high += 1


class SmcFlrLegSeq(SmcCsrSeq):
    """FLR leg helpers: counter programming, cool-pulse measurement and recovery."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.rows: list[dict] = []
        self.mon = RefMon()
        self.pad = {"samples": 0, "mismatch": 0, "data_high": 0, "driven": 0, "released": 0}

    async def ref(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_ref_i)

    def cool(self) -> int:
        return _int(cocotb.top.tb_rst_cool_from_flr) & 1

    async def await_cool(self, want: int, bound: int, label: str) -> None:
        last = None
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_ref_i)
            last = self.cool()
            if last == want:
                return
        raise AssertionError(
            f"{label}: rst_cool_from_flr stuck at {last}, want {want}, after {bound} edges"
        )

    async def await_state(self, want: int, label: str) -> None:
        last = None
        for _ in range(SYNC_ALLOWANCE):
            await RisingEdge(cocotb.top.clk_ref_i)
            last = _int(cocotb.top.tb_flr_counter_state)
            if last == want:
                return
        raise AssertionError(f"{label}: flr_counter_state {FLR_NAME.get(last, last)}, want {want}")

    async def _await_smc_bit(self, want: int, label: str) -> None:
        last = 0
        for _ in range(_BOUND):
            last = await self.csr_read(label, SMC_REG)
            if (last & SMC_BIT) == want:
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: SMC_REG=0x{last:x} want bit={want}")

    async def program(self, label: str, n: int, m: int) -> None:
        await self.csr_write(f"FLR_DELAY_{label}", FLR_DELAY, n)
        await self.csr_read(f"FLR_DELAY_RB_{label}", FLR_DELAY, expected=n)
        await self.csr_write(f"FLR_HOLD_{label}", FLR_HOLD, m)
        await self.csr_read(f"FLR_HOLD_RB_{label}", FLR_HOLD, expected=m)
        await self.ref(CDC_REF)

    async def clear_counters(self) -> None:
        await self.csr_write("FLR_HOLD_CLR", FLR_HOLD, 0)
        await self.csr_read("FLR_HOLD_CLR_RB", FLR_HOLD, expected=0)
        await self.csr_write("FLR_DELAY_CLR", FLR_DELAY, 0)
        await self.csr_read("FLR_DELAY_CLR_RB", FLR_DELAY, expected=0)

    def _take_pad(self) -> None:
        mon = self.mon
        self.pad["samples"] += mon.pad_samples
        self.pad["mismatch"] += mon.pad_mismatch
        self.pad["data_high"] += mon.pad_data_high
        self.pad["driven"] += mon.pad_driven
        self.pad["released"] += mon.pad_samples - mon.pad_driven

    async def recover(self, label: str) -> None:
        """Drop the request, wait the warm domain back, clear the latch, fold the pad counts."""
        dut = cocotb.top
        mon = self.mon
        dut.tb_cfg_flr_pf_active.value = 0
        for _ in range(_WARM_LOW_BOUND_SMC):
            await RisingEdge(dut.clk_smc_i)
            if mon.warm_falls:
                break
        assert mon.warm_falls > 0, f"{label}: warm smc clk reset never fell after the FLR cool"
        for _ in range(_RECOVERY_SMC):
            await RisingEdge(dut.clk_smc_i)
            if (_int(dut.tb_rst_warm_smc_clk_n) & 1) == 1:
                break
        else:
            raise AssertionError(f"{label}: warm smc clk reset still 0 after the FLR cool")
        self._take_pad()
        await self.csr_write(f"SMC_REG_CLR_{label}", SMC_REG, SMC_BIT)
        await self._await_smc_bit(0, f"SMC_REG_CLR_RB_{label}")

    def pulse(self, prefix: str) -> tuple[int, int]:
        """(pre-reset edges, hold edges) of the single recorded pulse; more than one fails."""
        mon = self.mon
        assert mon.posedges, f"{prefix}: no tb_flr_posedge_ref seen"
        assert len(mon.falls) == 1 and len(mon.rises) == 1, (
            f"{prefix}: rst_cool_no fell at clk_ref_i edges {mon.falls} and rose at {mon.rises}, "
            f"want exactly one fall and one rise; request edges {mon.posedge_text()}"
        )
        return mon.falls[0] - mon.posedges[0][0], mon.rises[0] - mon.falls[0]

    async def single_leg(self, label: str, n: int, m: int) -> dict:
        """One FLR edge with counters (n, m): one bounded cool pulse, then recovery."""
        dut = cocotb.top
        await self.program(label, n, m)
        self.mon.arm()
        dut.tb_cfg_flr_pf_active.value = 1
        await self.await_cool(0, n + SYNC_ALLOWANCE, f"{label}_COOL_ASSERT")
        await self.await_cool(1, m + SYNC_ALLOWANCE, f"{label}_COOL_RELEASE")
        await self.ref(16)
        pre, hold = self.pulse(label)
        row = {"leg": label, "N": n, "M": m, "pre": pre, "hold": hold}
        await self.recover(label)
        self.rows.append(row)
        return row

    async def setup(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_cfg_flr_pf_active",
            "tb_flr_posedge_ref",
            "tb_flr_counter_state",
            "tb_rst_cool_from_flr",
            "tb_rst_warm_smc_clk_n",
            "tb_core2pad_o",
            "tb_core2pad_en_o",
            "tb_isolate_req_o",
            "tb_skip_mem_repair_o",
        ):
            assert hasattr(dut, name), f"{name} missing from tb_top"
        await self.wait_fuse_sense_done()
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low, no FLR")
        await self.csr_read("PINEN_IDLE", ISOLATE_REQ_PINEN_REG, expected=0)
        await self.csr_read("SMC_REG_IDLE", SMC_REG, expected=0)
        assert self.cool() == 1, "rst_cool_from_flr already asserted"


class smc_flr_sequencer_single_pulse_test_seq(SmcFlrLegSeq):
    """A short and a long FLR leg; pad 62 on every sample, ISOLATE_REQ_VIS around them."""

    def __init__(self, name: str = "smc_flr_sequencer_single_pulse_test_seq") -> None:
        super().__init__(name)

    async def _long_hold(self) -> dict:
        dut = cocotb.top
        await self.program("LONG", LONG_N, LONG_M)
        self.mon.arm()
        dut.tb_cfg_flr_pf_active.value = 1
        await self.await_cool(0, LONG_N + SYNC_ALLOWANCE, "LONG_COOL_ASSERT")
        in_hold = await self.csr_read_bounded(
            "VIS_IN_HOLD", VIS_REG, timeout_ns=_IN_HOLD_READ_NS, allow_error=True
        )
        in_hold_text = "TIMEOUT" if self.timeouts else f"0x{in_hold:x}"
        await self.await_cool(1, LONG_M + SYNC_ALLOWANCE, "LONG_COOL_RELEASE")
        await self.ref(16)
        pre, hold = self.pulse("LONG")
        await self.recover("LONG")
        row = {"leg": "LONG", "N": LONG_N, "M": LONG_M, "pre": pre, "hold": hold}
        row["vis_in_hold"] = in_hold_text
        self.rows.append(row)
        return row

    async def body(self) -> None:
        dut = cocotb.top
        await self.setup()

        # ISOLATE_REQ_VIS follows the pin with PINEN at 0 and no isolation request.
        vis_low = await self.csr_read("VIS_PIN_LOW", VIS_REG, expected=VIS_COOL_IN | VIS_COOL_OUT)
        drive_isolate_pin(dut, 1)
        pin_arrived = await await_skip_mem_repair(dut, 1, "isolate pin high")
        vis_high = await self.csr_read(
            "VIS_PIN_HIGH", VIS_REG, expected=VIS_PIN | VIS_COOL_IN | VIS_COOL_OUT
        )
        iso_words = []
        for _ in range(_HOLD):
            await RisingEdge(dut.clk_smc_i)
            iso_words.append(_int(dut.tb_isolate_req_o))
        assert not any(iso_words), (
            f"{CHK_VIS} FAIL: with PINEN 0 the pin asserted tb_isolate_req_o={iso_words}"
        )
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low again")
        vis_low_again = await self.csr_read(
            "VIS_PIN_LOW_AGAIN", VIS_REG, expected=VIS_COOL_IN | VIS_COOL_OUT
        )

        self.mon.start()
        try:
            short = await self.single_leg("SHORT", FLR_N, FLR_M)
            long_row = await self._long_hold()
        finally:
            self.mon.stop()
            dut.tb_cfg_flr_pf_active.value = 0
        vis_after = await self.csr_read(
            "VIS_AFTER_HOLD", VIS_REG, expected=VIS_COOL_IN | VIS_COOL_OUT
        )
        await self.clear_counters()
        drive_isolate_pin(dut, None)

        pad = self.pad
        assert pad["driven"] >= FLR_M + LONG_M and pad["released"] >= FLR_N, (
            f"{CHK_PAD62} FAIL: pad {COOL_RESET_OUT_PAD} driven on {pad['driven']} and released on "
            f"{pad['released']} clk_ref_i samples; too few to compare"
        )
        assert pad["mismatch"] == 0 and pad["data_high"] == 0, (
            f"{CHK_PAD62} FAIL: pad {COOL_RESET_OUT_PAD} output enable differed from the inverted "
            f"rst_cool_no on {pad['mismatch']} of {pad['samples']} clk_ref_i samples and drove 1 on "
            f"{pad['data_high']} of {pad['driven']} enabled samples"
        )
        cocotb.log.info(
            "%s: two FLR legs (N=%d M=%d: pre=%d hold=%d; N=%d M=%d: pre=%d hold=%d clk_ref_i "
            "edges); over %d clk_ref_i samples tb_core2pad_en_o[%d] equalled the inverted "
            "rst_cool_no on every sample (%d mismatches), was 1 on %d samples with "
            "tb_core2pad_o[%d]=0 on all of them (%d high), and was 0 on %d samples",
            CHK_PAD62,
            short["N"],
            short["M"],
            short["pre"],
            short["hold"],
            long_row["N"],
            long_row["M"],
            long_row["pre"],
            long_row["hold"],
            pad["samples"],
            COOL_RESET_OUT_PAD,
            pad["mismatch"],
            pad["driven"],
            COOL_RESET_OUT_PAD,
            pad["data_high"],
            pad["released"],
        )

        cocotb.log.info(
            "%s: ISOLATE_REQ_VIS read 0x%x with the pin low, 0x%x with it high (pin seen after %d "
            "rises, tb_isolate_req_o 0 on %d of %d rises with PINEN 0), 0x%x low again and 0x%x "
            "after the FLR legs (cool_reset_n_i and cool_reset_n_o bits 1 at the released level); "
            "the bounded read during the %d-cycle hold answered %s (register block on the primary "
            "reset, recorded not graded)",
            CHK_VIS,
            vis_low,
            vis_high,
            pin_arrived,
            _HOLD - sum(1 for w in iso_words if w),
            _HOLD,
            vis_low_again,
            vis_after,
            LONG_M,
            long_row["vis_in_hold"],
        )

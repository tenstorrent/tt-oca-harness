# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A CT_SRC mask that selects its own wire-OR CTP lane re-triggers that lane until it is cleared.

A wire-OR CTP also receives the falling edge it drives onto the shared wire, and a route from a
CTP back to itself does not exist unless the mask selects it
(``hw/ip/cross_trigger/cross_trigger_network/doc/architecture.adoc``, "Chiplet 0" echo
description; ``hw/ip/cross_trigger/cross_trigger_matrix/doc/architecture.adoc``, "CTM routing
stages"). ``CT_SRC[n].CONFIG_0.CT_DST_SELECT`` is read-write and all-zero disables the output
(``cross_trigger_matrix.rdl``). The bench pin ``tb_xtrig_ctp_wire_ext_assert`` pulls the shared
wire of lane n low from outside; every CSR access runs over JTAG2AXI, with no firmware and no
probe. The request-output enable, the wire level and ``ct_dst`` of lane n are sampled on every
``clk_smu_i`` edge of each fixed window.

S1  Reset done, external assertions idle, wires at rest, TAP up, IDCODE, J2A gate open.
S2  Read CONFIG, STRETCH_MULT and CT_SRC[n].CONFIG_0 of lane n and log them.
S3  Mask 0: one external assertion reaches ct_dst; the request output never rises.
S4  Write CT_SRC[n].CONFIG_0 = 1 << n and read it back.
S5  The same assertion: first request-output pulse width, then a second rise.
S6  Fixed window from the first rise: rise count, a rise in the last sub-window, STATUS sample.
S7  Write CT_SRC[n].CONFIG_0 = 0 and read it back.
S8  The last pulse ends, then a quiet window with no rise.
S9  Rewrite the mask, assert again, write CONFIG.RESET and log the rises that follow.
S10 Restore CONFIG and CT_SRC[n].CONFIG_0 to 0 with read-back.
S11 PASS stamp two clk_smu_i cycles after S10.
"""

from __future__ import annotations

from collections import Counter
from typing import cast

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import (
    cross_trigger_network_indexed_addr,
    cross_trigger_network_u32,
    cross_trigger_u32,
)
from seq_lib.smu_compose_helpers import sample
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

DTP_CSR_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")

NUM_CTP = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTP_NUM")
NUM_CT_SRC = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM")
CTP_CONFIG_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")
CTP_STATUS_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STATUS_BASE_ADDR")
CTP_STRETCH_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STRETCH_MULT_BASE_ADDR")
CT_DST_SELECT_BM = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bm")
RESET_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__RESET_bm")
BUSY_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__BUSY_bm")
REQ_OUT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_OUT_bm")
ACK_OUT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_OUT_bm")
STRETCH_MULT_RESET = cross_trigger_u32("CROSS_TRIGGER_PORT__STRETCH_MULT__STRETCH_MULT_reset")

# cross_trigger_port.rdl CONFIG: MODE 0 is wire-OR, the only mode with an echo of the lane's own
# falling edge. The leaf uses an external CTP index (below CROSS_TRIGGER_NETWORK_CTP_NUM) left in
# its wire-OR reset mode; every such index routes the same way.
LANE = 3
LANE_SELECT = (1 << LANE) & CT_DST_SELECT_BM
# cross_trigger_matrix.rdl CT_SRC[n].CONFIG_0: all-zero disables that CT_Src output.
SELECT_CLEARED = 0
CONFIG_WIRE_OR = 0
CONFIG_RESET_ONLY = RESET_BM

# network architecture.adoc, wire-OR description: one external assertion is one falling edge on
# the shared wire, which the CTP reports as one ct_dst rise.
EXPECTED_CT_DST_RISES = 1
# cross_trigger_matrix.rdl CT_SRC[n].CONFIG_0: with the select clear nothing routes to the output.
EXPECTED_CONTROL_REQ_RISES = 0
# cross_trigger_port.rdl STRETCH_MULT: the pulse is STRETCH_MULT + 1 cycles wide.
EXPECTED_FIRST_PULSE_WIDTH = STRETCH_MULT_RESET + 1
# network architecture.adoc, wire-OR description: the port receives the falling edge it drives and
# a mask selecting its own lane forwards it again.
EXPECTED_SECOND_RISE = 1
EXPECTED_QUIET_RISES = 0
EXPECTED_ALIVE = 1

J2A_POLL_LIMIT = 128
# Windows and bounds, in clk_smu_i cycles.
ASSERT_CYCLES = 2
CT_DST_BOUND = 16
CONTROL_WINDOW = 32
SECOND_RISE_BOUND = 48
LOOP_WINDOW = 128
LOOP_LAST_WINDOW = 32
LAST_PULSE_BOUND = 16
# Cycles before the mask-clear write is issued in which a request-output rise must be seen.
PRE_WRITE_WINDOW = 12
QUIET_WINDOW = 64
RESET_WINDOW = 64
STEP_CLOCK_GAP = 2

# Bounded tick waits per kind, one site each; JTAG2AXI accesses: S2 3, S4 2, S6 1, S7 2, S9 4,
# S10 4.
EXPECTED_SITE_KINDS = {"ct_dst_rise": 1, "second_rise": 1, "last_pulse_end": 1}
EXPECTED_J2A_ACCESSES = 16

MEASURED_ITEMS = (
    "s2_config",
    "s2_stretch_mult",
    "s2_ct_src",
    "s6_total_rises",
    "s6_busy",
    "s6_req_out",
    "s6_ack_out",
    "s9_rises_after_reset",
)

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")

PIN_ASSERT = "tb_xtrig_ctp_wire_ext_assert"
PIN_PULL = "tb_xtrig_ctp_wire_pull"
PIN_GROUP = "tb_xtrig_ctp_wire_group"
PIN_EN = "tb_xtrig_ctp_req_out_dout_en"
PIN_DIN = "tb_xtrig_ctp_req_out_din"
PIN_CT_DST = "tb_xtrig_ctp_ct_dst"

# Sample tuple layout: (sim ns, request-output enable, wire level, ct_dst).
NS, EN, DIN, CT = range(4)


def _rises(samples: list, field: int, prev: int = 0) -> list[int]:
    """Indexes of ``samples`` whose ``field`` is 1 after a sample of 0."""
    out = []
    for i, entry in enumerate(samples):
        if entry[field] and not prev:
            out.append(i)
        prev = entry[field]
    return out


class smu_xtrig_ctm_self_loop_test_seq:
    """Self-selecting CT_SRC mask on a wire-OR CTP lane: loop, then stop."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.clk = self.dut.clk_smu_i
        self.jtag = None
        self.trace: list = []
        self.sites: list[dict] = []
        self.step_ns: dict[str, float] = {}
        self.measured: dict[str, int] = {}
        self.readbacks: list[tuple[str, int, int]] = []
        self.j2a = 0
        self.j2a_expired = 0
        self.j2a_last = "none"
        self.watch: list[int] = []
        self.watching = False
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    def _vec(self, name: str) -> int:
        return sample(getattr(self.dut, name), name)

    def _bit(self, name: str) -> int:
        return (self._vec(name) >> LANE) & 1

    def _ext(self, level: int) -> None:
        cur = self._vec(PIN_ASSERT)
        getattr(self.dut, PIN_ASSERT).value = (cur & ~(1 << LANE)) | (level << LANE)

    def _stamp(self, step: str, text: str) -> None:
        self.step_ns[step] = self._now()
        self._log(f"STEP {step} @{self.step_ns[step]:.3f}ns: {text}")

    async def _done(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self._stamp(step, text)

    async def _tick(self) -> tuple:
        await RisingEdge(self.clk)
        entry = (self._now(), self._bit(PIN_EN), self._bit(PIN_DIN), self._bit(PIN_CT_DST))
        self.trace.append(entry)
        return entry

    def _last_state(self) -> str:
        if not self.trace:
            return "no sample"
        ns, en, din, ct = self.trace[-1]
        return f"req_out_dout_en={en} wire={din} ct_dst={ct} at {ns:.3f}ns"

    def _dump(self, label: str) -> None:
        """Rise stamps of the sampled window, in samples from its first edge."""
        self._log(
            f"OBSERVATION {label} samples={len(self.trace)} "
            f"req_out_rises_at={_rises(self.trace, EN)} ct_dst_rises_at={_rises(self.trace, CT)} "
            f"wire_low_at={[i for i, e in enumerate(self.trace) if not e[DIN]]} measured"
        )

    def _site(self, kind: str, bound: int, used: int, expired: bool) -> None:
        last = self._last_state()
        self.sites.append(
            {"kind": kind, "bound": bound, "used": used, "last": last, "expired": int(expired)}
        )
        self._log(f"TIMEOUT-PATH {kind}: bound={bound} used={used} expired={int(expired)} {last}")
        if expired:
            self._dump(f"{kind} expiry")
            raise AssertionError(f"TIMEOUT {kind}: bound={bound} used={used} last_state={last}")

    def _addr(self, base_symbol: str, index: int, limit: int, offset: int = 0) -> int:
        if not 0 <= index < limit:
            raise AssertionError(f"{base_symbol} index {index} outside 0..{limit - 1}")
        return cast(
            int,
            DTP_CSR_BASE + cross_trigger_network_indexed_addr(base_symbol, index) + offset,
        )

    def _ctp_addr(self, offset: int) -> int:
        return self._addr("CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR", LANE, NUM_CTP, offset)

    def _src_addr(self) -> int:
        return self._addr("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_BASE_ADDR", LANE, NUM_CT_SRC)

    async def _rd32(self, addr: int, what: str) -> int:
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
            require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        except (TimeoutError, AssertionError) as exc:
            self.j2a_expired += 1
            self.j2a_last = f"{what} RD @0x{addr:08x}: {exc}"
            raise
        self.j2a += 1
        self.j2a_last = f"{what} RD status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return cast(int, axi64_unpack32(addr, rdata))

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag,
                addr,
                beat,
                wstrb=wstrb,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
            require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        except (TimeoutError, AssertionError) as exc:
            self.j2a_expired += 1
            self.j2a_last = f"{what} WR @0x{addr:08x}: {exc}"
            raise
        self.j2a += 1
        self.j2a_last = f"{what} WR status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _write_read(self, addr: int, value: int, what: str) -> int:
        await self._wr32(addr, value, what)
        got = await self._rd32(addr, f"{what} readback")
        self._log(f"CELL {what} addr=0x{addr:08x} wrote=0x{value:x} read=0x{got:x}")
        return got

    async def _tap_up(self) -> None:
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR access can run")

    async def _watch_loop(self) -> None:
        """Sample the request-output enable on every clk_smu_i edge until ``watching`` clears."""
        while self.watching:
            await RisingEdge(self.clk)
            self.watch.append(self._bit(PIN_EN))

    async def _assert_wire(self) -> None:
        """Pull the shared wire of the lane for ASSERT_CYCLES clk_smu_i cycles, then release."""
        await RisingEdge(self.clk)
        self._ext(1)
        for _ in range(ASSERT_CYCLES):
            await self._tick()
        self._ext(0)

    async def _rest_check(self, what: str) -> None:
        await RisingEdge(self.clk)
        en, din, ct = self._bit(PIN_EN), self._bit(PIN_DIN), self._bit(PIN_CT_DST)
        self._log(f"OBSERVATION {what} rest levels req_out_dout_en={en} wire={din} ct_dst={ct}")
        if (en, ct) != (0, 0) or not din:
            raise AssertionError(f"{what}: lane {LANE} not at rest en={en} wire={din} ct_dst={ct}")

    async def run(self) -> None:
        sb = self.sb
        dut = self.dut
        await self.cfg.reset_done.wait()

        pins = {
            name: self._vec(name) for name in (PIN_ASSERT, PIN_PULL, PIN_GROUP, PIN_DIN, PIN_CT_DST)
        }
        if pins[PIN_ASSERT] or (pins[PIN_GROUP] >> LANE) & 1 or pins[PIN_DIN] != pins[PIN_PULL]:
            raise AssertionError(
                f"bench wires not at rest: { {k: hex(v) for k, v in pins.items()} }"
            )
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self._tap_up()
        await self._done("S1", "reset done, wires at rest, TAP up, IDCODE read, J2A gate open")

        config_addr = self._ctp_addr(CTP_CONFIG_OFF)
        status_addr = self._ctp_addr(CTP_STATUS_OFF)
        stretch_addr = self._ctp_addr(CTP_STRETCH_OFF)
        src_addr = self._src_addr()
        for key, addr, what in (
            ("s2_config", config_addr, "CTP CONFIG"),
            ("s2_stretch_mult", stretch_addr, "CTP STRETCH_MULT"),
            ("s2_ct_src", src_addr, "CT_SRC CONFIG_0"),
        ):
            self.measured[key] = await self._rd32(addr, f"S2 {what}")
            self._log(f"OBSERVATION {key} addr=0x{addr:08x} measured={self.measured[key]:#x}")
        await self._done("S2", "precondition reads of lane CONFIG, STRETCH_MULT and CT_SRC")

        await self._rest_check("S3")
        self.trace = []
        await self._assert_wire()
        while not _rises(self.trace, CT) and len(self.trace) < CT_DST_BOUND:
            await self._tick()
        ct_up = bool(_rises(self.trace, CT))
        self._site("ct_dst_rise", CT_DST_BOUND, len(self.trace), not ct_up)
        while len(self.trace) < CONTROL_WINDOW:
            await self._tick()
        control = (len(_rises(self.trace, CT)), len(_rises(self.trace, EN)))
        self._dump("S3 control")
        self._stamp(
            "S3", "control assertion with the mask clear, ct_dst and request output sampled"
        )

        got = await self._write_read(src_addr, LANE_SELECT, "S4 CT_SRC mask")
        self.readbacks.append(("S4 CT_SRC", LANE_SELECT, got))
        await self._done("S4", "mask written and read back")

        await self._rest_check("S5")
        self.trace = []
        self.watching = True
        cocotb.start_soon(self._watch_loop())
        await self._assert_wire()
        while len(_rises(self.trace, EN)) < 2 and len(self.trace) < SECOND_RISE_BOUND:
            await self._tick()
        rises = _rises(self.trace, EN)
        self._site("second_rise", SECOND_RISE_BOUND, len(self.trace), len(rises) < 2)
        first = rises[0]
        width = 0
        while first + width < len(self.trace) and self.trace[first + width][EN]:
            width += 1
        gap = rises[1] - (first + width)
        self._log(
            f"OBSERVATION first_rise_sample={first} first_pulse_width={width} "
            f"gap_to_second_rise={gap} second_rise_sample={rises[1]} measured"
        )
        self._stamp("S5", "second rise of the request output after the first pulse ended")
        self._log(
            f"CHK-XT-SELFLOOP-RETRIGGER: first_pulse_width={width} expected="
            f"{EXPECTED_FIRST_PULSE_WIDTH} second_rise={int(len(rises) >= 2)} expected="
            f"{EXPECTED_SECOND_RISE} gap_cycles={gap}"
        )

        while len(self.trace) < first + LOOP_WINDOW:
            await self._tick()
        window = self.trace[first : first + LOOP_WINDOW]
        tail = LOOP_WINDOW - LOOP_LAST_WINDOW
        total = len(_rises(window, EN))
        last_rises = len(_rises(window[tail:], EN, window[tail - 1][EN]))
        self.measured["s6_total_rises"] = total
        self._dump("S6 loop window")
        self._log(f"OBSERVATION s6_total_rises window_cycles={LOOP_WINDOW} measured={total}")
        self._log(
            f"CHK-XT-SELFLOOP-ALIVE: rises_in_last_{LOOP_LAST_WINDOW}_cycles={last_rises} "
            f"expected_at_least={EXPECTED_ALIVE}"
        )
        status = await self._rd32(status_addr, "S6 CTP STATUS")
        self.measured["s6_busy"] = int(bool(status & BUSY_BM))
        self.measured["s6_req_out"] = int(bool(status & REQ_OUT_BM))
        self.measured["s6_ack_out"] = int(bool(status & ACK_OUT_BM))
        self._log(
            f"OBSERVATION s6_status=0x{status:08x} busy={self.measured['s6_busy']} "
            f"req_out={self.measured['s6_req_out']} ack_out={self.measured['s6_ack_out']} measured"
        )
        await self._done("S6", "loop window counted, STATUS sampled")

        write_idx = len(self.watch)
        self.watching = False
        pre = self.watch[write_idx - PRE_WRITE_WINDOW - 1 : write_idx]
        pre_rises = len(_rises([(0, v) for v in pre[1:]], 1, pre[0]))
        all_rises = len(_rises([(0, v) for v in self.watch[:write_idx]], 1))
        self._log(
            f"OBSERVATION s7 write issued at watch sample {write_idx}, rises since the S5 "
            f"assertion {all_rises}, rises in the last {PRE_WRITE_WINDOW} samples {pre_rises} "
            "measured"
        )
        stop_read = await self._write_read(src_addr, SELECT_CLEARED, "S7 CT_SRC mask clear")
        await self._done("S7", "mask cleared while the loop ran, read back")

        self.trace = []
        await self._tick()
        while self.trace[-1][EN] and len(self.trace) < LAST_PULSE_BOUND:
            await self._tick()
        self._site("last_pulse_end", LAST_PULSE_BOUND, len(self.trace), bool(self.trace[-1][EN]))
        self.trace = []
        for _ in range(QUIET_WINDOW):
            await self._tick()
        quiet = len(_rises(self.trace, EN))
        self._dump("S8 quiet window")
        self._stamp("S8", "last pulse ended, quiet window sampled")

        got = await self._write_read(src_addr, LANE_SELECT, "S9 CT_SRC mask rewrite")
        self.readbacks.append(("S9 CT_SRC", LANE_SELECT, got))
        await self._assert_wire()
        got = await self._write_read(config_addr, CONFIG_RESET_ONLY, "S9 CONFIG.RESET")
        self.readbacks.append(("S9 CONFIG", CONFIG_RESET_ONLY, got))
        self.trace = []
        for _ in range(RESET_WINDOW):
            await self._tick()
        self.measured["s9_rises_after_reset"] = len(_rises(self.trace, EN))
        self._dump("S9 window after CONFIG.RESET")
        self._log(
            f"OBSERVATION s9_rises_after_reset window_cycles={RESET_WINDOW} "
            f"measured={self.measured['s9_rises_after_reset']}"
        )
        self._stamp("S9", "mask rewritten, assertion repeated, CONFIG.RESET written")

        got = await self._write_read(config_addr, CONFIG_WIRE_OR, "S10 CONFIG restore")
        self.readbacks.append(("S10 CONFIG", CONFIG_WIRE_OR, got))
        got = await self._write_read(src_addr, SELECT_CLEARED, "S10 CT_SRC restore")
        self.readbacks.append(("S10 CT_SRC", SELECT_CLEARED, got))
        await self._done("S10", "CONFIG and CT_SRC restored to 0 with read-back")

        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self._stamp("S11", "PASS stamp")

        observed_rb = [(label, read) for label, _, read in self.readbacks]
        expected_rb = [(label, wrote) for label, wrote, _ in self.readbacks]
        self._log(f"CHK-XT-SELFLOOP-READBACK: read-back {observed_rb} written {expected_rb}")
        sb.expect_eq(
            "CHK-XT-SELFLOOP-READBACK every CT_SRC and CONFIG write reads back as written",
            observed_rb,
            expected_rb,
            evidence="CHK-XT-SELFLOOP-READBACK",
        )
        self._log(
            f"CHK-XT-SELFLOOP-CONTROL: ct_dst_rises={control[0]} request_output_rises={control[1]} "
            f"expected=({EXPECTED_CT_DST_RISES}, {EXPECTED_CONTROL_REQ_RISES})"
        )
        sb.expect_eq(
            "CHK-XT-SELFLOOP-CONTROL mask clear: ct_dst rises once, request output never rises",
            control,
            (EXPECTED_CT_DST_RISES, EXPECTED_CONTROL_REQ_RISES),
            evidence="CHK-XT-SELFLOOP-CONTROL",
        )
        sb.expect_eq(
            "CHK-XT-SELFLOOP-RETRIGGER first pulse width and a second rise",
            (width, int(len(rises) >= 2)),
            (EXPECTED_FIRST_PULSE_WIDTH, EXPECTED_SECOND_RISE),
            evidence="CHK-XT-SELFLOOP-RETRIGGER",
        )
        sb.expect_eq(
            "CHK-XT-SELFLOOP-ALIVE a request-output rise in the last sub-window of the loop window",
            int(last_rises > 0),
            EXPECTED_ALIVE,
            evidence="CHK-XT-SELFLOOP-ALIVE",
        )
        self._log(
            f"CHK-XT-SELFLOOP-STOP: mask_readback={stop_read} quiet_rises={quiet} "
            f"loop_second_rise={int(len(rises) >= 2)} loop_alive={int(last_rises > 0)} "
            f"rise_in_last_{PRE_WRITE_WINDOW}_samples_before_write={int(pre_rises > 0)}"
        )
        sb.expect_eq(
            "CHK-XT-SELFLOOP-STOP loop running at the write, mask reads back 0, quiet window",
            (stop_read, quiet, int(len(rises) >= 2), int(last_rises > 0), int(pre_rises > 0)),
            (
                SELECT_CLEARED,
                EXPECTED_QUIET_RISES,
                EXPECTED_SECOND_RISE,
                EXPECTED_ALIVE,
                EXPECTED_ALIVE,
            ),
            evidence="CHK-XT-SELFLOOP-STOP",
        )
        logged = tuple(name for name in MEASURED_ITEMS if name in self.measured)
        self._log(f"CHK-XT-SELFLOOP-MEASURED: logged items {logged} measured and logged only")
        sb.expect_eq(
            "CHK-XT-SELFLOOP-MEASURED every measured item was logged",
            logged,
            MEASURED_ITEMS,
            evidence="CHK-XT-SELFLOOP-MEASURED",
        )

        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        expired = sum(rec["expired"] for rec in self.sites) + self.j2a_expired
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} j2a_accesses={self.j2a} "
            f"j2a_poll_limit={J2A_POLL_LIMIT} expired={expired} j2a_last={self.j2a_last}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait sites per kind",
            (kinds, self.j2a),
            (EXPECTED_SITE_KINDS, EXPECTED_J2A_ACCESSES),
            evidence="CHK-TIMEOUT-PATHS",
        )

        stamps = [self.step_ns[s] for s in STEPS]
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(STEPS, stamps))
        gap_cycles = round((self.step_ns["S11"] - self.step_ns["S10"]) / self.cfg.smu_clk_period_ns)
        self._log(f"CHK-NONVAC: ordered sim-time fence {fence} s11_gap_cycles={gap_cycles}")
        sb.expect_eq(
            "CHK-NONVAC ordered sim-time fence",
            (all(b > a for a, b in zip(stamps, stamps[1:])), gap_cycles),
            (True, STEP_CLOCK_GAP),
            evidence="CHK-NONVAC",
        )
        self.done = True

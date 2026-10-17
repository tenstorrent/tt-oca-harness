# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI series completion across TCK to clk_smu_i ratios.

The test runs the same four-word series write and four single-load series reads at TCK periods of
40, 48, 32, 20 and 40 ns against a 10 ns clk_smu_i, each leg on a fresh JTAG master. The clk_smu_i
period measured over four rising edges and the bench period from +pll_sys_period_ns are compared
with the 10 ns system clock setting, so the ratios of the legs rest on a graded period. The legs at
ratio 4.0 and 4.8 and the recovery leg at ratio 4.0 after SERIES_CTRL.reset compare completion,
data, SERIES_CTRL.op and the write-launch and write-response counters at the SMU boundary. The legs
at ratio 3.2 and 2.0 are measured and logged only, except that SERIES_CTRL.op is 0 or 3 and never
1 or 2. A series read is one SERIES_CTRL read load followed by two data scans; capture 2 is the
word.

Sources: doc/integrator/src/smu-composition.adoc and doc/integrator/src/smu-dtp.adoc (system clock
and TCK settings), hw/ip/jtag/jtag_ptap/doc/architecture.adoc (*_AXI_SERIES_CTRL op codes and
reset, *_AXI_SERIES_DATA_INCR), hw/sys/dtp/doc/jtag.adoc (JTAG2AXI bridge table).
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_indexed_addr
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SERIES_CTRL,
    DTP_IR_WIDTH,
    J2A_OP_NOP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_SERIES_CTRL_LEN,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    pack_smc_series_ctrl,
    require_jtag_tdo_resolved,
    unpack_smc_series_ctrl,
)

# hw/sys/smc/regs/gen/c/smc_addr.h: SCRATCH_COLD_WARM is eight 32-bit words at 0xC0002880
# (hw/sys/smc/regs/blocks/scratch/scratch.rdl).
_SCRATCH_WARM = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR"
# Words of one series.
SERIES_WORDS = 4
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_DATA_INCR: n = 8 * 2**E bits, E = 2.
DATA_BITS = 8 << SMC_DBG_AXSIZE_4B
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_CTRL op: 0 okay, 3 an operation
# attempted before the previous one completed.
OP_OKAY = 0
OP_PENDING = J2A_STATUS_BUSY
LOW_LEGS = ("3P2", "2P0")
# doc/integrator/src/smu-composition.adoc, system clock settings: the 100 MHz setting is 10 ns.
SYS_CLK_PERIOD_NS = 10.0
# Rising edges over which the clk_smu_i period is measured and the relative tolerance it is held
# to against the setting.
SYS_CLK_PERIOD_EDGES = 4
SYS_CLK_PERIOD_TOLERANCE = 0.01

# Legs: (name, TCK period in ns, first word of the series). TCK periods give ratios 4.0, 4.8, 3.2,
# 2.0 against the system clock (doc/integrator/src/smu-dtp.adoc, TCK 10 MHz to 50 MHz).
LEG_4P0 = ("4P0", 40, 0x4040_0001)
LEG_4P8 = ("4P8", 48, 0x4848_0001)
LEG_3P2 = ("3P2", 32, 0x3232_0001)
LEG_2P0 = ("2P0", 20, 0x2020_0001)
LEG_RECOVERY = ("RECOVERY", 40, 0x4A4A_0001)
SETUP_TCK_NS = 40

GATE_POLL_LIMIT = 400
GATE_POLL_CLK = 50
OP_POLL_LIMIT = 16
POLL_CLK = 16
B_POLL_LIMIT = 64
B_POLL_CLK = 4
RETRY_LIMIT = 4
# TCKs spent in Run-Test/Idle after a data scan so the target can finish, and per retry
# (hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_CTRL op 3 guidance).
SERIES_IDLE_TCKS = 16
RETRY_IDLE_TCKS = 64

# Wait sites per kind: the gate wait; the SERIES_CTRL.op poll and the B counter wait of each of the
# five legs; the retry loops of the 3.2 and 2.0 legs.
EXPECTED_SITE_KINDS = {"gate": 1, "op_poll": 5, "b_count": 5, "retry": 2}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_CYCLES = 2
CHECK_ORDER = (
    "CHK-DBG-RATIO-SETUP",
    "CHK-DBG-RATIO-COMPLETE-4P0",
    "CHK-DBG-RATIO-COMPLETE-4P8",
    "CHK-DBG-RATIO-OP3-RULE",
    "CHK-DBG-RATIO-RECOVERY",
)


def _word_addr(idx: int) -> int:
    return smc_indexed_addr(_SCRATCH_WARM, idx)


class smu_dtp_jtag2axi_ratio_floor_test_seq:
    """SMC fabric series completion at TCK to clk_smu_i ratios 4.0, 4.8, 3.2, 2.0 and 4.0."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.ir_cur: int | None = None
        self.leg = "setup"
        self.scans = 0
        self.polls = 0
        self.step_ns: dict[str, float] = {}
        self.step_scans: dict[str, int] = {}
        self.sites: list[dict] = []
        self.checks: dict[str, tuple] = {}
        self.op_log: list[tuple[str, int]] = []
        self.legs: dict[str, dict] = {}
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.step_ns[step] = self._now()
        self.step_scans[step] = self.scans
        self._log(f"STEP {step} @{self.step_ns[step]:.3f}ns scans={self.scans}: {text}")

    def _site(
        self, kind: str, label: str, bound: int, unit: str, used: int, last: str, expired: bool
    ) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} {unit} used={used} last_state={last}"
            )

    def _check(self, chk: str, proof: str, got, want) -> None:
        self.checks[chk] = (proof, got, want)

    def _counts(self) -> tuple[int, int, int]:
        dut = self.dut
        return (
            sample(dut.dtp_smc_dbg_aw_count_o, "dtp_smc_dbg_aw_count_o"),
            sample(dut.dtp_smc_dbg_ar_count_o, "dtp_smc_dbg_ar_count_o"),
            sample(dut.dtp_smc_dbg_b_count_o, "dtp_smc_dbg_b_count_o"),
        )

    @staticmethod
    def _delta(now: tuple[int, int, int], base: tuple[int, int, int]) -> tuple[int, int, int]:
        return tuple((n - b) & 0xFFFF_FFFF for n, b in zip(now, base))

    async def _idle(self, tcks: int) -> None:
        for _ in range(tcks):
            await self.jtag.step_tms(0)

    async def _new_master(self, period_ns: int) -> None:
        self.jtag = make_smu_jtag_tap(self.dut, period_ns)
        await self.jtag.reset_tap()
        self.ir_cur = None
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)

    async def _ir(self, opcode: int, label: str) -> None:
        if self.ir_cur == opcode:
            return
        captured = await self.jtag.shift_ir(opcode, width=DTP_IR_WIDTH, back_to_rti=False)
        require_jtag_tdo_resolved(f"IR {label}")
        self.ir_cur = opcode
        self._log(f"SCAN IR {label} w={DTP_IR_WIDTH} in=0x{opcode:x} out=0x{captured:x}")

    async def _dr(
        self, opcode: int, value: int, width: int, label: str, *, counted: bool = True
    ) -> int:
        await self._ir(opcode, label)
        captured = await self.jtag.shift_dr(value, width, back_to_rti=True)
        require_jtag_tdo_resolved(f"DR {label}")
        if counted:
            self.scans += 1
            tag = f"SCAN {self.scans}"
        else:
            self.polls += 1
            tag = f"POLL {self.polls}"
        self._log(f"{tag} DR {label} w={width} in=0x{value:x} out=0x{captured:x}")
        return captured

    async def _ctrl(
        self, op: int, addr: int, label: str, *, reset: int = 0, counted: bool = True
    ) -> tuple[int, int, int, int, int]:
        """Scan SERIES_CTRL; returns the captured (reset, addr, pl_depth, size, op)."""
        word = pack_smc_series_ctrl(op, addr, pipeline_depth=0, size=SMC_DBG_AXSIZE_4B, reset=reset)
        captured = await self._dr(
            DTP_IR_SMC_AXI_SERIES_CTRL, word, SMC_DBG_SERIES_CTRL_LEN, label, counted=counted
        )
        fields = unpack_smc_series_ctrl(captured)
        self.op_log.append((self.leg, fields[-1]))
        return fields

    async def _nop_op(self, label: str) -> int:
        """Capture SERIES_CTRL.op with a nop control scan."""
        *_, op = await self._ctrl(J2A_OP_NOP, 0, label)
        return op

    async def _data(self, value: int, label: str) -> int:
        captured = await self._dr(self.op_incr, value, DATA_BITS, label)
        await self._idle(SERIES_IDLE_TCKS)
        return captured & ((1 << DATA_BITS) - 1)

    async def _wait_op(self, label: str) -> int:
        """Capture op with nop control scans until it leaves 3; returns the op."""
        used = 0
        first = None
        while True:
            _, _, field, _, status = await self._ctrl(
                J2A_OP_NOP, 0, f"{label}_op{used}", counted=False
            )
            used += 1
            first = field if first is None else first
            if status != OP_PENDING:
                break
            if used >= OP_POLL_LIMIT:
                self._site("op_poll", label, OP_POLL_LIMIT, "captures", used, f"op={status}", True)
            if self.leg in LOW_LEGS:
                await self._idle(RETRY_IDLE_TCKS)
            else:
                await ClockCycles(self.dut.clk_smu_i, POLL_CLK)
        self._site("op_poll", label, OP_POLL_LIMIT, "captures", used, f"op={status}", False)
        self._log(
            f"OBSERVATION {label} pl_depth field of the first SERIES_CTRL capture measured={first}"
        )
        return status

    async def _wait_b(self, base: tuple[int, int, int], label: str) -> None:
        """Poll the B counter at the SMU boundary until it shows a completion per word."""
        used = 0
        while True:
            delta = self._delta(self._counts(), base)[2]
            if delta >= SERIES_WORDS:
                break
            if used >= B_POLL_LIMIT:
                self._site("b_count", label, B_POLL_LIMIT, "polls", used, f"b_delta={delta}", True)
            used += 1
            await ClockCycles(self.dut.clk_smu_i, B_POLL_CLK)
        self._site("b_count", label, B_POLL_LIMIT, "polls", used, f"b_delta={delta}", False)

    async def _retry_pending(self, label: str, status: int, retries: list[int]) -> int:
        """While a capture reads 3 give 64 Run-Test/Idle TCKs and capture op again."""
        while status == OP_PENDING:
            if retries[0] >= RETRY_LIMIT:
                self._site(
                    "retry", self.leg, RETRY_LIMIT, "retries", retries[0], f"op={status}", True
                )
            retries[0] += 1
            await self._idle(RETRY_IDLE_TCKS)
            status = await self._nop_op(f"{label}_retry{retries[0]}")
            retries[1] = status
        return status

    async def run(self) -> None:
        self.op_incr = dtp_ir_opcode("SMC_AXI_SERIES_DATA_INCR")
        await self._setup()
        await self._mark("S2", "ratio 4.0 series write and single-load reads")
        await self._leg(LEG_4P0, measured=False)
        await self._mark("S3", "ratio 4.8 series write and single-load reads")
        await self._leg(LEG_4P8, measured=False)
        await self._mark("S4", "ratio 3.2 series write and single-load reads, measured only")
        await self._leg(LEG_3P2, measured=True)
        await self._mark("S5", "ratio 2.0 series write and single-load reads, measured only")
        await self._leg(LEG_2P0, measured=True)
        await self._mark("S6", "op code rule over the 3.2 and 2.0 captures")
        self._op_rule()
        await self._mark("S7", "series reset and ratio 4.0 recovery series")
        await self._leg(LEG_RECOVERY, measured=False, reset_first=True)
        await self._finish()

    async def _setup(self) -> None:
        await self._mark("S1", "TAP reset, IDCODE, gate, counter baseline, SERIES_CTRL reset")
        clk = self.dut.clk_smu_i
        await RisingEdge(clk)
        t0_ps = get_sim_time(unit="ps")
        for _ in range(SYS_CLK_PERIOD_EDGES):
            await RisingEdge(clk)
        period_ns = (get_sim_time(unit="ps") - t0_ps) / SYS_CLK_PERIOD_EDGES / 1000.0
        period_within = abs(period_ns - SYS_CLK_PERIOD_NS) <= (
            SYS_CLK_PERIOD_TOLERANCE * SYS_CLK_PERIOD_NS
        )
        cfg_period_ns = float(self.cfg.smu_clk_period_ns)
        await self._new_master(SETUP_TCK_NS)
        self.scans += 1
        idcode = await self.jtag.read_idcode()
        self.ir_cur = None
        require_jtag_tdo_resolved("IDCODE")
        self._log(f"SCAN {self.scans} DR IDCODE out=0x{idcode:08x}")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:08x} got 0x{idcode:08x}")

        gate = self.dut.tb_smc_jtag2axi_security_disable
        used = 0
        while True:
            val = gate.value
            if val.is_resolvable and int(val) == 0:
                break
            if used >= GATE_POLL_LIMIT:
                self._site(
                    "gate", "security_disable", GATE_POLL_LIMIT, "polls", used, str(val), True
                )
            used += 1
            await ClockCycles(clk, GATE_POLL_CLK)
        self._site("gate", "security_disable", GATE_POLL_LIMIT, "polls", used, str(val), False)
        gate_value = int(gate.value)
        base = self._counts()
        *_, before = await self._ctrl(J2A_OP_NOP, 0, "setup_reset", reset=1)
        after = await self._nop_op("setup_after_reset")
        ratio_unset = self.test.min_jtag_smu_ratio is None
        self._log(
            f"OBSERVATION min_jtag_smu_ratio unset {ratio_unset}, gate tap read {gate_value} "
            f"after {used} polls; measured and logged only"
        )
        self._check(
            "CHK-DBG-RATIO-SETUP",
            f"clk_smu_i period {period_ns:.3f} ns over {SYS_CLK_PERIOD_EDGES} edges within "
            f"{SYS_CLK_PERIOD_TOLERANCE * 100:.0f} % of the {SYS_CLK_PERIOD_NS} ns system clock "
            f"setting {period_within}, bench +pll_sys_period_ns period {cfg_period_ns} ns, "
            f"min_jtag_smu_ratio unset {ratio_unset} logged, gate tap read {gate_value} after "
            f"{used} polls, baselines aw/ar/b={base}, SERIES_CTRL.reset written (op {before} -> "
            f"{after}) (want within True, bench period {SYS_CLK_PERIOD_NS}, op {OP_OKAY})",
            (period_within, cfg_period_ns, after),
            (True, SYS_CLK_PERIOD_NS, OP_OKAY),
        )

    async def _leg(self, leg: tuple[str, int, int], *, measured: bool, reset_first=False) -> None:
        name, period_ns, first_word = leg
        self.leg = name
        start_ns = self._now()
        await self._new_master(period_ns)
        reset_op = None
        if reset_first:
            *_, before = await self._ctrl(J2A_OP_NOP, 0, f"{name}_reset", reset=1)
            reset_op = await self._nop_op(f"{name}_after_reset")
            self._log(f"OBSERVATION {name} op of the last low-ratio capture measured={before}")
        words = tuple(first_word + i for i in range(SERIES_WORDS))
        base = self._counts()
        addr0 = _word_addr(0)
        retries = [0, OP_OKAY]
        *_, op = await self._ctrl(J2A_OP_WRITE, addr0, f"{name}_wr_ctrl")
        if measured:
            retries[1] = op
            await self._retry_pending(f"{name}_wr_ctrl", op, retries)
        for i, word in enumerate(words):
            await self._data(word, f"{name}_wr{i}")
        wr_op = await self._wait_op(f"{name}_wr")
        await self._wait_b(base, f"{name}_wr")
        aw_d, _, b_d = self._delta(self._counts(), base)

        got: list[int] = []
        load_ops = [wr_op]
        word_ops: list[int] = []
        for i in range(SERIES_WORDS):
            *_, op = await self._ctrl(J2A_OP_READ, _word_addr(i), f"{name}_rd{i}_ctrl")
            if measured:
                retries[1] = op
                op = await self._retry_pending(f"{name}_rd{i}_ctrl", op, retries)
            load_ops.append(op)
            await self._data(0, f"{name}_rd{i}_first")
            got.append(await self._data(0, f"{name}_rd{i}_second"))
            if measured:
                op = await self._nop_op(f"{name}_rd{i}_op")
                retries[1] = op
                word_ops.append(await self._retry_pending(f"{name}_rd{i}_op", op, retries))
        if not measured:
            load_ops.append(await self._nop_op(f"{name}_final_op"))
        _, ar_d, _ = self._delta(self._counts(), base)
        elapsed = self._now() - start_ns
        if measured:
            self._site("retry", name, RETRY_LIMIT, "retries", retries[0], f"op={retries[1]}", False)
        rec = {
            "words": tuple(got),
            "want": words,
            "load_ops": tuple(load_ops),
            "word_ops": tuple(word_ops),
            "aw": aw_d,
            "b": b_d,
            "ar": ar_d,
            "retries": retries[0],
            "reset_op": reset_op,
        }
        self.legs[name] = rec
        tck_per_op = elapsed / period_ns / (2 * SERIES_WORDS)
        self._log(
            f"OBSERVATION leg {name} TCK {period_ns} ns: write op {wr_op} load ops {load_ops} "
            f"word ops {word_ops} read words {[hex(w) for w in got]} aw/b/ar delta "
            f"{aw_d}/{b_d}/{ar_d} retries {retries[0]} TCKs per operation {tck_per_op:.1f} "
            "measured"
        )
        if not measured:
            self._complete_check(name, rec)

    def _complete_check(self, name: str, rec: dict) -> None:
        chk = {
            "4P0": "CHK-DBG-RATIO-COMPLETE-4P0",
            "4P8": "CHK-DBG-RATIO-COMPLETE-4P8",
            "RECOVERY": "CHK-DBG-RATIO-RECOVERY",
        }[name]
        ops_want = (OP_OKAY,) * len(rec["load_ops"])
        got = (rec["words"], rec["load_ops"], rec["aw"], rec["b"])
        want = (rec["want"], ops_want, SERIES_WORDS, SERIES_WORDS)
        if name == "RECOVERY":
            got = (rec["reset_op"], *got)
            want = (OP_OKAY, *want)
        self._check(
            chk,
            f"leg {name}: read-backs {[hex(w) for w in rec['words']]} (want "
            f"{[hex(w) for w in rec['want']]}), op after every load {rec['load_ops']} (want all "
            f"{OP_OKAY}), aw/b delta {rec['aw']}/{rec['b']} (want {SERIES_WORDS}), reset op "
            f"{rec['reset_op']}; AR delta {rec['ar']} measured and logged only",
            got,
            want,
        )

    def _op_rule(self) -> None:
        low = [op for leg, op in self.op_log if leg in LOW_LEGS]
        zeros = low.count(OP_OKAY)
        pending = low.count(OP_PENDING)
        outside = tuple(sorted(set(low) - {OP_OKAY, OP_PENDING}))
        integration = tuple(
            sorted({op for leg in ("4P0", "4P8") for op in self.legs[leg]["load_ops"]})
        )
        branch = "exercised" if pending else "NOT-EXERCISED"
        self._log(
            f"OBSERVATION op 3 branch {branch}: captures={len(low)} op0={zeros} op3={pending}"
        )
        self._check(
            "CHK-DBG-RATIO-OP3-RULE",
            f"3.2 and 2.0 legs: {len(low)} op captures, op 0 x{zeros}, op 3 x{pending}, other "
            f"codes {outside} (want none), op 3 branch {branch}; integration op codes "
            f"{integration} (want ({OP_OKAY},))",
            (outside, integration),
            ((), (OP_OKAY,)),
        )

    async def _finish(self) -> None:
        sb = self.sb
        await self._mark("S8", "ordered checker lines, wait sites and the pass stamp")
        failures = []

        def run_check(chk: str, name: str, got, want) -> None:
            try:
                sb.expect_eq(name, got, want, evidence=chk)
            except AssertionError as exc:
                failures.append(str(exc))

        for chk in CHECK_ORDER:
            proof, got, want = self.checks[chk]
            self._log(f"{chk}: {proof}")
            run_check(chk, chk, got, want)

        for rec in self.sites:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        no_last = [rec["label"] for rec in self.sites if not rec["last"]]
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} expired={expired} "
            f"without_last_state={no_last} (want kinds {EXPECTED_SITE_KINDS}, expired 0)"
        )
        run_check(
            "CHK-TIMEOUT-PATHS",
            "wait records",
            (expired, no_last, kinds),
            (0, [], EXPECTED_SITE_KINDS),
        )

        await ClockCycles(self.dut.clk_smu_i, FENCE_CYCLES)
        self.step_ns["PASS"] = self._now()
        self.step_scans["PASS"] = self.scans
        fence_order = [*STEPS, "PASS"]
        stamps = [self.step_ns[s] for s in fence_order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        accesses = [self.step_scans[b] - self.step_scans[a] for a, b in zip(STEPS, STEPS[1:])]
        scanning = tuple(n for step, n in zip(STEPS, accesses) if step != "S6")
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(fence_order, stamps))
        self._log(
            f"CHK-NONVAC: ordered sim-time fence {fence} scans={self.scans} polls={self.polls} "
            f"accesses per step S1..S7={tuple(accesses)}"
        )
        run_check(
            "CHK-NONVAC", "CHK-NONVAC ordered sim-time fence", all(d > 0 for d in deltas), True
        )
        run_check(
            "CHK-NONVAC",
            "CHK-NONVAC accesses per scanning step",
            tuple(n > 0 for n in scanning),
            (True,) * len(scanning),
        )
        if failures:
            raise AssertionError(f"{len(failures)} checker compare(s) failed: {failures}")
        self.done = True

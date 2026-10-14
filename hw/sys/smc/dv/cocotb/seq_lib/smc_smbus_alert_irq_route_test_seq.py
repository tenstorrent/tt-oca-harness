# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMBALERT interrupt enable gating and routing to tb_i2c_irq for the three I2C instances.

Sources: hw/ip/i2c/regs/i2c.rdl (INTR_TEST, INTR_STATE, INTR_ENABLE SMBALERT),
hw/sys/smc/doc/interrupts.adoc (I2C interrupts 0, 1, 2 at peripheral bits 23 to 25).

`INTR_TEST.SMBALERT` latches `INTR_STATE.SMBALERT` with the alert pad idle. The latched bit
reaches `tb_i2c_irq[i]` only while `INTR_ENABLE.SMBALERT` is set, follows each enable write
and clears with a write of 1 to `INTR_STATE.SMBALERT`. The enable-to-output latency is
measured and logged without a compare while the synchroniser latency is open (owner value pending).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import _I2C_H, I2C_INTR_ENABLE_SMBALERT, I2C_INTR_STATE_SMBALERT

INSTANCES = (0, 1, 2)
INTR_TEST_SMBALERT = _field_mask(_I2C_H, "I2C__INTR_TEST__SMBALERT_bm")

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

STATE_POLLS = 500
MASKED_SAMPLES = 16
IRQ_POLLS = 2000
POLL_STEP_CYCLES = 4

FENCE_ORDER = ["SETUP", "PENDING_MASKED", "ROUTED", "TOGGLED", "CLEARED", "TEARDOWN"]
CHECKER_AFTER = {
    "CHK-IRQ-MASKED": "CLEARED",
    "CHK-IRQ-TEST-STATE": "CLEARED",
    "CHK-IRQ-ROUTE": "ROUTED",
    "CHK-IRQ-LATENCY-LOG": "ROUTED",
    "CHK-IRQ-ENABLE-TOGGLE": "CLEARED",
    "CHK-IRQ-CLEAR": "CLEARED",
    "CHK-TIMEOUT-PATHS": "TEARDOWN",
}


def _reg(name: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{name}_BASE_ADDR", idx)


class smc_smbus_alert_irq_route_test_seq(SmcCsrSeq):
    """Drive INTR_TEST.SMBALERT and follow INTR_STATE, INTR_ENABLE and tb_i2c_irq."""

    def __init__(self, name: str = "smc_smbus_alert_irq_route_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.masked: dict[int, str] = {}
        self.latency: dict[int, tuple[int, int, int]] = {}
        self.toggle: dict[int, str] = {}
        self.clear: dict[int, str] = {}
        self.state_polls: dict[int, int] = {}

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _irq() -> int:
        value = cocotb.top.tb_i2c_irq.value
        assert value.is_resolvable, f"tb_i2c_irq sampled X/Z ({value})"
        return int(value)

    async def _state(self, label: str, idx: int) -> int:
        return (await self.csr_read(label, _reg("INTR_STATE", idx))) & I2C_INTR_STATE_SMBALERT

    async def _wait_irq(self, name: str, want: int, only_allowed: int) -> tuple[int, int]:
        """Poll tb_i2c_irq until it equals ``want``; return (polls, ps) taken.

        Bits outside ``only_allowed`` must stay low at every sample.
        """
        start = int(get_sim_time("ps"))
        last = "never sampled"
        for polls in range(IRQ_POLLS):
            got = self._irq()
            last = f"tb_i2c_irq=0b{got:03b}"
            assert got & ~only_allowed == 0, (
                f"{name}: a masked instance bit rose, tb_i2c_irq=0b{got:03b}, "
                f"allowed 0b{only_allowed:03b}"
            )
            if got == want:
                self.waits.append((name, f"{IRQ_POLLS}x{POLL_STEP_CYCLES}cyc", last))
                return polls, int(get_sim_time("ps")) - start
            await ClockCycles(cocotb.top.clk_smc_i, POLL_STEP_CYCLES)
        self.waits.append((name, f"{IRQ_POLLS}x{POLL_STEP_CYCLES}cyc", f"EXPIRED {last}"))
        raise AssertionError(
            f"{name}: tb_i2c_irq not 0b{want:03b} within {IRQ_POLLS}x{POLL_STEP_CYCLES} "
            f"cycles; last {last}"
        )

    async def _set_enable(self, label: str, idx: int, on: bool) -> None:
        await self.csr_write(label, _reg("INTR_ENABLE", idx), I2C_INTR_ENABLE_SMBALERT if on else 0)

    async def _setup(self) -> int:
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for i in INSTANCES:
            await self.csr_write(f"INTR_ENABLE_{i}_ZERO", _reg("INTR_ENABLE", i), 0)
            await self.csr_write(
                f"INTR_STATE_{i}_W1C", _reg("INTR_STATE", i), I2C_INTR_STATE_SMBALERT
            )
        irq = self._irq()
        assert irq == 0, f"tb_i2c_irq=0b{irq:03b} after setup, expected 0b000"
        self._stamp("SETUP")
        return cg

    async def _pending_masked(self) -> None:
        for i in INSTANCES:
            await self.csr_write(f"INTR_TEST_{i}", _reg("INTR_TEST", i), INTR_TEST_SMBALERT)
            state = 0
            for polls in range(STATE_POLLS):
                state = await self._state(f"INTR_STATE_{i}_POLL", i)
                if state:
                    break
            else:
                self.waits.append((f"intr_state_{i}", f"{STATE_POLLS} reads", "EXPIRED state=0"))
                raise AssertionError(
                    f"INTR_STATE.SMBALERT of instance {i} still 0 after {STATE_POLLS} reads"
                )
            self.waits.append((f"intr_state_{i}", f"{STATE_POLLS} reads", f"state=1 at {polls}"))
            self.state_polls[i] = polls + 1
            seen = []
            for _ in range(MASKED_SAMPLES):
                irq = self._irq()
                seen.append(irq)
                assert irq == 0, (
                    f"instance {i}: tb_i2c_irq=0b{irq:03b} with INTR_ENABLE.SMBALERT=0 "
                    f"and INTR_STATE.SMBALERT=1"
                )
                await ClockCycles(cocotb.top.clk_smc_i, POLL_STEP_CYCLES)
            self.masked[i] = (
                f"instance {i}: INTR_STATE.SMBALERT=1 after {self.state_polls[i]} read(s), "
                f"tb_i2c_irq 0b000 in {len(seen)} of {MASKED_SAMPLES} samples"
            )
        self._stamp("PENDING_MASKED")

    async def _routed(self) -> None:
        for i in INSTANCES:
            await self._set_enable(f"INTR_ENABLE_{i}_ON", i, True)
            polls, ps = await self._wait_irq(f"route_rise_{i}", 1 << i, 1 << i)
            await self._set_enable(f"INTR_ENABLE_{i}_OFF", i, False)
            await self._wait_irq(f"route_fall_{i}", 0, 0)
            self.latency[i] = (polls, polls * POLL_STEP_CYCLES, ps)
        self._stamp("ROUTED")
        self._chk(
            "CHK-IRQ-ROUTE",
            "; ".join(
                f"instance {i}: enable written 1 with the interrupt pending, tb_i2c_irq="
                f"0b{1 << i:03b} observed after {self.latency[i][0]} polls, enable written 0, "
                f"tb_i2c_irq=0b000 checked_cleared"
                for i in INSTANCES
            ),
        )
        self._chk(
            "CHK-IRQ-LATENCY-LOG",
            "; ".join(
                f"instance {i}: enable_to_irq_polls={self.latency[i][0]} "
                f"enable_to_irq_clk_smc_cycles={self.latency[i][1]} "
                f"enable_to_irq_ps={self.latency[i][2]}"
                for i in INSTANCES
            )
            + "; logged only, no value compared (owner value pending)",
        )

    async def _toggled(self) -> None:
        for i in INSTANCES:
            levels = []
            for step, on in (("on1", True), ("off", False), ("on2", True)):
                await self._set_enable(f"INTR_ENABLE_{i}_{step}", i, on)
                want = (1 << i) if on else 0
                polls, _ = await self._wait_irq(f"toggle_{step}_{i}", want, 1 << i)
                levels.append(f"0b{want:03b}@{polls}")
            await self._set_enable(f"INTR_ENABLE_{i}_rel", i, False)
            await self._wait_irq(f"toggle_release_{i}", 0, 0)
            self.toggle[i] = f"instance {i}: writes 1,0,1 gave tb_i2c_irq {','.join(levels)} polls"
        self._stamp("TOGGLED")

    async def _cleared(self) -> None:
        for i in INSTANCES:
            await self._set_enable(f"INTR_ENABLE_{i}_ARM", i, True)
            await self._wait_irq(f"clear_arm_{i}", 1 << i, 1 << i)
            before = self._irq()
            assert before == 1 << i, (
                f"instance {i}: tb_i2c_irq=0b{before:03b} before the clear, expected 0b{1 << i:03b}"
            )
            await self.csr_write(
                f"INTR_STATE_{i}_CLR", _reg("INTR_STATE", i), I2C_INTR_STATE_SMBALERT
            )
            state = await self._state(f"INTR_STATE_{i}_CLRD", i)
            assert state == 0, f"instance {i}: INTR_STATE.SMBALERT still set after W1C"
            polls, _ = await self._wait_irq(f"clear_fall_{i}", 0, 0)
            await self._set_enable(f"INTR_ENABLE_{i}_END", i, False)
            self.clear[i] = (
                f"instance {i}: tb_i2c_irq=0b{before:03b} before the W1C, INTR_STATE.SMBALERT "
                f"reads 0 and tb_i2c_irq=0b000 after {polls} polls"
            )
        self._stamp("CLEARED")
        self._chk(
            "CHK-IRQ-MASKED",
            "set: 1 written to INTR_TEST.SMBALERT; observed: "
            + "; ".join(self.masked[i] for i in INSTANCES)
            + "; cleared: 1 written to INTR_STATE.SMBALERT; checked_cleared: INTR_STATE.SMBALERT "
            "reads 0 on all three instances",
        )
        self._chk(
            "CHK-IRQ-TEST-STATE",
            "set: 1 written to INTR_TEST.SMBALERT with the pad idle; observed: INTR_STATE.SMBALERT "
            "read 1 after "
            + ",".join(str(self.state_polls[i]) for i in INSTANCES)
            + " reads (instances 0,1,2); cleared: 1 written to INTR_STATE.SMBALERT; "
            "checked_cleared: INTR_STATE.SMBALERT reads 0 on all three instances",
        )
        self._chk(
            "CHK-IRQ-ENABLE-TOGGLE",
            "set: INTR_ENABLE.SMBALERT toggled 1,0,1 with the interrupt pending; observed: "
            + "; ".join(self.toggle[i] for i in INSTANCES)
            + "; cleared: 1 written to INTR_STATE.SMBALERT; checked_cleared: tb_i2c_irq 0b000",
        )
        self._chk(
            "CHK-IRQ-CLEAR",
            "set: INTR_STATE.SMBALERT=1 with the enable set; observed: "
            + "; ".join(self.clear[i] for i in INSTANCES)
            + "; cleared: 1 written to INTR_STATE.SMBALERT; checked_cleared: "
            "INTR_STATE.SMBALERT reads 0 and tb_i2c_irq reads 0b000",
        )

    async def _teardown(self, cg: int) -> None:
        for i in INSTANCES:
            await self.csr_write(f"INTR_ENABLE_{i}_TD", _reg("INTR_ENABLE", i), 0)
            await self.csr_write(
                f"INTR_STATE_{i}_TD", _reg("INTR_STATE", i), I2C_INTR_STATE_SMBALERT
            )
        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        self._stamp("TEARDOWN")

    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + [axi]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with its last "
            "state on expiry; %s",
            len(waits),
            "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )
        self.chk_lines.append(("CHK-TIMEOUT-PATHS", len(self.stamps)))

    def _emit_nonvac(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = dict(self.chk_lines)
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never printed"
            assert printed[name] > order.index(term), f"{name} printed before {term}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        cg = await self._setup()
        await self._pending_masked()
        await self._routed()
        await self._toggled()
        await self._cleared()
        await self._teardown(cg)
        self._emit_timeout_paths()
        self._emit_nonvac()

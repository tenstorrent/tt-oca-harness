# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generic base sequence for DTP cocotb stimulus.

This class intentionally stays feature-agnostic. Feature-specific helpers live in
child base sequences such as ``dtp_jtag_base_test_seq``,
``dtp_debug_tdr_base_test_seq``, and ``dtp_jtag2axi_base_test_seq``.
The test assigns ``cfg`` before starting the sequence (see DtpBaseTest.start_seq).
"""

from __future__ import annotations

import logging
import os
import random

import cocotb
from cocotb.triggers import ClockCycles
from pyuvm import uvm_sequence

from env.dtp_dbg_disable import (
    DBG_DISABLE_FIELDS,
    format_dbg_disable,
    full_dbg_disable,
    validate_dbg_disable,
)
from env.dtp_jtag_item import DtpJtagItem, DtpJtagOp
from env.dtp_types import DTP_IR_WIDTH, DtpJtagInstr, DtpTapState


class dtp_base_test_seq(uvm_sequence):
    """Common DTP protocol building blocks; concrete sequences override body()."""

    def __init__(
        self,
        name: str = "dtp_base_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name)
        self.log = logging.getLogger(name)
        # Assigned by the test (DtpBaseTest.start_seq) before the sequence runs.
        self.cfg = None
        self.visited_tap_states: set[DtpTapState] = set()
        self.current_tap_state: DtpTapState | None = None
        self.scenario_seed = scenario_seed
        self.random_count = random_count

    # --- quality logging / checking -----------------------------------------
    def log_banner(self, title: str) -> None:
        """Log a visible scenario boundary in simulation output."""
        self.log.info("=" * 70)
        self.log.info(title)
        self.log.info("=" * 70)

    def log_step(self, step: int | str, message: str, *args) -> None:
        """Log a numbered verification step."""
        self.log.info("Step %s: " + message, step, *args)

    def log_iteration(self, index: int, total: int, message: str, *args) -> None:
        """Log loop iteration context before applying stimulus."""
        self.log.info("Iteration %d/%d: " + message, index, total, *args)

    def log_summary(self, title: str, **fields: object) -> None:
        """Log a compact end-of-scenario summary."""
        self.log.info("-" * 70)
        self.log.info("Summary: %s", title)
        for key, value in fields.items():
            self.log.info("  %s = %s", key, value)
        self.log.info("-" * 70)

    def assert_equal(self, name: str, observed: int, expected: int, context: str = "") -> None:
        """Log and assert an expected/observed integer comparison."""
        context_suffix = f" ({context})" if context else ""
        self.log.info(
            "CHECK %-36s expected=0x%x observed=0x%x%s",
            name,
            expected,
            observed,
            context_suffix,
        )
        assert observed == expected, (
            f"{name}{context_suffix}: expected 0x{expected:x}, got 0x{observed:x}"
        )

    def assert_bit(self, name: str, value: int, bit_pos: int, expected: int) -> None:
        """Log and assert one bit of a packed value."""
        self.assert_equal(f"{name}[{bit_pos}]", self.bit(value, bit_pos), expected)

    # --- deterministic random / pattern helpers -----------------------------
    @staticmethod
    def random_seed() -> int:
        """Return the runner-provided seed, with a deterministic local default."""
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    def rng(self, salt: str = "") -> random.Random:
        """Return a deterministic local RNG for this sequence and optional salt."""
        label = salt or getattr(self, "name", self.__class__.__name__)
        salt_value = sum((idx + 1) * ord(ch) for idx, ch in enumerate(label))
        base_seed = self.scenario_seed if self.scenario_seed is not None else self.random_seed()
        seed = base_seed ^ salt_value
        self.log.info("Using deterministic random seed %d for %s", seed, label)
        return random.Random(seed)

    @staticmethod
    def bit(value: int, bit_pos: int) -> int:
        """Return one bit from an integer."""
        return (value >> bit_pos) & 0x1

    @staticmethod
    def field(value: int, lsb: int, width: int) -> int:
        """Return a packed bit field."""
        return (value >> lsb) & ((1 << width) - 1)

    @staticmethod
    def _bit_mask(width: int) -> int:
        return (1 << width) - 1

    def random_pattern(self, width: int, rng: random.Random) -> int:
        """Generate one deterministic random scan pattern."""
        return rng.getrandbits(width) & self._bit_mask(width)

    def directed_patterns(
        self,
        width: int,
        *,
        rng: random.Random | None = None,
        random_count: int | None = None,
    ) -> list[int]:
        """Return edge, alternating, walking, and deterministic random patterns."""
        mask = self._bit_mask(width)
        patterns = [
            0,
            mask,
            0xAAAA_AAAA_AAAA_AAAA & mask,
            0x5555_5555_5555_5555 & mask,
            0xA5A5_5A5A_C3C3_3C3C & mask,
            0x0123_4567_89AB_CDEF & mask,
        ]
        for bit_pos in sorted({0, width // 4, width // 2, (3 * width) // 4, width - 1}):
            patterns.append(1 << bit_pos)
            patterns.append(mask ^ (1 << bit_pos))
        rand = rng or self.rng("directed_patterns")
        count = self.random_count if random_count is None else random_count
        for _ in range(count):
            patterns.append(self.random_pattern(width, rand))
        return list(dict.fromkeys(patterns))

    # --- low-level item issue ------------------------------------------------
    async def _send(self, **fields) -> DtpJtagItem:
        """Create, populate, and run a single DtpJtagItem; return it with results."""
        item = DtpJtagItem()
        await self.start_item(item)
        for key, value in fields.items():
            setattr(item, key, value)
        await self.finish_item(item)
        return item

    # --- reusable TAP steps --------------------------------------------------
    async def reset_tap(self) -> DtpJtagItem:
        """Drive the TAP to Test-Logic-Reset."""
        return await self._send(op=DtpJtagOp.RESET_FSM)

    async def tms_step(self, tms: int) -> DtpJtagItem:
        """Drive one raw TMS cycle and return the observed DUT TAP state."""
        return await self._send(op=DtpJtagOp.TMS_STEP, tms=tms)

    async def load_ir(
        self,
        instr: DtpJtagInstr | int,
        *,
        back_to_rti: bool = True,
    ) -> DtpJtagItem:
        """Load a raw IR opcode and return captured previous-IR bits."""
        value = int(instr)
        self.log.info("Loading IR 0x%02x", value)
        item = await self._send(
            op=DtpJtagOp.SHIFT_IR,
            value=value,
            width=DTP_IR_WIDTH,
            back_to_rti=back_to_rti,
        )
        if back_to_rti:
            self.current_tap_state = DtpTapState.RUN_TEST_IDLE
            self.visited_tap_states.add(DtpTapState.RUN_TEST_IDLE)
        return item

    async def shift_dr(
        self,
        value: int,
        width: int,
        *,
        back_to_rti: bool = True,
    ) -> DtpJtagItem:
        """Shift raw DR data and return captured TDO bits."""
        item = await self._send(
            op=DtpJtagOp.SHIFT_DR,
            value=value,
            width=width,
            back_to_rti=back_to_rti,
        )
        if back_to_rti:
            self.current_tap_state = DtpTapState.RUN_TEST_IDLE
            self.visited_tap_states.add(DtpTapState.RUN_TEST_IDLE)
        return item

    async def sample_observables(self) -> DtpJtagItem:
        """Sample exposed DUT observables through the JTAG driver."""
        return await self._send(op=DtpJtagOp.SAMPLE)

    async def assert_trst(self, cycles: int = 5) -> DtpJtagItem:
        """Assert active-low TRST_N and sample the TAP state."""
        return await self._send(op=DtpJtagOp.SET_TRST, value=0, cycles=cycles)

    async def deassert_trst(self, cycles: int = 1) -> DtpJtagItem:
        """Deassert TRST_N and sample the TAP state."""
        return await self._send(op=DtpJtagOp.SET_TRST, value=1, cycles=cycles)

    async def pulse_por(self, cycles: int = 5) -> DtpJtagItem:
        """Pulse power-on reset and sample the TAP state while reset is asserted."""
        return await self._send(op=DtpJtagOp.PULSE_POR, cycles=cycles)

    async def read_idcode(self) -> DtpJtagItem:
        """Read the 32-bit IDCODE TDR."""
        return await self._send(op=DtpJtagOp.READ, reg="IDCODE")

    async def read_tdr(self, reg: str, shift_value: int = 0) -> int:
        """Read a named TDR, shifting caller-selected data through DR.

        The default shift value is zero, which is useful for catching unwanted
        R/W side effects. Tests that need to preserve writable bits should pass
        the expected retained value explicitly.
        """
        item = await self._send(op=DtpJtagOp.READ, reg=reg, value=shift_value)
        return item.result

    async def write_tdr(self, reg: str, value: int) -> None:
        """Write a named TDR through the shared JTAG driver."""
        await self._send(op=DtpJtagOp.WRITE, reg=reg, value=value)

    # --- lifecycle debug disables ---------------------------------------------
    # The DUT synchronizes dbg_disable_i through 2-stage TCK-domain flops, so
    # a disable change is only guaranteed visible after TCK has toggled.
    async def wait_dbg_disable_sync(self) -> None:
        """Settle a dbg_disable change: four idle TCK cycles (TB margin over
        the 2-stage synchronizers), then a short system-domain settle for the
        bridge-side logic behind them."""
        for _ in range(4):
            await self.tms_step(0)
        await self.wait_sys_cycles(4)

    async def set_dbg_disable(self, **bits: int) -> None:
        """Drive named dbg_disable fields (1 = disabled); others keep state."""
        named = validate_dbg_disable(bits)
        dut = cocotb.top
        for name, value in named.items():
            getattr(dut, f"dbg_disable_{name}").value = value
        self.log.info("dbg_disable set %s", format_dbg_disable(named))
        await self.wait_dbg_disable_sync()

    async def set_dbg_disable_vector(self, values) -> None:
        """Drive all eleven dbg_disable fields; unnamed fields are enabled (0)."""
        await self.set_dbg_disable(**full_dbg_disable(values))

    async def enable_all_debug(self) -> None:
        """Clear every disable: full debug access."""
        await self.set_dbg_disable_vector({})

    async def disable_debug_bits(self, *names: str) -> None:
        """Assert one or more named disables; other fields keep state."""
        await self.set_dbg_disable(**{name: 1 for name in names})

    def dbg_resource_enabled(self, name: str) -> bool:
        """Read back one driven dbg_disable input; True when enabled (0)."""
        if name not in DBG_DISABLE_FIELDS:
            raise ValueError(f"unknown dbg_disable field {name!r}")
        return int(getattr(cocotb.top, f"dbg_disable_{name}").value) == 0

    # --- system-domain helpers ----------------------------------------------
    async def wait_sys_cycles(self, cycles: int = 4) -> None:
        """Wait in the system-clock domain for registered DTP outputs to update."""
        await ClockCycles(cocotb.top.clk_i, cycles)

    async def pulse_system_reset(self, cycles: int = 5) -> None:
        """Pulse rst_n_i without asserting POR/TRST, preserving TAP accessibility."""
        cocotb.top.rst_n_i.value = 0
        await self.wait_sys_cycles(cycles)
        cocotb.top.rst_n_i.value = 1
        await self.wait_sys_cycles(cycles)

    async def expect_signal(self, name: str, expected: int) -> None:
        """Sample a flattened top-level observable and compare it."""
        item = await self.sample_observables()
        assert name in item.signals, f"{name} is not exposed by the DTP JTAG driver"
        observed = item.signals[name]
        self.assert_equal(name, observed, expected)

    async def body(self) -> None:
        raise NotImplementedError("override body() in a concrete test sequence")

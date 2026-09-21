# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_ss_reset_ctrl_sweep_test. No Force.

``ss_reset_ctrl_o`` is an array of 32 ``smc_reset_unit_pkg::reset_ctrl_t``
elements, one per subsystem, and each of its seven fields is owned by one
32-bit SMC reset-unit register whose bit i belongs to subsystem i
(``hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl``):

* ``SS_COLD_RESET_N.reset_n_n0_scan``      -> ``cold_reset_n``
* ``SS_WARM_RESET_N.reset_n_n0_scan``      -> ``warm_reset_n``
* ``SS_CONFIG_HOLD.configuration_state_hold`` -> ``config_state_hold``
* ``SS_SRAM_HOLD.sram_hold``               -> ``sram_hold``
* ``SS_CRITICAL_HOLD.critical_signal_hold`` -> ``critical_signal_hold``
* ``SS_DEBUG_HOLD.debug_hold``             -> ``debug_hold``
* ``SS_FORCE_TO_REF_CLK.force_ss_to_ref_clk_n`` -> ``force_to_ref_clk_n``

The two reset fields are active low, and the RDL gives them opposite reset
values: cold reset is held asserted (``0x0``) and warm reset released
(``0xFFFFFFFF``). The five remaining fields reset to ``0x0``. Every expected
value here is the mask or the reset constant the generated
``reset_unit.h`` carries for that field, and every compare is between two
values the DUT produced -- a CSR read-back and the boundary word the
testbench assembles from ``ss_reset_ctrl_o[i].<field>`` -- or between a
read-back and the RDL constant.

The sweep walks each register through the five binary-code patterns and their
complements, so lane i answers with a signature that is unique to i and any
lane permutation between register bit and subsystem element shows up. The pair
structure also puts both a 0 and a 1 on every bit, and the walk starts and
ends at the register's reset value, so every bit of all 32x7 fields is
observed rising and falling at the boundary.

``SS_COLD_RESET_LOCK`` is ``onwrite = woset``: a bit set there can never be
cleared and blocks further writes to the same bit of ``SS_COLD_RESET_N``. The
lock leg therefore runs after the cold-reset sweep, and it leaves the locked
lane at the register's reset value.
"""

from __future__ import annotations

from typing import NamedTuple

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import reset_unit_u32, smc_addr
from seq_lib.smu_compose_helpers import NUM_SUBSYSTEMS
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


class SsResetCtrlField(NamedTuple):
    """One ``reset_ctrl_t`` field, the register that owns it and its observe."""

    field: str
    addr: int
    mask: int
    reset: int
    pin: str


def _field(field: str, reg: str, rdl_field: str, pin: str) -> SsResetCtrlField:
    return SsResetCtrlField(
        field=field,
        addr=smc_addr(f"SMC_TOP_SMC_RESET_UNIT_{reg}_BASE_ADDR"),
        mask=reset_unit_u32(f"RESET_UNIT__{reg}__{rdl_field}_bm"),
        reset=reset_unit_u32(f"RESET_UNIT__{reg}__{rdl_field}_reset"),
        pin=pin,
    )


SS_RESET_CTRL_FIELDS: tuple[SsResetCtrlField, ...] = (
    _field("cold_reset_n", "SS_COLD_RESET_N", "RESET_N_N0_SCAN", "tb_ss_cold_reset_n"),
    _field("warm_reset_n", "SS_WARM_RESET_N", "RESET_N_N0_SCAN", "tb_ss_warm_reset_n"),
    _field(
        "config_state_hold",
        "SS_CONFIG_HOLD",
        "CONFIGURATION_STATE_HOLD",
        "tb_ss_config_state_hold",
    ),
    _field("sram_hold", "SS_SRAM_HOLD", "SRAM_HOLD", "tb_ss_sram_hold"),
    _field(
        "critical_signal_hold",
        "SS_CRITICAL_HOLD",
        "CRITICAL_SIGNAL_HOLD",
        "tb_ss_critical_signal_hold",
    ),
    _field("debug_hold", "SS_DEBUG_HOLD", "DEBUG_HOLD", "tb_ss_debug_hold"),
    _field(
        "force_to_ref_clk_n",
        "SS_FORCE_TO_REF_CLK",
        "FORCE_SS_TO_REF_CLK_N",
        "tb_ss_force_to_ref_clk_n",
    ),
)

SS_RESET_CTRL_BY_FIELD = {entry.field: entry for entry in SS_RESET_CTRL_FIELDS}

SS_COLD_RESET_LOCK = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR")
SS_COLD_RESET_LOCK_BM = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_LOCK__COLD_RESET_LOCK_bm")
SS_COLD_RESET_LOCK_RESET = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_LOCK__COLD_RESET_LOCK_reset")

# Lane signatures: pattern 2k holds bit k of the lane index and pattern 2k+1
# its complement, so the ten answers of lane i spell i and its complement.
LANE_CODE_PATTERNS: tuple[int, ...] = (
    0xAAAA_AAAA,
    0x5555_5555,
    0xCCCC_CCCC,
    0x3333_3333,
    0xF0F0_F0F0,
    0x0F0F_0F0F,
    0xFF00_FF00,
    0x00FF_00FF,
    0xFFFF_0000,
    0x0000_FFFF,
)
LOCKED_LANE = 0
SETTLE_CYCLES = 4
TOTAL_FIELD_BITS = NUM_SUBSYSTEMS * len(SS_RESET_CTRL_FIELDS)


class smu_smc_ss_reset_ctrl_sweep_seq:
    """The reset-unit subsystem registers against the ``ss_reset_ctrl_o`` lanes."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.samples = 0
        self.rose: set[tuple[str, int]] = set()
        self.fell: set[tuple[str, int]] = set()
        self.last: dict[str, int] = {}

    def _sample(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, addr: int, what: str) -> int:
        """One 32-bit CSR read, taken from the lane its address selects."""
        status, rdata = await jtag2axi_single_read(
            self.jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        """One 32-bit CSR write, strobed onto the lane its address selects."""
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag,
            addr,
            beat,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    def _observe(self, entry: SsResetCtrlField) -> int:
        """Sample one field's boundary word and record the edges it took."""
        word = self._sample(entry.pin)
        self.samples += 1
        previous = self.last.get(entry.field)
        if previous is not None:
            for bit in range(NUM_SUBSYSTEMS):
                was = (previous >> bit) & 1
                now = (word >> bit) & 1
                if was == now:
                    continue
                edges = self.rose if now else self.fell
                edges.add((entry.field, bit))
        self.last[entry.field] = word
        return word

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()

        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._sample("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._reset_values()
        await self._lane_sweep()
        await self._cold_reset_lock()
        self._edge_census()

    # ------------------------------------------------------------------
    # S1: the reset state of every field, at the register and at the port.
    # ------------------------------------------------------------------
    async def _reset_values(self) -> None:
        lock = await self._rd32(SS_COLD_RESET_LOCK, "SS_COLD_RESET_LOCK")
        self.sb.expect_eq(
            "SS_COLD_RESET_LOCK open at its RDL reset value, so every cold-reset lane is writable",
            lock & SS_COLD_RESET_LOCK_BM,
            SS_COLD_RESET_LOCK_RESET,
            evidence="CHK-SMU-SSRST-RESET",
        )
        for entry in SS_RESET_CTRL_FIELDS:
            readback = await self._rd32(entry.addr, entry.field)
            self.sb.expect_eq(
                f"the register owning {entry.field} holds its RDL reset value 0x{entry.reset:08x}",
                readback & entry.mask,
                entry.reset,
                evidence="CHK-SMU-SSRST-RESET",
            )
            self.sb.expect_eq(
                f"ss_reset_ctrl_o[31:0].{entry.field} presents that reset value on all 32 lanes",
                self._observe(entry),
                entry.reset,
                evidence="CHK-SMU-SSRST-RESET",
            )

    # ------------------------------------------------------------------
    # S2: each register's lanes on the matching field of every element.
    # ------------------------------------------------------------------
    async def _lane_sweep(self) -> None:
        dut = self.dut
        for entry in SS_RESET_CTRL_FIELDS:
            for pattern in (*LANE_CODE_PATTERNS, entry.reset):
                written = pattern & entry.mask
                await self._wr32(entry.addr, written, entry.field)
                await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
                readback = await self._rd32(entry.addr, entry.field)
                self.sb.expect_eq(
                    f"the register owning {entry.field} holds 0x{written:08x}",
                    readback & entry.mask,
                    written,
                    evidence="CHK-SMU-SSRST-LANE",
                )
                self.sb.expect_eq(
                    f"ss_reset_ctrl_o[i].{entry.field} carries register bit i of 0x{written:08x}",
                    self._observe(entry),
                    readback & entry.mask,
                    evidence="CHK-SMU-SSRST-LANE",
                )

    # ------------------------------------------------------------------
    # S3: the cold-reset lock. Runs after the sweep -- a lock bit is woset and
    # holds for the rest of the simulation.
    # ------------------------------------------------------------------
    async def _cold_reset_lock(self) -> None:
        dut = self.dut
        entry = SS_RESET_CTRL_BY_FIELD["cold_reset_n"]
        locked = 1 << LOCKED_LANE
        open_lanes = entry.mask & ~locked

        await self._wr32(SS_COLD_RESET_LOCK, locked, "SS_COLD_RESET_LOCK")
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        lock = await self._rd32(SS_COLD_RESET_LOCK, "SS_COLD_RESET_LOCK")
        self.sb.expect_eq(
            f"SS_COLD_RESET_LOCK bit {LOCKED_LANE} sets and no other lane locks with it",
            lock & SS_COLD_RESET_LOCK_BM,
            locked,
            evidence="CHK-SMU-SSRST-LOCK",
        )
        await self._wr32(SS_COLD_RESET_LOCK, 0, "SS_COLD_RESET_LOCK")
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        lock = await self._rd32(SS_COLD_RESET_LOCK, "SS_COLD_RESET_LOCK")
        self.sb.expect_eq(
            "a zero write leaves SS_COLD_RESET_LOCK set, as its woset field cannot be cleared",
            lock & SS_COLD_RESET_LOCK_BM,
            locked,
            evidence="CHK-SMU-SSRST-LOCK",
        )

        await self._wr32(entry.addr, entry.mask, "SS_COLD_RESET_N")
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        readback = await self._rd32(entry.addr, "SS_COLD_RESET_N")
        self.sb.expect_eq(
            f"an all-ones write reaches every unlocked cold-reset lane and not lane {LOCKED_LANE}",
            readback & entry.mask,
            open_lanes,
            evidence="CHK-SMU-SSRST-LOCK",
        )
        self.sb.expect_eq(
            f"ss_reset_ctrl_o[{LOCKED_LANE}].cold_reset_n holds while the other lanes follow",
            self._observe(entry),
            open_lanes,
            evidence="CHK-SMU-SSRST-LOCK",
        )

        await self._wr32(entry.addr, entry.reset, "SS_COLD_RESET_N")
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        readback = await self._rd32(entry.addr, "SS_COLD_RESET_N")
        self.sb.expect_eq(
            f"the unlocked lanes return to the RDL reset value 0x{entry.reset:08x}",
            readback & entry.mask,
            entry.reset,
            evidence="CHK-SMU-SSRST-LOCK",
        )
        self.sb.expect_eq(
            "ss_reset_ctrl_o carries that cold-reset word back to the boundary",
            self._observe(entry),
            entry.reset,
            evidence="CHK-SMU-SSRST-LOCK",
        )

    # ------------------------------------------------------------------
    # S4: the edge census over everything the sweep observed.
    # ------------------------------------------------------------------
    def _edge_census(self) -> None:
        # One sample per register state the sweep left behind: the reset read,
        # the ten patterns and the restore on each field, and the two
        # cold-reset states of the lock leg.
        expected_samples = len(SS_RESET_CTRL_FIELDS) * (2 + len(LANE_CODE_PATTERNS)) + 2
        self.sb.expect_eq(
            f"the sweep sampled ss_reset_ctrl_o {expected_samples} times, once per register state",
            self.samples,
            expected_samples,
            evidence="CHK-SMU-SSRST-TOGGLE",
        )
        self.log.info(
            "ss_reset_ctrl_o edges: %d bits rose and %d fell of %d field bits",
            len(self.rose),
            len(self.fell),
            TOTAL_FIELD_BITS,
        )
        missing = [
            (entry.field, bit)
            for entry in SS_RESET_CTRL_FIELDS
            for bit in range(NUM_SUBSYSTEMS)
            if (entry.field, bit) not in self.rose or (entry.field, bit) not in self.fell
        ]
        self.sb.expect_eq(
            f"all {TOTAL_FIELD_BITS} ss_reset_ctrl_o field bits were observed both rising "
            "and falling",
            missing,
            [],
            evidence="CHK-SMU-SSRST-TOGGLE",
        )

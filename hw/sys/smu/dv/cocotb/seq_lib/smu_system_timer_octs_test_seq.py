# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS-TIMER-OCTS: primary strap + free-run COUNT via product pin.

S1: SMC_ATTRIBUTES.chiplet_is_primary vs tb_top hardwire.
S2: PRESET + TIMER_START → STATUS.RUNNING; tb_timer_count advances.
S3: Larger PRESET + START; pin reloads to the new PRESET then advances.

COUNT CSR via J2A hangs under Verilator after free-run starts; product pin
``tb_timer_count`` (``timer_count_o``) is the authoritative observe path.

32-bit CSRs at addr[2]=1 use the upper 64b J2A lane (wstrb=0xF0), matching
``wdt_unlock``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    cpu_ctrl_bm,
    smc_addr,
    system_timer_octs_bm,
)
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)

ADDR_ATTRS = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
ATTR_PRIMARY_BM = cpu_ctrl_bm("CPU_CTRL__SMC_ATTRIBUTES__CHIPLET_IS_PRIMARY_bm")

ADDR_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
ADDR_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
ADDR_PRESET_LO = smc_addr(
    "SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR"
)
ADDR_PRESET_HI = smc_addr(
    "SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR"
)
STATUS_RUNNING = system_timer_octs_bm("SYSTEM_TIMER_OCTS__STATUS__RUNNING_bm")

PRESET = 0x1000
STATUS_POLL_MAX = 4096
PIN_POLL_MAX = 8192
PIN_POLL_STEP = 8
POLL_STEP = 32
# Cycles of STATUS/J2A overhead after START before pin sample.
RELOAD_PIN_SLACK = 4096


class smu_system_timer_octs_test_seq:
    """Prove OCTS primary free-run via STATUS + tb_timer_count."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.pin_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    @staticmethod
    def _j2a_word32_lane(addr: int, data: int = 0) -> tuple[int, int, int]:
        """Map a 32b CSR onto the 64b J2A data/wstrb lane (see wdt_unlock)."""
        word = int(data) & 0xFFFFFFFF
        if addr & 0x4:
            return addr, word << 32, 0xF0
        return addr, word, 0x0F

    async def _j2a_rd32(self, jtag, addr: int, label: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD fail {label} @0x{addr:x} status={st}")
        raw = int(rdata)
        if addr & 0x4:
            return (raw >> 32) & 0xFFFFFFFF
        return raw & 0xFFFFFFFF

    async def _j2a_wr32(self, jtag, addr: int, data: int, label: str) -> None:
        _, packed, wstrb = self._j2a_word32_lane(addr, data)
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            packed,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR fail {label} @0x{addr:x} status={st}")

    def _sample_pin_count(self) -> int | None:
        pin = getattr(self.dut, "tb_timer_count", None)
        if pin is None:
            return None
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on tb_timer_count: {val}")
        return int(val) & ((1 << 64) - 1)

    async def _poll_status_running(self, jtag, label: str) -> int:
        last = 0
        for _ in range(STATUS_POLL_MAX // POLL_STEP):
            last = await self._j2a_rd32(jtag, ADDR_STATUS, "STATUS")
            if last & STATUS_RUNNING:
                return last
            await ClockCycles(self.dut.clk_smu_i, POLL_STEP)
        raise AssertionError(
            f"TIMEOUT {label}: STATUS not RUNNING after "
            f"{STATUS_POLL_MAX} cycles (last=0x{last:08x})"
        )

    async def _poll_pin_above(self, prior: int, label: str) -> int:
        last = prior
        for i in range(PIN_POLL_MAX // PIN_POLL_STEP):
            await ClockCycles(self.dut.clk_smu_i, PIN_POLL_STEP)
            last = self._sample_pin_count()
            if last is None:
                raise AssertionError("tb_timer_count unobservable")
            if last > prior:
                return last
            if i > 0 and (i % 64) == 0:
                self._log(
                    f"{label}: pin still {last} (prior={prior}) "
                    f"after {i * PIN_POLL_STEP} cycles"
                )
        raise AssertionError(
            f"TIMEOUT {label}: tb_timer_count did not exceed {prior} "
            f"(last={last}) after {PIN_POLL_MAX} cycles"
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-OCTS-J2A-READY", idcode, 0x1)

        # S1: primary strap (TB hardwire) ↔ SMC_ATTRIBUTES
        attrs = await self._j2a_rd32(jtag, ADDR_ATTRS, "SMC_ATTRIBUTES")
        is_primary = attrs & ATTR_PRIMARY_BM
        if is_primary != ATTR_PRIMARY_BM:
            raise AssertionError(
                f"SMC_ATTRIBUTES.chiplet_is_primary want "
                f"0x{ATTR_PRIMARY_BM:x} got 0x{is_primary:x} "
                f"(attrs=0x{attrs:08x}); OSS tb_top ties chiplet_is_primary_i=1"
            )
        self.s1_ok = True
        self._log(
            "CHK-OCTS-PRIMARY-STRAP: csr=1 tb_tie=chiplet_is_primary_i "
            f"attrs=0x{attrs:08x}"
        )
        sb.expect_eq("CHK-OCTS-PRIMARY-STRAP", is_primary, ATTR_PRIMARY_BM)

        # S2: preset + start; prove free-run via product pin (not J2A COUNT).
        await self._j2a_wr32(jtag, ADDR_PRESET_LO, PRESET, "PRESET_LO")
        await self._j2a_wr32(jtag, ADDR_PRESET_HI, 0, "PRESET_HI")
        preset_rb = await self._j2a_rd32(jtag, ADDR_PRESET_LO, "PRESET_LO_RB")
        if preset_rb != PRESET:
            raise AssertionError(
                f"PRESET_LO readback 0x{preset_rb:x} want 0x{PRESET:x}"
            )
        await self._j2a_wr32(jtag, ADDR_START, 1, "TIMER_START")
        status = await self._poll_status_running(jtag, "after TIMER_START")
        self._log(f"OCTS STATUS RUNNING (0x{status:08x})")

        pin0 = self._sample_pin_count()
        if pin0 is None:
            raise AssertionError("tb_timer_count unobservable on OSS tb_top")
        if pin0 < PRESET:
            raise AssertionError(
                f"after START pin0={pin0} expected >= PRESET 0x{PRESET:x}"
            )
        self._log(f"OCTS pin0={pin0} (after RUNNING, preset_rb=0x{preset_rb:x})")
        pin1 = await self._poll_pin_above(pin0, "primary free-run")
        if pin1 <= pin0:
            raise AssertionError(f"pin did not advance {pin0} -> {pin1}")
        self.s2_ok = True
        self.pin_ok = True
        self._log(f"CHK-OCTS-COUNT-MONOTONIC: pin {pin0} -> {pin1}")
        sb.expect_true("CHK-OCTS-COUNT-MONOTONIC", pin1 > pin0)
        self._log(
            "CHK-OCTS-CSR-COUNT: DEFERRED-NOTE "
            "(J2A COUNT hangs under Verilator; pin is authoritative)"
        )

        # S3: larger PRESET + START must reload count (not only keep free-run).
        reload_preset = PRESET * 2
        await self._j2a_wr32(jtag, ADDR_PRESET_LO, reload_preset, "PRESET_LO_RELOAD")
        await self._j2a_wr32(jtag, ADDR_PRESET_HI, 0, "PRESET_HI_RELOAD")
        reload_rb = await self._j2a_rd32(jtag, ADDR_PRESET_LO, "PRESET_LO_RELOAD_RB")
        if reload_rb != reload_preset:
            raise AssertionError(
                f"PRESET_LO reload readback 0x{reload_rb:x} "
                f"want 0x{reload_preset:x}"
            )
        await self._j2a_wr32(jtag, ADDR_START, 1, "TIMER_START_RELOAD")
        await self._poll_status_running(jtag, "after preset reload TIMER_START")
        pin2 = self._sample_pin_count()
        if pin2 is None:
            raise AssertionError("tb_timer_count unobservable after reload")
        # Exact reload effect: count must sit near the new PRESET, not merely
        # continue free-run from the prior trajectory.
        if pin2 < reload_preset or pin2 > reload_preset + RELOAD_PIN_SLACK:
            raise AssertionError(
                f"after reload START pin={pin2} not in "
                f"[{reload_preset}, {reload_preset + RELOAD_PIN_SLACK}] "
                f"(preset_rb=0x{reload_rb:x})"
            )
        pin3 = await self._poll_pin_above(pin2, "after preset reload")
        if pin3 <= pin2:
            raise AssertionError(f"reload pin did not advance {pin2} -> {pin3}")
        self.s3_ok = True
        self._log(
            f"CHK-OCTS-PRESET-RELOAD: pin {pin2} -> {pin3} "
            f"(preset_rb=0x{reload_rb:x} window="
            f"[{reload_preset},{reload_preset + RELOAD_PIN_SLACK}])"
        )
        sb.expect_true(
            "CHK-OCTS-PRESET-RELOAD",
            reload_preset <= pin2 <= reload_preset + RELOAD_PIN_SLACK,
        )
        sb.expect_true("CHK-OCTS-PRESET-RELOAD-ADVANCE", pin3 > pin2)

        self._log(
            "PASS SYS-TIMER-OCTS "
            f"s1={self.s1_ok} s2={self.s2_ok} s3={self.s3_ok} "
            f"pin={self.pin_ok}"
        )

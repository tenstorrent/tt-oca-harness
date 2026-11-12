# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM STATUS_RPT eFuse policy for the SEP-to-SMC status ring."""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ValueChange
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_smc_mem import (
    SMC_SCRATCH9_ADDR,
    SMC_SCRATCH11_ADDR,
    SMC_SRAM_BASE,
    SMC_STRAPS_LO_ADDR,
)
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_STATUS_RPT_DISABLE = 1 << 21
_STATUS_BUFFER_READY = 1 << 2

_RING_OFFSET = 0x8000
_RING_ADDR = SMC_SRAM_BASE + _RING_OFFSET
_RING_ENTRIES = 16
_RING_HEADER_WORDS = 3
_RING_SENTINELS = tuple(0xA5A5_0000 | i for i in range(_RING_ENTRIES))

_STATUS_REPORTING_DISABLED = 0x8001_0076
_STATUS_REPORTING_ENABLED = 0x8001_0077
_STATUS_PLL_CLK_INIT = 0x0101_006F
_MAX_POLICY_CYCLES = 4_000_000
_POLL_CYCLES = 100


@dataclass(frozen=True)
class _Case:
    fuse: int
    strap_disabled: bool
    ring_enabled: bool


_CASES = {
    "follow-enabled": _Case(fuse=0, strap_disabled=False, ring_enabled=True),
    "follow-disabled": _Case(fuse=0, strap_disabled=True, ring_enabled=False),
    "force-enabled": _Case(fuse=1, strap_disabled=True, ring_enabled=True),
    "force-disabled-10": _Case(fuse=2, strap_disabled=False, ring_enabled=False),
    "force-disabled-11": _Case(fuse=3, strap_disabled=False, ring_enabled=False),
}


@pyuvm.test()
class sep_status_reporting_policy_test(sep_base_test):
    """Grade the sensed eFuse/strap decision through ring and scratch behavior."""

    build_env = False

    def _select_case(self) -> tuple[str, _Case]:
        name = cocotb.plusargs.get("status_rpt_case")
        assert name in _CASES, f"+status_rpt_case={name!r}; expected one of {sorted(_CASES)}"
        return str(name), _CASES[str(name)]

    @staticmethod
    def _ring_words(smc_mem) -> tuple[int, ...]:
        return tuple(
            smc_mem.read32(_RING_ADDR + 4 * i) for i in range(_RING_HEADER_WORDS + _RING_ENTRIES)
        )

    async def _record_statuses(self, statuses: list[int]) -> None:
        dut = cocotb.top
        last = None
        while True:
            status = (
                self.rd(
                    dut.scratch_cold_probe_o,
                    mask=0xFFFF_FFFF << 32,
                    allow_unknown=True,
                )
                >> 32
            )
            if status != last:
                last = status
                statuses.append(status)
            await ValueChange(dut.scratch_cold_probe_o)

    async def run_scenario(self) -> None:
        name, case = self._select_case()
        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "SMC responder not bound (rom_boot target only)"

        straps_lo = smc_mem.read32(SMC_STRAPS_LO_ADDR)
        observed_disabled = bool(straps_lo & _STATUS_RPT_DISABLE)
        assert observed_disabled == case.strap_disabled, (
            f"{name}: STRAPS_LO[21]={int(observed_disabled)}, expected {int(case.strap_disabled)}"
        )

        efuse = SepEfuseImage()
        efuse.set_lc_state(LC_TEST_DEV)
        efuse.set_int("STATUS_RPT", case.fuse)
        self.write_efuse_image(efuse)

        smc_mem.write32(_RING_ADDR, 0)
        smc_mem.write32(_RING_ADDR + 4, 0)
        smc_mem.write32(_RING_ADDR + 8, _RING_ENTRIES)
        for i, sentinel in enumerate(_RING_SENTINELS):
            smc_mem.write32(_RING_ADDR + 12 + 4 * i, sentinel)
        smc_mem.write32(SMC_SCRATCH11_ADDR, _RING_OFFSET)

        if not case.ring_enabled:
            status_to_sep = smc_mem.read32(SMC_SCRATCH9_ADDR)
            smc_mem.write32(SMC_SCRATCH9_ADDR, status_to_sep & ~_STATUS_BUFFER_READY)

        ring_before = self._ring_words(smc_mem)
        statuses: list[int] = []
        expected_marker = (
            _STATUS_REPORTING_ENABLED if case.ring_enabled else _STATUS_REPORTING_DISABLED
        )
        rejected_marker = (
            _STATUS_REPORTING_DISABLED if case.ring_enabled else _STATUS_REPORTING_ENABLED
        )
        watcher = cocotb.start_soon(self._record_statuses(statuses))
        try:
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            for _ in range(0, _MAX_POLICY_CYCLES, _POLL_CYCLES):
                if rejected_marker in statuses:
                    raise AssertionError(
                        f"{name}: observed rejected policy marker 0x{rejected_marker:08x}; "
                        f"expected 0x{expected_marker:08x}"
                    )
                if case.ring_enabled:
                    head = smc_mem.read32(_RING_ADDR)
                    entries = tuple(
                        smc_mem.read32(_RING_ADDR + 12 + 4 * i) for i in range(_RING_ENTRIES)
                    )
                    if head != 0 and _STATUS_PLL_CLK_INIT in entries:
                        break
                elif _STATUS_PLL_CLK_INIT in statuses:
                    break
                await ClockCycles(cocotb.top.clk_i, _POLL_CYCLES)
            else:
                raise AssertionError(
                    f"{name}: policy evidence did not appear within {_MAX_POLICY_CYCLES} cycles; "
                    f"scratch={[hex(v) for v in statuses]}, "
                    f"ring={[hex(v) for v in self._ring_words(smc_mem)]}"
                )
        finally:
            watcher.cancel()

        assert expected_marker in statuses, (
            f"{name}: cold_scratch[1] never held 0x{expected_marker:08x}; "
            f"observed {[hex(v) for v in statuses]}"
        )
        assert _STATUS_PLL_CLK_INIT in statuses, (
            f"{name}: cold_scratch[1] never advanced to PLL_CLK_INIT; "
            f"observed {[hex(v) for v in statuses]}"
        )
        assert statuses.index(expected_marker) < statuses.index(_STATUS_PLL_CLK_INIT), (
            f"{name}: reporting marker did not precede PLL_CLK_INIT: {[hex(v) for v in statuses]}"
        )

        ring_after = self._ring_words(smc_mem)
        if case.ring_enabled:
            head = ring_after[0]
            entries = ring_after[_RING_HEADER_WORDS:]
            assert head != 0, f"{name}: ring head did not advance"
            assert _STATUS_PLL_CLK_INIT in entries, (
                f"{name}: ring lacks PLL_CLK_INIT; entries={[hex(v) for v in entries]}"
            )
        else:
            assert ring_after == ring_before, (
                f"{name}: disabled policy modified the ring: "
                f"before={[hex(v) for v in ring_before]}, "
                f"after={[hex(v) for v in ring_after]}"
            )
            assert not smc_mem.read32(SMC_SCRATCH9_ADDR) & _STATUS_BUFFER_READY, (
                f"{name}: BUFFER_READY unexpectedly became set"
            )

        self.logger.info(
            "CHK-STATUS-RPT-POLICY PASS: %s fuse=%d strap_disabled=%d ring_enabled=%d",
            name,
            case.fuse,
            case.strap_disabled,
            case.ring_enabled,
        )

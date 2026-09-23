# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM MEM_REPAIR / MBIST boot gate, pass arm (PyUVM).

Injects exactly mem_repair_success, mbist_done and mbist_pass (0x112); the pass arm
emits nothing, so the test requires a completed boot and no failure-arm output.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge

from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Must match +sep_dft_status in the testlist entry.
_DFT_STATUS_PASS = 0x0000_0112
_MEM_REPAIR_DONE_BIT = 0
_MEM_REPAIR_SUCCESS_BIT = 1
_MBIST_DONE_BIT = 4
_MBIST_PASS_BIT = 8
_MEM_REPAIR_ABORT_BIT = 2
_MBIST_ABORT_BIT = 12

# Failure-arm cold_scratch[1] words; keep in step with sep_firmware_mbist_fail_test.
_STATUS_MBIST_WARN = 0x0801_0000 | 0x219          # WARN + SEP_MSG_MBIST_FAIL
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | 0xD001   # ERROR + ROM_ERR_DFT_GATE_BLOCKED
# Written by vector.S just before the gate reads DFX_CTRL_STATUS_SMU.
_STATUS_PRESTART_DONE = 0x8001_0056

# Only the C runtime prints these, so they show the gate let the boot through.
_POST_GATE_MARKERS = ("COLD", "CHIP_ID=")


@pyuvm.test()
class sep_firmware_mbist_pass_test(sep_rom_ot_dma_boot_test):
    """mem_repair_success, mbist_done and mbist_pass set: the ROM boots through."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + _POST_GATE_MARKERS

    # Class defaults: the base may call log_transport() before the monitor starts.
    _status_seq: list[int] = []
    _s10_seq: list[int] = []
    _dft_seq: list[int] = []

    async def _gate_monitor(self) -> None:
        # Sample every cycle: a later report_status() overwrites cold_scratch[1].
        dut = cocotb.top
        last_status = None
        last_s10 = None
        last_dft = None
        try:
            while True:
                await RisingEdge(dut.clk_i)
                status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
                if status != last_status:
                    last_status = status
                    self._status_seq.append(status)
                s10 = self.rd(dut.smc_scratch10_probe_o) & 0xFFFF_FFFF
                if s10 != last_s10:
                    last_s10 = s10
                    self._s10_seq.append(s10)
                dft = self.rd(dut.smc_dft_status_probe_o) & 0xFFFF_FFFF
                if dft != last_dft:
                    last_dft = dft
                    self._dft_seq.append(dft)
        except Exception:  # noqa: BLE001 - end of sim tears down the clock
            return

    def log_transport(self, flash) -> None:
        self.logger.info("cold_scratch[1] sequence: %s",
                         [hex(v) for v in self._status_seq])
        self.logger.info("SMC scratch[10] sequence: %s",
                         [hex(v) for v in self._s10_seq])
        self.logger.info("DFX_CTRL_STATUS_SMU sequence: %s",
                         [hex(v) for v in self._dft_seq])

    async def run_scenario(self) -> None:
        injected = cocotb.plusargs.get("sep_dft_status")
        assert injected is not None, (
            "+sep_dft_status is not set: the testbench default is 0x113, which "
            "also passes both arms, so this run would prove only that the default "
            "boots -- not that the gate keys on bits 1, 4 and 8 specifically"
        )
        assert int(str(injected), 16) == _DFT_STATUS_PASS, (
            f"+sep_dft_status={injected} does not match the word this test checks "
            f"for (0x{_DFT_STATUS_PASS:08x})"
        )
        for _name, _bit in (
            ("mem_repair_success", _MEM_REPAIR_SUCCESS_BIT),
            ("mbist_done", _MBIST_DONE_BIT),
            ("mbist_pass", _MBIST_PASS_BIT),
        ):
            assert (_DFT_STATUS_PASS >> _bit) & 1, (
                f"injected DFT status 0x{_DFT_STATUS_PASS:08x} has {_name} "
                f"(bit {_bit}) CLEAR -- the gate requires all three, so this is "
                f"a failure-arm injection"
            )
        _required = (
            (1 << _MEM_REPAIR_SUCCESS_BIT)
            | (1 << _MBIST_DONE_BIT)
            | (1 << _MBIST_PASS_BIT)
        )
        assert _DFT_STATUS_PASS == _required, (
            f"injected DFT status must be exactly the three required bits and "
            f"nothing else; 0x{_DFT_STATUS_PASS:08x} != 0x{_required:08x}. Leaving "
            f"mem_repair_done (bit {_MEM_REPAIR_DONE_BIT}), mem_repair_abort "
            f"(bit {_MEM_REPAIR_ABORT_BIT}) and mbist_abort (bit "
            f"{_MBIST_ABORT_BIT}) clear is what makes this discriminating: a gate "
            f"keyed on any of them, or on a whole-word comparison, fails here"
        )
        self.logger.info(
            "CHK-DFT-PASS-STIMULUS: DFX_CTRL_STATUS_SMU = 0x%08x "
            "(mem_repair_success + mbist_done + mbist_pass; repair_done=%d "
            "repair_abort=%d mbist_abort=%d -- all deliberately clear)",
            _DFT_STATUS_PASS,
            (_DFT_STATUS_PASS >> _MEM_REPAIR_DONE_BIT) & 1,
            (_DFT_STATUS_PASS >> _MEM_REPAIR_ABORT_BIT) & 1,
            (_DFT_STATUS_PASS >> _MBIST_ABORT_BIT) & 1,
        )

        self._status_seq = []
        self._s10_seq = []
        self._dft_seq = []
        cocotb.start_soon(self._gate_monitor())
        await super().run_scenario()

        status_hex = [hex(v) for v in self._status_seq]
        s10_hex = [hex(v) for v in self._s10_seq]
        dft_hex = [hex(v) for v in self._dft_seq]

        # The probe flop reads 0 before its first sample, so 0 is also legal.
        assert self._dft_seq, (
            "DFX_CTRL_STATUS_SMU was never sampled; the monitor did not run, so "
            "the injection is unverified"
        )
        assert self._dft_seq[-1] == _DFT_STATUS_PASS, (
            f"DFX_CTRL_STATUS_SMU settled at 0x{self._dft_seq[-1]:08x}, expected "
            f"0x{_DFT_STATUS_PASS:08x}: the injection did not reach the register "
            f"the MEM_REPAIR gate reads, so this run does not test the pass arm "
            f"this testcase claims. Observed {dft_hex}"
        )
        assert set(self._dft_seq) <= {0, _DFT_STATUS_PASS}, (
            f"DFX_CTRL_STATUS_SMU held {dft_hex}; the only values allowed are the "
            f"probe's power-up 0 and the injected 0x{_DFT_STATUS_PASS:08x}. Any "
            f"other value -- in particular the testbench default 0x00000113 -- "
            f"means the gate read something this testcase did not choose"
        )
        self.logger.info(
            "CHK-DFT-INJECTED: DFX_CTRL_STATUS_SMU = 0x%08x at the SMC, for the "
            "whole run", _DFT_STATUS_PASS,
        )

        assert _STATUS_PRESTART_DONE in self._status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_PRESTART_DONE:08x} "
            f"(BOOTROM_PRESTART_DONE, written immediately before the gate): the "
            f"run cannot be said to have reached the MEM_REPAIR gate. "
            f"Observed {status_hex}"
        )
        self.logger.info(
            "CHK-DFT-REACHED: cold_scratch[1] = 0x%08x, so execution arrived at "
            "the gate", _STATUS_PRESTART_DONE,
        )

        assert _STATUS_MBIST_WARN not in self._status_seq, (
            f"cold_scratch[1] held the MBIST WARN word "
            f"0x{_STATUS_MBIST_WARN:08x}: the gate classified a passing "
            f"mem_repair_success as a failure. Observed {status_hex}"
        )
        assert _STATUS_DFT_GATE_BLOCKED not in self._status_seq, (
            f"cold_scratch[1] held ROM_ERR_DFT_GATE_BLOCKED "
            f"0x{_STATUS_DFT_GATE_BLOCKED:08x}: the gate blocked a boot it should "
            f"have allowed. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-DFT-NO-WARN: neither 0x%08x nor 0x%08x reached cold_scratch[1]",
            _STATUS_MBIST_WARN, _STATUS_DFT_GATE_BLOCKED,
        )

        assert set(self._s10_seq) <= {0}, (
            f"SMC scratch[10] was written ({s10_hex}); only the MEM_REPAIR failure "
            f"arm publishes there, so the gate took the failure branch"
        )
        self.logger.info("CHK-DFT-NO-PUBLISH: SMC scratch[10] stayed 0")

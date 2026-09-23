# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""MEM_REPAIR reports failure but the bypass fuse is blown, so BL0 continues.

The ROM must publish the raw DFT status, write the WARN word and boot on. The
injected word fails the memory-repair arm.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge

from env.sep_efuse_image import SepEfuseImage, LC_TEST_DEV
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Must match +sep_dft_status in the testlist.
_DFT_STATUS_FAIL = 0xFFFF_FFFD
_MEM_REPAIR_DONE_BIT = 0
_MEM_REPAIR_SUCCESS_BIT = 1
_MBIST_PASS_BIT = 8

_STATUS_RPT_SKIP_MEM_CHECK_BIT = 2

_STATUS_MBIST_WARN = 0x0801_0000 | 0x219          # WARN + SEP_MSG_MBIST_FAIL
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | 0xD001   # ERROR + ROM_ERR_DFT_GATE_BLOCKED
_STATUS_PRESTART_DONE = 0x8001_0056

_POST_GATE_MARKERS = ("COLD", "CHIP_ID=")


@pyuvm.test()
class sep_mbist_fail_continue_test(sep_rom_ot_dma_boot_test):
    """MEM_REPAIR failed, STATUS_RPT bit 2 blown: warn, publish, and boot on."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + _POST_GATE_MARKERS

    # Defaults for log_transport(), which can run before the monitor starts.
    _status_seq: list[int] = []
    _s10_seq: list[int] = []
    _dft_seq: list[int] = []

    def build_efuse_image(self):
        image = SepEfuseImage()
        image.set_lc_state(LC_TEST_DEV)
        image.set_int("STATUS_RPT", 1 << _STATUS_RPT_SKIP_MEM_CHECK_BIT)
        bypass = (image.field_int("STATUS_RPT") >> _STATUS_RPT_SKIP_MEM_CHECK_BIT) & 1
        assert bypass == 1, (
            f"STATUS_RPT bit {_STATUS_RPT_SKIP_MEM_CHECK_BIT} did not take in the "
            f"OTP image (STATUS_RPT=0x{image.field_int('STATUS_RPT'):08x}); without "
            f"the bypass this run would halt on the gate and the test would be "
            f"reporting on the failure arm instead"
        )
        self.logger.info(
            "CHK-BYPASS-FUSE: OTP STATUS_RPT = 0x%08x, bit %d (SKIP_MEM_CHECK) "
            "blown", image.field_int("STATUS_RPT"),
            _STATUS_RPT_SKIP_MEM_CHECK_BIT,
        )
        return image

    async def _gate_monitor(self) -> None:
        # Sample every cycle: each later report_status() overwrites the WARN word.
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
            "+sep_dft_status is not set: the testbench default 0x113 passes the "
            "gate, so this run would not reach the failure branch the bypass is "
            "supposed to rescue"
        )
        assert int(str(injected), 16) == _DFT_STATUS_FAIL, (
            f"+sep_dft_status={injected} does not match the word this test checks "
            f"for (0x{_DFT_STATUS_FAIL:08x})"
        )
        assert not (_DFT_STATUS_FAIL >> _MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{_DFT_STATUS_FAIL:08x} has mem_repair_success "
            f"(bit {_MEM_REPAIR_SUCCESS_BIT}) SET -- that is the pass arm, and the "
            f"bypass would never be consulted"
        )
        assert (_DFT_STATUS_FAIL >> _MBIST_PASS_BIT) & 1, (
            f"injected DFT status 0x{_DFT_STATUS_FAIL:08x} has mbist_pass (bit "
            f"{_MBIST_PASS_BIT}) clear; keeping it SET is what pins the failure to "
            f"the REPAIR arm. With mbist_pass set, arm 2 would have been satisfied "
            f"had execution got there, so a gate that failed for any MBIST reason "
            f"is excluded and the scope claim in the docstring holds"
        )
        self.logger.info(
            "CHK-DFT-FAIL-STIMULUS: DFX_CTRL_STATUS_SMU = 0x%08x "
            "(mem_repair_success=%d, mem_repair_done=%d, mbist_pass=%d)",
            _DFT_STATUS_FAIL,
            (_DFT_STATUS_FAIL >> _MEM_REPAIR_SUCCESS_BIT) & 1,
            (_DFT_STATUS_FAIL >> _MEM_REPAIR_DONE_BIT) & 1,
            (_DFT_STATUS_FAIL >> _MBIST_PASS_BIT) & 1,
        )

        # Rebind per instance so appends do not mutate the shared class-level lists.
        self._status_seq = []
        self._s10_seq = []
        self._dft_seq = []
        cocotb.start_soon(self._gate_monitor())
        await super().run_scenario()

        status_hex = [hex(v) for v in self._status_seq]
        s10_hex = [hex(v) for v in self._s10_seq]
        dft_hex = [hex(v) for v in self._dft_seq]

        # The probe flop reads 0 before its first clocked update, so 0 is allowed below.
        assert self._dft_seq, (
            "DFX_CTRL_STATUS_SMU was never sampled; the monitor did not run, so the "
            "injection is unverified"
        )
        assert self._dft_seq[-1] == _DFT_STATUS_FAIL, (
            f"DFX_CTRL_STATUS_SMU settled at 0x{self._dft_seq[-1]:08x}, expected "
            f"0x{_DFT_STATUS_FAIL:08x}: the injection did not reach the register the "
            f"MEM_REPAIR gate reads. Observed {dft_hex}"
        )
        assert set(self._dft_seq) <= {0, _DFT_STATUS_FAIL}, (
            f"DFX_CTRL_STATUS_SMU held {dft_hex}; the only values allowed are the "
            f"probe's power-up 0 and the injected 0x{_DFT_STATUS_FAIL:08x}. The tb "
            f"default 0x00000113 appearing would mean the gate read a passing word"
        )
        self.logger.info("CHK-DFT-INJECTED: DFX_CTRL_STATUS_SMU = 0x%08x at the SMC",
                         _DFT_STATUS_FAIL)

        assert _STATUS_PRESTART_DONE in self._status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_PRESTART_DONE:08x} "
            f"(BOOTROM_PRESTART_DONE, written immediately before the gate); the run "
            f"cannot be said to have reached the MEM_REPAIR gate. "
            f"Observed {status_hex}"
        )
        self.logger.info("CHK-DFT-REACHED: cold_scratch[1] = 0x%08x",
                         _STATUS_PRESTART_DONE)

        assert _STATUS_MBIST_WARN in self._status_seq, (
            f"cold_scratch[1] never held the WARN word 0x{_STATUS_MBIST_WARN:08x} "
            f"(SEP_MSG_MBIST_FAIL): the gate did not take the failure branch, so "
            f"the bypass was never consulted and this run does not test it. "
            f"Observed {status_hex}"
        )
        self.logger.info(
            "CHK-MBIST-FAIL-TAKEN: cold_scratch[1] held 0x%08x (WARN, transient)",
            _STATUS_MBIST_WARN,
        )

        assert _DFT_STATUS_FAIL in self._s10_seq, (
            f"SMC scratch[10] never held the failing DFT status "
            f"0x{_DFT_STATUS_FAIL:08x}; the ROM did not publish the value it "
            f"gated on. Observed {s10_hex}"
        )
        self.logger.info("CHK-MBIST-PUBLISH: SMC scratch[10] = 0x%08x",
                         _DFT_STATUS_FAIL)

        assert _STATUS_DFT_GATE_BLOCKED not in self._status_seq, (
            f"cold_scratch[1] held ROM_ERR_DFT_GATE_BLOCKED "
            f"0x{_STATUS_DFT_GATE_BLOCKED:08x}: the ROM halted despite the bypass "
            f"fuse being blown. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-BYPASS-TAKEN: 0x%08x never reached cold_scratch[1]; the boot "
            "continued past a failed MEM_REPAIR because STATUS_RPT bit %d was blown",
            _STATUS_DFT_GATE_BLOCKED, _STATUS_RPT_SKIP_MEM_CHECK_BIT,
        )

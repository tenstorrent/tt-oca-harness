# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the MEM_REPAIR / MBIST boot-gate arms that let the boot continue.

The gate is in ``bootrom/prod/src/vector.S``; ``sep_firmware_mbist_fail_test`` lists it above
``_DFT_STATUS_FAIL``. A member names the DFX_CTRL_STATUS_SMU word it injects and the bypass straps
it sets, states its stimulus shape in ``check_stimulus_shape()`` and grades the run in
``check_gate_outcome()``. The OT-SPI boot gives every member a definite end; the gate is upstream
of the transport choice.

The monitor records every change of cold_scratch[1], SMC scratch[10], DFX_CTRL_STATUS_SMU and both
strap words from before CPU release, because the failure arm's observables are transient and an
absence claim is only meaningful against the whole sequence.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_smc_mem import (
    SMC_DFT_STATUS_ADDR,
    SMC_SCRATCH10_ADDR,
    SMC_STRAPS_HI_ADDR,
    SMC_STRAPS_LO_ADDR,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl and
# bootrom/prod/include/sep_smc_interface.h.
MEM_REPAIR_DONE_BIT = 0
MEM_REPAIR_SUCCESS_BIT = 1
MEM_REPAIR_ABORT_BIT = 2
MBIST_DONE_BIT = 4
MBIST_PASS_BIT = 8
MBIST_ABORT_BIT = 12

# The two bypass straps the gate reads (vector.S STRAP_BYPASS_SRAM_REPAIR, STRAP_MBIST_BYPASS_HI).
STRAP_BYPASS_SRAM_REPAIR_LO = 1 << 13
STRAP_MBIST_BYPASS_HI = 1 << 22

# The two words the failure arm writes to cold_scratch[1].
STATUS_MBIST_WARN = 0x0801_0000 | 0x219  # WARN + SEP_MSG_MBIST_FAIL
STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | 0xD001  # ERROR + ROM_ERR_DFT_GATE_BLOCKED
# The last store vector.S makes before it reads DFX_CTRL_STATUS_SMU.
STATUS_PRESTART_DONE = 0x8001_0056

# Printed by rom_main.c, so only a run that left the gate reaches them.
POST_GATE_MARKERS = ("SMC_MEM_CHK", "CHIP_ID=")

_VECTOR_S = Path(__file__).resolve().parents[4] / "bootrom" / "prod" / "src" / "vector.S"


def mbist_done_wait_iters() -> int:
    """The mbist_done wait bound that SEP-ROM-SMC-030 names, as the ROM under test sets it."""
    match = re.search(r"^\.equ\s+MBIST_DONE_WAIT_ITERS,\s*(\d+)", _VECTOR_S.read_text(), re.M)
    assert match, f"MBIST_DONE_WAIT_ITERS is not defined in {_VECTOR_S}"
    return int(match.group(1))


class sep_dft_gate_boot_base(sep_rom_ot_dma_boot_test):
    """Inject a DFX status word and bypass straps, boot, and keep the gate's whole history."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + POST_GATE_MARKERS

    # Member contract. The bypass bits the member does not name must read 0 at the SMC.
    expected_dft_status: int
    required_straps_lo: int = 0
    required_straps_hi: int = 0

    # Read by log_transport(), which the base can call before run_scenario() rebinds them.
    status_seq: list[int] = []
    scratch10_seq: list[int] = []
    dft_seq: list[int] = []
    straps_lo_seq: list[int] = []
    straps_hi_seq: list[int] = []

    def check_stimulus_shape(self) -> None:
        raise NotImplementedError

    def check_gate_outcome(self, console: list[str]) -> None:
        raise NotImplementedError

    def check_gate_stimulus(self) -> None:
        """Reject a launch whose plusargs do not carry this member's injection."""
        injected = cocotb.plusargs.get("sep_dft_status")
        assert injected is not None, (
            "+sep_dft_status is not set: the testbench default 0x113 passes both arms, so this "
            "run would describe an ordinary boot. Add the injection to the testlist entry"
        )
        assert int(str(injected), 16) == self.expected_dft_status, (
            f"+sep_dft_status={injected} does not match the word this test checks for "
            f"(0x{self.expected_dft_status:08x}); align the testlist entry with the test"
        )
        for name, required in (
            ("sep_straps_lo", self.required_straps_lo),
            ("sep_straps_hi", self.required_straps_hi),
        ):
            arg = cocotb.plusargs.get(name)
            if required:
                assert arg is not None and int(str(arg), 16) & required == required, (
                    f"+{name}={arg!r} does not set 0x{required:08x}; the bypass this test "
                    f"grades would not be strapped"
                )
            else:
                assert arg is None, (
                    f"+{name}={arg!r} is set but this test straps nothing in that word; "
                    f"remove it so the gate sees only the intended bypass"
                )

    async def _gate_monitor(self) -> None:
        dut = cocotb.top
        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "SMC responder not bound (rom_boot target only)"
        seqs = (
            (self.scratch10_seq, SMC_SCRATCH10_ADDR),
            (self.dft_seq, SMC_DFT_STATUS_ADDR),
            (self.straps_lo_seq, SMC_STRAPS_LO_ADDR),
            (self.straps_hi_seq, SMC_STRAPS_HI_ADDR),
        )
        try:
            while True:
                await RisingEdge(dut.clk_i)
                status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
                if not self.status_seq or self.status_seq[-1] != status:
                    self.status_seq.append(status)
                for seq, addr in seqs:
                    value = smc_mem.read32(addr)
                    if not seq or seq[-1] != value:
                        seq.append(value)
        except Exception:  # noqa: BLE001 - end of sim tears down the clock
            return

    def log_transport(self, flash) -> None:
        # Called from the base's `finally`, so the evidence is logged even when a check fails.
        self.logger.info("cold_scratch[1] sequence: %s", [hex(v) for v in self.status_seq])
        self.logger.info("SMC scratch[10] sequence: %s", [hex(v) for v in self.scratch10_seq])
        self.logger.info("DFX_CTRL_STATUS_SMU sequence: %s", [hex(v) for v in self.dft_seq])
        self.logger.info("STRAPS_LO sequence: %s", [hex(v) for v in self.straps_lo_seq])
        self.logger.info("STRAPS_HI sequence: %s", [hex(v) for v in self.straps_hi_seq])

    def start_watchers(self, console: list[str]) -> None:
        self._console = console

    async def run_scenario(self) -> None:
        self.check_gate_stimulus()
        self.check_stimulus_shape()
        self.status_seq = []
        self.scratch10_seq = []
        self.dft_seq = []
        self.straps_lo_seq = []
        self.straps_hi_seq = []
        self._console: list[str] = []
        self._gate_mon = cocotb.start_soon(self._gate_monitor())
        # Asserts the SPI path, the post-gate markers and the BL1 PASS verdict.
        await super().run_scenario()
        self.check_gate_outcome(self._console)

    def assert_dft_injected(self, chk: str) -> None:
        """The word at the SMC, not cocotb's copy of the command line, is the injection."""
        dft_hex = [hex(v) for v in self.dft_seq]
        assert self.dft_seq, "DFX_CTRL_STATUS_SMU was never sampled; the monitor did not run"
        assert self.dft_seq[-1] == self.expected_dft_status, (
            f"DFX_CTRL_STATUS_SMU settled at 0x{self.dft_seq[-1]:08x}, expected "
            f"0x{self.expected_dft_status:08x}: the injection did not reach the register the "
            f"gate reads. Observed {dft_hex}"
        )
        assert set(self.dft_seq) <= {0, self.expected_dft_status}, (
            f"DFX_CTRL_STATUS_SMU held {dft_hex}; only 0 and the injected "
            f"0x{self.expected_dft_status:08x} are allowed, so the gate read a word this test "
            f"did not choose"
        )
        self.logger.info(
            "%s: DFX_CTRL_STATUS_SMU = 0x%08x at the SMC, for the whole run",
            chk,
            self.expected_dft_status,
        )

    def assert_straps_captured(self, chk: str, console: list[str]) -> None:
        """Both strap words carry exactly the bypass bits this member names, and the ROM read them."""
        for name, seq, required, bypass in (
            ("STRAPS_LO", self.straps_lo_seq, self.required_straps_lo, STRAP_BYPASS_SRAM_REPAIR_LO),
            ("STRAPS_HI", self.straps_hi_seq, self.required_straps_hi, STRAP_MBIST_BYPASS_HI),
        ):
            seq_hex = [hex(v) for v in seq]
            assert seq, f"{name} was never sampled; the monitor did not run"
            final = seq[-1]
            assert set(seq) <= {0, final}, (
                f"{name} changed during the run ({seq_hex}); the gate could have read a value "
                f"other than the one graded here"
            )
            assert final & bypass == required & bypass, (
                f"{name} = 0x{final:08x} at the SMC: bypass bit 0x{bypass:08x} must be "
                f"{'set' if required & bypass else 'clear'} for this test"
            )
            assert final & required == required, (
                f"{name} = 0x{final:08x} at the SMC lacks the required bits 0x{required:08x}"
            )
            echo = f"{name}=0x{final:08x}"
            assert any(echo in line for line in console), (
                f"ROM never printed {echo}: the C runtime read a different strap word than the "
                f"one the SMC model holds. Console: {console}"
            )
        self.logger.info(
            "%s: STRAPS_LO = 0x%08x and STRAPS_HI = 0x%08x at the SMC and in the ROM echo",
            chk,
            self.straps_lo_seq[-1],
            self.straps_hi_seq[-1],
        )

    def assert_gate_reached(self, chk: str) -> None:
        """vector.S ran up to the instruction before the gate."""
        assert STATUS_PRESTART_DONE in self.status_seq, (
            f"cold_scratch[1] never held 0x{STATUS_PRESTART_DONE:08x} (BOOTROM_PRESTART_DONE, "
            f"written immediately before the gate): the run cannot be said to have reached the "
            f"gate. Observed {[hex(v) for v in self.status_seq]}"
        )
        self.logger.info(
            "%s: cold_scratch[1] = 0x%08x, so execution arrived at the gate",
            chk,
            STATUS_PRESTART_DONE,
        )

    def assert_no_failure_arm(self, warn_chk: str, publish_chk: str) -> None:
        """Neither cold_scratch[1] word nor the SMC scratch[10] publish of the failure arm appeared."""
        assert not self._gate_mon.done(), (
            "the gate monitor stopped before the check, so its record can end before the failure arm"
        )
        status_hex = [hex(v) for v in self.status_seq]
        assert STATUS_MBIST_WARN not in self.status_seq, (
            f"cold_scratch[1] held the MBIST WARN word 0x{STATUS_MBIST_WARN:08x}: the gate took "
            f"the failure arm. Observed {status_hex}"
        )
        assert STATUS_DFT_GATE_BLOCKED not in self.status_seq, (
            f"cold_scratch[1] held ROM_ERR_DFT_GATE_BLOCKED 0x{STATUS_DFT_GATE_BLOCKED:08x}: the "
            f"gate blocked a boot it should have allowed. Observed {status_hex}"
        )
        self.logger.info(
            "%s: neither 0x%08x nor 0x%08x reached cold_scratch[1]",
            warn_chk,
            STATUS_MBIST_WARN,
            STATUS_DFT_GATE_BLOCKED,
        )
        # Written only by the first store under vector.S's dft_gate_failed label.
        assert set(self.scratch10_seq) <= {0}, (
            f"SMC scratch[10] was written ({[hex(v) for v in self.scratch10_seq]}); only the "
            f"gate's failure arm publishes there"
        )
        self.logger.info("%s: SMC scratch[10] stayed 0", publish_chk)


def assert_no_bypass_strapped(test, chk: str) -> None:
    """Neither bypass strap is launched or held at the SMC, so the gate must evaluate both arms."""
    for name in ("sep_straps_lo", "sep_straps_hi"):
        arg = cocotb.plusargs.get(name)
        assert arg is None, (
            f"+{name}={arg!r} is set; a terminal-path test must leave both bypass straps clear"
        )
    smc_mem = test.cfg.smc_mem
    assert smc_mem is not None, "SMC responder not bound (rom_boot target only)"
    lo = smc_mem.read32(SMC_STRAPS_LO_ADDR)
    hi = smc_mem.read32(SMC_STRAPS_HI_ADDR)
    assert not lo & STRAP_BYPASS_SRAM_REPAIR_LO and not hi & STRAP_MBIST_BYPASS_HI, (
        f"STRAPS_LO = 0x{lo:08x}, STRAPS_HI = 0x{hi:08x} at the SMC: a bypass strap is set, so "
        f"the halt is not evidence of the unbypassed arm"
    )
    test.logger.info(
        "%s: STRAPS_LO = 0x%08x and STRAPS_HI = 0x%08x at the SMC, both bypass bits clear",
        chk,
        lo,
        hi,
    )

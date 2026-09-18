# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP008: MEM_REPAIR reports failure but the bypass fuse is blown, so BL0 continues.

The fuse arm of the gate in ``bootrom/prod/src/vector.S``, and the one neither
``sep_firmware_mbist_fail_test`` nor ``sep_firmware_mbist_pass_test`` covers --
both of those say so in their own docstrings. The gate, by label::

    lw   t1, (SMC_DFX_CTRL_STATUS_SMU)      # smc_base + 0xB800 (smc_addr.h)
    # arm 1: memory repair, skipped entirely if BYPASS_SRAM_REPAIR is strapped
    and  t2, straps_lo, STRAP_BYPASS_SRAM_REPAIR
    bnez t2, 1f
    andi t2, t1, DFT_MEM_REPAIR_SUCCESS     # bit 1 clear -> dft_gate_failed
    beqz t2, dft_gate_failed                #   <-- THIS RUN LEAVES HERE
1:  # arm 2: MBIST, skipped if MBIST_BYPASS is strapped; polls mbist_done, then
    #        checks mbist_abort / timeout / mbist_pass -- not reached by this test
    dft_gate_failed:
      sw   t1, (SMC_SCRATCH_MBIST_FAIL)     # publish raw value, scratch 10
      sw   0x08010219, (SEP_COLD_SCRATCH_1) # WARN + SEP_MSG_MBIST_FAIL
      lw   t3, (SEP_EFUSE_STATUS_RPT)       # bypass fuse
      andi t4, t3, STATUS_RPT_SKIP_MEM_CHECK # (1 << 2) blown -> continue
    mem_repair_fail_hang:
      sw   0x0f01d001, (SEP_COLD_SCRATCH_1) # ERROR + ROM_ERR_DFT_GATE_BLOCKED
      wfi, then spin

This testcase drives the failure injection AND blows the bypass, so the run must
take the failure branch, publish the raw status, record the WARN, and then
continue -- reaching the C runtime and completing an ordinary boot.

THE BYPASS FUSE. It is not the ``MBIST_NO_HANG`` fuse the procedure names -- no
such fuse exists anywhere in the tree -- but ``STATUS_RPT`` bit 2, which
``vector.S`` calls ``STATUS_RPT_SKIP_MEM_CHECK``. Bit 2 is inside
``reserved[31:2]`` in ``sep_efuse_map.rdl``, so the ROM's use of it is undeclared
in the register model; the bit is readable and the ROM branches on it.

TWO WORDS, NOT A STRING. The procedure expects "a WARNING: MBIST_FAIL_NO_HANG (or
equivalent) to scratch 1". The gate runs before the C runtime, so ``simputs()``
does not exist yet and no string is emitted; the equivalent is the status WORD
0x08010219 = STATUS_ENCODE(WARN, SEP_MSG_MBIST_FAIL). It is also TRANSIENT --
every later ``report_status()`` overwrites cold_scratch[1] -- so it is sampled
continuously rather than read at the end, which is why a monitor coroutine exists
here at all.

WHICH ARM THIS ACTUALLY EXERCISES, AND IT IS NOT THE MBIST ONE. The gate has two
arms (``vector.S``): memory repair, then MBIST. The injected 0xFFFFFFFD has
``mem_repair_success`` (bit 1) CLEAR, so it fails on the FIRST arm and the MBIST
check is never reached -- even though the same word has ``mbist_pass`` SET.

What this testcase therefore proves is the FUSE POLICY on the shared failure
handler: a failed gate plus ``SKIP_MEM_CHECK`` blown means the boot continues.
That policy is common to both arms, so the result carries over. But this is NOT
coverage of "MBIST failed and the boot continued", which needs
``+sep_dft_status=00000012`` plus the fuse.

The gate reads ``mbist_done`` and ``mbist_pass``.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_smc_mem import SMC_DFT_STATUS_ADDR, SMC_SCRATCH10_ADDR
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Must match +sep_dft_status in the testlist. Identical to the failure arm's
# injection: this testcase differs from sep_firmware_mbist_fail_test in the FUSE,
# not in the stimulus, which is what isolates the bypass as the cause.
_DFT_STATUS_FAIL = 0xFFFF_FFFD
# bootrom/prod/include/sep_smc_interface.h:64-65.
_MEM_REPAIR_DONE_BIT = 0
_MEM_REPAIR_SUCCESS_BIT = 1
# dfx_ctrl_status.rdl. The ROM's second arm reads this bit; it is
# asserted below to show that this run never gets that far, having already left on
# the repair arm.
_MBIST_PASS_BIT = 8

# STATUS_RPT_SKIP_MEM_CHECK in vector.S.
_STATUS_RPT_SKIP_MEM_CHECK_BIT = 2

# cold_scratch[1] words, numerically identical to the two MBIST siblings so the
# three arms state one contract between them.
_STATUS_MBIST_WARN = 0x0801_0000 | 0x219  # WARN + SEP_MSG_MBIST_FAIL
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | 0xD001  # ERROR + ROM_ERR_DFT_GATE_BLOCKED
# vector.S, written immediately BEFORE the gate.
_STATUS_PRESTART_DONE = 0x8001_0056

# C-runtime console markers. The gate stops the ROM before C on the blocked arm,
# so requiring these is how "it continued" is established.
#   SMC_MEM_CHK  rom_main.c:190
#   CHIP_ID=     rom_main.c:562
_POST_GATE_MARKERS = ("SMC_MEM_CHK", "CHIP_ID=")
# The procedure's "boot reaches at least START_MANIFEST_VALIDATION". This ROM
# names that checkpoint MANIFEST_SRC= / MANIFEST_OK, both already required by the
# base class, so the gate-specific addition is the C-runtime pair above.


@pyuvm.test()
class sep_mbist_fail_continue_test(sep_rom_ot_dma_boot_test):
    """MEM_REPAIR failed, STATUS_RPT bit 2 blown: warn, publish, and boot on."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + _POST_GATE_MARKERS

    # Populated by _gate_monitor(); read by log_transport(), which the base calls
    # from a `finally` that can run before the monitor ever starts.
    _status_seq: list[int] = []
    _s10_seq: list[int] = []
    _dft_seq: list[int] = []

    def build_efuse_image(self):
        """TEST_DEV plus the MEM_REPAIR bypass bit.

        Built here rather than taken from a TOML preload because the only field
        that differs from the base's default image is this one bit, and the
        failure-arm sibling establishes that an image built at this point reaches
        the model (the base's own eFuse backdoor check verifies it word by word).
        """
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
            "CHK-BYPASS-FUSE: OTP STATUS_RPT = 0x%08x, bit %d (SKIP_MEM_CHECK) blown",
            image.field_int("STATUS_RPT"),
            _STATUS_RPT_SKIP_MEM_CHECK_BIT,
        )
        return image

    async def _gate_monitor(self) -> None:
        """Record every change of cold_scratch[1], SMC scratch[10] and the DFT word.

        Continuous sampling is required, not stylistic: cold_scratch[1] is
        overwritten by each subsequent report_status(), and on this arm the boot
        CONTINUES, so the WARN word is guaranteed to be gone by the end of the run.
        A single final read could not see it.
        """
        dut = cocotb.top
        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "SMC responder not bound (rom_boot target only)"
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
                s10 = smc_mem.read32(SMC_SCRATCH10_ADDR)
                if s10 != last_s10:
                    last_s10 = s10
                    self._s10_seq.append(s10)
                dft = smc_mem.read32(SMC_DFT_STATUS_ADDR)
                if dft != last_dft:
                    last_dft = dft
                    self._dft_seq.append(dft)
        except Exception:  # noqa: BLE001 - end of sim tears down the clock
            return

    def log_transport(self, flash) -> None:
        # Runs from the base's `finally`, i.e. before any assertion can abort the
        # run, so the gate evidence is in the log even when a later check fails.
        self.logger.info("cold_scratch[1] sequence: %s", [hex(v) for v in self._status_seq])
        self.logger.info("SMC scratch[10] sequence: %s", [hex(v) for v in self._s10_seq])
        self.logger.info("DFX_CTRL_STATUS_SMU sequence: %s", [hex(v) for v in self._dft_seq])

    async def run_scenario(self) -> None:
        # Guard the stimulus before anything else. Without the injection the tb
        # default 0x113 passes both arms, the failure branch is never taken, and
        # every check below would be describing an ordinary boot.
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

        # Per-instance lists, shadowing the class-level defaults above.
        self._status_seq = []
        self._s10_seq = []
        self._dft_seq = []
        cocotb.start_soon(self._gate_monitor())
        # Boots, and asserts the SPI path markers plus fw_done/fw_pass. Reaching
        # the end of this call is the "boot continued" half of the result, and it
        # covers the procedure's "scratch 0 != 0xdeadbeef at end of test".
        await super().run_scenario()

        status_hex = [hex(v) for v in self._status_seq]
        s10_hex = [hex(v) for v in self._s10_seq]
        dft_hex = [hex(v) for v in self._dft_seq]

        # CHK-DFT-INJECTED: the word the gate reads over AXI really is the failing
        # one, measured at the SMC rather than at cocotb's copy of the command
        # line. If the plusarg failed to apply, the model would hold the tb default
        # 0x113 -- which passes both arms, so the boot would still succeed and every
        # remaining check would still hold while the bypass was never
        # exercised. The leading 0 is the probe flop's own power-up value, sampled
        # before its first clocked update, not a value the DUT ever presented.
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
        self.logger.info(
            "CHK-DFT-INJECTED: DFX_CTRL_STATUS_SMU = 0x%08x at the SMC", _DFT_STATUS_FAIL
        )

        # CHK-DFT-REACHED: vector.S ran up to the instruction before the gate, so
        # the checks below describe this gate rather than a path that never got
        # there.
        assert _STATUS_PRESTART_DONE in self._status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_PRESTART_DONE:08x} "
            f"(BOOTROM_PRESTART_DONE, written immediately before the gate); the run "
            f"cannot be said to have reached the MEM_REPAIR gate. "
            f"Observed {status_hex}"
        )
        self.logger.info("CHK-DFT-REACHED: cold_scratch[1] = 0x%08x", _STATUS_PRESTART_DONE)

        # CHK-MBIST-FAIL-TAKEN: the gate classified the injected word as a FAILURE.
        # This is what separates this arm from the pass arm: without it, a run in
        # which the gate simply continued (because it never saw the failure) would
        # satisfy every "boot completed" check below.
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

        # CHK-MBIST-PUBLISH: the raw status reached SMC scratch[10]. The procedure
        # calls this out specifically, and it is durable -- unlike the WARN word,
        # nothing else writes scratch[10], so it survives to the end of the boot.
        assert _DFT_STATUS_FAIL in self._s10_seq, (
            f"SMC scratch[10] never held the failing DFT status "
            f"0x{_DFT_STATUS_FAIL:08x}; the ROM did not publish the value it "
            f"gated on. Observed {s10_hex}"
        )
        self.logger.info("CHK-MBIST-PUBLISH: SMC scratch[10] = 0x%08x", _DFT_STATUS_FAIL)

        # CHK-BYPASS-TAKEN: the ERROR word never appeared. Together with the
        # completed boot above, this is the bypass: the gate found the failure,
        # recorded it, consulted the fuse, and did NOT halt.
        assert _STATUS_DFT_GATE_BLOCKED not in self._status_seq, (
            f"cold_scratch[1] held ROM_ERR_DFT_GATE_BLOCKED "
            f"0x{_STATUS_DFT_GATE_BLOCKED:08x}: the ROM halted despite the bypass "
            f"fuse being blown. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-BYPASS-TAKEN: 0x%08x never reached cold_scratch[1]; the boot "
            "continued past a failed MEM_REPAIR because STATUS_RPT bit %d was blown",
            _STATUS_DFT_GATE_BLOCKED,
            _STATUS_RPT_SKIP_MEM_CHECK_BIT,
        )

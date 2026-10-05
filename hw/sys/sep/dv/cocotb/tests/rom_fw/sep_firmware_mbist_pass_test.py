# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM MEM_REPAIR / MBIST boot gate, PASS arm.

The pass-side partner of ``sep_firmware_mbist_fail_test``, whose comment above
``_DFT_STATUS_FAIL`` lists the gate in ``bootrom/prod/src/vector.S``.
``hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl`` declares ``mem_repair_done[0]``,
``mem_repair_success[1]``, ``mem_repair_abort[2]``, ``mbist_done[4]``, ``mbist_pass[8]`` and
``mbist_abort[12]``. The gate keys on ``mem_repair_success`` and ``mbist_pass``, after it waits
for ``mbist_done``. ``hw/sys/smc/regs/gen/c/smc_addr.h`` places
``SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR`` at 0xC000_B800, seen from SEP as 0x4000_B800. The SMC
responder is a flat memory, so this test cannot fail on the address; ``tb_top.sv`` flags an access
outside a declared window through ``smc_addr_violations_o``.

The gate runs before the C runtime starts and its pass arm prints nothing, so the checks assert
that execution reached the C runtime and that no failure-arm observable appeared.
``+sep_dft_status=00000112`` is exactly bits 1, 4 and 8. The testbench default 0x113 also boots, so
the injection is what makes the run a test. 0x112 hangs a gate on ``mem_repair_done``, on the whole
word equal to 0x113, or on a required abort bit. "Any bit set" is ruled out by the fail tests:
0xFFFFFFFD must block on repair and 0x12 must block on MBIST.

Not covered: the ``BYPASS_SRAM_REPAIR`` and ``MBIST_BYPASS`` strap arms, the ``mbist_abort``
branch, the poll timeout, and an MBIST failure followed by a blown ``SKIP_MEM_CHECK`` fuse
(``sep_mbist_fail_continue_test`` enters the fuse arm from the repair failure). The OT-SPI boot
gives the run a definite end; the gate is upstream of the transport choice.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_smc_mem import SMC_DFT_STATUS_ADDR, SMC_SCRATCH10_ADDR
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Must match +sep_dft_status in the testlist entry.
#
# 0x112 is exactly the three bits the ROM's boot gate requires, and nothing else:
# mem_repair_success (bit 1) for the repair arm, and mbist_done (bit 4) plus
# mbist_pass (bit 8) for the MBIST arm. mbist_done matters as much as mbist_pass:
# the gate polls for it before trusting the verdict, because the hardware releases
# the SEP CPU after repair alone and MBIST may still be running.
#
# 0x2 (mem_repair_success alone) hangs: with mbist_done clear the gate waits for
# MBIST, times out and treats it as a failure.
#
# The MBIST arm's FAILURE path is covered by sep_firmware_mbist_only_fail_test,
# which injects 0x12 (mem_repair_success + mbist_done, mbist_pass CLEAR) so it
# passes the repair arm and is rejected by the MBIST verdict. sep_firmware_mbist_
# fail_test cannot do that job: its 0xFFFFFFFD fails the repair arm first and
# never reaches the MBIST check.
_DFT_STATUS_PASS = 0x0000_0112
# bootrom/prod/include/sep_smc_interface.h and
# hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl.
_MEM_REPAIR_DONE_BIT = 0
_MEM_REPAIR_SUCCESS_BIT = 1
_MBIST_DONE_BIT = 4
_MBIST_PASS_BIT = 8
_MEM_REPAIR_ABORT_BIT = 2
_MBIST_ABORT_BIT = 12

# The two words the FAILURE arm writes to cold_scratch[1]; neither may appear.
# Kept numerically identical to sep_firmware_mbist_fail_test so the pair states
# one contract from both sides.
_STATUS_MBIST_WARN = 0x0801_0000 | 0x219  # WARN + SEP_MSG_MBIST_FAIL
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | 0xD001  # ERROR + ROM_ERR_DFT_GATE_BLOCKED
# Written by vector.S immediately before the gate: the
# STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_BOOTROM_PRESTART_DONE) store, the last
# thing that runs ahead of the `lw` of DFX_CTRL_STATUS_SMU. Its presence places
# execution at the gate, so "the boot completed" is a statement about this gate.
_STATUS_PRESTART_DONE = 0x8001_0056

# C-runtime console markers. The failure arm forbids these because the gate stops
# the ROM before C exists; the pass arm must therefore require them, or "the gate
# let it through" would rest on the boot result alone.
#   SMC_MEM_CHK  rom_main.c
#   CHIP_ID=     rom_main.c
_POST_GATE_MARKERS = ("SMC_MEM_CHK", "CHIP_ID=")


@pyuvm.test()
class sep_firmware_mbist_pass_test(sep_rom_ot_dma_boot_test):
    """Exactly mem_repair_success, mbist_done and mbist_pass set: the ROM boots straight through."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + _POST_GATE_MARKERS

    # Populated by _gate_monitor(); read by log_transport(), which the base calls
    # from a `finally` that can run before the monitor ever starts.
    _status_seq: list[int] = []
    _s10_seq: list[int] = []
    _dft_seq: list[int] = []

    async def _gate_monitor(self) -> None:
        """Record every change of cold_scratch[1] and SMC scratch[10].

        Sampled continuously rather than read at the end because both of the
        failure arm's observables are transient in principle: cold_scratch[1] is
        overwritten by each subsequent report_status(), so a WARN word written and
        then moved past would be invisible to a single final read. The absence
        claims below are only meaningful against the whole sequence.
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
        # default 0x113 boots for its own reasons and every check below would be
        # describing an ordinary boot.
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
        # Self-check the stimulus shape, so a future edit cannot turn this into a
        # weaker injection that any plausible gate would pass.
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
        _required = (1 << _MEM_REPAIR_SUCCESS_BIT) | (1 << _MBIST_DONE_BIT) | (1 << _MBIST_PASS_BIT)
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
            "repair_abort=%d mbist_abort=%d -- all clear)",
            _DFT_STATUS_PASS,
            (_DFT_STATUS_PASS >> _MEM_REPAIR_DONE_BIT) & 1,
            (_DFT_STATUS_PASS >> _MEM_REPAIR_ABORT_BIT) & 1,
            (_DFT_STATUS_PASS >> _MBIST_ABORT_BIT) & 1,
        )

        # Per-instance lists, shadowing the class-level defaults above.
        self._status_seq = []
        self._s10_seq = []
        self._dft_seq = []
        cocotb.start_soon(self._gate_monitor())
        # Boots, and asserts the SPI path markers plus fw_done/fw_pass. Reaching
        # the end of this call is the "execution continued" half of the result.
        await super().run_scenario()

        status_hex = [hex(v) for v in self._status_seq]
        s10_hex = [hex(v) for v in self._s10_seq]
        dft_hex = [hex(v) for v in self._dft_seq]

        # CHK-DFT-INJECTED: the word the ROM's gate reads over AXI really is the
        # one this test asked for, measured at the SMC model rather than at
        # cocotb's copy of the command line. The plusarg guard above proves only
        # that the run was LAUNCHED with the injection. If the plusarg does not
        # apply on the RTL side, the model holds the testbench default 0x113,
        # which passes both arms, and the boot still succeeds.
        #
        # _gate_monitor reads the SMC responder on each clock. The checker permits
        # only 0 and the injected word, and requires the final sample to equal the
        # injected word; the testbench default 0x113 is not permitted.
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
            f"DFX_CTRL_STATUS_SMU held {dft_hex}; the only values allowed are "
            f"0 and the injected 0x{_DFT_STATUS_PASS:08x}. Any "
            f"other value -- in particular the testbench default 0x00000113 -- "
            f"means the gate read something this testcase did not choose"
        )
        self.logger.info(
            "CHK-DFT-INJECTED: DFX_CTRL_STATUS_SMU = 0x%08x at the SMC, for the whole run",
            _DFT_STATUS_PASS,
        )

        # CHK-DFT-REACHED: vector.S ran up to the instruction before the gate.
        # Without this the absence checks below would also hold for a run that
        # never got as far as the gate at all.
        assert _STATUS_PRESTART_DONE in self._status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_PRESTART_DONE:08x} "
            f"(BOOTROM_PRESTART_DONE, written immediately before the gate): the "
            f"run cannot be said to have reached the MEM_REPAIR gate. "
            f"Observed {status_hex}"
        )
        self.logger.info(
            "CHK-DFT-REACHED: cold_scratch[1] = 0x%08x, so execution arrived at the gate",
            _STATUS_PRESTART_DONE,
        )

        # CHK-DFT-NO-WARN / CHK-DFT-NO-BLOCK: neither word the failure arm writes
        # ever appeared. These are the direct negatives of the fail test's
        # CHK-DFT-DETECT and CHK-DFT-TERMINAL.
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
            _STATUS_MBIST_WARN,
            _STATUS_DFT_GATE_BLOCKED,
        )

        # CHK-DFT-NO-PUBLISH: SMC scratch[10] is written only by the failure arm
        # (the first store under vector.S's ``dft_gate_failed`` label), so it must
        # stay at its power-on 0. This is the
        # independent half of the two absence checks above: it lives in a
        # different register block, written by a different instruction.
        assert set(self._s10_seq) <= {0}, (
            f"SMC scratch[10] was written ({s10_hex}); only the MEM_REPAIR failure "
            f"arm publishes there, so the gate took the failure branch"
        )
        self.logger.info("CHK-DFT-NO-PUBLISH: SMC scratch[10] stayed 0")

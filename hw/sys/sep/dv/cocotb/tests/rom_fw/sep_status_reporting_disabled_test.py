# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``STATUS_RPT_DISABLE`` (``STRAPS_LO[21]``) stops only the SMC SRAM status ring.

rom.adoc defines the strap as status-ring disable with ``cold_scratch[1]`` retained. The test
publishes a valid, non-full ring before reset (scratch[11] points at it, scratch[9] reports it
ready), so a ROM that ignored the strap would insert entries and move the head. With the strap
set the ring bytes must be unchanged at the end of the boot, ``cold_scratch[1]`` must announce
the disable and keep changing afterwards, and the boot must reach the same BL1 PASS as the enabled
control ``sep_firmware_mbist_pass_test`` (same DFX word, same OT-SPI image).

Scope: the captured strap word at the SMC model to the ROM branch; SMC-side handling of the
strap is a separate SMC ROM contract.
"""

from __future__ import annotations

import pyuvm
from env.sep_smc_mem import (
    SEP_STATUS_RING_BASE,
    SMC_SCRATCH9_ADDR,
    preload_sep_status_ring,
    read_sep_status_ring,
)
from rom_fw.sep_dft_gate_base import (
    MBIST_DONE_BIT,
    MBIST_PASS_BIT,
    MEM_REPAIR_SUCCESS_BIT,
    sep_dft_gate_boot_base,
)

_STRAP_STATUS_RPT_DISABLE_LO = 1 << 21
# bootrom/prod/include/sep_smc_interface.h SMC_SEP_STATUS_BUFFER_READY.
_SMC_SEP_STATUS_BUFFER_READY = 1 << 2
# STATUS_ENCODE(DEBUG, SEP_MSG_STATUS_REPORTING_{DISABLED,ENABLED,READY}), status_values.h.
_STATUS_RPT_DISABLED = 0x8001_0076
_STATUS_RPT_ENABLED = 0x8001_0077
_STATUS_RPT_READY = 0x8001_0078

# Non-full ring: head one past tail leaves capacity, so an enabled ROM would write entries[1].
_RING_HEAD = 1
_RING_TAIL = 0
_RING_ENTRIES = [0xA55A_5AA5] + [0xC3C3_0000 | i for i in range(1, 8)]


@pyuvm.test()
class sep_status_reporting_disabled_test(sep_dft_gate_boot_base):
    """Disable strap set over a live ring: scratch status continues, ring bytes stay put."""

    expected_dft_status = (
        (1 << MEM_REPAIR_SUCCESS_BIT) | (1 << MBIST_DONE_BIT) | (1 << MBIST_PASS_BIT)
    )
    required_straps_lo = _STRAP_STATUS_RPT_DISABLE_LO
    required_markers = sep_dft_gate_boot_base.required_markers + ("STATUS_RPT_DISABLED",)
    forbidden_markers = sep_dft_gate_boot_base.forbidden_markers + (
        "STATUS_RPT_ENABLED",
        "ring buffer address:",
    )

    def check_stimulus_shape(self) -> None:
        self.logger.info(
            "CHK-STATUS-DISABLE-STIMULUS: launch straps STRAPS_LO[21] over the passing DFX "
            "word 0x%08x",
            self.expected_dft_status,
        )

    async def run_scenario(self) -> None:
        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "SMC responder not bound (rom_boot target only)"
        scratch9 = smc_mem.read32(SMC_SCRATCH9_ADDR)
        assert scratch9 & _SMC_SEP_STATUS_BUFFER_READY, (
            f"SMC scratch[9] = 0x{scratch9:08x} does not report the ring ready; an enabled ROM "
            f"would then wait instead of writing, and the quiet ring would prove nothing"
        )
        self._ring_before = preload_sep_status_ring(
            smc_mem, head=_RING_HEAD, tail=_RING_TAIL, entries=_RING_ENTRIES
        )
        self.logger.info(
            "status ring at 0x%08x before boot: %s", SEP_STATUS_RING_BASE, self._ring_before.hex()
        )
        await super().run_scenario()

    def check_gate_outcome(self, console: list[str]) -> None:
        self.assert_dft_injected("CHK-STATUS-DISABLE-STIMULUS")
        self.assert_straps_captured("CHK-STATUS-DISABLE-STIMULUS", console)
        self.logger.info(
            "CHK-STATUS-DISABLE-STIMULUS PASS: STRAPS_LO[21] measured at the SMC and echoed by "
            "the ROM"
        )

        status_hex = [hex(v) for v in self.status_seq]
        assert _STATUS_RPT_DISABLED in self.status_seq, (
            f"cold_scratch[1] never held STATUS_REPORTING_DISABLED 0x{_STATUS_RPT_DISABLED:08x}. "
            f"Observed {status_hex}"
        )
        for word in (_STATUS_RPT_ENABLED, _STATUS_RPT_READY):
            assert word not in self.status_seq, (
                f"cold_scratch[1] held 0x{word:08x}: the ROM took the ring-enable path despite "
                f"the strap. Observed {status_hex}"
            )
        self.logger.info(
            "CHK-STATUS-DISABLE-ANNOUNCE PASS: STATUS_RPT_DISABLED on the console and "
            "0x%08x in cold_scratch[1]; no ENABLED/READY word",
            _STATUS_RPT_DISABLED,
        )

        after = self.status_seq[self.status_seq.index(_STATUS_RPT_DISABLED) + 1 :]
        assert after, (
            f"cold_scratch[1] never changed after STATUS_REPORTING_DISABLED: the scratch status "
            f"channel stopped with the ring. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-STATUS-DISABLE-SCRATCH PASS: %d further cold_scratch[1] update(s) after the "
            "announcement: %s",
            len(after),
            [hex(v) for v in after],
        )

        smc_mem = self.cfg.smc_mem
        ring_after = read_sep_status_ring(smc_mem, len(_RING_ENTRIES))
        assert ring_after == self._ring_before, (
            f"status ring at 0x{SEP_STATUS_RING_BASE:08x} changed during the boot: before "
            f"{self._ring_before.hex()}, after {ring_after.hex()}. The ROM wrote the ring "
            f"although STATUS_RPT_DISABLE was strapped"
        )
        self.logger.info(
            "CHK-STATUS-DISABLE-RING-QUIET PASS: head, tail, num_entries and %d entries "
            "byte-identical (%d bytes)",
            len(_RING_ENTRIES),
            len(ring_after),
        )

        self.assert_gate_reached("CHK-STATUS-DISABLE-BOOT")
        self.assert_no_failure_arm("CHK-STATUS-DISABLE-BOOT", "CHK-STATUS-DISABLE-BOOT")
        self.logger.info(
            "CHK-STATUS-DISABLE-BOOT PASS: BL1 PASS verdict over OT-SPI, the outcome of the "
            "enabled control sep_firmware_mbist_pass_test"
        )

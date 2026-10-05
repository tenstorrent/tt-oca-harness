# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Non-vacuous SMC and SEP boot scoreboards for the SMU wrapper OSS flow."""

from __future__ import annotations

import cocotb
from pyuvm import ConfigDB, UVMConfigItemNotFound, uvm_component

__all__ = ["SmuSepBootScoreboard", "SmuSmcBootScoreboard"]


class SmuSmcBootScoreboard(uvm_component):
    """Require SMC instruction-memory activity and an architectural PASS."""

    def build_phase(self) -> None:
        self.pass_seen = False
        self.fail_seen = False
        self.max_rom_reads = 0
        self.max_scratch_writes = 0
        self._finalized = False

    def sample(self, *, passed: int, failed: int, rom_reads: int, scratch_writes: int) -> None:
        self.pass_seen |= bool(passed)
        self.fail_seen |= bool(failed)
        self.max_rom_reads = max(self.max_rom_reads, rom_reads)
        self.max_scratch_writes = max(self.max_scratch_writes, scratch_writes)

    @staticmethod
    def _log_evidence(logger, token: str) -> None:
        logger.info("EVIDENCE: %s", token)
        logger.info("EVIDENCE:%s", token)
        if not token.startswith("CHK-"):
            logger.info("EVIDENCE:CHK-%s", token)
            logger.info("EVIDENCE: CHK-%s", token)

    def finalize(self) -> None:
        """Grade the samples once and stamp the evidence tokens.

        The leaf calls it at the end of run_scenario so the tokens are in the
        log before the base test's evidence gate reads them; check_phase runs
        top-down in pyuvm, after that gate, and calls it only as a fallback.
        """
        if self._finalized:
            return
        self._finalized = True
        self.logger.info(
            "SMC boot evidence: pass=%s fail=%s rom_reads=%d scratch_writes=%d",
            self.pass_seen,
            self.fail_seen,
            self.max_rom_reads,
            self.max_scratch_writes,
        )
        errors: list[str] = []
        if self.fail_seen:
            errors.append("SMC firmware wrote TEST_FAIL")
        if not self.pass_seen:
            errors.append("SMC firmware never wrote TEST_PASS")
        if self.max_rom_reads == 0:
            errors.append("SMC ROM had no read activity")
        if self.max_scratch_writes == 0:
            errors.append("SMC scratch SRAM had no write activity")
        assert not errors, "SMC boot scoreboard: " + "; ".join(errors)
        # Evidence tokens of the wrapper firmware smoke
        self._log_evidence(self.logger, "SMC_ROM_READ_OK")
        self._log_evidence(self.logger, "SMC_SCRATCH_WRITE_OK")
        self._log_evidence(self.logger, "SMC_TEST_PASS_OK")
        self._log_evidence(self.logger, "CHK-NONVAC")

    def check_phase(self) -> None:
        self.finalize()


class SmuSepBootScoreboard(uvm_component):
    """Require real SEP reset, boot-ROM fetch, ICCM execution, and DCCM stores.

    This is the boot-readiness bar of the SMU-level SEP smoke: SEP must be
    observed fetching from the boot-ROM entry window and then executing
    firmware from ICCM.
    Console/STDOUT checking over the external AXI path is out of scope here.
    """

    MIN_DISTINCT_PCS = 16
    MIN_TRACES = 256
    BOOT_ROM_BASE = 0x1004_0000
    BOOT_ROM_END = 0x1005_0000
    ICCM_BASE = 0xC000_0000
    ICCM_END = 0xC004_0000

    def build_phase(self) -> None:
        # Retirement evidence lives in the SEP CPU trace monitor, which
        # smu_base_test builds before any scoreboard. check_phase fails loudly
        # when it is absent: skipping the PC-advance check would vacuously pass
        # a core that never booted.
        try:
            self.trace_mon = ConfigDB().get(self, "", "sep_trace_mon")
        except UVMConfigItemNotFound:
            self.trace_mon = None
        self.reset_low_seen = False
        self.reset_high_seen = False
        self.fuse_low_seen = False
        self.fuse_high_seen = False
        self._fuse_sense_skipped = None
        self.smc_arm_seen = False
        self.boot_rom_seen = False
        self.iccm_seen = False
        self.max_dccm_writes = 0
        self.console = bytearray()
        self._finalized = False

    @property
    def fuse_sense_skipped(self) -> bool:
        """Whether the DUT replaced the SEP fuse sense with the shadow preload.

        Read from ``sep_fuse_sense_skipped_o``, which the testbench drives from
        the SEP efuse shadow registers' own ``sim_skip_fuse_sense`` flag: the
        node that selects the substitute, inside the module that would otherwise
        run the sense. An unreadable or unresolved port reads as "the sense
        ran", which keeps the fuse conditions required.
        """
        if self._fuse_sense_skipped is None:
            signal = getattr(cocotb.top, "sep_fuse_sense_skipped_o", None)
            value = signal.value if signal is not None else None
            if value is None or (hasattr(value, "is_resolvable") and not value.is_resolvable):
                self._fuse_sense_skipped = False
            else:
                self._fuse_sense_skipped = bool(int(value))
        return self._fuse_sense_skipped

    def sample_status(self, *, reset_n: int, fuse_done: int) -> None:
        self.reset_low_seen |= not bool(reset_n)
        self.reset_high_seen |= bool(reset_n)
        self.fuse_low_seen |= not bool(fuse_done)
        self.fuse_high_seen |= bool(fuse_done)

    def sample_arm(self, smc_pass: int) -> None:
        self.smc_arm_seen |= bool(smc_pass)

    @property
    def trace_count(self) -> int:
        return self.trace_mon.trace_count if self.trace_mon is not None else 0

    @property
    def pcs(self) -> set[int]:
        return self.trace_mon.pcs if self.trace_mon is not None else set()

    def sample_windows(self, *, boot_rom_seen: int, iccm_seen: int) -> None:
        """Fold in the TB's sticky fetch-window detectors.

        The boot-ROM trampoline retires only a couple of instructions right
        after reset release, before the sequence loop starts polling; the
        hardware detectors in tb_wrapper_top.sv observe those cycles.
        """
        self.boot_rom_seen |= bool(boot_rom_seen)
        self.iccm_seen |= bool(iccm_seen)

    def sample_dccm(self, dccm_writes: int) -> None:
        self.max_dccm_writes = max(self.max_dccm_writes, dccm_writes)

    def sample_char(self, byte: int) -> None:
        self.console.append(byte & 0xFF)

    def console_text(self) -> str:
        return bytes(self.console).decode("ascii", "replace")

    def boot_ready(self) -> bool:
        """True once every required boot-readiness evidence item is present.

        The fuse-sense terms count only when the sense actually runs; with the
        substitute active they are testbench-supplied and carry no readiness.
        """
        fuse_ready = self.fuse_sense_skipped or (self.fuse_low_seen and self.fuse_high_seen)
        return (
            self.reset_low_seen
            and self.reset_high_seen
            and fuse_ready
            and self.smc_arm_seen
            and self.boot_rom_seen
            and self.iccm_seen
            and self.trace_count >= self.MIN_TRACES
            and len(self.pcs) >= self.MIN_DISTINCT_PCS
            and self.max_dccm_writes > 0
        )

    @staticmethod
    def _log_evidence(logger, token: str) -> None:
        logger.info("EVIDENCE: %s", token)
        logger.info("EVIDENCE:%s", token)
        if not token.startswith("CHK-"):
            logger.info("EVIDENCE:CHK-%s", token)
            logger.info("EVIDENCE: CHK-%s", token)

    def finalize(self) -> None:
        """Grade the samples once and stamp the evidence tokens.

        Same contract as SmuSmcBootScoreboard.finalize: the leaf calls it at
        the end of run_scenario, ahead of the base test's evidence gate.
        """
        if self._finalized:
            return
        self._finalized = True
        self.logger.info(
            "SEP boot evidence: reset(low/high)=%s/%s fuse(low/high)=%s/%s "
            "fuse_sense_skipped=%s smc_arm=%s traces=%d distinct_pcs=%d "
            "boot_rom=%s iccm=%s dccm_writes=%d console=%r",
            self.reset_low_seen,
            self.reset_high_seen,
            self.fuse_low_seen,
            self.fuse_high_seen,
            self.fuse_sense_skipped,
            self.smc_arm_seen,
            self.trace_count,
            len(self.pcs),
            self.boot_rom_seen,
            self.iccm_seen,
            self.max_dccm_writes,
            self.console_text(),
        )
        errors: list[str] = []
        if self.trace_mon is None:
            errors.append("no SEP CPU trace monitor attached (sep_trace_mon missing from ConfigDB)")
        if not self.reset_low_seen:
            errors.append("SEP reset was never observed asserted")
        if not self.reset_high_seen:
            errors.append("SEP reset was never observed released")
        if self.fuse_sense_skipped:
            self.logger.info(
                "SEP fuse sense is replaced by the shadow-register preload in this run "
                "(sep_fuse_sense_skipped_o=1): fuse-done low/high=%s/%s is informational, "
                "not boot-readiness evidence",
                self.fuse_low_seen,
                self.fuse_high_seen,
            )
        else:
            if not self.fuse_low_seen:
                errors.append("SEP fuse-done was never observed inactive")
            if not self.fuse_high_seen:
                errors.append("SEP fuse sense never completed")
        if not self.smc_arm_seen:
            errors.append("SMC arm firmware never signaled TEST_PASS")
        if not self.boot_rom_seen:
            errors.append("SEP never fetched from the boot-ROM window")
        if not self.iccm_seen:
            errors.append("SEP never executed in the ICCM range")
        if self.trace_count < self.MIN_TRACES:
            errors.append(
                f"SEP retired {self.trace_count} instructions; minimum is {self.MIN_TRACES}"
            )
        if len(self.pcs) < self.MIN_DISTINCT_PCS:
            errors.append(
                f"SEP observed {len(self.pcs)} distinct PCs; minimum is {self.MIN_DISTINCT_PCS}"
            )
        if self.max_dccm_writes == 0:
            errors.append("SEP firmware never stored results into DCCM")
        assert not errors, "SEP boot scoreboard: " + "; ".join(errors)
        self._log_evidence(self.logger, "SEP_BOOT_ROM_OK")
        self._log_evidence(self.logger, "SEP_ICCM_OK")
        self._log_evidence(self.logger, "SEP_DCCM_WRITE_OK")
        self._log_evidence(self.logger, "CHK-NONVAC")

    def check_phase(self) -> None:
        self.finalize()

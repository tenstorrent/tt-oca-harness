# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Non-vacuous SMC and SEP boot scoreboards for the SMU wrapper OSS flow."""

from __future__ import annotations

from pyuvm import uvm_component


class SmuSmcBootScoreboard(uvm_component):
    """Require SMC instruction-memory activity and an architectural PASS."""

    def build_phase(self) -> None:
        self.pass_seen = False
        self.fail_seen = False
        self.max_rom_reads = 0
        self.max_scratch_writes = 0

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

    def check_phase(self) -> None:
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
        # aidv tokens for wrapper firmware smoke (distinct from DUT cocotb smoke)
        self._log_evidence(self.logger, "SMC_ROM_READ_OK")
        self._log_evidence(self.logger, "SMC_SCRATCH_WRITE_OK")
        self._log_evidence(self.logger, "SMC_TEST_PASS_OK")
        self._log_evidence(self.logger, "CHK-NONVAC")


class SmuSepBootScoreboard(uvm_component):
    """Require real SEP reset, boot-ROM fetch, ICCM execution, and DCCM stores.

    This is the boot-readiness bar of the SMU-level SEP smoke (mirroring the
    internal `smu_sep_smoke_test` contract): SEP must be observed fetching
    from the boot-ROM entry window and then executing firmware from ICCM.
    Console/STDOUT checking over the external AXI path is out of scope here
    and tracked separately (issue #3939).
    """

    MIN_DISTINCT_PCS = 16
    MIN_TRACES = 256
    BOOT_ROM_BASE = 0x1004_0000
    BOOT_ROM_END = 0x1005_0000
    ICCM_BASE = 0xC000_0000
    ICCM_END = 0xC004_0000

    def build_phase(self) -> None:
        self.reset_low_seen = False
        self.reset_high_seen = False
        self.fuse_low_seen = False
        self.fuse_high_seen = False
        self.smc_arm_seen = False
        self.trace_count = 0
        self.pcs: set[int] = set()
        self.boot_rom_seen = False
        self.iccm_seen = False
        self.max_dccm_writes = 0
        self.console = bytearray()

    def sample_status(self, *, reset_n: int, fuse_done: int) -> None:
        self.reset_low_seen |= not bool(reset_n)
        self.reset_high_seen |= bool(reset_n)
        self.fuse_low_seen |= not bool(fuse_done)
        self.fuse_high_seen |= bool(fuse_done)

    def sample_arm(self, smc_pass: int) -> None:
        self.smc_arm_seen |= bool(smc_pass)

    def sample_trace(self, valid: int, pc: int) -> None:
        if valid:
            pc &= 0xFFFF_FFFF
            self.trace_count += 1
            self.pcs.add(pc)
            self.boot_rom_seen |= self.BOOT_ROM_BASE <= pc < self.BOOT_ROM_END
            self.iccm_seen |= self.ICCM_BASE <= pc < self.ICCM_END

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
        """True once every required boot-readiness evidence item is present."""
        return (
            self.reset_low_seen
            and self.reset_high_seen
            and self.fuse_low_seen
            and self.fuse_high_seen
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

    def check_phase(self) -> None:
        self.logger.info(
            "SEP boot evidence: reset(low/high)=%s/%s fuse(low/high)=%s/%s "
            "smc_arm=%s traces=%d distinct_pcs=%d boot_rom=%s iccm=%s "
            "dccm_writes=%d console=%r",
            self.reset_low_seen,
            self.reset_high_seen,
            self.fuse_low_seen,
            self.fuse_high_seen,
            self.smc_arm_seen,
            self.trace_count,
            len(self.pcs),
            self.boot_rom_seen,
            self.iccm_seen,
            self.max_dccm_writes,
            self.console_text(),
        )
        errors: list[str] = []
        if not self.reset_low_seen:
            errors.append("SEP reset was never observed asserted")
        if not self.reset_high_seen:
            errors.append("SEP reset was never observed released")
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

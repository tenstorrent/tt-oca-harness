# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS scoreboard (6 item types)."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_subscriber

from .smc_axil_item import SmcAxilItem, SmcAxilOp
from .smc_clk_item import SmcClkItem, SmcClkOp
from .smc_gpio_item import SmcGpioItem, SmcGpioOp
from .smc_i2c_item import SmcI2cItem, SmcI2cOp
from .smc_irq_item import SmcIrqItem, SmcIrqOp
from .smc_memory_model import SmcMemoryModel
from .smc_protocol_vip_item import SmcProtocolVipItem
from .smc_reset_item import SmcResetItem, SmcResetOp
from .smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp


class SmcScoreboard(uvm_subscriber):

    def build_phase(self) -> None:
        self.i2c_samples_seen = 0
        self.reset_samples_seen = 0
        self.clk_samples_seen = 0
        self.irq_samples_seen = 0
        self.gpio_samples_seen = 0
        self.axil_samples_seen = 0
        self.sys_axi_checks_seen = 0
        self.sys_axi_value_checks_seen = 0
        self.memory_model_updates_seen = 0
        self.memory_model_checks_seen = 0
        self.protocol_vip_checks_seen = 0
        self.action_items_seen = 0
        # TB-local golden only — never a DUT hierarchy backdoor (U1-3).
        self.memory_model: SmcMemoryModel | None = None
        try:
            cfg = ConfigDB().get(self, "", "cfg")
            self.memory_model = getattr(cfg, "memory_model", None)
        except Exception:
            self.memory_model = None
        self.events: dict[str, set] = {
            "reset_op": set(),
            "reset_state": set(),
            "i2c_state": set(),
            "clk_bucket": set(),
            "irq_state": set(),
            "gpio_state": set(),
            "axil_master": set(),
            "sys_axi": set(),
            "protocol_vip": set(),
            "memory_model": set(),
        }

    def _cov(self, bin_name: str, value) -> None:
        self.events[bin_name].add(value)
        self.logger.info("FUNC_COV_VALUE bin=%s value=%s", bin_name, value)

    def write(self, item) -> None:
        if isinstance(item, SmcI2cItem):
            self._check_i2c(item)
        elif isinstance(item, SmcResetItem):
            self._check_reset(item)
        elif isinstance(item, SmcClkItem):
            self._check_clk(item)
        elif isinstance(item, SmcIrqItem):
            self._check_irq(item)
        elif isinstance(item, SmcGpioItem):
            self._check_gpio(item)
        elif isinstance(item, SmcAxilItem):
            self._check_axil(item)
        elif isinstance(item, SmcSysAxiItem):
            self._check_sys_axi(item)
        elif isinstance(item, SmcProtocolVipItem):
            self._check_protocol_vip(item)
        else:
            self.logger.warning("SmcScoreboard ignoring %s", type(item).__name__)

    def _check_i2c(self, item):
        if item.op is not SmcI2cOp.SAMPLE: return
        self.i2c_samples_seen += 1
        self.logger.info("Scoreboard I2C sample #%d: %s", self.i2c_samples_seen, item)
        assert item.resolvable, f"I2C not resolvable: {item}"
        assert item.cg_en == 0
        self._cov("i2c_state", (int(item.resolvable), int(item.cg_en)))

    def _check_reset(self, item):
        self._cov("reset_op", item.op.name)
        if item.op is SmcResetOp.RAW_SAMPLE:
            # Snapshot during a glitch window: record the observed state without
            # enforcing the post-reset stable invariants.
            self._cov("reset_state", (item.powergood_stable, item.rst_cold_stable_ref_clk_n, item.rst_primary_ref_clk_n, item.rst_primary_smc_clk_n))
            return
        if item.op is not SmcResetOp.SAMPLE:
            self.action_items_seen += 1
            return
        self.reset_samples_seen += 1
        self.logger.info("Scoreboard reset sample #%d: %s", self.reset_samples_seen, item)
        assert item.resolvable, f"reset not resolvable: {item}"
        assert item.powergood_stable == 1
        assert item.rst_cold_stable_ref_clk_n == 1
        assert item.rst_primary_ref_clk_n == 1
        assert item.rst_primary_smc_clk_n == 1
        self._cov("reset_state", (item.powergood_stable, item.rst_cold_stable_ref_clk_n, item.rst_primary_ref_clk_n, item.rst_primary_smc_clk_n))

    def _check_clk(self, item):
        if item.op is not SmcClkOp.COUNT_EDGES: return
        self.clk_samples_seen += 1
        self.logger.info("Scoreboard clk sample #%d: %s", self.clk_samples_seen, item)
        assert item.ref_rising_edges > 0
        assert item.smc_rising_edges > 0
        assert item.periph_rising_edges > 0
        assert item.smc_rising_edges >= item.ref_rising_edges
        self._cov("clk_bucket", (item.ref_rising_edges // 50, item.smc_rising_edges // 50, item.periph_rising_edges // 50))

    def _check_irq(self, item):
        if item.op is not SmcIrqOp.SAMPLE: return
        self.irq_samples_seen += 1
        self.logger.info("Scoreboard IRQ sample #%d: %s", self.irq_samples_seen, item)
        assert item.resolvable, f"IRQ not resolvable: {item}"
        assert item.sync_irq == 0
        assert item.gpio_irq_any == 0
        assert item.uart_irq_any == 0
        self._cov("irq_state", (int(item.sync_irq), int(item.gpio_irq_any), int(item.uart_irq_any)))

    def _check_gpio(self, item):
        if item.op is not SmcGpioOp.SAMPLE: return
        self.gpio_samples_seen += 1
        self.logger.info("Scoreboard GPIO sample #%d: %s", self.gpio_samples_seen, item)
        # The real, non-vacuous evidence here is resolvability: the three GPIO
        # observability aggregates settle to a defined 0/1 (no X) after reset.
        # Their *value* is intentionally NOT asserted: they are OR-reductions over
        # the whole pad bus (which also carries idle-high LSIO pads such as UART
        # TX), so a specific level is a bus-aggregate artifact, not GPIO-diagnostic
        # -- asserting it would be a golden==observed common-mode lock. Isolated
        # per-pad GPIO drive is proven by smc_gpio_output_driveback_test. The
        # `in (0, 1)` guards below are only a belt-and-braces range check on the
        # already-resolved single-bit reductions.
        assert item.resolvable, f"GPIO not resolvable: {item}"
        assert item.core2pad_any in (0, 1)
        assert item.core2pad_en_any in (0, 1)
        assert item.pad2core_en_any in (0, 1)
        self._cov("gpio_state", (int(item.core2pad_any), int(item.core2pad_en_any), int(item.pad2core_en_any)))

    def _check_axil(self, item):
        if item.op is not SmcAxilOp.SAMPLE: return
        self.axil_samples_seen += 1
        self.logger.info("Scoreboard AXIL sample #%d: %s", self.axil_samples_seen, item)
        assert item.resolvable, f"AXIL not resolvable: {item}"
        # Idle invariant: no spurious AXI-Lite master traffic in the public smoke.
        assert item.any_master_active == 0, (
            f"tb_axil_any_master_active expected 0 (idle), got {item.any_master_active}"
        )
        self._cov("axil_master", (int(item.any_master_active),))

    def _resp_is_okay(self, item: SmcSysAxiItem) -> bool:
        """True only for AXI OKAY — not SLVERR/DECERR even if allow_error."""
        return (not item.timed_out) and item.resp_code == 0

    def _check_sys_axi(self, item):
        self.sys_axi_checks_seen += 1
        self.logger.info("Scoreboard SYS AXI check #%d: %s",
                         self.sys_axi_checks_seen, item)
        if getattr(item, "expect_error", False):
            # Negative-path probe (mirrors the SEP expect_error guard): a real
            # error response is the expected outcome. Two vacuous passes are
            # rejected structurally here, independent of the sequence's own
            # asserts: an OKAY response means the access was NOT blocked, and a
            # timeout means it wedged rather than returning an error.
            assert not item.timed_out, (
                f"SYS AXI {item.op.value} @ 0x{item.addr:014x} marked expect_error "
                f"but TIMED OUT (a blocked access must return an error, not wedge)"
            )
            assert item.resp_code is not None and item.resp_code > 1, (
                f"SYS AXI {item.op.value} @ 0x{item.addr:014x} marked expect_error "
                f"but returned resp={item.resp_code} (expected SLVERR/DECERR)"
            )
            self._cov("sys_axi", (item.op.value, item.addr >> 12))
            return
        assert item.resp_ok, (
            f"SYS AXI {item.op.value} @ 0x{item.addr:014x} returned non-OKAY"
        )
        if item.expected_resp is not None:
            assert item.resp_code == item.expected_resp, (
                f"SYS AXI {item.op.value} @ 0x{item.addr:014x} resp "
                f"{item.resp_code}, expected {item.expected_resp}"
            )
        self._cov("sys_axi", (item.op.value, item.addr >> 12))
        if item.op is SmcSysAxiOp.READ and item.expected is not None:
            mask = (1 << (item.length * 8)) - 1
            got = item.rdata & mask
            exp = item.expected & mask
            assert got == exp, (
                f"SYS AXI read 0x{item.addr:014x} = 0x{got:x}, expected 0x{exp:x}"
            )
            self.sys_axi_value_checks_seen += 1
        self._check_sys_axi_memory_model(item)

    def _check_sys_axi_memory_model(self, item: SmcSysAxiItem) -> None:
        """U1-3: update/compare TB-local SmcMemoryModel on OKAY fabric traffic."""
        if self.memory_model is None:
            return
        if item.update_golden:
            assert self._resp_is_okay(item), (
                f"SYS AXI golden update refused for non-OKAY "
                f"{item.op.value} @ 0x{item.addr:x} resp={item.resp_code}"
            )
            assert item.op is SmcSysAxiOp.WRITE, (
                "update_golden is only valid for SYS AXI writes"
            )
            region = self.memory_model.find_region(
                item.addr, item.length, item.memory_region
            )
            assert region is not None, (
                f"update_golden set but no memory region covers 0x{item.addr:x} "
                f"(region={item.memory_region!r})"
            )
            self.memory_model.write_int(
                item.addr,
                item.wdata,
                length=item.length,
                region=region.name,
            )
            self.memory_model_updates_seen += 1
            self._cov("memory_model", ("update", region.name, item.addr >> 3))
            self.logger.info(
                "Scoreboard memory-model UPDATE #%d: %s @ 0x%x <- 0x%x",
                self.memory_model_updates_seen,
                region.name,
                item.addr,
                item.wdata,
            )
        if item.check_golden:
            assert self._resp_is_okay(item), (
                f"SYS AXI golden check refused for non-OKAY "
                f"{item.op.value} @ 0x{item.addr:x} resp={item.resp_code}"
            )
            assert item.op is SmcSysAxiOp.READ, (
                "check_golden is only valid for SYS AXI reads"
            )
            region = self.memory_model.find_region(
                item.addr, item.length, item.memory_region
            )
            assert region is not None, (
                f"check_golden set but no memory region covers 0x{item.addr:x} "
                f"(region={item.memory_region!r})"
            )
            mask = (1 << (item.length * 8)) - 1
            exp = self.memory_model.read_int(
                item.addr, length=item.length, region=region.name
            ) & mask
            got = item.rdata & mask
            assert got == exp, (
                f"SYS AXI memory-model mismatch @ 0x{item.addr:x} "
                f"region={region.name}: got 0x{got:x}, expected 0x{exp:x}"
            )
            self.memory_model_checks_seen += 1
            self._cov("memory_model", ("check", region.name, item.addr >> 3))
            self.logger.info(
                "Scoreboard memory-model CHECK #%d: %s @ 0x%x == 0x%x",
                self.memory_model_checks_seen,
                region.name,
                item.addr,
                got,
            )

    def _check_protocol_vip(self, item):
        self.protocol_vip_checks_seen += 1
        self.logger.info("Scoreboard protocol VIP check #%d: %s",
                         self.protocol_vip_checks_seen, item)
        # `passed` is a completion marker only (always True when an item is
        # recorded — sequences abort on mismatch before recording). Do not
        # assert it; the real protocol verification lives in sequence-body /
        # SYS-AXI scoreboard checks. The checks below guard against a scenario
        # recording an empty/inconsistent evidence record (which would
        # otherwise let a mis-wired test log false coverage).
        assert item.scenario != "", "protocol VIP scenario name is empty"
        assert item.details != "", (
            f"protocol VIP {item.scenario} recorded without evidence details"
        )
        assert item.csr_accesses >= 0
        assert item.timeouts >= 0
        # Every timeout counted by csr_read_bounded() is also an access, so a
        # recorded item must never report more timeouts than accesses.
        assert item.timeouts <= item.csr_accesses, (
            f"protocol VIP {item.scenario}: timeouts ({item.timeouts}) exceed "
            f"csr_accesses ({item.csr_accesses})"
        )
        # U6-3: optional byte-level golden — mismatch fails the test.
        if item.expected_bytes is not None:
            obs = item.observed_bytes if item.observed_bytes is not None else b""
            assert obs == item.expected_bytes, (
                f"protocol VIP {item.scenario} byte golden mismatch: "
                f"got {obs.hex()}, expected {item.expected_bytes.hex()}"
            )
        self._cov("protocol_vip", (item.kind.value, item.scenario, int(item.proxy)))

    def check_phase(self):
        total = (self.i2c_samples_seen + self.reset_samples_seen + self.clk_samples_seen
                 + self.irq_samples_seen + self.gpio_samples_seen + self.axil_samples_seen
                 + self.sys_axi_checks_seen + self.protocol_vip_checks_seen)
        assert total > 0, "SmcScoreboard saw no SAMPLE items"

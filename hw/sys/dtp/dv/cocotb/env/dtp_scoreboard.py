# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP scoreboard: always on, in every test, and comparing only.

Every reference-model feature is judged on two streams the env wires in
``connect_phase``: the observed monitor stream (``observed_export``) and
the expected items its ``Dtp<Feature>RefModel`` publishes
(``expected_export``). The base pairs the two in order and hands each pair
to ``compare_pair()``, which extracts the observed value and records the
verdict; an expected item without a contract pairs and drops silently, so a
reference model can publish one item per observed item. Expected values
never originate here.

  ir_decode        expected: ``DtpIrDecodeRefModel`` on the JTAG event and
                   IR-scan streams. Observed: ``jtag_ptap_inst_decoded``,
                   sampled when the expected item arrives (the cycle the
                   instruction becomes active).
  idcode, bypass   expected: ``DtpIdcodeRefModel``, ``DtpBypassRefModel``.
                   Observed: the reconstructed DR scan's TDO bits.
  jtag2axi_op      the JTAG agent's completed JTAG2AXI single operations:
                   a write reports SUCCESS and lands its strobed bytes in
                   the responder memory, and a read reports SUCCESS and
                   returns the memory's bytes.

A required feature (``DtpEnvCfg.required_features``, set by the test) that
ends with zero comparisons fails the run. The scan monitor swallows a
subscriber exception and counts it, so the count is recorded as
``CHK-JTAG-MON-CALLBACKS`` and must be zero. The SV-UVM twin is
``dtp_scoreboard``.
"""

from __future__ import annotations

from ocah_jtag_vip import OcahJtagScanItem
from ocah_lib import OcahScoreboard
from pyuvm import ConfigDB

from .dtp_expected_item import DtpAnalysisImp, DtpExpectedItem
from .dtp_jtag_item import DtpJtagItem, DtpJtagOp
from .dtp_jtag_scan_builder import DtpJtagScanBuilder
from .dtp_types import (
    DTP_FEATURE_BYPASS,
    DTP_FEATURE_IDCODE,
    DTP_FEATURE_IR_DECODE,
    DtpJtag2AxiStatus,
    get_jtag2axi_target,
)

__all__ = ["DtpScoreboard"]

JTAG2AXI_OP_FEATURE = "jtag2axi_op"


class DtpScoreboard(OcahScoreboard):
    def __init__(self, name: str, parent: object) -> None:
        super().__init__(name, parent)
        self.name_tag = "dtp_scoreboard"
        # Set by the env: the scan builder whose monitor feeds the reference models.
        self.scan_builder: DtpJtagScanBuilder | None = None

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        for feature in (
            DTP_FEATURE_IR_DECODE,
            DTP_FEATURE_IDCODE,
            DTP_FEATURE_BYPASS,
            JTAG2AXI_OP_FEATURE,
        ):
            self.add_feature(feature)
        for feature in sorted(self.cfg.required_features):
            self.require_feature(feature)
        self.ir_decode_expected_export = DtpAnalysisImp(
            "ir_decode_expected_export", self, self.write_ir_decode_expected
        )
        self.op_export = DtpAnalysisImp("op_export", self, self.write_op)

    def check_phase(self) -> None:
        monitor = self.scan_builder.monitor if self.scan_builder is not None else None
        if monitor is not None and self.evidence is not None:
            self.evidence.expect_equal(
                "CHK-JTAG-MON-CALLBACKS",
                monitor.callback_errors,
                0,
                context="reference-model exceptions the scan monitor swallowed",
            )
        super().check_phase()

    # ------------------------------------------------------------------
    # ir_decode: the observation is a TB-interface observable, sampled in
    # the time step the instruction became active.
    # ------------------------------------------------------------------
    def write_ir_decode_expected(self, expected: DtpExpectedItem) -> None:
        try:
            observed = self.tb_if.sample("jtag_ptap_inst_decoded")
        except ValueError:
            self.record_compare(
                DTP_FEATURE_IR_DECODE,
                passed=False,
                expected=f"0x{expected.expected & expected.mask:x}",
                observed="X",
                context=expected.context,
            )
            return
        self.compare_equal(
            DTP_FEATURE_IR_DECODE,
            observed & expected.mask,
            expected.expected & expected.mask,
            expected.context,
        )

    # ------------------------------------------------------------------
    # Pair verdicts.
    # ------------------------------------------------------------------
    def compare_pair(self, feature: str, observed: object, expected: object) -> None:
        if feature in (DTP_FEATURE_IDCODE, DTP_FEATURE_BYPASS):
            self._compare_scan_value(feature, observed, expected)
        else:
            super().compare_pair(feature, observed, expected)

    def _compare_scan_value(self, feature: str, observed: object, expected: object) -> None:
        """The scan's shifted-out bits under the expected mask."""
        if not isinstance(observed, OcahJtagScanItem) or not isinstance(expected, DtpExpectedItem):
            raise TypeError(f"{feature}: unexpected pair {type(observed)}, {type(expected)}")
        if not expected.compare:
            return
        self.compare_equal(
            feature,
            observed.tdo_value & expected.mask,
            expected.expected & expected.mask,
            expected.context,
        )

    # ------------------------------------------------------------------
    # jtag2axi_op: completed single operations against the responder memory.
    # ------------------------------------------------------------------
    def write_op(self, item: DtpJtagItem) -> None:
        if item.op is DtpJtagOp.J2A_WRITE:
            self._check_j2a_write(item)
        elif item.op is DtpJtagOp.J2A_READ:
            self._check_j2a_read(item)

    def _check_j2a_write(self, item: DtpJtagItem) -> None:
        context = (
            f"write addr=0x{item.axi_addr:x} size={item.axi_size} wstrb=0x{item.axi_wstrb:02x}"
        )
        if item.status != DtpJtag2AxiStatus.SUCCESS or self.cfg.axi_ram is None:
            self._record_status(item, context)
            return
        # The TDR data and wstrb fields are the bus lanes of the beat holding
        # the address.
        beat_bytes = get_jtag2axi_target("smc_axi").beat_bytes
        beat_addr = item.axi_addr - item.axi_addr % beat_bytes
        mem = self.cfg.axi_ram.read(beat_addr % self.cfg.axi_mem_size, beat_bytes)
        expected = item.axi_data.to_bytes(beat_bytes, "little")
        lanes = [idx for idx in range(beat_bytes) if (item.axi_wstrb >> idx) & 0x1]
        self.compare_equal(
            JTAG2AXI_OP_FEATURE,
            bytes(mem[idx] for idx in lanes).hex(),
            bytes(expected[idx] for idx in lanes).hex(),
            context,
        )

    def _check_j2a_read(self, item: DtpJtagItem) -> None:
        context = f"read addr=0x{item.axi_addr:x} size={item.axi_size}"
        if item.status != DtpJtag2AxiStatus.SUCCESS or self.cfg.axi_ram is None:
            self._record_status(item, context)
            return
        byte_count = 1 << item.axi_size
        mem = int.from_bytes(
            self.cfg.axi_ram.read(item.axi_addr % self.cfg.axi_mem_size, byte_count), "little"
        )
        # The data field returns the whole beat; the addressed bytes sit on
        # the lanes the address selects.
        lane = item.axi_addr % get_jtag2axi_target("smc_axi").beat_bytes
        rdata = (item.rdata >> (8 * lane)) & ((1 << (8 * byte_count)) - 1)
        self.compare_equal(JTAG2AXI_OP_FEATURE, rdata, mem, context)

    def _record_status(self, item: DtpJtagItem, context: str) -> None:
        self.compare_equal(
            JTAG2AXI_OP_FEATURE,
            DtpJtag2AxiStatus(item.status).name,
            DtpJtag2AxiStatus.SUCCESS.name,
            context,
        )

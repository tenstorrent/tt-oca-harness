# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP scoreboard: always on, in every test, and comparing only.

Every feature is judged on two streams the env wires in ``connect_phase``:
the observed monitor stream and the expected items its
``Dtp<Feature>RefModel`` publishes. The base pairs the two in order per lane
and hands each pair to ``compare_pair()``, which extracts the observed value
from the monitor item and records the verdict; an expected item without a
contract pairs and drops silently, so a reference model can publish one item
per observed item. Expected values never originate here.

  ir_decode        expected: ``DtpIrDecodeRefModel`` on the JTAG event and
                   IR-scan streams. Observed: ``jtag_ptap_inst_decoded``,
                   sampled when the expected item arrives (the cycle the
                   instruction becomes active).
  idcode, bypass   expected: ``DtpIdcodeRefModel``, ``DtpBypassRefModel``.
                   Observed: the reconstructed DR scan's TDO bits.
  xtrig_csr        expected: ``DtpXtrigCsrRefModel``. Observed: the read
  xtrig_decode     data, or the response code, of the XTRIG AXI-Lite
                   monitor's item.
  jtag2axi_req     expected: ``DtpJtag2AxiReqRefModel``, one AXI item per
                   launched bridge transaction on the lane of its port.
                   Observed: the monitor items of the three bridge ports
                   (direction, address, size on AXI4, strobes, and the
                   strobed write data must match; every transaction must have
                   been predicted and every prediction must land). A system
                   or power-on reset withdraws the pending predictions,
                   and a completion while the bridge's lifecycle disable is
                   asserted withdraws the ones queued behind it.
  jtag2axi_status  expected: ``DtpJtag2AxiStatusRefModel``. Observed: the
                   status field, and after a completed read the data field,
                   of the SINGLE_OP or SERIES_CTRL capture.

A required feature (``DtpEnvCfg.required_features``, set by the test) that
ends with zero comparisons fails the run. The scan, XTRIG and bridge-port
monitors swallow a subscriber exception and count it, so the counts are
recorded as ``CHK-JTAG-MON-CALLBACKS``, ``CHK-XTRIG-MON-CALLBACKS`` and
``CHK-J2A-MON-CALLBACKS`` and must be zero. The SV-UVM twin is
``dtp_scoreboard``.
"""

from __future__ import annotations

from collections.abc import Callable

from ocah_axi_vip import OcahAxiItem, OcahAxiProtocol
from ocah_jtag_vip import OcahJtagScanItem
from ocah_lib import OcahScoreboard
from pyuvm import ConfigDB

from .dtp_axi_agent import DtpAxiAgent
from .dtp_expected_item import DtpAnalysisImp, DtpExpectedItem
from .dtp_jtag2axi_model import strobe_lanes
from .dtp_jtag2axi_status_item import DtpJtag2AxiStatusItem
from .dtp_jtag_scan_builder import DtpJtagScanBuilder
from .dtp_types import (
    DTP_FEATURE_BYPASS,
    DTP_FEATURE_IDCODE,
    DTP_FEATURE_IR_DECODE,
    DTP_FEATURE_JTAG2AXI_REQ,
    DTP_FEATURE_JTAG2AXI_STATUS,
    DTP_FEATURE_XTRIG_CSR,
    DTP_FEATURE_XTRIG_DECODE,
    JTAG2AXI_TARGETS,
    DtpJtag2AxiStatus,
)
from .dtp_xtrig_agent import DtpXtrigAgent

__all__ = ["DtpScoreboard"]


class DtpScoreboard(OcahScoreboard):
    def __init__(self, name: str, parent: object) -> None:
        super().__init__(name, parent)
        self.name_tag = "dtp_scoreboard"
        # Set by the env: the components whose monitors feed the reference models.
        self.scan_builder: DtpJtagScanBuilder | None = None
        self.xtrig_agent: DtpXtrigAgent | None = None
        self.axi_agent: DtpAxiAgent | None = None
        # The bridge behind each port monitor (the item `source`).
        self._target_by_source: dict[str, str] = {}
        self._resets_seen = (0, 0)

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        for feature in (
            DTP_FEATURE_IR_DECODE,
            DTP_FEATURE_IDCODE,
            DTP_FEATURE_BYPASS,
            DTP_FEATURE_XTRIG_CSR,
            DTP_FEATURE_XTRIG_DECODE,
            DTP_FEATURE_JTAG2AXI_REQ,
            DTP_FEATURE_JTAG2AXI_STATUS,
        ):
            self.add_feature(feature)
        for feature in sorted(self.cfg.required_features):
            self.require_feature(feature)
        self.ir_decode_expected_export = DtpAnalysisImp(
            "ir_decode_expected_export", self, self.write_ir_decode_expected
        )
        self.jtag2axi_req_observed_export = DtpAnalysisImp(
            "jtag2axi_req_observed_export", self, self.write_jtag2axi_req_observed
        )
        self.jtag2axi_req_expected_export = DtpAnalysisImp(
            "jtag2axi_req_expected_export", self, self.write_jtag2axi_req_expected
        )

    def bind_port(self, target: str, source: str) -> None:
        """Name the monitor whose items carry a bridge's transactions."""
        self._target_by_source[source] = target

    def check_phase(self) -> None:
        jtag = self.scan_builder.monitor if self.scan_builder is not None else None
        xtrig = self.xtrig_agent.monitor if self.xtrig_agent is not None else None
        ports = list(self.axi_agent.port_monitors.values()) if self.axi_agent is not None else []
        for monitor in (xtrig, *ports):
            if monitor is not None:
                monitor.halt()
        self._sync_reset()
        callbacks = (
            ("CHK-JTAG-MON-CALLBACKS", [jtag]),
            ("CHK-XTRIG-MON-CALLBACKS", [xtrig]),
            ("CHK-J2A-MON-CALLBACKS", ports),
        )
        for check_id, monitors in callbacks:
            present = [monitor for monitor in monitors if monitor is not None]
            if present and self.evidence is not None:
                self.evidence.expect_equal(
                    check_id,
                    sum(monitor.callback_errors for monitor in present),
                    0,
                    context="reference-model exceptions the monitors swallowed",
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
    # jtag2axi_req: bridge transactions pair per port; the reference model
    # stamps each prediction with the source of the monitor that will carry it.
    # ------------------------------------------------------------------
    def write_jtag2axi_req_observed(self, item: OcahAxiItem) -> None:
        self._sync_reset()
        self.push_observed(DTP_FEATURE_JTAG2AXI_REQ, item, item.source)
        self._drop_queued_predictions(item.source)

    def write_jtag2axi_req_expected(self, item: OcahAxiItem) -> None:
        self._sync_reset()
        self.push_expected(DTP_FEATURE_JTAG2AXI_REQ, item, item.source)

    # ------------------------------------------------------------------
    # Pair verdicts.
    # ------------------------------------------------------------------
    def compare_pair(self, feature: str, observed: object, expected: object) -> None:
        if feature in (DTP_FEATURE_IDCODE, DTP_FEATURE_BYPASS):
            self._compare_scan_value(feature, observed, expected)
        elif feature == DTP_FEATURE_XTRIG_CSR:
            self._compare_axi(feature, observed, expected, lambda item: item.first_data)
        elif feature == DTP_FEATURE_XTRIG_DECODE:
            self._compare_axi(feature, observed, expected, lambda item: item.resp)
        elif feature == DTP_FEATURE_JTAG2AXI_REQ:
            self._compare_jtag2axi_req(observed, expected)
        elif feature == DTP_FEATURE_JTAG2AXI_STATUS:
            self._compare_jtag2axi_status(observed, expected)
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

    def _compare_axi(
        self,
        feature: str,
        observed: object,
        expected: object,
        extract: Callable[[OcahAxiItem], int],
    ) -> None:
        """One field of the AXI item under the expected mask."""
        if not isinstance(observed, OcahAxiItem) or not isinstance(expected, DtpExpectedItem):
            raise TypeError(f"{feature}: unexpected pair {type(observed)}, {type(expected)}")
        if not expected.compare:
            return
        self.compare_equal(
            feature,
            extract(observed) & expected.mask,
            expected.expected & expected.mask,
            expected.context,
        )

    def _compare_jtag2axi_req(self, observed: object, expected: object) -> None:
        """One verdict per bridge transaction.

        Direction, address, size (AXI4 only; AXI-Lite carries none), one
        beat, and for writes the strobes and the data on the strobed lanes.
        The response code is the AXI recorder's verdict and stays out of it.
        """
        if not isinstance(observed, OcahAxiItem) or not isinstance(expected, OcahAxiItem):
            raise TypeError(f"jtag2axi_req: unexpected pair {type(observed)}, {type(expected)}")
        diff = []
        if expected.direction != observed.direction:
            diff.append("direction")
        if expected.address != observed.address:
            diff.append("address")
        if expected.protocol is OcahAxiProtocol.AXI4 and expected.size != observed.size:
            diff.append("size")
        if observed.beat_count != 1:
            diff.append("beats")
        if expected.is_write:
            strb_e = expected.strobes[0] if expected.strobes else 0
            strb_o = observed.strobes[0] if observed.strobes else 0
            lanes = strobe_lanes(strb_e)
            if strb_e != strb_o:
                diff.append("strobes")
            if (expected.first_data & lanes) != (observed.first_data & lanes):
                diff.append("data")
        self.record_compare(
            DTP_FEATURE_JTAG2AXI_REQ,
            passed=not diff,
            expected=self._request_string(expected),
            observed=self._request_string(observed),
            context=f"port={observed.source}" + (f" mismatch: {' '.join(diff)}" if diff else ""),
        )

    @staticmethod
    def _request_string(item: OcahAxiItem) -> str:
        text = f"{item.direction} addr=0x{item.address:x}"
        if item.protocol is OcahAxiProtocol.AXI4:
            text += f" size={item.size}"
        text += f" beats={item.beat_count}"
        if item.is_write:
            strb = item.strobes[0] if item.strobes else 0
            text += f" strb=0x{strb:02x} data=0x{item.first_data:x}"
        return text

    def _compare_jtag2axi_status(self, observed: object, expected: object) -> None:
        """One verdict per bridge capture: the status field, and the data after an OKAY read."""
        if not isinstance(observed, OcahJtagScanItem) or not isinstance(
            expected, DtpJtag2AxiStatusItem
        ):
            raise TypeError(f"jtag2axi_status: unexpected pair {type(observed)}, {type(expected)}")
        if not expected.compare:
            return
        target = JTAG2AXI_TARGETS[expected.target]
        status = observed.tdo_value & 0x3
        diff = []
        if status != int(expected.status):
            diff.append("status")
        rdata = 0
        if expected.compare_rdata:
            data_off = 2 + target.size_bits + target.wstrb_bits
            rdata = (observed.tdo_value >> data_off) & expected.rdata_mask
            if rdata != expected.rdata & expected.rdata_mask:
                diff.append("rdata")
        observed_text = f"status={DtpJtag2AxiStatus(status).name}"
        if expected.compare_rdata:
            observed_text += f" rdata=0x{rdata:x}"
        self.record_compare(
            DTP_FEATURE_JTAG2AXI_STATUS,
            passed=not diff,
            expected=expected.describe(),
            observed=observed_text,
            context=expected.context + (f" mismatch: {' '.join(diff)}" if diff else ""),
        )

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------
    def _sync_reset(self) -> None:
        """A system or power-on reset aborts the bridge transactions in flight.

        The predictions waiting for them are withdrawn.
        """
        seen = (self.tb_if.sample("sys_rst_assert_count"), self.tb_if.sample("por_assert_count"))
        if seen == self._resets_seen:
            return
        self._resets_seen = seen
        dropped = self.flush_expected(DTP_FEATURE_JTAG2AXI_REQ)
        if dropped:
            self.logger.debug("reset withdrew %d predicted bridge transaction(s)", dropped)

    def _drop_queued_predictions(self, source: str) -> None:
        """A completion while the bridge's disable is asserted drops the requests behind it."""
        target = self._target_by_source.get(source)
        if target is None or not self.tb_if.dbg_field(JTAG2AXI_TARGETS[target].dbg_disable_bit):
            return
        dropped = self.flush_expected(DTP_FEATURE_JTAG2AXI_REQ, source)
        if dropped:
            self.logger.debug(
                "%s: the disable dropped %d queued bridge request(s)", source, dropped
            )

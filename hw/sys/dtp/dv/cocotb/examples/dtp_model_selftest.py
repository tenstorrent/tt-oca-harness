# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simulator-free selftest of the DTP plain models.

Runs as plain Python from ``hw/sys/dtp/dv/cocotb`` with the ``dv`` dependency
group installed and the ``python_paths`` of ``dtp_sim_cfg.toml`` on
``PYTHONPATH`` (``python -m examples.dtp_model_selftest``). It round-trips the
IR and 3DCR tracking model, the iJTAG SIB model, and the composed STAP chain
with and without downstream TAPs, the host segment, and the
ZERO_LENGTH_BYPASS and BYPASS layouts. The run exits non-zero on the first
contract that does not hold.
"""

from __future__ import annotations

import logging
import sys

from env.dtp_dbg_disable import STAP_DISABLE
from env.dtp_ijtag_sib_model import (
    IJTAG_CHAIN_LEN_MAX,
    IJTAG_INSTRUMENT_WIDTHS,
    IJTAG_OBSERVE_SCAN_WIDTH,
    IJTAG_SIB_COUNT,
    SCAN_MARKER_WIDTH,
    DtpIjtagSibModel,
)
from env.dtp_jtag_ir_model import DtpJtagIrModel
from env.dtp_stap_3dcr_model import (
    PTAP_3DCR_WIDTH,
    STAP_3DCR_WIDTH,
    STAP_HOST_SEGMENT_WIDTH,
    STAP_ORDER,
    STAP_SIB_COUNT,
    DtpStap3dcrModel,
    DtpStap3dcrState,
    DtpStapChainFlop,
)
from env.dtp_types import DTP_IR_WIDTH, DtpJtagInstr, DtpScanKind
from ocah_jtag_vip import (
    OcahJtagDevice,
    OcahJtagEvent,
    OcahJtagScanItem,
    OcahJtagState,
    next_jtag_state,
)

LOG = logging.getLogger("dtp_model_selftest")


def _device(name: str, idcode: int) -> OcahJtagDevice:
    """A downstream TAP map: 5-bit IR, IDCODE at 0x01, a 12-bit writable register at 0x02."""
    device = OcahJtagDevice(name=name, idcode=idcode, ir_width=5)
    device.add_reg("IDCODE", 32, 0x01)
    device.add_reg("DS_TDR", 12, 0x02, write=True)
    return device


def _selftest_ir_model() -> None:
    """Drive the model through scripted TMS/TDI streams without a simulator.

    Covers a plain IDCODE-to-BYPASS load, a composed IR scan that leaves the
    active instruction unknown while the shifted value stays known, a
    TAP_3DCR write that sets stap_sel with config_hold so a TMS
    Test-Logic-Reset keeps the select, TRST and power-on reset clearing it,
    and a one-bit TAP_3DCR scan.
    """
    state = {"tap": OcahJtagState.TEST_LOGIC_RESET, "acc": [], "kind": ""}
    model = DtpJtagIrModel()
    model.sync_power_on_reset(0)

    def step(tms: int, tdi: int = 0) -> bool:
        previous = state["tap"]
        if previous in (OcahJtagState.CAPTURE_IR, OcahJtagState.CAPTURE_DR):
            state["acc"] = []
        if previous in (OcahJtagState.SHIFT_IR, OcahJtagState.SHIFT_DR):
            state["acc"].append(tdi)
        nxt = next_jtag_state(previous, tms)
        state["tap"] = nxt
        if (previous, nxt) in (
            (OcahJtagState.SHIFT_IR, OcahJtagState.EXIT1_IR),
            (OcahJtagState.SHIFT_DR, OcahJtagState.EXIT1_DR),
        ):
            bits = state["acc"]
            item = OcahJtagScanItem(
                kind="IR" if previous is OcahJtagState.SHIFT_IR else "DR",
                tdi_value=sum(bit << idx for idx, bit in enumerate(bits)),
                tdo_value=0,
                bit_count=len(bits),
            )
            (model.on_ir_scan if item.is_ir else model.on_dr_scan)(item)
        return model.on_event(OcahJtagEvent(kind="STEP", tms=tms, tdi=tdi))

    def tlr() -> None:
        for _ in range(5):
            step(1)
        step(0)

    def scan(ir: bool, value: int, width: int) -> None:
        # From Run-Test/Idle: Select-DR [, Select-IR], Capture, Shift x width,
        # Exit1, Update, Run-Test/Idle.
        step(1)
        if ir:
            step(1)
        step(0)
        step(0)
        for idx in range(width):
            step(1 if idx == width - 1 else 0, (value >> idx) & 0x1)
        step(1)
        step(0)

    tlr()
    assert model.ir_known() and model.ir() == int(DtpJtagInstr.IDCODE)
    scan(True, int(DtpJtagInstr.BYPASS_3F), DTP_IR_WIDTH)
    assert model.ir_known() and model.ir() == int(DtpJtagInstr.BYPASS_3F)
    # A wider IR scan leaves the instruction unknown, but its last six bits
    # land in the register, so the TAP_3DCR write below is tracked.
    scan(True, int(DtpJtagInstr.TAP_3DCR) << 3, DTP_IR_WIDTH + 3)
    assert not model.ir_known()
    assert model.ptap_select_clear()
    scan(False, 0b110, 3)
    assert not model.ptap_select_clear(), "TAP_3DCR scan should set stap_sel"
    tlr()
    assert not model.ptap_select_clear(), "config_hold keeps the select through a TMS reset"
    model.on_event(OcahJtagEvent(kind="TRST", trst_n=0, trst_asserted=1))
    assert model.ptap_select_clear(), "TRST clears the 3DCR"
    tlr()
    scan(True, int(DtpJtagInstr.TAP_3DCR), DTP_IR_WIDTH)
    scan(False, 0b10, 2)
    assert not model.ptap_select_clear()
    tlr()
    assert model.ptap_select_clear(), "without config_hold a TMS reset clears the select"
    scan(True, int(DtpJtagInstr.TAP_3DCR), DTP_IR_WIDTH)
    scan(False, 0b11, 2)
    model.sync_power_on_reset(1)
    assert model.ptap_select_clear(), "power-on reset clears the 3DCR"
    tlr()
    scan(True, int(DtpJtagInstr.TAP_3DCR), DTP_IR_WIDTH)
    scan(False, 0b1, 1)
    assert not model.ptap_select_clear(), "a one-bit scan sets stap_sel"


def _selftest_ijtag() -> None:
    """Round-trip the SIB model: open a pattern with instrument values,
    predict the next capture, gate one SIB and prove its stored bit
    re-arms on release, and check the marker placement of an observe scan."""
    model = DtpIjtagSibModel()
    assert model.chain_len() == IJTAG_SIB_COUNT
    values = {"dft_secure": 0xA, "dft": 0x15, "dfd": 0x2A}
    # Opening scan: the instruments join the chain after its Update-DR, so
    # the values shifted for them are dropped.
    model.apply_scan(pattern=0b111, inst_values=values)
    assert model.chain_len() == IJTAG_CHAIN_LEN_MAX
    assert all(v == 0 for v in model.instruments.values())
    # Maintain scan with values: every instrument latches its segment.
    width = model.chain_len()
    composed = model.compose_scan(width, inst_values=values)
    assert (composed >> (width - 1)) & 1 == 1  # dft_secure SIB, TDI-nearest
    assert (composed >> (width - 5)) & 0xF == 0xA  # its 4-bit instrument
    model.apply_scan(inst_values=values)
    expected, length = model.expected_capture()
    assert length == width and expected == composed
    # Gate dfd: it captures closed and leaves the chain; the stored bit
    # survives a gated close attempt and re-arms on release.
    gate = {"dfd": 1}
    assert model.chain_len(gate) == IJTAG_CHAIN_LEN_MAX - IJTAG_INSTRUMENT_WIDTHS["dfd"]
    model.apply_scan(pattern=0b110, dbg_disable=gate)
    assert model.stored["dfd"] == 1 and model.effective(gate)["dfd"] == 0
    assert model.effective()["dfd"] == 1
    model.apply_scan(pattern=0)
    assert model.chain_len() == IJTAG_SIB_COUNT
    # Observe-scan marker placement: the chain image sits above the marker.
    marker = 0x8001
    value = (model.compose_scan(IJTAG_SIB_COUNT) << (IJTAG_OBSERVE_SCAN_WIDTH - 3)) | marker
    assert value & ((1 << SCAN_MARKER_WIDTH) - 1) == marker


def _selftest_stap() -> None:
    """Round-trip the composed-chain model with and without downstream TAPs.

    For every STAP, select it, compose a maintain scan, and check that the
    layout, the capture prediction, and the downstream segment slice agree,
    both as a wire loopback and with a device attached (IDCODE, a written
    register, an IR scan, gating, and parking). The iJTAG model round-trips
    first, then the host segment and the ZERO_LENGTH_BYPASS and BYPASS
    layouts.
    """
    _selftest_ijtag()

    width = 64
    for stap in STAP_ORDER:
        for attached in (False, True):
            model = DtpStap3dcrModel()
            if attached:
                model.attach(
                    stap, _device(f"{stap}_ds", 0x1D51_0001 | (STAP_ORDER.index(stap) << 8))
                )
            # With the PTAP select clear the chain holds: a scan that sets the
            # select cannot open a SIB in the same Update-DR.
            assert len(model.chain_layout()) == 2
            model.apply_scan(ptap_select=1, ptap_config_hold=1, sib_en={stap: 1})
            assert not model.sib_en[stap] and len(model.chain_layout()) == 2 + 4
            # Select the STAP: open its SIB, write the payload.
            model.apply_scan(sib_en={stap: 1})
            model.apply_scan(payloads={stap: DtpStap3dcrState(1, 1, 1)})
            layout = model.chain_layout()
            expect_len = 2 + 4 + STAP_3DCR_WIDTH + DtpStap3dcrModel.SPLICE_EXTRA[stap]
            if attached:
                expect_len += 32  # IDCODE selected after reset
            assert len(layout) == expect_len, (stap, attached, len(layout), expect_len)
            expected, care, chain_len = model.expected_capture()
            assert chain_len == len(layout)
            if attached:
                lsb, seg = model.ds_capture_slice(stap)
                assert (
                    seg == 32 and (expected >> lsb) & 0xFFFF_FFFF == model.downstream[stap].idcode
                )
                # IR scan: PTAP IR + chain with the downstream IR segment.
                ir_layout = model.chain_layout(scan_kind=DtpScanKind.IR)
                assert (
                    len(ir_layout)
                    == DTP_IR_WIDTH + 4 + STAP_3DCR_WIDTH + 5 + DtpStap3dcrModel.SPLICE_EXTRA[stap]
                )
                value = model.compose_ir_scan(width, 0x0E, ds_ir={stap: 0x02})
                assert (value >> (width - DTP_IR_WIDTH)) == 0x0E
                model.apply_ir_scan(0x0E, ds_ir={stap: 0x02})
                assert model.downstream[stap].active_ir == 0x02
                # DR write of the 12-bit register round-trips through the slice.
                lsb, seg = model.ds_capture_slice(stap)
                assert seg == 12
                composed = model.compose_scan(width, ds_values={stap: 0xABC})
                layout = model.chain_layout()
                depth0 = next(  # TDI-nearest downstream flop = register MSB
                    d for d, f in enumerate(layout) if f.owner == stap and f.field == "ds"
                )
                assert (composed >> (width - depth0 - 12)) & 0xFFF == 0xABC
                model.apply_scan(ds_values={stap: 0xABC})
                expected, care, chain_len = model.expected_capture()
                assert (expected >> lsb) & 0xFFF == 0xABC
                # Gating parks the downstream (tms_hold=1) on IDCODE and drops it from the chain.
                gate = {STAP_DISABLE[stap]: 1}
                assert not model.spliced_downstream(gate)
                model.apply_scan(dbg_disable=gate)
                assert model.downstream[stap].active_ir == 0x01
                assert model.downstream[stap].values["DS_TDR"] == 0xABC
                # Release: IDCODE is back in the chain.
                lsb, seg = model.ds_capture_slice(stap)
                assert seg == 32
            # Composed maintain scan carries the stored state (MSB TDI-nearest).
            composed = model.compose_scan(width)
            assert (composed >> (width - 1)) & 1 == 1  # PTAP stap_sel
            model.flush_scan()
            assert len(model.chain_layout()) == 2
            model.apply_scan(ptap_select=1)
            assert len(model.chain_layout()) == 2 + 4
    _selftest_host_segment(width)
    _selftest_zlb_bypass(width, _device("smc_ds", 0x1D51_0101))


def _selftest_host_segment(width: int) -> None:
    """The host segment sits at the TDO end while ``stap_host`` is enabled,
    keeps its value through a gated scan, and clears in Test-Logic-Reset."""
    model = DtpStap3dcrModel()
    model.attach_host_segment()
    model.apply_scan(ptap_select=1)
    gate = {STAP_DISABLE["stap_host"]: 1}
    seg_len = STAP_HOST_SEGMENT_WIDTH
    assert len(model.chain_layout()) == PTAP_3DCR_WIDTH + STAP_SIB_COUNT + seg_len
    assert len(model.chain_layout(gate)) == PTAP_3DCR_WIDTH + STAP_SIB_COUNT
    assert (
        len(model.chain_layout(scan_kind=DtpScanKind.IR)) == DTP_IR_WIDTH + STAP_SIB_COUNT + seg_len
    )
    composed = model.compose_scan(width, ptap_select=1, host_segment=0x5A)
    assert (composed >> (width - PTAP_3DCR_WIDTH - STAP_SIB_COUNT - seg_len)) & 0x7F == 0x5A
    model.apply_scan(ptap_select=1, host_segment=0x5A)
    expected, care, chain_len = model.expected_capture()
    assert chain_len == PTAP_3DCR_WIDTH + STAP_SIB_COUNT + seg_len
    assert expected & 0x7F == 0x5A and care & 0x7F == 0x7F
    model.apply_scan(dbg_disable=gate, host_segment=0x11)
    assert model.host_segment == 0x5A
    model.apply_ir_scan(0x0E, host_segment=0x33)
    assert model.host_segment == 0x33
    model.tlr()
    assert model.host_segment == 0


def _selftest_zlb_bypass(width: int, device: OcahJtagDevice) -> None:
    """With the PTAP select set, a data scan under ZERO_LENGTH_BYPASS is the
    BYPASS scan: the bypass register's captured 0 precedes the STAP chain,
    neither reaches the PTAP 3DCR, and the spliced downstream register
    latches the value composed for it. With the select clear neither layout
    holds a chain flop."""
    assert DtpStap3dcrModel().chain_layout(scan_kind=DtpScanKind.ZLB) == []
    model = DtpStap3dcrModel()
    model.attach("smc", device)
    model.apply_scan(ptap_select=1, ptap_config_hold=1)
    model.apply_scan(sib_en={"smc": 1})
    model.apply_scan(payloads={"smc": DtpStap3dcrState(0, 1, 0)})
    model.apply_ir_scan(0x3D, ds_ir={"smc": 0x02})
    zlb = model.chain_layout(scan_kind=DtpScanKind.ZLB)
    chain = model.chain_layout(scan_kind=DtpScanKind.DR)[PTAP_3DCR_WIDTH:]
    assert (
        zlb
        == model.chain_layout(scan_kind=DtpScanKind.BYPASS)
        == [DtpStapChainFlop("ptap", "bypass"), *chain]
    )
    composed = model.compose_scan(width, ds_values={"smc": 0xABC}, scan_kind=DtpScanKind.ZLB)
    depth0 = next(d for d, f in enumerate(zlb) if f.owner == "smc" and f.field == "ds")
    assert (composed >> (width - depth0 - 12)) & 0xFFF == 0xABC
    model.apply_scan(ds_values={"smc": 0xABC})
    assert model.ptap_select == 1 and model.ptap_config_hold == 1
    lsb, seg = model.ds_capture_slice("smc", scan_kind=DtpScanKind.ZLB)
    expected, care, chain_len = model.expected_capture(scan_kind=DtpScanKind.ZLB)
    assert chain_len == len(chain) + 1 and seg == 12 and (expected >> lsb) & 0xFFF == 0xABC
    assert (care >> len(chain)) & 1 == 1 and (expected >> len(chain)) & 1 == 0
    assert model.expected_capture(scan_kind=DtpScanKind.BYPASS) == (expected, care, chain_len)


SELFTESTS = (
    ("ir_model", _selftest_ir_model),
    ("stap_3dcr_model", _selftest_stap),
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    for name, selftest in SELFTESTS:
        selftest()
        LOG.info("%s: PASS", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())

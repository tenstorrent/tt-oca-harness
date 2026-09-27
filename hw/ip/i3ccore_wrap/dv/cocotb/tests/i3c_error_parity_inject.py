# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Error: Parity Injection

Two cocotb tests:

  test_error_status_baseline
      Clean private write: response ERR_STATUS must read exactly 0x0 SUCCESS and no
      transfer-error interrupt may latch. This is the negative control for the error
      path -- it proves the error reporting reads clean when nothing is wrong.

  test_error_parity_inject
      Real bus-level bit-flip injection. A single bit is flipped on the shared SDA
      inside one data byte of an immediate write, which breaks that byte's T-bit
      parity, and the target's TE2 check must fire.

In I3C SDR every data byte is followed by a T-bit which, for a controller->target
write, is the odd parity of that byte. Flipping any single data bit makes the
target's recomputed parity disagree with the transmitted T-bit.

The flip needs a TB hook (`sda_corrupt`, tb_i3ccore.sv) because `sda_shared` is a
continuous assign -- a cocotb deposit on it would be overwritten at the next
evaluation. `sda_corrupt` has no continuous driver, so cocotb can drive it, and it is
XOR-ed into the shared bus.

Two independent checkers validate the result:

  1. TARGET_ERR_CNT_TE2 increments by exactly 1.
  2. The corrupted byte -- and every byte after it in the same transfer -- must NOT
     reach the target RX FIFO because parity_err suppresses RX FIFO writes until the
     target returns idle. Injecting into byte k must leave exactly k bytes received.

Attribution note: te2_err_o = te2_err_ccc | te2_err_priv_wr
so the counter also advances on CCC data-parity errors. No CCC traffic is issued
inside the injection window, so a +1 is attributable to the private write.
"""

import os
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.i3c_api import (
    TTI_ERR_CTRL_TE2_DET_EN_BIT,
    PioIntrStatus,
    TtiQueueStatus,
    TtiTargetErrCtrl,
    build_immediate_write_cmd,
)
from env.i3c_test_base import bring_up_and_assign, make_env

# Authoritative register map (generated) — no hand-copied offsets.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))
import oca_i3c_wrap_reg as _csr  # noqa: E402

WRITE_DATA = [0xDE, 0xAD, 0xBE, 0xEF]
INJECT_BYTE = 2  # flip inside byte 2 -> bytes 0..1 should survive
INJECT_BIT = 0  # which of the 8 data bits of that byte


async def _enable_te2_detection(helper, tgt, log):
    """Set TTI.TARGET_ERR_CTRL.te2_err_det_en and return the read-back bit."""
    reg = TtiTargetErrCtrl()
    reg.val = await helper.read(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TARGET_ERR_CTRL_REG_ADDR)
    reg.f.te2_err_det_en = 1
    await helper.write(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TARGET_ERR_CTRL_REG_ADDR, reg.val)

    back = TtiTargetErrCtrl()
    back.val = await helper.read(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TARGET_ERR_CTRL_REG_ADDR)
    log.info(
        f"TARGET_ERR_CTRL = 0x{back.val:08X} "
        f"(te2_err_det_en bit {TTI_ERR_CTRL_TE2_DET_EN_BIT} = {back.f.te2_err_det_en})"
    )
    return back.f.te2_err_det_en


async def _te2_count(helper, tgt):
    """Return the saturating 8-bit TARGET_ERR_CNT_TE2.CNT field."""
    return (
        await helper.read(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TARGET_ERR_CNT_TE2_REG_ADDR)
    ) & 0xFF


async def _drain_target_rx(helper, tgt, log):
    """Read the target RX descriptor and drain its bytes. Returns (n_bytes, data).

    Returns (None, []) if no descriptor was ever posted, which for the injection leg
    is a legitimate outcome (no byte survived to complete a descriptor).
    """
    ok, _ = await helper.poll_field_clear(
        tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_STATUS_REG_ADDR,
        TtiQueueStatus,
        "rx_desc_queue_empty",
        max_polls=2000,
        interval=10,
    )
    if not ok:
        log.info("  no target RX descriptor was posted")
        return None, []

    desc = await helper.read(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR)
    n = desc & 0xFFFF
    err = (desc >> 20) & 0xFFF
    log.info(f"  target RX descriptor = 0x{desc:08X} (data_length={n}, error={err})")

    data = []
    remaining = n
    while remaining > 0:
        word = await helper.read(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_RX_DATA_PORT_REG_ADDR)
        take = min(4, remaining)
        data.extend(helper.unpack_bytes(word, take))
        remaining -= take
    return n, data


async def _issue_immediate_write(helper, ctrl, data, tid=0):
    """Push an immediate-write command descriptor (no response wait)."""
    cmd_lo, cmd_hi = build_immediate_write_cmd(data, dat_idx=0, tid=tid)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)


async def _wait_response(helper, ctrl, log, max_polls=20000):
    """Wait for resp_ready_stat and return (ok, resp, err_status)."""
    ok, _ = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=max_polls,
        interval=10,
    )
    if not ok:
        log.info("  no controller response descriptor within the poll budget")
        return False, 0, None
    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err = (resp >> 28) & 0xF  # ERR_STATUS [31:28], HCI v1.2 Table 146
    log.info(f"  controller response = 0x{resp:08X} (err_status=0x{err:X})")
    return True, resp, err


async def _inject_bit_flip(dut, byte_index, bit_index, log):
    """Flip one bus bit inside data byte `byte_index` of the next transfer.

    Bit slots after a START on this TB's shared open-drain bus (same counting the
    existing NACK monitor in i3c_error_sanity.py uses):
        edges 1..8 = 7-bit address + RnW,  edge 9 = ACK,
        then every data byte takes 9 edges: 8 data bits + 1 T-bit.
    So data byte b (0-based) has its data bits on edges 9+9b+1 .. 9+9b+8.
    """
    target_edge = 9 + 9 * byte_index + 1 + bit_index

    def bus_scl():
        return int(dut.scl_i.value) & 1

    def bus_sda():
        return int(dut.sda_i.value) & 1

    # Wait for a genuine START: SDA falls while SCL is high.
    prev = bus_sda()
    while True:
        await RisingEdge(dut.clk)
        cur = bus_sda()
        if prev == 1 and cur == 0 and bus_scl() == 1:
            break
        prev = cur

    # Count up to the edge before the targeted bit slot.
    edges = 0
    while edges < target_edge - 1:
        while bus_scl() == 1:
            await RisingEdge(dut.clk)
        while bus_scl() == 0:
            await RisingEdge(dut.clk)
        edges += 1

    # Corrupt for the whole of the next bit slot, so the value sampled on the
    # target rising edge is inverted, then release.
    while bus_scl() == 1:
        await RisingEdge(dut.clk)
    dut.sda_corrupt.value = 1
    while bus_scl() == 0:
        await RisingEdge(dut.clk)
    while bus_scl() == 1:
        await RisingEdge(dut.clk)
    dut.sda_corrupt.value = 0
    log.info(
        f"  injected bit flip at SCL edge {target_edge} (data byte {byte_index}, bit {bit_index})"
    )


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_error_status_baseline(dut):
    """Clean transfer: response ERR_STATUS must read exactly 0x0 SUCCESS."""
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    data = [0xDE, 0xAD, 0xBE, 0xEF]
    ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
    # MIPI I3C HCI v1.2 Table 146 encodes ERR_STATUS in bits [31:28].
    err = (resp >> 28) & 0xF
    tb.log.info(f"baseline write resp=0x{resp:08X} err_status={err}")
    assert ok, f"baseline transfer failed resp=0x{resp:08X}"
    assert err == 0, f"baseline transfer err_status=0x{err:X}, expected 0x0 SUCCESS"
    assert rx == data, f"baseline payload mismatch: got {rx} != sent {data}"

    # No error was injected, so no error interrupt may be latched either.
    await ClockCycles(dut.clk, 50)
    status = await helper.read_into(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
    )
    tb.log.info(f"PIO_INTR_STATUS = 0x{status.val:08X}")
    assert not status.f.transfer_err_stat, (
        f"transfer_err_stat latched on a clean transfer: 0x{status.val:08X}"
    )

    tb.log.info("Error-status baseline verified (err_status=0x0, no transfer error)")


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_error_parity_inject(dut):
    """Flip one bus bit in a data byte; the target's TE2 parity check must fire."""
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # The compare in i3c_target_fsm.sv is gated at the source, so enable TE2 first.
    te2_en = await _enable_te2_detection(helper, tgt, tb.log)
    assert te2_en == 1, (
        "TARGET_ERR_CTRL.te2_err_det_en did not read back as 1; the target parity "
        "check is gated off and no injected error could ever be detected"
    )

    # ---- Leg 1: clean transfer. Sensitivity control for the counter. ----
    tb.log.info("=" * 60)
    tb.log.info("Leg 1: clean immediate write (TE2 counter must NOT move)")
    base_cnt = await _te2_count(helper, tgt)
    tb.log.info(f"  TE2 count before = {base_cnt}")
    assert base_cnt < 0xFF, "TE2 counter is saturated at 0xFF; cannot measure a delta"

    await _issue_immediate_write(helper, ctrl, WRITE_DATA, tid=0)
    got_resp, _resp, err = await _wait_response(helper, ctrl, tb.log)
    assert got_resp, "clean leg: no controller response descriptor"
    assert err == 0, f"clean leg: err_status=0x{err:X}, expected 0x0 SUCCESS"

    n_clean, data_clean = await _drain_target_rx(helper, tgt, tb.log)
    assert n_clean == len(WRITE_DATA), (
        f"clean leg: target received {n_clean} bytes, expected {len(WRITE_DATA)}"
    )
    assert data_clean == WRITE_DATA, f"clean leg: payload mismatch {data_clean} != {WRITE_DATA}"

    clean_cnt = await _te2_count(helper, tgt)
    tb.log.info(f"  TE2 count after clean transfer = {clean_cnt}")
    assert clean_cnt == base_cnt, (
        f"TE2 counter moved on a CLEAN transfer ({base_cnt} -> {clean_cnt}); the "
        f"counter is not a valid parity-error indicator"
    )

    # ---- Leg 2: same transfer with one corrupted data bit. ----
    tb.log.info("=" * 60)
    tb.log.info(f"Leg 2: immediate write with a bit flip in data byte {INJECT_BYTE}")

    injector = cocotb.start_soon(_inject_bit_flip(dut, INJECT_BYTE, INJECT_BIT, tb.log))
    await _issue_immediate_write(helper, ctrl, WRITE_DATA, tid=1)
    got_resp, resp, err = await _wait_response(helper, ctrl, tb.log)
    await injector

    # The injection hook must be back at rest before the next transfer.
    assert int(dut.sda_corrupt.value) == 0, "sda_corrupt left asserted"

    n_bad, data_bad = await _drain_target_rx(helper, tgt, tb.log)
    bad_cnt = await _te2_count(helper, tgt)
    tb.log.info(f"  TE2 count after injection = {bad_cnt}")

    # Checker 1: exactly one byte had bad parity, so exactly one increment.
    assert bad_cnt == clean_cnt + 1, (
        f"TE2 counter went {clean_cnt} -> {bad_cnt}, expected exactly one increment. "
        f"A parity mismatch on data byte {INJECT_BYTE} must raise te2_err_priv_wr "
        f"in i3c_target_fsm, which increments TARGET_ERR_CNT_TE2 in tti."
    )

    # Checker 2: parity_err remains asserted until target idle and suppresses RX FIFO
    # writes, so only the bytes before the corrupted byte may be received.
    expected_rx = WRITE_DATA[:INJECT_BYTE]
    if n_bad is None:
        received = []
    else:
        received = data_bad
    assert received == expected_rx, (
        f"target RX got {received}, expected only the {INJECT_BYTE} byte(s) before the "
        f"corrupted one ({expected_rx}): parity_err latches until idle and gates "
        f"rx_fifo_wvalid_raw, so no byte from the flip onwards may be pushed"
    )

    tb.log.info("=" * 60)
    tb.log.info(
        f"TE2 parity injection verified: count {clean_cnt} -> {bad_cnt}, "
        f"target RX suppressed from byte {INJECT_BYTE} onwards "
        f"(received {received})"
    )

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Write/Read Sanity against an independent VIP target

The VIP-target counterpart of `i3c_write_read_sanity`: SETDASA, a private write,
then a private read, with the bus partner replaced by a cocotb VIP target.
Requires `+i3c_vip_target`, which takes the RTL peer off the shared bus.

This is the control for the substitution itself: it runs the same sequence as the
peer-topology module, so a failure here is the VIP target or its bus wiring rather
than the controller.

The controller sequences are written out here rather than taken from
`i3c_api.I3CController.private_write` / `private_read`, because those drive the RTL
target's TTI registers to move the far side of the transfer, which a Python target
does not have.
"""

import cocotb
import oca_i3c_wrap_reg as _csr
from cocotb.triggers import ClockCycles
from env.i3c_api import PioIntrStatus
from env.i3c_test_base import (
    DEFAULT_DYNAMIC_ADDR,
    DEFAULT_STATIC_ADDR,
    init_controller,
    make_env,
)
from env.i3c_vip_target import VipI3cTarget

BYTES_PER_ENTRY = 4

# Command descriptor DWORD 0 field positions (i3c_pkg.sv regular_trans_dat_desc_t).
RNW_BIT = 29
WROC_BIT = 30
TOC_BIT = 31

POLL_BUDGET = 10000

WRITE_DATA = bytes([0xDE, 0xAD, 0xBE, 0xEF])
READ_DATA = bytes([0x11, 0x22, 0x33, 0x44])


async def _issue_transfer(helper, ctrl, *, length, is_read, dat_idx=0):
    cmd_lo = (dat_idx << 16) | (int(is_read) << RNW_BIT) | (1 << WROC_BIT) | (1 << TOC_BIT)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, length << 16)


async def _await_response(dut, helper, ctrl, what):
    """Poll for the response descriptor and return it decoded."""
    for _ in range(POLL_BUDGET):
        status = await helper.read_into(
            ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
        )
        if status.f.resp_ready_stat:
            resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
            return resp, (resp >> 28) & 0xF, resp & 0xFFFF
        await ClockCycles(dut.clk, 10)

    raise AssertionError(
        f"no response descriptor for the {what} after {POLL_BUDGET} polls: "
        f"last PIO_INTR_STATUS=0x{status.val:08X} "
        f"(tx_thld={status.f.tx_thld_stat}, rx_thld={status.f.rx_thld_stat}, "
        f"transfer_err={status.f.transfer_err_stat}, "
        f"transfer_abort={status.f.transfer_abort_stat})"
    )


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_vip_write_read_sanity(dut):
    """SETDASA, private write, private read, all against the VIP target."""
    tb, helper, ctrl, _tgt = await make_env(dut)

    vip = VipI3cTarget(
        sda_i=dut.sda_shared,
        sda_o=dut.vip_sda_o,
        scl_i=dut.scl_shared,
        scl_o=dut.vip_scl_o,
        static_addr=DEFAULT_STATIC_ADDR,
    )

    await init_controller(ctrl)

    ok, resp = await ctrl.send_setdasa(DEFAULT_STATIC_ADDR, DEFAULT_DYNAMIC_ADDR)
    assert ok, f"SETDASA to the VIP target failed with response 0x{resp:08X}"
    got = await vip.wait_dynamic_addr()
    assert got == DEFAULT_DYNAMIC_ADDR, (
        f"VIP target holds address {got}, expected 0x{DEFAULT_DYNAMIC_ADDR:02X}"
    )
    tb.log.info(f"VIP target holds dynamic address 0x{got:02X}")

    # Private write. The payload is shorter than the TX threshold, so preload it
    # rather than waiting for tx_thld_stat.
    tb.log.info(f"Private write: {WRITE_DATA.hex()}")
    for off in range(0, len(WRITE_DATA), BYTES_PER_ENTRY):
        word = helper.pack_bytes(WRITE_DATA[off : off + BYTES_PER_ENTRY])
        await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_TX_DATA_PORT_REG_ADDR, word)
    await _issue_transfer(helper, ctrl, length=len(WRITE_DATA), is_read=False)

    resp, err_status, resp_len = await _await_response(dut, helper, ctrl, "private write")
    tb.log.info(f"  response=0x{resp:08X} err_status=0x{err_status:X} data_length={resp_len}")
    assert err_status == 0x0, (
        f"private write to the VIP target reported ERR_STATUS 0x{err_status:X}; "
        f"0x5 NACK would mean the VIP did not ACK its dynamic address. "
        f"resp=0x{resp:08X}"
    )
    # For a write, a non-zero DATA_LENGTH means bytes were left unsent.
    assert resp_len == 0, (
        f"private write response DATA_LENGTH={resp_len}, expected 0 "
        f"({len(WRITE_DATA)} bytes were issued)"
    )
    received = vip.received_data()
    assert received == WRITE_DATA, (
        f"VIP target captured {received.hex()}, expected {WRITE_DATA.hex()}"
    )
    tb.log.info(f"  VIP target captured {received.hex()}")

    # Private read.
    tb.log.info(f"Private read: {READ_DATA.hex()}")
    vip.load_read_data(READ_DATA)
    await _issue_transfer(helper, ctrl, length=len(READ_DATA), is_read=True)

    resp, err_status, resp_len = await _await_response(dut, helper, ctrl, "private read")
    tb.log.info(f"  response=0x{resp:08X} err_status=0x{err_status:X} data_length={resp_len}")
    assert err_status == 0x0, (
        f"private read from the VIP target reported ERR_STATUS 0x{err_status:X} "
        f"(resp=0x{resp:08X}, data_length={resp_len})"
    )
    # A short read here would mean the VIP stopped early, not that the DUT is at
    # fault: the payload is exactly the requested length.
    assert resp_len == len(READ_DATA), (
        f"private read response DATA_LENGTH={resp_len}, expected {len(READ_DATA)}"
    )

    # The payload is below the RX threshold, so nothing fires rx_thld_stat and the
    # whole payload is still queued. HCI 6.8.1: drain by DATA_LENGTH.
    rx_data = []
    while len(rx_data) < resp_len:
        word = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR)
        take = min(BYTES_PER_ENTRY, resp_len - len(rx_data))
        rx_data.extend(helper.unpack_bytes(word, take))

    assert bytes(rx_data) == READ_DATA, (
        f"private read payload mismatch: got {bytes(rx_data).hex()}, expected {READ_DATA.hex()}"
    )
    tb.log.info(f"  controller received {bytes(rx_data).hex()}")

    tb.log.info("VIP target verified as a bus partner: SETDASA, private write, private read")

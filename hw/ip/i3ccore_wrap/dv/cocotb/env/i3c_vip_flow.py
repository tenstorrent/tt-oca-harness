# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Controller-side transfer flows for a VIP bus partner.

`I3CController.private_write` / `private_read` move the far side of a transfer by
driving the RTL target's TTI registers, which a Python target does not have. These
are the same controller sequences with the target half handled by the model, and
they keep the `(ok, resp, data)` return shape so a ported test reads like its
peer-topology original.

Requires `+i3c_vip_target`, which takes the RTL peer off the shared bus.
"""

import oca_i3c_wrap_reg as _csr
from cocotb.triggers import ClockCycles

from .i3c_api import PioIntrStatus
from .i3c_test_base import DEFAULT_DYNAMIC_ADDR, DEFAULT_STATIC_ADDR, init_controller
from .i3c_vip_target import VipI3cTarget

BYTES_PER_ENTRY = 4

# Command descriptor DWORD 0 field positions (i3c_pkg.sv regular_trans_dat_desc_t).
RNW_BIT = 29
WROC_BIT = 30
TOC_BIT = 31

POLL_BUDGET = 20000


def attach_vip(dut, static_addr=DEFAULT_STATIC_ADDR):
    """Attach a VIP target to the shared bus. Call after reset is released."""
    return VipI3cTarget(
        sda_i=dut.sda_shared,
        sda_o=dut.vip_sda_o,
        scl_i=dut.scl_shared,
        scl_o=dut.vip_scl_o,
        static_addr=static_addr,
    )


async def bring_up_and_assign(
    dut,
    ctrl,
    *,
    static_addr=DEFAULT_STATIC_ADDR,
    dynamic_addr=DEFAULT_DYNAMIC_ADDR,
    tx_buf=1,
    rx_buf=1,
    vip=None,
):
    """Attach the VIP, initialize the controller, then SETDASA over the bus.

    Returns the VIP target. Pass `vip` to re-initialize the controller against an
    already attached one, which a sweep needs: only one model can drive the bus.
    """
    if vip is None:
        vip = attach_vip(dut, static_addr)

    await init_controller(ctrl, tx_buf=tx_buf, rx_buf=rx_buf)

    ok, resp = await ctrl.send_setdasa(static_addr, dynamic_addr)
    assert ok, f"SETDASA to the VIP target failed with response 0x{resp:08X}"

    got = await vip.wait_dynamic_addr()
    assert got == dynamic_addr, (
        f"VIP target holds address {got}, expected 0x{dynamic_addr:02X}; the "
        "controller reported SETDASA success, so the VIP did not decode the "
        "directed CCC phase"
    )
    return vip


async def _issue(helper, ctrl, *, length, is_read, dat_idx):
    cmd_lo = (dat_idx << 16) | (int(is_read) << RNW_BIT) | (1 << WROC_BIT) | (1 << TOC_BIT)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, length << 16)


async def private_write(dut, helper, ctrl, vip, data, dat_idx=0):
    """Private write to the VIP target. Returns (ok, resp, bytes it captured)."""
    data = list(data)
    data_len = len(data)
    tx_bytes_per_int = (1 << (ctrl.tx_thld + 1)) * BYTES_PER_ENTRY

    ok, _ = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "cmd_queue_ready_stat",
    )
    assert ok, "command queue never reported ready"

    await _issue(helper, ctrl, length=data_len, is_read=False, dat_idx=dat_idx)

    written = 0
    status = None
    for _ in range(POLL_BUDGET):
        status = await helper.read_into(
            ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
        )
        if status.f.resp_ready_stat:
            break
        if written < data_len and status.f.tx_thld_stat:
            chunk = min(tx_bytes_per_int, data_len - written)
            for off in range(0, chunk, BYTES_PER_ENTRY):
                word = helper.pack_bytes(data[written + off : written + off + BYTES_PER_ENTRY])
                await helper.write(
                    ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_TX_DATA_PORT_REG_ADDR, word
                )
            written += chunk
        await ClockCycles(dut.clk, 10)
    else:
        raise AssertionError(
            f"private write: no response descriptor after {POLL_BUDGET} polls "
            f"(tx_written={written}/{data_len}B, "
            f"last PIO_INTR_STATUS=0x{status.val:08X})"
        )

    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    resp_len = resp & 0xFFFF
    if err_status:
        helper.log.info(f"private write: err_status=0x{err_status:X} resp=0x{resp:08X}")
        return False, resp, list(vip.received_data())
    # For a write, a non-zero DATA_LENGTH means bytes were left unsent.
    assert resp_len == 0, (
        f"private write response DATA_LENGTH={resp_len}, expected 0 ({data_len} bytes were issued)"
    )
    return True, resp, list(vip.received_data())


async def private_read(dut, helper, ctrl, vip, tx_data, dat_idx=0):
    """Private read from the VIP target. Returns (ok, resp, bytes received)."""
    tx_data = list(tx_data)
    data_len = len(tx_data)
    rx_entries_per_int = 1 << (ctrl.rx_thld + 1)

    # The model ends the data phase after the last queued byte, so the queue length
    # is what makes the read full-length or short, with no arming step to sequence.
    vip.load_read_data(tx_data)

    await _issue(helper, ctrl, length=data_len, is_read=True, dat_idx=dat_idx)

    rx_data = []
    status = None
    for _ in range(POLL_BUDGET):
        status = await helper.read_into(
            ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
        )
        if status.f.rx_thld_stat:
            for _e in range(rx_entries_per_int):
                word = await helper.read(
                    ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR
                )
                rx_data.extend(helper.unpack_bytes(word, BYTES_PER_ENTRY))
        if status.f.resp_ready_stat:
            break
        await ClockCycles(dut.clk, 10)
    else:
        raise AssertionError(
            f"private read: no response descriptor after {POLL_BUDGET} polls "
            f"(rx_drained={len(rx_data)}/{data_len}B, "
            f"last PIO_INTR_STATUS=0x{status.val:08X})"
        )

    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    resp_len = resp & 0xFFFF
    if err_status:
        helper.log.info(f"private read: err_status=0x{err_status:X} resp=0x{resp:08X}")
        return False, resp, rx_data[:data_len]

    # The threshold-driven drain moves whole rx_entries_per_int batches only, so a
    # sub-threshold tail is still queued. HCI 6.8.1: drain by DATA_LENGTH.
    while len(rx_data) < resp_len:
        word = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR)
        take = min(BYTES_PER_ENTRY, resp_len - len(rx_data))
        rx_data.extend(helper.unpack_bytes(word, take))

    assert resp_len == data_len, (
        f"private read response DATA_LENGTH={resp_len}, expected {data_len}"
    )
    return True, resp, rx_data[:data_len]


async def do_transfer(dut, helper, ctrl, vip, t):
    """Drive an `i3c_rand.I3CTransfer` against the VIP target and self-check."""
    if t.dir == "write":
        ok, resp, rx = await private_write(dut, helper, ctrl, vip, t.data, dat_idx=t.dat_idx)
        assert ok, f"write {t.length}B failed resp=0x{resp:08X}"
        assert rx == t.data, f"write {t.length}B data mismatch"
    else:
        ok, resp, rx = await private_read(dut, helper, ctrl, vip, t.data, dat_idx=t.dat_idx)
        assert ok, f"read {t.length}B failed resp=0x{resp:08X}"
        assert rx == t.data, f"read {t.length}B data mismatch"
    return ok, resp, rx

# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

"""
I3C Error: Target Read Abort  (Test Plan #37)

The controller requests a read of `requested_len` bytes but the target only
supplies `supplied_len < requested_len` bytes. The verification point is that
the controller reports a completed/short read (raises resp_ready_stat) rather
than hanging waiting for the missing bytes.

Constrained-random: both `requested_len` and `supplied_len` are randomized
(shared framework, seed from +seed/SEED/default) under the constraint
`4 <= supplied_len < requested_len`, both dword-aligned, so the short-read /
abort datapath sees a range of (requested, supplied) gaps instead of a single
fixed 8-vs-4 case.

Unlike the previous scaffold, this drives the read command length and the
target TX byte-count *independently* (the `private_read` helper ties them
together, which produces a clean read with no mismatch). The controller
response is polled with a bounded budget; getting a response at all is the
"does not hang" scoreboard.
"""
import cocotb
from cocotb.triggers import ClockCycles
from i3c_test_base import make_env, bring_up_and_assign
from i3c_rand import RandMgr, rand_bytes

from i3c_api import PioIntrStatus
from I3CCSR_reg import (
    PIOCONTROL_COMMAND_PORT_REG_ADDR,
    PIOCONTROL_RESPONSE_PORT_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
    PIOCONTROL_RX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    I3C_EC_TTI_TX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR,
)

BYTES_PER_ENTRY = 4
TTI_TX_DATA_THLD_STAT = (1 << 8)
TTI_TX_DESC_THLD_STAT = (1 << 10)
TTI_TX_DESC_COMPLETE = (1 << 26)


@cocotb.test(timeout_time=4000, timeout_unit='us')
async def test_error_target_abort(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="target_abort")          # seed logged; +seed/SEED override

    # Constraint: 4 <= supplied < requested, both dword-aligned.
    req_entries = r.randint(3, 8)                       # 12 .. 32 bytes requested
    sup_entries = r.randint(1, req_entries - 1)         # strictly fewer supplied
    requested_len = req_entries * BYTES_PER_ENTRY
    supplied_len = sup_entries * BYTES_PER_ENTRY
    tgt_data = rand_bytes(r, supplied_len)
    dat_idx = 0

    tb.log.info(f"Short read: controller requests {requested_len}B, "
                f"target supplies {supplied_len}B")

    # Issue read command for the *requested* length (rnw=1, wroc=1, toc=1)
    cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 30) | (1 << 31)
    cmd_hi = requested_len << 16
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Wait for target TX descriptor queue space, then tell the target to supply
    # only `supplied_len` bytes (deliberately fewer than requested).
    for _ in range(1000):
        tgt_status = await helper.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
        if tgt_status & TTI_TX_DESC_THLD_STAT:
            break
        await ClockCycles(dut.clk, 10)
    await helper.write(tgt.base + I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR,
                       supplied_len << 16)

    bytes_written = 0
    bytes_read = 0
    rx_data = []
    rx_entries_per_int = 1 << (ctrl.rx_thld + 1)

    # Bounded loop: fill the (short) target data, drain controller RX, and wait
    # for the controller response. The bound is the "does not hang" guarantee.
    got_resp = False
    for _ in range(20000):
        tgt_status = await helper.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)

        if bytes_written < supplied_len and (tgt_status & TTI_TX_DATA_THLD_STAT):
            chunk = min(BYTES_PER_ENTRY * rx_entries_per_int, supplied_len - bytes_written)
            for i in range(0, chunk, BYTES_PER_ENTRY):
                word = helper.pack_bytes(
                    tgt_data[bytes_written + i:bytes_written + i + BYTES_PER_ENTRY])
                await helper.write(tgt.base + I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word)
            bytes_written += chunk

        ctrl_status = await helper.read_into(
            ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus)
        if ctrl_status.f.rx_thld_stat:
            for _e in range(rx_entries_per_int):
                word = await helper.read(ctrl.base + PIOCONTROL_RX_DATA_PORT_REG_ADDR)
                rx_data.extend(helper.unpack_bytes(word, BYTES_PER_ENTRY))
                bytes_read += BYTES_PER_ENTRY
        if ctrl_status.f.resp_ready_stat:
            got_resp = True
            break

        await ClockCycles(dut.clk, 10)

    # Verification point: the controller must NOT hang — it reports a response.
    assert got_resp, (f"Controller hung on short read "
                      f"(requested={requested_len}, supplied={supplied_len})")

    resp = await helper.read(ctrl.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    resp_len = resp & 0xFFFF
    tb.log.info(f"short read result: resp=0x{resp:08X} err_status={err_status} "
                f"data_length={resp_len} rx_drained={bytes_read}B")

    tb.log.info(f"Target read-abort test complete (seed=0x{r.seed:08X})")

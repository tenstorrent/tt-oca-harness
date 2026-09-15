# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Error: Target Read Abort

The controller requests `requested_len` bytes but the target only supplies
`supplied_len < requested_len` and then ends the data phase with its T-bit. Both
values of the command descriptor's SRE field are exercised, because SRE is what
decides whether that short receive is an error:

  test_short_read_permitted   sre=0 -> a short read is PERMITTED, so per MIPI I3C
                              HCI v1.2 Table 146 the outcome is a response with
                              ERR_STATUS 0x0 SUCCESS and DATA_LENGTH equal to the
                              RECEIVED length. DATA_LENGTH is how software learns
                              the read was short.

  test_short_read_error       sre=1 -> a short read is NOT permitted, so the same
                              stimulus must yield ERR_STATUS 0x7
                              I3C_SHORT_READ_ERR.

A response is mandatory in BOTH cases. HCI v1.2 §PIO Mode: "Response Descriptor
structures shall be generated for all Command Descriptors with field WROC having a
value of 1'b1, for all Direct Read or Direct GET CCCs (i.e., as with any Read-type
transfer), or when the transfer phase encountered an error" -- this command sets
wroc=1 and is a read, so either clause alone requires one. The only exemption from
the 1:1 command/response mapping is successful *Write*-type transfers.

Constrained-random: `requested_len` and `supplied_len` are randomized (shared
framework, seed from +seed/SEED/default) with `supplied < requested`, both
dword-aligned, so the short-read datapath sees a range of gaps.

The read command length and target TX byte count are driven independently. A bounded
response poll checks completion, and the response status and received length
distinguish a short read from an address NACK.
"""

import cocotb
import oca_i3c_wrap_reg as _csr
from cocotb.triggers import ClockCycles
from env.i3c_api import PioIntrStatus, TtiQueueStatus
from env.i3c_rand import RandMgr, rand_bytes
from env.i3c_test_base import bring_up_and_assign, make_env

BYTES_PER_ENTRY = 4
TTI_TX_DATA_THLD_STAT = 1 << 8
TTI_TX_DESC_COMPLETE = 1 << 26

# Command descriptor DWORD 0 field positions (i3c_pkg.sv regular_trans_dat_desc_t).
SRE_BIT = 24  # iff 0 permits short reads
RNW_BIT = 29
WROC_BIT = 30
TOC_BIT = 31

POLL_BUDGET = 20000


async def _drive_short_read(dut, tb, helper, ctrl, tgt, r, sre):
    """Create a genuine short read with the given SRE, and observe the outcome.

    Asserts only on harness preconditions (target arming). The DUT's response is
    returned, never judged here, so each test states its own expectation.
    """
    # Controller RX threshold, in entries and bytes. bring_up_and_assign uses
    # rx_buf=1, so rx_thld_stat only fires at 1 << (1+1) = 4 entries = 16 bytes.
    rx_entries_per_int = 1 << (ctrl.rx_thld + 1)

    # Constraint: supplied >= the RX threshold, and supplied < requested, both
    # dword-aligned. supplied must reach the threshold or rx_thld_stat can never fire
    # and the drain below is unreachable -- a property of the TB's threshold config,
    # not of the DUT, which would otherwise look like the DUT delivering nothing. The
    # spec warns about exactly this hazard: the last data DWORD of a read "might never
    # reach the threshold and therefore not trigger the RX_THLD_STAT interrupt",
    # "especially pertinent for very short Read transfers".
    sup_entries = r.randint(rx_entries_per_int, rx_entries_per_int + 3)
    req_entries = sup_entries + r.randint(1, 4)  # strictly more requested
    requested_len = req_entries * BYTES_PER_ENTRY
    supplied_len = sup_entries * BYTES_PER_ENTRY
    tgt_data = rand_bytes(r, supplied_len)
    dat_idx = 0

    tb.log.info(
        f"Short read (sre={sre}): controller requests {requested_len}B, "
        f"target supplies {supplied_len}B"
    )

    # Arm the target before issuing the read because an empty TX queue causes an
    # address NACK. Poll QUEUE_STATUS because TX_DESC_THLD_STAT is not a reliable
    # readiness indication.
    ok, _qs = await helper.poll_field_clear(
        tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_STATUS_REG_ADDR,
        TtiQueueStatus,
        "tx_desc_queue_full",
        max_polls=1000,
        interval=10,
    )
    assert ok, (
        "target TX descriptor queue never freed (tx_desc_queue_full never cleared "
        f"in 1000 polls, supplied_len={supplied_len})"
    )

    # Tell the target to supply only `supplied_len` bytes (fewer than requested).
    await helper.write(
        tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR, supplied_len << 16
    )

    bytes_written = 0
    bytes_read = 0
    rx_data = []

    # Pre-fill the whole short payload before the command so arming wins the race
    # deterministically; anything left over streams in the loop below.
    while bytes_written < supplied_len:
        qs = await helper.read_into(
            tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_STATUS_REG_ADDR, TtiQueueStatus
        )
        if qs.f.tx_data_queue_full:
            break
        word = helper.pack_bytes(tgt_data[bytes_written : bytes_written + BYTES_PER_ENTRY])
        await helper.write(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word)
        bytes_written += min(BYTES_PER_ENTRY, supplied_len - bytes_written)
    tb.log.info(f"  armed target: {bytes_written}/{supplied_len}B pre-filled")

    # Issue the read command for the *requested* length.
    cmd_lo = (
        (0x0 << 0)
        | (dat_idx << 16)
        | (sre << SRE_BIT)
        | (1 << RNW_BIT)
        | (1 << WROC_BIT)
        | (1 << TOC_BIT)
    )
    cmd_hi = requested_len << 16
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Bounded loop: top up target TX, drain controller RX, wait for the response.
    # The bound is the "does not hang" guarantee.
    got_resp = False
    polls = 0
    tgt_status = 0
    ctrl_status = None
    for _ in range(POLL_BUDGET):
        polls += 1
        tgt_status = await helper.read(
            tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR
        )

        if bytes_written < supplied_len and (tgt_status & TTI_TX_DATA_THLD_STAT):
            chunk = min(BYTES_PER_ENTRY * rx_entries_per_int, supplied_len - bytes_written)
            for i in range(0, chunk, BYTES_PER_ENTRY):
                word = helper.pack_bytes(
                    tgt_data[bytes_written + i : bytes_written + i + BYTES_PER_ENTRY]
                )
                await helper.write(
                    tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word
                )
            bytes_written += chunk

        ctrl_status = await helper.read_into(
            ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
        )
        if ctrl_status.f.rx_thld_stat:
            for _e in range(rx_entries_per_int):
                word = await helper.read(
                    ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR
                )
                rx_data.extend(helper.unpack_bytes(word, BYTES_PER_ENTRY))
                bytes_read += BYTES_PER_ENTRY
        if ctrl_status.f.resp_ready_stat:
            got_resp = True
            break

        await ClockCycles(dut.clk, 10)

    obs = {
        "sre": sre,
        "requested_len": requested_len,
        "supplied_len": supplied_len,
        "tgt_data": tgt_data,
        "got_resp": got_resp,
        "polls": polls,
        "bytes_written": bytes_written,
        "bytes_read": bytes_read,
        "rx_data": rx_data,
        "tgt_status": tgt_status,
        "ctrl_status": ctrl_status,
        "resp": None,
        "err_status": None,
        "resp_len": None,
    }

    if got_resp:
        resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        obs["resp"] = resp
        obs["err_status"] = (resp >> 28) & 0xF  # ERR_STATUS [31:28], Table 146
        obs["resp_len"] = resp & 0xFFFF
        tb.log.info(
            f"  response=0x{resp:08X} err_status=0x{obs['err_status']:X} "
            f"data_length={obs['resp_len']} rx_drained={bytes_read}B"
        )

    return obs


def _no_response_diag(o):
    """Last-state diagnostics: distinguishes 'data moved, response missing' from
    'nothing ever moved on the bus'."""
    c = o["ctrl_status"]
    if c is None:
        return "the service loop never executed"
    return (
        f"after {o['polls']} polls: "
        f"target_tx_written={o['bytes_written']}/{o['supplied_len']}B, "
        f"ctrl_rx_drained={o['bytes_read']}B, "
        f"last TTI_INTERRUPT_STATUS=0x{o['tgt_status']:08X} "
        f"(tx_desc_complete={(o['tgt_status'] >> 26) & 1}), "
        f"last PIO_INTR_STATUS=0x{c.val:08X} "
        f"(rx_thld={c.f.rx_thld_stat}, resp_ready={c.f.resp_ready_stat}, "
        f"transfer_err={c.f.transfer_err_stat}, "
        f"transfer_abort={c.f.transfer_abort_stat})"
    )


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_short_read_permitted(dut):
    """sre=0: a short read is permitted -> SUCCESS with the RECEIVED DATA_LENGTH."""
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="target_abort_sre0")

    o = await _drive_short_read(dut, tb, helper, ctrl, tgt, r, sre=0)

    # The controller must not hang: a response descriptor is mandatory for a
    # read-type transfer with wroc=1 (HCI PIO Mode), and sre=0 does not exempt it.
    assert o["got_resp"], (
        f"no response descriptor for a permitted short read "
        f"(requested={o['requested_len']}, supplied={o['supplied_len']}), " + _no_response_diag(o)
    )

    # Getting *a* response is not the scenario: an address NACK satisfies got_resp
    # exactly as well as a real short read, so check the outcome exactly.
    assert o["err_status"] == 0x0, (
        f"expected ERR_STATUS 0x0 SUCCESS for a permitted short read (sre=0), got "
        f"0x{o['err_status']:X}; 0x5 NACK would mean the target was not armed before "
        f"the command and no data moved. resp=0x{o['resp']:08X}"
    )
    # Table 146: for a read, DATA_LENGTH is the RECEIVED length -- this is how
    # software learns the read came up short.
    assert o["resp_len"] == o["supplied_len"], (
        f"response DATA_LENGTH {o['resp_len']} != {o['supplied_len']} bytes the target "
        f"supplied (requested {o['requested_len']})"
    )

    # Final drain: the threshold-driven drain can only move whole rx_entries_per_int
    # batches, so a sub-threshold tail is still queued. HCI 6.8.1: use DATA_LENGTH.
    bytes_read, rx_data = o["bytes_read"], o["rx_data"]
    while bytes_read < o["resp_len"]:
        word = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR)
        take = min(BYTES_PER_ENTRY, o["resp_len"] - bytes_read)
        rx_data.extend(helper.unpack_bytes(word, take))
        bytes_read += take

    # Zero observed bytes is a fail, never a pass.
    assert bytes_read == o["supplied_len"], (
        f"controller delivered {bytes_read}B, expected {o['supplied_len']}B"
    )
    assert rx_data[: o["supplied_len"]] == list(o["tgt_data"]), (
        f"short-read payload mismatch: got "
        f"{[f'0x{b:02X}' for b in rx_data[: o['supplied_len']]]} != "
        f"sent {[f'0x{b:02X}' for b in o['tgt_data']]}"
    )

    tb.log.info(f"Permitted short read verified (seed=0x{r.seed:08X})")


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_short_read_error(dut):
    """sre=1: a short read is NOT permitted -> ERR_STATUS 0x7 I3C_SHORT_READ_ERR."""
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="target_abort_sre1")

    o = await _drive_short_read(dut, tb, helper, ctrl, tgt, r, sre=1)

    assert o["got_resp"], (
        f"no response descriptor for a short read with sre=1 "
        f"(requested={o['requested_len']}, supplied={o['supplied_len']}), " + _no_response_diag(o)
    )
    # Table 146: 0x7 I3C_SHORT_READ_ERR is defined as the target returning fewer bytes
    # than requested "of a Transfer Command that did not permit a 'short' read" --
    # which is exactly sre=1.
    assert o["err_status"] == 0x7, (
        f"expected ERR_STATUS 0x7 I3C_SHORT_READ_ERR for sre=1, got "
        f"0x{o['err_status']:X} (resp=0x{o['resp']:08X}, "
        f"data_length={o['resp_len']}, rx_drained={o['bytes_read']}B)"
    )

    tb.log.info(f"Short-read error reporting verified (seed=0x{r.seed:08X})")

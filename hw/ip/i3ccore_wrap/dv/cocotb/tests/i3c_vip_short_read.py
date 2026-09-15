# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Short Read against an independent VIP target

Same stimulus and same expectations as `i3c_error_target_abort`, with the bus
partner replaced by a cocotb VIP target instead of a second instance of the RTL
under test. Requires `+i3c_vip_target`, which takes the RTL peer off the shared
bus so the VIP is the only responder.

The point of the pairing is attribution. In the peer topology both sides of a
short read are produced by the same vendored RTL, so a missing response
descriptor cannot be pinned to the controller. Here the short read is generated
by a model: the VIP queues fewer bytes than the controller requests and ends the
data phase with its own T-bit.

  sre=0   a short read is PERMITTED, so per MIPI I3C HCI v1.2 Table 146 the outcome
          is a response with ERR_STATUS 0x0 SUCCESS and DATA_LENGTH equal to the
          RECEIVED length. DATA_LENGTH is how software learns the read was short.

  sre=1   a short read is NOT permitted, so the same stimulus must yield ERR_STATUS
          0x7 I3C_SHORT_READ_ERR.

A response is mandatory in BOTH cases. HCI v1.2 §PIO Mode: "Response Descriptor
structures shall be generated for all Command Descriptors with field WROC having a
value of 1'b1, for all Direct Read or Direct GET CCCs (i.e., as with any Read-type
transfer), or when the transfer phase encountered an error" -- this command sets
wroc=1 and is a read, so either clause alone requires one. The only exemption from
the 1:1 command/response mapping is successful *Write*-type transfers.
"""

import cocotb
import oca_i3c_wrap_reg as _csr
from cocotb.triggers import ClockCycles
from env.i3c_api import PioIntrStatus
from env.i3c_rand import RandMgr, rand_bytes
from env.i3c_test_base import (
    DEFAULT_DYNAMIC_ADDR,
    DEFAULT_STATIC_ADDR,
    init_controller,
    make_env,
)
from env.i3c_vip_target import VipI3cTarget

BYTES_PER_ENTRY = 4

# Command descriptor DWORD 0 field positions (i3c_pkg.sv regular_trans_dat_desc_t).
SRE_BIT = 24  # iff 0 permits short reads
RNW_BIT = 29
WROC_BIT = 30
TOC_BIT = 31

POLL_BUDGET = 20000


async def _bring_up_vip(
    dut, tb, ctrl, static_addr=DEFAULT_STATIC_ADDR, dynamic_addr=DEFAULT_DYNAMIC_ADDR
):
    """Attach the VIP target, then assign it a dynamic address over the bus."""
    vip = VipI3cTarget(
        sda_i=dut.sda_shared,
        sda_o=dut.vip_sda_o,
        scl_i=dut.scl_shared,
        scl_o=dut.vip_scl_o,
        static_addr=static_addr,
    )

    await init_controller(ctrl)

    ok, resp = await ctrl.send_setdasa(static_addr, dynamic_addr)
    assert ok, f"SETDASA to the VIP target failed with response 0x{resp:08X}"

    got = await vip.wait_dynamic_addr()
    assert got == dynamic_addr, (
        f"VIP target holds address {got}, expected 0x{dynamic_addr:02X}; the controller "
        "reported SETDASA success, so the VIP did not decode the directed CCC phase"
    )
    tb.log.info(f"VIP target holds dynamic address 0x{vip.dynamic_addr:02X}")
    return vip


def _pick_lengths(ctrl, r):
    """Pick one (requested, supplied) pair, shared by both SRE runs.

    Constraint: supplied >= the RX threshold, and supplied < requested, both
    dword-aligned. supplied must reach the threshold or rx_thld_stat can never fire
    and the drain is unreachable -- a property of the TB's threshold config, not of
    the DUT. The spec warns about exactly this hazard: the last data DWORD of a read
    "might never reach the threshold and therefore not trigger the RX_THLD_STAT
    interrupt", "especially pertinent for very short Read transfers".
    """
    # Controller RX threshold, in entries. init_controller uses rx_buf=1, so
    # rx_thld_stat only fires at 1 << (1+1) = 4 entries = 16 bytes.
    rx_entries_per_int = 1 << (ctrl.rx_thld + 1)
    sup_entries = r.randint(rx_entries_per_int, rx_entries_per_int + 3)
    req_entries = sup_entries + r.randint(1, 4)  # strictly more requested
    return req_entries * BYTES_PER_ENTRY, sup_entries * BYTES_PER_ENTRY


async def _drive_short_read(dut, tb, helper, ctrl, vip, r, sre, requested_len, supplied_len):
    """Create a genuine short read with the given SRE, and observe the outcome.

    Asserts only on harness preconditions. The DUT's response is returned, never
    judged here, so the caller states the expectation.
    """
    rx_entries_per_int = 1 << (ctrl.rx_thld + 1)
    tgt_data = rand_bytes(r, supplied_len)
    dat_idx = 0

    tb.log.info(
        f"Short read (sre={sre}): controller requests {requested_len}B, "
        f"VIP target supplies {supplied_len}B"
    )

    # Queue the whole short payload up front. The VIP terminates the data phase
    # after the last queued byte, so no mid-transfer top-up is needed and there is
    # no arming race for the address phase to lose.
    vip.load_read_data(tgt_data)

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

    # Bounded loop: drain controller RX and wait for the response. The bound is the
    # "does not hang" guarantee.
    got_resp = False
    polls = 0
    bytes_read = 0
    rx_data = []
    ctrl_status = None
    for _ in range(POLL_BUDGET):
        polls += 1
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
        "bytes_read": bytes_read,
        "rx_data": rx_data,
        "ctrl_status": ctrl_status,
        "vip_state": vip.state,
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
        f"ctrl_rx_drained={o['bytes_read']}B of {o['supplied_len']}B supplied, "
        f"VIP target state={o['vip_state']!r}, "
        f"last PIO_INTR_STATUS=0x{c.val:08X} "
        f"(rx_thld={c.f.rx_thld_stat}, resp_ready={c.f.resp_ready_stat}, "
        f"transfer_err={c.f.transfer_err_stat}, "
        f"transfer_abort={c.f.transfer_abort_stat})"
    )


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_short_read_reporting_vip(dut):
    """Both SRE values against one VIP target, sre=1 checked first.

    A single test, because the VIP target attaches to the shared bus for the whole
    simulation and a second instance would contend with the first. Both stimuli run
    before any assertion, so a missing sre=0 response still yields the sre=1 result
    that tells us whether the topology itself works.
    """
    tb, helper, ctrl, _tgt = await make_env(dut)
    vip = await _bring_up_vip(dut, tb, ctrl)
    r = RandMgr(name="vip_short_read")

    # One length pair for both runs. SRE lives in the command descriptor and never
    # reaches the bus, so with the lengths held fixed the target's behaviour is
    # identical across the two runs and SRE is the only variable.
    requested_len, supplied_len = _pick_lengths(ctrl, r)

    err = await _drive_short_read(dut, tb, helper, ctrl, vip, r, 1, requested_len, supplied_len)
    permitted = await _drive_short_read(
        dut, tb, helper, ctrl, vip, r, 0, requested_len, supplied_len
    )

    # sre=1 first: it is the reference path. If short-read detection reports here and
    # sre=0 does not, the gap is in reporting, not in the model driving the bus.
    assert err["got_resp"], (
        f"no response descriptor for a short read with sre=1 "
        f"(requested={err['requested_len']}, supplied={err['supplied_len']}), "
        + _no_response_diag(err)
    )
    # Table 146: 0x7 I3C_SHORT_READ_ERR is defined as the target returning fewer bytes
    # than requested "of a Transfer Command that did not permit a 'short' read" --
    # which is exactly sre=1.
    assert err["err_status"] == 0x7, (
        f"expected ERR_STATUS 0x7 I3C_SHORT_READ_ERR for sre=1, got "
        f"0x{err['err_status']:X} (resp=0x{err['resp']:08X}, "
        f"data_length={err['resp_len']}, rx_drained={err['bytes_read']}B)"
    )
    tb.log.info("sre=1 short-read error reporting verified against the VIP target")

    # The controller must not hang: a response descriptor is mandatory for a
    # read-type transfer with wroc=1 (HCI PIO Mode), and sre=0 does not exempt it.
    assert permitted["got_resp"], (
        f"no response descriptor for a permitted short read "
        f"(requested={permitted['requested_len']}, "
        f"supplied={permitted['supplied_len']}), " + _no_response_diag(permitted)
    )

    # Getting *a* response is not the scenario: an address NACK satisfies got_resp
    # exactly as well as a real short read, so check the outcome exactly.
    assert permitted["err_status"] == 0x0, (
        f"expected ERR_STATUS 0x0 SUCCESS for a permitted short read (sre=0), got "
        f"0x{permitted['err_status']:X}; 0x5 NACK would mean the VIP target did not "
        f"ACK its dynamic address. resp=0x{permitted['resp']:08X}"
    )
    # Table 146: for a read, DATA_LENGTH is the RECEIVED length -- this is how
    # software learns the read came up short.
    assert permitted["resp_len"] == permitted["supplied_len"], (
        f"response DATA_LENGTH {permitted['resp_len']} != "
        f"{permitted['supplied_len']} bytes the VIP target supplied "
        f"(requested {permitted['requested_len']})"
    )

    # Final drain: the threshold-driven drain can only move whole rx_entries_per_int
    # batches, so a sub-threshold tail is still queued. HCI 6.8.1: use DATA_LENGTH.
    bytes_read, rx_data = permitted["bytes_read"], permitted["rx_data"]
    while bytes_read < permitted["resp_len"]:
        word = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR)
        take = min(BYTES_PER_ENTRY, permitted["resp_len"] - bytes_read)
        rx_data.extend(helper.unpack_bytes(word, take))
        bytes_read += take

    # Zero observed bytes is a fail, never a pass.
    assert bytes_read == permitted["supplied_len"], (
        f"controller delivered {bytes_read}B, expected {permitted['supplied_len']}B"
    )
    assert rx_data[: permitted["supplied_len"]] == list(permitted["tgt_data"]), (
        f"short-read payload mismatch: got "
        f"{[f'0x{b:02X}' for b in rx_data[: permitted['supplied_len']]]} != "
        f"sent {[f'0x{b:02X}' for b in permitted['tgt_data']]}"
    )

    tb.log.info(f"Both SRE paths verified against the VIP target (seed=0x{r.seed:08X})")

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: a mismatching returned ID is distinguishable.

Wire-level proof on the t_axi bundle: the test drives the request channels by
hand against the shared fault slave with one-shot response-ID corruption
armed, and observes BID/RID with the same ``OcahAxiIdCapture`` primitive the
blocking result API uses.  The corrupted response ID must come back as
``issued ^ mask`` — never the issued ID — while the data path stays intact,
and the very next transaction must match again (one-shot).

A cocotbext backend master cannot sit on this bundle: it polices response-ID
pairing and fails on an ID it never issued, which is why the corrupted
transactions are driven at wire level (see ``ocah_axi_vip_harness``).
"""

from __future__ import annotations

import logging
import random

import cocotb
from ocah_axi_vip import OcahAxiIdCapture
from ocah_axi_vip_harness import (
    ID_MASK,
    build_wire_slave,
    drive_wire_read,
    drive_wire_write,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_id_mismatch_test")

RESP_OKAY = 0


def _bid_capture(dut) -> OcahAxiIdCapture:
    return OcahAxiIdCapture(
        clock=dut.clk,
        valid=dut.t_axi_bvalid,
        ready=dut.t_axi_bready,
        id_signal=dut.t_axi_bid,
        last=None,
        log=log,
        label="t_axi BID",
    )


def _rid_capture(dut) -> OcahAxiIdCapture:
    return OcahAxiIdCapture(
        clock=dut.clk,
        valid=dut.t_axi_rvalid,
        ready=dut.t_axi_rready,
        id_signal=dut.t_axi_rid,
        last=dut.t_axi_rlast,
        log=log,
        label="t_axi RID",
    )


@cocotb.test()
async def ocah_axi_id_mismatch_test(dut) -> None:
    await start_clock_reset(dut)
    slave = build_wire_slave(dut)

    addr = random.randrange(0, 2**14) & ~0x3
    data = random.getrandbits(32)

    # Baseline write: uncorrupted responder echoes the issued AWID.
    awid = random.randrange(256)
    capture = _bid_capture(dut)
    resp = await drive_wire_write(dut, awid=awid, addr=addr, data=data)
    observed = await capture.finish()
    log.info("baseline write: issued=0x%02x observed=%s resp=%d", awid, observed, resp)
    assert resp == RESP_OKAY and observed == awid

    # Armed one-shot BID corruption over several random masks: each returned
    # ID differs from the issued one by exactly the armed mask, the data path
    # is untouched, and the following unarmed write matches again (one-shot).
    data2 = random.getrandbits(32)
    addr2 = (addr + 0x100) & ~0x3
    for round_index in range(3):
        mask = random.randrange(1, 256)
        slave.sequence.inject_id_corruption(mask=mask, write=True, read=False)
        awid = random.randrange(256)
        data2 = random.getrandbits(32)
        capture = _bid_capture(dut)
        resp = await drive_wire_write(dut, awid=awid, addr=addr2, data=data2)
        observed = await capture.finish()
        expected = (awid ^ mask) & ID_MASK
        log.info(
            "corrupted write %d: issued=0x%02x mask=0x%02x observed=%s expected=0x%02x",
            round_index,
            awid,
            mask,
            observed,
            expected,
        )
        assert resp == RESP_OKAY
        assert observed is not None, "BID capture miss on the corrupted write"
        assert observed == expected, (
            f"round {round_index}: BID {observed:#x} != issued^mask {expected:#x}"
        )
        assert observed != awid, "corrupted BID must be distinguishable from the issued AWID"
        backdoor = slave.sequence.read32(addr2)
        assert backdoor == data2, "ID corruption must not disturb the write data path"

        # One-shot: the next write matches again without any disarm call.
        awid = random.randrange(256)
        capture = _bid_capture(dut)
        resp = await drive_wire_write(dut, awid=awid, addr=addr, data=data)
        observed = await capture.finish()
        assert resp == RESP_OKAY and observed == awid, (
            f"round {round_index}: BID corruption must be one-shot"
        )

    # Baseline read: uncorrupted responder echoes the issued ARID.
    arid = random.randrange(256)
    capture = _rid_capture(dut)
    resp, rdata = await drive_wire_read(dut, arid=arid, addr=addr)
    observed = await capture.finish()
    log.info("baseline read: issued=0x%02x observed=%s rdata=0x%08x", arid, observed, rdata)
    assert resp == RESP_OKAY and rdata == data and observed == arid

    # Armed one-shot RID corruption over several random masks, sampled on the
    # completing beat; each following unarmed read matches again (one-shot).
    for round_index in range(3):
        mask = random.randrange(1, 256)
        slave.sequence.inject_id_corruption(mask=mask, write=False, read=True)
        arid = random.randrange(256)
        capture = _rid_capture(dut)
        resp, rdata = await drive_wire_read(dut, arid=arid, addr=addr2)
        observed = await capture.finish()
        expected = (arid ^ mask) & ID_MASK
        log.info(
            "corrupted read %d: issued=0x%02x mask=0x%02x observed=%s expected=0x%02x rdata=0x%08x",
            round_index,
            arid,
            mask,
            observed,
            expected,
            rdata,
        )
        assert resp == RESP_OKAY and rdata == data2, "RID corruption must not disturb read data"
        assert observed is not None, "RID capture miss on the corrupted read"
        assert observed == expected, (
            f"round {round_index}: RID {observed:#x} != issued^mask {expected:#x}"
        )
        assert observed != arid, "corrupted RID must be distinguishable from the issued ARID"

        # One-shot for reads too.
        arid = random.randrange(256)
        capture = _rid_capture(dut)
        resp, rdata = await drive_wire_read(dut, arid=arid, addr=addr)
        observed = await capture.finish()
        assert resp == RESP_OKAY and observed == arid, (
            f"round {round_index}: RID corruption must be one-shot"
        )

    # clear_errors() disarms pending corruption.
    slave.sequence.inject_id_corruption(mask=random.randrange(1, 256))
    slave.sequence.clear_errors()
    awid = random.randrange(256)
    capture = _bid_capture(dut)
    resp = await drive_wire_write(dut, awid=awid, addr=addr, data=data)
    observed = await capture.finish()
    assert resp == RESP_OKAY and observed == awid, "clear_errors must disarm ID corruption"

    log.info("done: BID/RID corruption observed, one-shot and disarm proven")

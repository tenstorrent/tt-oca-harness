# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pipelined reads of one ABR register from the SMN inbound master each return its value.

no_cpu / +skip_fuse_sense.

The test drives concurrent single-beat reads of one read-only ABR register at
depths 1, 2, 3, 4 and 8, one ARID each, on `m_axi`. That is the SoC-facing
inbound port (`smn_inbound_axi_req_i` in `hw/sys/sep/rtl/sep.sv`), a real master
that may hold several reads outstanding with distinct `ARID`s: AXI places no
restriction on that, and no SEP document places one on this aperture. The path
reaches the ABR aperture through an inbound-filter read window, the local
crossbar (`u_sep_local_axi_xbar_wrapper.ext_axi_req_i` in `sep.sv`) and the
crypto interconnect. An AXI-to-AHB bridge that drops HADDR[2:0] on streamed
reads returns a wrong value from the third read in flight, so the sweep fails on
that defect. `sep_abr_pipelined_read_matrix_test` runs the same depths on both
masters, plus the identity-word orders.

Single-beat reads only (`ARLEN = 0`): the crypto demux routes any `AxLEN != 0`
to its error slave (`aw_is_burst` / `ar_is_burst` in
`hw/sys/sep/rtl/sep_crypto_axi_interconnect.sv`), which `hw/sys/sep/doc/crypto.adoc`
states to software.

The comparand is `MLDSA_VERSION1`, a read-only register. `abr_reg.rdl` gives
it no reset and no SEP document gives its value, so the control read alone is
the golden for the sweep.

Checkers:
  CHK-ABR-CONTROL  the control read answers OKAY with a known, nonzero
                   value. It is the comparand for everything below, so a
                   control of zero would let every pipelined read compare
                   equal and turn the sweep vacuous
  CHK-ABR-PIPELINED-READ  every read, at every depth, returns that same value
                   and an OKAY response; a timeout counts as a failure
  CHK-ABR-PIPELINE-OVERLAP  at every depth, the m_axi pins accept all N ARs
                   before the first R handshake, so N reads are in flight at
                   once. Without it a path that serialised the reads would
                   still return the right values and pass the compare above
"""

from __future__ import annotations

import pyuvm
from cocotb.triggers import with_timeout
from env.sep_axi_agent import SepAxiOp
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from seq_lib.sep_abr_bus_seq import AbrBusWatch
from seq_lib.sep_abr_keygen_seq import ABR_BASE, ABR_VERSION1
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg

SIZE_4B = 2
RESP_OKAY = 0
# The address comes from the RDL via sep_abr_keygen_seq, never a literal.
A_VERSION1 = ABR_VERSION1
DEPTHS = (1, 2, 3, 4, 8)
# The TB master bus whose AR/R handshakes the overlap check records.
BUS = "m_axi"
READ_TIMEOUT_NS = 20_000


def word(raw, addr: int) -> int:
    if isinstance(raw, (bytes, bytearray)):
        b = bytes(raw)
        if len(b) >= 8:
            off = 4 if (addr & 4) else 0
            return int.from_bytes(b[off : off + 4], "little")
        return int.from_bytes(b[:4], "little")
    return int(raw) & 0xFFFF_FFFF


@pyuvm.test()
class sep_abr_pipelined_read_test(sep_base_test):
    """Pipelined ABR reads from the inbound master return the register value at every depth."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # The inbound filter denies by default, so the window is opened first.
        # Programmed from the CPU-LSU side, which is how every inbound test
        # reaches these CSRs.
        filt = SepInboundFilter(self)
        cfg = SepInboundFilterCfg(entry=0, allow_addr=ABR_BASE)
        await filt.program_rule(
            cfg,
            read_allowed=True,
            write_allowed=True,
            allow_burst=False,
            end_addr=ABR_BASE + 0x1000,
        )
        self.logger.info("inbound entry 0 allows 0x%08x..0x%08x", ABR_BASE, ABR_BASE + 0x1000)

        # Control: one read on its own, through the sequencer, so the value the
        # aperture holds is established before anything is pipelined.
        seq = SepAxiAccessSeq(
            "abr_ctrl_rd", op=SepAxiOp.READ, addr=A_VERSION1, length=4, size=SIZE_4B
        )
        await self.start_ext_seq(seq)
        alone = seq.rdata & 0xFFFF_FFFF
        self.logger.info(
            "m_axi control: 0x%08x read alone -> 0x%08x (resp=%d)",
            A_VERSION1,
            alone,
            seq.resp_code,
        )

        # The control read is the golden, so it has to be worth comparing
        # against. A control that answered zero, or answered at all with an
        # error, would let every pipelined read compare equal to it and this
        # leaf would be green over a dead aperture. The m_axi bus monitor fails
        # an OKAY beat that carries X/Z in the lanes read, so an OKAY control
        # is a known value.
        assert seq.resp_code == RESP_OKAY, (
            f"CHK-ABR-CONTROL FAIL: the control read of 0x{A_VERSION1:08x} "
            f"returned resp={seq.resp_code}, expected OKAY. The aperture is not "
            "readable, so nothing below would mean anything."
        )
        assert alone != 0, (
            f"CHK-ABR-CONTROL FAIL: the control read of 0x{A_VERSION1:08x} "
            "returned zero. This is the golden every pipelined read is compared "
            "against; a zero control would make that comparison vacuous."
        )
        self.logger.info(
            "CHK-ABR-CONTROL PASS: 0x%08x reads 0x%08x alone, OKAY, known and nonzero "
            "-- the golden for the depth sweep",
            A_VERSION1,
            alone,
        )

        axi = self.env.ext_axi_agent.driver.axi
        wrong: list[tuple[int, int, int | None]] = []
        bad_resp: list[tuple[int, int, int]] = []
        # (depth, ARs accepted, ARs accepted before the first R, max outstanding)
        overlap: list[tuple[int, int, int, int]] = []
        for depth in DEPTHS:
            # The watch records the AR and R handshakes on the m_axi pins, so
            # the overlap is measured on the DUT port, not taken from the order
            # in which this test called init_read.
            watch = AbrBusWatch((BUS,))
            watch.start()
            try:
                evs = [
                    axi.init_read(address=A_VERSION1, length=4, size=SIZE_4B, arid=i)
                    for i in range(depth)
                ]
                vals, lost = [], 0
                for ev in evs:
                    try:
                        await with_timeout(ev.wait(), READ_TIMEOUT_NS, "ns")
                    except Exception:
                        lost += 1
                        vals.append(None)
                        continue
                    # worst_resp, not int(resp or 0): an unreadable response must
                    # not coerce to OKAY. It returns RESP_TIMEOUT instead.
                    code = worst_resp(getattr(ev.data, "resp", None))
                    if code != RESP_OKAY:
                        # An error response is a different failure from silently
                        # wrong data, and is recorded as such rather than folded
                        # into the value compare.
                        bad_resp.append((depth, len(vals), code))
                    vals.append(word(getattr(ev.data, "data", None), A_VERSION1))
            finally:
                watch.stop()
            rec = watch.rec[BUS]
            overlap.append((depth, len(rec.ar), rec.ar_before_first_r, rec.max_rd_outstanding))
            self.logger.info(
                "m_axi depth=%d overlap: %d AR accepted, %d before the first R, "
                "max %d reads outstanding",
                depth,
                len(rec.ar),
                rec.ar_before_first_r,
                rec.max_rd_outstanding,
            )
            shown = ", ".join("timeout" if v is None else f"0x{v:08x}" for v in vals)
            self.logger.info(
                "m_axi depth=%d @0x%08x: %s  [timeouts=%d]",
                depth,
                A_VERSION1,
                shown,
                lost,
            )
            for i, v in enumerate(vals):
                if v != alone:
                    wrong.append((depth, i, v))

        assert not bad_resp, (
            "CHK-ABR-PIPELINED-READ FAIL: "
            + "; ".join(f"depth {d} read {i} answered resp={c}" for d, i, c in bad_resp)
            + f". Every read is of 0x{A_VERSION1:08x}, which answers OKAY when "
            "read on its own, so the aperture refused a read it had already "
            "accepted an AR for."
        )
        assert not wrong, (
            "CHK-ABR-PIPELINED-READ FAIL: "
            + "; ".join(
                f"depth {d} read {i} returned " + ("no response" if v is None else f"0x{v:08x}")
                for d, i, v in wrong
            )
            + f". Every read is of 0x{A_VERSION1:08x}, which returns 0x{alone:08x} when "
            "read on its own. MLDSA_VERSION1 is read-only with unconditional "
            "combinational readback, so it holds one value and the response carried "
            "something else."
        )
        self.logger.info(
            "CHK-ABR-PIPELINED-READ PASS: every read at depths %s returned 0x%08x",
            ", ".join(str(d) for d in DEPTHS),
            alone,
        )

        serial = [o for o in overlap if not (o[1] == o[2] == o[3] == o[0])]
        assert not serial, (
            "CHK-ABR-PIPELINE-OVERLAP FAIL: "
            + "; ".join(
                f"depth {d}: {n} AR accepted, {before} before the first R, max {mx} outstanding"
                for d, n, before, mx in serial
            )
            + ". Each depth must hold all of its reads in flight at once on the "
            "m_axi pins; otherwise its value compare proves nothing about pipelining."
        )
        self.logger.info(
            "CHK-ABR-PIPELINE-OVERLAP PASS: AR accepted before the first R / max "
            "outstanding per depth: %s",
            ", ".join(f"depth {d}: {before}/{mx}" for d, _n, before, mx in overlap),
        )

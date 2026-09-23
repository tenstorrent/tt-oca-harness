# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pipelined reads of an ABR register from the SMN inbound master must return it.

Reproducer for issue #2253. It FAILS while the RTL carries that defect, and
passes when it is fixed.

Driven from `m_axi`, the SoC-facing inbound port (`hw/sys/sep/rtl/sep.sv:98`),
because that is a real master rather than a stand-in. The CPU-LSU splice is not
used: `s_axi` exists only to present what the VeeR LSU would present, and the
LSU serialises MMIO loads -- a firmware run of the same four reads keeps one
transaction in flight and never enters the bridge's streaming state. Driving
several reads at once on that port would be stimulus the port cannot carry in
the real design, so it proves nothing.

The inbound path has no such limit. It reaches the ABR aperture through the
local crossbar (`sep.sv:415`, `ext_axi_req_i`) and the crypto interconnect, and
an SoC master may legitimately hold several reads outstanding with distinct
`ARID`s -- AXI places no restriction on that, and no SEP document places one on
this aperture.

Single-beat reads only (`ARLEN = 0`): the crypto demux routes any `AxLEN != 0`
to its error slave (`sep_crypto_axi_interconnect.sv:111-112`, `:175`, `:205`),
which `hw/sys/sep/doc/crypto.adoc` states to software.

The comparand is `MLDSA_VERSION1`, a plain read-only register with unconditional
combinational readback, so it holds one value and zero is not that value.

Checkers:
  CHK-ABR-CONTROL  the control read answers OKAY and returns the generated
                   golden. It is the comparand for everything below, so a
                   control of zero would let every pipelined read compare
                   equal and turn the sweep vacuous
  CHK-ABR-PIPELINED-READ  every read, at every depth, returns that same value
                   and an OKAY response; a timeout counts as a failure

Pass Criteria: every named checker PASSes. UVM_ERROR == 0.
"""

from __future__ import annotations

import pyuvm
from cocotb.triggers import with_timeout
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg

from seq_lib.sep_abr_keygen_seq import ABR_BASE, ABR_VERSION1, VER1_EXP

SIZE_4B = 2
RESP_OKAY = 0
# Address and expected word both come from the generated map via
# sep_abr_keygen_seq, never a literal. The control read is held against
# VER1_EXP so the golden for the sweep cannot silently become zero.
A_VERSION1 = ABR_VERSION1
DEPTHS = (1, 2, 3, 4, 8)
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
    """ABR reads at increasing depth from the inbound master."""

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
            "REPRO m_axi control: 0x%08x read alone -> 0x%08x (resp=%d)",
            A_VERSION1, alone, seq.resp_code,
        )

        # The control read is the golden, so it has to be worth comparing
        # against. A control that answered zero, or answered at all with an
        # error, would let every pipelined read compare equal to it and this
        # leaf would be green over a dead aperture.
        assert seq.resp_code == RESP_OKAY, (
            f"CHK-ABR-CONTROL FAIL: the control read of 0x{A_VERSION1:08x} "
            f"returned resp={seq.resp_code}, expected OKAY. The aperture is not "
            "readable, so nothing below would mean anything."
        )
        assert alone == VER1_EXP, (
            f"CHK-ABR-CONTROL FAIL: the control read of 0x{A_VERSION1:08x} "
            f"returned 0x{alone:08x}, expected 0x{VER1_EXP:08x}. This is the "
            "golden every pipelined read is compared against; a zero or wrong "
            "control would make that comparison vacuous."
        )
        self.logger.info(
            "CHK-ABR-CONTROL PASS: 0x%08x reads 0x%08x alone, OKAY -- a non-zero "
            "golden for the depth sweep",
            A_VERSION1, alone,
        )

        axi = self.env.ext_axi_agent.driver.axi
        wrong: list[tuple[int, int, int | None]] = []
        bad_resp: list[tuple[int, int, int]] = []
        for depth in DEPTHS:
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
                resp = getattr(ev.data, "resp", None)
                code = max(resp) if isinstance(resp, (list, tuple)) else int(resp or 0)
                if code != RESP_OKAY:
                    # An error response is a different failure from silently
                    # wrong data, and is recorded as such rather than folded
                    # into the value compare.
                    bad_resp.append((depth, len(vals), code))
                vals.append(word(getattr(ev.data, "data", None), A_VERSION1))
            shown = ", ".join("timeout" if v is None else f"0x{v:08x}" for v in vals)
            self.logger.info(
                "m_axi depth=%d @0x%08x: %s  [timeouts=%d]",
                depth, A_VERSION1, shown, lost,
            )
            for i, v in enumerate(vals):
                if v != alone:
                    wrong.append((depth, i, v))

        assert not bad_resp, (
            "CHK-ABR-PIPELINED-READ FAIL: "
            + "; ".join(
                f"depth {d} read {i} answered resp={c}" for d, i, c in bad_resp
            )
            + f". Every read is of 0x{A_VERSION1:08x}, which answers OKAY when "
            "read on its own, so the aperture refused a read it had already "
            "accepted an AR for. See issue #2253."
        )
        assert not wrong, (
            "CHK-ABR-PIPELINED-READ FAIL: "
            + "; ".join(
                f"depth {d} read {i} returned "
                + ("no response" if v is None else f"0x{v:08x}")
                for d, i, v in wrong
            )
            + f". Every read is of 0x{A_VERSION1:08x}, which returns 0x{alone:08x} when "
            "read on its own. MLDSA_VERSION1 is read-only with unconditional "
            "combinational readback, so it holds one value and the response carried "
            "something else. See issue #2253."
        )
        self.logger.info(
            "CHK-ABR-PIPELINED-READ PASS: every read at depths %s returned 0x%08x",
            ", ".join(str(d) for d in DEPTHS),
            alone,
        )

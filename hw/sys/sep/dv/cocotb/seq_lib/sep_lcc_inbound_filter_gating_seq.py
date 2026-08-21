# SPDX-License-Identifier: Apache-2.0
"""LCC sep_debug -> inbound-filter gating sequences for the SEP OSS flow.

Stimulus for the inbound-filter-gating test (reference suite ``sep_lcc_uvm_inbound_filter
_gating_test``). The contract:

  feat_ctrl.sep_debug (FEAT_CTRL[0]) drives the SEP inbound filter's
  ``filter_skip_i`` (``sep.sv``: ``inbound_filter_skip_i = feat_ctrl_o.sep_debug``).
  When sep_debug=0 the inbound filter is active (block-by-default) and an external
  AXI access is blocked; when sep_debug=1 the filter is skipped and the external
  access reaches the SEP-local fabric.

Two buses are exercised:
  * CONTROL (CPU-LSU, ``s_axi``, no inbound filter): reads FEAT_CTRL and writes
    DEMOTE_1 to flip PROD -> PROD_DBG_1. FEAT_CTRL reads carry an ``expected``
    golden value so the scoreboard exact-value-checks the lc_state -> feat_ctrl
    decode (and FEAT_CTRL[0] is the frontdoor mirror of the internal
    ``filter_skip_i`` -- the OSS replacement for the reference suite's backdoor ``uvm_hdl_read``).
  * EXTERNAL (SMN-inbound, ``m_axi``): the filtered path. ``SepExtAxiProbeSeq``
    issues a single read and exposes resp_ok / resp_code / timed_out. Timeout is
    fatal by default; the inbound filter proves a blocked access by routing it to
    axi_err_slv with RESP_DECERR.

Register-map constants live here (co-located with the stimulus, never copied into
the test). Offsets mirror ``hw/sys/sep/regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl``.
"""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_lcc_golden import LCC_DEMOTE_1, LCC_DEMOTE_2, LCC_FEAT_CTRL

# SEP-local lifecycle-controller block. The LCC register map lives in
# env.sep_lcc_golden (single source of truth).
DEMOTE_BIT = 0x1                        # DEMOTE.demote (field [0:0])


class SepLccFeatCtrlCheckSeq(uvm_sequence):
    """Read FEAT_CTRL (lo+hi) on the CONTROL bus and exact-value-check vs golden.

    ``expected`` is the 64-bit golden FEAT_CTRL from ``feat_ctrl_expected(...)``.
    Each 32-bit half is read with ``item.expected`` set so the scoreboard does the
    value compare (positive evidence, fails on a broken decode). Exposes
    ``feat_ctrl`` (64-bit observed) and ``sep_debug`` (FEAT_CTRL[0]).
    """

    def __init__(self, expected: int, *, name: str = "lcc_feat_ctrl_check_seq") -> None:
        super().__init__(name)
        self.expected = expected & ((1 << 64) - 1)
        self.feat_ctrl: int | None = None
        self.sep_debug: int | None = None

    async def _read_expect(self, addr: int, expected: int, label: str) -> int:
        item = SepAxiItem(f"rd_{label}_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata & 0xFFFF_FFFF

    async def body(self) -> None:
        lo = await self._read_expect(LCC_FEAT_CTRL, self.expected & 0xFFFF_FFFF, "feat_lo")
        hi = await self._read_expect(
            LCC_FEAT_CTRL + 4, (self.expected >> 32) & 0xFFFF_FFFF, "feat_hi"
        )
        self.feat_ctrl = lo | (hi << 32)
        self.sep_debug = lo & 0x1


class SepLccDemoteSeq(uvm_sequence):
    """Write DEMOTE_{1,2}.demote on the CONTROL bus and read it back.

    The two demote registers act independently, each on its own debug group:
    DEMOTE_1 relaxes DBG_1 ([15:0]) and DEMOTE_2 relaxes DBG_2 ([31:16]). Which
    register this sequence drives is therefore load-bearing, not a detail -- so
    it is a parameter rather than being baked into the class.

    ``group`` is 1 or 2. ``value`` allows clearing as well as setting, which is what
    lets a caller show one group's demote does not move the other group's bits.
    Exposes ``demote`` (the read-back demote bit).
    """

    def __init__(self, group: int = 1, value: int = DEMOTE_BIT, *,
                 name: str | None = None) -> None:
        super().__init__(name or f"lcc_demote{group}_seq")
        assert group in (1, 2), f"demote group must be 1 or 2, got {group}"
        self.group = group
        self.value = value & DEMOTE_BIT
        self.addr = LCC_DEMOTE_1 if group == 1 else LCC_DEMOTE_2
        self.demote: int | None = None

    async def body(self) -> None:
        wr = SepAxiItem(f"wr_demote{self.group}")
        wr.op = SepAxiOp.WRITE
        wr.addr = self.addr
        wr.length = 4
        wr.wdata = self.value
        await self.start_item(wr)
        await self.finish_item(wr)

        rd = SepAxiItem(f"rd_demote{self.group}")
        rd.op = SepAxiOp.READ
        rd.addr = self.addr
        rd.length = 4
        rd.expected = self.value
        await self.start_item(rd)
        await self.finish_item(rd)
        self.demote = rd.rdata & 0x1


# Back-compatible alias: the original class only ever drove DEMOTE_1.
class SepLccDemote1Seq(SepLccDemoteSeq):
    def __init__(self, *, name: str = "lcc_demote1_seq") -> None:
        super().__init__(group=1, name=name)


# AXI response codes (axi_pkg): blocked inbound traffic is routed to axi_err_slv
# with RESP_DECERR (axi_filter_wrap.sv), so a blocked external probe must return
# exactly this -- not a timeout (which would mean a wedge) nor SLVERR.
RESP_DECERR = 3


class SepExtAxiProbeSeq(uvm_sequence):
    """Single read on the EXTERNAL (SMN-inbound, ``m_axi``) master.

    Run on the external sequencer (``start_ext_seq``). The access traverses the
    inbound filter: blocked when sep_debug=0 (the filter routes it to axi_err_slv
    -> RESP_DECERR) and allowed when sep_debug=1 (OKAY + real data). Exposes
    ``resp_ok`` / ``resp_code`` / ``timed_out`` / ``rdata``.

    ``allow_timeout`` defaults False: a non-completing access is then a test-fatal
    wedge, NOT accepted as "blocked". A blocked access is proven by the specific
    DECERR response code, not by a timeout.
    """

    def __init__(self, addr: int, *, allow_timeout: bool = False,
                 name: str = "ext_axi_probe_seq") -> None:
        super().__init__(name)
        self.addr = addr
        self.allow_timeout = allow_timeout
        self.resp_ok: bool = False
        self.resp_code: int = -1
        self.timed_out: bool = False
        self.rdata: int = 0

    async def body(self) -> None:
        item = SepAxiItem(f"ext_rd_0x{self.addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = self.addr
        item.length = 4
        item.allow_timeout = self.allow_timeout
        await self.start_item(item)
        await self.finish_item(item)
        self.resp_ok = item.resp_ok
        self.resp_code = item.resp_code
        self.timed_out = item.timed_out
        self.rdata = item.rdata & 0xFFFF_FFFF

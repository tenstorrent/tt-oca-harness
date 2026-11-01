# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One write-1-to-set write of the LC_STATE shadow word, then its readback.

This is the LC_STATE next-state path: a frontdoor write of the shadow word,
which reaches ``efuse_shadow_regs`` as the access-controlled APB request whose
setup phase computes the next lifecycle state. Distinct from the OTP-program
path the lifecycle stitch walk drives -- that one burns a fuse bit and re-senses,
and never evaluates this next-state logic.

Two value checks per write, both exact-value (so a broken next state fails here
rather than merely "no X"):

  * the LC_STATE shadow word reads back the differentially encoded ``{~raw, raw}``
    for the expected next state in bytes [7:0] (the caller grades it from
    ``observed_word``; bytes [31:8] are compared only when ``expected_upper`` is
    given), and
  * the lifecycle controller's FEAT_CTRL decodes that same next state, which is
    what proves the write reached the LCC rather than only the shadow storage.

The expected next state comes from ``lc_state_next`` in the LCC golden, which is
derived from the lifecycle chapter and not from the RTL.
"""

from __future__ import annotations

import cocotb
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_image import lc_encode
from env.sep_lcc_golden import LCC_FEAT_CTRL, feat_ctrl_expected, lc_state_name
from pyuvm import uvm_sequence
from sep_reg_meta import RegBlock, sep_reg, sym

LC_STATE_SHADOW = sym("SEP_EFUSE_MAP_LC_STATE_REG_ADDR")
_LC_STATE_MAP = RegBlock("SEP_EFUSE_MAP")
LC_STATE_BYTE_MASK = _LC_STATE_MAP.field_mask("LC_STATE", "lc_state")
LC_STATE_UPPER_MASK = _LC_STATE_MAP.field_mask("LC_STATE", "rsvd")
# FEAT_CTRL is one 64-bit register read as two 32-bit words; the upper word
# starts half the register width above its address.
_FEAT_CTRL_WIDTH = sep_reg.SEP_LIFECYCLE_CTRL_FEAT_CTRL_REG_WIDTH
assert _FEAT_CTRL_WIDTH == 64, f"FEAT_CTRL is {_FEAT_CTRL_WIDTH} bits; the seq reads two words"
LCC_FEAT_CTRL_HI = LCC_FEAT_CTRL + _FEAT_CTRL_WIDTH // 16


class SepLcShadowWriteSeq(uvm_sequence):
    """Write ``wdata`` to the LC_STATE shadow word; require ``expected_raw``.

    ``refused`` marks a write that a token gate or the terminal rule refuses: no
    text states the response of such a write, so the scoreboard does not grade it
    and the caller logs ``write_resp``.
    """

    def __init__(
        self,
        wdata: int,
        expected_raw: int,
        expected_upper: int | None,
        *,
        sip_dis: int,
        sys_dis: int,
        demote_1: int = 0,
        demote_2: int = 0,
        sec_dis: int = 0,
        do_write: bool = True,
        refused: bool = False,
        name: str = "sep_lc_shadow_write_seq",
    ) -> None:
        super().__init__(name)
        self.wdata = wdata & 0xFFFF_FFFF
        self.expected_raw = expected_raw & 0xF
        self.expected_upper = (
            None if expected_upper is None else expected_upper & LC_STATE_UPPER_MASK
        )
        self.sip_dis = sip_dis
        self.sys_dis = sys_dis
        self.demote_1 = demote_1
        self.demote_2 = demote_2
        self.sec_dis = sec_dis
        # do_write=False turns this into readback-only, for the transient-RMA
        # path: there the lifecycle nibble moves on a token match with no bus
        # request at all, so a write would be the wrong stimulus.
        self.do_write = do_write
        self.refused = refused
        self.write_resp: int | None = None
        self.observed_lc_raw: int | None = None
        self.observed_word: int | None = None
        self.observed_feat: int | None = None

    async def _access(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        data: int = 0,
        expected: int | None = None,
        label: str = "axi",
    ) -> SepAxiItem:
        item = SepAxiItem(f"{label}_0x{addr:08x}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.expected = expected
        item.allow_unverified_write_resp = op is SepAxiOp.WRITE and self.refused
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def body(self) -> None:
        expected_word = (
            None
            if self.expected_upper is None
            else self.expected_upper | lc_encode(self.expected_raw)
        )
        feat = feat_ctrl_expected(
            self.expected_raw,
            self.sip_dis,
            self.sys_dis,
            demote_1=self.demote_1,
            demote_2=self.demote_2,
            sec_dis=self.sec_dis,
        )

        if self.do_write:
            wr = await self._access(
                SepAxiOp.WRITE, LC_STATE_SHADOW, data=self.wdata, label="wr_lc_state_shadow"
            )
            self.write_resp = wr.resp_code
        rd = await self._access(
            SepAxiOp.READ, LC_STATE_SHADOW, expected=expected_word, label="rd_lc_state_shadow"
        )
        word = int(rd.rdata)
        self.observed_word = word
        # Publish the nibble the DUT returned, not the one this sequence expected:
        # the caller's transition check consumes it, so that check stays driven by
        # DUT data rather than comparing two test-side constants.
        self.observed_lc_raw = word & 0xF

        feat_lo = int(
            (
                await self._access(
                    SepAxiOp.READ, LCC_FEAT_CTRL, expected=feat & 0xFFFF_FFFF, label="rd_feat_lo"
                )
            ).rdata
        )
        feat_hi = int(
            (
                await self._access(
                    SepAxiOp.READ,
                    LCC_FEAT_CTRL_HI,
                    expected=(feat >> 32) & 0xFFFF_FFFF,
                    label="rd_feat_hi",
                )
            ).rdata
        )
        self.observed_feat = feat_lo | (feat_hi << 32)

        cocotb.log.info(
            "[lc-w1s] %s -> shadow 0x%08x (%s) FEAT_CTRL=0x%016x",
            f"wrote 0x{self.wdata:08x}" if self.do_write else "no write",
            word,
            lc_state_name(self.observed_lc_raw),
            self.observed_feat,
        )

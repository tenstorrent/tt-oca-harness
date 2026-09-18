# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RMA token match / mismatch stimulus for the standalone token RANDCFG.

Writes a 256-bit token into the eFuse MMR input registers, pulses EOP, and
polls the match status until it is a documented terminal code (match
``6'b010101``, mismatch ``6'b101010``, or error ``6'b111111``). Token
values come from the run seed. Digest
compare is SHA-256 over the 32-byte big-endian token (same as the stitch
walk). LC_STATE programming stays with ``sep_efuse_otp_program_seq``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_image import LC_WORD_IDX
from env.sep_lcc_golden import LC_RMA_CHIP_1, LC_RMA_SIP_1

# Re-exported for sep_efuse_rma_token_rand_test, which builds its golden via
# seq_lib rather than reaching into env directly.
from env.sep_rma_token import SepRmaTokenCfg as SepRmaTokenCfg
from pyuvm import uvm_sequence
from env.sep_spec_tables import agg_from_pic
from sep_reg_meta import EFUSE_MMR, sym

_RMA_SIP_TOKEN_I = sym("EFUSE_MMR_RMA_SIP_TOKEN_I_0__REG_ADDR")
_RMA_CHIPLET_TOKEN_I = sym("EFUSE_MMR_RMA_CHIPLET_TOKEN_I_0__REG_ADDR")
_SEC_DISABLE_TOKEN_I = sym("EFUSE_MMR_SEC_DISABLE_TOKEN_I_0__REG_ADDR")
_TOKEN_EOP = sym("EFUSE_MMR_TOKEN_EOP_REG_ADDR")
_RMA_SIP_TOKEN_MATCH = sym("EFUSE_MMR_RMA_SIP_TOKEN_MATCH_REG_ADDR")
_RMA_CHIPLET_TOKEN_MATCH = sym("EFUSE_MMR_RMA_CHIPLET_TOKEN_MATCH_REG_ADDR")
_SEC_DISABLE_TOKEN_MATCH = sym("EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_REG_ADDR")
_TOKEN_MATCH_FAULT = sym("EFUSE_MMR_TOKEN_MATCH_FAULT_REG_ADDR")
_TOKEN_MATCH = 0x15
_TOKEN_MISMATCH = 0x2A
_TOKEN_ERROR = 0x3F
_TOKEN_CODES = (_TOKEN_MATCH, _TOKEN_MISMATCH, _TOKEN_ERROR)

TOKEN_MATCH = _TOKEN_MATCH
TOKEN_MISMATCH = _TOKEN_MISMATCH
TOKEN_ERROR = _TOKEN_ERROR
TOKEN_MATCH_FAULT = _TOKEN_MATCH_FAULT
FAULT_RMA_SIP = EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "rma_sip_token_fault")
FAULT_RMA_CHIPLET = EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "rma_chiplet_token_fault")
FAULT_SEC_DISABLE = EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "secure_disable_token_fault")
EOP_RMA_SIP = EFUSE_MMR.field_mask("TOKEN_EOP", "rma_sip_token_go")
EOP_RMA_CHIPLET = EFUSE_MMR.field_mask("TOKEN_EOP", "rma_chiplet_token_go")
EOP_SEC_DISABLE = EFUSE_MMR.field_mask("TOKEN_EOP", "secure_disable_token_go")
TOKEN_CMP_INJECT_OFF = 0
TOKEN_CMP_INJECT_COLLAPSE = 1
TOKEN_CMP_INJECT_DISAGREE = 2
TOKEN_CMP_INJECT_COMMON = 3
TOKEN_CMP_INJECT_COMMON_MATCH = 4
TOKEN_CMP_SEL_SIP = 0
TOKEN_CMP_SEL_CHIPLET = 1
TOKEN_CMP_SEL_SEC = 2
IRQ_TOKEN_MATCH_FAULT = agg_from_pic("Token match fault")

TOKEN_RMA_SIP = 0
TOKEN_RMA_CHIPLET = 1
TOKEN_SEC_DISABLE = 2
_LC_STATE_BIT_BASE = LC_WORD_IDX * 32

_POLL_CYCLES = 200


class SepRmaTokenMatchSeq(uvm_sequence):
    """Present a token and publish whether the match code landed."""

    def __init__(
        self,
        kind: int,
        token: int,
        *,
        name: str = "sep_rma_token_match_seq",
    ) -> None:
        super().__init__(name)
        assert kind in (TOKEN_RMA_SIP, TOKEN_RMA_CHIPLET, TOKEN_SEC_DISABLE)
        self.kind = kind
        self.token = token
        self.matched: bool | None = None
        self.match_code: int | None = None
        self.timed_out = False

    async def _write(self, addr: int, data: int, label: str) -> None:
        item = SepAxiItem(f"{label}_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def _read(self, addr: int, label: str) -> int:
        item = SepAxiItem(f"{label}_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def body(self) -> None:
        if self.kind == TOKEN_RMA_SIP:
            token_base = _RMA_SIP_TOKEN_I
            eop_value = EOP_RMA_SIP
            match_addr = _RMA_SIP_TOKEN_MATCH
            token_name = "RMA_SIP"
        elif self.kind == TOKEN_RMA_CHIPLET:
            token_base = _RMA_CHIPLET_TOKEN_I
            eop_value = EOP_RMA_CHIPLET
            match_addr = _RMA_CHIPLET_TOKEN_MATCH
            token_name = "RMA_CHIPLET"
        else:
            token_base = _SEC_DISABLE_TOKEN_I
            eop_value = EOP_SEC_DISABLE
            match_addr = _SEC_DISABLE_TOKEN_MATCH
            token_name = "SEC_DISABLE"

        for i in range(8):
            await self._write(
                token_base + 4 * i,
                (self.token >> (32 * i)) & 0xFFFF_FFFF,
                "token_input",
            )
        await self._write(_TOKEN_EOP, eop_value, "token_eop")

        for _ in range(_POLL_CYCLES):
            await ClockCycles(cocotb.top.clk_i, 1)
            result = await self._read(match_addr, "token_match") & 0x3F
            self.match_code = result
            if result in _TOKEN_CODES:
                self.matched = result == _TOKEN_MATCH
                cocotb.log.info(
                    "[rma] %s token code=0x%02x matched=%s",
                    token_name,
                    result,
                    self.matched,
                )
                return
        # Never settling is a DUT failure, not a mismatch. Recording it as
        # matched=False would make a token block that answers nothing
        # indistinguishable from one that correctly rejected a wrong token, so
        # every "mismatch" check in every caller would pass on a dead comparator.
        raise AssertionError(
            f"{token_name} token match status never settled after {_POLL_CYCLES} "
            f"cycles (last code=0x{self.match_code:02x}; expected one of "
            f"match 0x{_TOKEN_MATCH:02x}, mismatch 0x{_TOKEN_MISMATCH:02x}, "
            f"error 0x{_TOKEN_ERROR:02x})"
        )


def rma_lc_bit(kind: int) -> int:
    """OTP bit that the token gate authorizes (LC_STATE raw bit 1 or 2)."""
    if kind == TOKEN_RMA_SIP:
        return _LC_STATE_BIT_BASE + 1
    if kind == TOKEN_RMA_CHIPLET:
        return _LC_STATE_BIT_BASE + 2
    raise ValueError(f"unknown token kind {kind}")


def rma_lc_raw(kind: int) -> int:
    if kind == TOKEN_RMA_SIP:
        return LC_RMA_SIP_1
    if kind == TOKEN_RMA_CHIPLET:
        return LC_RMA_CHIP_1
    raise ValueError(f"unknown token kind {kind}")

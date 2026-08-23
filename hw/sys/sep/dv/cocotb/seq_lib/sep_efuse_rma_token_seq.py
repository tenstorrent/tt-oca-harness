# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RMA token match / mismatch stimulus for the standalone token RANDCFG.

Writes a 256-bit token into the eFuse MMR input registers, pulses EOP, and
polls the match status. A match is the documented 6'b010101 code; a mismatch
must not produce that code. Token values come from the run seed. Digest
compare is SHA-256 over the 32-byte big-endian token (same as the stitch
walk). LC_STATE programming stays with ``sep_efuse_otp_program_seq``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_image import LC_WORD_IDX
from env.sep_lcc_golden import LC_RMA_CHIP_1, LC_RMA_SIP_1
from env.sep_rma_token import SepRmaTokenCfg
from sep_reg_meta import sym

_EFUSE_MMR_BASE = sym("EFUSE_MMR_REG_MAP_BASE_ADDR")
_RMA_SIP_TOKEN_I = _EFUSE_MMR_BASE + 0x00
_RMA_CHIPLET_TOKEN_I = _EFUSE_MMR_BASE + 0x20
_TOKEN_EOP = _EFUSE_MMR_BASE + 0x60
_RMA_SIP_TOKEN_MATCH = _EFUSE_MMR_BASE + 0x64
_RMA_CHIPLET_TOKEN_MATCH = _EFUSE_MMR_BASE + 0x68
_TOKEN_MATCH = 0x15

TOKEN_RMA_SIP = 0
TOKEN_RMA_CHIPLET = 1
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
        assert kind in (TOKEN_RMA_SIP, TOKEN_RMA_CHIPLET)
        self.kind = kind
        self.token = token
        self.matched: bool | None = None
        self.match_code: int | None = None

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
            eop_value = 0x0000_0001
            match_addr = _RMA_SIP_TOKEN_MATCH
            token_name = "RMA_SIP"
        else:
            token_base = _RMA_CHIPLET_TOKEN_I
            eop_value = 0x0000_0100
            match_addr = _RMA_CHIPLET_TOKEN_MATCH
            token_name = "RMA_CHIPLET"

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
            if result == _TOKEN_MATCH:
                self.matched = True
                cocotb.log.info("[rma] %s token matched (code=0x%02x)", token_name, result)
                return
        self.matched = False
        cocotb.log.info(
            "[rma] %s token did not match (last code=0x%02x)",
            token_name, self.match_code,
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

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO wrap 0: interface_enable outranks lsio_select; clear drops register TX."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
_WRAP0_BIT = 1 << 0

_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
_TX_ENABLE = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_LSIO_SELECT = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_SELECT_bm")

OUT_REG = _IF_ENABLE | _TX_ENABLE | _CORE2PAD
# Both mux bits set: interface_enable must still win (RDL: higher priority).
OUT_REG_WITH_LSIO = OUT_REG | _LSIO_SELECT
# LSIO requested, register interface off — wrap 0 register TX must drop.
OUT_LSIO_ONLY = _LSIO_SELECT | _TX_ENABLE | _CORE2PAD

# AXI write handshake already completed; this bound is the fail-closed ceiling
# until the GPIO wrap-0 flop is visible on tb_core2pad_en_o[0].
_MUX_BOUND = 64


class smc_gpio_p0_mux_test_seq(SmcCsrSeq):
    """Wrap 0 register TX vs lsio_select priority."""

    def __init__(self, name: str = "smc_gpio_p0_mux_test_seq") -> None:
        super().__init__(name)
        self.reg_ok = False
        self.priority_ok = False
        self.lsio_ok = False

    @staticmethod
    def _known_int(sig, label: str) -> int:
        v = sig.value
        if not v.is_resolvable:
            raw = getattr(v, "binstr", None) or str(v)
            raise AssertionError(f"{label}: sample unknown binstr={raw}")
        return int(v)

    async def _await_en_bit(self, dut, expect: int, label: str) -> None:
        clk = dut.clk_smc_i
        last = None
        for _ in range(_MUX_BOUND):
            await RisingEdge(clk)
            last = self._known_int(dut.tb_core2pad_en_o, label)
            got = (last >> 0) & 1
            if got == expect:
                return
        raise AssertionError(
            f"{label}: tb_core2pad_en_o[0] last={last} bit0={(last >> 0) & 1} "
            f"want={expect} after {_MUX_BOUND} smc clocks"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        width = len(dut.tb_core2pad_en_o.value)
        mask = (1 << width) - 1
        base_en = self._known_int(dut.tb_core2pad_en_o, "BASE_EN") & mask
        assert (base_en & _WRAP0_BIT) == 0, (
            f"wrap0 already enabled before register TX base=0x{base_en:x}"
        )

        await self.csr_write("GPIO0_REG_TX", GPIO0_DATA_CTRL, OUT_REG)
        await self._await_en_bit(dut, 1, "REG")
        en_reg = self._known_int(dut.tb_core2pad_en_o, "REG_EN") & mask
        delta = (en_reg ^ base_en) & mask
        assert delta == _WRAP0_BIT, (
            f"register TX did not toggle GPIO0 wrap bit 0 "
            f"base=0x{base_en:x} en=0x{en_reg:x} delta=0x{delta:x}"
        )
        val_reg = self._known_int(dut.tb_core2pad_o, "REG_VAL")
        assert (val_reg & _WRAP0_BIT) == _WRAP0_BIT, "register TX value not 1"
        self.reg_ok = True
        cocotb.log.info("CHK-GPIO-P0-MUX-REG: wrap0 core2pad_en delta=0x%x val=1", _WRAP0_BIT)

        await self.csr_write("GPIO0_REG_WINS", GPIO0_DATA_CTRL, OUT_REG_WITH_LSIO)
        await self._await_en_bit(dut, 1, "PRIO")
        en_both = self._known_int(dut.tb_core2pad_en_o, "PRIO_EN") & mask
        assert (en_both & _WRAP0_BIT) == _WRAP0_BIT, (
            "lsio_select overrode interface_enable (register TX enable dropped)"
        )
        val_both = self._known_int(dut.tb_core2pad_o, "PRIO_VAL")
        assert (val_both & _WRAP0_BIT) == _WRAP0_BIT, (
            "interface_enable lost value while lsio_select also set"
        )
        self.priority_ok = True
        cocotb.log.info("CHK-GPIO-P0-MUX-PRIO: interface_enable kept wrap0 TX with lsio_select")

        await self.csr_write("GPIO0_LSIO", GPIO0_DATA_CTRL, OUT_LSIO_ONLY)
        await self._await_en_bit(dut, 0, "LSIO")
        en_lsio = self._known_int(dut.tb_core2pad_en_o, "LSIO_EN") & mask
        assert (en_lsio & _WRAP0_BIT) == (base_en & _WRAP0_BIT), (
            f"clearing interface_enable left register TX enable "
            f"base_bit={bool(base_en & _WRAP0_BIT)} now={bool(en_lsio & _WRAP0_BIT)}"
        )
        self.lsio_ok = True
        cocotb.log.info("CHK-GPIO-P0-MUX-LSIO: wrap0 register TX dropped without interface_enable")

        await self.csr_write("GPIO0_RESTORE", GPIO0_DATA_CTRL, 0)
        cocotb.log.info(
            "CHK-GPIO-P0-MUX-BASIC: reg=%s prio=%s lsio=%s",
            self.reg_ok,
            self.priority_ok,
            self.lsio_ok,
        )

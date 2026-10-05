# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO wrap 0 mux: register interface outranks a LIVE lsio_select competitor.

The integrator pad table (`doc/integrator/meta/ocah_gpio_table.csv`) gives pad
0 the function SPI.DATA[0], and the bench drives the SMC's SPI data lanes
through its `tb_spi_dq_oe_n` / `tb_spi_txd` pins (`tb/tb_top.sv`), parked
not-driving by the base test. This sequence therefore drives data lane 0
through those pins before the mux legs, so that:

  * `lsio_select` alone is shown to ROUTE the LSIO function to the pad -- the
    positive control that separates a live select bit from one tied to 0, since
    with the source parked both produce `core2pad_en[0] = 0`; and
  * the priority leg runs against a competitor that is actually contributing a
    different value, so "interface_enable wins" is a distinguishable outcome
    rather than one both hypotheses satisfy.

The expectations are the GPIO ownership table
(`hw/ip/gpio/doc/architecture.adoc`, "Data and Direction Ownership"): a
hardware LSIO request outranks everything, the register interface outranks a
software-forced `lsio_select`, and a software-forced `lsio_select` routes the
same LSIO inputs to the pad. `DATA_CTRL.lsio_enable` "reports the hardware
request after the disable gate", so it is read back clear in every leg to
show the first row is not in play and the routing the LSIO leg measures is
the software-forced one.

No force, no deposit: the LSIO source is driven through the same `tb_spi_*`
input pins the SPI pad testcases use, and restored afterwards.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_index

#: The SPI data lane the bench drives as the LSIO source, and the wrap the
#: integrator pad table assigns that lane to. One `gpio` controller serves one
#: pad and `core2pad_en_o` carries one bit per wrap (`architecture.adoc`,
#: `port_table.adoc`), so the register instance and the enable bit are both
#: this index.
_SPI_DATA_LANE = 0
_WRAP = pad_index(f"SPI.DATA[{_SPI_DATA_LANE}]")
_WRAP0_BIT = 1 << _WRAP

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", _WRAP)

_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
_TX_ENABLE = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_LSIO_SELECT = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_SELECT_bm")
_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")
_PAD2CORE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")

#: DATA_CTRL bits a readback may differ in: PAD2CORE is a live pad
#: status bit, not storage, so it is excluded from the write/readback compare.
_CTRL_STORED_MASK = 0xFFFF_FFFF & ~_PAD2CORE

OUT_REG = _IF_ENABLE | _TX_ENABLE | _CORE2PAD
# Both mux bits set: interface_enable must still win (RDL: higher priority).
OUT_REG_WITH_LSIO = OUT_REG | _LSIO_SELECT
# LSIO requested, register interface off. CORE2PAD is NOT set here:
# with the register path deselected the pad data must come from the LSIO source,
# so leaving the register's own data bit clear keeps the two candidates distinct.
OUT_LSIO_ONLY = _LSIO_SELECT | _TX_ENABLE

# AXI write handshake already completed; this bound is the fail-closed ceiling
# until the GPIO wrap-0 flop is visible on tb_core2pad_en_o[0].
_MUX_BOUND = 64


class smc_gpio_p0_mux_test_seq(SmcCsrSeq):
    """Wrap 0 register TX vs lsio_select priority."""

    def __init__(self, name: str = "smc_gpio_p0_mux_test_seq") -> None:
        super().__init__(name)
        #: Measured `core2pad_en_o` / `core2pad_o` wrap-0 bits per leg.
        self.en_base = -1
        self.en_reg = -1
        self.en_both = -1
        self.en_lsio = -1
        self.val_lsio = -1
        self.val_lsio_flipped = -1

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
            got = (last >> _WRAP) & 1
            if got == expect:
                return
        raise AssertionError(
            f"{label}: tb_core2pad_en_o[{_WRAP}] last={last} "
            f"bit{_WRAP}={(last >> _WRAP) & 1} want={expect} after "
            f"{_MUX_BOUND} smc clocks"
        )

    async def _await_pad_val(self, dut, expect: int, label: str) -> int:
        """Bounded wait for `core2pad_o[_WRAP]`; expiry is a failure."""
        clk = dut.clk_smc_i
        last = None
        for _ in range(_MUX_BOUND):
            await RisingEdge(clk)
            last = self._known_int(dut.tb_core2pad_o, label)
            if ((last >> _WRAP) & 1) == expect:
                return last
        raise AssertionError(
            f"{label}: tb_core2pad_o[{_WRAP}] last={last} "
            f"bit{_WRAP}={(last >> _WRAP) & 1 if last is not None else None} "
            f"want={expect} after {_MUX_BOUND} smc clocks"
        )

    async def _check_ctrl_readback(self, name: str, written: int) -> int:
        """Read DATA_CTRL back and pin the fields this sequence programmed.

        Without it the mux select is written blind: a write that landed in the
        wrong field, was masked by the GPIO ACCESS_FILTER, or was dropped by a
        decode change would be invisible on the register side of the proof.
        PAD2CORE is excluded because it is a live pad status bit, not storage.
        """
        got = await self.csr_read(name, GPIO0_DATA_CTRL)
        assert (got & _LSIO_ENABLE) == 0, (
            f"{name}: DATA_CTRL.lsio_enable reads set (0x{got:08x}); a hardware LSIO request "
            f"owns wrap {_WRAP}, so the legs below would measure that request and not the "
            f"register and lsio_select fields they program"
        )
        assert (got & _CTRL_STORED_MASK) == (written & _CTRL_STORED_MASK), (
            f"{name}: DATA_CTRL stored 0x{got & _CTRL_STORED_MASK:08x}, wrote "
            f"0x{written & _CTRL_STORED_MASK:08x} (mask 0x{_CTRL_STORED_MASK:08x})"
        )
        return got

    @staticmethod
    def _drive_lsio_source(dut, *, driving: bool, data: int) -> None:
        """Drive the wrap's LSIO function (SPI data lane 0) through bench pins.

        The bench's SPI enable pin stays low, so no hardware LSIO request is
        raised: `DATA_CTRL.lsio_enable` is read back clear in every leg. With
        the source driving, a live `lsio_select` bit routes it to the pad and a
        dead one does not.
        """
        dq_oe_n = 0xFF & ~(1 << _SPI_DATA_LANE) if driving else 0xFF
        dut.tb_spi_dq_oe_n.value = dq_oe_n
        dut.tb_spi_txd.value = (data & 1) << _SPI_DATA_LANE

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        width = len(dut.tb_core2pad_en_o.value)
        mask = (1 << width) - 1
        base_en = self._known_int(dut.tb_core2pad_en_o, "BASE_EN") & mask
        self.en_base = base_en
        assert (base_en & _WRAP0_BIT) == 0, (
            f"wrap0 already enabled before register TX base=0x{base_en:x}"
        )

        # Bring the LSIO competitor to life BEFORE the mux legs, driving the
        # opposite data value to the one the register path will carry, so every
        # leg below has two distinguishable candidates.
        self._drive_lsio_source(dut, driving=True, data=0)

        await self.csr_write("GPIO0_REG_TX", GPIO0_DATA_CTRL, OUT_REG)
        await self._await_en_bit(dut, 1, "REG")
        await self._check_ctrl_readback("GPIO0_REG_TX_RB", OUT_REG)
        en_reg = self._known_int(dut.tb_core2pad_en_o, "REG_EN") & mask
        self.en_reg = en_reg
        delta = (en_reg ^ base_en) & mask
        assert delta == _WRAP0_BIT, (
            f"register TX did not toggle GPIO0 wrap bit {_WRAP} "
            f"base=0x{base_en:x} en=0x{en_reg:x} delta=0x{delta:x}"
        )
        val_reg = self._known_int(dut.tb_core2pad_o, "REG_VAL")
        assert (val_reg & _WRAP0_BIT) == _WRAP0_BIT, "register TX value not 1"
        cocotb.log.info(
            "CHK-GPIO-P0-MUX-REG: wrap0 core2pad_en delta=0x%x core2pad=0x%x",
            delta,
            val_reg & _WRAP0_BIT,
        )

        # PRIORITY, against a live competitor. `lsio_select` is set as well, and
        # the LSIO source is driving data 0 while the register carries CORE2PAD
        # = 1, so "interface_enable wins" and "lsio_select wins" produce
        # DIFFERENT pad data; with the SPI source parked both would produce the
        # same value.
        await self.csr_write("GPIO0_REG_WINS", GPIO0_DATA_CTRL, OUT_REG_WITH_LSIO)
        await self._await_en_bit(dut, 1, "PRIO")
        await self._check_ctrl_readback("GPIO0_REG_WINS_RB", OUT_REG_WITH_LSIO)
        en_both = self._known_int(dut.tb_core2pad_en_o, "PRIO_EN") & mask
        self.en_both = en_both
        assert (en_both & _WRAP0_BIT) == _WRAP0_BIT, (
            "lsio_select overrode interface_enable (register TX enable dropped)"
        )
        val_both = self._known_int(dut.tb_core2pad_o, "PRIO_VAL")
        assert (val_both & _WRAP0_BIT) == _WRAP0_BIT, (
            f"wrap{_WRAP} core2pad followed the LSIO source (0) instead of the "
            f"register CORE2PAD (1) while both interface_enable and lsio_select "
            f"were set: lsio_select outranked interface_enable"
        )
        cocotb.log.info(
            "CHK-GPIO-P0-MUX-PRIO: with interface_enable AND lsio_select both "
            "set and the LSIO source driving 0, wrap%d kept the register value "
            "core2pad=%d en=%d -- the register interface outranks a live "
            "lsio_select",
            _WRAP,
            (val_both >> _WRAP) & 1,
            (en_both >> _WRAP) & 1,
        )

        # LSIO ROUTING, the positive control for the select bit itself.
        # interface_enable is cleared and CORE2PAD is left at 0, so the register
        # path contributes en=0 / data=0. No hardware LSIO request is raised
        # (lsio_enable reads clear), and the LSIO source is driving, so a live
        # select bit gives en=1 and a select bit tied to 0 gives en=0.
        await self.csr_write("GPIO0_LSIO", GPIO0_DATA_CTRL, OUT_LSIO_ONLY)
        await self._await_en_bit(dut, 1, "LSIO")
        await self._check_ctrl_readback("GPIO0_LSIO_RB", OUT_LSIO_ONLY)
        en_lsio = self._known_int(dut.tb_core2pad_en_o, "LSIO_EN") & mask
        self.en_lsio = en_lsio
        assert (en_lsio & _WRAP0_BIT) == _WRAP0_BIT, (
            f"lsio_select alone did not route the LSIO output enable to wrap"
            f"{_WRAP}: core2pad_en=0x{en_lsio:x}. A select bit tied to 0 gives "
            f"exactly this result, so the mux select is not reaching the mux"
        )
        val_lsio = self._known_int(dut.tb_core2pad_o, "LSIO_VAL")
        self.val_lsio = (val_lsio >> _WRAP) & 1
        assert self.val_lsio == 0, (
            f"wrap{_WRAP} core2pad is {self.val_lsio} but the LSIO source is "
            f"driving 0 and the register CORE2PAD bit is clear"
        )

        # Data routing: flip the LSIO source and require the pad to follow it.
        # A mux that merely enabled the output would not.
        self._drive_lsio_source(dut, driving=True, data=1)
        val_flipped = await self._await_pad_val(dut, 1, "LSIO_FLIP")
        self.val_lsio_flipped = (val_flipped >> _WRAP) & 1
        cocotb.log.info(
            "CHK-GPIO-P0-MUX-LSIO: lsio_select alone routed the LSIO function "
            "to wrap%d -- core2pad_en=%d with the source driving (a select bit "
            "tied to 0 gives 0 here), and core2pad followed the source from %d "
            "to %d when it was flipped",
            _WRAP,
            (en_lsio >> _WRAP) & 1,
            self.val_lsio,
            self.val_lsio_flipped,
        )

        # Restore: register path off, SPI pads back to the idle-safe parking the
        # base test established, and wrap 0 back to its pre-write baseline.
        await self.csr_write("GPIO0_RESTORE", GPIO0_DATA_CTRL, 0)
        self._drive_lsio_source(dut, driving=False, data=0)
        await self._await_en_bit(dut, (base_en >> _WRAP) & 1, "RESTORE")

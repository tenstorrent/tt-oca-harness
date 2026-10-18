# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO DATA_CTRL_ENABLE single-bit writes and DATA_CTRL cross-register isolation.

Sources hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL_ENABLE, DATA_CTRL), integrator GPIO pad table.

Instance 60 is the pad the integrator table reserves. Each DATA_CTRL_ENABLE bit is written
alone, then DATA_CTRL core2pad and DATA_CTRL_ENABLE = 0x31 are written in both orders.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_function
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)
_DATA_CTRL_ENABLE = (
    "gpio_intf/DATA_CTRL_ENABLE",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_ENABLE_REG_ADDR",
)

_INSTANCE = 60
_INSTANCE_FUNCTION = "Reserved"

STEP_ORDER = (
    "BRINGUP_DONE",
    "SINGLE_BIT_READBACKS",
    "CROSS_ORDER_ONE",
    "CROSS_ORDER_TWO",
    "RESTORE_READBACK",
)
CHK_ORDER = (
    ("SINGLE_BIT_READBACKS", "CHK-GPIO-ENABLE-BITS-ALONE"),
    ("CROSS_ORDER_TWO", "CHK-GPIO-ENABLE-CROSS-REGISTER"),
)


class smc_gpio_data_ctrl_enable_fields_test_seq(SmcCsrSeq):
    """Write DATA_CTRL_ENABLE bits alone and against DATA_CTRL on instance 60."""

    def __init__(self, name: str = "smc_gpio_data_ctrl_enable_fields_test_seq") -> None:
        super().__init__(name)
        self.bits_driven = 0
        self.orders_driven = 0
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read(self, label: str, inst: RegInstance) -> int:
        got = await self.csr_read(f"GPIO{_INSTANCE}_{label}", inst.addr)
        assert isinstance(got, int), f"{label}: unresolved read data {got!r}"
        return got

    async def _single_bits(self, en: RegInstance, bits: dict[str, int]) -> str:
        parts = []
        for name, mask in bits.items():
            await self.csr_write(f"GPIO{_INSTANCE}_{name}_SET", en.addr, mask)
            got = await self._read(f"{name}_RB", en)
            assert got == mask, (
                f"GPIO {_INSTANCE} DATA_CTRL_ENABLE after writing {name} alone reads "
                f"0x{got:08x}, expected 0x{mask:08x}"
            )
            parts.append(f"{name}=0x{got:x}")
            self.bits_driven += 1
            await self.csr_write(f"GPIO{_INSTANCE}_{name}_CLR", en.addr, 0)
            back = await self._read(f"{name}_CLR_RB", en)
            assert back == 0, f"DATA_CTRL_ENABLE after restoring {name} reads 0x{back:08x}"
        assert self.bits_driven == 3, f"{self.bits_driven} of 3 bits driven"
        return ", ".join(parts)

    async def _cross(self, dc: RegInstance, en: RegInstance, order: str, first_dc: bool) -> str:
        c2p = 1
        en_word = 0x31
        rw = dc.reg.rw_mask
        dc_reset = dc.reg.reset_word & rw
        en_reset = en.reg.reset_word
        writes = [("DC", dc, c2p), ("EN", en, en_word)]
        if not first_dc:
            writes.reverse()
        seen: dict[str, int] = {}
        for tag, inst, word in writes:
            await self.csr_write(f"GPIO{_INSTANCE}_{order}_{tag}_WR", inst.addr, word)
            seen[tag] = await self._read(f"{order}_{tag}_RB", inst)
            if tag == "DC":
                assert seen[tag] & rw == c2p, (
                    f"{order}: DATA_CTRL after its write reads 0x{seen[tag] & rw:08x}, "
                    f"expected 0x{c2p:08x}"
                )
            else:
                assert seen[tag] == en_word, (
                    f"{order}: DATA_CTRL_ENABLE after its write reads 0x{seen[tag]:08x}, "
                    f"expected 0x{en_word:08x}"
                )
        dc_after = await self._read(f"{order}_DC_FINAL", dc)
        en_after = await self._read(f"{order}_EN_FINAL", en)
        assert dc_after & rw == c2p, (
            f"{order}: DATA_CTRL reads 0x{dc_after & rw:08x} after both writes, expected "
            f"0x{c2p:08x}; the DATA_CTRL_ENABLE write disturbed it"
        )
        assert en_after == en_word, (
            f"{order}: DATA_CTRL_ENABLE reads 0x{en_after:08x} after both writes, expected "
            f"0x{en_word:08x}; the DATA_CTRL write disturbed it"
        )
        await self.csr_write(f"GPIO{_INSTANCE}_{order}_DC_CLR", dc.addr, dc.reg.reset_word)
        await self.csr_write(f"GPIO{_INSTANCE}_{order}_EN_CLR", en.addr, en_reset)
        dc_back = await self._read(f"{order}_DC_CLR_RB", dc)
        en_back = await self._read(f"{order}_EN_CLR_RB", en)
        assert dc_back & rw == dc_reset, f"{order}: DATA_CTRL restore reads 0x{dc_back & rw:08x}"
        assert en_back == en_reset, f"{order}: DATA_CTRL_ENABLE restore reads 0x{en_back:08x}"
        self.orders_driven += 1
        return f"{order} DATA_CTRL_ENABLE=0x{en_after:x} DATA_CTRL_rw=0x{dc_after & rw:x}"

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP_DONE < SINGLE_BIT_READBACKS < CROSS_ORDER_ONE < "
            "CROSS_ORDER_TWO < RESTORE_READBACK; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        function = pad_function(_INSTANCE)
        assert function == _INSTANCE_FUNCTION, (
            f"the integrator pad table gives pad {_INSTANCE} the function {function!r}, not "
            f"{_INSTANCE_FUNCTION!r}"
        )
        dc = reg_instances(*_DATA_CTRL)[_INSTANCE]
        en = reg_instances(*_DATA_CTRL_ENABLE)[_INSTANCE]
        fields = {f.name: f.mask for f in en.reg.fields}
        bits = {n: fields[n] for n in ("use_reg_core2pad", "use_reg_tx", "use_reg_rx")}
        assert tuple(bits.values()) == (0x1, 0x10, 0x20), f"field masks {bits}"
        idle_dc = await self._read("DC_IDLE", dc)
        idle_en = await self._read("EN_IDLE", en)
        assert idle_dc & dc.reg.rw_mask == dc.reg.reset_word & dc.reg.rw_mask, (
            f"DATA_CTRL reads 0x{idle_dc:08x} before any write"
        )
        assert idle_en == en.reg.reset_word, f"DATA_CTRL_ENABLE reads 0x{idle_en:08x} at start"
        self._mark("BRINGUP_DONE")

        single = await self._single_bits(en, bits)
        self._mark("SINGLE_BIT_READBACKS")
        self._chk(
            "SINGLE_BIT_READBACKS",
            "CHK-GPIO-ENABLE-BITS-ALONE",
            f"on GPIO instance {_INSTANCE} each DATA_CTRL_ENABLE bit written alone read back "
            f"exactly itself ({single}), the other two bits clear, and 0x0 after each restore",
        )

        one = await self._cross(dc, en, "ORDER_DC_FIRST", True)
        self._mark("CROSS_ORDER_ONE")
        two = await self._cross(dc, en, "ORDER_EN_FIRST", False)
        self._mark("CROSS_ORDER_TWO")
        self._chk(
            "CROSS_ORDER_TWO",
            "CHK-GPIO-ENABLE-CROSS-REGISTER",
            f"on GPIO instance {_INSTANCE} in both orders DATA_CTRL_ENABLE read 0x31 and the "
            f"writable DATA_CTRL bits read 0x1 with neither disturbed by the other's write "
            f"({one}; {two})",
        )

        final_dc = await self._read("DC_END", dc)
        final_en = await self._read("EN_END", en)
        assert final_dc & dc.reg.rw_mask == dc.reg.reset_word & dc.reg.rw_mask
        assert final_en == en.reg.reset_word
        self._mark("RESTORE_READBACK")
        assert self.orders_driven == 2, f"{self.orders_driven} of 2 orders exercised"
        self._nonvac()

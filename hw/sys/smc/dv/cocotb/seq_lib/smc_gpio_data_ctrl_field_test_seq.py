# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One GPIO DATA_CTRL, one field at a time, on a pad nothing else uses.

`smc_gpio_intf_regblock_sweep_test` cycles `DATA_CTRL_ENABLE` and
`ACCESS_FILTER` on every GPIO_INTF instance but leaves `DATA_CTRL` at its reset
word, because writing it moves the pad mux and can drive the pad. So the write
side of its seven software-writable fields has never run.

This leaf writes them, with the smallest footprint that reaches them: **one
instance, one field at a time, each field set and put straight back to its
reset with a read-back on either side, and nothing held between fields.** At no
point is more than one field off its reset value.

**The instance is GPIO 60, and it is idle by construction.** `smc_padring.sv`
gives a function to every index except 13, 14, 17, 18, 21, 22, 25, 26, 52, 59
and 60: SPI takes 0-10, the UARTs 11, 12, 15, 16, 19, 20, 23 and 24, I3C 27-36,
I2C 37-48, and the remaining named pads 49-51 and 53-58 and 61-64 carry boot,
OCCP, cool reset and the rest. Index 60 is in none of them, `tb_top.sv` never
names it -- it is not in the testbench's pad table and nothing drives or
observes it -- and the only `DATA_CTRL` index any other leaf touches is 0.

**What the pad does during the cycle: nothing.** `gpio.sv` builds the output
enable as `lsio_pin ? ~lsio_core2pad_en_ni : sel_reg_tx ? enable_rx_tx[0] :
lsio_sw ? ~lsio_core2pad_en_ni : 1'b0`, where `lsio_pin` is
`lsio_interface_select_i && ~lsio_disable` and `sel_reg_tx` is
`interface_enable || use_reg_tx`. For index 60 the padring leaves both LSIO
inputs at the defaults it assigns at the top of its comb block --
`lsio_interface_select_o = '0` and `lsio_core2pad_en_n = DISABLED`, which
`smc_padring_pkg` defines as `1'b1` -- so `lsio_pin` is 0 and both LSIO
branches give an output enable of 0. The only branch that can drive the pad is
`sel_reg_tx && enable_rx_tx[0]`, and that needs **two** fields off their reset
at once: `enable_rx_tx` and either `interface_enable` or
`DATA_CTRL_ENABLE.use_reg_tx`. One field at a time is exactly what makes that
unreachable, so the output enable is 0 at every step of this leaf and the pad
stays in its reset drive state throughout.

The order still puts the fields that cannot touch the pad mux first --
`interrupt_enable`, `interrupt_type`, `core2pad`, `enable_rx_tx` -- then
`lsio_disable`, which only ever withdraws LSIO ownership, then `lsio_select`
and `interface_enable` last. The leaf reads the register against its RDL reset
before it starts and again at the end.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)

# The GPIO index this leaf drives. `smc_padring.sv` assigns no LSIO function to
# it, `tb_top.sv` never names it, and no other leaf writes a DATA_CTRL but
# index 0.
_INSTANCE = 60

# Fields in the order they are driven: the four that cannot reach the pad mux,
# then the LSIO ownership fields with `lsio_disable` -- which only withdraws
# ownership -- ahead of `lsio_select` and `interface_enable`.
_ORDER = (
    "interrupt_enable",
    "interrupt_type",
    "core2pad",
    "enable_rx_tx",
    "lsio_disable",
    "lsio_select",
    "interface_enable",
)

# Accesses one field costs: the write that sets it, the read that proves it
# landed, the write that puts it back and the read that proves the register is
# at its reset again.
_ACCESSES_PER_FIELD = 4


class smc_gpio_data_ctrl_field_test_seq(SmcCsrSeq):
    """Drive each DATA_CTRL field of one idle GPIO instance on its own."""

    def __init__(self, name: str = "smc_gpio_data_ctrl_field_test_seq") -> None:
        super().__init__(name)
        self.fields_driven = 0

    async def _field_leg(self, inst: RegInstance, name: str, mask: int) -> None:
        reset = inst.reg.reset_word
        word = reset | mask
        assert word != reset, f"{name}: the field is already set in the RDL reset"

        await self.csr_write(f"GPIO{_INSTANCE}_{name}_SET", inst.addr, word)
        got = await self.csr_read(f"GPIO{_INSTANCE}_{name}_SET_RB", inst.addr)
        assert got & inst.reg.rw_mask == word & inst.reg.rw_mask, (
            f"GPIO {_INSTANCE} DATA_CTRL after writing {name}: the software-writable bits "
            f"read 0x{got & inst.reg.rw_mask:08x}, 0x{word & inst.reg.rw_mask:08x} was "
            f"written"
        )
        assert got & ~inst.reg.declared_mask & 0xFFFF_FFFF == 0, (
            f"GPIO {_INSTANCE} DATA_CTRL reads 0x{got:08x} with {name} set, which drives "
            f"bits no field of the register occupies"
        )

        await self.csr_write(f"GPIO{_INSTANCE}_{name}_CLR", inst.addr, reset)
        back = await self.csr_read(f"GPIO{_INSTANCE}_{name}_CLR_RB", inst.addr)
        assert back & inst.reg.rw_mask == reset & inst.reg.rw_mask, (
            f"GPIO {_INSTANCE} DATA_CTRL after putting {name} back: the software-writable "
            f"bits read 0x{back & inst.reg.rw_mask:08x}, the RDL reset is "
            f"0x{reset & inst.reg.rw_mask:08x}"
        )
        self.fields_driven += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        instances = reg_instances(*_DATA_CTRL)
        assert _INSTANCE < len(instances), (
            f"the generated map declares {len(instances)} DATA_CTRL instances, so there is "
            f"no index {_INSTANCE}"
        )
        inst = instances[_INSTANCE]

        by_name = {field.name: field for field in inst.reg.fields}
        writable = {name for name, field in by_name.items() if field.plain_rw}
        assert set(_ORDER) == writable, (
            f"this leaf drives {sorted(_ORDER)} but the generated contract makes "
            f"{sorted(writable)} software-writable with a pinned readback"
        )

        idle = await self.csr_read(f"GPIO{_INSTANCE}_IDLE", inst.addr)
        assert idle & inst.reg.rw_mask == inst.reg.reset_word & inst.reg.rw_mask, (
            f"GPIO {_INSTANCE} DATA_CTRL reads 0x{idle:08x} before this leaf wrote it; its "
            f"RDL reset is 0x{inst.reg.reset_word:08x}, so the instance is not idle and "
            f"something else owns it"
        )

        for name in _ORDER:
            await self._field_leg(inst, name, by_name[name].mask)

        assert self.fields_driven == len(_ORDER), (
            f"{self.fields_driven} of {len(_ORDER)} fields driven"
        )
        floor = 1 + len(_ORDER) * _ACCESSES_PER_FIELD
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; {len(_ORDER)} fields "
            f"cannot have taken fewer than {floor}"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-GPIO-DATA-CTRL-FIELDS: on GPIO instance %d, which the padring gives no "
            "LSIO function and the testbench never drives, each of the %d software-writable "
            "DATA_CTRL fields was set on its own and put straight back to its reset, with "
            "the whole register read after each write; no field was ever set alongside "
            "another, which is what keeps the pad output enable at 0 throughout, and the "
            "register began and ended at its RDL reset",
            _INSTANCE,
            self.fields_driven,
        )

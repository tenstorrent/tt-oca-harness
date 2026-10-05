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

**The instance is a pad the integrator table reserves.** The integrator pad
table (`doc/integrator/meta/ocah_gpio_table.csv`) assigns a function to every
pad; its row for index 60 reads "Reserved", so no peripheral owns the pad and
the bench pad table (`tb/tb_top.sv`) names no function on it either. The only
`DATA_CTRL` index any other leaf writes is 0. The leaf reads the register
against its RDL reset before it starts and again at the end.

**What the pad does during the cycle is measured, not assumed.** The GPIO
ownership table (`hw/ip/gpio/doc/architecture.adoc`, "Data and Direction
Ownership") gives the transmit enable to the hardware LSIO request first, then
to `enable_rx_tx[0]` when `interface_enable` or `use_reg_tx` selects the
register, then to the LSIO inputs when `lsio_select` forces them, and
otherwise disables it. With one field off its reset at a time the register
row needs two fields at once and is unreachable, and the bench never raises a
hardware LSIO request. The `lsio_select` step hands the pad to its LSIO
inputs, and no document states what the LSIO plane carries on a Reserved pad:
the bench records that as a DV-owned fact (`RESERVED_PAD_LSIO_TX_ENABLE`) and
samples the pad's `core2pad_en_o` bit after every write, so a pad that drove
during any step fails here rather than being argued away.

The order still puts the fields that cannot touch the pad mux first --
`interrupt_enable`, `interrupt_type`, `core2pad`, `enable_rx_tx` -- then
`lsio_disable`, which only ever withdraws LSIO ownership, then `lsio_select`
and `interface_enable` last.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_function
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)

# The GPIO index this leaf drives: a pad the integrator pad table reserves, so
# no peripheral function owns it. `body` checks the table still says so.
_INSTANCE = 60
_INSTANCE_FUNCTION = "Reserved"

# The transmit enable a Reserved pad presents while `lsio_select` hands it to
# its LSIO inputs. No specification states what the LSIO plane carries on a
# pad the table reserves; the bench takes it as not driving, and measures it.
RESERVED_PAD_LSIO_TX_ENABLE = 0

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

    @staticmethod
    def _tx_enable() -> int:
        """The pad's bit of `core2pad_en_o`, mirrored on `tb_core2pad_en_o`."""
        raw = cocotb.top.tb_core2pad_en_o.value
        assert raw.is_resolvable, f"tb_core2pad_en_o is X/Z: {raw}"
        return (int(raw) >> _INSTANCE) & 1

    def _require_pad_idle(self, step: str) -> None:
        oe = self._tx_enable()
        assert oe == RESERVED_PAD_LSIO_TX_ENABLE, (
            f"GPIO {_INSTANCE} core2pad_en_o reads {oe} {step}; the pad drove while this leaf "
            f"held one DATA_CTRL field off its reset, so the pad did not stay in its reset "
            f"drive state"
        )

    async def _field_leg(self, inst: RegInstance, name: str, mask: int) -> None:
        reset = inst.reg.reset_word
        word = reset | mask
        assert word != reset, f"{name}: the field is already set in the RDL reset"

        await self.csr_write(f"GPIO{_INSTANCE}_{name}_SET", inst.addr, word)
        got = await self.csr_read(f"GPIO{_INSTANCE}_{name}_SET_RB", inst.addr)
        self._require_pad_idle(f"with {name} set")
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
        self._require_pad_idle(f"after {name} was put back")
        assert back & inst.reg.rw_mask == reset & inst.reg.rw_mask, (
            f"GPIO {_INSTANCE} DATA_CTRL after putting {name} back: the software-writable "
            f"bits read 0x{back & inst.reg.rw_mask:08x}, the RDL reset is "
            f"0x{reset & inst.reg.rw_mask:08x}"
        )
        self.fields_driven += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        function = pad_function(_INSTANCE)
        assert function == _INSTANCE_FUNCTION, (
            f"the integrator pad table gives pad {_INSTANCE} the function {function!r}, not "
            f"{_INSTANCE_FUNCTION!r}; this leaf drives a pad no peripheral owns"
        )

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
        self._require_pad_idle("before the first field was written")

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
            "CHK-GPIO-DATA-CTRL-FIELDS: on GPIO instance %d, which the integrator pad table "
            "marks %s and the testbench never drives, each of the %d software-writable "
            "DATA_CTRL fields was set on its own and put straight back to its reset, with "
            "the whole register read after each write; no field was ever set alongside "
            "another, the pad's core2pad_en_o bit read %d after every write, and the "
            "register began and ended at its RDL reset",
            _INSTANCE,
            function,
            self.fields_driven,
            RESERVED_PAD_LSIO_TX_ENABLE,
        )

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO DATA_CTRL field values, read-modify-write isolation and Programmer's Guide constants.

Contract SMC_GPIO_CSR_008, anchor smc_gpio_data_ctrl_rw_values_test.
Scenarios GPIO-CSR-DATA-CTRL-RW.S2, S3, S4 and S5.
Sources hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL), doc/programmer/src/smc-programming.adoc.

Instance 60 is the pad the integrator table reserves. Every access is a whole-word write of
the software-writable bits; DATA_CTRL is restored to its reset word after each phase.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_function
from .smc_probe_positive_control import _pad_vec
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)

_INSTANCE = 60
_INSTANCE_FUNCTION = "Reserved"
_RW_FIELDS = (
    "core2pad",
    "enable_rx_tx",
    "interface_enable",
    "lsio_select",
    "interrupt_enable",
    "lsio_disable",
    "interrupt_type",
)
_BASE = {
    "core2pad": 1,
    "enable_rx_tx": 1,
    "interface_enable": 1,
    "lsio_select": 1,
    "interrupt_enable": 1,
    "lsio_disable": 1,
    "interrupt_type": 2,
}
_NEW = {
    "core2pad": 0,
    "enable_rx_tx": 2,
    "interface_enable": 0,
    "lsio_select": 0,
    "interrupt_enable": 0,
    "lsio_disable": 0,
    "interrupt_type": 1,
}
_PG_CONSTANTS = (
    (0x1, "core2pad"),
    (0x10, "enable_rx_tx"),
    (0x20, "enable_rx_tx"),
    (0x10000, "interface_enable"),
    (0x40000, "interrupt_enable"),
    (0x200000, "interrupt_type"),
)

STEP_ORDER = (
    "BRINGUP_DONE",
    "RX_TX_VALUES",
    "INTERRUPT_TYPE_VALUES",
    "RMW_ISOLATION",
    "PG_CONSTANTS",
    "RESTORE_READBACK",
)
CHK_ORDER = (
    ("RX_TX_VALUES", "CHK-GPIO-DATA-CTRL-RX-TX-VALUES"),
    ("INTERRUPT_TYPE_VALUES", "CHK-GPIO-DATA-CTRL-INTERRUPT-TYPE-VALUES"),
    ("RMW_ISOLATION", "CHK-GPIO-DATA-CTRL-RMW-ISOLATION"),
    ("PG_CONSTANTS", "CHK-GPIO-DATA-CTRL-PG-CONSTANTS"),
)


class smc_gpio_data_ctrl_rw_values_test_seq(SmcCsrSeq):
    """Write DATA_CTRL field values, read-modify-writes and constants on instance 60."""

    def __init__(self, name: str = "smc_gpio_data_ctrl_rw_values_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.masks: dict[str, int] = {}
        self.rw = 0
        self.reset = 0

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    def _shift(self, field: str) -> int:
        return (self.masks[field] & -self.masks[field]).bit_length() - 1

    def _word(self, **values: int) -> int:
        return sum(v << self._shift(f) for f, v in values.items())

    def _field(self, word: int, field: str) -> int:
        return (word & self.masks[field]) >> self._shift(field)

    async def _read(self, label: str, dc: RegInstance) -> int:
        got = await self.csr_read(f"GPIO{_INSTANCE}_{label}", dc.addr)
        assert isinstance(got, int), f"{label}: unresolved read data {got!r}"
        return got

    async def _write_read(self, label: str, dc: RegInstance, word: int) -> int:
        await self.csr_write(f"GPIO{_INSTANCE}_{label}_WR", dc.addr, word)
        return await self._read(f"{label}_RB", dc)

    async def _restore(self, label: str, dc: RegInstance) -> None:
        got = await self._write_read(f"{label}_RESTORE", dc, self.reset)
        assert got & self.rw == self.reset & self.rw, (
            f"{label}: DATA_CTRL restore reads 0x{got & self.rw:08x}"
        )

    async def _values(self, dc: RegInstance, field: str) -> str:
        parts = []
        for value in range(4):
            got = await self._write_read(f"{field}_{value}", dc, self._word(**{field: value}))
            assert got & self.rw == self._word(**{field: value}), (
                f"DATA_CTRL after {field}={value} reads 0x{got & self.rw:08x}, expected "
                f"0x{self._word(**{field: value}):08x}"
            )
            assert self._field(got, field) == value, f"{field} reads {self._field(got, field)}"
            parts.append(f"{value}->0x{got & self.rw:x}")
        await self._restore(field, dc)
        return ", ".join(parts)

    async def _rmw(self, dc: RegInstance) -> str:
        base = self._word(**_BASE)
        got = await self._write_read("BASE", dc, base)
        assert got & self.rw == base, f"base pattern reads 0x{got & self.rw:08x}, wrote 0x{base:x}"
        parts = []
        exercised = 0
        for field in _RW_FIELDS:
            assert _NEW[field] != _BASE[field], field
            cur = await self._read(f"{field}_RMW_RD", dc)
            assert cur & self.rw == base, f"{field}: pre-read 0x{cur & self.rw:08x} != base"
            word = (cur & self.rw & ~self.masks[field]) | self._word(**{field: _NEW[field]})
            got = await self._write_read(f"{field}_RMW", dc, word)
            assert self._field(got, field) == _NEW[field], (
                f"{field} reads {self._field(got, field)}, expected {_NEW[field]}"
            )
            for other in _RW_FIELDS:
                if other != field:
                    assert self._field(got, other) == _BASE[other], (
                        f"RMW of {field} changed {other} to {self._field(got, other)}"
                    )
            assert got & self.rw == word, f"{field}: word 0x{got & self.rw:08x} != 0x{word:08x}"
            parts.append(f"{field}={_BASE[field]}->{self._field(got, field)}")
            exercised += 1
            await self.csr_write(f"GPIO{_INSTANCE}_{field}_RMW_BASE", dc.addr, base)
        assert exercised == 7, f"{exercised} of 7 fields exercised"
        await self._restore("RMW", dc)
        return ", ".join(parts)

    async def _constants(self, dc: RegInstance) -> str:
        parts = []
        for const, field in _PG_CONSTANTS:
            got = await self._write_read(f"PG_0x{const:x}", dc, const)
            assert got & self.rw == const, f"constant 0x{const:x} reads 0x{got & self.rw:08x}"
            assert const & self.masks[field] == const, f"0x{const:x} is not inside {field}"
            owners = [f for f, m in self.masks.items() if got & self.rw & m]
            assert owners == [field], f"constant 0x{const:x} sets fields {owners}"
            parts.append(f"0x{const:x}->{field}")
            await self._restore(f"PG_0x{const:x}", dc)
        assert len(parts) == 6, f"{len(parts)} of 6 constants driven"
        return ", ".join(parts)

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP_DONE < RX_TX_VALUES < INTERRUPT_TYPE_VALUES < "
            "RMW_ISOLATION < PG_CONSTANTS < RESTORE_READBACK; checker lines %s; stamps %s",
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
        self.masks = {f.name: f.mask for f in dc.reg.fields if f.name in _RW_FIELDS}
        assert tuple(self.masks) == _RW_FIELDS or set(self.masks) == set(_RW_FIELDS), self.masks
        self.rw = dc.reg.rw_mask
        self.reset = dc.reg.reset_word & self.rw
        assert self.rw == sum(self.masks.values()), f"rw mask 0x{self.rw:x} vs {self.masks}"
        dut = cocotb.top
        assert hasattr(dut, "tb_core2pad_en_o"), "tb_core2pad_en_o is not exported"
        idle = await self._read("DC_IDLE", dc)
        assert idle & self.rw == self.reset, f"DATA_CTRL reads 0x{idle:08x} before any write"
        self._mark("BRINGUP_DONE")

        rxtx = await self._values(dc, "enable_rx_tx")
        en_bit = (_pad_vec(dut, "tb_core2pad_en_o") >> _INSTANCE) & 1
        self._mark("RX_TX_VALUES")
        self._chk(
            "RX_TX_VALUES",
            "CHK-GPIO-DATA-CTRL-RX-TX-VALUES",
            f"on GPIO instance {_INSTANCE} enable_rx_tx read back exactly the written value "
            f"with no other writable bit set ({rxtx}); tb_core2pad_en_o[{_INSTANCE}] sampled "
            f"after restore = {en_bit}",
        )

        itype = await self._values(dc, "interrupt_type")
        self._mark("INTERRUPT_TYPE_VALUES")
        self._chk(
            "INTERRUPT_TYPE_VALUES",
            "CHK-GPIO-DATA-CTRL-INTERRUPT-TYPE-VALUES",
            f"on GPIO instance {_INSTANCE} interrupt_type read back exactly the written value "
            f"with no other writable bit set ({itype})",
        )

        rmw = await self._rmw(dc)
        self._mark("RMW_ISOLATION")
        self._chk(
            "RMW_ISOLATION",
            "CHK-GPIO-DATA-CTRL-RMW-ISOLATION",
            f"on GPIO instance {_INSTANCE} each of 7 fields changed alone from base "
            f"0x{self._word(**_BASE):x} with the other six unchanged ({rmw})",
        )

        consts = await self._constants(dc)
        self._mark("PG_CONSTANTS")
        self._chk(
            "PG_CONSTANTS",
            "CHK-GPIO-DATA-CTRL-PG-CONSTANTS",
            f"on GPIO instance {_INSTANCE} each Programmer's Guide constant read back as "
            f"exactly itself in the named field ({consts})",
        )

        final = await self._read("DC_END", dc)
        assert final & self.rw == self.reset, f"DATA_CTRL reads 0x{final:08x} at the end"
        self._mark("RESTORE_READBACK")
        self._nonvac()

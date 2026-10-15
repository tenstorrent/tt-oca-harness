# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every DATA_CTRL field written and the pad driven both ways on every GPIO_INTF instance.

`smc_gpio_intf_regblock_sweep_test` cycles the other two registers of the block
on every instance; this sequence writes `DATA_CTRL` there and takes each
instance through one cycle:

* the register read at its reset, recording the hardware LSIO request status
  (`lsio_enable`), which the pad's function fixes for the whole run;
* `lsio_select` set on its own: the software select ranks below the hardware
  request, so the status reads what it read at reset;
* register control of the receiver with `lsio_disable` set, which withdraws
  the hardware request on every pad so the status reads 0, then the pad driven
  from the bench through each interrupt type: the two level types follow the
  pad both ways, the two edge types pulse once on their edge, and a cleared
  `interrupt_enable` masks an active level that the next write unmasks;
* the reset word restored, with the status back at its recorded value.

The register never owns the pad driver: `enable_rx_tx` enables the receiver
only, so `core2pad` reaches `core2pad_o` and `core2pad_en_o` stays 0. Every
readback after the reset read carries a fully predicted word, `lsio_enable`
and `pad2core` included.

The pad is driven on the bench side of the pad macro. Most pads take
`tb_gpio_ext_drive_*`; the pads `tb_top.sv` drives for a protocol VIP whatever
that enable says (UART0 RX, the I2C0 and I3C0 open-drain lines, AVSBus SDATA
and the two OCTS inject lines) take the bench input that owns them, and are
left at the value `smc_base_test` sets.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import gpio_intf_u32
from .smc_gpio_vip_utils import await_gpio_irq_only, drive_gpio_pad
from .smc_pad_table import AVS_SDATA_PAD, pad_index
from .smc_regblock_field_sweep_utils import RegInstance, SmcRegblockFieldSweepSeq, reg_instances

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)
_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")
_PAD2CORE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")

# The software-writable fields of DATA_CTRL this sequence writes; `body` holds
# the generated contract to the same set.
_FIELDS = frozenset(
    (
        "core2pad",
        "enable_rx_tx",
        "interface_enable",
        "lsio_select",
        "interrupt_enable",
        "lsio_disable",
        "interrupt_type",
    )
)

# interrupt_type encodings, as gpio_intf.rdl defines them.
_ACTIVE_HIGH = 0
_ACTIVE_LOW = 1
_RISING_EDGE = 2
_FALLING_EDGE = 3

# enable_rx_tx with the receiver enabled and the driver disabled.
_RX_ONLY = 2

# Pads tb_top.sv drives for a protocol VIP regardless of tb_gpio_ext_drive_en,
# keyed by pad index: the bench input that sets the pad, whether a 1 on that
# input pulls the pad low, and the value smc_base_test leaves on it.
_BENCH_OWNED_PADS: dict[int, tuple[str, bool, int]] = {
    pad_index("UART[0].RX"): ("tb_uart0_rx_ext_drive", False, 1),
    pad_index("I3C[0] SCL"): ("tb_i3c0_scl_ext_low", True, 0),
    pad_index("I3C[0] SDA"): ("tb_i3c0_sda_ext_low", True, 0),
    pad_index("I2C[0] SCL"): ("tb_i2c0_scl_ext_low", True, 0),
    pad_index("I2C[0] SDA"): ("tb_i2c0_sda_ext_low", True, 0),
    AVS_SDATA_PAD: ("tb_avs_sdata_ext", False, 1),
    pad_index("System Timer Sync Load"): ("tb_octs_sync_load_ext", False, 0),
    pad_index("System Timer Credit Count"): ("tb_octs_cnt_credit_ext", False, 0),
}

# Cycles a level interrupt is re-checked once it has reached the expected value.
_LEVEL_HOLD_CYCLES = 4

# SEP_IN accesses per instance: the reset read; a write and readback for the
# lsio_select word; the active-high write with a readback at each pad level; a
# write and readback for each of active-low, rising edge, falling edge, the
# masked level and the unmasked level; the restore write and readback.
_ACCESSES_PER_INSTANCE = 18
# Every readback but the reset read carries a fully predicted word.
_PREDICTED_READS_PER_INSTANCE = 9


class smc_gpio_intf_data_ctrl_write_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Write every DATA_CTRL field and drive the pad both ways on every GPIO_INTF instance."""

    def __init__(self, name: str = "smc_gpio_intf_data_ctrl_write_sweep_test_seq") -> None:
        super().__init__(name)
        self.lsio_requests = 0
        self.pulse_widths: set[int] = set()

    @staticmethod
    def _drive_pad(dut, wrap: int, level: int | None) -> None:
        owned = _BENCH_OWNED_PADS.get(wrap)
        if owned is None:
            drive_gpio_pad(dut, wrap, level)
            return
        signal, active_low, released = owned
        if level is None:
            value = released
        else:
            value = level ^ 1 if active_low else level
        getattr(dut, signal).value = value

    @staticmethod
    def _port_bit(dut, name: str, wrap: int) -> int:
        raw = getattr(dut, name).value
        assert raw.is_resolvable, f"{name} is not resolvable (X/Z): {raw}"
        return (int(raw) >> wrap) & 1

    def _register_word(self, inst: RegInstance, interrupt_type: int, interrupt_enable: int) -> int:
        return self.pack_fields(
            inst,
            core2pad=1,
            enable_rx_tx=_RX_ONLY,
            interface_enable=1,
            lsio_disable=1,
            interrupt_enable=interrupt_enable,
            interrupt_type=interrupt_type,
        )

    async def _read_word(
        self, inst: RegInstance, label: str, rw_word: int, lsio_enable: int, pad2core: int
    ) -> int:
        """Read one instance against a fully predicted word."""
        word = rw_word & inst.reg.rw_mask
        word |= _LSIO_ENABLE if lsio_enable else 0
        word |= _PAD2CORE if pad2core else 0
        got = await self.csr_read(f"{inst.label}:{label}", inst.addr, expected=word)
        assert got == word, (
            f"{inst.label} @ 0x{inst.addr:08x} [{label}]: read 0x{got:08x}, the contract "
            f"predicts 0x{word:08x} (software-writable bits 0x{word & inst.reg.rw_mask:08x}, "
            f"lsio_enable={lsio_enable}, pad2core={pad2core})"
        )
        self.value_checks += 1
        return got

    def _require_receiver(self, inst: RegInstance, dut) -> None:
        wrap = inst.index
        assert self._port_bit(dut, "tb_pad2core_en_o", wrap) == 1, (
            f"{inst.label}: pad2core_en_o[{wrap}] is 0 while the register enables the receiver"
        )
        assert self._port_bit(dut, "tb_core2pad_o", wrap) == 1, (
            f"{inst.label}: core2pad_o[{wrap}] is 0 while the register owns core2pad with the "
            f"field set"
        )
        assert self._port_bit(dut, "tb_core2pad_en_o", wrap) == 0, (
            f"{inst.label}: core2pad_en_o[{wrap}] is 1 while enable_rx_tx enables the receiver "
            f"only, so the register drove the pad"
        )

    async def _await_pulse(self, inst: RegInstance, dut, label: str) -> None:
        wrap = inst.index
        await await_gpio_irq_only(dut, wrap, 1, f"{inst.label}:{label} pulse")
        width = await await_gpio_irq_only(
            dut, wrap, 0, f"{inst.label}:{label} pulse end", hold=_LEVEL_HOLD_CYCLES
        )
        self.pulse_widths.add(width)

    async def _instance_cycle(self, inst: RegInstance, dut) -> None:
        wrap = inst.index
        reg = inst.reg
        reset = reg.reset_word

        idle = await self.csr_read(f"{inst.label}:reset", inst.addr)
        assert idle & reg.rw_mask == reset & reg.rw_mask, (
            f"{inst.label} @ 0x{inst.addr:08x}: reads 0x{idle:08x} before this sequence wrote "
            f"it; the RDL reset is 0x{reset:08x}, so the instance is not idle"
        )
        assert idle & ~reg.declared_mask & self.word_mask(inst) == 0, (
            f"{inst.label} @ 0x{inst.addr:08x}: reads 0x{idle:08x}, which drives bits no field "
            f"of the register occupies"
        )
        assert idle & _PAD2CORE == 0, (
            f"{inst.label}: pad2core reads 1 while the register does not own the receiver"
        )
        lsio_request = 1 if idle & _LSIO_ENABLE else 0
        self.lsio_requests += lsio_request

        word = self.pack_fields(inst, lsio_select=1)
        await self.csr_write(f"{inst.label}:lsio_select", inst.addr, word)
        await self._read_word(inst, "lsio_select", word, lsio_request, 0)

        self._drive_pad(dut, wrap, 0)
        word = self._register_word(inst, _ACTIVE_HIGH, 1)
        await self.csr_write(f"{inst.label}:active_high", inst.addr, word)
        await await_gpio_irq_only(
            dut, wrap, 0, f"{inst.label}:active_high pad low", _LEVEL_HOLD_CYCLES
        )
        await self._read_word(inst, "active_high:pad_low", word, 0, 0)
        self._require_receiver(inst, dut)
        self._drive_pad(dut, wrap, 1)
        await await_gpio_irq_only(
            dut, wrap, 1, f"{inst.label}:active_high pad high", _LEVEL_HOLD_CYCLES
        )
        await self._read_word(inst, "active_high:pad_high", word, 0, 1)

        word = self._register_word(inst, _ACTIVE_LOW, 1)
        await self.csr_write(f"{inst.label}:active_low", inst.addr, word)
        await await_gpio_irq_only(
            dut, wrap, 0, f"{inst.label}:active_low pad high", _LEVEL_HOLD_CYCLES
        )
        await self._read_word(inst, "active_low", word, 0, 1)
        self._drive_pad(dut, wrap, 0)
        await await_gpio_irq_only(
            dut, wrap, 1, f"{inst.label}:active_low pad low", _LEVEL_HOLD_CYCLES
        )

        word = self._register_word(inst, _RISING_EDGE, 1)
        await self.csr_write(f"{inst.label}:rising_edge", inst.addr, word)
        await await_gpio_irq_only(
            dut, wrap, 0, f"{inst.label}:rising_edge armed", _LEVEL_HOLD_CYCLES
        )
        await self._read_word(inst, "rising_edge", word, 0, 0)
        self._drive_pad(dut, wrap, 1)
        await self._await_pulse(inst, dut, "rising_edge")

        word = self._register_word(inst, _FALLING_EDGE, 1)
        await self.csr_write(f"{inst.label}:falling_edge", inst.addr, word)
        await await_gpio_irq_only(
            dut, wrap, 0, f"{inst.label}:falling_edge armed", _LEVEL_HOLD_CYCLES
        )
        await self._read_word(inst, "falling_edge", word, 0, 1)
        self._drive_pad(dut, wrap, 0)
        await self._await_pulse(inst, dut, "falling_edge")

        word = self._register_word(inst, _ACTIVE_LOW, 0)
        await self.csr_write(f"{inst.label}:masked", inst.addr, word)
        await await_gpio_irq_only(dut, wrap, 0, f"{inst.label}:masked", _LEVEL_HOLD_CYCLES)
        await self._read_word(inst, "masked", word, 0, 0)
        word = self._register_word(inst, _ACTIVE_LOW, 1)
        await self.csr_write(f"{inst.label}:unmasked", inst.addr, word)
        await await_gpio_irq_only(dut, wrap, 1, f"{inst.label}:unmasked", _LEVEL_HOLD_CYCLES)
        await self._read_word(inst, "unmasked", word, 0, 0)

        self._drive_pad(dut, wrap, None)
        await self.csr_write(f"{inst.label}:restore", inst.addr, reset)
        await await_gpio_irq_only(dut, wrap, 0, f"{inst.label}:restore", _LEVEL_HOLD_CYCLES)
        await self._read_word(inst, "restore", reset, lsio_request, 0)
        self.registers_swept += 1

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        instances = reg_instances(*_DATA_CTRL)
        count = len(instances)
        writable = {field.name for field in instances[0].reg.fields if field.plain_rw}
        assert writable == _FIELDS, (
            f"this sequence writes {sorted(_FIELDS)} but the generated contract makes "
            f"{sorted(writable)} software-writable with a pinned readback"
        )
        assert max(_BENCH_OWNED_PADS) < count, (
            f"the bench-owned pads {sorted(_BENCH_OWNED_PADS)} exceed the {count} GPIO_INTF "
            f"instances the generated map declares"
        )
        sb_before = self.env.scoreboard.sys_axi_value_checks_seen

        for inst in instances:
            await self._instance_cycle(inst, dut)

        self.assert_all_reachable(count * _ACCESSES_PER_INSTANCE, "GPIO_INTF_DATA_CTRL_WRITE_SWEEP")
        assert self.registers_swept == count, (
            f"the sweep completed {self.registers_swept} instance cycles for {count} instances"
        )
        booked = self.assert_value_checks(
            sb_before, count * _PREDICTED_READS_PER_INSTANCE, "GPIO_INTF_DATA_CTRL_WRITE_SWEEP"
        )
        assert self.lsio_requests > 0, (
            "no instance read a hardware LSIO request at reset, so the lsio_enable leg "
            "compared nothing"
        )
        cocotb.log.info(
            "CHK-GPIO-INTF-DATA-CTRL-WRITE-SWEEP: %d GPIO_INTF DATA_CTRL instances each read "
            "their RDL reset, took lsio_select on its own, then core2pad, enable_rx_tx, "
            "interface_enable, lsio_disable, interrupt_enable and every interrupt_type value "
            "under register control, and were restored to that reset; every readback matched "
            "its predicted word, with lsio_enable reading 0 under lsio_disable and its reset "
            "value otherwise (%d instances carry a hardware LSIO request); %d contract "
            "compares, %d booked by the scoreboard",
            count,
            self.lsio_requests,
            self.value_checks,
            booked,
        )
        cocotb.log.info(
            "CHK-GPIO-INTF-IRQ-TYPE-SWEEP: on each of %d instances the interrupt bit of that "
            "instance alone followed the pad both ways as active-high and as active-low "
            "level, pulsed once on the rising edge and once on the falling edge (pulse "
            "widths seen: %s clk_smc_i cycles), stayed clear with interrupt_enable clear "
            "while the active-low level was active, and rose when the next write set "
            "interrupt_enable again",
            count,
            sorted(self.pulse_widths),
        )
        cocotb.log.info(
            "CHK-GPIO-INTF-PAD-RECEIVER-SWEEP: on each of %d instances under register control "
            "DATA_CTRL.pad2core read the bench-driven pad level both ways, pad2core_en_o "
            "carried the receiver enable, core2pad_o carried the core2pad field and "
            "core2pad_en_o stayed 0, so the pad was sampled and never driven by the register",
            count,
        )

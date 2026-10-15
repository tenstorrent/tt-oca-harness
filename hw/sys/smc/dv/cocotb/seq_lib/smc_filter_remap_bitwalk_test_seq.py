# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A one and a zero walked across every address bit of the filter and remap tables.

The filter and remap leaves program a handful of fixed regions, so most bits of
`START_ADDR`, `END_ADDR`, `REGION_START` and `REGION_END` only ever hold their
reset value. This leaf walks a one and then a zero across every software-
writable bit of those registers on every entry, reads each register back after
every write and holds it to the contract its RDL states, then restores the RDL
reset so no entry is left programmed.

**Filter address registers.** `filter_ctrl.rdl` makes `start_addr` and
`end_addr` `hw = rw`: hardware writes the range back rounded to the granule
"only when both land in the same granule; otherwise readback returns the
programmed values". The granule is 2^`data_bus_width` bytes while
`allow_burst` is clear, and every entry is held at its `FILTER_CONFIG` reset
(disabled, no burst) for the whole walk, which the leaf reads back before it
starts. The two registers of an entry are walked together, one of them carrying
the one and the other the zero, and the register written first is the one
whose new word keeps the pair apart from the other's old word, so the pair
never shares a granule and every readback is the programmed word; the
rounding case is `smc_filter_region_span_test`.
A disabled entry matches nothing, so the fabric keeps running while its range
is an arbitrary pair, and the restore leg puts the reset range back and reads it.

**Remap table.** `alias_remap.rdl` gives `REGION_START.start_addr` and
`REGION_END.end_addr` bits [55:12] as plain `sw = rw; hw = r` storage. Every
write carries ones in the low twelve bits and the top byte as well, and the
expected readback is the word masked to the field, so the walk shows the
register drops what lands outside it. `REGION_ATTRS.valid` is read clear on every
region before the walk, so no region is live while its bounds move.

**Mailbox data and strobes.** `axil_mailbox.rdl` makes `WRITE_DATA`
`sw = w; onwrite = wuser` and `READ_DATA` `sw = r; onread = ruser`, the
wrapper RDL says the two apertures of a pair share one FIFO, so a word written
through one aperture's `WRITE_DATA` is what the other aperture's `READ_DATA`
returns, and `hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc` states that
inactive byte lanes are written as zero. Each of the 64 apertures takes a walking-one strobe over its eight
byte lanes plus four of the 256 strobe patterns, so every pattern but the empty
one, which the AXI master refuses to drive, is presented once across the
block. The word read back from the paired aperture must carry the written
byte on every strobed lane and zero on every lane the strobe left out. Every
`ERROR_FLAGS` register is read clear afterwards, the sticky threshold
interrupts the pushes raised are acknowledged, and `mailbox_interrupts` is
required to be quiet.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr, smc_addr_symbols
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_contract, smc_reg_addr
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_FILTER_BANKS = ("INBOUND", "OUTBOUND")
_FILTER_REGS = ("START_ADDR", "END_ADDR")
_REMAP_REGS = ("region_start", "region_end")
_MAILBOX_PORTS = ("OUTBOUND", "INBOUND")
_MAILBOX_LANES = 8
_STROBE_PATTERNS = 1 << _MAILBOX_LANES
_WORD64 = (1 << 64) - 1
_DATA_SEED = 0x0123_4567_89AB_CDEF


def _filter_spec(bank: str, register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_{bank.lower()}_filter_ctrl/{register}",
        f"SMC_TOP_SMC_{bank}_FILTER_CTRL_{register}_BASE_ADDR",
        f"SMC_TOP_SMC_{bank}_FILTER_CTRL_{register}_NUM",
        f"SMC_{bank}_FILTER_CTRL_{{index}}__{register}_REG_ADDR",
    )


def _remap_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_alias_remap/REGION/{register}",
        f"SMC_TOP_SMC_ALIAS_REMAP_REGION_{register.upper()}_BASE_ADDR",
        f"SMC_TOP_SMC_ALIAS_REMAP_REGION_{register.upper()}_NUM",
        f"SMC_ALIAS_REMAP_{{index}}__REGION_{register.upper()}_REG_ADDR",
    )


def _field(reg: RdlReg, name: str):
    for field in reg.fields:
        if field.name == name:
            return field
    raise KeyError(f"{reg.path}: the generated map declares no field named {name}")


def _rotl64(word: int, bits: int) -> int:
    bits %= 64
    return ((word << bits) | (word >> (64 - bits))) & _WORD64


def _walk_data(step: int) -> int:
    """A 64-bit word whose every byte differs from the others and from the last step."""
    word = _rotl64(_DATA_SEED, 8 * step)
    return word ^ _WORD64 if step % 2 else word


def _strobe_mask(strobe: int) -> int:
    mask = 0
    for lane in range(_MAILBOX_LANES):
        if strobe >> lane & 1:
            mask |= 0xFF << (8 * lane)
    return mask


class smc_filter_remap_bitwalk_test_seq(SmcCsrSeq):
    """Walk every filter, remap and mailbox-strobe bit, reading each one back."""

    def __init__(self, name: str = "smc_filter_remap_bitwalk_test_seq") -> None:
        super().__init__(name)
        self.filter_entries = 0
        self.filter_bits = 0
        self.remap_regions = 0
        self.remap_bits = 0
        self.mailbox_apertures = 0
        self.strobe_writes = 0
        self.strobe_patterns: set[int] = set()
        self.value_checks = 0

    async def _read_exact(self, label: str, addr: int, expected: int) -> int:
        got = await self.csr_read(label, addr, expected=expected, length=8)
        assert got == expected, f"{label} @ 0x{addr:08x} reads 0x{got:016x}, not 0x{expected:016x}"
        self.value_checks += 1
        return got

    # -- filters ---------------------------------------------------------

    @staticmethod
    def _shares_granule(start: int, end: int, granule_shift: int) -> bool:
        return start >> granule_shift == end >> granule_shift

    async def _program_range(
        self,
        start_inst: RegInstance,
        end_inst: RegInstance,
        held: tuple[int, int],
        start: int,
        end: int,
        granule_shift: int,
        label: str,
    ) -> tuple[int, int]:
        """Write a range so that no pair the entry holds on the way shares a granule.

        Hardware writes the rounded pair back whenever the two registers share
        a granule, so the register written first is the one whose new value
        keeps the pair apart while the other still holds its old word.
        """
        assert not self._shares_granule(start, end, granule_shift), (
            f"{start_inst.label} [{label}]: 0x{start:x}..0x{end:x} shares a granule, so the "
            f"readback would be the rounded pair rather than the walked word"
        )
        start_first = not self._shares_granule(start, held[1], granule_shift)
        assert start_first or not self._shares_granule(held[0], end, granule_shift), (
            f"{start_inst.label} [{label}]: neither order from 0x{held[0]:x}..0x{held[1]:x} to "
            f"0x{start:x}..0x{end:x} keeps the pair in different granules"
        )
        writes = [(start_inst, start), (end_inst, end)]
        for inst, value in writes if start_first else reversed(writes):
            await self.csr_write(f"{inst.label}:{label}", inst.addr, value, 8)
        await self._read_exact(f"{start_inst.label}:{label}_rb", start_inst.addr, start)
        await self._read_exact(f"{end_inst.label}:{label}_rb", end_inst.addr, end)
        return start, end

    async def _walk_filter_entry(
        self,
        start_inst: RegInstance,
        end_inst: RegInstance,
        granule_shift: int,
    ) -> None:
        start_field = _field(start_inst.reg, "start_addr")
        end_field = _field(end_inst.reg, "end_addr")
        assert start_field.width == end_field.width and start_field.offset == 0, (
            f"{start_inst.label}: the two address fields differ in shape"
        )
        width = start_field.width
        mask = (1 << width) - 1
        held = (start_inst.reg.reset_word, end_inst.reg.reset_word)
        for pass_name, start_is_one in (("one", True), ("zero", False)):
            for bit in range(width):
                one = 1 << bit
                zero = ~one & mask
                start, end = (one, zero) if start_is_one else (zero, one)
                held = await self._program_range(
                    start_inst, end_inst, held, start, end, granule_shift, f"{pass_name}{bit}"
                )
                self.filter_bits += 1
        for inst in (start_inst, end_inst):
            await self.csr_write(f"{inst.label}:restore", inst.addr, inst.reg.reset_word, 8)
        for inst in (start_inst, end_inst):
            await self._read_exact(f"{inst.label}:restore_rb", inst.addr, inst.reg.reset_word)

    async def _filters(self) -> None:
        for bank in _FILTER_BANKS:
            configs = reg_instances(*_filter_spec(bank, "FILTER_CONFIG"))
            starts = reg_instances(*_filter_spec(bank, "START_ADDR"))
            ends = reg_instances(*_filter_spec(bank, "END_ADDR"))
            assert len(configs) == len(starts) == len(ends), f"{bank}: ragged filter map"
            config_reg = configs[0].reg
            burst = _field(config_reg, "allow_burst")
            bus_width = _field(config_reg, "data_bus_width")
            assert burst.reset == 0 and bus_width.reset is not None, (
                f"{bank}: FILTER_CONFIG resets with allow_burst set or no data_bus_width"
            )
            granule_shift = bus_width.reset
            for cfg, start_inst, end_inst in zip(configs, starts, ends):
                await self._read_exact(f"{cfg.label}:guard", cfg.addr, config_reg.reset_word)
                await self._walk_filter_entry(start_inst, end_inst, granule_shift)
                self.filter_entries += 1

    # -- remap table -----------------------------------------------------

    async def _remap(self) -> None:
        attrs = reg_instances(*_remap_spec("region_attrs"))
        starts = reg_instances(*_remap_spec("region_start"))
        ends = reg_instances(*_remap_spec("region_end"))
        assert len(attrs) == len(starts) == len(ends), "ragged alias remap map"
        valid = _field(attrs[0].reg, "valid").mask
        for attr, start_inst, end_inst in zip(attrs, starts, ends):
            held = await self.csr_read(f"{attr.label}:guard", attr.addr, length=8)
            assert held & valid == 0, (
                f"{attr.label} reads 0x{held:x} with valid set before the walk; its bounds "
                f"would be live while they move"
            )
            rw = start_inst.reg.rw_mask
            assert rw and rw == end_inst.reg.rw_mask, (
                f"{start_inst.label}: the two bound registers differ in writable bits"
            )
            bits = [bit for bit in range(64) if rw >> bit & 1]
            outside = ~rw & _WORD64
            for bit in bits:
                one = 1 << bit
                zero = ~one & rw
                for start, end in ((one, zero), (zero, one)):
                    await self.csr_write(
                        f"{start_inst.label}:bit{bit}", start_inst.addr, start | outside, 8
                    )
                    await self.csr_write(
                        f"{end_inst.label}:bit{bit}", end_inst.addr, end | outside, 8
                    )
                    await self._read_exact(
                        f"{start_inst.label}:bit{bit}_rb", start_inst.addr, start
                    )
                    await self._read_exact(f"{end_inst.label}:bit{bit}_rb", end_inst.addr, end)
                self.remap_bits += 1
            for inst in (start_inst, end_inst):
                await self.csr_write(f"{inst.label}:restore", inst.addr, inst.reg.reset_word, 8)
            for inst in (start_inst, end_inst):
                await self._read_exact(f"{inst.label}:restore_rb", inst.addr, inst.reg.reset_word)
            self.remap_regions += 1

    # -- mailbox strobes -------------------------------------------------

    @staticmethod
    def _mailbox_reg(port: str, index: int, register: str) -> int:
        """One mailbox register address, from the per-instance symbol of each map."""
        contract = rdl_contract(f"smc_mailbox/{port.lower()}_mailbox_0/{register}")
        base0 = smc_addr(f"SMC_TOP_SMC_MAILBOX_{port}_MAILBOX_0_BASE_ADDR")
        addr = smc_addr(f"SMC_TOP_SMC_MAILBOX_{port}_MAILBOX_{index}_BASE_ADDR") + (
            contract.addr - base0
        )
        mapped = smc_reg_addr(f"SMC_MAILBOX_{port}_MAILBOX_{index}_{register}_REG_ADDR")
        assert addr == mapped, (
            f"{port} mailbox {index} {register}: smc_addr.h gives 0x{addr:08x}, smc_reg.py "
            f"0x{mapped:08x}"
        )
        return addr

    async def _mailbox(self) -> None:
        pairs = len(smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_\d+_BASE_ADDR"))
        assert pairs == len(
            smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_\d+_BASE_ADDR")
        ), "the generated map exports unequal outbound and inbound mailbox counts"
        assert pairs > 0, "the generated map declares no mailbox pair"
        apertures = [
            (port, index, _MAILBOX_PORTS[1 - side])
            for index in range(pairs)
            for side, port in enumerate(_MAILBOX_PORTS)
        ]
        irq_ack = 0
        for field in rdl_contract("smc_mailbox/outbound_mailbox_0/IRQS").fields:
            irq_ack |= field.mask
        step = 0
        for aperture, (port, index, peer) in enumerate(apertures):
            write_addr = self._mailbox_reg(port, index, "WRITE_DATA")
            read_addr = self._mailbox_reg(peer, index, "READ_DATA")
            walking = [1 << lane for lane in range(_MAILBOX_LANES)]
            share = _STROBE_PATTERNS // len(apertures)
            shared = [p for p in range(aperture * share, (aperture + 1) * share) if p]
            for strobe in walking + shared:
                data = _walk_data(step)
                step += 1
                await self.csr_write_strobed(
                    f"MBOX_{port}{index}:strb{strobe:02x}", write_addr, data, strobe, 8
                )
                self.strobe_writes += 1
                self.strobe_patterns.add(strobe)
                await self._read_exact(
                    f"MBOX_{peer}{index}:strb{strobe:02x}_rb",
                    read_addr,
                    data & _strobe_mask(strobe),
                )
            self.mailbox_apertures += 1
        for port, index, _peer in apertures:
            await self._read_exact(
                f"MBOX_{port}{index}:error", self._mailbox_reg(port, index, "ERROR_FLAGS"), 0
            )
            irqs = self._mailbox_reg(port, index, "IRQS")
            await self.csr_write(f"MBOX_{port}{index}:irq_ack", irqs, irq_ack, 8)
            await self._read_exact(f"MBOX_{port}{index}:irq_rb", irqs, 0)
        vector = cocotb.top.tb_mailbox_interrupts.value
        assert vector.is_resolvable and int(vector) == 0, (
            f"mailbox_interrupts reads {vector} after every threshold interrupt was acknowledged"
        )

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        checks_before = sb.sys_axi_value_checks_seen

        await self._filters()
        cocotb.log.info(
            "CHK-FILTER-ADDR-BITWALK: on %d filter entries a one and a zero walked across "
            "all %d bits of START_ADDR and END_ADDR, each pair reading back as programmed "
            "because its two words never share a granule, and every entry was restored to "
            "its RDL reset and read back with FILTER_CONFIG at reset throughout",
            self.filter_entries,
            self.filter_bits // (2 * self.filter_entries),
        )

        await self._remap()
        cocotb.log.info(
            "CHK-REMAP-REGION-BITWALK: on %d alias-remap regions a one and a zero walked "
            "across all %d writable bits of REGION_START and REGION_END, each reading back "
            "the written word with the unimplemented bits clear, with every region's valid "
            "bit read clear first and both bounds restored to reset and read back",
            self.remap_regions,
            self.remap_bits // self.remap_regions,
        )

        await self._mailbox()
        missing = set(range(1, _STROBE_PATTERNS)) - self.strobe_patterns
        assert not missing, f"strobe patterns never driven: {sorted(missing)}"
        cocotb.log.info(
            "CHK-MAILBOX-STROBE-WALK: %d strobed WRITE_DATA writes over %d mailbox apertures, "
            "a walking one over the eight byte lanes on each and every non-empty strobe "
            "pattern once across the block; every paired READ_DATA returned the written byte "
            "on each strobed lane and zero elsewhere, every ERROR_FLAGS read clear and "
            "mailbox_interrupts is quiet",
            self.strobe_writes,
            self.mailbox_apertures,
        )

        booked = sb.sys_axi_value_checks_seen - checks_before
        assert booked == self.value_checks, (
            f"the scoreboard booked {booked} exact-value compares for {self.value_checks} "
            f"reads that each carried an expected word"
        )

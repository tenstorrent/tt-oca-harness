# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DST field storage, scratch registers and same-offset block independence.

Contract SMC_DFD_TRACE_013, anchor smc_dfd_csr_field_access_test.
Scenarios DST-CSR-ACCESS.S1/S3/S4, DST-INST-FIELDS.S1, DFD-SCRATCH-RW.S1/S2, DFD-APERTURE-MAP.S2.
Sources: dfd_dst.rdl, dfd_dst_sink.rdl, dfd_funnel.rdl through the generated map, smc_cla.rdl.

Every address, field position, width, reset value and access type comes from the generated
register map through :mod:`seq_lib.smc_rdl_regmap`. Values the contract leaves to an open
specification finding (SF-016, SF-017, SF-030) are measured and printed, not compared.
"""

from __future__ import annotations

from functools import lru_cache

import cocotb
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlField, RdlReg, rdl_registers_under

_CLA_ADDRMAP = "smc_cla"
_BLOCKS = ("dst_sink", "funnel", "dst")
_DST_REGISTERS = 6
_FUSE_SENSE_MAX_CYCLES = 200_000

# SF-016: the supported value set of these fields is not pinned, so their readback is printed.
_PRINT_ONLY_FIELDS = ("Trdstformat", "Trdstsyncmode")

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_FENCE = (
    ("BRINGUP_SENSE_DONE", "S1"),
    ("FIELD_LIST_BUILT", "S1"),
    ("RW_PATTERNS", "S2"),
    ("ISOLATION", "S3"),
    ("UNDEFINED_BITS_PRINTED", "S4"),
    ("INST_FIELDS_PRINTED", "S5"),
    ("SCRATCH_PATTERNS", "S6"),
    ("SCRATCH_DISTINCT", "S7"),
    ("OFFSET_FF8_DISTINCT", "S8"),
)
_CHK_STEP = (
    ("CHK-DST-RW-PATTERNS", "RW_PATTERNS"),
    ("CHK-DST-FIELD-ISOLATION", "ISOLATION"),
    ("CHK-DST-UNDEFINED-BITS", "UNDEFINED_BITS_PRINTED"),
    ("CHK-DST-INST-FIELDS-RW", "INST_FIELDS_PRINTED"),
    ("CHK-SCRATCH-PATTERNS", "SCRATCH_PATTERNS"),
    ("CHK-SCRATCH-NO-ALIAS", "SCRATCH_DISTINCT"),
    ("CHK-APERTURE-OFFSET-ISOLATION", "OFFSET_FF8_DISTINCT"),
)
_WORD = 0xFFFF_FFFF


def _block_of(reg: RdlReg) -> str:
    return reg.path.split("/")[1].split("[", 1)[0]


def _name_of(reg: RdlReg) -> str:
    return reg.path.rsplit("/", 1)[1]


@lru_cache(maxsize=1)
def _registers() -> dict[tuple[str, str], RdlReg]:
    found: dict[tuple[str, str], RdlReg] = {}
    for reg in rdl_registers_under(_CLA_ADDRMAP):
        if _block_of(reg) in _BLOCKS:
            found.setdefault((_block_of(reg), _name_of(reg)), reg)
    return found


def _sw_fields(reg: RdlReg) -> tuple[RdlField, ...]:
    return tuple(f for f in reg.fields if f.access == "read-write")


def _baseline(reg: RdlReg) -> int:
    """Word holding every software-writable field at its RDL reset and every other bit 0."""
    word = 0
    for field in _sw_fields(reg):
        word |= ((field.reset or 0) << field.offset) & field.mask
    return word


def _undefined_mask(reg: RdlReg) -> int:
    return ~reg.declared_mask & _WORD


def _bits(value: int) -> str:
    return "[" + ",".join(str(i) for i in range(32) if (value >> i) & 1) + "]"


class smc_dfd_csr_field_access_test_seq(SmcCsrSeq):
    """Field patterns, isolation, scratch patterns and same-offset independence of the DFD MMRs."""

    def __init__(self, name: str = "smc_dfd_csr_field_access_test_seq") -> None:
        super().__init__(name)
        self.value_checks = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []

    # -- evidence plumbing ------------------------------------------------

    def _stamp(self, term: str) -> None:
        self._stamps.append((term, int(get_sim_time("ps"))))
        self._events.append(("STEP", term))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._events.append(("CHK", chk_id))

    # -- access helpers ---------------------------------------------------

    async def _read(self, reg: RdlReg, label: str) -> int:
        value = await self.csr_read(f"{reg.path}:{label}", reg.addr, length=reg.width_bytes)
        assert isinstance(value, int), f"{reg.path} [{label}]: read data {value!r} is not an int"
        return value & _WORD

    async def _write(self, reg: RdlReg, word: int, label: str) -> None:
        await self.csr_write(f"{reg.path}:{label}", reg.addr, word & _WORD, length=reg.width_bytes)

    @staticmethod
    def _field_value(word: int, field: RdlField) -> int:
        return (word & field.mask) >> field.offset

    # -- S2 ---------------------------------------------------------------

    async def _rw_patterns(self, dst: list[RdlReg]) -> str:
        compared = 0
        printed: list[str] = []
        for reg in dst:
            base = _baseline(reg)
            for field in _sw_fields(reg):
                ones = (1 << field.width) - 1
                seen: list[int] = []
                for value in (ones, 0):
                    word = (base & ~field.mask) | (value << field.offset)
                    await self._write(reg, word, f"{field.name}_{value:x}")
                    got = self._field_value(await self._read(reg, f"{field.name}_rb"), field)
                    seen.append(got)
                    if field.plain_rw and field.name not in _PRINT_ONLY_FIELDS:
                        assert got == value, (
                            f"{reg.path} @ 0x{reg.addr:08x} field {field.name} "
                            f"[{field.offset}+:{field.width}]: wrote 0x{value:x} alone with the "
                            f"other fields at baseline 0x{base:08x}, reads 0x{got:x}"
                        )
                        compared += 1
                if not (field.plain_rw and field.name not in _PRINT_ONLY_FIELDS):
                    printed.append(
                        f"{_name_of(reg)}.{field.name}(ones->0x{seen[0]:x},zeros->0x{seen[1]:x})"
                    )
                await self._write(reg, base, f"{field.name}_base")
        self.value_checks += compared
        return (
            f"{compared} sw=rw DST field patterns (all ones then all zeros, field alone, others "
            f"at baseline) read back exactly; printed not compared (hardware-driven or "
            f"SF-016/SF-017): {'; '.join(printed)}"
        )

    # -- S3 ---------------------------------------------------------------

    async def _snapshot(self, dst: list[RdlReg], label: str) -> dict[str, int]:
        return {_name_of(reg): await self._read(reg, f"{label}_{_name_of(reg)}") for reg in dst}

    async def _isolation(self, dst: list[RdlReg]) -> str:
        fields_checked = 0
        for reg in dst:
            base = _baseline(reg)
            for field in _sw_fields(reg):
                await self._write(reg, base, f"iso_{field.name}_base")
                before = await self._snapshot(dst, "pre")
                other = ((1 << field.width) - 1) ^ self._field_value(base, field)
                await self._write(
                    reg, (base & ~field.mask) | (other << field.offset), f"iso_{field.name}"
                )
                after = await self._snapshot(dst, "post")
                for peer in dst:
                    name = _name_of(peer)
                    mask = peer.static_mask
                    if peer is reg:
                        mask &= ~field.mask
                    assert after[name] & mask == before[name] & mask, (
                        f"{peer.path} @ 0x{peer.addr:08x}: writing {_name_of(reg)}.{field.name} "
                        f"= 0x{other:x} moved bits 0x{(after[name] ^ before[name]) & mask:08x} "
                        f"(before 0x{before[name]:08x}, after 0x{after[name]:08x})"
                    )
                    self.value_checks += 1
                await self._write(reg, base, f"iso_{field.name}_restore")
                fields_checked += 1
        return (
            f"{fields_checked} sw=rw DST fields each written alone to the complement of its "
            f"baseline; every other non-hardware-driven field of the same register and every "
            f"register of the DST block kept the value read before the write"
        )

    # -- S4 ---------------------------------------------------------------

    async def _undefined_bits(self, dst: list[RdlReg]) -> str:
        rows: list[str] = []
        for reg in dst:
            undefined = _undefined_mask(reg)
            if not undefined:
                continue
            base = _baseline(reg)
            await self._write(reg, base | undefined, f"undef_ones_{_name_of(reg)}")
            ones = await self._read(reg, f"undef_ones_{_name_of(reg)}") & undefined
            await self._write(reg, base, f"undef_zeros_{_name_of(reg)}")
            zeros = await self._read(reg, f"undef_zeros_{_name_of(reg)}") & undefined
            rows.append(
                f"{_name_of(reg)} undefined bits {_bits(undefined)}: after ones set "
                f"{_bits(ones)}, after zeros set {_bits(zeros)}"
            )
        return (
            "every write and read of the positions no DST field covers completed with OKAY inside "
            "the bound; stored values printed per bit, none asserted (SF-030 open): "
            + "; ".join(rows)
        )

    # -- S5 ---------------------------------------------------------------

    async def _inst_fields(self, ctl: RdlReg) -> str:
        tracing = next(f for f in ctl.fields if f.name == "Trdstinsttracing")
        trigger = next(f for f in ctl.fields if f.name == "Trdstinsttriggerenable")
        active = next(f for f in ctl.fields if f.name == "Trdstactive")
        enable = next(f for f in ctl.fields if f.name == "Trdstenable")
        base = _baseline(ctl)
        rows: list[str] = []
        changed = False
        for state, state_bits in (
            ("inactive", 0),
            ("active", active.mask | enable.mask),
        ):
            for value in (1, 0):
                word = base & ~(tracing.mask | trigger.mask | active.mask | enable.mask)
                word |= state_bits | (value * (tracing.mask | trigger.mask))
                await self._write(ctl, word, f"inst_{state}_{value}")
                got = await self._read(ctl, f"inst_{state}_{value}")
                t_got = self._field_value(got, tracing)
                changed |= t_got != value
                rows.append(
                    f"trace {state} wrote {value}/{value}: Trdstinsttracing={t_got} "
                    f"Trdstinsttriggerenable={self._field_value(got, trigger)}"
                )
        await self._write(ctl, base, "inst_restore")
        return (
            "Trdstinsttracing and Trdstinsttriggerenable written with the trace inactive and "
            "active (no capture started) and read back; values printed, none asserted (SF-017 "
            f"open); hardware changed Trdstinsttracing: {changed}; " + "; ".join(rows)
        )

    # -- S6, S7, S8 -------------------------------------------------------

    @staticmethod
    def _scratch(registers: dict[tuple[str, str], RdlReg]) -> list[RdlReg]:
        return [registers[(blk, nm)] for blk in _BLOCKS for nm in ("ScratchLo", "ScratchHi")]

    async def _scratch_patterns(self, scratch: list[RdlReg]) -> str:
        patterns = [_WORD, 0, 0xAAAA_AAAA, 0x5555_5555] + [1 << i for i in range(32)]
        for reg in scratch:
            for value in patterns:
                await self._write(reg, value, f"pat_{value:x}")
                got = await self._read(reg, f"pat_{value:x}")
                assert got == value, (
                    f"{reg.path} @ 0x{reg.addr:08x}: wrote 0x{value:08x}, reads 0x{got:08x}"
                )
                self.value_checks += 1
            await self._write(reg, 0, "pat_restore")
        return (
            f"{len(scratch)} scratch registers each read back exactly {len(patterns)} patterns "
            f"(all ones, all zeros, 0xAAAAAAAA, 0x55555555 and 32 walking-one positions)"
        )

    async def _scratch_distinct(self, scratch: list[RdlReg]) -> str:
        values = [0xC0DE_0001 + 0x0101_1010 * i for i in range(len(scratch))]
        assert len(set(values)) == len(values)
        for reg, value in zip(scratch, values):
            await self._write(reg, value, "distinct")
        seen = []
        for reg, value in zip(scratch, values):
            got = await self._read(reg, "distinct_rb")
            assert got == value, (
                f"{reg.path} @ 0x{reg.addr:08x}: wrote 0x{value:08x} before any read, reads "
                f"0x{got:08x}"
                + (f", the value of {scratch[values.index(got)].path}" if got in values else "")
            )
            self.value_checks += 1
            seen.append(f"{_block_of(reg)}/{_name_of(reg)}=0x{got:08x}")
        for reg in scratch:
            await self._write(reg, 0, "distinct_restore")
        return (
            "six distinct values written before any read, each read back from its own "
            "register: " + ", ".join(seen)
        )

    async def _offset_isolation(self, registers: dict[tuple[str, str], RdlReg]) -> str:
        probes = [registers[(blk, "ScratchLo")] for blk in _BLOCKS]
        assert len({reg.addr & 0xFFF for reg in probes}) == 1, (
            f"the three ScratchLo offsets differ: {[hex(reg.addr) for reg in probes]}"
        )
        values = [0x1357_9BDF, 0x2468_ACE0, 0xFEDC_BA98]
        expected = [0, 0, 0]
        rows = []
        for index, (reg, value) in enumerate(zip(probes, values)):
            await self._write(reg, value, "offset_ff8")
            expected[index] = value
            for peer, want in zip(probes, expected):
                got = await self._read(peer, "offset_ff8_rb")
                assert got == want, (
                    f"after writing 0x{value:08x} to {reg.path} @ 0x{reg.addr:08x}, {peer.path} "
                    f"@ 0x{peer.addr:08x} reads 0x{got:08x}, want 0x{want:08x}"
                )
                self.value_checks += 1
            rows.append(f"{_block_of(reg)}@0x{reg.addr:08x}=0x{value:08x}")
        return (
            f"offset 0x{probes[0].addr & 0xFFF:03x} of the three blocks took distinct values "
            f"({', '.join(rows)}); each read back from its own block and the other two kept theirs"
        )

    async def _restore_all(self, registers: dict[tuple[str, str], RdlReg]) -> int:
        count = 0
        for (blk, _name), reg in registers.items():
            if blk != "dst" and _name not in ("ScratchLo", "ScratchHi"):
                continue
            await self._write(reg, reg.reset_word, "restore")
            got = await self._read(reg, "restore_rb")
            mask = reg.static_mask
            assert got & mask == reg.reset_word & mask, (
                f"{reg.path} @ 0x{reg.addr:08x}: restored to 0x{reg.reset_word:08x}, static "
                f"bits read 0x{got & mask:08x}"
            )
            count += 1
        return count

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_fuse_sense_done"), "tb_top exports no tb_fuse_sense_done"
        await self.wait_fuse_sense_done(_FUSE_SENSE_MAX_CYCLES)
        fuse_state = f"tb_fuse_sense_done={int(dut.tb_fuse_sense_done.value)}"
        self._stamp("BRINGUP_SENSE_DONE")

        registers = _registers()
        dst = sorted(
            (reg for (blk, _n), reg in registers.items() if blk == "dst"), key=lambda r: r.addr
        )
        assert len(dst) == _DST_REGISTERS, (
            f"the generated map carries {len(dst)} registers under {_CLA_ADDRMAP}/dst, not "
            f"{_DST_REGISTERS}"
        )
        scratch = self._scratch(registers)
        dst_rw = [reg for reg in dst]
        for reg in dst:
            reset_read = await self._read(reg, "reset")
            assert reset_read & reg.static_mask == reg.reset_word & reg.static_mask, (
                f"{reg.path} @ 0x{reg.addr:08x}: reset read 0x{reset_read:08x}, static bits "
                f"expected 0x{reg.reset_word & reg.static_mask:08x}"
            )
        self._stamp("FIELD_LIST_BUILT")

        text = await self._rw_patterns(dst_rw)
        self._stamp("RW_PATTERNS")
        self._chk("CHK-DST-RW-PATTERNS", text)

        text = await self._isolation(dst_rw)
        self._stamp("ISOLATION")
        self._chk("CHK-DST-FIELD-ISOLATION", text)

        text = await self._undefined_bits(dst)
        self._stamp("UNDEFINED_BITS_PRINTED")
        self._chk("CHK-DST-UNDEFINED-BITS", text)

        text = await self._inst_fields(registers[("dst", "Trdstcontrol")])
        self._stamp("INST_FIELDS_PRINTED")
        self._chk("CHK-DST-INST-FIELDS-RW", text)

        text = await self._scratch_patterns(scratch)
        self._stamp("SCRATCH_PATTERNS")
        self._chk("CHK-SCRATCH-PATTERNS", text)

        text = await self._scratch_distinct(scratch)
        self._stamp("SCRATCH_DISTINCT")
        self._chk("CHK-SCRATCH-NO-ALIAS", text)

        text = await self._offset_isolation(registers)
        self._stamp("OFFSET_FF8_DISTINCT")
        self._chk("CHK-APERTURE-OFFSET-ISOLATION", text)

        restored = await self._restore_all(registers)
        self._stamps.append(("TIMEOUT_PATHS", int(get_sim_time("ps"))))
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 2 bounded waits: fuse_sense_done=%d smc clocks last=%s, "
            "sep_in_access=%dns last=ok after %d accesses; expiry raises AssertionError with the "
            "last observed signal or register; %d registers restored to reset",
            _FUSE_SENSE_MAX_CYCLES,
            fuse_state,
            self.cfg.axi_timeout_ns,
            self.accesses,
            restored,
        )

        terms = [t for t, _ in _FENCE]
        stamp_terms = [t for t, _ in self._stamps if t in terms]
        assert stamp_terms == terms, f"fence terms {stamp_terms}, contract order {terms}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        step_events = [name for kind, name in self._events if kind == "STEP"]
        assert step_events == terms, f"step events {step_events}"
        chk_events = [name for kind, name in self._events if kind == "CHK"]
        assert chk_events == [c for c, _ in _CHK_STEP], f"checker order {chk_events}"
        for chk_id, term in _CHK_STEP:
            assert self._events.index(("STEP", term)) < self._events.index(("CHK", chk_id)), (
                f"{chk_id} printed before its step {term}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(terms),
            ",".join(c for c, _ in _CHK_STEP),
            ",".join(f"{t}={ps}" for t, ps in self._stamps),
        )

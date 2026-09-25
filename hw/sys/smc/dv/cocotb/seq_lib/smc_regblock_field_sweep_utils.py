# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-instance register cycles against the generated RDL contract.

The blocks these helpers drive are instantiated more than once in the SMC
register map, and the generated IP-XACT export declares each register once. So
the *contract* of a register -- width, field positions, reset, software-access
type -- comes from :mod:`seq_lib.smc_rdl_regmap`, while the *address* of every
instance comes from that register's indexed ``smc_addr.h`` macro. Instance 0
has to agree between the two generated views or :func:`reg_instances` raises.

:meth:`SmcRegblockFieldSweepSeq.granule_cycle` is the cycle the sweeps drive on
one instance:

* read at reset -- bits no field occupies read 0, every software-writable bit
  carries the model, and every bit whose reset the contract pins and software
  cannot write carries that reset;
* write each half of the register with the software-writable bits set, then
  with the low pattern, reading the whole register back after each half. The
  halves go out as separate narrower accesses, so the byte lanes over the other
  half are deasserted and each readback also proves the untouched half kept its
  value;
* restore the RDL reset through both halves and read it back.

Only fields the contract pins exactly (``RdlField.plain_rw``) are written:
hardware-driven, self-clearing, ``oneToSet`` and read-side-effect fields have no
written-value expectation, so a caller that wants one drives it itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_contract, rdl_contract_array, rdl_register, smc_reg_addr


@dataclass(frozen=True)
class RegInstance:
    """One instance of a register the generated map declares once."""

    label: str
    reg: RdlReg
    addr: int
    index: int

    @property
    def width_bytes(self) -> int:
        return self.reg.width_bytes


def reg_instances(
    path: str, symbol: str, count_symbol: str, py_symbol: str
) -> tuple[RegInstance, ...]:
    """Every instance of ``path``, addressed through the indexed ``symbol`` macro.

    ``path`` is the IP-XACT hierarchy of the register, which carries the
    contract. ``symbol`` is the ``SMC_TOP_*_BASE_ADDR(idx)`` macro of the same
    register in ``smc_addr.h`` and ``count_symbol`` its companion ``*_NUM``.
    ``py_symbol`` is the per-instance ``*_REG_ADDR`` name in ``smc_reg.py``,
    with ``{index}`` where the instance number goes; every address is compared
    against it, so the three generated views of the same RDL have to agree.
    """
    reg = rdl_contract(path)
    count = smc_addr(count_symbol)
    assert count > 0, f"{count_symbol} is {count}"
    out: list[RegInstance] = []
    for index in range(count):
        addr = smc_indexed_addr(symbol, index)
        mapped = smc_reg_addr(py_symbol.format(index=index))
        assert addr == mapped, (
            f"{path}[{index}]: {symbol}({index}) resolves to 0x{addr:08x} and "
            f"smc_reg.{py_symbol.format(index=index)} says 0x{mapped:08x}"
        )
        out.append(RegInstance(f"{path}[{index}]", reg, addr, index))
    assert out[0].addr == reg.addr, (
        f"{path}: the IP-XACT map places instance 0 at 0x{reg.addr:08x} and "
        f"{symbol}(0) resolves to 0x{out[0].addr:08x}, so the generated views of "
        f"the same RDL do not agree on this register"
    )
    return tuple(out)


def single_reg_instance(path: str) -> RegInstance:
    """The one instance of a register the address map instantiates once.

    :func:`smc_rdl_regmap.rdl_register` already compares the IP-XACT address
    against the register's own ``*_REG_ADDR`` symbol in ``smc_reg.py``, so the
    two generated views have to agree before the caller sees the address.
    """
    reg = rdl_register(path)
    return RegInstance(path, reg, reg.addr, 0)


def array_reg_instances(
    path: str, py_symbol: str, stride_symbol: str, outer_index: int
) -> tuple[RegInstance, ...]:
    """Every element of a register array inside one copy of its register file.

    The IP-XACT export declares the array once, under the first copy of the
    register file, so element ``e`` of copy ``n`` sits ``n`` strides above the
    declared element address. ``py_symbol`` names the per-copy, per-element
    ``*_REG_ADDR`` symbol in ``smc_reg.py``, with ``{index}`` for the copy and
    ``{element}`` for the element; every address is compared against it.
    """
    stride = smc_addr(stride_symbol)
    out: list[RegInstance] = []
    for element, reg in enumerate(rdl_contract_array(path)):
        addr = reg.addr + outer_index * stride
        mapped = smc_reg_addr(py_symbol.format(index=outer_index, element=element))
        assert addr == mapped, (
            f"{path}[{outer_index}][{element}]: the IP-XACT element at 0x{reg.addr:08x} plus "
            f"{outer_index} strides of 0x{stride:x} gives 0x{addr:08x}, smc_reg.py says "
            f"0x{mapped:08x}"
        )
        out.append(RegInstance(f"{path}[{outer_index}][{element}]", reg, addr, element))
    return tuple(out)


class SmcRegblockFieldSweepSeq(SmcCsrSeq):
    """CSR sequence with the per-instance RDL-contract register cycle."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.registers_swept = 0
        self.value_checks = 0

    @staticmethod
    def word_mask(inst: RegInstance) -> int:
        return (1 << (inst.width_bytes * 8)) - 1

    @staticmethod
    def volatile_mask(inst: RegInstance) -> int:
        """Bits hardware can drive, so no host-side model predicts them."""
        mask = 0
        for field in inst.reg.fields:
            if field.volatile or field.reset is None:
                mask |= field.mask
        return mask

    async def read_check(self, inst: RegInstance, label: str, model: int, prot: int = 0) -> int:
        """Read one instance and hold it to the register's RDL contract.

        A register no field of which hardware drives has a fully predicted
        word, which goes out as the access's ``expected`` so the scoreboard
        books an exact compare of its own alongside the field-level asserts
        below. A register with a hardware-driven field has no such word and
        carries the asserts alone.
        """
        reg = inst.reg
        predicted: int | None = None
        if self.volatile_mask(inst) == 0:
            predicted = (model & reg.rw_mask) | (reg.reset_word & ~reg.rw_mask)
            predicted &= self.word_mask(inst)
        value = await self.csr_read(
            f"{inst.label}:{label}",
            inst.addr,
            expected=predicted,
            length=inst.width_bytes,
            prot=prot,
        )
        value &= self.word_mask(inst)

        unimplemented = value & ~reg.declared_mask & self.word_mask(inst)
        assert unimplemented == 0, (
            f"{inst.label} @ 0x{inst.addr:08x} [{label}]: read "
            f"0x{value:0{inst.width_bytes * 2}x}, which drives 0x{unimplemented:x} in bits "
            f"no field of the register occupies (declared 0x{reg.declared_mask:x})"
        )

        got_rw = value & reg.rw_mask
        want_rw = model & reg.rw_mask
        assert got_rw == want_rw, (
            f"{inst.label} @ 0x{inst.addr:08x} [{label}]: software-writable bits read "
            f"0x{got_rw:x}, the register contract says 0x{want_rw:x}"
        )

        pinned_ro = reg.static_mask & ~reg.rw_mask
        assert value & pinned_ro == reg.reset_word & pinned_ro, (
            f"{inst.label} @ 0x{inst.addr:08x} [{label}]: bits software cannot write read "
            f"0x{value & pinned_ro:x}, their RDL reset is 0x{reg.reset_word & pinned_ro:x}"
        )
        self.value_checks += 1
        return value

    @staticmethod
    def pack_fields(inst: RegInstance, **values: int) -> int:
        """Pack named fields of one register into a word, from the generated map.

        For a register whose legal values are constrained, so a caller can
        state the word it means in field terms instead of a literal.
        """
        by_name = {field.name: field for field in inst.reg.fields}
        missing = set(values) - set(by_name)
        assert not missing, (
            f"{inst.label}: the generated map declares no field named {', '.join(sorted(missing))}"
        )
        word = 0
        for name, value in values.items():
            field = by_name[name]
            assert value < (1 << field.width), (
                f"{inst.label}.{name} is {field.width} bits and cannot hold {value}"
            )
            word |= value << field.offset
        return word

    @staticmethod
    def _held_mask(inst: RegInstance, hold_fields: frozenset[str]) -> int:
        mask = 0
        for field in inst.reg.fields:
            if field.name in hold_fields:
                mask |= field.mask
        missing = hold_fields - {field.name for field in inst.reg.fields}
        assert not missing, (
            f"{inst.label}: the generated map declares no field named "
            f"{', '.join(sorted(missing))}, so holding it would hold nothing"
        )
        return mask

    async def granule_cycle(
        self,
        inst: RegInstance,
        low_value: int = 0,
        hold_fields: frozenset[str] = frozenset(),
        ones_value: int | None = None,
    ) -> None:
        """Half-register writes on one instance, then the RDL reset restored.

        ``hold_fields`` names software-writable fields this cycle must leave at
        their reset: the caller states why at the call site. They stay in the
        model, so every read still checks them, and they are simply never given
        the ones pattern.

        ``ones_value`` replaces the all-ones pattern, and ``low_value`` the
        all-zeros one, for a register whose RDL constrains which words are
        legal. The caller states the constraint and checks it holds for every
        word it supplies; a register with no constraint leaves both alone.
        """
        reg = inst.reg
        held = self._held_mask(inst, hold_fields)
        driven = reg.rw_mask & ~held
        high = driven if ones_value is None else (ones_value & driven)
        assert driven, (
            f"{inst.label}: no field of the register is software-writable with a "
            f"readback the contract pins and not held, so the cycle would write nothing"
        )
        half = inst.width_bytes // 2
        granules = ((0, half), (half, inst.width_bytes - half))
        model = reg.reset_word
        await self.read_check(inst, "reset", model)

        for pattern, tag in ((high, "ones"), (low_value & driven, "low")):
            for offset, width in granules:
                gmask = ((1 << (width * 8)) - 1) << (offset * 8)
                touched = driven & gmask
                await self.csr_write(
                    f"{inst.label}:{tag}@{offset}",
                    inst.addr + offset,
                    (pattern & gmask) >> (offset * 8),
                    length=width,
                )
                model = (model & ~touched) | (pattern & touched)
                await self.read_check(inst, f"{tag}@{offset}", model)

        for offset, width in granules:
            gmask = ((1 << (width * 8)) - 1) << (offset * 8)
            await self.csr_write(
                f"{inst.label}:restore@{offset}",
                inst.addr + offset,
                (reg.reset_word & gmask) >> (offset * 8),
                length=width,
            )
        await self.read_check(inst, "restore", reg.reset_word)
        self.registers_swept += 1

    async def word_cycle(
        self,
        inst: RegInstance,
        low_value: int = 0,
        hold_fields: frozenset[str] = frozenset(),
    ) -> None:
        """Full-width writes on one instance, then the RDL reset restored.

        For a register block whose bus adapter refuses a sub-word write, so the
        half-register cycle cannot be used. The caller says which block and why.
        """
        reg = inst.reg
        held = self._held_mask(inst, hold_fields)
        driven = reg.rw_mask & ~held
        assert driven, (
            f"{inst.label}: no field of the register is software-writable with a "
            f"readback the contract pins and not held, so the cycle would write nothing"
        )
        await self.read_check(inst, "reset", reg.reset_word)
        for pattern, tag in ((driven, "ones"), (low_value & driven, "low")):
            model = (reg.reset_word & ~driven) | (pattern & driven)
            await self.csr_write(f"{inst.label}:{tag}", inst.addr, model, length=inst.width_bytes)
            await self.read_check(inst, tag, model)
        await self.csr_write(
            f"{inst.label}:restore", inst.addr, reg.reset_word, length=inst.width_bytes
        )
        await self.read_check(inst, "restore", reg.reset_word)
        self.registers_swept += 1

    def assert_value_checks(self, sb_before: int, minimum: int, block: str) -> int:
        """Minimum-activity gate on the scoreboard's own exact-value compares."""
        booked = self.env.scoreboard.sys_axi_value_checks_seen - sb_before
        assert booked >= minimum, (
            f"{block}: the scoreboard booked {booked} SEP_IN AXI exact-value compares "
            f"for reads this sweep issued with {minimum} predicted words"
        )
        return booked

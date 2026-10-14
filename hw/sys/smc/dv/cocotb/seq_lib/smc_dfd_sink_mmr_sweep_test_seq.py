# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RDL-contract write sweep of the DST, sink and funnel MMR blocks.

Every address, field position, reset value, software-access type and
volatility comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap`. The vendored RTL is not a source for any value
this sequence programs or compares against.

``smc_dfd_cla_mmr_sweep_test`` drives the write side of the ``cla`` sub-block
of the SMC_CLA aperture. The other three sub-blocks -- ``dst``, ``dst_sink``
and ``funnel`` -- are written by the trace leaves only at the addresses they
configure. This sequence writes every register of all three.

The registers fall into two classes the contract distinguishes:

* Registers with at least one field the contract pins -- ``sw = rw`` and not
  also hardware-driven -- take the pattern in those bits and give it back.
* The sink and funnel control and pointer registers are ``sw = rw; hw = rw``:
  software writes them and hardware also drives them, so the RDL pins no
  readback value. They are still written, because the decode is what is being
  exercised, and what they are held to is the one thing the contract does
  state: a bit no field occupies reads 0.

Every register is also checked before the write for its read-only, non-volatile
bits carrying their RDL reset, and those bits are re-checked afterwards, so a
write that spills out of its own fields fails.

**No trace runs here.** This leaf starts no trace and arms no CLA, so the
enables it writes into ``Trdstcontrol``, ``Trdstramcontrol`` and
``Trfunnelcontrol`` have nothing to act on; the trace-carrying leaves own
those registers when a stream is live. The control and pointer registers are
still swept last, and every register is put back to its RDL reset.
"""

from __future__ import annotations

from functools import lru_cache

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_registers_under

_CLA_ADDRMAP = "smc_cla"

# Sub-blocks this sequence owns, and the register counts the generated map is
# expected to carry for each. A regenerated map that gains or loses a register
# fails rather than silently changing the sweep.
_BLOCKS: dict[str, int] = {"dst": 6, "dst_sink": 13, "funnel": 5}

# Registers swept last, because they carry the enables and the window and
# pointer state the trace-carrying leaves set up. Nothing in this leaf depends
# on them, and all of them are restored, but sweeping them after the inert
# registers keeps the disturbance at the end of the run.
# Adjacent register pairs of the sink written as one double-width access, so
# each register's address is reached by a transfer that also carries its
# neighbour. Every other access this leaf issues is one register wide. The
# names repeat across sub-blocks, so the block is named too.
_PAIR_BLOCK = "dst_sink"
_PAIRS = (("Trdstramcontrol", "Trdstramimpl"), ("ScratchLo", "ScratchHi"))

_LAST = (
    "Trdstcontrol",
    "Trdstramcontrol",
    "Trdstramstartlow",
    "Trdstramstarthigh",
    "Trdstramlimitlow",
    "Trdstramlimithigh",
    "Trdstramwplow",
    "Trdstramwphigh",
    "Trdstramrplow",
    "Trdstramrphigh",
    "Trfunnelcontrol",
    "Trfunneldisinput",
)


def _sw_write_mask(reg: RdlReg) -> int:
    """Bits the contract lets software write, whether or not hardware drives them."""
    mask = 0
    for field in reg.fields:
        if field.access == "read-write":
            mask |= field.mask
    return mask


@lru_cache(maxsize=1)
def _swept() -> tuple[RdlReg, ...]:
    """Every register of the three sub-blocks, inert ones first."""
    found: dict[tuple[str, str], RdlReg] = {}
    for reg in rdl_registers_under(_CLA_ADDRMAP):
        block = reg.path.split("/")[1].split("[", 1)[0]
        if block not in _BLOCKS:
            continue
        found.setdefault((block, reg.path.rsplit("/", 1)[1]), reg)
    for block, expected in _BLOCKS.items():
        got = sum(1 for key in found if key[0] == block)
        assert got == expected, (
            f"the generated map carries {got} registers under {_CLA_ADDRMAP}/{block}, not "
            f"the {expected} this sweep is sized for"
        )
    ordered = sorted(found.items(), key=lambda kv: (kv[0][1] in _LAST, kv[1].addr))
    return tuple(reg for _, reg in ordered)


class smc_dfd_sink_mmr_sweep_test_seq(SmcCsrSeq):
    """Write every DST, sink and funnel MMR against its RDL contract and restore it."""

    def __init__(self, name: str = "smc_dfd_sink_mmr_sweep_test_seq") -> None:
        super().__init__(name)
        self.registers_swept = 0
        self.pinned_registers = 0
        self.readonly_checks = 0
        self.narrow_writes = 0
        self.value_checks = 0

    @staticmethod
    def _word_mask(reg: RdlReg) -> int:
        return (1 << (reg.width_bytes * 8)) - 1

    async def _read_check(self, reg: RdlReg, label: str, model: int | None) -> int:
        """Read one register and hold it to every part of its contract that is pinned."""
        value = await self.csr_read(f"{reg.path}:{label}", reg.addr, length=reg.width_bytes)
        value &= self._word_mask(reg)

        undeclared = value & ~reg.declared_mask & self._word_mask(reg)
        assert undeclared == 0, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: reads 0x{value:08x}, which drives "
            f"0x{undeclared:x} in bits no field of the register occupies (declared "
            f"0x{reg.declared_mask:x})"
        )

        if model is not None and reg.rw_mask:
            got = value & reg.rw_mask
            want = model & reg.rw_mask
            assert got == want, (
                f"{reg.path} @ 0x{reg.addr:08x} [{label}]: the bits the contract pins read "
                f"0x{got:x}, it says 0x{want:x}"
            )

        pinned_ro = reg.static_mask & ~_sw_write_mask(reg)
        if pinned_ro:
            assert value & pinned_ro == reg.reset_word & pinned_ro, (
                f"{reg.path} @ 0x{reg.addr:08x} [{label}]: bits software cannot write read "
                f"0x{value & pinned_ro:x}, their RDL reset is 0x{reg.reset_word & pinned_ro:x}"
            )
            self.readonly_checks += 1
        self.value_checks += 1
        return value

    async def _cycle(self, reg: RdlReg) -> None:
        """Read at reset, write every declared bit, read back, restore, read back."""
        await self._read_check(reg, "reset", reg.reset_word)
        await self.csr_write(
            f"{reg.path}:pattern", reg.addr, reg.declared_mask, length=reg.width_bytes
        )
        await self._read_check(reg, "pattern", reg.declared_mask)
        await self.csr_write(
            f"{reg.path}:restore", reg.addr, reg.reset_word, length=reg.width_bytes
        )
        await self._read_check(reg, "restore", reg.reset_word)
        self.registers_swept += 1
        if reg.rw_mask:
            self.pinned_registers += 1

    async def _narrow_cycle(self, low: RdlReg, high: RdlReg) -> None:
        """Write a register pair as one double-width access and check both halves.

        Every other access this leaf issues is one register wide, which asserts
        the whole byte strobe of that register. A double-width write at the low
        register's address carries both registers in one transfer, so each half
        is reached with the other half's lanes driving the same transfer.
        """
        await self._read_check(low, "pair_reset", low.reset_word)
        await self._read_check(high, "pair_reset", high.reset_word)
        pattern = (high.declared_mask << 32) | low.declared_mask
        await self.csr_write(f"{low.path}:pair", low.addr, pattern, length=8)
        self.narrow_writes += 1
        await self._read_check(low, "pair", low.declared_mask)
        await self._read_check(high, "pair", high.declared_mask)
        await self.csr_write(
            f"{low.path}:pair_restore",
            low.addr,
            (high.reset_word << 32) | low.reset_word,
            length=8,
        )
        await self._read_check(low, "pair_restore", low.reset_word)
        await self._read_check(high, "pair_restore", high.reset_word)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        swept = _swept()
        for reg in swept:
            await self._cycle(reg)

        assert self.registers_swept == len(swept), (
            f"the sweep drove {self.registers_swept} registers, the list built from the "
            f"generated map has {len(swept)}"
        )
        assert self.pinned_registers >= 8, (
            f"only {self.pinned_registers} of the {len(swept)} swept registers have a bit "
            f"the contract pins to the written value, so the readback leg would rest on too "
            f"few registers"
        )
        # Three reads per register that has a read-only, non-volatile bit at all.
        with_ro = sum(1 for reg in swept if reg.static_mask & ~_sw_write_mask(reg))
        assert self.readonly_checks == 3 * with_ro, (
            f"{self.readonly_checks} reads checked a read-only bit against its RDL reset; "
            f"{with_ro} of the {len(swept)} swept registers carry such a bit and each is "
            f"read three times, so {3 * with_ro} were expected"
        )
        assert with_ro >= 6, (
            f"only {with_ro} of the {len(swept)} swept registers carry a bit the contract "
            f"makes read-only and not hardware-driven, so the no-spill leg would rest on "
            f"too few registers"
        )
        cocotb.log.info(
            "CHK-DFD-SINK-MMR-DECODE: every one of the %d registers of the dst, dst_sink and "
            "funnel sub-blocks was read at its RDL reset, written with every bit its fields "
            "declare, read back, restored and read back again; %d of them have a bit the "
            "contract pins to the written value and gave it back exactly, and no read drove "
            "a bit no field occupies (%d value compares)",
            self.registers_swept,
            self.pinned_registers,
            self.value_checks,
        )
        by_name = {
            reg.path.rsplit("/", 1)[1]: reg
            for reg in swept
            if reg.path.split("/")[1].split("[", 1)[0] == _PAIR_BLOCK
        }
        for low_name, high_name in _PAIRS:
            assert low_name in by_name and high_name in by_name, (
                f"the generated map no longer carries {_PAIR_BLOCK}/{low_name} and "
                f"{_PAIR_BLOCK}/{high_name} as a pair"
            )
            low, high = by_name[low_name], by_name[high_name]
            assert high.addr == low.addr + low.width_bytes, (
                f"{low.path} at 0x{low.addr:08x} and {high.path} at 0x{high.addr:08x} are "
                f"not adjacent, so a double-width write at the first does not carry both"
            )
            await self._narrow_cycle(low, high)
        assert self.narrow_writes == len(_PAIRS), (
            f"the pair pass issued {self.narrow_writes} double-width writes, not the "
            f"{len(_PAIRS)} its pair list calls for"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DFD-SINK-MMR-PAIR: %d adjacent register pairs of the sink each took one "
            "double-width write carrying both registers, and both halves read back with "
            "the bits the contract pins taking the pattern and every read-only bit still "
            "at its RDL reset; every other access this leaf issues is one register wide",
            self.narrow_writes,
        )
        cocotb.log.info(
            "CHK-DFD-SINK-MMR-READONLY: %d reads over the %d swept registers that carry one "
            "held the bits the contract makes read-only and not hardware-driven to their RDL "
            "reset, across the write of every declared bit of every register, so no write "
            "reached a field software does not own",
            self.readonly_checks,
            with_ro,
        )

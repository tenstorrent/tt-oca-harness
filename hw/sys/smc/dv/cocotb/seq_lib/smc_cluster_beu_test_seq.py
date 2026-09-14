# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN accesses to the documented BEU window land on SMC_BASE_CONFIG.

THIS TESTCASE DOES NOT PROVE ANY BEU PROPERTY, AND DOES NOT CLAIM TO.

The address map places one Bus Error Unit per core at
``0xC801_0000 + core*0x1000``. Nothing in this bench reaches them.
The local fabric folds every request into the local-alias aperture: it keeps
the address bits under ``REGION_SIZE - 1`` and prefixes ``LOCAL_BASE`` (RDL
``SMC_BASE_CONFIG.REGION_SIZE`` field description; ``hw/sys/smc/doc/fabric.adoc``
"Local and Remote Resource Access"). At the generated resets -- ``LOCAL_BASE``
``0xC000_0000``, ``REGION_SIZE`` 16 MiB, neither written here -- only
``addr[23:0]`` survives, so ``0xC801_x000`` becomes ``0xC001_x000``
(``local_fabric_masked_addr`` in ``smc_addr_map``).

The reads do not reach the cluster at all, so the value mismatch is not an
unmodelled register block behind a cluster black-box. The three non-zero words
cores 0 and 1 return are bit-for-bit the ``SMC_BASE_CONFIG`` RDL resets --
``GLOBAL_BASE`` 0x4000_0000, ``REGION_SIZE`` 0x0100_0000,
``CLOCK_GATE_CONTROL`` 0x1F00_0000, all composed here from the generated field
symbols -- and the authoritative BEU resets (CAUSE 0x0, ENABLE 0xE6,
PLIC_ENABLE 0x0, ``bus_error_unit.rdl``) match none of them.

WHAT IT PROVES. Two things about the decode, both asserted rather than assumed:

1. **Read aliasing.** Each documented BEU address and the ``0xC001_xxxx``
   address ``local_fabric_masked_addr`` maps it to are read in the same run and
   must return the SAME word. Only the mapped read carries an ``expected=``, and
   only where the register behind it has a generated RDL reset; the BEU-address
   read is pinned by nothing except the pair compare, so that compare is the
   sole check on it and fails if the fold is repaired.
2. **Write co-residency.** A distinguishing hysteresis value is written to
   ``0xC801_0018`` and read back at ``0xC001_0018``. One register cannot be
   two registers, so this is positive evidence of a single physical location
   behind both addresses -- a property no read-side ``expected=`` restates, and
   one that temporal isolation cannot manufacture, because the write and the
   readback address different words of the address space.

Cores 0 and 1 return identical triples because ``0xC001_1xxx`` is RDL deadspace
between ``SMC_BASE_CONFIG`` and ``SMC_ALIAS_REMAP`` that the DUT answers with
the ``SMC_BASE_CONFIG`` words (the aliasing ``smc_deadspace_decode_test``
tracks); cores 2 and 3 map onto ``alias_remap`` / ``mmode_remap``, which are
reset-zero. Those six pairs are 0 == 0 and carry no discrimination on their own;
they are swept and counted separately from the discriminating pairs, and the
evidence token says which is which.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import (
    CG_HYST_MASK,
    CG_HYST_SHIFT,
    CLOCK_GATE_CONTROL_RESET,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    local_fabric_masked_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

BEU_CORE_BASE = 0xC801_0000
BEU_CORE_STRIDE = 0x1000
BEU_CORES = 4

# Representative BEU register offsets (subset of the 6-register block).
BEU_CAUSE_OFFSET = 0x00
BEU_ENABLE_OFFSET = 0x10
BEU_PLIC_ENABLE_OFFSET = 0x18

_OFFSETS = (
    ("CAUSE", BEU_CAUSE_OFFSET),
    ("ENABLE", BEU_ENABLE_OFFSET),
    ("PLIC_ENABLE", BEU_PLIC_ENABLE_OFFSET),
)

# Golden for the MAPPED address, per (core, offset), where the register the fold
# lands on has a generated RDL reset. Cores 0 and 1 fold into the SMC_BASE_CONFIG
# window, whose three reset words are composed from the generated field symbols
# in `smc_addr_map` rather than transcribed here -- so these are RDL goldens for
# the registers actually read, not a snapshot of what the DUT returned.
# Cores 2 and 3 fold onto alias_remap / mmode_remap, which export no generated
# per-field reset header, so no golden is claimed for them.
_BASE_CONFIG_RESETS = {
    "CAUSE": GLOBAL_BASE_RESET & 0xFFFF_FFFF,
    "ENABLE": REGION_SIZE_RESET & 0xFFFF_FFFF,
    "PLIC_ENABLE": CLOCK_GATE_CONTROL_RESET & 0xFFFF_FFFF,
}
MAPPED_GOLDEN: dict[int, dict[str, int]] = {
    0: dict(_BASE_CONFIG_RESETS),
    1: dict(_BASE_CONFIG_RESETS),
}

# Co-residency probe: CLOCK_GATE_CONTROL's hysteresis field set to a value the
# reset does not carry. Every CG_EN bit stays at its reset 0, so no clock gate is
# armed by this write and the value is restored before the sequence ends.
_CG_HYST_PROBE = 0x2A
assert (_CG_HYST_PROBE << CG_HYST_SHIFT) & CG_HYST_MASK != (
    CLOCK_GATE_CONTROL_RESET & CG_HYST_MASK
), "the co-residency probe must differ from the reset it overwrites"
_CORESIDENCY_BEU_ADDR = BEU_CORE_BASE + BEU_PLIC_ENABLE_OFFSET
_CORESIDENCY_MAPPED_ADDR = local_fabric_masked_addr(_CORESIDENCY_BEU_ADDR)


class smc_cluster_beu_test_seq(SmcCsrSeq):
    """Locks the BEU-window aliasing by reads and a write co-residency."""

    def __init__(self, name: str = "smc_cluster_beu_test_seq") -> None:
        super().__init__(name)
        #: (beu_addr, mapped_addr, word) triples proven identical
        self.alias_pairs: list[tuple[int, int, int]] = []
        #: subset of `alias_pairs` whose common word is non-zero
        self.discriminating_pairs: list[tuple[int, int, int]] = []
        #: word read back at the mapped address after writing the BEU address
        self.coresidency_word: int | None = None
        #: word the mapped address holds once the probe has been restored
        self.restored_word: int | None = None

    async def body(self) -> None:
        for core in range(BEU_CORES):
            base = BEU_CORE_BASE + core * BEU_CORE_STRIDE
            golden = MAPPED_GOLDEN.get(core, {})
            for label, off in _OFFSETS:
                beu_addr = base + off
                mapped = local_fabric_masked_addr(beu_addr)
                assert mapped != beu_addr, (
                    f"core{core} {label}: the fold maps 0x{beu_addr:08x} onto "
                    f"itself, so this pair cannot demonstrate aliasing"
                )
                # The mapped read is the pinned side. The BEU-address read
                # carries NO `expected=`, so the pair compare below is the only
                # check on it and is fail-capable rather than a restatement of an
                # upstream exact compare.
                via_mapped = await self.csr_read(
                    f"CORE{core}_MAPPED_{label}",
                    mapped,
                    expected=golden.get(label),
                )
                via_beu = await self.csr_read(f"CORE{core}_BEU_WINDOW_{label}", beu_addr)
                assert via_beu == via_mapped, (
                    f"core{core} {label}: documented BEU address 0x{beu_addr:08x} "
                    f"returned 0x{via_beu:08x} but the address the local-fabric "
                    f"fold maps it to, 0x{mapped:08x}, returned "
                    f"0x{via_mapped:08x}. If these have diverged the fold has "
                    f"changed and this testcase's premise needs revisiting."
                )
                self.alias_pairs.append((beu_addr, mapped, via_beu))
                if via_beu != 0:
                    self.discriminating_pairs.append((beu_addr, mapped, via_beu))

        await self._write_coresidency()

        assert len(self.alias_pairs) == BEU_CORES * len(_OFFSETS), (
            f"aliasing read for {len(self.alias_pairs)} of "
            f"{BEU_CORES * len(_OFFSETS)} (core, register) pairs"
        )
        # Six of the twelve pairs fold onto reset-zero remap tables. A 0 == 0
        # pair is satisfied by any dead, gated or unmapped responder, so the
        # count of pairs whose common word is non-zero is asserted separately;
        # a fold that started answering zero everywhere fails here even though
        # every pair compare above would still hold.
        assert len(self.discriminating_pairs) == 6, (
            f"{len(self.discriminating_pairs)} of 12 alias pairs returned a "
            f"non-zero word; cores 0 and 1 fold into SMC_BASE_CONFIG and must "
            f"contribute six non-zero pairs "
            f"({[hex(w) for _b, _m, w in self.alias_pairs]})"
        )
        # `self.accesses` is bumped by this sequence's own csr_* calls, so
        # asserting it against a literal only restates the loops above and cannot
        # fail on anything the DUT did ([NO-ZERO-ACTIVITY-PASS]).
        # `assert_all_reachable` cross-checks the same count against the
        # scoreboard, which a mis-bound analysis path or a dead port fails.
        self.assert_all_reachable(BEU_CORES * len(_OFFSETS) * 2 + 5, "CLUSTER_BEU")
        cocotb.log.info(
            "CHK-BEU-WINDOW-ALIASED: %d (core, register) pairs read at BOTH the "
            "documented BEU address and the 0xC001_xxxx address "
            "the local-alias fold maps it to (LOCAL_BASE reset 0x%08x); "
            "each pair returned the same word, %d of them a non-zero one. "
            "Write co-residency: hysteresis 0x%x written at 0x%08x read back as "
            "0x%08x at 0x%08x. This testcase locks the local-fabric fold aliasing; "
            "it proves NO BEU property, because no access reaches a BEU.",
            len(self.alias_pairs),
            LOCAL_BASE_RESET,
            len(self.discriminating_pairs),
            _CG_HYST_PROBE,
            _CORESIDENCY_BEU_ADDR,
            self.coresidency_word,
            _CORESIDENCY_MAPPED_ADDR,
        )

    async def _write_coresidency(self) -> None:
        """Write via the BEU address, read back via the folded address.

        A read pair can be explained by two distinct registers that happen to
        hold the same word. A write that appears at the other address cannot:
        it is positive evidence that one physical register sits behind both.
        """
        original = await self.csr_read(
            "CORESIDENCY_SAVE",
            _CORESIDENCY_MAPPED_ADDR,
            expected=CLOCK_GATE_CONTROL_RESET & 0xFFFF_FFFF,
        )
        probe = (original & ~CG_HYST_MASK) | ((_CG_HYST_PROBE << CG_HYST_SHIFT) & CG_HYST_MASK)
        await self.csr_write("CORESIDENCY_WR_VIA_BEU", _CORESIDENCY_BEU_ADDR, probe)
        self.coresidency_word = await self.csr_read(
            "CORESIDENCY_RB_VIA_MAPPED", _CORESIDENCY_MAPPED_ADDR, expected=probe
        )
        assert self.coresidency_word == probe, (
            f"write of 0x{probe:08x} to the documented BEU address "
            f"0x{_CORESIDENCY_BEU_ADDR:08x} did not appear at the folded "
            f"address 0x{_CORESIDENCY_MAPPED_ADDR:08x}, which read back "
            f"0x{self.coresidency_word:08x} (was 0x{original:08x}). The two "
            f"addresses are not one register."
        )
        await self.csr_write("CORESIDENCY_RESTORE", _CORESIDENCY_MAPPED_ADDR, original)
        self.restored_word = await self.csr_read(
            "CORESIDENCY_RESTORE_RB", _CORESIDENCY_MAPPED_ADDR, expected=original
        )

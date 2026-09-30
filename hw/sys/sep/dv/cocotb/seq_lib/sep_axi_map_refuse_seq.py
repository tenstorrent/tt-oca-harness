# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Whole-map response expectation for sep_axi_map_refuse_test.

Every probe address is classified by ``env/sep_axi_decode_map.py``. A
reserved address must not answer OKAY. The generated memory map
(``hw/sys/sep/regs/gen/adoc/memory_map.adoc``) names a response code for each
reserved span, but those codes were taken from the RTL, so they are not an
expected value here: any refusal is accepted and the code is logged.
``sep_fabric_deadspace_decode_test`` owns the dead tail inside a window.
This sequence owns the gaps between windows.

Addresses that would disturb the run are excluded by name with a reason, the
way the register sweep does it. A silent skip is a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_axi_decode_map import (
    may_complete,
    region_of,
    spec_regions,
)
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import SEP_CPU_CTRL, SEP_RESET_CTRL, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0

# Live-bus control. sep_cpu_ctrl SEP_NMI_VEC is a known-good decode target with a
# non-zero generated reset and no read side effects, so a refusal elsewhere in the
# run is a decode result and not a dead bus. A register whose reset is 0 would be a
# zero-vs-zero compare and would also pass against a tied-off decode. Address and
# expected value come from the generated SystemRDL export.
MAPPED_CSR_ADDR = SEP_CPU_CTRL.addr("SEP_NMI_VEC")
MAPPED_CSR_EXP = SEP_CPU_CTRL.reset32("SEP_NMI_VEC")
ROM_ONE_PAST = sym("SEP_BOOT_ROM_MEM_BASE_ADDR") + sym("SEP_BOOT_ROM_MEM_SIZE")
# First byte above the last OTP register block (EFUSE_MMR) in the generated
# export. No RDL block owns the OTP window from here to 0x1093_FFFF.
OTP_ONE_PAST = sym("EFUSE_MMR_REG_MAP_BASE_ADDR") + sym("EFUSE_MMR_REG_MAP_SIZE")

# Live words a refused read must not return. A refused access never reaches a
# unit (memory_map.adoc), so a refused read that hands back one of these values
# has reached the unit that owns it. The set is the live-bus control plus the
# first word of the two blocks that directed read anchors sit directly above:
# the reset controller (anchor 0x1080_3008) and the boot ROM (ROM_ONE_PAST).
# Each is sampled at run time over the ordinary path; a zero word is dropped,
# because it cannot tell a refusal that returns zero from an aliased zero.
LIVE_DATA_ADDRS: tuple[tuple[int, str], ...] = (
    (MAPPED_CSR_ADDR, "SEP_CPU_CTRL.SEP_NMI_VEC"),
    (SEP_RESET_CTRL.addr("SW_RESET_N"), "SEP_RESET_CTRL.SW_RESET_N"),
    (sym("SEP_BOOT_ROM_MEM_BASE_ADDR"), "boot ROM word 0"),
)

# Reserved spans that must not be probed, each with the reason. These are
# excluded from stimulus, not from the contract: the map still says reserved.
_PROBE_EXCLUDE: dict[tuple[int, int], str] = {
    # Reading the CPU TCM aperture with the core held off drives the LSU stub
    # rather than the fabric, so the response says nothing about decode.
    (0xC000_0000, 0xCFFF_FFFF): "CPU TCM aperture, not fabric-decoded here",
    # The external chiplet and SMU apertures leave SEP entirely; the responder
    # is the testbench, so a refusal there is a TB property.
    (0x0000_0000, 0x0FFF_FFFF): "external chiplet aperture, TB-terminated",
    (0x4000_0000, 0xBFFF_FFFF): "external SMU aperture, TB-terminated",
    # Reserved in the map and excluded from this walk. The generated memory map
    # names a code for them, but those codes were taken from the RTL and are
    # not an expected value; the system-bus span is graded for refusal by
    # sep_unmapped_access_policy_test.
    (0x1091_4000, 0x1091_4FFF): "reserved crypto gap, excluded",
    (0x1092_1000, 0x1092_FFFF): "reserved KM gap, excluded",
    (0x1093_8000, 0x1093_FFFF): "reserved OTP gap, excluded",
    (0x10A4_0000, 0x10A5_FFFF): "reserved SYS gap, excluded",
    # SEP External: memory_map.adoc gives an adopter-defined response.
    (0x2000_0000, 0x3FFF_FFFF): "SEP External window, adopter-defined",
}


def _excluded(addr: int) -> str | None:
    for (lo, hi), why in _PROBE_EXCLUDE.items():
        if lo <= addr <= hi:
            return why
    return None


@dataclass(frozen=True)
class MapProbe:
    addr: int
    op: str  # "r" | "w"
    unit: str  # spec Unit column, for the failure message
    anchor: bool  # True = walked every seed


# The walk must stay at least this wide. Below it, a reserved row has stopped
# yielding addresses and the run is proving less than it reports.
PROBE_FLOOR = 18

# Reserved rows that cannot fill their probe quota. They are counted, and a
# new one has to be understood rather than absorbed.
SHORT_ROW_LIMIT = 5

# Anchors that survive the exclude list. A drop here does not move
# short_regions, so the count is held on its own.
ANCHOR_KEPT = 8

# Reserved gaps walked on every seed: one address just past the end of a live
# block. Three sit in excluded spans and are dropped, so eight survive.
_ANCHORS: tuple[tuple[int, str], ...] = (
    (ROM_ONE_PAST, "r"),
    (0x1080_3008, "r"),  # first byte above the reset controller
    (0x1080_3008, "w"),
    (0x1091_4000, "r"),  # KMAC/DRBG gap
    (0x1092_1000, "r"),  # above the Key Manager window
    (OTP_ONE_PAST, "r"),  # above the last OTP register block
    (0x1096_0000, "r"),  # above the entropy pool
    (0x10A4_0000, "r"),  # above the system-bus window
    (0x1200_0000, "r"),  # above the STEE remap region
    (0x10FF_0000, "r"),  # inside the span no detailed SEP-local row describes
    (0x10FF_1000, "w"),
)


class SepAxiMapRefuseCfg:
    """Anchors every seed, plus seed-selected addresses from reserved rows."""

    def __init__(self, seed: int, *, per_region: int = 2) -> None:
        self.seed = seed
        regions = spec_regions()
        rng = SepSeededRng(seed)

        probes: list[MapProbe] = []
        self.skipped: dict[str, int] = {}
        seen: set[tuple[int, str]] = set()

        for addr, op in _ANCHORS:
            why = _excluded(addr)
            if why is not None:
                self.skipped[why] = self.skipped.get(why, 0) + 1
                continue
            if not may_complete(addr, regions):
                reg = region_of(addr, regions)
                probes.append(MapProbe(addr, op, reg.unit if reg else "?", True))
                seen.add((addr, op))

        # Reserved rows, coarse ones last so the fine gaps are probed first.
        reserved = [r for r in regions if r.reserved]
        self.short_regions: dict[str, tuple[int, int]] = {}
        for reg in reserved:
            why = _excluded(reg.base)
            if why is not None:
                self.skipped[why] = self.skipped.get(why, 0) + 1
                continue
            added, spins = 0, 0
            while added < per_region and spins < 16:
                spins += 1
                addr = rng.randrange(reg.base, reg.end_addr + 1) & ~0x3
                if addr < reg.base:
                    continue
                op = "r" if rng.getrandbits(1) else "w"
                if (addr, op) in seen:
                    continue
                if _excluded(addr) is not None:
                    continue
                seen.add((addr, op))
                probes.append(MapProbe(addr, op, reg.unit, False))
                added += 1
            if added < per_region:
                # Probe count is the coverage claim; record the shortfall.
                key = f"0x{reg.base:08x}"
                self.short_regions[key] = (added, per_region)

        if not probes:
            raise RuntimeError(
                "no reserved probe survived the exclusions; the refuse test "
                "would pass without asking the DUT anything"
            )
        self.probes = tuple(probes)

    def summary(self) -> str:
        n_anchor = sum(1 for p in self.probes if p.anchor)
        skips = " ".join(f"{k}={v}" for k, v in sorted(self.skipped.items()))
        short = " ".join(f"{k}={g}/{w}" for k, (g, w) in sorted(self.short_regions.items()))
        return (
            f"seed={self.seed} probes={len(self.probes)} anchors={n_anchor} "
            f"random={len(self.probes) - n_anchor} "
            f"skip=[{skips}] short=[{short}]"
        )


class SepAxiMapRefuse:
    """Drives one map probe and reports whether the fabric refused it."""

    def __init__(self, test) -> None:
        self.test = test
        self.refused = 0
        self.decerr = 0
        self.slverr = 0
        # addr -> (value, label) of the live words sampled by sample_live().
        self.live: dict[int, tuple[int, str]] = {}
        self.reads_compared = 0

    async def _access(self, op: SepAxiOp, addr: int, *, wdata: int = 0):
        seq = SepAxiAccessSeq(
            f"maprefuse_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
            expect_error=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF, seq.timed_out

    async def mapped_csr(self) -> str | None:
        """None when the mapped control read OKAY with its reset value.

        Read through the ordinary path, with no DECERR credit armed: this
        address must complete, so an error response here is a failure rather
        than an expected refusal.
        """
        seq = SepAxiAccessSeq(
            f"maprefuse_ctrl_0x{MAPPED_CSR_ADDR:08x}",
            op=SepAxiOp.READ,
            addr=MAPPED_CSR_ADDR,
            length=4,
            size=2,
        )
        await self.test.start_seq(seq)
        if seq.timed_out:
            return f"mapped CSR 0x{MAPPED_CSR_ADDR:08x} timed out"
        if seq.resp_code != RESP_OKAY:
            return f"mapped CSR 0x{MAPPED_CSR_ADDR:08x} resp={seq.resp_code}, expected OKAY"
        got = seq.rdata & 0xFFFF_FFFF
        if got != MAPPED_CSR_EXP:
            return (
                f"mapped CSR 0x{MAPPED_CSR_ADDR:08x} read 0x{got:08x}, "
                f"expected the generated reset 0x{MAPPED_CSR_EXP:08x}"
            )
        return None

    async def sample_live(self) -> str | None:
        """Read LIVE_DATA_ADDRS over the ordinary path. None when all read OKAY."""
        for addr, label in LIVE_DATA_ADDRS:
            seq = SepAxiAccessSeq(
                f"maprefuse_live_0x{addr:08x}", op=SepAxiOp.READ, addr=addr, length=4, size=2
            )
            await self.test.start_seq(seq)
            if seq.timed_out or seq.resp_code != RESP_OKAY:
                return (
                    f"live word {label} 0x{addr:08x} resp={seq.resp_code} timed_out={seq.timed_out}"
                )
            val = seq.rdata & 0xFFFF_FFFF
            if val:
                self.live[addr] = (val, label)
        return None

    async def probe(self, item: MapProbe) -> str | None:
        """None when the fabric refused. A string names the failure."""
        # One DECERR credit, the way the deadspace probe does it: the monitor
        # treats an unexpected DECERR as a protocol error otherwise.
        self.test.env.axi_monitor.arm_expected_decerr(1)
        data_fail: str | None = None
        if item.op == "w":
            resp, _rd, timed_out = await self._access(SepAxiOp.WRITE, item.addr, wdata=0xFFFF_FFFF)
        else:
            resp, rd, timed_out = await self._access(SepAxiOp.READ, item.addr)
            # The data of a refused read is compared whatever its flavour: a
            # refusal that still returns a live word has reached the unit.
            if not timed_out and resp != RESP_OKAY:
                self.reads_compared += 1
                for live_addr, (val, label) in self.live.items():
                    if rd == val:
                        data_fail = (
                            f"r 0x{item.addr:08x} ({item.unit}) refused with resp={resp} "
                            f"but returned 0x{rd:08x}, the live value of {label} "
                            f"0x{live_addr:08x}"
                        )
                        break

        # A standing credit absorbs the next unexpected DECERR anywhere on this
        # bus, so a probe that saw no DECERR beat hands it back. Keyed off the
        # response rather than the monitor tally: the monitor counts on its own
        # clock edge, which may not have run when start_seq returns.
        if timed_out or resp != 3:
            self.test.env.axi_monitor.release_expected_decerr(1)

        if timed_out:
            return (
                f"{item.op} 0x{item.addr:08x} ({item.unit}) timed out; a "
                "reserved address must be refused, not left hanging"
            )
        if resp == RESP_OKAY:
            return (
                f"{item.op} 0x{item.addr:08x} resp=OKAY, expected refuse -- "
                f"memory_map.adoc lists this address as reserved ({item.unit})"
            )
        self.refused += 1
        if resp == 3:
            self.decerr += 1
        elif resp == 2:
            self.slverr += 1
        return data_fail


def _selftest() -> None:
    cfg = SepAxiMapRefuseCfg(1)
    # Both channels on every seed. The write anchor is what guarantees it, so a
    # map change that routes that address must fail here rather than quietly
    # reducing the walk to reads.
    for seed in (1, 2, 3):
        c = SepAxiMapRefuseCfg(seed)
        ops = {p.op for p in c.probes}
        assert ops == {"r", "w"}, f"seed {seed} covers only {ops}"
        # A floor on the walk. Rows the crossbar routes yield nothing, which is
        # correct, but the shortfall is otherwise only logged -- so a map or
        # crossbar change that routed more rows could shrink the walk toward
        # the anchors while the run still reported a clean pass.
        assert len(c.probes) >= PROBE_FLOOR, (
            f"seed {seed} built {len(c.probes)} probes, below the floor of "
            f"{PROBE_FLOOR}; a reserved row stopped yielding addresses"
        )
        assert len(c.short_regions) <= SHORT_ROW_LIMIT, (
            f"seed {seed} left {len(c.short_regions)} reserved row(s) short of "
            f"their quota, above the limit of {SHORT_ROW_LIMIT}"
        )
        n_anchor = sum(1 for p in c.probes if p.anchor)
        assert n_anchor == ANCHOR_KEPT, (
            f"seed {seed} kept {n_anchor} anchors, expected {ANCHOR_KEPT}"
        )
    assert len(cfg.probes) >= 10, f"only {len(cfg.probes)} probes"
    # Every probe must be reserved per the spec, or the test is asking the DUT
    # to refuse something it is supposed to answer.
    regions = spec_regions()
    for p in cfg.probes:
        assert not may_complete(p.addr, regions), (
            f"probe 0x{p.addr:08x} is allocated ({p.unit}); refusing it would "
            "be a false expectation"
        )
        assert _excluded(p.addr) is None, f"probe 0x{p.addr:08x} is excluded"
    # Seed-stable membership: the anchor set does not move.
    a1 = {(p.addr, p.op) for p in SepAxiMapRefuseCfg(1).probes if p.anchor}
    a2 = {(p.addr, p.op) for p in SepAxiMapRefuseCfg(2).probes if p.anchor}
    assert a1 == a2, "anchor set moved with the seed"


_selftest()

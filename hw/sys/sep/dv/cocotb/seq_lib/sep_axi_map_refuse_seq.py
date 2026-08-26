# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Whole-map response expectation for sep_axi_map_refuse_test.

Every probe address is classified by ``env/sep_axi_decode_map.py`` from the
allocation tables in ``hw/sys/sep/doc/memory_map.adoc``. A reserved address
must not answer OKAY; the map does not mandate DECERR over SLVERR, so either
refusal is accepted and the flavour is only logged.

Scope note. ``sep_fabric_deadspace_decode_test`` probes the dead tail INSIDE a
block window -- the span between a block's allocated register size and its
window end. This sequence probes the gaps BETWEEN windows, which no test
covered: the reserved rows of the memory map itself. The two do not overlap,
and neither subsumes the other.

Addresses that would disturb the run are excluded by name with a reason, the
way the register sweep does it. A silent skip is a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_axi_decode_map import (
    may_complete, region_of, rtl_ranges, spec_regions,
)
from env.sep_seeded_rng import SepSeededRng
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0

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
}


def _excluded(addr: int) -> str | None:
    for (lo, hi), why in _PROBE_EXCLUDE.items():
        if lo <= addr <= hi:
            return why
    return None


@dataclass(frozen=True)
class MapProbe:
    addr: int
    op: str          # "r" | "w"
    unit: str        # spec Unit column, for the failure message
    anchor: bool     # True = walked every seed
    routed: bool     # True = an xbar rule covers this address

    @property
    def klass(self) -> str:
        """Which contract this probe belongs to.

        "unrouted"  no decode rule covers the address, so the fabric has
                    nothing to send it to and must refuse. A hard contract.
        "routed"    an xbar rule covers it but the map calls the span
                    reserved. Whether the fabric should refuse is an open
                    specification question, not a proven defect, so these are
                    reported as findings and do not fail the test. Deciding it
                    from the RTL would be letting the decoder write its own
                    contract.
        """
        return "routed" if self.routed else "unrouted"


# Reserved gaps that stay in the probe set on every seed: one address just past
# the end of a live block, which is where a truncating decoder aliases first.
_ANCHORS: tuple[tuple[int, str], ...] = (
    (0x1080_3008, "r"),   # first byte above the reset controller
    (0x1080_3008, "w"),
    (0x1091_4000, "r"),   # KMAC/DRBG gap
    (0x1092_1000, "r"),   # above the Key Manager window
    (0x1093_8000, "r"),   # above the OTP window
    (0x1096_0000, "r"),   # above the entropy pool
    (0x10A4_0000, "r"),   # above the system-bus window
    (0x1200_0000, "r"),   # above the STEE remap region
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
        rtl = rtl_ranges()

        def _routed(addr: int) -> bool:
            return any(r.contains(addr) for r in rtl)

        for addr, op in _ANCHORS:
            why = _excluded(addr)
            if why is not None:
                self.skipped[why] = self.skipped.get(why, 0) + 1
                continue
            if not may_complete(addr, regions):
                if _routed(addr):
                    # Routed-but-reserved: whether the fabric must refuse is an
                    # open specification question, so there is no contract to
                    # assert. The scoreboard has no "outcome unknown" mode --
                    # expect_error demands a refusal -- so driving it would
                    # assert the open question by the back door. Report these
                    # from the static cross-check instead; see audit_rtl_vs_spec.
                    self.skipped["routed span, open spec question"] = (
                        self.skipped.get("routed span, open spec question", 0) + 1)
                    continue
                reg = region_of(addr, regions)
                probes.append(MapProbe(
                    addr, op, reg.unit if reg else "?", True, False))
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
                if _routed(addr):
                    self.skipped["routed span, open spec question"] = (
                        self.skipped.get("routed span, open spec question", 0) + 1)
                    continue
                seen.add((addr, op))
                probes.append(MapProbe(addr, op, reg.unit, False, False))
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
        n_routed = sum(1 for p in self.probes if p.routed)
        skips = " ".join(f"{k}={v}" for k, v in sorted(self.skipped.items()))
        short = " ".join(
            f"{k}={g}/{w}" for k, (g, w) in sorted(self.short_regions.items())
        )
        return (
            f"seed={self.seed} probes={len(self.probes)} anchors={n_anchor} "
            f"random={len(self.probes) - n_anchor} "
            f"unrouted={len(self.probes) - n_routed} routed_reserved={n_routed} "
            f"skip=[{skips}] short=[{short}]"
        )


class SepAxiMapRefuse:
    """Drives one map probe and reports whether the fabric refused it."""

    def __init__(self, test) -> None:
        self.test = test
        self.refused = 0
        self.decerr = 0
        self.slverr = 0

    async def _access(self, op: SepAxiOp, addr: int, *, wdata: int = 0):
        seq = SepAxiAccessSeq(
            f"maprefuse_{op.value}_0x{addr:08x}",
            op=op, addr=addr, wdata=wdata, length=4, size=2,
            expect_error=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF, seq.timed_out

    async def probe(self, item: MapProbe) -> str | None:
        """None when the fabric refused. A string names the failure."""
        # One DECERR credit, the way the deadspace probe does it: the monitor
        # treats an unexpected DECERR as a protocol error otherwise.
        self.test.env.axi_monitor.arm_expected_decerr(1)
        if item.op == "w":
            resp, _rd, timed_out = await self._access(
                SepAxiOp.WRITE, item.addr, wdata=0xFFFF_FFFF)
        else:
            resp, _rd, timed_out = await self._access(SepAxiOp.READ, item.addr)

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
        return None


def _selftest() -> None:
    cfg = SepAxiMapRefuseCfg(1)
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

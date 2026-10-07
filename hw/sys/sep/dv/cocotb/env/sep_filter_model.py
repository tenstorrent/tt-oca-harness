# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reference model of one SEP AXI filter instance (inbound or outbound).

Written from the filter specification, never from the RTL:

* ``hw/ip/axi_filter/doc/index.adoc``, "Instances", "Match, Then Permit",
  "Address Range Granule" and "Blocked Transactions";
* ``hw/ip/axi_filter/regs/gen/adoc/filter_ctrl.adoc`` (FILTER_CONFIG,
  START_ADDR, END_ADDR);
* ``hw/sys/smc/doc/assets/smc-traffic-filters.svg``: an entry matches the
  source ID when ``src_id`` is 0 or equals AxUSER[3:0].

Rules:

* An entry matches a transaction when it is enabled, the address lies in its
  widened range, AxPROT[1] equals ``allow_ns``, the source ID matches and
  either ``allow_burst`` is 1 or AxLEN is 0.
* The widened range: START_ADDR rounds down and END_ADDR rounds up to the
  granule, 4 KiB when ``allow_burst`` is 1 and 8 bytes when it is 0. A range
  that straddles a granule boundary admits both granules.
* The lowest-numbered matching entry wins, and only its permission bit for the
  direction counts. A clear permission bit blocks. A failed match falls
  through to the next entry. No match blocks.
* The read (AR) and write (AW) channels are decoded independently.

The model takes only the programmed register fields and the request
attributes. It states no verdict for an inverted range or for a range that
touches 2^56-1, because the specification states none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GRANULE_4K = 0x1000
GRANULE_8B = 0x8
ADDR_MASK = (1 << 56) - 1

# Match terms, reported in the order a failing entry is described.
TERM_ENABLED = "entry_disabled"
TERM_RANGE = "range"
TERM_NS = "ns_mismatch"
TERM_SRC = "src_mismatch"
TERM_BURST = "burst_mismatch"


@dataclass
class FilterEntry:
    """Programmed fields of one entry (the RDL fields of FILTER_CONFIG,
    START_ADDR and END_ADDR). ``group_id`` is carried for logging only: the
    specification states that a transaction with group ID 0 matches whatever
    the field holds."""

    start: int = 0
    end: int = 0
    enabled: bool = False
    read_allowed: bool = False
    write_allowed: bool = False
    allow_ns: bool = False
    allow_burst: bool = False
    src_id: int = 0
    group_id: int = 0

    @property
    def granule(self) -> int:
        return GRANULE_4K if self.allow_burst else GRANULE_8B

    @property
    def widened(self) -> tuple[int, int]:
        """(lowest admitted byte, highest admitted byte)."""
        g = self.granule
        return (self.start & ~(g - 1)) & ADDR_MASK, (self.end | (g - 1)) & ADDR_MASK

    def covers(self, addr: int) -> bool:
        lo, hi = self.widened
        return lo <= (addr & ADDR_MASK) <= hi

    def failed_terms(self, addr: int, *, prot1: int, user: int, axlen: int) -> list[str]:
        """Every match term the request fails, in a fixed order."""
        fails = []
        if not self.enabled:
            fails.append(TERM_ENABLED)
        if not self.covers(addr):
            fails.append(TERM_RANGE)
        if int(self.allow_ns) != (prot1 & 1):
            fails.append(TERM_NS)
        if self.src_id != 0 and self.src_id != (user & 0xF):
            fails.append(TERM_SRC)
        if not self.allow_burst and axlen != 0:
            fails.append(TERM_BURST)
        return fails

    def permits(self, write: bool) -> bool:
        return self.write_allowed if write else self.read_allowed


@dataclass
class FilterVerdict:
    allowed: bool
    winner: int | None
    """Index of the lowest matching entry, or None for no match."""
    reason: str
    """``allow``, ``perm_block`` or ``no_match``."""
    lowest_cover: int | None = None
    """Lowest entry whose widened range covers the address (enabled or not)."""
    lowest_cover_fails: list[str] = field(default_factory=list)
    fallthrough: bool = False
    """The lowest covering entry failed a match term and a higher entry matched."""
    hides_allow: bool = False
    """The winner blocks while a higher matching entry would admit."""

    @property
    def resp(self) -> str:
        return "OKAY" if self.allowed else "DECERR"

    def summary(self) -> str:
        w = "none" if self.winner is None else str(self.winner)
        return (
            f"winner={w} reason={self.reason} expect={self.resp} "
            f"lowest_cover={self.lowest_cover} fails={','.join(self.lowest_cover_fails) or '-'}"
        )


class FilterModel:
    """One filter instance: ``n`` entries, index 0 the lowest."""

    def __init__(self, n_entries: int, name: str) -> None:
        self.name = name
        self.entries = [FilterEntry() for _ in range(n_entries)]

    def reset(self) -> None:
        """The reset state: every entry disabled (filter_ctrl.adoc)."""
        self.entries = [FilterEntry() for _ in self.entries]

    def set(self, idx: int, entry: FilterEntry) -> None:
        self.entries[idx] = entry

    def disable(self, idx: int) -> None:
        self.entries[idx].enabled = False

    def verdict(
        self, addr: int, *, write: bool, prot1: int = 0, user: int = 0, axlen: int = 0
    ) -> FilterVerdict:
        """The verdict of one request on one channel."""
        lowest_cover = None
        lowest_fails: list[str] = []
        winner = None
        for i, e in enumerate(self.entries):
            fails = e.failed_terms(addr, prot1=prot1, user=user, axlen=axlen)
            if lowest_cover is None and TERM_RANGE not in fails:
                lowest_cover = i
                lowest_fails = fails
            if not fails:
                winner = i
                break
        if winner is None:
            return FilterVerdict(False, None, "no_match", lowest_cover, lowest_fails)
        allowed = self.entries[winner].permits(write)
        hides = False
        if not allowed:
            for e in self.entries[winner + 1 :]:
                if not e.failed_terms(addr, prot1=prot1, user=user, axlen=axlen) and e.permits(write):
                    hides = True
                    break
        return FilterVerdict(
            allowed,
            winner,
            "allow" if allowed else "perm_block",
            lowest_cover,
            lowest_fails,
            fallthrough=lowest_cover is not None and lowest_cover != winner,
            hides_allow=hides,
        )

    def admitted_range(self, idx: int) -> tuple[int, int]:
        """The widened range of one entry."""
        return self.entries[idx].widened


def _selftest() -> None:
    m = FilterModel(4, "in")
    # Entry 1 covers one 8-byte granule, read only, allow_ns 1.
    m.set(1, FilterEntry(start=0x1000_0004, end=0x1000_0004, enabled=True, read_allowed=True,
                         allow_ns=True))
    assert m.verdict(0x1000_0000, write=False, prot1=1).allowed
    assert m.verdict(0x1000_0007, write=False, prot1=1).allowed
    assert not m.verdict(0x1000_0008, write=False, prot1=1).allowed
    assert m.verdict(0x1000_0000, write=True, prot1=1).reason == "perm_block"
    assert m.verdict(0x1000_0000, write=False, prot1=0).reason == "no_match"
    # Entry 0 disabled over the same range: fall-through to entry 1.
    m.set(0, FilterEntry(start=0x1000_0000, end=0x1000_0FFF, enabled=False, read_allowed=True,
                         write_allowed=True, allow_ns=True))
    v = m.verdict(0x1000_0000, write=False, prot1=1)
    assert v.allowed and v.winner == 1 and v.fallthrough and v.lowest_cover_fails == [TERM_ENABLED]
    # 4 KiB granule straddle admits both pages.
    m.reset()
    m.set(2, FilterEntry(start=0x8000_2FF0, end=0x8000_3010, enabled=True, read_allowed=True,
                         allow_ns=False, allow_burst=True))
    assert m.admitted_range(2) == (0x8000_2000, 0x8000_3FFF)
    assert not m.verdict(0x8000_1FFC, write=False).allowed
    assert m.verdict(0x8000_3FFC, write=False).allowed
    # Source ID: 0 is a wildcard; a non-zero value matches AxUSER[3:0] only.
    m.reset()
    m.set(0, FilterEntry(start=0, end=0xFFF, enabled=True, read_allowed=True, src_id=5))
    m.set(3, FilterEntry(start=0, end=0xFFF, enabled=True, read_allowed=True, src_id=0))
    assert m.verdict(0x10, write=False, user=0x15).winner == 0
    v = m.verdict(0x10, write=False, user=0x4)
    assert v.winner == 3 and v.lowest_cover_fails == [TERM_SRC]
    # A burst fails an entry with allow_burst 0.
    m.reset()
    m.set(0, FilterEntry(start=0, end=0x1FFF, enabled=True, read_allowed=True))
    assert m.verdict(0x10, write=False, axlen=1).reason == "no_match"


if __name__ == "__main__":
    _selftest()
    print("sep_filter_model selftest: PASS")

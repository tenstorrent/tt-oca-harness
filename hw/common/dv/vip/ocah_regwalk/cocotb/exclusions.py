# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hand-named exclusions of a register walk, each with a reason, and their accounting.

The RDL arms in ``access`` cover what the field contract states. Everything a
walk must still leave alone for a reason outside the RDL -- a fabric remap, a
FIFO port, a lock, an OTP trigger -- is named here, so that every register of an
inventory is either admitted or excluded with a reason, and a silent shrink of
the walk is impossible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from .regmodel import RegInst

ReasonFn = Callable[[RegInst], "str | None"]


@dataclass(frozen=True)
class Partition:
    """The outcome of ``ExclusionSet.account``: every register admitted or excluded."""

    admitted: tuple[RegInst, ...]
    excluded: tuple[tuple[RegInst, str], ...]

    def tally(self) -> dict[str, int]:
        """Excluded-register count per reason, sorted by reason."""
        counts: dict[str, int] = {}
        for _reg, why in self.excluded:
            counts[why] = counts.get(why, 0) + 1
        return dict(sorted(counts.items()))

    def summary(self) -> str:
        skipped = " ".join(f"{why}={n}" for why, n in self.tally().items())
        return f"admitted={len(self.admitted)} excluded={len(self.excluded)} [{skipped}]"


def _checked(entries: Mapping | None, what: str) -> dict:
    out = dict(entries or {})
    for key, why in out.items():
        if not isinstance(why, str) or not why.strip():
            raise ValueError(f"{what} exclusion {key!r} needs a reason")
    return out


class ExclusionSet:
    """Named exclusions keyed four ways, consulted in this order:

    * ``named``: ``(block, name)`` for one register, ``(block, base_name)`` for
      every element of a register array, ``(block, None)`` for a whole block;
    * ``name_suffix``: ``name == suffix`` or ``name`` ends in ``"_" + suffix``;
    * ``name_prefix``, ``name_substring``: on the register name;
    * ``block_prefix``: on the block name.
    """

    def __init__(
        self,
        *,
        named: Mapping[tuple[str, str | None], str] | None = None,
        name_suffix: Mapping[str, str] | None = None,
        name_prefix: Mapping[str, str] | None = None,
        name_substring: Mapping[str, str] | None = None,
        block_prefix: Mapping[str, str] | None = None,
    ) -> None:
        self.named = _checked(named, "named")
        self.name_suffix = _checked(name_suffix, "name_suffix")
        self.name_prefix = _checked(name_prefix, "name_prefix")
        self.name_substring = _checked(name_substring, "name_substring")
        self.block_prefix = _checked(block_prefix, "block_prefix")
        self._last: Partition | None = None

    def _named_key(self, reg: RegInst) -> tuple[str, str | None] | None:
        for key in ((reg.block, reg.name), (reg.block, reg.base_name), (reg.block, None)):
            if key in self.named:
                return key
        return None

    def reason(self, reg: RegInst) -> str | None:
        key = self._named_key(reg)
        if key is not None:
            return self.named[key]
        for suffix, why in self.name_suffix.items():
            if reg.name == suffix or reg.name.endswith("_" + suffix):
                return why
        for prefix, why in self.name_prefix.items():
            if reg.name.startswith(prefix):
                return why
        for fragment, why in self.name_substring.items():
            if fragment in reg.name:
                return why
        for prefix, why in self.block_prefix.items():
            if reg.block.startswith(prefix):
                return why
        return None

    def account(
        self,
        inventory: Iterable[RegInst],
        *reason_fns: ReasonFn,
        admitted: Iterable[RegInst | str] | None = None,
        strict: bool = True,
    ) -> Partition:
        """Partition ``inventory`` into admitted and excluded registers.

        ``reason_fns`` are consulted first, then this set. With ``admitted``
        given, a register with no reason must be in it (by instance or symbol),
        and one in it must have no reason. With ``strict``, every ``named``
        entry must match a register of the inventory. Each violation raises
        ``LookupError`` naming the registers, so a walk cannot shrink silently.
        """
        regs = tuple(inventory)
        admit = (
            None
            if admitted is None
            else {r.symbol if isinstance(r, RegInst) else r for r in admitted}
        )
        kept: list[RegInst] = []
        dropped: list[tuple[RegInst, str]] = []
        hit: set[tuple[str, str | None]] = set()
        unaccounted: list[str] = []
        conflicts: list[str] = []
        for reg in regs:
            why = None
            for fn in reason_fns:
                why = fn(reg)
                if why is not None:
                    break
            key = self._named_key(reg)
            if key is not None:
                hit.add(key)
            if why is None:
                why = self.reason(reg)
            if why is not None:
                dropped.append((reg, why))
                if admit is not None and reg.symbol in admit:
                    conflicts.append(f"{reg.symbol} ({why})")
            elif admit is None or reg.symbol in admit:
                kept.append(reg)
            else:
                unaccounted.append(reg.symbol)
        if unaccounted:
            raise LookupError(
                "registers neither admitted nor excluded with a reason: " + ", ".join(unaccounted)
            )
        if conflicts:
            raise LookupError("admitted registers that carry an exclusion: " + ", ".join(conflicts))
        if admit is not None:
            unknown = sorted(admit - {r.symbol for r in regs})
            if unknown:
                raise LookupError(
                    "admitted registers absent from the inventory: " + ", ".join(unknown)
                )
        if strict:
            stale = sorted(f"{b}.{n}" for b, n in self.named if (b, n) not in hit)
            if stale:
                raise LookupError("named exclusions that match no register: " + ", ".join(stale))
        self._last = Partition(tuple(kept), tuple(dropped))
        return self._last

    def tally(self) -> dict[str, int]:
        """The per-reason counts of the last ``account``."""
        if self._last is None:
            raise RuntimeError("ExclusionSet.tally before account")
        return self._last.tally()

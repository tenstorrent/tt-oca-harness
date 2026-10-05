# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Firmware symbol table for PC symbolization.

Parses the ``nm -B -n`` listing the firmware build emits next to every ELF
(``<test>.<mode>.sym``, see hw/common/dv/fw/compile.mk) and resolves retired
PCs to ``name+0xoff`` strings for the CPU-trace monitor's backtraces. Plain
Python over the committed build artifacts -- no toolchain (addr2line/objdump)
is needed at simulation time.

Trace PCs are link addresses: the ``-0xC0000000`` bias in fw.mk only rebases
the TCM hex images, the ELF (and therefore nm) keeps the executed addresses.
Multiple tables merge into one lookup so a run that executes Boot ROM plus a
loaded image (e.g. BL1) symbolizes both ranges.
"""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path

# nm type codes that mark code symbols. Text (t/T) plus weak (w/W): picolibc
# exports several weak entry points that are the only name a PC inside them has.
_CODE_TYPES = frozenset("tTwW")

# A PC this far past the nearest preceding symbol is not inside that function --
# it falls in the gap between two loaded images (e.g. ROM vs ICCM ranges when
# only one image's table is loaded). Report bare hex instead of a bogus name.
_MAX_OFF = 0x1_0000


class SepFwSymbols:
    """Merged, sorted (addr -> name) map over one or more nm listings."""

    def __init__(self) -> None:
        self._syms: list[tuple[int, str]] = []
        self._addrs: list[int] = []
        self.loaded: list[str] = []

    def load(self, path: str | Path) -> int:
        """Merge one ``nm -B -n`` listing; returns the number of code symbols.

        Lines are ``<hex addr> <type> <name>``; undefined symbols have no
        address column and are skipped, as are non-code types (data/bss would
        otherwise swallow PCs that fall past the last text symbol).
        """
        path = Path(path)
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split(None, 2)
            if len(parts) != 3 or parts[1] not in _CODE_TYPES:
                continue
            try:
                addr = int(parts[0], 16)
            except ValueError:
                continue
            self._syms.append((addr, parts[2]))
            count += 1
        self._syms.sort()
        self._addrs = [addr for addr, _ in self._syms]
        self.loaded.append(str(path))
        return count

    def lookup(self, pc: int) -> str:
        """``name+0xoff`` for the symbol covering ``pc``; bare hex outside any."""
        i = bisect_right(self._addrs, pc) - 1
        if i < 0:
            return f"0x{pc:08x}"
        addr, name = self._syms[i]
        off = pc - addr
        if off >= _MAX_OFF:
            return f"0x{pc:08x}"
        return name if off == 0 else f"{name}+0x{off:x}"

    def __len__(self) -> int:
        return len(self._syms)

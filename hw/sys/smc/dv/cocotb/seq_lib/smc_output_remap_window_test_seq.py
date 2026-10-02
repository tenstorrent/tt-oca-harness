# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound traffic through the M-mode and hypervisor remap windows.

The output fabric sends an outbound access whose address falls in the M-mode or
the hypervisor (Xvisor) window to that window's remap table; every other
outbound address passes straight through. Each window is decoded twice: once at
`LOCAL_BASE` plus the window's offset and once at `GLOBAL_BASE` plus it. The
offset is the window's generated base (`SMC_TOP_MMODE_REGION_BASE_ADDR`,
`SMC_TOP_XVISOR_REGION_BASE_ADDR`) less the SMC register window base, and the
size is the generated `*_REGION_SIZE`. With the reset bases, the local copies sit
just above the SMC's own 16 MB aperture. So an inbound master that addresses
them is sent out, and no leaf had sent anything there.

`output_remap.rdl` describes an entry as an `offset` that replaces the upper bits
of the address when the entry's `valid` bit is set. The entry is selected by the
1 MB slot of the access within its window, and the low 20 bits are kept. The
sequence programs M-mode entries 0 and 1 and hypervisor entry 0 with distinct
offsets in SYS_OUT memory and `valid` set, and M-mode entry 2 with an offset but
`valid` clear. It then writes and reads a word through each window's local and
global copy over the JTAG ingress, through M-mode slot 2, plus one address just
past the hypervisor window. Each write must land in the SYS_OUT responder's
memory at the address the entry predicts, and nowhere else:

* the window address itself still holds its sentinel;
* the address past the hypervisor window passes through unremapped;
* the address in M-mode slot 2 passes through unremapped, and entry 2's offset
  target still holds its sentinel;
* a read through the same window returns the word.

**Source-ID matching in the outbound filter.** `fabric.adoc` ("SMC Source ID by
Traffic Path") has traffic through the M-mode remap carry `MMODE_ID` and
traffic through the hypervisor remap carry `OTHER_ID`. The document names the
values; `smc_pkg.sv` defines them, and the leaf reads `MMODE_ID` from there.

While the words go out, outbound filter entry 0 allows reads and writes to the
M-mode targets for source `MMODE_ID`. Entry 1 matches the hypervisor target for
the same source and allows nothing. The hypervisor words carry `OTHER_ID`, so
entry 1 must not match them: if source-ID matching were ignored, entry 1 would
deny them and those legs would fail. Both entries are restored to their RDL
reset.

The remap entries are restored to their reset afterwards.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    _field_mask,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_contract

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    SMC_MMODE_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_MMODE_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
)

_REG_WINDOW_BASE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
_MMODE_BASE = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR")
_MMODE_SIZE = smc_addr("SMC_TOP_MMODE_REGION_SIZE")
_XVISOR_BASE = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR")
_XVISOR_SIZE = smc_addr("SMC_TOP_XVISOR_REGION_SIZE")
_MMODE_OFFSET = _MMODE_BASE - _REG_WINDOW_BASE
_XVISOR_OFFSET = _XVISOR_BASE - _REG_WINDOW_BASE

# output_remap.rdl: an entry covers one 1 MB slot and keeps the low 20 bits.
_SLOT_BITS = 20
_SLOT = 1 << _SLOT_BITS
_ADDR_MASK = (1 << 56) - 1
_REMAP_H = _REPO / "hw" / "ip" / "output_remap" / "regs" / "gen" / "c" / "output_remap.h"
_VALID = _field_mask(_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__VALID_bm")

# Remap targets in SYS_OUT memory, one per programmed entry, 1 MB aligned.
_MMODE0_TARGET = 0x0240_0000
_MMODE1_TARGET = 0x0250_0000
_XVISOR0_TARGET = 0x0260_0000
_MMODE2_STALE_TARGET = 0x0270_0000
# (label, ATTRS address, value written)
_ENTRIES = (
    ("MMODE0", SMC_MMODE_REMAP_0__REGION_REGION_ATTRS_REG_ADDR, _VALID | _MMODE0_TARGET),
    ("MMODE1", SMC_MMODE_REMAP_1__REGION_REGION_ATTRS_REG_ADDR, _VALID | _MMODE1_TARGET),
    ("MMODE2", SMC_MMODE_REMAP_2__REGION_REGION_ATTRS_REG_ADDR, _MMODE2_STALE_TARGET),
    ("XVISOR0", SMC_XVISOR_REMAP_0__REGION_REGION_ATTRS_REG_ADDR, _VALID | _XVISOR0_TARGET),
)

_WORD = 8

_SMC_PKG = Path(__file__).resolve().parents[6] / "hw" / "sys" / "smc" / "rtl" / "smc_pkg.sv"


def _pkg_user(name: str) -> int:
    match = re.search(rf"{name}\s*=\s*smc_axi_user_t'\('?h?([0-9A-Fa-f]+)\)", _SMC_PKG.read_text())
    assert match, f"{name} not found in {_SMC_PKG}"
    text = match.group(0)
    return int(match.group(1), 16 if "'h" in text else 10)


MMODE_ID = _pkg_user("MmodeSrcId")
OTHER_ID = _pkg_user("OthersSrcId")
assert MMODE_ID != 0 and MMODE_ID != OTHER_ID, "entry 0 needs a non-wildcard M-mode source ID"

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"


def _filter(field: str) -> int:
    return _field_mask(_FILTER_H, f"FILTER_CTRL__FILTER_CONFIG__{field.upper()}_bm")


def _filter_bp(field: str) -> int:
    return _field_mask(_FILTER_H, f"FILTER_CTRL__FILTER_CONFIG__{field.upper()}_bp")


_FILTER_BASE = (
    _filter("entry_enabled")
    | _filter("allow_burst")
    | (3 << _filter_bp("data_bus_width"))
    | (MMODE_ID << _filter_bp("src_id"))
)
# (entry, start, end, config)
_FILTER_ENTRIES = (
    (
        0,
        _MMODE0_TARGET,
        _MMODE1_TARGET + _SLOT - 1,
        _FILTER_BASE | _filter("read_allowed") | _filter("write_allowed"),
    ),
    (1, _XVISOR0_TARGET, _XVISOR0_TARGET + _SLOT - 1, _FILTER_BASE),
)


def _outbound(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A


def _remapped(addr: int, region_base: int, targets: dict[int, int]) -> int:
    """SYS_OUT address output_remap.rdl predicts for ``addr`` in a window at ``region_base``.

    ``targets`` maps each valid slot to its offset; any other slot passes through.
    """
    adjusted = (addr - region_base) & _ADDR_MASK
    slot = (adjusted >> _SLOT_BITS) & 0x7
    if slot not in targets:
        return addr
    return targets[slot] | (adjusted & (_SLOT - 1))


_MMODE_TARGETS = {0: _MMODE0_TARGET, 1: _MMODE1_TARGET}
_XVISOR_TARGETS = {0: _XVISOR0_TARGET}

_MMODE2_ADDR = LOCAL_BASE_RESET + _MMODE_OFFSET + 2 * _SLOT + 0x1C0
_MMODE2_STALE = _MMODE2_STALE_TARGET | ((_MMODE2_ADDR - _MMODE_BASE) & (_SLOT - 1))

# (label, address the master uses, SYS_OUT address the word must land at)
_LEGS = (
    (
        "MMODE_LOCAL_SLOT0",
        LOCAL_BASE_RESET + _MMODE_OFFSET + 0x40,
        _remapped(LOCAL_BASE_RESET + _MMODE_OFFSET + 0x40, _MMODE_BASE, _MMODE_TARGETS),
    ),
    (
        "MMODE_GLOBAL_SLOT0",
        GLOBAL_BASE_RESET + _MMODE_OFFSET + 0x80,
        _remapped(GLOBAL_BASE_RESET + _MMODE_OFFSET + 0x80, _MMODE_BASE, _MMODE_TARGETS),
    ),
    (
        "MMODE_LOCAL_SLOT1",
        LOCAL_BASE_RESET + _MMODE_OFFSET + _SLOT + 0xC0,
        _remapped(LOCAL_BASE_RESET + _MMODE_OFFSET + _SLOT + 0xC0, _MMODE_BASE, _MMODE_TARGETS),
    ),
    (
        "XVISOR_LOCAL_SLOT0",
        LOCAL_BASE_RESET + _XVISOR_OFFSET + 0x100,
        _remapped(LOCAL_BASE_RESET + _XVISOR_OFFSET + 0x100, _XVISOR_BASE, _XVISOR_TARGETS),
    ),
    (
        "XVISOR_GLOBAL_SLOT0",
        GLOBAL_BASE_RESET + _XVISOR_OFFSET + 0x140,
        _remapped(GLOBAL_BASE_RESET + _XVISOR_OFFSET + 0x140, _XVISOR_BASE, _XVISOR_TARGETS),
    ),
    (
        "MMODE_LOCAL_SLOT2_INVALID",
        _MMODE2_ADDR,
        _remapped(_MMODE2_ADDR, _MMODE_BASE, _MMODE_TARGETS),
    ),
    (
        "PAST_XVISOR_LOCAL",
        LOCAL_BASE_RESET + _XVISOR_OFFSET + _XVISOR_SIZE + 0x180,
        LOCAL_BASE_RESET + _XVISOR_OFFSET + _XVISOR_SIZE + 0x180,
    ),
)


class smc_output_remap_window_test_seq(SmcCsrSeq):
    """Write and read through both copies of both remap windows, and past them."""

    def __init__(self, name: str = "smc_output_remap_window_test_seq") -> None:
        super().__init__(name)
        self.legs_checked = 0

    async def _jtag(self, op: SmcSysAxiOp, addr: int, data: int | None = None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"remap_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = _WORD
        if data is not None:
            item.wdata = data
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        assert item.resp_code == 0, (
            f"JTAG {op.value} at 0x{addr:x} completed with resp {item.resp_code}, not OKAY"
        )
        return item

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"

        # The local copies lie above the SMC's own aperture and the global copies
        # above the global one, so both leave through the output fabric.
        assert _MMODE_OFFSET >= REGION_SIZE_RESET and _XVISOR_OFFSET >= REGION_SIZE_RESET
        assert _MMODE_SIZE == _XVISOR_SIZE and _XVISOR_OFFSET == _MMODE_OFFSET + _MMODE_SIZE
        targets = [target for _label, _addr, target in _LEGS]
        assert len(set(targets)) == len(targets), "two legs land on the same SYS_OUT word"

        for label, addr, value in _ENTRIES:
            await self.csr_read(
                f"{label}_ATTRS_RESET",
                addr,
                expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=_WORD,
            )
            await self.csr_write(f"{label}_ATTRS", addr, value, length=_WORD)
            await self.csr_read(f"{label}_ATTRS_RB", addr, expected=value, length=_WORD)

        resets = {}
        for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
            resets[reg] = rdl_contract(f"smc_outbound_filter_ctrl/{reg}").reset_word
        for entry, start, end, config in _FILTER_ENTRIES:
            await self.csr_read(
                f"OB{entry}_CONFIG_RESET",
                _outbound("FILTER_CONFIG", entry),
                expected=resets["FILTER_CONFIG"],
                length=_WORD,
            )
            await self.csr_write(
                f"OB{entry}_START", _outbound("START_ADDR", entry), start, length=_WORD
            )
            await self.csr_write(f"OB{entry}_END", _outbound("END_ADDR", entry), end, length=_WORD)
            await self.csr_write(
                f"OB{entry}_CONFIG", _outbound("FILTER_CONFIG", entry), config, length=_WORD
            )
            await self.csr_read(
                f"OB{entry}_CONFIG_RB",
                _outbound("FILTER_CONFIG", entry),
                expected=config,
                length=_WORD,
            )

        for index, (label, addr, target) in enumerate(_LEGS):
            word = 0xC0DE_0000_0000_0000 | (index << 40) | (addr & 0xFFFF_FFFF)
            responder.write_int(target, _SENTINEL, _WORD)
            if target != addr:
                responder.write_int(addr, _SENTINEL, _WORD)
            if addr == _MMODE2_ADDR:
                responder.write_int(_MMODE2_STALE, _SENTINEL, _WORD)
            await self._jtag(SmcSysAxiOp.WRITE, addr, word)
            landed = responder.read_int(target, _WORD)
            assert landed == word, (
                f"[{label}] a write at 0x{addr:x} left SYS_OUT 0x{target:x} holding "
                f"0x{landed:016x}; output_remap.rdl puts it there, expected 0x{word:016x}"
            )
            if target != addr:
                untouched = responder.read_int(addr, _WORD)
                assert untouched == _SENTINEL, (
                    f"[{label}] SYS_OUT 0x{addr:x}, the unremapped address, changed to "
                    f"0x{untouched:016x}; the write should only have reached 0x{target:x}"
                )
            if addr == _MMODE2_ADDR:
                stale = responder.read_int(_MMODE2_STALE, _WORD)
                assert stale == _SENTINEL, (
                    f"[{label}] SYS_OUT 0x{_MMODE2_STALE:x}, where M-mode entry 2's offset "
                    f"points, changed to 0x{stale:016x}; entry 2 is not valid, so the write "
                    f"should have passed through to 0x{addr:x}"
                )
            got = await self._jtag(SmcSysAxiOp.READ, addr)
            assert got.rdata == word, (
                f"[{label}] a read at 0x{addr:x} returned 0x{got.rdata:016x}; the write "
                f"through the same window put 0x{word:016x} at 0x{target:x}"
            )
            self.legs_checked += 1
            cocotb.log.info(
                "[%s] 0x%x -> SYS_OUT 0x%x: written, landed and read back", label, addr, target
            )

        for entry, _start, _end, _config in _FILTER_ENTRIES:
            for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
                await self.csr_write(
                    f"OB{entry}_{reg}_RESTORE", _outbound(reg, entry), resets[reg], length=_WORD
                )
                await self.csr_read(
                    f"OB{entry}_{reg}_RESTORE_RB",
                    _outbound(reg, entry),
                    expected=resets[reg],
                    length=_WORD,
                )

        for label, addr, _value in _ENTRIES:
            await self.csr_write(
                f"{label}_ATTRS_RESTORE",
                addr,
                OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=_WORD,
            )
            await self.csr_read(
                f"{label}_ATTRS_RESTORE_RB",
                addr,
                expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=_WORD,
            )

        cocotb.log.info(
            "CHK-OUTPUT-REMAP-WINDOWS: %d outbound words went through the M-mode and "
            "hypervisor windows at their LOCAL_BASE and GLOBAL_BASE copies and past the "
            "hypervisor window; each landed in SYS_OUT memory at the address the "
            "programmed entry predicts (%s), left the unremapped address alone, and read "
            "back through the same window; the word through the M-mode entry with valid "
            "clear passed through and left that entry's offset target alone; outbound filter entries matching source 0x%x "
            "(M-mode) allowed the M-mode words and did not catch the hypervisor words, which "
            "carry source 0x%x",
            self.legs_checked,
            ", ".join(f"0x{a:x}->0x{t:x}" for _l, a, t in _LEGS),
            MMODE_ID,
            OTHER_ID,
        )

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
them is sent out.

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
Traffic Path", and the output-fabric figure `assets/smc-output-fabric.svg`)
has the M-mode output remap set the AxUSER source ID to `MMODE_ID` (0xC) and
the Xvisor remap set it to `OTHER_ID` (0); the leaf carries both as its own
constants. `filter_ctrl.rdl` makes a `src_id` of 0 the wildcard, so only
`MMODE_ID` can be matched.

While the words go out, outbound filter entry 0 allows reads and writes to the
M-mode targets for source `MMODE_ID`. Entry 1 matches the hypervisor target for
the same source and allows nothing. The hypervisor words carry `OTHER_ID`, so
entry 1 must not match them: if source-ID matching were ignored, entry 1 would
deny them and those legs would fail. Entry 0 is then re-armed to deny the
M-mode targets for `MMODE_ID`, and a further M-mode word must be refused with
DECERR (`fabric.adoc`: a matching deny entry routes the transaction to an error
slave that returns a decode error) and leave its target untouched, which only
a path carrying exactly `MMODE_ID` does. Both entries are restored to their RDL
reset.

The remap entries are restored to their reset afterwards.

**Every region's valid bit.** Each of the eight M-mode and eight Xvisor
`region_attrs` registers is read at its reset (`valid` 0), written with `valid`
set and a distinct 1 MB-aligned offset, and read back. With the region valid, a
word through slot r of the window's local copy must land at the offset's bits
[55:20] (`output_remap.adoc`: 36 MSBs for 8 x 1 MB regions) with the request's
low 20 bits, and leave the request address alone. The region is then rewritten
with the same offset and `valid` clear, read back, and a second word at the
same window address must land at the request address and leave the first word
at the remapped address. Every word reads back through the window.

**Partial-lane writes.** Each region is then written with WSTRB=0x0F (offset
[31:0] on the enabled lanes, `valid` set on the disabled top lane) and with
WSTRB=0x80 (`valid` set on the top lane, another offset on the disabled lanes),
and read back after each write. Whether a write honours its strobes is not
stated (SF-027), so the two readbacks are logged, not compared. One word through
slot r must then land where the second readback's `valid` and offset put it.

**Alias cacheable field.** Each alias remap region (`alias_remap.adoc`:
`cacheable` 59:56, `offset` 55:12, `valid` 63) is written with `cacheable` all
ones and a distinct offset, then with `cacheable` zero and the same offset,
`valid` clear, and read back exactly after each write.

Every region and both filter entries end at their reset.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time
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

import smc_reg as _regs  # noqa: E402
from smc_reg import (  # noqa: E402
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
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
AXI_RESP_DECERR = 3

# fabric.adoc, "SMC Source ID by Traffic Path" and the output-fabric figure
# (assets/smc-output-fabric.svg): the M-mode output remap sets the AxUSER
# source ID to MMODE (0xC), the Xvisor remap to OTHERS (0) and the direct path
# to SMC (3). filter_ctrl.rdl makes src_id 0 the wildcard.
MMODE_ID = 0xC
OTHER_ID = 0x0
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


_REGIONS = range(8)
_OFFSET = _field_mask(_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__OFFSET_bm")
_ALIAS_H = _REPO / "hw" / "ip" / "axi_alias_remap" / "regs" / "gen" / "c" / "alias_remap.h"
_ALIAS_OFFSET = _field_mask(_ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bm")
_ALIAS_CACHEABLE = _field_mask(_ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__CACHEABLE_bm")
_LOW_LANES = 0x0F
_TOP_LANE = 0x80


def _attrs(window: str, region: int) -> int:
    return getattr(_regs, f"SMC_{window}_REMAP_{region}__REGION_REGION_ATTRS_REG_ADDR")


# (label, register prefix, window base, set offset, WSTRB=0x0F offset, WSTRB=0x80 offset)
_WINDOWS = (
    ("mmode", "MMODE", _MMODE_BASE, 0x0300_0000, 0x0400_0000, 0x0500_0000),
    ("xvisor", "XVISOR", _XVISOR_BASE, 0x0380_0000, 0x0480_0000, 0x0580_0000),
)
_ALIAS_OFFSETS = tuple(0x0012_3400_0000 + (a << 24) + ((a + 1) << 12) for a in _REGIONS)
assert all(off & ~_ALIAS_OFFSET == 0 for off in _ALIAS_OFFSETS)

_STEPS = (
    "SETUP",
    "EXISTING",
    "MMODE_VALID",
    "XVISOR_VALID",
    "ROUTE",
    "MMODE_WSTRB",
    "XVISOR_WSTRB",
    "ALIAS_CACHEABLE",
    "RESTORE",
)

_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_DENIED_WORD = 0xDE1E_D000_0000_0000


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
        self.mmode_denied = 0
        self.jtag_accesses = 0
        self.chk_seen: list[str] = []
        self._stamps: list[tuple[str, int, int]] = []
        self._wstrb_rows: list[str] = []

    def _mark(self, step: str, count: int) -> None:
        assert count > 0, f"fence term {step} did nothing"
        self._stamps.append((step, count, int(get_sim_time("ns"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    async def _jtag(
        self, op: SmcSysAxiOp, addr: int, data: int | None = None, *, denied: bool = False
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"remap_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = _WORD
        if data is not None:
            item.wdata = data
        if denied:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        if denied:
            assert item.resp_code == AXI_RESP_DECERR, (
                f"JTAG {op.value} at 0x{addr:x} completed with resp {item.resp_code}; the "
                f"outbound filter entry denying source 0x{MMODE_ID:x} routes it to the error "
                f"slave, which answers DECERR"
            )
        else:
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
        self._mark("SETUP", len(_ENTRIES) + len(_FILTER_ENTRIES))

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

        # Entry 0 re-armed to deny the M-mode targets for the same source. Only
        # a word carrying exactly MMODE_ID is caught, so the refusal and the
        # untouched target tie the M-mode remap path to that source ID.
        deny_label, deny_addr, deny_target = _LEGS[0]
        await self.csr_write(
            "OB0_CONFIG_DENY", _outbound("FILTER_CONFIG", 0), _FILTER_BASE, length=_WORD
        )
        await self.csr_read(
            "OB0_CONFIG_DENY_RB", _outbound("FILTER_CONFIG", 0), expected=_FILTER_BASE, length=_WORD
        )
        responder.write_int(deny_target, _SENTINEL, _WORD)
        await self._jtag(SmcSysAxiOp.WRITE, deny_addr, _DENIED_WORD, denied=True)
        kept = responder.read_int(deny_target, _WORD)
        assert kept == _SENTINEL, (
            f"[{deny_label}_DENIED] SYS_OUT 0x{deny_target:x} holds 0x{kept:016x} after a write "
            f"the outbound filter denies for source 0x{MMODE_ID:x}; the M-mode word reached its "
            f"target, so the M-mode remap path does not carry source 0x{MMODE_ID:x}"
        )
        self.mmode_denied += 1
        cocotb.log.info(
            "[%s_DENIED] 0x%x: refused with DECERR by entry 0 denying source 0x%x; SYS_OUT 0x%x "
            "kept its sentinel",
            deny_label,
            deny_addr,
            MMODE_ID,
            deny_target,
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
            "clear passed through and left that entry's offset target alone; outbound filter "
            "entries matching source 0x%x (M-mode) allowed the M-mode words and did not catch "
            "the hypervisor words, which carry source 0x%x, and %d M-mode word was refused with "
            "DECERR once entry 0 denied that source",
            self.legs_checked,
            ", ".join(f"0x{a:x}->0x{t:x}" for _l, a, t in _LEGS),
            MMODE_ID,
            OTHER_ID,
            self.mmode_denied,
        )
        self.chk_seen.append("CHK-OUTPUT-REMAP-WINDOWS")
        self._mark("EXISTING", self.legs_checked + self.mmode_denied)

        await self._valid_sets()
        await self._route()
        for window in _WINDOWS:
            await self._wstrb(window)
        await self._alias_cacheable()
        await self._restore(resets)

    async def _send(self, label: str, addr: int, landing: int, word: int, keep: dict) -> None:
        """Write ``word`` at ``addr`` over JTAG; it must land at ``landing`` and nowhere in ``keep``."""
        responder = self.cfg.sys_out_mem
        await self._jtag(SmcSysAxiOp.WRITE, addr, word)
        landed = responder.read_int(landing, _WORD)
        assert landed == word, (
            f"[{label}] a write at 0x{addr:x} left SYS_OUT 0x{landing:x} holding "
            f"0x{landed:016x}, expected 0x{word:016x}"
        )
        for at, value in keep.items():
            held = responder.read_int(at, _WORD)
            assert held == value, (
                f"[{label}] SYS_OUT 0x{at:x} holds 0x{held:016x} after the write at 0x{addr:x}; "
                f"it should still hold 0x{value:016x}, the word belongs only at 0x{landing:x}"
            )
        got = await self._jtag(SmcSysAxiOp.READ, addr)
        assert got.rdata == word, (
            f"[{label}] a read at 0x{addr:x} returned 0x{got.rdata:016x}; the write through "
            f"the same window put 0x{word:016x} at 0x{landing:x}"
        )

    async def _valid_sets(self) -> None:
        for (label, prefix, _base, set_base, _lo, _hi), step in zip(
            _WINDOWS, ("MMODE_VALID", "XVISOR_VALID")
        ):
            for r in _REGIONS:
                addr = _attrs(prefix, r)
                await self.csr_read(
                    f"{prefix}{r}_VALID_RESET",
                    addr,
                    expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                    length=_WORD,
                )
                value = _VALID | (set_base + r * _SLOT)
                await self.csr_write(f"{prefix}{r}_VALID_SET", addr, value, length=_WORD)
                await self.csr_read(f"{prefix}{r}_VALID_SET_RB", addr, expected=value, length=_WORD)
            self._mark(step, len(_REGIONS))

    async def _route(self) -> None:
        responder = self.cfg.sys_out_mem
        landings = []
        for label, prefix, base, set_base, _lo, _hi in _WINDOWS:
            for r in _REGIONS:
                offset = set_base + r * _SLOT
                addr = base + r * _SLOT + 0x200 + _WORD * r
                remapped = _remapped(addr, base, {r: offset})
                assert remapped != addr
                first = 0xF1A5_0000_0000_0000 | (int(prefix == "XVISOR") << 44) | (r << 40) | addr
                second = first ^ 0x0F0F_0000_0000_0000
                responder.write_int(addr, _SENTINEL, _WORD)
                responder.write_int(remapped, _SENTINEL, _WORD)
                await self._send(f"{prefix}{r}_VALID", addr, remapped, first, {addr: _SENTINEL})
                attrs = _attrs(prefix, r)
                await self.csr_write(f"{prefix}{r}_VALID_CLEAR", attrs, offset, length=_WORD)
                await self.csr_read(
                    f"{prefix}{r}_VALID_CLEAR_RB", attrs, expected=offset, length=_WORD
                )
                await self._send(f"{prefix}{r}_CLEARED", addr, addr, second, {remapped: first})
                landings.append(f"{label}{r}:0x{addr:x}->0x{remapped:x}|0x{addr:x}")
                cocotb.log.info(
                    "[%s%d] valid: 0x%x -> SYS_OUT 0x%x; cleared: 0x%x -> SYS_OUT 0x%x, "
                    "readbacks ok",
                    prefix,
                    r,
                    addr,
                    remapped,
                    addr,
                    addr,
                )
        self._mark("ROUTE", len(landings))
        for label, _prefix, _base, set_base, _lo, _hi in _WINDOWS:
            name = "O_r" if label == "mmode" else "X_r"
            self._chk(
                f"CHK-ORMP-VALID-{label.upper()}",
                f"r0..7 reset valid=0, set valid=1 off={name}, clear valid=0 off={name} "
                f"({name}=0x{set_base:x}+r*0x{_SLOT:x}, every readback exact)",
            )
        self._chk(
            "CHK-ORMP-VALID-ROUTE",
            "mmode r0..7 xvisor r0..7 valid->remapped, cleared->passthrough, readbacks ok, "
            "request address sentinel kept while valid, first word kept at the remapped address "
            "once cleared: " + " ".join(landings),
        )

    async def _wstrb(self, window: tuple) -> None:
        label, prefix, base, _set, lo_base, hi_base = window
        responder = self.cfg.sys_out_mem
        rows = []
        for r in _REGIONS:
            attrs = _attrs(prefix, r)
            addr = base + r * _SLOT + 0x400 + _WORD * r
            await self.csr_write_strobed(
                f"{prefix}{r}_WSTRB_0F", attrs, _VALID | (lo_base + r * _SLOT), _LOW_LANES, _WORD
            )
            rb_lo = await self.csr_read(f"{prefix}{r}_WSTRB_0F_RB", attrs, length=_WORD)
            await self.csr_write_strobed(
                f"{prefix}{r}_WSTRB_80", attrs, _VALID | (hi_base + r * _SLOT), _TOP_LANE, _WORD
            )
            rb_hi = await self.csr_read(f"{prefix}{r}_WSTRB_80_RB", attrs, length=_WORD)
            remapped = (rb_hi & _OFFSET & ~(_SLOT - 1)) | ((addr - base) & (_SLOT - 1))
            valid = bool(rb_hi & _VALID)
            landing = remapped if valid else addr
            other = addr if valid else remapped
            responder.write_int(addr, _SENTINEL, _WORD)
            responder.write_int(remapped, _SENTINEL, _WORD)
            keep = {} if other == landing else {other: _SENTINEL}
            word = 0x5B5B_0000_0000_0000 | (int(prefix == "XVISOR") << 44) | (r << 40) | addr
            await self._send(f"{prefix}{r}_WSTRB", addr, landing, word, keep)
            route = "remapped" if valid else "passthrough"
            rows.append(
                f"{label}{r} rb_after_0x0F=0x{rb_lo:016x} rb_after_0x80=0x{rb_hi:016x} "
                f"route={route}@0x{landing:x}"
            )
        self._mark(f"{prefix}_WSTRB", len(rows))
        if prefix == "XVISOR":
            self._chk(
                "CHK-ORMP-WSTRB",
                "mmode/xvisor r0..7 partial-lane readbacks measured (LINKED-ISSUE SF-027), "
                "each landing consistent with the read-back valid and offset: "
                + "; ".join(self._wstrb_rows + rows),
            )
        else:
            self._wstrb_rows = rows

    async def _alias_cacheable(self) -> None:
        for a, offset in zip(_REGIONS, _ALIAS_OFFSETS):
            addr = getattr(_regs, f"SMC_ALIAS_REMAP_{a}__REGION_REGION_ATTRS_REG_ADDR")
            await self.csr_read(
                f"ALIAS{a}_ATTRS_RESET",
                addr,
                expected=REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=_WORD,
            )
            ones = _ALIAS_CACHEABLE | offset
            await self.csr_write(f"ALIAS{a}_CACHEABLE_F", addr, ones, length=_WORD)
            await self.csr_read(f"ALIAS{a}_CACHEABLE_F_RB", addr, expected=ones, length=_WORD)
            await self.csr_write(f"ALIAS{a}_CACHEABLE_0", addr, offset, length=_WORD)
            await self.csr_read(f"ALIAS{a}_CACHEABLE_0_RB", addr, expected=offset, length=_WORD)
        self._mark("ALIAS_CACHEABLE", len(_ALIAS_OFFSETS))
        self._chk(
            "CHK-ALIAS-CACHEABLE",
            "a0..7 cacheable 0xF -> 0x0, offset and valid unchanged (valid=0, offsets "
            + ",".join(f"0x{o:x}" for o in _ALIAS_OFFSETS)
            + ")",
        )

    async def _restore(self, resets: dict[str, int]) -> None:
        count = 0
        for _label, prefix, *_rest in _WINDOWS:
            for r in _REGIONS:
                addr = _attrs(prefix, r)
                await self.csr_write(
                    f"{prefix}{r}_RESTORE",
                    addr,
                    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                    length=_WORD,
                )
                await self.csr_read(
                    f"{prefix}{r}_RESTORE_RB",
                    addr,
                    expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                    length=_WORD,
                )
                count += 1
        for a in _REGIONS:
            addr = getattr(_regs, f"SMC_ALIAS_REMAP_{a}__REGION_REGION_ATTRS_REG_ADDR")
            await self.csr_write(
                f"ALIAS{a}_RESTORE", addr, REMAP_REGION_REGION_ATTRS_REG_DEFAULT, length=_WORD
            )
            await self.csr_read(
                f"ALIAS{a}_RESTORE_RB",
                addr,
                expected=REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                length=_WORD,
            )
            count += 1
        for entry, _start, _end, _config in _FILTER_ENTRIES:
            for reg, value in resets.items():
                await self.csr_read(
                    f"OB{entry}_{reg}_FINAL", _outbound(reg, entry), expected=value, length=_WORD
                )
            count += 1
        self._mark("RESTORE", count)

        assert tuple(s for s, _c, _t in self._stamps) == _STEPS, f"fence {self._stamps}"
        times = [t for _s, _c, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        self._chk(
            "CHK-NONVAC",
            "ordered fence "
            + "<".join(_STEPS)
            + "; terms "
            + ", ".join(f"{s}(n={c})@{t}ns" for s, c, t in self._stamps)
            + f"; checker lines {','.join(self.chk_seen)}; SEP_IN accesses {self.accesses}, "
            f"JTAG accesses {self.jtag_accesses}",
        )

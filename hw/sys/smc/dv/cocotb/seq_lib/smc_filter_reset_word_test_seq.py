# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter, alias remap and output remap reset words; a cold reset clears `locked`.

Contract SMC_FILTER_12, anchor smc_filter_reset_word_test.
Allocated scenarios: FILTER-RESET-WORD.S1-S5, FILTER-LOCK.S7.
Spec sources: filter_ctrl.rdl, alias_remap.rdl, output_remap.rdl, axi_filter doc (Locking).

Every access is a SEP_IN 8-byte access. The alias and output remap reset words are 0x0, so
they are graded as the post-reset readback of a previously programmed non-zero value; the
filter entry 7 legs and the entry 12 `locked` leg rest on a non-zero prior value too. The
reset-word reads of S2 and the post-reset 0x0 compares of an untouched register cannot
discriminate X/Z in this two-state model. SF-010 leaves open which reset clears filter
entries; the leaf applies the cold reset and grades only what the contract states.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

FUSE_SENSE_BOUND = 200_000
AXI_TIMEOUT_NS = 50_000
ACCESS_FLOOR = 82
ENTRIES = (0, 7, 15)
LOCK_ENTRY = 12
RESET_CFG, RESET_START, RESET_END = 0x3000, 0x0, 0x7
E7_START, E7_END, E7_CFG, E7_CFG_RB = 0x0200_1000, 0x0200_1FFF, 0x0105_0013, 0x0105_3013
LOCKED_CFG = 0x8000_0000_0000_3000
SRC3_WRITE, SRC3_READ = 0x3_0000, 0x3_3000
ALIAS_START, ALIAS_END, ALIAS_ATTRS = 0x0200_2000, 0x0200_3000, 0x8F00_0000_0000_1000
MMODE_ATTRS = {0: 0x8000_0000_0240_0000, 7: 0x8000_0000_0250_0000}
XVISOR_ATTRS = dict(MMODE_ATTRS)
REGIONS = (0, 7)

_P = "SMC_TOP_SMC_"
_BANKS = ("INBOUND", "OUTBOUND")
FENCE_ORDER = (
    "RESET_STATE_READS",
    "PROGRAMMED_READBACKS",
    "COLD_RESET_ASSERT",
    "COLD_RESET_RELEASE",
    "POST_RESET_READS",
    "LOCKED_ENTRY_WRITE",
)
CHK_ORDER = (
    ("CHK-RESET-WORD-INBOUND", "RESET_STATE_READS"),
    ("CHK-RESET-WORD-OUTBOUND", "RESET_STATE_READS"),
    ("CHK-RESET-ALIAS-REMAP", "POST_RESET_READS"),
    ("CHK-RESET-OUTPUT-REMAP", "POST_RESET_READS"),
    ("CHK-RESET-FILTER-PROGRAMMED", "POST_RESET_READS"),
    ("CHK-RESET-CLEARS-LOCK", "POST_RESET_READS"),
    ("CHK-LOCK-WRITABLE-AFTER-RESET", "LOCKED_ENTRY_WRITE"),
)


def _filt(bank: str, reg: str, idx: int) -> int:
    return smc_indexed_addr(f"{_P}{bank}_FILTER_CTRL_{reg}_BASE_ADDR", idx)


def _alias(reg: str, idx: int) -> int:
    return smc_indexed_addr(f"{_P}ALIAS_REMAP_REGION_REGION_{reg}_BASE_ADDR", idx)


def _remap(unit: str, idx: int) -> int:
    return smc_indexed_addr(f"{_P}{unit}_REMAP_REGION_REGION_ATTRS_BASE_ADDR", idx)


class smc_filter_reset_word_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Program non-reset values over SEP_IN, cold reset, read the reset words back."""

    def __init__(self, name: str = "smc_filter_reset_word_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.fence: list[tuple[str, int]] = []
        self.chk_order: list[tuple[str, int]] = []
        self.last_access = "none"

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    def _stamp(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_order.append((chk_id, len(self.fence)))

    async def _access(self, name: str, addr: int, op: SmcSysAxiOp, data: int | None) -> int:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op, item.addr, item.length = op, addr, 8
        if data is not None:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.last_access = f"{name}@0x{addr:08x} resp={item.resp_code}"
        assert item.resp_code == 0, f"{self.last_access}: not OKAY"
        return int(item.rdata) if op == SmcSysAxiOp.READ else 0

    async def _rd(self, name: str, addr: int, want: int) -> int:
        got = await self._access(name, addr, SmcSysAxiOp.READ, None)
        assert got == want, f"{name}@0x{addr:08x}: read 0x{got:x}, want 0x{want:x}"
        return got

    async def _wr(self, name: str, addr: int, data: int) -> None:
        await self._access(name, addr, SmcSysAxiOp.WRITE, data)

    async def _fuse_sense(self, label: str) -> None:
        await wait_fuse_sense_done(FUSE_SENSE_BOUND)
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            self._timeout_paths.append(f"{label}.{sub}: bound={FUSE_SENSE_BOUND}smc_cycles last=1")

    async def _reset_words(self) -> None:
        lines = {}
        for bank in _BANKS:
            parts = lines[bank] = []
            for idx in ENTRIES:
                for reg, want in (
                    ("FILTER_CONFIG", RESET_CFG),
                    ("START_ADDR", RESET_START),
                    ("END_ADDR", RESET_END),
                ):
                    got = await self._rd(f"{bank}_{reg}_{idx}", _filt(bank, reg, idx), want)
                    parts.append(f"e{idx}.{reg}=0x{got:x}")
        self._stamp("RESET_STATE_READS")
        for bank in _BANKS:
            self._chk(f"CHK-RESET-WORD-{bank}", f"entries 0,7,15 {' '.join(lines[bank])}, all OKAY")

    async def _program(self) -> list[str]:
        for bank in _BANKS:
            await self._wr(f"{bank}_E7_START", _filt(bank, "START_ADDR", 7), E7_START)
            await self._wr(f"{bank}_E7_END", _filt(bank, "END_ADDR", 7), E7_END)
            await self._wr(f"{bank}_E7_CFG", _filt(bank, "FILTER_CONFIG", 7), E7_CFG)
            await self._wr(f"{bank}_E12_LOCK", _filt(bank, "FILTER_CONFIG", LOCK_ENTRY), LOCKED_CFG)
        for r in REGIONS:
            await self._wr(f"ALIAS{r}_START", _alias("START", r), ALIAS_START)
            await self._wr(f"ALIAS{r}_END", _alias("END", r), ALIAS_END)
            await self._wr(f"ALIAS{r}_ATTRS", _alias("ATTRS", r), ALIAS_ATTRS)
            await self._wr(f"MMODE{r}_ATTRS", _remap("MMODE", r), MMODE_ATTRS[r])
            await self._wr(f"XVISOR{r}_ATTRS", _remap("XVISOR", r), XVISOR_ATTRS[r])
        pre = []
        for bank in _BANKS:
            for reg, want in (
                ("START_ADDR", E7_START),
                ("END_ADDR", E7_END),
                ("FILTER_CONFIG", E7_CFG_RB),
            ):
                await self._rd(f"{bank}_E7_{reg}_PRE", _filt(bank, reg, 7), want)
            got = await self._rd(
                f"{bank}_E12_PRE", _filt(bank, "FILTER_CONFIG", LOCK_ENTRY), LOCKED_CFG
            )
            pre.append(f"{bank}.e12=0x{got:x}")
        for r in REGIONS:
            await self._rd(f"ALIAS{r}_START_PRE", _alias("START", r), ALIAS_START)
            await self._rd(f"ALIAS{r}_END_PRE", _alias("END", r), ALIAS_END)
            await self._rd(f"ALIAS{r}_ATTRS_PRE", _alias("ATTRS", r), ALIAS_ATTRS)
            await self._rd(f"MMODE{r}_PRE", _remap("MMODE", r), MMODE_ATTRS[r])
            await self._rd(f"XVISOR{r}_PRE", _remap("XVISOR", r), XVISOR_ATTRS[r])
        self._stamp("PROGRAMMED_READBACKS")
        return pre

    async def _cold_reset(self) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "cold_assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._hold_raw(
            "cold_hold",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._stamp("COLD_RESET_ASSERT")
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("cold_release")
        await self._fuse_sense("post_reset")
        self._stamp("COLD_RESET_RELEASE")

    async def _post_reset(self, pre: list[str]) -> None:
        parts = {"filter": [], "alias": [], "remap": [], "lock": []}
        for bank in _BANKS:
            for reg, want in (
                ("FILTER_CONFIG", RESET_CFG),
                ("START_ADDR", RESET_START),
                ("END_ADDR", RESET_END),
            ):
                got = await self._rd(f"{bank}_E7_{reg}_POST", _filt(bank, reg, 7), want)
                parts["filter"].append(f"{bank}.e7.{reg}=0x{got:x}")
        for bank in _BANKS:
            got = await self._rd(
                f"{bank}_E12_POST", _filt(bank, "FILTER_CONFIG", LOCK_ENTRY), RESET_CFG
            )
            assert not got >> 63, f"{bank} entry 12 still locked: 0x{got:x}"
            parts["lock"].append(f"{bank}.e12=0x{got:x}")
        for r in REGIONS:
            for reg in ("START", "END", "ATTRS"):
                got = await self._rd(f"ALIAS{r}_{reg}_POST", _alias(reg, r), 0)
                parts["alias"].append(f"r{r}.{reg}=0x{got:x}")
            for unit in ("MMODE", "XVISOR"):
                got = await self._rd(f"{unit}{r}_POST", _remap(unit, r), 0)
                parts["remap"].append(f"{unit.lower()}{r}=0x{got:x}")
        self._stamp("POST_RESET_READS")
        prior = "each rests on a non-zero prior value programmed before the cold reset"
        self._chk(
            "CHK-RESET-ALIAS-REMAP",
            f"pre-reset START 0x{ALIAS_START:x} END 0x{ALIAS_END:x} ATTRS 0x{ALIAS_ATTRS:x} read "
            f"back; post-reset {' '.join(parts['alias'])}; {prior}",
        )
        self._chk(
            "CHK-RESET-OUTPUT-REMAP",
            f"pre-reset ATTRS read back 0x{MMODE_ATTRS[0]:x}/0x{MMODE_ATTRS[7]:x}; post-reset "
            f"{' '.join(parts['remap'])}; {prior}",
        )
        self._chk(
            "CHK-RESET-FILTER-PROGRAMMED",
            f"pre-reset entry 7 FILTER_CONFIG 0x{E7_CFG_RB:x} START 0x{E7_START:x} END "
            f"0x{E7_END:x} read back in both banks; post-reset {' '.join(parts['filter'])}; "
            f"{prior}",
        )
        for leg, text in (
            ("set", "write of 0x%x to entry 12 of both banks answered OKAY" % LOCKED_CFG),
            ("observed", f"pre-reset reads {' '.join(pre)}"),
            ("cleared", "cold reset applied through COLD_RST_LO and COLD_RST_HI"),
            ("checked_cleared", f"post-reset reads {' '.join(parts['lock'])}, bit 63 clear"),
        ):
            cocotb.log.info("LIFECYCLE CHK-RESET-CLEARS-LOCK %s: %s", leg, text)
        self._chk(
            "CHK-RESET-CLEARS-LOCK",
            f"entry 12 read {' '.join(pre)} after the locking write and "
            f"{' '.join(parts['lock'])} after the cold reset; rests on a non-zero prior value",
        )

    async def _lock_writable(self) -> None:
        parts = []
        for bank in _BANKS:
            addr = _filt(bank, "FILTER_CONFIG", LOCK_ENTRY)
            await self._wr(f"{bank}_E12_SRC3", addr, SRC3_WRITE)
            got = await self._rd(f"{bank}_E12_SRC3_RB", addr, SRC3_READ)
            await self._wr(f"{bank}_E12_RESTORE", addr, 0)
            await self._rd(f"{bank}_E12_RESTORE_RB", addr, RESET_CFG)
            parts.append(f"{bank}.e12 write 0x{SRC3_WRITE:x} OKAY read 0x{got:x}")
        self._stamp("LOCKED_ENTRY_WRITE")
        self._chk(
            "CHK-LOCK-WRITABLE-AFTER-RESET",
            f"{' '.join(parts)}; restored to 0x{RESET_CFG:x}; no DECERR",
        )

    async def body(self) -> None:
        await self._fuse_sense("bringup")
        await self._reset_words()
        pre = await self._program()
        await self._cold_reset()
        await self._post_reset(pre)
        await self._lock_writable()
        for bank in _BANKS:
            addr = _filt(bank, "FILTER_CONFIG", LOCK_ENTRY)
            await self._rd(f"{bank}_E12_CLEANUP", addr, RESET_CFG)
        assert self.accesses >= ACCESS_FLOOR, f"{self.accesses} accesses, floor {ACCESS_FLOOR}"
        self._timeout_paths.append(
            f"sep_in_axi_access: bound={AXI_TIMEOUT_NS}ns, {self.accesses} accesses "
            f"last={self.last_access}"
        )
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._timeout_paths)} bounded waits: {'; '.join(self._timeout_paths)}; "
            "expiry raises AssertionError",
        )
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        order = [s for s, _ in self.fence]
        assert order == list(FENCE_ORDER), f"fence order {order}"
        stamps = [t for _, t in self.fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        seen = [c for c, _ in self.chk_order if c != "CHK-TIMEOUT-PATHS"]
        assert seen == [c for c, _ in CHK_ORDER], f"checker lines out of order {seen}"
        pos = {s: i + 1 for i, s in enumerate(FENCE_ORDER)}
        printed = dict(self.chk_order)
        for chk_id, step in CHK_ORDER:
            assert printed[chk_id] >= pos[step], f"{chk_id} printed before step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; accesses %d (floor %d); checker lines %s; stamps %s",
            " < ".join(order),
            self.accesses,
            ACCESS_FLOOR,
            ",".join(c for c, _ in self.chk_order),
            ",".join(str(t) for t in stamps),
        )

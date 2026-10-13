# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scope of a filter lock: refused writes, queued writes, reads and frozen decisions.

Contract SMC_FILTER_13, anchor smc_filter_lock_scope_test.
Allocated scenarios: FILTER-LOCK.S1, S3, S4, S6, S8.
Spec sources: axi_filter index.adoc Locking a Filter Entry and Match Then Permit, filter_ctrl.rdl.

`FILTER_CONFIG.locked` is write-once. The sequence locks inbound 14 and 13, outbound 14, 13, 5, 3
and 12; entry 0 of either bank is never locked and no locked entry is used again.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, reg_reset_word, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    BLOCKED_WRITE_HOLD_CYCLES,
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    hold_output_responder_writes,
    jtag_axi_read,
    jtag_axi_write,
    output_responder_counts,
)

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_LOCKED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__LOCKED_bm")
_ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_SRC_ID_BP = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp")
_RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
_RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
_RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")
_LOCKED_CFG = _RESET_CFG | _LOCKED

# Contract words: DENY_BOTH_B1 / PERMIT_B1 and their read-backs (data_bus_width 3).
_DENY_B1 = 0x0000_0000_0100_0010
_PERMIT_B1 = 0x0000_0000_0100_0013
_READBACK_BITS = 0x3000
_COMBINED = 0x8000_0000_0023_0003
_REFUSED_START = 0x0200_1000
_REFUSED_END = 0x0200_1FFF
_REFUSED_SRC_ID = 5
_R1 = (0x0200_8000, 0x0200_8FFF)
_R2 = (0x0200_9000, 0x0200_9FFF)
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_DECERR = 3
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_FLOOR = 79
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_TERMS = "ENTRIES_QUIET<LOCK_BANKS<QUEUED_GROUPS<FROZEN_DECISIONS<LOCK_WITH_FIELDS"
_CHECKERS = (
    ("CHK-LOCK-WRITES-REFUSED", "S2"),
    ("CHK-LOCK-READS-OKAY", "S2"),
    ("CHK-LOCK-QUEUED-WRITES", "S3"),
    ("CHK-LOCK-FROZEN-PERMIT", "S4"),
    ("CHK-LOCK-FROZEN-DENY", "S4"),
    ("CHK-LOCK-WITH-FIELDS-OBSERVE", "S5"),
)


def _reg(bank: str, reg: str, entry: int) -> int:
    sym = f"SMC_TOP_SMC_{bank.upper()}_FILTER_CTRL_{reg}_BASE_ADDR"
    return smc_indexed_addr(sym, entry)


def _write(tag: str, addr: int, data: int, refused: bool) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"wr_{tag}")
    item.op = SmcSysAxiOp.WRITE
    item.addr = addr
    item.length = 8
    item.wdata = data
    if refused:
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = _DECERR
    return item


class smc_filter_lock_scope_test_seq(SmcCsrSeq):
    """Lock filter entries and show what the lock refuses, keeps and freezes."""

    def __init__(self, name: str = "smc_filter_lock_scope_test_seq") -> None:
        super().__init__(name)
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _expect_decerr(self, *addrs: int) -> None:
        self.env.axi_monitor.expected_decerr_addrs.update(addrs)

    async def _refuse(self, tag: str, addr: int, data: int) -> int:
        self._expect_decerr(addr)
        resp = await self.csr_write_expect_error(tag, addr, data, length=8, resp=_DECERR)
        return resp

    async def _read_locked(self, bank: str, entry: int, tag: str) -> tuple[int, int, int]:
        got = []
        for reg, want in (
            ("FILTER_CONFIG", _LOCKED_CFG),
            ("START_ADDR", _RESET_START),
            ("END_ADDR", _RESET_END),
        ):
            word = await self.csr_read(
                f"{bank}{entry}_{reg}_{tag}", _reg(bank, reg, entry), expected=want, length=8
            )
            assert word == want, f"{bank} {entry} {reg} read 0x{word:x}, want 0x{want:x}"
            got.append(word)
        return got[0], got[1], got[2]

    async def _lock_and_refuse(self, bank: str, entry: int) -> str:
        cfg = _reg(bank, "FILTER_CONFIG", entry)
        await self.csr_write(f"{bank}{entry}_LOCK", cfg, _LOCKED_CFG, length=8)
        resp = [
            await self._refuse(
                f"{bank}{entry}_CFG", cfg, _RESET_CFG | (_REFUSED_SRC_ID << _SRC_ID_BP)
            ),
            await self._refuse(
                f"{bank}{entry}_START", _reg(bank, "START_ADDR", entry), _REFUSED_START
            ),
            await self._refuse(f"{bank}{entry}_END", _reg(bank, "END_ADDR", entry), _REFUSED_END),
        ]
        return f"{bank} {entry} BRESP {resp}"

    async def _queued_group(self, bank: str, entry: int) -> str:
        addrs = [_reg(bank, r, entry) for r in ("FILTER_CONFIG", "START_ADDR", "END_ADDR")]
        data = (_RESET_CFG | (_REFUSED_SRC_ID << _SRC_ID_BP), _REFUSED_START, _REFUSED_END)
        lock = _write(f"{bank}{entry}_QLOCK", addrs[0], _LOCKED_CFG, refused=False)
        behind = [
            _write(f"{bank}{entry}_Q{n}", a, d, refused=True)
            for n, (a, d) in enumerate(zip(addrs, data))
        ]
        self._expect_decerr(*addrs)
        group = SmcSysAxiGroupItem(f"{bank}{entry}_queued", [lock, *behind])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += 4
        assert lock.resp_code == 0, f"{bank} {entry} lock write BRESP {lock.resp_code}"
        refused = [item.resp_code for item in behind]
        assert refused == [_DECERR] * 3, f"{bank} {entry} queued writes answered {refused}"
        await self._read_locked(bank, entry, "Q")
        return f"{bank} {entry} lock {lock.resp_code} queued {refused}"

    async def _program(self, entry: int, bank: str, rng: tuple[int, int], word: int) -> None:
        await self.csr_write(f"OB{entry}_START", _reg(bank, "START_ADDR", entry), rng[0], length=8)
        await self.csr_write(f"OB{entry}_END", _reg(bank, "END_ADDR", entry), rng[1], length=8)
        await self.csr_write(f"OB{entry}_CFG", _reg(bank, "FILTER_CONFIG", entry), word, length=8)
        await self.csr_read(
            f"OB{entry}_CFG_RB",
            _reg(bank, "FILTER_CONFIG", entry),
            expected=word | _READBACK_BITS,
            length=8,
        )

    async def _lock_with_disable(self, entry: int, word: int) -> int:
        cfg = _reg("outbound", "FILTER_CONFIG", entry)
        await self.csr_write(f"OB{entry}_LOCK", cfg, word | _READBACK_BITS | _LOCKED, length=8)
        resp = await self._refuse(f"OB{entry}_DISABLE", cfg, word & ~_ENTRY_ENABLED)
        await self.csr_read(
            f"OB{entry}_CFG_LOCKED",
            cfg,
            expected=word | _READBACK_BITS | _LOCKED,
            length=8,
        )
        return resp

    @staticmethod
    def _probe(sig) -> int:
        assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _idle_state(self) -> str:
        top = cocotb.top
        sigs = (top.tb_output_axi_awvalid, top.tb_output_axi_wvalid, top.tb_output_axi_arvalid)
        vals = [self._probe(s) for s in sigs]
        assert vals == [0, 0, 0], f"SYS_OUT awvalid/wvalid/arvalid {vals} after a refused write"
        return "aw/w/ar valid 0/0/0"

    async def _jtag_landing(self, addr: int, word: int, counts: list[int]) -> str:
        responder = self.cfg.sys_out_mem
        responder.write_int(addr, _SENTINEL, 8)
        item = await jtag_axi_write(self, addr, word)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"JTAG write 0x{addr:x} BRESP {item.resp_code}"
        await check_output_responder_delta(
            start_writes=counts[0],
            start_reads=counts[1],
            write_delta=1,
            read_delta=0,
            last_addr=addr,
            last_wdata=word,
        )
        counts[0] += 1
        landed = responder.read_int(addr, 8)
        assert landed == word, f"JTAG write 0x{addr:x} left 0x{landed:016x}, want 0x{word:x}"
        return f"0x{addr:x} BRESP 0 landed 0x{landed:x}"

    async def _jtag_readback(self, addr: int, word: int, counts: list[int]) -> None:
        item = await jtag_axi_read(self, addr, expected=word)
        self.jtag_accesses += 1
        assert item.resp_code == 0 and item.rdata == word, (
            f"JTAG read 0x{addr:x} resp {item.resp_code} data 0x{item.rdata:x}, want 0x{word:x}"
        )
        await check_output_responder_delta(
            start_writes=counts[0],
            start_reads=counts[1],
            write_delta=0,
            read_delta=1,
        )
        counts[1] += 1

    async def _jtag_blocked(self, addr: int, word: int, counts: list[int]) -> str:
        responder = self.cfg.sys_out_mem
        responder.write_int(addr, _SENTINEL, 8)
        item = await jtag_axi_write(self, addr, word, expect_error=True, expected_resp=_DECERR)
        self.jtag_accesses += 1
        assert item.resp_code == _DECERR, f"JTAG write 0x{addr:x} BRESP {item.resp_code}"
        await hold_output_responder_writes(expected_writes=counts[0], label=f"deny 0x{addr:x}")
        kept = responder.read_int(addr, 8)
        assert kept == _SENTINEL, f"blocked JTAG write changed 0x{addr:x} to 0x{kept:016x}"
        return f"0x{addr:x} BRESP {item.resp_code} kept 0x{kept:x} ({self._idle_state()})"

    async def _restore(self, entry: int) -> None:
        for reg, word in (
            ("FILTER_CONFIG", _RESET_CFG),
            ("START_ADDR", _RESET_START),
            ("END_ADDR", _RESET_END),
        ):
            await self.csr_restore(f"OB{entry}_{reg}", _reg("outbound", reg, entry), word)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        top = cocotb.top
        fuse = [
            self._probe(s)
            for s in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n)
        ]
        self._waits.append(
            f"tb_fuse_sense_done bound {_FUSE_BOUND} clk_smc_i last {fuse[0]}; tb_fuse_reset_n "
            f"bound {_FUSE_BOUND} last {fuse[1]}; tb_rst_warm_smc_clk_n bound {_FUSE_BOUND} "
            f"last {fuse[2]}"
        )

        # S1: every entry the run touches starts unlocked and disabled.
        s1 = [("inbound", 14), ("outbound", 14), ("inbound", 13), ("outbound", 13)]
        s1 += [("outbound", e) for e in (5, 6, 3, 4, 12)]
        for bank, entry in s1:
            word = await self.csr_read(
                f"{bank}{entry}_QUIET", _reg(bank, "FILTER_CONFIG", entry), length=8
            )
            assert not word & (_LOCKED | _ENTRY_ENABLED), f"{bank} {entry} not quiet: 0x{word:x}"
        self._mark_step("S1")

        # S2: writes to a locked entry are refused, reads are not.
        refused = []
        reads = []
        for bank in ("inbound", "outbound"):
            refused.append(await self._lock_and_refuse(bank, 14))
            reads.append(await self._read_locked(bank, 14, "S2"))
        self._mark_step("S2")
        self._log_chk(
            "CHK-LOCK-WRITES-REFUSED",
            f"lock write OKAY then FILTER_CONFIG/START_ADDR/END_ADDR writes DECERR ({_DECERR}) on "
            f"{'; '.join(refused)}; entries 14 locked here only, entry 0 untouched",
        )
        self._log_chk(
            "CHK-LOCK-READS-OKAY",
            "OKAY reads of FILTER_CONFIG/START_ADDR/END_ADDR on inbound 14 and outbound 14 "
            f"returned {[[hex(w) for w in r] for r in reads]}",
        )

        # S3: the three writes queued directly behind the lock write.
        queued = [await self._queued_group(bank, 13) for bank in ("inbound", "outbound")]
        self._mark_step("S3")
        self._log_chk(
            "CHK-LOCK-QUEUED-WRITES",
            f"{'; '.join(queued)}; entries read back 0x{_LOCKED_CFG:x}/0x{_RESET_START:x}/"
            f"0x{_RESET_END:x}; each group answered within {_AXI_BOUND_NS} ns; "
            "entries 13 locked here only",
        )

        # S4: locked permit and deny entries keep their decision against overlapping entries.
        await self._program(5, "outbound", _R1, _PERMIT_B1)
        await self._program(6, "outbound", _R1, _DENY_B1)
        await self._program(3, "outbound", _R2, _DENY_B1)
        await self._program(4, "outbound", _R2, _PERMIT_B1)
        counts = list(output_responder_counts())
        disable5 = await self._lock_with_disable(5, _PERMIT_B1)
        permit = [await self._jtag_landing(0x0200_8100, 0x1111_2222_3333_4444, counts)]
        disable3 = await self._lock_with_disable(3, _DENY_B1)
        permit.append(await self._jtag_landing(0x0200_8108, 0x5555_6666_7777_8888, counts))
        await self._jtag_readback(0x0200_8100, 0x1111_2222_3333_4444, counts)
        await self._jtag_readback(0x0200_8108, 0x5555_6666_7777_8888, counts)
        deny = [await self._jtag_blocked(0x0200_9100, 0x9999_AAAA_BBBB_CCCC, counts)]
        deny.append(await self._jtag_blocked(0x0200_9108, 0xDDDD_EEEE_FFFF_0001, counts))
        self._mark_step("S4")
        self._log_chk(
            "CHK-LOCK-FROZEN-PERMIT",
            f"locked permit entry 5 over R1 admits JTAG writes {permit}, disable write DECERR "
            f"{disable5}, unlocked deny entry 6 covers the same range; SYS_OUT write/read counts "
            f"{counts}; entry 5 locked here only",
        )
        self._log_chk(
            "CHK-LOCK-FROZEN-DENY",
            f"locked deny entry 3 over R2 blocks JTAG writes {deny}, disable write DECERR "
            f"{disable3}, unlocked permit entry 4 covers the same range; entry 3 locked here only",
        )

        # S5: observe-only, SF-016.
        cfg12 = _reg("outbound", "FILTER_CONFIG", 12)
        self._expect_decerr(cfg12)
        item = _write("OB12_COMBINED", cfg12, _COMBINED, refused=False)
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        reads = [await self.csr_read(f"OB12_COMBINED_RB{n}", cfg12, length=8) for n in (1, 2)]
        self._mark_step("S5")
        bit63 = reads[0] >> 63
        self._log_chk(
            "CHK-LOCK-WITH-FIELDS-OBSERVE",
            f"observe-only SF-016 combined write 0x{_COMBINED:x} BRESP {item.resp_code} "
            f"reads 0x{reads[0]:x} 0x{reads[1]:x} bit63 {bit63}; outbound 12 locked here only",
        )
        assert reads[0] == reads[1], f"reads differ: {[hex(r) for r in reads]}"
        assert bit63 == (item.resp_code == 0), f"bit63 {bit63} with BRESP {item.resp_code}"

        # S6: restore the unlocked entries.
        await self._restore(4)
        await self._restore(6)
        self._mark_step("S6")

        self._waits += [
            f"SEP_IN and JTAG AXI accesses bound {_AXI_BOUND_NS} ns, allow_timeout False, "
            f"{self.accesses} SEP_IN and {self.jtag_accesses} JTAG completed",
            f"check_output_responder_delta bound {RESPONDER_OBS_TIMEOUT_CYCLES} clk_smc_i, "
            f"last write/read counts {counts}",
            f"hold_output_responder_writes bound {BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i, "
            f"last write count {counts[0]}",
        ]
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in _CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        total = self.accesses + self.jtag_accesses
        assert total >= _FLOOR, f"{total} accesses, floor {_FLOOR}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d (%d SEP_IN + %d JTAG) "
            "vs floor %d; stamps %s",
            _TERMS,
            ",".join(c for c, _ in self._chk_marks),
            total,
            self.accesses,
            self.jtag_accesses,
            _FLOOR,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %s", " | ".join(self._waits))

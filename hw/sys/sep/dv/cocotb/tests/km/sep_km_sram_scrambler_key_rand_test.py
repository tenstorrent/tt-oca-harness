# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM SRAM scrambler: key and address dependence, the one-to-one row map, the lock, resets.

no_cpu / lsu_stub_all_live / +skip_fuse_sense / +km_rom_hex=km_rom_scr.param.parhex.
Seeded (``SepSeededRng`` in ``env/sep_km_img_param.py``): every draw is logged as
``DRAW``.

The KM CPU runs IMG-SCR (``tests/km_fw/km_rom_scr.S``). The prestage step stages a
copy of the committed image with the parameter block of the leaf seed at KM ROM
word 0xF00 (``HK-IMG-PARAM``), and the image load preloads it at t=0. The leaf
rebuilds the same staged text from the seed and requires the file to match, so
the golden and the image come from one function of the seed. The image reports
every value through the KM mailbox; the host reads each message through the SEP
side of the mailbox (``HOST-MBX``), and every golden is a plan value, a register
value of ``km_csr.adoc`` or an inequality of the scrambler description. There is
no cipher model.

Specification: ``hw/ip/scrambler/doc/architecture.adoc`` ("Data Scrambling
Algorithm", "Address Tweaking", "Address Scrambling", "Integration in the Key
Manager"); ``hw/ip/key_manager/doc/architecture.adoc`` ("Key Manager Control
and Status Registers (KMCSR)", "ROM Warm-Persistent SRAM Region", "Mailbox
Transport"); ``hw/ip/key_manager/doc/firmware.adoc`` ("Memory Scrambler
Provisioning": the SRAM scrambler key and enable/lock state survive warm reset);
``hw/ip/key_manager/regs/gen/adoc/km_csr.adoc`` ("SCRAMBLER_KEY",
"SCRAMBLER_CTRL").

Checks:
  CHK-SSCR-KEY      the kept write of P at a1 under kB carries other data than the
                    kept write of P at a1 under kA; the 8 words read under kA after
                    the key returns to kA equal the plaintexts
  CHK-SSCR-STORED   the two kept writes of P at a1 and a2 under kA carry different data
  CHK-SSCR-ALIAS    64 distinct words at 64 distinct addresses read back under kA
  CHK-SSCR-LOCK     after the lock with the enable at 1: SCRAMBLER_KEY reads 0, a key
                    write, an enable write and a write of 0 to the lock are ignored,
                    SCRAMBLER_CTRL reads 0x3 and the 16 reads equal the plaintexts
  CHK-SSCR-RST      a warm reset keeps 0x3 and the 8 words; a cold reset reads 0x0
                    and a kB write reads back
  CHK-SSCR-LOCK0    the lock written with the enable at 0 makes the next store a
                    scrambled write
  CHK-SSCR-ROWS     the 64 stores are 64 accepted SRAM writes that change at most
                    64 rows of the array

Anchors: the scrambled-write monitor at the SRAM macro port and the array word at
its kept rows (``KM-SRAM-MON``), the count of accepted SRAM writes
(``KM-COUNT``), the read-only array tap in stored form (``KM-SRAM``), and the
frames of the KM mailbox read through ``HOST-MBX`` with an OKAY response.

Controls (a missing one fails the leaf): the first kA reads, the array word at
each kept row, SCRAMBLER_KEY read before the lock, SCRAMBLER_CTRL 0x0 after the
enable is cleared before the lock, the kB write before the lock that changes the
stored word, the store before the lock that does not count, the tap word at the
kept rows, the empty mailbox before the warm reset.

Logged only: the 8 reads under kB (``OBS-SSCR-KB``), whether each kept data word
differs from its plaintext (``OBS-SSCR-STORED``), the number of changed rows
(``OBS-SSCR-ROWS``), the 8 reads with the enable clear (``OBS-SSCR-EN0``), and
SCRAMBLER_CTRL after a lock written with the enable at 0 (``ctrl_rd_logged``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from env import sep_km_img_param as ip
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import CHeaderRegBlock, ip_c_header
from seq_lib.sep_km_mailbox_seq import (
    KM_STATUS_INBOUND_EMPTY,
    KM_STATUS_OUTBOUND_DEPTH_LSB,
    KM_STATUS_OUTBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_EMPTY,
    KM_STATUS_OUTBOUND_SEPARATOR,
    RESP_OKAY,
    SepKmMailbox,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SW_RESET_N_RESET_DEFAULT, SepSwReset

TEST = ip.T_SCR
IMAGE = "km_rom_scr"
TEMPLATE = Path(__file__).resolve().parents[1] / f"{IMAGE}.parhex"
STAGED_NAME = f"{IMAGE}.param.parhex"

WORD = 0xFFFF_FFFF
SRAM_WORDS = 8192
KEPT_SLOTS = 4

# --- generated fields (RDL) -----------------------------------------------------
_KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
_KM_MBX = CHeaderRegBlock("KM_MAILBOX_KM", ip_c_header("key_manager").with_name("km_mailbox_km.h"))
_SCR = _KM_CSR.fields("SCRAMBLER_CTRL_REG")
SCR_ENABLE = _SCR["ENABLE"]["bm"]
SCR_LOCK = _SCR["LOCK"]["bm"]
SCR_CTRL_RESET = _KM_CSR.reset("SCRAMBLER_CTRL_REG")
SCR_CTRL_FIELDS = SCR_ENABLE | SCR_LOCK
CTRL_LOCKED = SCR_ENABLE | SCR_LOCK
_MBX_ST = _KM_MBX.fields("STATUS_REG")

# --- image layout (km_rom_scr.S; checked against the image signature) -----------
SIG_ADDR = 0x40
SIG_MAGIC = 0x5343_5231  # "SCR1"
LAYOUT_VERSION = 1
PHASE_MAGIC = 0x5048_0000
MSG_READY = 0x5245_4459
MSG_ONE = 0x4F4E_4531
MSG_DONE = 0x444F_4E45
ERR_PARAM = 0xEEEE_0001
ERR_PHASE = 0xEEEE_0002

_GROUP_BOUND = 400_000  # clocks for one message to reach the outbound FIFO
_POLL_CYCLES = 32  # clocks between SEP_STATUS polls
_CAPTURE_BOUND = 400_000  # clocks for the fourth scrambled write
_WARM_HOLD = 32  # clocks with the KM bit of SW_RESET_N low


def _h(v: int | None) -> str:
    return "X" if v is None else f"0x{v:08x}"


def signature_expect() -> tuple[int, ...]:
    """The signature words of IMG-SCR from the plan module and the RDL headers."""
    p = ip.ScrPlan
    return (
        SIG_MAGIC,
        LAYOUT_VERSION,
        ip.PARAM_BASE_WORD * 4,
        p.OFF_KA,
        p.OFF_KB,
        p.OFF_ADDRS8,
        p.OFF_DATA8,
        p.OFF_ORDER8,
        p.OFF_ADDRS64,
        p.OFF_DATA64,
        p.OFF_ADDRS_LOCK,
        p.OFF_DATA_LOCK,
        p.PAYLOAD_WORDS,
        SCR_ENABLE,
        SCR_LOCK,
        _MBX_ST["OUTBOUND_DEPTH"]["bp"],
        _MBX_ST["OUTBOUND_DEPTH"]["bw"],
        _MBX_ST["INBOUND_EMPTY"]["bm"],
        PHASE_MAGIC,
        MSG_READY,
        MSG_ONE,
        MSG_DONE,
        ERR_PARAM,
        ERR_PHASE,
    )


def check_plan(p: ip.ScrPlan) -> None:
    """Raise if the plan breaks a rule that the checks rely on (a generator bug)."""
    faults = []
    if not p.ka or not p.kb:
        faults.append("a key is 0")
    if not all(((p.ka ^ p.kb) >> (8 * i)) & 0xFF for i in range(4)):
        faults.append("kA and kB share a byte")
    if p.data8[0] != p.data8[1] or p.addrs8[0] == p.addrs8[1]:
        faults.append("the equal-plaintext pair is not two addresses with one word")
    if p.addrs8[1] != p.addrs8[0] + 4:
        faults.append("addrs8[0..1] is not an adjacent pair")
    if (p.addrs8[2] % ip.SRAM_REGION_BYTES) != (p.addrs8[3] % ip.SRAM_REGION_BYTES) or (
        p.addrs8[2] // ip.SRAM_REGION_BYTES == p.addrs8[3] // ip.SRAM_REGION_BYTES
    ):
        faults.append("addrs8[2..3] is not one offset in two regions")
    if sorted(p.order8) != list(range(8)):
        faults.append("order8 is not a permutation")
    allw = p.addrs8 + p.addrs64 + p.addrs_lock
    if len(set(allw)) != len(allw):
        faults.append("the address sets overlap")
    if any(a % 4 or not ip.SRAM_DRAW_LO <= a <= ip.SRAM_DRAW_HI for a in allw):
        faults.append("an address is outside the draw window")
    if len(set(p.data64)) != 64 or 0 in p.data64:
        faults.append("the 64 words are not distinct and non-zero")
    if 0 in p.data8 or 0 in p.data_lock:
        faults.append("a drawn word is 0")
    if faults:
        raise AssertionError(f"{TEST}: plan rule broken: {'; '.join(faults)}")


def read_parhex(path: Path) -> dict[int, int]:
    """ROM byte address -> 32-bit word of a KM ROM ``.parhex`` image."""
    words: dict[int, int] = {}
    addr = 0
    for raw in path.read_text(encoding="ascii").splitlines():
        tok = raw.strip()
        if not tok or tok.startswith("//"):
            continue
        if tok.startswith("@"):
            addr = int(tok[1:], 16)
            continue
        words[4 * addr] = int(tok, 16) & WORD
        addr += 1
    return words


class _TransportError(AssertionError):
    pass


@pyuvm.test()
class sep_km_sram_scrambler_key_rand_test(sep_base_test):
    """SRAM scrambler key and address dependence, row map, lock and reset domains."""

    required_evidence = (
        "CHK-SSCR-KEY",
        "CHK-SSCR-STORED",
        "CHK-SSCR-ALIAS",
        "CHK-SSCR-LOCK",
        "CHK-SSCR-RST",
        "CHK-SSCR-LOCK0",
        "CHK-SSCR-ROWS",
    )

    # ------------------------------------------------------------------ main

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.chk = SepChkLog(self, TEST, seed)
        self.dut = cocotb.top
        self.plan: ip.ScrPlan = ip.plan(TEST, seed)  # type: ignore[assignment]
        check_plan(self.plan)
        self._log_draws()
        self._check_image(seed)

        # Step 1-2: bring-up, KM release, phase 1.
        await self.bring_up_no_cpu()
        self.mbox = SepKmMailbox(self)
        self.swrst = SepSwReset(self)
        await self._wait_sep_reset_n()
        await self.swrst.release("km")
        self.cap: dict | None = None
        self._cap_on = True
        capture = cocotb.start_soon(self._capture_kept())
        open_graded_window(TEST, self.logger)
        await self._post_phase(1)
        await self._boot1(capture)
        close_graded_window(self.logger)

        await self._boot2()
        await self._boot3()
        await self._boot4()

        if not (self.swrst.value >> SW_RESET_N_BIT["km"]) & 1:
            await self.swrst.release("km")
        close_graded_window(self.logger)
        self.chk.finish()

    # ------------------------------------------------------------ set-up

    def _log_draws(self) -> None:
        p = self.plan
        lg = self.logger.info
        lg("DRAW ka=%s kb=%s", _h(p.ka), _h(p.kb))
        lg("DRAW addrs8=%s", [hex(a) for a in p.addrs8])
        lg("DRAW data8=%s", [_h(d) for d in p.data8])
        lg("DRAW order8=%s", p.order8)
        lg("DRAW addrs64=%s", [hex(a) for a in p.addrs64])
        lg("DRAW data64=%s", [_h(d) for d in p.data64])
        lg(
            "DRAW addrs_lock=%s data_lock=%s",
            [hex(a) for a in p.addrs_lock],
            [_h(d) for d in p.data_lock],
        )

    def _check_image(self, seed: int) -> None:
        """The staged image is the template with the block of this seed (HK-IMG-PARAM)."""
        arg = cocotb.plusargs.get("km_rom_hex")
        if not isinstance(arg, str) or Path(arg).name != STAGED_NAME:
            raise AssertionError(
                f"{TEST}: +km_rom_hex={arg!r}; the leaf boots the staged {STAGED_NAME}"
            )
        staged = Path(arg) if Path(arg).is_absolute() else Path.cwd() / arg
        if not staged.is_file():
            raise AssertionError(f"{TEST}: no staged image {staged}; the prestage step did not run")
        want = ip.staged_text(TEMPLATE, TEST, seed)
        got = staged.read_text(encoding="ascii")
        if got != want:
            raise AssertionError(
                f"{TEST}: {staged} is not the template with the block of seed {seed} "
                f"(sha256 {ip.identity(got)}, expected {ip.identity(want)})"
            )
        words = read_parhex(staged)
        expect = signature_expect()
        sig = tuple(words.get(SIG_ADDR + 4 * i, 0) for i in range(len(expect)))
        if sig != expect:
            raise AssertionError(
                f"{TEST}: IMG-SCR signature {[hex(w) for w in sig]} does not match the "
                f"host layout {[hex(w) for w in expect]}; rebuild the image"
            )
        block = ip.block_words(TEST, seed)
        base = ip.PARAM_BASE_WORD * 4
        if [words.get(base + 4 * i) for i in range(len(block))] != block:
            raise AssertionError(f"{TEST}: the staged block differs from the plan block")
        tmpl = TEMPLATE.read_text(encoding="ascii")
        self.logger.info(
            "KM-IMG-PARAM item=%s seed=%d template=%s template_sha256=%s staged=%s "
            "staged_sha256=%s block_words=%d",
            TEST,
            seed,
            TEMPLATE.name,
            hashlib.sha256(tmpl.encode("ascii")).hexdigest(),
            staged,
            ip.identity(got),
            len(block),
        )

    # ------------------------------------------------------------ plumbing

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(20_000):
            await RisingEdge(self.dut.clk_i)
            if self.rd(self.dut.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError("dbg_sep_reset_n_o did not read 1 within 20000 clocks")

    async def _post_phase(self, n: int) -> None:
        await self.mbox.post_raw_words([PHASE_MAGIC | n])
        self.logger.info("STEP phase word %d posted", n)

    async def _status(self) -> int:
        return await self.mbox.read_status()

    @staticmethod
    def _depth(st: int) -> int:
        return (st >> KM_STATUS_OUTBOUND_DEPTH_LSB) & KM_STATUS_OUTBOUND_DEPTH_MASK

    async def _wait_group(self, n: int, tag: str) -> None:
        """Wait until the outbound FIFO holds the n words of message ``tag``."""
        depth = 0
        for _ in range(0, _GROUP_BOUND, _POLL_CYCLES):
            depth = self._depth(await self._status())
            if depth >= n:
                break
            await ClockCycles(self.dut.clk_i, _POLL_CYCLES)
        else:
            raise _TransportError(
                f"message {tag}: {depth} of {n} words within {_GROUP_BOUND} clocks"
            )
        if depth != n:
            raise _TransportError(f"message {tag}: outbound depth {depth}, expected {n}")

    async def _read_group(self, n: int, tag: str) -> list[int]:
        """Read the n words of message ``tag``; the separator is on the last word only."""
        words = []
        for i in range(n):
            resp, data = await self.mbox.read_data_raw()
            if resp != RESP_OKAY:
                raise _TransportError(f"message {tag}: word {i} read resp={resp}")
            st = await self._status()
            sep = (st >> KM_STATUS_OUTBOUND_SEPARATOR) & 1
            if sep != (1 if i == n - 1 else 0):
                raise _TransportError(f"message {tag}: word {i} separator={sep}")
            words.append(data & WORD)
        return words

    async def _recv(self, n: int, tag: str, need: str, before=None) -> list[int]:
        """One message of n words; ``before`` runs once it is in the FIFO, before the read.

        A transport failure fails the checker ``need`` and stops the leaf.
        """
        try:
            await self._wait_group(n, tag)
            if before is not None:
                await before()
            words = await self._read_group(n, tag)
        except _TransportError as exc:
            self.chk.ok(need, False, transport=tag, reason=str(exc))
            raise
        self.logger.info("MSG %s %s", tag, [_h(w) for w in words])
        return words

    def _count_ok(self, got: list[int], want: list[int]) -> int:
        return sum(1 for g, w in zip(got, want, strict=True) if g == w)

    async def _capture_kept(self) -> None:
        """KM-SRAM-MON at the clock its count first reads 4 (the fourth scrambled write).

        The kept rows and data stay in the monitor; the array word at each kept row
        is taken in the same clock, before the next write can land.
        """
        dut = self.dut
        n = len(dut.km_sram_scr_wr_addr_o) // KEPT_SLOTS
        for _ in range(_CAPTURE_BOUND):
            if not self._cap_on:
                return
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            try:
                cnt = self.rd_known(dut.km_sram_scr_wr_count_o)
            except AssertionError:
                continue
            if cnt < KEPT_SLOTS:
                continue
            rows = self.rd_known(dut.km_sram_scr_wr_addr_o)
            data = self.rd_known(dut.km_sram_scr_wr_data_o)
            cells = self.rd_known(dut.km_sram_scr_wr_cell_o)
            self.cap = {
                "count": cnt,
                "rows": [(rows >> (n * i)) & ((1 << n) - 1) for i in range(KEPT_SLOTS)],
                "data": [(data >> (32 * i)) & WORD for i in range(KEPT_SLOTS)],
                "cells": [(cells >> (32 * i)) & WORD for i in range(KEPT_SLOTS)],
            }
            return

    async def _snapshot(self) -> list[int | None]:
        """The 8192 words of the KM-SRAM tap in stored form {parity, data}."""
        dut = self.dut
        out: list[int | None] = []
        for i in range(SRAM_WORDS):
            dut.km_sram_peek_addr_i.value = i
            await Timer(1, units="ns")
            try:
                out.append(self.rd_known(dut.km_sram_peek_o))
            except AssertionError:
                out.append(None)
        dut.km_sram_peek_addr_i.value = 0
        return out

    # ------------------------------------------------------------ boot 1

    async def _boot1(self, capture) -> None:
        p = self.plan
        d8 = p.data8

        g_ka = await self._recv(8, "ka", "SSCR-KEY")
        g_kb = await self._recv(8, "kb", "SSCR-KEY")
        g_ka2 = await self._recv(8, "ka-again", "SSCR-KEY")
        self._cap_on = False
        await capture
        g_en0 = await self._recv(9, "enable0", "SSCR-LOCK")

        rows_state: dict = {}

        async def at_ready() -> None:
            rows_state["s1"] = await self._snapshot()
            rows_state["w1"] = self.rd_known(self.dut.km_sram_write_count_o)
            rows_state["live"] = self.rd_known(self.dut.km_sram_scr_wr_cell_o)

        async def at_done() -> None:
            rows_state["s2"] = await self._snapshot()
            rows_state["w2"] = self.rd_known(self.dut.km_sram_write_count_o)

        ready = await self._recv(1, "ready", "SSCR-ROWS", before=at_ready)
        done = await self._recv(1, "done", "SSCR-ROWS", before=at_done)
        g64: list[int] = []
        for k in range(4):
            g64 += await self._recv(16, f"words64-{k}", "SSCR-ALIAS")
        g_key_unlocked = await self._recv(1, "key-unlocked", "SSCR-LOCK")
        g_locked = await self._recv(2, "locked", "SSCR-LOCK")
        g_kb_locked = await self._recv(8, "kb-locked", "SSCR-LOCK")
        g_en0_locked = await self._recv(9, "enable0-locked", "SSCR-LOCK")
        g_lock0_locked = await self._recv(9, "lock0-locked", "SSCR-LOCK")

        # CHK-SSCR-KEY and CHK-SSCR-STORED: the kept writes.
        cap = self.cap
        ka_ok = self._count_ok(g_ka, d8)
        self.chk.ctrl("SSCR-KEY-KA", ka_ok == 8, ka_ok=ka_ok, open_owner="sep_km_mem_smoke_test")
        if cap is None or cap["count"] != KEPT_SLOTS:
            self.chk.ok(
                "SSCR-KEY",
                False,
                reason="no clock with exactly 4 scrambled writes",
                count=None if cap is None else cap["count"],
            )
            self.chk.ok("SSCR-STORED", False, reason="kept writes not captured")
            self._lock_checks(
                None, g_en0, g_key_unlocked, g_locked, g_kb_locked, g_en0_locked, g_lock0_locked
            )
        else:
            data = cap["data"]
            key_pair_ne = data[0] != data[2]
            ka_again_ok = self._count_ok(g_ka2, d8)
            self.chk.ok(
                "SSCR-KEY",
                key_pair_ne and ka_again_ok == 8,
                ka_ok=f"{ka_ok}(control)",
                key_pair_ne=key_pair_ne,
                ka_again_ok=ka_again_ok,
            )
            self.chk.obs("SSCR-KB", kb_eq=self._count_ok(g_kb, d8))
            self._stored_checks(cap)
            self._lock_checks(
                key_pair_ne,
                g_en0,
                g_key_unlocked,
                g_locked,
                g_kb_locked,
                g_en0_locked,
                g_lock0_locked,
            )

        # CHK-SSCR-ALIAS.
        readback_ok = self._count_ok(g64, p.data64)
        self.chk.ok("SSCR-ALIAS", readback_ok == 64, logical=64, readback_ok=readback_ok)

        # CHK-SSCR-ROWS.
        self._rows_check(rows_state, ready, done)

        # The mailbox is empty before the warm reset.
        st = await self._status()
        empty = bool((st >> KM_STATUS_OUTBOUND_EMPTY) & 1) and bool(
            (st >> KM_STATUS_INBOUND_EMPTY) & 1
        )
        self.chk.ctrl("SSCR-MBOX-EMPTY", empty, status=_h(st))

    def _stored_checks(self, cap: dict) -> None:
        p = self.plan
        rows, data, cells = cap["rows"], cap["data"], cap["cells"]
        # The array word at a kept row equals the data of the last kept write to it.
        want = []
        for i in range(KEPT_SLOTS):
            last = max(j for j in range(KEPT_SLOTS) if rows[j] == rows[i])
            want.append(data[last])
        array_eq = sum(1 for c, w in zip(cells, want, strict=True) if c == w)
        self.chk.ctrl(
            "SSCR-STORED-ARRAY",
            array_eq == KEPT_SLOTS,
            array_eq=array_eq,
            rows=[hex(r) for r in rows],
            open_owner="sep_km_mem_smoke_test",
        )
        same_p_pair_ne = data[0] != data[1]
        self.chk.ok(
            "SSCR-STORED",
            same_p_pair_ne,
            array_eq=f"{array_eq}(control)",
            same_p_pair_ne=same_p_pair_ne,
        )
        plain = [p.data8[0], p.data8[1], p.data8[0], p.data8[p.order8[0]]]
        self.chk.obs(
            "SSCR-STORED",
            stored_ne=sum(1 for d, q in zip(data, plain, strict=True) if d != q),
        )

    def _lock_checks(
        self,
        key_pair_ne,
        g_en0,
        g_key_unlocked,
        g_locked,
        g_kb_locked,
        g_en0_locked,
        g_lock0_locked,
    ) -> None:
        p = self.plan
        d8 = p.data8
        key_rd_unlocked_ok = g_key_unlocked[0] == p.ka
        self.chk.ctrl("SSCR-LOCK-KEYRD", key_rd_unlocked_ok, key_rd=_h(g_key_unlocked[0]))
        en0_ctrl = g_en0[0]
        self.chk.ctrl("SSCR-LOCK-EN0", en0_ctrl == 0, en0_ctrl=_h(en0_ctrl))
        self.chk.obs("SSCR-EN0", reads_eq=self._count_ok(g_en0[1:], d8))
        self.chk.ctrl("SSCR-LOCK-KEYWR", bool(key_pair_ne), key_pair_ne=key_pair_ne)
        ctrl_rds = [g_locked[0], g_en0_locked[0], g_lock0_locked[0]]
        key_rd_locked = g_locked[1]
        kb_ok = self._count_ok(g_kb_locked, d8)
        en_ok = self._count_ok(g_en0_locked[1:], d8)
        l0_ok = self._count_ok(g_lock0_locked[1:], d8)
        key_write_ignored = kb_ok == 8
        enable_write_ignored = g_en0_locked[0] == CTRL_LOCKED and en_ok == 8
        lock_write0_kept = g_lock0_locked[0] == CTRL_LOCKED and l0_ok == 8
        all_ctrl = all(v == CTRL_LOCKED for v in ctrl_rds)
        self.locked_ctrl = g_locked[0]
        self.chk.ok(
            "SSCR-LOCK",
            key_rd_locked == 0
            and key_write_ignored
            and enable_write_ignored
            and lock_write0_kept
            and all_ctrl,
            key_rd_unlocked_ok=f"{int(key_rd_unlocked_ok)}(control)",
            en0_ctrl=f"{_h(en0_ctrl)}(control)",
            key_rd_locked=_h(key_rd_locked),
            key_write_ignored=key_write_ignored,
            enable_write_ignored=enable_write_ignored,
            lock_write0_kept=lock_write0_kept,
            ctrl_rd=[_h(v) for v in ctrl_rds],
            reads_ok=en_ok + l0_ok,
            kb_reads_ok=kb_ok,
            rsvd_mask=_h(WORD & ~SCR_CTRL_FIELDS),
        )

    def _rows_check(self, st: dict, ready: list[int], done: list[int]) -> None:
        cap = self.cap
        s1, s2 = st["s1"], st["s2"]
        unknown = sum(1 for a, b in zip(s1, s2, strict=True) if a is None or b is None)
        # The tap reads the live array: at the first snapshot it shows the word that
        # the monitor reads at each kept row (no SRAM write lies between the two).
        if cap is not None:
            live = [(st["live"] >> (32 * i)) & WORD for i in range(KEPT_SLOTS)]
            tap = [None if s1[r] is None else s1[r] & WORD for r in cap["rows"]]
            self.chk.ctrl(
                "SSCR-ROWS-TAP",
                tap == live,
                tap=[_h(v) for v in tap],
                live=[_h(v) for v in live],
            )
        else:
            self.chk.ctrl("SSCR-ROWS-TAP", False, reason="kept rows not captured")
        changed = sum(1 for a, b in zip(s1, s2, strict=True) if a != b)
        writes = st["w2"] - st["w1"]
        self.chk.ok(
            "SSCR-ROWS",
            ready == [MSG_READY]
            and done == [MSG_DONE]
            and unknown == 0
            and writes == 64
            and changed <= 64,
            logical=64,
            changed_rows_max=64,
            sram_writes=writes,
            unknown_rows=unknown,
            ready=_h(ready[0]),
            done=_h(done[0]),
        )
        self.chk.obs("SSCR-ROWS", changed_rows=changed)

    # ------------------------------------------------------------ boots 2-4

    async def _boot2(self) -> None:
        """Warm reset with the lock set, then the 8 words under kA with no key write."""
        await self.mbox.flush()
        await self.swrst.park("km")
        await ClockCycles(self.dut.clk_i, _WARM_HOLD)
        await self.swrst.release("km")
        open_graded_window(TEST, self.logger)
        await self._post_phase(2)
        g = await self._recv(9, "warm", "SSCR-RST")
        close_graded_window(self.logger)
        self.warm = g

    async def _cold_release(self, phase: int) -> None:
        r = await self.pulse_rst_ni()
        self.logger.info("LOG cold reset release_clks=%d", r["release_clks"])
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        if (SW_RESET_N_RESET_DEFAULT >> SW_RESET_N_BIT["km"]) & 1:
            raise AssertionError(
                f"SW_RESET_N reset value {_h(SW_RESET_N_RESET_DEFAULT)} releases the KM"
            )
        await self.swrst.release("km")
        open_graded_window(TEST, self.logger)
        await self._post_phase(phase)

    async def _boot3(self) -> None:
        """Cold reset: SCRAMBLER_CTRL reads its reset value and a kB write lands."""
        p = self.plan
        await self._cold_release(3)
        g = await self._recv(2, "cold", "SSCR-RST")
        close_graded_window(self.logger)
        warm_ctrl = self.warm[0]
        warm_reads_ok = self._count_ok(self.warm[1:], p.data8)
        cold_ctrl, cold_key = g
        self.chk.ctrl(
            "SSCR-RST-PRE",
            getattr(self, "locked_ctrl", None) == CTRL_LOCKED and p.kb != 0,
            pre_ctrl=_h(getattr(self, "locked_ctrl", None)),
            kb_nonzero=p.kb != 0,
        )
        self.chk.ok(
            "SSCR-RST",
            warm_ctrl == CTRL_LOCKED
            and warm_reads_ok == 8
            and cold_ctrl == SCR_CTRL_RESET
            and cold_key == p.kb,
            warm_ctrl=_h(warm_ctrl),
            warm_reads_ok=warm_reads_ok,
            cold_ctrl=_h(cold_ctrl),
            cold_key_write_lands=cold_key == p.kb,
        )

    async def _boot4(self) -> None:
        """Lock written with the enable at 0: the next store is a scrambled write."""
        await self._cold_release(4)
        cnt: dict[str, int] = {}

        def sample(name: str):
            async def fn() -> None:
                cnt[name] = self.rd_known(self.dut.km_sram_scr_wr_count_o)

            return fn

        r0 = await self._recv(1, "lock0-ready", "SSCR-LOCK0", before=sample("c0"))
        r1 = await self._recv(1, "lock0-one", "SSCR-LOCK0", before=sample("c1"))
        g = await self._recv(2, "lock0-done", "SSCR-LOCK0", before=sample("c2"))
        close_graded_window(self.logger)
        d10 = cnt["c1"] - cnt["c0"]
        d21 = cnt["c2"] - cnt["c1"]
        frames = r0 == [MSG_READY] and r1 == [MSG_ONE] and g[1] == MSG_DONE
        self.chk.ctrl("SSCR-LOCK0-OFF", d10 == 0 and frames, c1_minus_c0=d10)
        self.chk.ok(
            "SSCR-LOCK0",
            d21 == 1 and frames,
            c1_minus_c0=f"{d10}(control)",
            c2_minus_c1=d21,
            ctrl_rd_logged=_h(g[0]),
            frames_ok=frames,
        )

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lock slots 1 to 40, the lock exemptions, the lock order, program rounds and version flags.

Contract: slot n has its write-lock at ``LOCKS`` bit 2n and its read-lock at bit
2n+1 (slots 32 to 40 in ``LOCKS_SPARE`` bits 2(n-32) and 2(n-32)+1). A write-lock
stops programs of its field and shadow writes; a read-lock stops the shadow read and
a read-interface request on the field, which sets ``efuse_req_error``. The sense
fills a locked shadow. ``LOCKS``, ``LOCKS_SPARE`` and ``LC_STATE`` stay readable with
every assigned lock bit burned. A programmed bit reaches the shadow only at the next
sense, a burned bit never clears, and a burned version flag stays set.
Sources: ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (sections Shadow Register and
JTAG Access Control, Fuse Programming and RMA Authorization, Shadow Register Updates
and Test-Mode Protection, Fuse Fields, Anti-Rollback Security-Version Flags);
``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc`` (``LOCKS``, ``LOCKS_SPARE``,
``SIP_DIS``, ``SYS_DIS``); ``hw/ip/efuse/regs/gen/adoc/efuse_interface_ctrl.adoc``
(``EFUSE_PROGRAM_CTRL``, ``EFUSE_READ_CTRL``, ``EFUSE_INTERFACE_CTRL_STATUS``);
``hw/sys/sep/doc/lifecycle_controller.adoc`` (Per-LC-state Feature Control Profile).
``hw/sys/sep/doc/otp_fuse_controller.adoc`` states "`efuse_guard` filters every
command before it reaches the shim" and "A write-lock blocks fuse programming and
shadow writes; a read-lock blocks software and JTAG reads of both the fuse field and
its shadow"; ``hw/ip/efuse/doc/architecture.adoc`` (Access Permissions and Security)
states that lock state is enforced by the eFuse guard.

The seed draws one leaf kind and its t=0 image through ``sep_efuse_plan.plan``
(the pre-sim hook stages the same image): the lock leg 4, the single-bit image 1,
the exempt cell 1, the order cell 2 and the chain leg 2.

Checkers:
  CHK-LOCK-CELL     lock leg and single-bit image, one line per read slot: the
                    sensed-shadow output equals the staged words (the sense ignores
                    locks); an unlocked frontdoor read equals them; a read-interface
                    request on a read-locked field sets ``efuse_req_error`` from 0
                    (read before the go) and the write-one clear returns it to 0, on an
                    unlocked twin it ends with ``read_done`` 1, ``read_status`` 0 and
                    ``efuse_req_error`` 0; a program on a write-locked field sets
                    ``efuse_req_error``, which the clear returns to 0, with no bank
                    bit change and no program command at the post-guard tap, on an
                    unlocked field it lands exactly its bit with one program command
                    at its address; a shadow write is
                    blocked under a write-lock and ORs the new bit without one.
  CHK-GUARD-NOPULSE lock leg and single-bit image, one line per blocked request (a
                    read-interface request on a read-locked field, a program on a
                    write-locked field): from the go write to the disable write, the
                    post-guard ``efuse_shim_cmd_valid_o`` and the bank APB
                    ``efuse_bank_psel_o``, sampled on every rising clock edge, are 0 on
                    every edge, so no pulse of even one clock reaches the shim or the
                    bank.
  CHK-LOCK-EXEMPT   exempt cell: ``LC_STATE``, ``LOCKS`` and ``LOCKS_SPARE`` read their
                    staged values with every assigned lock bit burned.
  CHK-LOCK-ORDER    order cell: a shadow write lands only before the lock, the lock bit
                    survives a write of 0 to ``LOCKS``, a later write of a third bit
                    leaves the shadow unchanged.
  CHK-PROG-ROUND    chain leg, per round: the frontdoor word is unchanged after the
                    program and the bank gains exactly the bit; after the resense all
                    256 sensed words equal the model, the frontdoor word holds the bit
                    and ``FEAT_CTRL`` equals the profile row of the new image.
  CHK-PROG-VERSION  chain leg: after the resense only the programmed version flag is
                    set, and it stays set after a second resense.

Controls: the unlocked neighbours of the target slot are the accepted read and
landed program twins of the lock leg (``CTRL-LOCK-CELL-RD-TWIN``,
``CTRL-LOCK-CELL-PROG-TWIN``); every accepted read and landed program of the same
leaf, sampled in the same window by the same sampler, shows valid and ``psel`` 1 on
at least one edge (``CTRL-GUARD-NOPULSE-LIVE``, one line per request kind); an
unlocked shadow-write field is the twin of a blocked shadow write (``CTRL-LOCK-CELL-WR-TWIN``; the plan trap filter leaves at
least one of slots 3, 4, 21 and 22 without a write-lock in every lock leaf); the single-bit image has its own
twin slot; the exempt cell has the ``CLASS_KEY`` blocked request and the ``LOCKS``
accepted request (``CTRL-LOCK-EXEMPT-RL``, ``CTRL-LOCK-EXEMPT-TWIN``); the order cell
has a control write on a second slot (``CTRL-LOCK-ORDER-PATH``) and the third bit
absent before its write (``CTRL-LOCK-ORDER-THIRD``); the chain compares all 256
words after the first sense with the staged image.

Observations: ``OBS-LOCK-READ`` logs the response and data of a frontdoor read that a
read-lock blocks; the specification states neither, so they are not graded.

Time: W is ``_W_MULT`` times the sense time measured at the first sense. A program
or read-interface request waits the full W with no early exit, then reads its
status. Every sense wait is bounded by ``_SENSE_BOUND`` clocks; a timeout fails the
check that the step feeds.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense. RAND-REP (lock leg,
single-bit image, order cell) and RANDCFG (chain leg).
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import (
    PulseCount,
    SepEfuseBank,
    SepShimCmdMonitor,
    WatchMark,
    diff_is_exactly,
    diff_log,
)
from env.sep_efuse_plan import (
    LOCK_SLOT_FIELD,
    PROGRAM_CTRL_ADDR,
    READ_CTRL_ADDR,
    STATUS_ADDR,
    bit_address,
    feat_ctrl_profile,
    field_n_words,
    field_word,
    plan,
    program_go_no_wait,
    read_ctrl_word,
    shadow_addr,
    write_lock_bit,
)
from env.sep_efuse_test_lib import (
    SenseClock,
    SepEfuseFd,
    probe_words,
    rst_pulse,
    set_shadow_golden,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

TEST = "sep_efuse_lock_slot_matrix_rand_test"

# W = _W_MULT x the sense time of the first sense (test parameter).
_W_MULT = 2
_SENSE_BOUND = 20_000
# Clocks after the B of a shadow or LOCKS write before the next access (FCOV write
# effects sample 8 clocks after the B).
_WR_SETTLE = 16
_WORD = 0xFFFF_FFFF
_RESP_OKAY = 0

_ST = "EFUSE_INTERFACE_CTRL_STATUS"
_PG = "EFUSE_PROGRAM_CTRL"
_RD = "EFUSE_READ_CTRL"
_REQ_ERR = EFUSE_INTERFACE_CTRL.field_mask(_ST, "efuse_req_error")
_CLEAR3 = (
    EFUSE_INTERFACE_CTRL.field_mask(_ST, "efuse_req_error_clear")
    | EFUSE_INTERFACE_CTRL.field_mask(_ST, "efuse_program_addr_error_clear")
    | EFUSE_INTERFACE_CTRL.field_mask(_ST, "efuse_read_addr_error_clear")
)
_PG_BUSY = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_busy")
_PG_DONE = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_done")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_status")
_RD_BUSY = EFUSE_INTERFACE_CTRL.field_mask(_RD, "read_busy")
_RD_DONE = EFUSE_INTERFACE_CTRL.field_mask(_RD, "read_done")
_RD_STATUS = EFUSE_INTERFACE_CTRL.field_mask(_RD, "read_status")

_KIND_W = ("write", "write_read")
_KIND_R = ("read", "write_read")
_SHADOW_WRITE_FIELDS = ("SIP_DIS", "SYS_DIS", "REQUIRED_SIGNERS", "REQUIRED_ALGS")

# Checks per leaf kind (checkers table of the entry). No check runs on every seed.
_EVIDENCE = {
    "lock_leg": ("CHK-LOCK-CELL", "CHK-GUARD-NOPULSE"),
    "single_bit": ("CHK-LOCK-CELL", "CHK-GUARD-NOPULSE"),
    "exempt": ("CHK-LOCK-EXEMPT",),
    "order": ("CHK-LOCK-ORDER",),
    "chain": ("CHK-PROG-ROUND", "CHK-PROG-VERSION"),
}
_KIND_CHECK = {k: v[0] for k, v in _EVIDENCE.items()}


def _bit(v: int, m: int) -> int:
    return int(bool(v & m))


def _hexw(words: list[int]) -> str:
    return ":".join(f"{w:08x}" for w in words)


@pyuvm.test()
class sep_efuse_lock_slot_matrix_rand_test(sep_base_test):
    """Lock slots, exemptions, lock order, program rounds and version flags per leaf kind."""

    # The leaf kind sets the checks; run_scenario names them before the first DUT read.
    required_evidence: tuple[str, ...] = ()

    # --- bus, probes and senses ----------------------------------------------
    async def _rd(self, addr: int, *, blocked: bool = False) -> SepAxiAccessSeq:
        """Frontdoor read. A read of a read-locked field is logged, not graded, so its
        response and a timeout pass the scoreboard."""
        return await self.fd.access(
            SepAxiOp.READ, addr, ungraded_read=blocked, allow_timeout=blocked
        )

    async def _rd32(self, addr: int) -> int:
        return await self.fd.rd(addr)

    async def _wr(self, addr: int, data: int, *, shadow: bool = False) -> int:
        """One 32-bit frontdoor write. A shadow write is graded by its effect, not its
        response, so its response is returned and logged only."""
        seq = await self.fd.access(SepAxiOp.WRITE, addr, data & _WORD, unverified_write=shadow)
        if shadow:
            await ClockCycles(cocotb.top.clk_i, _WR_SETTLE)
        return 0 if seq.resp_ok else seq.resp_code

    def _probe(self, name: str) -> list[int]:
        """Words of ``name`` at the sensed-shadow output ``efuse_shadow_probe_o``."""
        w0, n = field_word(name), field_n_words(name)
        mask = ((1 << (32 * n)) - 1) << (32 * w0)
        v = self.rd_known(cocotb.top.efuse_shadow_probe_o, mask) >> (32 * w0)
        return [(v >> (32 * k)) & _WORD for k in range(n)]

    def _probe_all(self) -> list[int]:
        return probe_words(self, cocotb.top.efuse_shadow_probe_o, 256)

    async def _fd_words(self, name: str) -> tuple[list[int], int]:
        """Frontdoor words of ``name`` and the OR of the non-OKAY response codes."""
        words, bad = [], 0
        for k in range(field_n_words(name)):
            seq = await self._rd(shadow_addr(name, k))
            words.append(seq.rdata & _WORD)
            bad |= 0 if seq.resp_ok else max(seq.resp_code, 1)
        return words, bad

    async def _fd_locked(self, slot: int, name: str) -> None:
        """Frontdoor read of a read-locked field: logged, not graded."""
        for k in range(field_n_words(name)):
            seq = await self._rd(shadow_addr(name, k), blocked=True)
            self.chk.obs(
                "LOCK-READ",
                slot=slot,
                word=k,
                resp="timeout" if seq.timed_out else (0 if seq.resp_ok else seq.resp_code),
                rdata=f"0x{seq.rdata & _WORD:08x}",
            )

    async def _sense(self, check: str, *, first: bool = False) -> int:
        """Release (first) or pulse ``rst_ni``, wait for sense done, return the sense time.

        The base post-sense compare grades every staged field at the sensed-shadow
        output against the current golden; a mismatch or a timeout fails ``check``.
        """
        clock = SenseClock(self).start()
        try:
            if first:
                await self.release_no_cpu_reset()
            else:
                await rst_pulse(self)
            await self.wait_fuse_sense(max_cycles=_SENSE_BOUND)
            if clock.clocks is None:
                raise AssertionError("the sense clock did not see the sense-done rise")
        except AssertionError as exc:
            clock.stop()
            self.chk.ok(check, False, step="sense", first=first, reason=str(exc)[:240])
            raise
        return clock.clocks

    # --- read and program interface (entry step 1) -------------------------------
    async def _req_err_now(self) -> int:
        return _bit(await self._rd32(STATUS_ADDR), _REQ_ERR)

    async def _clear_status(self) -> int:
        """Write-one clear of the three flags; returns ``efuse_req_error`` read back after it."""
        await self._wr(STATUS_ADDR, _CLEAR3)
        return await self._req_err_now()

    async def _read_if(self, bit_addr: int) -> dict[str, Any]:
        """Read bit ``bit_addr`` through the read interface: go, full W, status, disable.

        ``efuse_req_error`` is sticky, so the request reads it before the go
        (``pre_req_err``) and after its own clear (``clr_req_err``); a blocked read
        graded on a flag that was already set cannot pass.
        """
        pre = await self._req_err_now()
        start = self._pulse_mark()
        await self._wr(READ_CTRL_ADDR, read_ctrl_word(bit_addr))
        await ClockCycles(cocotb.top.clk_i, self.w)
        ctrl = await self._rd32(READ_CTRL_ADDR)
        st = await self._rd32(STATUS_ADDR)
        await self._wr(READ_CTRL_ADDR, 0)
        r = {
            "pulses": self._pulses(start),
            "busy": _bit(ctrl, _RD_BUSY),
            "done": _bit(ctrl, _RD_DONE),
            "status": _bit(ctrl, _RD_STATUS),
            "req_err": _bit(st, _REQ_ERR),
            "pre_req_err": pre,
            "clr_req_err": "na",
        }
        if r["req_err"] or r["status"]:
            r["clr_req_err"] = await self._clear_status()
        return r

    async def _program(self, bit_addr: int, *, read_back: int = 0, watch: bool = True) -> dict:
        """Program bit ``bit_addr`` (data 1): go, full W, command tap, bank diff, status."""
        snap = self.bank.snapshot()
        mark = self.shim.mark() if watch else None
        start = self._pulse_mark() if watch else None
        await program_go_no_wait(self._wr, bit_addr, read_back=read_back)
        await ClockCycles(cocotb.top.clk_i, self.w)
        progs = self.shim.programs_since(mark) if mark is not None else None
        diff = self.bank.diff_since(snap)
        ctrl = await self._rd32(PROGRAM_CTRL_ADDR)
        st = await self._rd32(STATUS_ADDR)
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        r = {
            "pulses": self._pulses(start),
            "busy": _bit(ctrl, _PG_BUSY),
            "done": _bit(ctrl, _PG_DONE),
            "prog_status": _bit(ctrl, _PG_STATUS),
            "req_err": _bit(st, _REQ_ERR),
            "diff": diff,
            "progs": progs,
            "clr_req_err": "na",
        }
        if r["req_err"]:
            r["clr_req_err"] = await self._clear_status()
        return r

    def _pulse_mark(self) -> WatchMark | None:
        """Start of a request window, when the command monitor runs (lock leg, single bit)."""
        return self.shim.mark() if self.pulse_watch else None

    def _pulses(self, start: WatchMark | None) -> PulseCount | None:
        """Valid and ``psel`` clocks from ``start`` to now; raises if no edge was sampled."""
        return None if start is None else self.shim.pulses_between(start, self.shim.mark())

    def _guard_nopulse(self, req: str, r: dict, blocked: bool, **fields: Any) -> None:
        """CHK-GUARD-NOPULSE on a blocked request; an accepted one feeds the live control."""
        pc: PulseCount | None = r["pulses"]
        if pc is None:
            return
        if blocked:
            self.chk.ok(
                "GUARD-NOPULSE",
                pc.valid == 0 and pc.psel == 0,
                req=req,
                **fields,
                edges=pc.edges,
                valid_pulses=pc.valid,
                psel_pulses=pc.psel,
            )
            self.blocked_reqs[req] += 1
        else:
            self.live_reqs[req].append(pc)

    def _guard_live_ctrl(self) -> None:
        """Each request kind with a blocked request has accepted twins that all show
        valid and ``psel`` on the same sampler."""
        for req, n_blocked in self.blocked_reqs.items():
            if not n_blocked:
                continue
            live = self.live_reqs[req]
            self.chk.ctrl(
                "GUARD-NOPULSE-LIVE",
                bool(live) and all(pc.valid >= 1 and pc.psel >= 1 for pc in live),
                req=req,
                blocked=n_blocked,
                accepted=len(live),
                edges=",".join(str(pc.edges) for pc in live),
                valid_pulses=",".join(str(pc.valid) for pc in live),
                psel_pulses=",".join(str(pc.psel) for pc in live),
            )

    @staticmethod
    def _landed(r: dict, bit_addr: int) -> bool:
        progs = r["progs"]
        cmd_ok = progs is None or (len(progs) == 1 and progs[0].address == bit_addr)
        return (
            r["busy"] == 0
            and r["req_err"] == 0
            and r["done"] == 1
            and diff_is_exactly(r["diff"], bit_addr)
            and cmd_ok
        )

    @staticmethod
    def _refused(r: dict) -> bool:
        progs = r["progs"]
        return (
            r["busy"] == 0
            and r["req_err"] == 1
            and r["clr_req_err"] == 0
            and not r["diff"]
            and not progs
        )

    # --- scenario ---------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        p = plan(TEST, seed)
        kind = p.leg["kind"]
        for line in p.log_lines(kind=kind):
            self.logger.info("%s", line)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        self.required_evidence = _EVIDENCE[kind]
        self.logger.info(
            "EVIDENCE seed=%d kind=%s required=%s", seed, kind, ",".join(self.required_evidence)
        )
        self.chk = SepChkLog(self, TEST, seed)
        self.plan = p
        self.fd = SepEfuseFd(self)
        check = _KIND_CHECK[kind]

        # The prestaged file holds the same image; this write sets the post-sense golden.
        self.write_efuse_image(p.image)
        close_graded_window()
        # The sense of the leaf image is graded stimulus (the sense ignores locks).
        open_graded_window(TEST, self.logger)
        sense = await self._sense(check, first=True)
        self.w = _W_MULT * sense
        self.logger.info(
            "WINDOW seed=%d sense_clks=%d w_mult=%d w=%d", seed, sense, _W_MULT, self.w
        )
        self.bank = SepEfuseBank()
        # The post-guard command tap anchors the lock leg and the single-bit image only.
        self.shim = SepShimCmdMonitor(psel=True)
        self.pulse_watch = kind in ("lock_leg", "single_bit")
        if self.pulse_watch:
            self.shim.start()
        await ClockCycles(cocotb.top.clk_i, 2)

        if kind == "lock_leg":
            await self._lock_leg()
        elif kind == "single_bit":
            await self._single_bit()
        elif kind == "exempt":
            await self._exempt()
        elif kind == "order":
            await self._order()
        else:
            await self._chain()

        close_graded_window(self.logger)
        if kind in ("lock_leg", "single_bit"):
            await self.shim.stop()
        self.chk.finish(f" kind={kind}")

    # --- lock leg and single-bit image (entry steps 2 to 7) ----------------------
    async def _cell(
        self,
        slot: int,
        kind: str,
        *,
        read_bit: dict | None,
        prog_bit: dict | None,
        shadow_bit: dict | None,
        fd_read: bool = True,
    ) -> dict[str, Any]:
        """Steps 3 to 6 on one slot. Returns the cell result and its log fields."""
        name = LOCK_SLOT_FIELD[slot]
        wl, rl = kind in _KIND_W, kind in _KIND_R
        w0 = field_word(name)
        staged = [self.plan.image.words[w0 + k] & _WORD for k in range(field_n_words(name))]
        ok = True
        f: dict[str, Any] = {"slot": slot, "field": name, "wl": int(wl), "rl": int(rl)}
        f["staged"] = _hexw(staged)

        # Step 3: the sense fills the shadow, locked or not.
        probe = self._probe(name)
        f["sense_probe"] = _hexw(probe)
        ok &= probe == staged

        # Step 4: frontdoor read and the read-interface request.
        if not fd_read:
            f["read"] = "na"
        elif rl:
            await self._fd_locked(slot, name)
            f["read"] = "logged"
        else:
            words, bad = await self._fd_words(name)
            f["read"] = _hexw(words)
            ok &= words == staged and bad == 0
        if read_bit is None:
            f["rd_if"] = "na"
            f["rd_req_err"] = "na"
            f["rd_pre_req_err"] = "na"
            f["rd_clr_req_err"] = "na"
        else:
            r = await self._read_if(read_bit["addr"])
            f["rd_if"] = "blocked" if rl else "accepted"
            f["rd_req_err"] = r["req_err"]
            f["rd_pre_req_err"] = r["pre_req_err"]
            f["rd_clr_req_err"] = r["clr_req_err"]
            f["rd_bit_addr"] = read_bit["addr"]
            f["rd_flags"] = f"busy{r['busy']}/done{r['done']}/st{r['status']}"
            self._guard_nopulse("read", r, rl, slot=slot, field=name, bit_addr=read_bit["addr"])
            if rl:
                ok &= (
                    r["pre_req_err"] == 0
                    and r["req_err"] == 1
                    and r["clr_req_err"] == 0
                    and r["busy"] == 0
                )
            else:
                ok &= r["busy"] == 0 and r["done"] == 1 and r["status"] == 0 and r["req_err"] == 0
                self.accepted_reads += int(ok)

        # Step 5: program a zero bit of the used range.
        if prog_bit is None:
            f.update(prog="na", req_err="na", clr_req_err="na", otp_diff="na", shim_cmd="na")
        else:
            a = prog_bit["addr"]
            r = await self._program(a)
            f["prog_bit_addr"] = a
            f["req_err"] = r["req_err"]
            f["clr_req_err"] = r["clr_req_err"]
            f["otp_diff"] = (
                "none" if not r["diff"] else (a if diff_is_exactly(r["diff"], a) else "other")
            )
            f["shim_cmd"] = len(r["progs"])
            f["pg_flags"] = f"busy{r['busy']}/done{r['done']}/st{r['prog_status']}"
            self._guard_nopulse("program", r, wl, slot=slot, field=name, bit_addr=a)
            if wl:
                f["prog"] = "blocked"
                ok &= self._refused(r)
            else:
                f["prog"] = "landed"
                landed = self._landed(r, a)
                ok &= landed
                self.landed_progs += int(landed)
            if r["diff"] and not diff_is_exactly(r["diff"], a):
                f["diff_detail"] = diff_log(r["diff"])

        # Step 6: shadow write of the staged value with one bit the shadow lacks.
        if shadow_bit is None:
            f["shadow_wr"] = "na"
        else:
            wk, b = shadow_bit["word"], shadow_bit["bit"]
            resp = await self._wr(shadow_addr(name, wk), staged[wk] | (1 << b), shadow=True)
            exp = list(staged)
            if not wl:
                exp[wk] |= 1 << b
            after = self._probe(name)
            f["shadow_wr"] = "blocked" if wl else "or"
            f["shadow_exp"] = _hexw(exp)
            f["shadow_got"] = _hexw(after)
            f["wr_resp"] = resp
            ok &= after == exp
            if not wl:
                self.or_writes += int(after == exp)
            else:
                self.blocked_writes += 1
        return {"ok": ok, "fields": f}

    def _reset_twin_counts(self) -> None:
        self.accepted_reads = 0
        self.landed_progs = 0
        self.or_writes = 0
        self.blocked_writes = 0
        self.blocked_reqs = {"read": 0, "program": 0}
        self.live_reqs: dict[str, list[PulseCount]] = {"read": [], "program": []}

    async def _lock_leg(self) -> None:
        leg = self.plan.leg
        target = leg["target"]
        layout = leg["layout"]
        neighbours = sorted(n for n in (target - 1, target + 1) if 1 <= n <= 40)
        self._reset_twin_counts()
        blocked_reads = blocked_progs = 0
        for slot in leg["slot_order"]:
            kind = layout.get(slot, "none")
            name = LOCK_SLOT_FIELD[slot]
            res = await self._cell(
                slot,
                kind,
                read_bit=leg["read_bits"].get(slot),
                prog_bit=leg["program_bits"].get(slot),
                shadow_bit=leg["shadow_write_bits"].get(name),
            )
            blocked_reads += int(slot in leg["read_bits"] and kind in _KIND_R)
            blocked_progs += int(slot in leg["program_bits"] and kind in _KIND_W)
            self.chk.ok("LOCK-CELL", res["ok"], target=target, **res["fields"])
        self.chk.ctrl(
            "LOCK-CELL-RD-TWIN",
            self.accepted_reads >= 1,
            target=target,
            neighbours=neighbours,
            accepted=self.accepted_reads,
            blocked=blocked_reads,
        )
        self.chk.ctrl(
            "LOCK-CELL-PROG-TWIN",
            self.landed_progs >= 1,
            target=target,
            neighbours=neighbours,
            landed_with_shim_cmd=self.landed_progs,
            blocked=blocked_progs,
        )
        self._guard_live_ctrl()
        if self.blocked_writes:
            self.chk.ctrl(
                "LOCK-CELL-WR-TWIN",
                self.or_writes >= 1,
                target=target,
                or_writes=self.or_writes,
                blocked=self.blocked_writes,
            )

    async def _single_bit(self) -> None:
        leg = self.plan.leg
        slot, lk, twin = leg["slot"], leg["lock_kind"], leg["twin_slot"]
        name = LOCK_SLOT_FIELD[slot]
        own_bit = {"field": name, "word": 0, "bit": 0, "addr": bit_address(name, 0, 0)}
        self._reset_twin_counts()
        if lk == "read":
            res = await self._cell(slot, "read", read_bit=own_bit, prog_bit=None, shadow_bit=None)
            tw = await self._cell(
                twin, "none", read_bit=leg["twin_bit"], prog_bit=None, shadow_bit=None
            )
            twin_ok = self.accepted_reads >= 1
        else:
            res = await self._cell(
                slot, "write", read_bit=None, prog_bit=own_bit, shadow_bit=None, fd_read=False
            )
            tw = await self._cell(
                twin,
                "none",
                read_bit=None,
                prog_bit=leg["twin_bit"],
                shadow_bit=None,
                fd_read=False,
            )
            twin_ok = self.landed_progs >= 1
        self.chk.ok("LOCK-CELL", res["ok"], image="single_bit", **res["fields"])
        self.chk.ok("LOCK-CELL", tw["ok"], image="single_bit", role="twin", **tw["fields"])
        self.chk.ctrl("LOCK-CELL-SINGLE-TWIN", twin_ok, slot=slot, kind=lk, twin=twin)
        self._guard_live_ctrl()

    # --- exempt cell (entry step 8) ---------------------------------------------
    async def _exempt(self) -> None:
        leg = self.plan.leg
        img = self.plan.image
        got: dict[str, tuple[list[int], int]] = {}
        for name in ("LC_STATE", "LOCKS", "LOCKS_SPARE"):
            got[name] = await self._fd_words(name)
        # Controls of the exempt reads: a blocked request on CLASS_KEY (read-lock burned)
        # and an accepted request on LOCKS (no lock slot).
        close_graded_window(self.logger)
        ck = await self._read_if(leg["class_key_bit"]["addr"])
        lk = await self._read_if(leg["locks_bit"]["addr"])
        ctl_rl = (
            ck["pre_req_err"] == 0
            and ck["req_err"] == 1
            and ck["clr_req_err"] == 0
            and ck["busy"] == 0
        )
        ctl_twin = lk["busy"] == 0 and lk["done"] == 1 and lk["status"] == 0 and lk["req_err"] == 0
        self.chk.ctrl(
            "LOCK-EXEMPT-RL",
            ctl_rl,
            field="CLASS_KEY",
            bit_addr=leg["class_key_bit"]["addr"],
            pre_req_err=ck["pre_req_err"],
            req_err=ck["req_err"],
            clr_req_err=ck["clr_req_err"],
            busy=ck["busy"],
        )
        self.chk.ctrl(
            "LOCK-EXEMPT-TWIN",
            ctl_twin,
            field="LOCKS",
            bit_addr=leg["locks_bit"]["addr"],
            done=lk["done"],
            status=lk["status"],
            req_err=lk["req_err"],
        )
        await self._fd_locked(7, "CLASS_KEY")
        open_graded_window(TEST, self.logger)
        locks_all = all(w == _WORD for w in got["LOCKS"][0])
        self.chk.ctrl("LOCK-EXEMPT-ALL-BURNED", locks_all, locks=_hexw(got["LOCKS"][0]))
        for name in ("LC_STATE", "LOCKS", "LOCKS_SPARE"):
            w0 = field_word(name)
            exp = [img.words[w0 + k] & _WORD for k in range(field_n_words(name))]
            words, bad = got[name]
            self.chk.ok(
                "LOCK-EXEMPT",
                words == exp and bad == 0,
                target=name,
                exp=f"0x{_hexw(exp)}",
                got=f"0x{_hexw(words)}",
                resp=bad,
                ctl_field="CLASS_KEY",
                ctl_req_err=ck["req_err"],
                ctl_twin="LOCKS",
                ctl_twin_done=lk["done"],
                ctl_twin_req_err=lk["req_err"],
            )

    # --- order cell (entry steps 9 to 11) ----------------------------------------
    async def _locks(self) -> int:
        lo = await self._rd32(shadow_addr("LOCKS", 0))
        hi = await self._rd32(shadow_addr("LOCKS", 1))
        return (hi << 32) | lo

    async def _order(self) -> None:
        leg = self.plan.leg
        img = self.plan.image
        slot, perm = leg["slot"], list(leg["permutation"])
        name = LOCK_SLOT_FIELD[slot]
        n = field_n_words(name)
        staged = [img.words[field_word(name) + k] & _WORD for k in range(n)]
        (wa, ba), (wb, bb), (wc, bc) = (tuple(x) for x in leg["bits_abc"])

        # Step 9: control write on a second slot that the cell does not lock.
        close_graded_window(self.logger)
        cslot, cbit = leg["control_slot"], leg["control_bit"]
        cname = LOCK_SLOT_FIELD[cslot]
        cstaged = [img.words[field_word(cname) + k] & _WORD for k in range(field_n_words(cname))]
        cexp = list(cstaged)
        cexp[cbit["word"]] |= 1 << cbit["bit"]
        await self._wr(
            shadow_addr(cname, cbit["word"]),
            cstaged[cbit["word"]] | (1 << cbit["bit"]),
            shadow=True,
        )
        cgot = self._probe(cname)
        self.chk.ctrl(
            "LOCK-ORDER-PATH",
            cgot == cexp,
            field=cname,
            exp=_hexw(cexp),
            got=_hexw(cgot),
        )
        open_graded_window(TEST, self.logger)

        # Step 10: the three actions in the drawn permutation.
        lock_bit = write_lock_bit(slot)
        gold = list(staged)
        locked = False
        ok = True
        trace = []

        async def _write_field(word: int, bit: int) -> None:
            value = list(staged)
            value[word] |= 1 << bit
            for k in range(n):
                await self._wr(shadow_addr(name, k), value[k], shadow=True)

        for action in perm:
            if action == "lock":
                await self._wr(
                    shadow_addr("LOCKS", lock_bit // 32), 1 << (lock_bit % 32), shadow=True
                )
                locked = True
            else:
                word, bit = (wa, ba) if action == "write_a" else (wb, bb)
                await _write_field(word, bit)
                if not locked:
                    gold[word] |= 1 << bit
            shadow = self._probe(name)
            locks = await self._locks()
            locks_exp = (1 << lock_bit) if locked else 0
            step_ok = shadow == gold and locks == locks_exp
            ok &= step_ok
            trace.append(f"{action}:{int(step_ok)}")
            if not step_ok:
                trace.append(f"shadow={_hexw(shadow)}/exp={_hexw(gold)}/locks=0x{locks:016x}")

        # Step 11: a zero write to LOCKS keeps the lock; a third-bit write is blocked.
        await self._wr(shadow_addr("LOCKS", 0), 0, shadow=True)
        await self._wr(shadow_addr("LOCKS", 1), 0, shadow=True)
        locks_after = await self._locks()
        lock_after_zero = (locks_after >> lock_bit) & 1
        before_c = self._probe(name)
        self.chk.ctrl(
            "LOCK-ORDER-THIRD",
            not (before_c[wc] >> bc) & 1,
            field=name,
            bit_c=f"{wc}.{bc}",
            shadow=_hexw(before_c),
        )
        await _write_field(wc, bc)
        final = self._probe(name)
        third = (final[wc] >> bc) & 1
        ok &= lock_after_zero == 1 and locks_after == (1 << lock_bit) and final == gold
        self.chk.ok(
            "LOCK-ORDER",
            ok,
            field=name,
            perm="/".join(perm),
            shadow=f"0x{_hexw(final)}",
            exp=f"0x{_hexw(gold)}",
            lock_after_zero=lock_after_zero,
            third_bit_landed=third,
            locks=f"0x{locks_after:016x}",
            lock_bit=lock_bit,
            bits=f"a={wa}.{ba},b={wb}.{bb},c={wc}.{bc}",
            trace=",".join(trace),
        )

    # --- chain leg (entry steps 12 to 16) -----------------------------------------
    async def _chain(self) -> None:
        leg = self.plan.leg
        p = self.plan
        ref = [w & _WORD for w in p.image.words]
        # Step 12: the first compare of all 256 sensed words with the staged image.
        first = self._probe_all()
        mism = [i for i in range(256) if first[i] != ref[i]]
        self.first_mismatch = len(mism)
        if mism:
            self.chk.ok(
                "PROG-ROUND",
                False,
                round=0,
                step="first_sense",
                mismatched_words=mism[:16],
                n_mismatch=len(mism),
            )

        for k, rnd in enumerate(leg["rounds"], start=1):
            await self._round(k, rnd, ref)

        # Steps 15 and 16: version round, then two resenses.
        vb = leg["version_bit"]
        vname, a = vb["field"], vb["addr"]
        r = await self._program(a, watch=False)
        landed = r["req_err"] == 0 and diff_is_exactly(r["diff"], a)
        ref[field_word(vname) + vb["word"]] |= 1 << vb["bit"]
        set_shadow_golden(self, self.plan.image, words=ref)
        exp = [0] * field_n_words(vname)
        exp[vb["word"]] = 1 << vb["bit"]
        await self._sense("CHK-PROG-VERSION")
        after1, bad1 = await self._fd_words(vname)
        await self._sense("CHK-PROG-VERSION")
        after2, bad2 = await self._fd_words(vname)
        self.chk.ok(
            "PROG-VERSION",
            landed and after1 == exp and after2 == exp and bad1 == 0 and bad2 == 0,
            field="BL1" if vname == "BL1_VERSION" else "BL2",
            bit=leg["version_index"],
            index_class=leg["index_class"],
            req_err=r["req_err"],
            otp_diff=a if diff_is_exactly(r["diff"], a) else diff_log(r["diff"]),
            exp=f"0x{_hexw(exp)}",
            word_after_sense=f"0x{_hexw(after1)}",
            word_after_resense2=f"0x{_hexw(after2)}",
        )

    async def _round(self, k: int, rnd: dict, ref: list[int]) -> None:
        """Step 13 (program, unchanged shadow) and step 14 (resense, model compare)."""
        name, a, rb = rnd["field"], rnd["addr"], rnd["read_back"]
        wi = field_word(name) + rnd["word"]
        old = ref[wi]
        pre = await self._rd32(shadow_addr(name, rnd["word"]))
        r = await self._program(a, read_back=rb, watch=False)
        after_prog = await self._rd32(shadow_addr(name, rnd["word"]))
        prog_ok = r["req_err"] == 0 and diff_is_exactly(r["diff"], a)
        new = old | (1 << rnd["bit"])
        ref[wi] = new
        # The reference of the next round is the model: this reference OR this bit.
        set_shadow_golden(self, self.plan.image, words=ref)
        await self._sense("CHK-PROG-ROUND")
        sensed = self._probe_all()
        mism = [i for i in range(256) if sensed[i] != ref[i]]
        fd = await self._rd32(shadow_addr(name, rnd["word"]))
        sip = ref[field_word("SIP_DIS")] | (ref[field_word("SIP_DIS") + 1] << 32)
        sys_ = ref[field_word("SYS_DIS")] | (ref[field_word("SYS_DIS") + 1] << 32)
        row = feat_ctrl_profile(self.plan.lc_raw, sip, sys_)
        feat = await self.fd.feat_ctrl()
        ok = (
            prog_ok
            and self.first_mismatch == 0
            and pre == old
            and after_prog == old
            and not mism
            and sensed[wi] == new
            and fd == new
            and feat == row.value
        )
        self.chk.ok(
            "PROG-ROUND",
            ok,
            round=k,
            field=name,
            bit_addr=a,
            rb=rb,
            otp_diff=a if diff_is_exactly(r["diff"], a) else diff_log(r["diff"]),
            req_err=r["req_err"],
            prog_status=r["prog_status"],
            shadow_pre=f"0x{pre:08x}",
            shadow_after_prog=f"0x{after_prog:08x}",
            shadow_after_sense=f"0x{sensed[wi]:08x}",
            fd_after_sense=f"0x{fd:08x}",
            exp_after_sense=f"0x{new:08x}",
            n_mismatch=len(mism),
            mismatched_words=mism[:16],
            first_sense_mismatch=self.first_mismatch,
            feat_exp=f"0x{row.value:016x}",
            feat_got=f"0x{feat:016x}",
            profile=row.log(),
        )

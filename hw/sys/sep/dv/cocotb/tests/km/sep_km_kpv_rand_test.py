# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KPV slot states, CTRL write rules, trailing words, neighbours, KPV scrambler resets, wipe and cipher.

no_cpu (``lsu_stub_all_live``) / ``+skip_fuse_sense`` / ``+km_rom_hex=km_rom_poke.parhex``.
The SRAM scrambler stays off. RAND-REP (slots, words, state order, values) and
RANDCFG (KPV scrambler key, lock timing, wipe hold width W).

Vehicle. The POKE KM image (``tests/km_fw/km_rom_poke.S``) runs the KM bus
operations that the host posts and reports what the DUT returned in KM SRAM
words 0 to 97 (``km_sram_probe_o``). The KM CPU does not see the AXI response,
so each reporting operation clears IRQ_STATUS.AXI_SLVERR and AXI_DECERR before
the access and reports them after it as ``slv`` and ``dec``. Every value that a
check compares is a POKE readback of the DUT, a host readback of
``SEP_STATUS``, or a snapshot of the KM-KPV tap (``km_kpv_words_o``).

Specification. ``hw/ip/key_manager/doc/architecture.adoc``, sections "Key and
Policy Vault (KPV)", "KPV Scrambling", "Wipe State" and "Reset Conditioning";
``hw/ip/key_manager/regs/gen/adoc/km_kpv.adoc``, sections "KEY_ENTRY[64].WORD[16]",
"CTRL[64]", "KPV_SCRAMBLER_CTRL"; ``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``,
section "KM_WIPE_CTRL"; ``hw/ip/scrambler/doc/architecture.adoc``, section
"Data Scrambling Algorithm". Addresses and field masks come from the generated
RDL header (``sep_km_kpv_rand_model.py``).

Checkers:
  CHK-KPV-ADDR     each cell of the address walk (words 0, 15 and a drawn word
                   of 12 drawn slots, and word 0 of each next slot) reads its own
                   value, CTRL of each drawn slot reads 0, and the sweep over all
                   64 slots reads back word 0 with CTRL 0. Control: the word of
                   the next slot holds another value.
  CHK-KPV-CTRLW    CTRL fields are write-one-to-set: a write of 0 sets nothing
                   on an erased slot and keeps a set lock, a write of F sets F
                   only (seal gives 0x9, an erase ends at 0), three more writes of
                   F keep the value, a second field G adds its bit. Control:
                   CTRL reads 0 after the erase that starts each sequence.
  CHK-KPV-STATE    W: read returns the record, no SLVERR. R: write completes
                   with no SLVERR. WR: write and read refused with SLVERR, read
                   0. Sealed: write refused with SLVERR, read returns the
                   record. Control: the free-state write and read of the slot.
  CHK-KPV-ERASE    the erase of an R or a WR slot clears CTRL, the 16 reads
                   complete with no SLVERR and 16 new values read back.
  CHK-KPV-RETIRED  a sealed slot that is erased reads CTRL 0xB and refuses read
                   (0, SLVERR) and write (SLVERR), before and after a second erase.
  CHK-KPV-RACE     erase and seal in back-to-back writes retire the slot when
                   the erase bit reads 1 right after the seal write. A try that
                   shows the erase bit at 0 is logged and not graded. Control:
                   erase, wait, seal gives 0x9.
  CHK-KPV-TRAIL    after an erase, a write of k words keeps words k to 15; with
                   lock_use set they read 0 with SLVERR. Control: words 0 to
                   k - 1 read the written values.
  CHK-KPV-NEIGH    no op of the CTRL-rule, state-walk, race and trailing-word
                   steps changes CTRL or a word of the slots next to its slot.
                   Control: CTRL of the slot itself changes in each sequence.
  CHK-KPV-RESET    CTRL of the 12 drawn slots reads 0 after the power-up cold
                   reset, after a warm reset (SW_RESET_N bit 0) that follows
                   locked, sealed and retired slots, and after a cold reset
                   (rst_ni) that follows CTRL 0x1 on every drawn slot.
  CHK-KPV-NOX      VCS only: no compared KPV read and no KM-KPV snapshot holds
                   an X or Z bit. On Verilator (two-state) the leaf logs a LOG line.
  CHK-KSCR-RST     a warm reset keeps the KPV scrambler enable, lock and key (the
                   24 cells still read D); a cold reset clears KPV_SCRAMBLER_CTRL.
                   Controls: the enable-0 twin cells and the enable-1 cells read D.
  CHK-WIPE-KPV     a KM_WIPE_CTRL rising edge clears all 1024 KPV words, all 64
                   CTRL, the KPV scrambler key, enable and lock, sets
                   IRQ_STATUS.WIPE_STATE, and the KM CPU runs the next list.
                   Control: the vault before the wipe is non-zero.
  CHK-WIPE-SCOPE   the wipe keeps the 8 SRAM words, the mailbox word
                   (SEP_STATUS depth 1) and the HMAC key_valid. Control: each
                   witness is non-zero before the wipe.
  CHK-WIPE-EDGE2   a held level and a write of 1 while high set no second
                   WIPE_STATE over 200 host clocks; a 0-then-1 edge sets it again.
                   Control: the first rising edge sets it.
  CHK-KSCR-CIPHER  with the scrambler enabled, two writes of d1 and d2 to one
                   cell change exactly one stored word, and
                   ibox(iplayer(S1)) ^ ibox(iplayer(S2)) == d1 ^ d2 in 32 draws
                   that cover every nibble value in each of the 8 lanes.
  CHK-NONVAC       every control of a "no effect" check above was seen.

Log only: OBS-BLOCKED CHK-KPV-ERASE-RET and ``OBS-KPV-ERASE-RET LOG`` (the
erase fill is not stated), ``OBS-KPV-ERASE-FILL LOG``, ``OBS-KSCR-COLD LOG``
(KPV cells after a cold reset are not stated), ``OBS-KPV-RACE-REDRAW`` and
``OBS-KPV-RACE``, ``LOG err_o`` (PIC vector bit 30 at the wipe) and the
second-key control of the cipher leg.

Not sent: a key access during an erase (not defined), a KPV_SCRAMBLER_KEY read
after the lock (not stated).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env import sep_km_poke as kp
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_reg_meta import SEP_CPU_CTRL
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import agg_from_pic
from km import sep_km_kpv_rand_model as m
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import KM_STATUS_INBOUND_DEPTH_LSB, KM_STATUS_INBOUND_DEPTH_MASK
from seq_lib.sep_km_poke_seq import SepKmPoke
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SW_RESET_N_RESET_DEFAULT, SepSwReset

TEST = "sep_km_kpv_rand_test"

# Bounds and test parameters (clk_i cycles or KM loads).
_SEP_RESET_BOUND = 20_000
_ERASE_POLL = 4096
_LEVEL_HOLD_CLKS = 200
# The held-level poll makes _LEVEL_POLL_LOADS IRQ_STATUS loads. The window from
# the second write of 1 to the sync after the poll must last at least
# _LEVEL_WINDOW_MULT x _LEVEL_HOLD_CLKS, so that the poll alone spans more than
# _LEVEL_HOLD_CLKS clocks after the report reads and the sync are taken off.
_LEVEL_POLL_LOADS = 512
_LEVEL_WINDOW_MULT = 4
_WIPE_WINDOW_DELAY = 4000
_WIPE_WINDOW_POLL = 16
_WIPE_WINDOW_BOUND = 400_000

_KM_WIPE_CTRL = SEP_CPU_CTRL.addr("KM_WIPE_CTRL")
_KM_WIPE_BIT = SEP_CPU_CTRL.field_mask("KM_WIPE_CTRL", "wipe_state")
_PIC_KM_UNREC = agg_from_pic("KM unrecoverable error")
_KM_BIT = 1 << SW_RESET_N_BIT["km"]

_STATE_BITS = {"W": m.LOCK_WRITE, "R": m.LOCK_USE, "WR": m.LOCK_WRITE | m.LOCK_USE}
# CTRL after a write of one field alone to an erased slot (km_kpv.adoc, "CTRL[64]").
_SET_ALONE = {m.LOCK_WRITE: m.LOCK_WRITE, m.LOCK_USE: m.LOCK_USE, m.ERASE: 0, m.SEAL: m.SEALED}

_REQUIRED = (
    "CHK-KPV-ADDR",
    "CHK-KPV-CTRLW",
    "CHK-KPV-STATE",
    "CHK-KPV-ERASE",
    "CHK-KPV-RETIRED",
    "CHK-KPV-TRAIL",
    "CHK-KPV-NEIGH",
    "CHK-KPV-RESET",
    "CHK-KSCR-RST",
    "CHK-WIPE-KPV",
    "CHK-WIPE-SCOPE",
    "CHK-WIPE-EDGE2",
    "CHK-KSCR-CIPHER",
    "CHK-NONVAC",
)

_KPV_READ_OPS = (kp.OP_RD, kp.OP_RDBLK, kp.OP_RDLOOP, kp.OP_POLL)


def _h(v: int) -> str:
    return f"0x{v:08x}"


def _erase_ops(slot: int) -> list[kp.PokeOp]:
    """Erase ``slot`` and poll (bounded) until the erase bit reads 0."""
    a = m.ctrl_addr(slot)
    return [kp.wr(a, m.ERASE), kp.poll(a, m.ERASE, 0, _ERASE_POLL)]


@dataclass
class _Watch:
    """Neighbour snapshots around every op on one slot."""

    slot: int
    snaps: list[tuple] = field(default_factory=list)
    own: list[int] = field(default_factory=list)
    ops: int = 0

    def snap_ops(self) -> list[kp.PokeOp]:
        ops = [kp.rd(m.ctrl_addr(self.slot))]
        for n in m.neighbours(self.slot):
            ops += [kp.rd(m.ctrl_addr(n)), kp.rd(m.word_addr(n, 0))]
        return ops


@pyuvm.test()
class sep_km_kpv_rand_test(sep_base_test):
    """KPV slot-state matrix, CTRL rules, neighbours, scrambler across resets, wipe and cipher."""

    required_evidence = _REQUIRED

    # --- transport ---------------------------------------------------------------

    def _check_result(self, r: kp.PokeResult) -> None:
        addr = r.op.words[1] if len(r.op.words) > 1 else None
        kpv_read = (
            r.op.code in _KPV_READ_OPS and addr is not None and m.KPV_BASE <= addr < m.KPV_DATA_END
        )
        if kpv_read:
            self.compared += 1
            if not r.known:
                self.x_words += 1
        elif not r.known:
            raise AssertionError(f"POKE op {r.index} ({r.op.name}) returned an unknown bit")

    async def _run(self, ops, **kw) -> list[kp.PokeResult]:
        res = await self.poke.run(ops, allow_unknown=True, **kw)
        for r in res:
            self._check_result(r)
        return res

    async def _run_groups(self, groups: list[list[kp.PokeOp]]) -> list[list[kp.PokeResult]]:
        """Run op groups packed into as few lists as fit; a group never splits."""
        out: list[list[kp.PokeResult]] = []
        batch: list[list[kp.PokeOp]] = []
        words = slots = 0

        async def flush() -> None:
            if not batch:
                return
            res = await self._run([op for g in batch for op in g])
            i = 0
            for g in batch:
                out.append(res[i : i + len(g)])
                i += len(g)
            batch.clear()

        for g in groups:
            gw, gs = kp.list_words(g), kp.list_slots(g)
            if words + gw > kp.BUF_WORDS or slots + gs > kp.N_SLOTS:
                await flush()
                words = slots = 0
            batch.append(g)
            words += gw
            slots += gs
        await flush()
        return out

    @staticmethod
    def _erase_done(res: list[kp.PokeResult], slot: int) -> None:
        poll = res[-1]
        if poll.data[0] & m.ERASE:
            raise AssertionError(
                f"erase of slot {slot} did not end within {poll.data[1]} loads: "
                f"CTRL={_h(poll.data[0])} (bounded wait expired)"
            )

    def _ctrl(self, v: int) -> int:
        self.rsvd["CTRL"] |= v & ~m.CTRL_FIELDS & m.WORD
        return v & m.CTRL_FIELDS

    def _scr(self, v: int) -> int:
        self.rsvd["KPV_SCRAMBLER_CTRL"] |= v & ~m.SCR_FIELDS & m.WORD
        return v & m.SCR_FIELDS

    def _irq(self, v: int) -> int:
        self.rsvd["IRQ_STATUS"] |= v & ~m.IRQ_FIELDS & m.WORD
        return v & m.IRQ_WIPE

    def _draw(self, name: str, value) -> None:
        self.logger.info("DRAW %s=%s", name, value)

    async def _watched(self, w: _Watch, groups: list[list[kp.PokeOp]]) -> list[list[kp.PokeResult]]:
        """Run ``groups`` on slot ``w.slot`` with a neighbour snapshot before and after each."""
        seq: list[list[kp.PokeOp]] = []
        for g in groups:
            seq.append(w.snap_ops())
            seq.append(g)
        seq.append(w.snap_ops())
        res = await self._run_groups(seq)
        for k in range(0, len(res), 2):
            snap = res[k]
            w.own.append(self._ctrl(snap[0].value))
            w.snaps.append(
                tuple(
                    (self._ctrl(snap[1 + 2 * j].value), snap[2 + 2 * j].value)
                    for j in range(len(m.neighbours(w.slot)))
                )
            )
        w.ops += len(groups)
        if not any(x is w for x in self.watches):
            self.watches.append(w)
        return [res[k] for k in range(1, len(res), 2)]

    def _snapshot(self) -> tuple[list[int], int]:
        """KM-KPV tap: the 1024 stored words and the number of X or Z bits."""
        sig = cocotb.top.km_kpv_words_o
        value = sig.value
        x_bits = 0
        if not isinstance(value, int):
            bits = getattr(value, "binstr", None)
            if bits is None:
                bits = str(value)
            x_bits = sum(1 for c in bits if c not in "01")
        whole = self.rd(sig, allow_unknown=True)
        return [(whole >> (32 * i)) & m.WORD for i in range(m.N_KPV_WORDS)], x_bits

    async def _wipe_ctrl(self, value: int) -> None:
        seq = SepAxiAccessSeq(
            "km_wipe_ctrl", op=SepAxiOp.WRITE, addr=_KM_WIPE_CTRL, wdata=value, size=2
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM_WIPE_CTRL write {_h(value)} not OKAY")

    async def _mbox_depth(self) -> int:
        st = await self.poke.mbox.read_status()
        return (st >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(_SEP_RESET_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(f"dbg_sep_reset_n_o did not read 1 within {_SEP_RESET_BOUND} clocks")

    async def _count_clks(self) -> None:
        while self._clk_run:
            await RisingEdge(cocotb.top.clk_i)
            self._clk_count += 1

    def _gate(self, on: bool) -> None:
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    # --- scenario ----------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.rng = SepSeededRng(seed)
        self.plan = m.draw_plan(self.rng)
        for name, value in self.plan.draws:
            self._draw(name, value)
        self.chk = SepChkLog(self, TEST, seed)
        self.vcs = "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        self.compared = 0
        self.x_words = 0
        self.x_snap_bits = 0
        self.rsvd = {"CTRL": 0, "KPV_SCRAMBLER_CTRL": 0, "IRQ_STATUS": 0}
        self.rsvd_mask = {
            "CTRL": ~m.CTRL_FIELDS & m.WORD,
            "KPV_SCRAMBLER_CTRL": ~m.SCR_FIELDS & m.WORD,
            "IRQ_STATUS": ~m.IRQ_FIELDS & m.WORD,
        }
        self.watches: list[_Watch] = []
        self.controls: dict[str, bool] = {}

        # Step 1: cold reset, KM release, start marker.
        self._gate(False)
        await self.bring_up_no_cpu()
        await self._wait_sep_reset_n()
        self.swrst = SepSwReset(self)
        self.poke = SepKmPoke(self)
        await self.swrst.release("km")
        await self.poke.wait_boot()
        self._gate(True)

        await self._step_power_up()
        await self._step_define()
        await self._step_addr_walk_and_sweep()
        await self._step_ctrl_rules()
        await self._step_state_walk()
        await self._step_race()
        await self._step_trail()
        self._grade_neighbours()
        await self._step_scrambler()
        await self._step_warm()
        await self._step_cold()
        await self._step_wipe()
        await self._step_level_and_edge()
        await self._step_cipher()
        await self._step_end()
        self.chk.finish()

    # Step 2.
    async def _step_power_up(self) -> None:
        res = await self._run([kp.rd(m.ctrl_addr(s)) for s in self.plan.drawn])
        ctrl = [self._ctrl(r.value) for r in res]
        self.chk.ok(
            "KPV-RESET",
            all(c == 0 for c in ctrl),
            kind="cold",
            point="power_up",
            slots=len(ctrl),
            set_before=0,
            ctrl=_h(max(ctrl)),
        )

    # Step 3.
    async def _step_define(self) -> None:
        slots = sorted({n for s in self.plan.drawn for n in (s, *m.neighbours(s))})
        res = await self._run_groups([_erase_ops(s) for s in slots])
        for s, r in zip(slots, res, strict=True):
            self._erase_done(r, s)
        self.logger.info("LOG define erased_slots=%d", len(slots))

    # Steps 4 and 5.
    async def _step_addr_walk_and_sweep(self) -> None:
        p = self.plan
        cells = list(p.cells.items())
        groups = [[kp.wr(m.word_addr(s, w), v)] for (s, w), v in cells]
        groups += [[kp.rd(m.word_addr(s, w))] for (s, w), _ in cells]
        groups += [[kp.rd(m.ctrl_addr(s))] for s in p.drawn]
        res = await self._run_groups(groups)
        n = len(cells)
        reads = {cells[i][0]: res[n + i][0].value for i in range(n)}
        ctrl = [self._ctrl(res[2 * n + i][0].value) for i in range(len(p.drawn))]
        alias = sum(1 for (cell, v) in cells if reads[cell] != v)
        ctrl_bad = sum(1 for c in ctrl if c != 0)
        twin = all(reads[(s + 1, 0)] != reads[(s, 0)] for s in p.drawn if s + 1 < m.N_SLOTS)
        self.chk.ctrl("KPV-ADDR-NEXT", twin, pairs=sum(1 for s in p.drawn if s + 1 < m.N_SLOTS))

        sweep_groups = []
        for s in p.sweep_order:
            sweep_groups.append(
                [
                    *_erase_ops(s),
                    kp.wr(m.word_addr(s, 0), p.sweep_values[s]),
                    kp.rd(m.word_addr(s, 0)),
                    kp.rd(m.ctrl_addr(s)),
                ]
            )
        sres = await self._run_groups(sweep_groups)
        sweep_ok = 0
        for s, r in zip(p.sweep_order, sres, strict=True):
            self._erase_done(r[:2], s)
            if r[3].value == p.sweep_values[s] and self._ctrl(r[4].value) == 0:
                sweep_ok += 1
        self.chk.ok(
            "KPV-ADDR",
            alias == 0 and ctrl_bad == 0 and sweep_ok == m.N_SLOTS,
            cells=n,
            alias=alias,
            ctrl_nonzero=ctrl_bad,
            sweep_slots=len(p.sweep_order),
            sweep_ok=sweep_ok,
        )

    # Step 6.
    async def _step_ctrl_rules(self) -> None:
        p = self.plan
        counts = {"write0_free": 0, "write0_keeps": 0, "set_only": 0, "triple_same": 0, "or_ok": 0}
        start_zero = True
        for f, s in p.ctrlw_slots.items():
            g = p.ctrlw_g[f]
            a = m.ctrl_addr(s)
            wf = [kp.wr(a, f)] + ([kp.poll(a, m.ERASE, 0, _ERASE_POLL)] if f == m.ERASE else [])
            lock = f != m.ERASE
            # The CTRL reads in order: start, after write 0, after F, [after write 0
            # for a lock field], after the second, third and fourth F, after G. The
            # last three F writes have only reads between them, so they are three identical
            # writes in a row.
            groups = [_erase_ops(s), [kp.rd(a)], [kp.wr(a, 0)], [kp.rd(a)], wf, [kp.rd(a)]]
            if lock:
                groups += [[kp.wr(a, 0)], [kp.rd(a)]]
            groups += [wf, [kp.rd(a)], wf, [kp.rd(a)], wf, [kp.rd(a)], [kp.wr(a, g)], [kp.rd(a)]]
            res = await self._watched(_Watch(s), groups)
            self._erase_done(res[0], s)
            vals = []
            for grp, r in zip(groups, res, strict=True):
                if grp is wf and f == m.ERASE:
                    self._erase_done(r, s)
                if grp[0].code == kp.OP_RD:
                    vals.append(self._ctrl(r[0].value))
            c_start, c_w0, c_set = vals[0], vals[1], vals[2]
            rest = vals[3:]
            c_keep = rest.pop(0) if lock else None
            c_r2, c_r3, c_r4, c_or = rest
            exp_set = _SET_ALONE[f]
            exp_or = _SET_ALONE[g] if f == m.ERASE else exp_set | _SET_ALONE[g]
            start_zero &= c_start == 0
            counts["write0_free"] += c_w0 == 0
            counts["set_only"] += c_set == exp_set
            if lock:
                counts["write0_keeps"] += c_keep == exp_set
            counts["triple_same"] += c_r2 == exp_set and c_r3 == exp_set and c_r4 == exp_set
            counts["or_ok"] += c_or == exp_or
            self.logger.info(
                "LOG ctrlw slot=%d field=%s g=%s start=%s w0=%s set=%s keep=%s r2=%s r3=%s r4=%s "
                "or=%s "
                "exp_set=%s exp_or=%s",
                s,
                m.FIELD_NAME[f],
                m.FIELD_NAME[g],
                _h(c_start),
                _h(c_w0),
                _h(c_set),
                "-" if c_keep is None else _h(c_keep),
                _h(c_r2),
                _h(c_r3),
                _h(c_r4),
                _h(c_or),
                _h(exp_set),
                _h(exp_or),
            )
        self.controls["ctrlw_start_zero"] = self.chk.ctrl("KPV-CTRLW-START", start_zero)
        self.chk.ok(
            "KPV-CTRLW",
            counts["write0_free"] == 4
            and counts["write0_keeps"] == 3
            and counts["set_only"] == 4
            and counts["triple_same"] == 4
            and counts["or_ok"] == 4,
            slots=list(p.ctrlw_slots.values()),
            **counts,
        )

    # Step 7.
    async def _step_state_walk(self) -> None:
        p = self.plan
        twin_ok = True
        for s in p.walk_slots:
            wk = p.walk_word[s]
            wa, ca = m.word_addr(s, wk), m.ctrl_addr(s)
            base = m.word_addr(s, 0)
            w = _Watch(s)

            vf = m.nz_word(self.rng)
            self._draw(f"walk_free_value_s{s}", _h(vf))
            fr = await self._watched(w, [[kp.wr(wa, vf)], [kp.rd(wa)]])
            free_twin = fr[0][0].slv == 0 and fr[1][0].value == vf and fr[1][0].slv == 0
            twin_ok &= free_twin
            self.logger.info(
                "LOG state slot=%d state=free wr_slv=%d rd=%s rd_slv=%d control=1",
                s,
                fr[0][0].slv,
                _h(fr[1][0].value),
                fr[1][0].slv,
            )

            for st in p.walk_order[s]:
                rec = m.distinct_words(self.rng, m.N_WORDS)
                vne = m.nz_word(self.rng, (rec[wk],))
                self._draw(f"walk_{st}_s{s}", f"rec0={_h(rec[0])},wr={_h(vne)}")
                groups = [
                    [kp.wrblk(base, rec)],
                    [kp.wr(ca, _STATE_BITS[st])],
                    [kp.wr(wa, vne)],
                    [kp.rd(wa)],
                    [kp.wr(ca, 0)],
                    _erase_ops(s),
                ]
                if st in ("R", "WR"):
                    new = [m.nz_word(self.rng, (rec[i],)) for i in range(m.N_WORDS)]
                    self._draw(f"walk_new_{st}_s{s}", _h(new[0]))
                    groups += [
                        [kp.rdblk(base, m.N_WORDS)],
                        [kp.rd(ca)],
                        [kp.wrblk(base, new)],
                        [kp.rdblk(base, m.N_WORDS)],
                    ]
                res = await self._watched(w, groups)
                self._erase_done(res[5], s)
                wr_slv, rd, rd_slv = res[2][0].slv, res[3][0].value, res[3][0].slv
                if st == "W":
                    graded = rd == rec[wk] and rd_slv == 0
                    self.chk.ctrl("KPV-STATE-W-WRITE", wr_slv == 1, slot=s, wr_slv=wr_slv)
                elif st == "R":
                    graded = wr_slv == 0
                    self.chk.ctrl(
                        "KPV-STATE-R-READ",
                        rd == 0 and rd_slv == 1,
                        slot=s,
                        rd=_h(rd),
                        rd_slv=rd_slv,
                    )
                else:
                    graded = wr_slv == 1 and rd == 0 and rd_slv == 1
                self.chk.ok(
                    "KPV-STATE", graded, slot=s, state=st, wr_slv=wr_slv, rd=_h(rd), rd_slv=rd_slv
                )
                if st in ("R", "WR"):
                    after = res[6]
                    ctrl = self._ctrl(res[7][0].value)
                    slv_bits = [f.slv for f in after[0].flags]
                    rewrite = res[9][0].data
                    rewrite_ok = sum(1 for i in range(m.N_WORDS) if rewrite[i] == new[i])
                    same = sum(1 for i in range(m.N_WORDS) if after[0].data[i] == rec[i])
                    self.chk.ok(
                        "KPV-ERASE",
                        ctrl == 0 and not any(slv_bits) and rewrite_ok == m.N_WORDS,
                        slot=s,
                        state=st,
                        ctrl=f"0x{ctrl:x}",
                        rd_slv=int(any(slv_bits)),
                        rewrite_ok=rewrite_ok,
                    )
                    self.logger.info(
                        "OBS-KPV-ERASE-FILL LOG slot=%d state=%s words_same=%d", s, st, same
                    )

            # Sealed state, then the erase that retires the slot.
            rec = m.distinct_words(self.rng, m.N_WORDS)
            vne = m.nz_word(self.rng, (rec[wk],))
            self._draw(f"walk_sealed_s{s}", f"rec0={_h(rec[0])},wr={_h(vne)}")
            groups = [
                [kp.wrblk(base, rec)],
                [kp.wr(ca, m.SEAL)],
                [kp.rd(ca)],
                [kp.wr(wa, vne)],
                [kp.rd(wa)],
                [kp.wr(ca, 0)],
                _erase_ops(s),
                [kp.rd(ca)],
            ]
            res = await self._watched(w, groups)
            self._erase_done(res[6], s)
            sealed_ctrl = self._ctrl(res[2][0].value)
            self.chk.ctrl("KPV-STATE-SEAL", sealed_ctrl == m.SEALED, slot=s, ctrl=_h(sealed_ctrl))
            wr_slv, rd, rd_slv = res[3][0].slv, res[4][0].value, res[4][0].slv
            self.chk.ok(
                "KPV-STATE",
                wr_slv == 1 and rd == rec[wk] and rd_slv == 0,
                slot=s,
                state="sealed",
                wr_slv=wr_slv,
                rd=_h(rd),
                rd_slv=rd_slv,
            )
            retired_ctrl = self._ctrl(res[7][0].value)
            stored, xb = self._snapshot()
            self.x_snap_bits += xb
            words = stored[s * m.N_WORDS : (s + 1) * m.N_WORDS]
            self.chk.blocked("KPV-ERASE-RET", "erase_fill_not_stated")
            self.logger.info(
                "OBS-KPV-ERASE-RET LOG slot=%d state=sealed words_same=%d stored=%s",
                s,
                sum(1 for i in range(m.N_WORDS) if words[i] == rec[i]),
                [_h(v) for v in words],
            )

            # Retired state.
            vr = m.nz_word(self.rng)
            self._draw(f"walk_retired_value_s{s}", _h(vr))
            groups = [
                [kp.rd(wa)],
                [kp.wr(wa, vr)],
                _erase_ops(s),
                [kp.rd(wa)],
                [kp.wr(wa, vr)],
                [kp.rd(ca)],
            ]
            res = await self._watched(w, groups)
            self._erase_done(res[2], s)
            r1, w1, r2, w2 = res[0][0], res[1][0], res[3][0], res[4][0]
            final = self._ctrl(res[5][0].value)
            self.chk.ctrl("KPV-RETIRED-REERASE", final == m.RETIRED, slot=s, ctrl=_h(final))
            self.chk.ok(
                "KPV-RETIRED",
                retired_ctrl == m.RETIRED
                and r1.value == 0
                and r1.slv == 1
                and w1.slv == 1
                and r2.value == 0
                and r2.slv == 1
                and w2.slv == 1,
                slot=s,
                ctrl=f"0x{retired_ctrl:X}",
                rd=_h(r1.value),
                rd_slv=r1.slv,
                wr_dropped=w1.slv,
                wr_slv=w1.slv,
                after_reerase_rd=_h(r2.value),
                after_reerase_rd_slv=r2.slv,
                after_reerase_wr_dropped=w2.slv,
                ctrl_control=f"0x{final:X}",
            )
        self.controls["state_free_twin"] = self.chk.ctrl("KPV-STATE-TWIN", twin_ok)

    # Step 8.
    async def _step_race(self) -> None:
        p = self.plan
        tries = [p.race_slot, *p.race_extra[:4]]
        graded = None
        n = 0
        for s in tries:
            n += 1
            a = m.ctrl_addr(s)
            res = await self._watched(
                _Watch(s),
                [
                    [kp.wr2(a, m.ERASE, a, m.SEAL, readback=True)],
                    [kp.poll(a, m.ERASE, 0, _ERASE_POLL)],
                    [kp.rd(a)],
                ],
            )
            self._erase_done(res[1], s)
            after_seal = self._ctrl(res[0][0].value)
            final = self._ctrl(res[2][0].value)
            if after_seal & m.ERASE:
                graded = (s, after_seal, final)
                break
            self.logger.info(
                "OBS-KPV-RACE-REDRAW slot=%d case=finished ctrl_after_seal=%s ctrl_final=%s",
                s,
                _h(after_seal),
                _h(final),
            )
        self.logger.info("OBS-KPV-RACE graded=%d tries=%d", int(graded is not None), n)

        self._gate(False)
        cs = p.race_extra[4]
        a = m.ctrl_addr(cs)
        res = await self._watched(_Watch(cs), [_erase_ops(cs), [kp.wr(a, m.SEAL)], [kp.rd(a)]])
        self._erase_done(res[0], cs)
        control = self._ctrl(res[2][0].value)
        self._gate(True)
        self.chk.ctrl("KPV-RACE-SEQ", control == m.SEALED, slot=cs, ctrl=_h(control))
        if graded is not None:
            s, after_seal, final = graded
            self.chk.ok(
                "KPV-RACE",
                final == m.RETIRED,
                slot=s,
                erase_seen=1,
                tries=n,
                ctrl=f"0x{final:X}",
                control=f"0x{control:X}",
            )

    # Step 9.
    async def _step_trail(self) -> None:
        p = self.plan
        s, k = p.trail_slot, p.trail_k
        base = m.word_addr(s, 0)
        w = _Watch(s)
        res = await self._watched(w, [_erase_ops(s), [kp.rdblk(base, m.N_WORDS)]])
        self._erase_done(res[0], s)
        e = list(res[1][0].data)
        vals = [m.nz_word(self.rng, (e[i],)) for i in range(k)]
        self._draw("trail_values", [_h(v) for v in vals])
        res = await self._watched(
            w,
            [
                [kp.wrblk(base, vals)],
                [kp.rdblk(base, m.N_WORDS)],
                [kp.wr(m.ctrl_addr(s), m.LOCK_USE)],
                [kp.rdblk(m.word_addr(s, k), m.N_WORDS - k)],
            ],
        )
        after = res[1][0].data
        locked = res[3][0]
        written = sum(1 for i in range(k) if after[i] == vals[i])
        kept = sum(1 for i in range(k, m.N_WORDS) if after[i] == e[i])
        lz = all(v == 0 for v in locked.data) and all(f.slv == 1 for f in locked.flags)
        self.controls["trail_written"] = self.chk.ctrl(
            "KPV-TRAIL-WRITTEN", written == k, k=k, written=written
        )
        self.chk.ok(
            "KPV-TRAIL",
            written == k and kept == m.N_WORDS - k and lz,
            slot=s,
            k=k,
            written=f"{written}/{k}",
            kept=f"{kept}/{m.N_WORDS - k}",
            lock_use_zero=lz,
        )

    # Step 10.
    def _grade_neighbours(self) -> None:
        by_slot: dict[int, list[_Watch]] = {}
        for w in self.watches:
            by_slot.setdefault(w.slot, []).append(w)
        changes = 0
        ops = 0
        moved = True
        for slot, ws in by_slot.items():
            snaps = [sn for w in ws for sn in w.snaps]
            own = [o for w in ws for o in w.own]
            ops += sum(w.ops for w in ws)
            changes += sum(1 for i in range(1, len(snaps)) if snaps[i] != snaps[0])
            slot_moved = any(o != own[0] for o in own)
            moved &= slot_moved
            if not slot_moved:
                self.logger.info("LOG neigh slot=%d own_ctrl_constant=%s", slot, _h(own[0]))
        self.controls["neigh_twin"] = self.chk.ctrl("KPV-NEIGH-TWIN", moved, slots=len(by_slot))
        self.chk.ok(
            "KPV-NEIGH", changes == 0, ops=ops, slots=len(by_slot), neighbor_changes=changes
        )

    # Step 11.
    async def _step_scrambler(self) -> None:
        p = self.plan
        cells = p.scr_cells
        d = p.scr_values
        groups = [_erase_ops(s) for s in p.scr_slots]
        groups += [[kp.wr(m.word_addr(s, w), v)] for (s, w), v in zip(cells, d, strict=True)]
        groups += [[kp.rd(m.word_addr(s, w))] for (s, w) in cells]
        groups += [_erase_ops(s) for s in p.scr_slots]
        groups += [[kp.wr(m.SCR_KEY, p.kk)], [kp.wr(m.SCR_CTRL, m.SCR_ENABLE)]]
        if p.lock_before:
            groups.append([kp.wr(m.SCR_CTRL, m.SCR_ENABLE | m.SCR_LOCK)])
        groups += [[kp.wr(m.word_addr(s, w), v)] for (s, w), v in zip(cells, d, strict=True)]
        groups += [[kp.rd(m.word_addr(s, w))] for (s, w) in cells]
        if not p.lock_before:
            groups.append([kp.wr(m.SCR_CTRL, m.SCR_ENABLE | m.SCR_LOCK)])
        groups.append([kp.rd(m.SCR_CTRL)])
        groups += [[kp.rd(m.ctrl_addr(s))] for s in p.drawn]
        res = await self._run_groups(groups)
        ns, nc = len(p.scr_slots), len(cells)
        for i, s in enumerate(p.scr_slots):
            self._erase_done(res[i], s)
            self._erase_done(res[ns + 2 * nc + i], s)
        twin = res[ns + nc : ns + 2 * nc]
        self.twin_equal = sum(1 for r, v in zip(twin, d, strict=True) if r[0].value == v)
        off = 2 * ns + 2 * nc + 2 + (1 if p.lock_before else 0) + nc
        logical = res[off : off + nc]
        self.logical_ok = sum(1 for r, v in zip(logical, d, strict=True) if r[0].value == v)
        self.scr_pre = self._scr(res[-1 - len(p.drawn)][0].value)
        self.warm_pre = [self._ctrl(r[0].value) for r in res[-len(p.drawn) :]]
        self.logger.info(
            "LOG scrambler twin_equal=%d logical_ok=%d scr_ctrl=%s lock_timing=%s",
            self.twin_equal,
            self.logical_ok,
            _h(self.scr_pre),
            "before" if p.lock_before else "after",
        )

    # Step 12.
    async def _step_warm(self) -> None:
        p = self.plan
        await self.poke.prepare_reset()
        # The inbound FIFO keeps its words across a warm reset and the POKE boot
        # does not flush it, so a leftover word would read as a list header.
        await self.poke.mbox.flush()
        await self.swrst.park("km")
        await self.swrst.release("km")
        await self.poke.wait_boot()
        groups = [[kp.rd(m.ctrl_addr(s))] for s in p.drawn]
        groups.append([kp.rd(m.SCR_CTRL)])
        groups += [[kp.rd(m.word_addr(s, w))] for (s, w) in p.scr_cells]
        res = await self._run_groups(groups)
        nd = len(p.drawn)
        ctrl = [self._ctrl(r[0].value) for r in res[:nd]]
        self.scr_warm = self._scr(res[nd][0].value)
        self.cells_warm = sum(
            1 for r, v in zip(res[nd + 1 :], p.scr_values, strict=True) if r[0].value == v
        )
        stepped = {*p.ctrlw_slots.values(), *p.walk_slots, p.race_slot, p.trail_slot}
        set_before = sum(1 for c in self.warm_pre if c != 0)
        stepped_set = all(
            c != 0 for s, c in zip(p.drawn, self.warm_pre, strict=True) if s in stepped
        )
        self.chk.ctrl(
            "KPV-RESET-WARM-SET", stepped_set, stepped=len(stepped), set_before=set_before
        )
        self.chk.ok(
            "KPV-RESET",
            all(c == 0 for c in ctrl),
            kind="warm",
            slots=nd,
            set_before=set_before,
            ctrl=_h(max(ctrl)),
        )
        groups = [[kp.wr(m.ctrl_addr(s), m.LOCK_WRITE)] for s in p.drawn]
        groups += [[kp.rd(m.ctrl_addr(s))] for s in p.drawn]
        res = await self._run_groups(groups)
        self.cold_pre = [self._ctrl(r[0].value) for r in res[nd:]]

    # Step 13.
    async def _step_cold(self) -> None:
        p = self.plan
        await self.poke.prepare_reset()
        await self.pulse_rst_ni(release_bound=_SEP_RESET_BOUND)
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        swrst = await self.swrst.read_back()
        self.logger.info("LOG cold sw_reset_n_after_rst_ni=%s", _h(swrst))
        await self.swrst.release("km")
        await self.poke.wait_boot()
        groups = [[kp.rd(m.ctrl_addr(s))] for s in p.drawn]
        groups.append([kp.rd(m.SCR_CTRL)])
        groups += [[kp.rd(m.word_addr(s, w))] for (s, w) in p.scr_cells]
        res = await self._run_groups(groups)
        nd = len(p.drawn)
        ctrl = [self._ctrl(r[0].value) for r in res[:nd]]
        cold_scr = self._scr(res[nd][0].value)
        cells_ne = sum(
            1 for r, v in zip(res[nd + 1 :], p.scr_values, strict=True) if r[0].value != v
        )
        set_before = sum(1 for c in self.cold_pre if c == m.LOCK_WRITE)
        self.chk.ok(
            "KPV-RESET",
            set_before == nd and all(c == 0 for c in ctrl),
            kind="cold",
            slots=nd,
            set_before=set_before,
            ctrl=_h(max(ctrl)),
        )
        self.chk.ctrl("KSCR-RST-TWIN", self.twin_equal == m.N_SCR_CELLS, twin_equal=self.twin_equal)
        self.chk.ctrl(
            "KSCR-RST-LOGICAL", self.logical_ok == m.N_SCR_CELLS, logical_ok=self.logical_ok
        )
        both = m.SCR_ENABLE | m.SCR_LOCK
        self.chk.ok(
            "KSCR-RST",
            self.scr_pre == both
            and self.scr_warm == both
            and self.cells_warm == m.N_SCR_CELLS
            and cold_scr == 0,
            e=1,
            twin_equal=self.twin_equal,
            logical_ok=self.logical_ok,
            pre_ctrl=f"0x{self.scr_pre:x}",
            warm_kept=self.scr_warm == both,
            cells_ok=self.cells_warm,
            cold_ctrl=f"0x{cold_scr:x}",
        )
        self.logger.info("OBS-KSCR-COLD LOG cells_ne=%d", cells_ne)

    # Steps 14, 15 and 16.
    async def _step_wipe(self) -> None:
        p = self.plan
        fs, ss, rs = p.wipe_slots
        va = m.distinct_words(self.rng, m.N_WORDS)
        vb = m.distinct_words(self.rng, m.N_WORDS)
        vc = m.distinct_words(self.rng, m.N_WORDS)
        self._draw("wipe_values", f"free0={_h(va[0])},sealed0={_h(vb[0])},retired0={_h(vc[0])}")
        setup = [
            kp.wr(m.SCR_KEY, p.kk2),
            kp.rd(m.SCR_KEY),
            kp.wr(m.SCR_CTRL, m.SCR_ENABLE | m.SCR_LOCK),
            kp.wrblk(m.word_addr(fs, 0), va),
            kp.wrblk(m.word_addr(ss, 0), vb),
            kp.wr(m.ctrl_addr(ss), m.SEAL),
            kp.wrblk(m.word_addr(rs, 0), vc),
            kp.wr(m.ctrl_addr(rs), m.SEAL),
            *_erase_ops(rs),
            kp.wr(m.HMAC_KEY_CTRL, m.HMAC_KEY_VALID),
            *[kp.wr(a, v) for a, v in zip(p.sram_addrs, p.sram_values, strict=True)],
        ]
        sres = await self._run(setup)
        self._erase_done(sres[8:10], rs)
        key_pre = sres[1].value

        reads = [
            kp.rdblk(m.word_addr(fs, 0), m.N_WORDS),
            kp.rdblk(m.word_addr(ss, 0), m.N_WORDS),
            kp.rd(m.ctrl_addr(fs)),
            kp.rd(m.ctrl_addr(ss)),
            kp.rd(m.ctrl_addr(rs)),
            kp.rd(m.SCR_CTRL),
            kp.rd(m.HMAC_KEY_CTRL),
            *[kp.rd(a) for a in p.sram_addrs],
            kp.rdloop(m.KPV_BASE, m.N_KPV_WORDS),
            kp.delay(_WIPE_WINDOW_DELAY),
        ]
        ha = await self.poke.post(reads)
        last = len(reads) - 1
        waited = 0
        while not (self.poke.state() == (kp.ST_RUN, ha.tag) and self.poke.progress()[0] == last):
            if waited > _WIPE_WINDOW_BOUND:
                raise AssertionError("POKE did not reach the delay op of the wipe pre-state list")
            await ClockCycles(cocotb.top.clk_i, _WIPE_WINDOW_POLL)
            waited += _WIPE_WINDOW_POLL
        pre = self.poke.results(ha, partial=True, allow_unknown=True)
        for r in pre:
            self._check_result(r)
        sram_pre = [pre[7 + i].value for i in range(m.N_SRAM_WORDS)]
        loop_pre = pre[7 + m.N_SRAM_WORDS]
        hmac_pre = pre[6].value & m.HMAC_KEY_CTRL_FIELDS

        # The pushed mailbox word is the header of the read-back list, so the image
        # takes it as its next list after the delay op ends.
        opsb = [
            kp.rdloop(m.KPV_BASE, m.N_KPV_WORDS),
            kp.rdblk(m.ctrl_addr(0), m.N_SLOTS),
            kp.rd(m.SCR_KEY),
            kp.rd(m.SCR_CTRL),
            kp.rd(m.IRQ_STATUS),
            kp.rd(m.HMAC_KEY_CTRL),
            *[kp.rd(a) for a in p.sram_addrs],
        ]
        hb = self.poke.reserve(opsb)
        depth0 = await self._mbox_depth()
        await self.poke.post_header(hb)
        depth_pre = await self._mbox_depth()

        await self._wipe_ctrl(_KM_WIPE_BIT)
        await ClockCycles(cocotb.top.clk_i, p.wipe_hold)
        await self._wipe_ctrl(0)
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        vec = self.rd(cocotb.top.sep_internal_interrupts_probe_o, 1 << _PIC_KM_UNREC)
        await RisingEdge(cocotb.top.clk_i)
        self.logger.info("LOG err_o=%d", (vec >> _PIC_KM_UNREC) & 1)
        depth_post = await self._mbox_depth()
        if not (self.poke.state() == (kp.ST_RUN, ha.tag) and self.poke.progress()[0] == last):
            raise AssertionError(
                "the delay op ended before the post-wipe SEP_STATUS read; raise _WIPE_WINDOW_DELAY"
            )

        await self.poke.post(hb.ops, handle=hb, header_sent=True)
        await self.poke.wait(hb)
        post = self.poke.results(hb, allow_unknown=True)
        for r in post:
            self._check_result(r)

        both = m.SCR_ENABLE | m.SCR_LOCK
        vault_pre = (
            key_pre == p.kk2
            and list(pre[0].data) == va
            and list(pre[1].data) == vb
            and self._ctrl(pre[3].value) == m.SEALED
            and self._ctrl(pre[4].value) == m.RETIRED
            and self._scr(pre[5].value) == both
            and loop_pre.data[0] >= 2 * m.N_WORDS
        )
        self.controls["wipe_pre_vault"] = self.chk.ctrl(
            "WIPE-KPV-PRE",
            vault_pre,
            key=_h(key_pre),
            sealed_ctrl=_h(self._ctrl(pre[3].value)),
            retired_ctrl=_h(self._ctrl(pre[4].value)),
            scr=_h(self._scr(pre[5].value)),
            words_nonzero=loop_pre.data[0],
        )
        scope_pre = (
            sram_pre == p.sram_values
            and hmac_pre == m.HMAC_KEY_VALID
            and depth0 == 0
            and depth_pre == 1
        )
        self.controls["wipe_pre_scope"] = self.chk.ctrl(
            "WIPE-SCOPE-PRE",
            scope_pre,
            sram_same=sum(1 for a, b in zip(sram_pre, p.sram_values, strict=True) if a == b),
            mbox_depth_before_push=depth0,
            mbox_depth=depth_pre,
            keyvalid_hmac=hmac_pre,
        )

        loop, ctrls = post[0], post[1]
        ctrl_nonzero = sum(1 for v in ctrls.data if self._ctrl(v) != 0)
        key = post[2].value
        scr = self._scr(post[3].value)
        status = self._irq(post[4].value) != 0
        hmac = post[5].value & m.HMAC_KEY_CTRL_FIELDS
        sram_post = [post[6 + i].value for i in range(m.N_SRAM_WORDS)]
        self.chk.ok(
            "WIPE-KPV",
            loop.data[0] == 0
            and loop.data[1] == 0
            and ctrl_nonzero == 0
            and key == 0
            and scr == 0
            and status,
            words_nonzero=loop.data[0],
            words_or=_h(loop.data[1]),
            ctrl_nonzero=ctrl_nonzero,
            kpv_key=_h(key),
            en=int(bool(scr & m.SCR_ENABLE)),
            lock=int(bool(scr & m.SCR_LOCK)),
            status=int(status),
            cpu_alive=1,
            W=p.wipe_hold,
        )
        sram_same = sum(1 for a, b in zip(sram_post, p.sram_values, strict=True) if a == b)
        self.chk.ok(
            "WIPE-SCOPE",
            sram_same == m.N_SRAM_WORDS and depth_post == 1 and hmac == m.HMAC_KEY_VALID,
            sram_same=sram_same,
            mbox_depth=depth_post,
            keyvalid_hmac=hmac,
        )

    # Steps 17 and 18.
    async def _step_level_and_edge(self) -> None:
        irq = m.IRQ_STATUS
        marks: dict[str, int] = {}

        async def on_sync(k: int) -> None:
            if k == 0:
                await self._wipe_ctrl(_KM_WIPE_BIT)
            elif k == 1:
                await ClockCycles(cocotb.top.clk_i, _LEVEL_HOLD_CLKS)
            elif k == 2:
                await self._wipe_ctrl(_KM_WIPE_BIT)
                marks["t0"] = self._clk_count
            else:
                marks["t1"] = self._clk_count
            return None

        ops = [
            kp.wr(irq, m.IRQ_WIPE),
            kp.rd(irq),
            kp.sync(),
            kp.rd(irq),
            kp.sync(),
            kp.wr(irq, m.IRQ_WIPE),
            kp.rd(irq),
            kp.sync(),
            kp.poll(irq, m.IRQ_WIPE, m.IRQ_WIPE, _LEVEL_POLL_LOADS),
            kp.sync(),
        ]
        self._clk_count = 0
        self._clk_run = True
        cocotb.start_soon(self._count_clks())
        res = await self._run(ops, on_sync=on_sync)
        self._clk_run = False
        window = marks["t1"] - marks["t0"]
        # A poll that stopped early saw WIPE_STATE set: that is a DUT verdict,
        # graded below. Only a poll that made every load must span the window.
        full_poll = res[8].data[1] == _LEVEL_POLL_LOADS
        if full_poll and window < _LEVEL_WINDOW_MULT * _LEVEL_HOLD_CLKS:
            raise AssertionError(
                f"the held-level read window lasted {window} clocks, below "
                f"{_LEVEL_WINDOW_MULT * _LEVEL_HOLD_CLKS}; raise _LEVEL_POLL_LOADS"
            )
        cleared = self._irq(res[1].value)
        first = self._irq(res[3].value)
        after_clear = self._irq(res[6].value)
        poll = res[8]
        held = (
            after_clear == 0 and self._irq(poll.data[0]) == 0 and poll.data[1] == _LEVEL_POLL_LOADS
        )
        self.controls["wipe_first_edge"] = self.chk.ctrl(
            "WIPE-EDGE1",
            cleared == 0 and first != 0,
            cleared=int(bool(cleared)),
            status=int(bool(first)),
        )

        async def edge(_k: int) -> None:
            await self._wipe_ctrl(0)
            await self._wipe_ctrl(_KM_WIPE_BIT)
            return None

        res2 = await self._run(
            [kp.wr(irq, m.IRQ_WIPE), kp.rd(irq), kp.sync(), kp.rd(irq)], on_sync=edge
        )
        before = self._irq(res2[1].value)
        again = self._irq(res2[3].value) != 0
        self.chk.ok(
            "WIPE-EDGE2",
            held and before == 0 and again,
            level_high_no_wipe=int(held),
            hold_clks=_LEVEL_HOLD_CLKS,
            window_clks=window,
            poll_loads=poll.data[1],
            status_again=int(again),
        )
        self._gate(False)
        await self._wipe_ctrl(0)
        self._gate(True)

    # Step 19.
    async def _step_cipher(self) -> None:
        p = self.plan
        base, xb = self._snapshot()
        self.x_snap_bits += xb
        self.chk.ctrl(
            "KSCR-CIPHER-BASE", all(v == 0 for v in base), words_nonzero=sum(1 for v in base if v)
        )
        await self._run([kp.wr(m.SCR_KEY, p.cipher_key), kp.wr(m.SCR_CTRL, m.SCR_ENABLE)])
        snaps: list[list[int]] = []

        async def snap(_k: int) -> None:
            words, x = self._snapshot()
            self.x_snap_bits += x
            snaps.append(words)
            return None

        per_list = 8
        for i in range(0, m.N_CIPHER, per_list):
            ops = []
            for (s, w), d1, d2 in p.cipher[i : i + per_list]:
                a = m.word_addr(s, w)
                ops += [kp.wr(a, d1), kp.sync(), kp.wr(a, d2), kp.sync()]
            await self._run(ops, on_sync=snap)
        diff_ok = 0
        one_word = 0
        for j, (cell, d1, d2) in enumerate(p.cipher):
            sa, sb = snaps[2 * j], snaps[2 * j + 1]
            changed = [i for i in range(m.N_KPV_WORDS) if sa[i] != sb[i]]
            if len(changed) == 1:
                one_word += 1
                pi = changed[0]
                if m.inverse_diff(sa[pi], sb[pi]) == d1 ^ d2:
                    diff_ok += 1
            else:
                self.logger.info(
                    "LOG cipher draw=%d cell=%s changed_words=%d", j, cell, len(changed)
                )
        lanes = {(ln, (d1 >> (4 * ln)) & 0xF) for _c, d1, _d2 in p.cipher for ln in range(8)}
        self.chk.ok(
            "KSCR-CIPHER",
            diff_ok == m.N_CIPHER and one_word == m.N_CIPHER and len(lanes) == 8 * 16,
            draws=m.N_CIPHER,
            lane_values=f"8x{len(lanes) // 8}",
            one_word=one_word,
            diff_ok=diff_ok,
        )

        # Control (logged): under the second key the same cell and data store
        # another word. Draw 32 gives the index and the word of d1 under key k.
        self._gate(False)
        (s, w), d1, _d2 = p.cipher[-1]
        sa, sb = snaps[-2], snaps[-1]
        idx_k = [i for i in range(m.N_KPV_WORDS) if sa[i] != sb[i]]
        await self._run(
            [kp.wr(m.SCR_KEY, p.cipher_key2), kp.wr(m.word_addr(s, w), d1), kp.sync()], on_sync=snap
        )
        under_k2 = snaps[-1]
        idx_k2 = [i for i in range(m.N_KPV_WORDS) if under_k2[i] != sb[i]]
        self.logger.info(
            "LOG KSCR-CIPHER-K2 control=1 cell=%s d1=%s idx_k=%s word_k=%s idx_k2=%s word_k2=%s",
            f"{s}.{w}",
            _h(d1),
            idx_k,
            [_h(sa[i]) for i in idx_k],
            idx_k2,
            [_h(under_k2[i]) for i in idx_k2],
        )
        self._gate(True)

    # Step 20 and the end-of-leaf grades.
    async def _step_end(self) -> None:
        self._gate(False)
        swrst = await self.swrst.read_back()
        if not swrst & _KM_BIT:
            self.swrst.value = swrst
            await self.swrst.release("km")
        if self.vcs:
            self.chk.ok(
                "KPV-NOX",
                self.x_words == 0 and self.x_snap_bits == 0,
                compared_words=self.compared,
                x_words=self.x_words,
                snapshot_x_bits=self.x_snap_bits,
            )
        else:
            self.logger.info(
                "LOG CHK-KPV-NOX not graded: Verilator is two-state compared_words=%d",
                self.compared,
            )
        for reg, seen in self.rsvd.items():
            self.logger.info(
                "LOG RSVD reg=%s masked=%s seen_or=%s", reg, _h(self.rsvd_mask[reg]), _h(seen)
            )
        self.chk.ok(
            "NONVAC",
            all(self.controls.values()),
            controls=sorted(k for k, v in self.controls.items() if v),
            missing=sorted(k for k, v in self.controls.items() if not v) or "none",
        )

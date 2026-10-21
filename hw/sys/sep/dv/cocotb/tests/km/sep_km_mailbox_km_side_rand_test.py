# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM-side mailbox registers, words, error responses, flush and the KM CPU interrupt route.

no_cpu (``lsu_stub_all_live``) / ``+skip_fuse_sense`` /
``+km_rom_hex=km_rom_mbox_km.param.parhex``.

Vehicle. The IMG-MBOX-KM image (``tests/km_fw/km_rom_mbox_km.S``) runs a fixed
script of phases as a legal master of the KM side of the mailbox and writes
what the DUT returned to KM SRAM words 0 to 97 (``km_sram_probe_o``,
KM-RESULT). It takes every drawn value from the parameter block that
``dv_sim_prestage.py`` stages at KM ROM word 0xF00
(``env/sep_km_img_param.py``, ``MboxPlan``); this test calls the same
``plan(item, seed)`` for its golden and checks that the staged file and the
image echo of the block match it. The host side of the mailbox is the SEP
LSU master (HOST-MBX). The image advances when it sees the host action of a
phase on the KM side of the mailbox: an inbound fill level, a free outbound
slot, flushed_by_sep, or a sync word (one ``SYNC_WORD`` written to an empty
inbound FIFO, which the image reads and checks; it is a handshake, not
stimulus). A FIFO model written from the register text gives the expected
depth, flags and word order.

Specification. ``hw/ip/key_manager/doc/architecture.adoc``, sections "Reset
Conditioning", "Mailbox Transport", "Key Manager CPU Interrupt Processing";
``hw/ip/key_manager/regs/gen/adoc/km_mailbox_km.adoc``, sections "Key Manager
Mailbox KM Side", "KM_READ_DATA", "KM_STATUS", "KM_IRQ_STATUS",
"KM_IRQ_ENABLE", "KM_CTRL", "KM_WRITE_SEPARATOR";
``hw/ip/key_manager/regs/gen/adoc/km_mailbox_sep.adoc``, sections
"SEP_READ_DATA", "SEP_CTRL". Field masks and reset values come from the
generated RDL headers (``sep_km_mailbox_km_side_rand_model.py``).

Checkers:
  CHK-KMBOX-RST    after reset KM_STATUS reads its RDL reset (0x5), KM_CTRL,
                   KM_IRQ_ENABLE and KM_WRITE_SEPARATOR read 0, and
                   KM_IRQ_STATUS[4:2] reads 0. KM_IRQ_STATUS[1:0] reads 0b11
                   with the 16 inbound words of the first inbound pass queued
                   and 0b10 after the image read them. The reset value of the
                   level bits is logged only.
  CHK-KMBOX-OUT    per outbound pass (N = 16, 1, 15, drawn): KM_STATUS shows
                   outbound_depth N, outbound_empty 0, outbound_full 1 only for
                   N = 16; KM_WRITE_SEPARATOR.set reads 1 after the arm and 0
                   after the write; SEP_STATUS shows the outbound FIFO empty
                   after the host read the N words. The word compare and
                   SEP_STATUS.outbound_separator are logged (control=1).
  CHK-KMBOX-IN     per inbound pass (M = 16, 1, 15, drawn): KM_STATUS shows
                   inbound_depth M, inbound_empty 0, inbound_full 1 only for
                   M = 16; inbound_separator reads 1 after the last word and 0
                   after every other word, and 0 after the extra word with no
                   separator. The word compare is logged (control=1).
  CHK-KMBOX-ERR    per error pass (inbound underflow and outbound overflow,
                   each with both response-bit values): the sticky bit sets in
                   KM_STATUS and KM_IRQ_STATUS; IRQ_STATUS.AXI_SLVERR reads 1
                   only with the response bit 0; the queue is unchanged
                   (inbound depth 0; outbound depth 16 and the host reads the 16
                   words written, then an empty FIFO); a write of 0 keeps the
                   KM_IRQ_STATUS bit, a write of 1 clears it; a write of 1
                   clears the KM_STATUS bit after a second event. Each clear is
                   graded only after a read of 1.
  CHK-KMBOX-FLUSH  per flush cell (KM or SEP flush, FIFOs both empty, one
                   non-empty, both non-empty): KM flush: both FIFOs read empty
                   on both sides and KM_CTRL.flush reads 0; SEP flush: the
                   outbound FIFO reads empty on both sides (inbound depth and
                   SEP_CTRL.flush logged, control=1). The peer flushed-by-other
                   bit sets, a write of 0 keeps it and a write of 1 clears it.
  CHK-KMBOX-IRQ    per enable run (S and its complement): in every check cycle
                   the CPU IRQ 4 handler count rises exactly when the OR of
                   (KM_IRQ_STATUS bit AND KM_IRQ_ENABLE bit) of the model is
                   non-zero; KM_IRQ_STATUS[4:0] matches the model sources,
                   KM_IRQ_ENABLE reads the written value, IRQ_STATUS reads 0
                   and the CPU IRQ 3 count does not change.
  CHK-NONVAC       every control of the checks above was seen.

Controls (CTRL lines; a missing one fails the leaf): the level bits move at
the first FIFO event; the three bits read 0 and KM_CTRL reads the pass value
before each error pass; the outbound FIFO is full before the overflow; the
peer bit reads 0 and the depths read the fill before each flush; KM_CTRL and
IRQ_STATUS read the interrupt-phase values; the line is low with no source
before each run, the outbound FIFO is full at its start, each source raises
the line in the run that enables it; an IRQ_SET of DRBG_ERR with its enable
raises CPU IRQ 3 and sets IRQ_STATUS.DRBG_ERR; KMCSR IRQ_STATUS shows no
AXI_DECERR at any publish of the image and no AXI_SLVERR outside the error
passes, so no counted KM readback had an error response.

Log only: the read data of the empty reads, the value of the other sticky
register after a clear (the coupling of the KM_STATUS and KM_IRQ_STATUS
sticky bits is not stated), the flush poll counts, the reset value of the
level bits, and the reserved bits of every KM-side readback with their mask.

Not sent: the SEP inbound overflow and the SEP outbound underflow, a flush in
the middle of a frame, a second arm of the separator with no write between.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env import sep_km_img_param as kip
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from km import sep_km_mailbox_km_side_rand_model as m
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_BASE,
    KM_MBOX_CTRL,
    KM_MBOX_IRQ_STATUS,
    KM_MBOX_READ_DATA,
    KM_MBOX_STATUS,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = m.TEST

# Bounds (clk_i cycles, or host reads).
_SEP_RESET_BOUND = 20_000
_BOOT_BOUND = 400_000
_PHASE_BOUND = 2_000_000
_POLL_CYCLES = 16
_SEP_FLUSH_POLL = 1_000

_REQUIRED = (
    "CHK-KMBOX-RST",
    "CHK-KMBOX-OUT",
    "CHK-KMBOX-IN",
    "CHK-KMBOX-ERR",
    "CHK-KMBOX-FLUSH",
    "CHK-KMBOX-IRQ",
    "CHK-NONVAC",
)


def _h(v: int) -> str:
    return f"0x{v & m.WORD:08x}"


@pyuvm.test()
class sep_km_mailbox_km_side_rand_test(sep_base_test):
    """KM-side mailbox registers, words, error responses, flush and interrupt route."""

    required_evidence = _REQUIRED

    # --- bench access --------------------------------------------------------

    async def _sep_rd(self, off: int) -> int:
        seq = SepAxiAccessSeq("km_mbox_sep_rd", op=SepAxiOp.READ, addr=KM_MBOX_BASE + off, size=2)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SEP mailbox read @0x{KM_MBOX_BASE + off:08x} not OKAY")
        return seq.rdata & m.WORD

    async def _sep_wr(self, off: int, data: int) -> None:
        seq = SepAxiAccessSeq(
            "km_mbox_sep_wr", op=SepAxiOp.WRITE, addr=KM_MBOX_BASE + off, wdata=data, size=2
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SEP mailbox write @0x{KM_MBOX_BASE + off:08x} not OKAY")

    async def _sync(self) -> None:
        await self._sep_wr(KM_MBOX_WRITE_DATA, m.SYNC_WORD)

    def _word(self, i: int, *, allow_unknown: bool = False) -> int:
        mask = m.WORD << (32 * i)
        v = self.rd(cocotb.top.km_sram_probe_o, mask, allow_unknown=allow_unknown)
        return (v >> (32 * i)) & m.WORD

    def _report(self, n: int) -> list[int]:
        """Report words R0..R(n-1); an unknown bit raises."""
        if n > m.N_R:
            raise ValueError(f"report of {n} words exceeds {m.N_R}")
        mask = ((1 << (32 * n)) - 1) << (32 * m.W_R)
        v = self.rd(cocotb.top.km_sram_probe_o, mask) >> (32 * m.W_R)
        return [(v >> (32 * i)) & m.WORD for i in range(n)]

    async def _wait(self, phases: tuple[int, ...], what: str, bound: int = _PHASE_BOUND) -> int:
        """Wait for the next publish of the image; it must be one of ``phases``."""
        want = (self.seq + 1) & 0xFF
        waited = 0
        last = None
        while waited <= bound:
            st = m.state_of(self._word(m.W_STATE, allow_unknown=True))
            last = st
            if st is not None:
                if st[1] == m.PH_ERROR:
                    raise AssertionError(
                        f"IMG-MBOX-KM stopped at {what}: {m.err_text(self._word(m.W_AUX))}"
                    )
                if st[0] == want:
                    if st[1] not in phases:
                        raise AssertionError(
                            f"IMG-MBOX-KM published {m.PHASE_NAMES.get(st[1], hex(st[1]))} "
                            f"while the host waited for {what}"
                        )
                    self.seq = want
                    self._bus(st[1])
                    return st[1]
            await ClockCycles(cocotb.top.clk_i, _POLL_CYCLES)
            waited += _POLL_CYCLES
        raise AssertionError(f"IMG-MBOX-KM did not reach {what} in {bound} clocks (state {last})")

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(_SEP_RESET_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(f"dbg_sep_reset_n_o did not read 1 within {_SEP_RESET_BOUND} clocks")

    def _bus(self, phase: int) -> None:
        """KMCSR IRQ_STATUS at the publish: no error response on a legal access.

        AXI_DECERR is never expected. AXI_SLVERR is the graded response of the
        error passes and reads 0 at every other publish (the image clears it
        before the flush cells).
        """
        bus = self._word(m.W_BUS)
        allowed = m.CSR_SLVERR if phase == m.PH_ERR else 0
        self.bus_seen += 1
        if bus & (m.CSR_SLVERR | m.CSR_DECERR) & ~allowed:
            self.bus_bad.append(f"{m.PHASE_NAMES.get(phase, hex(phase))}:{_h(bus)}")

    def _rsvd(self, name: str, value: int, fields: int) -> None:
        self.rsvd[name] = (self.rsvd.get(name, (0, fields))[0] | (value & ~fields & m.WORD), fields)

    def _ctrl(self, name: str, seen: bool, **fields) -> bool:
        ok = self.chk.ctrl(name, seen, **fields)
        self.controls[name] = self.controls.get(name, True) and ok
        return ok

    # --- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.plan = kip.plan(TEST, seed)
        self.hd = m.host_draws(SepSeededRng(seed ^ m.HOST_STREAM))
        self._log_draws()
        self.chk = SepChkLog(self, TEST, seed)
        self.seq = 0
        self.rsvd: dict[str, tuple[int, int]] = {}
        self.controls: dict[str, bool] = {}
        self.mb = m.Mailbox()
        self.bus_seen = 0
        self.bus_bad: list[str] = []
        self._check_image(seed)

        # Step 1: no_cpu bring-up with fuse sense skipped, KM release.
        close_graded_window(self.logger)
        await self.bring_up_no_cpu()
        await self._wait_sep_reset_n()
        self.swrst = SepSwReset(self)
        await self.swrst.release("km")

        await self._step_reset()
        open_graded_window(TEST, self.logger)
        await self._step_out()
        await self._step_in()
        self._grade_reset()
        await self._step_err()
        await self._step_flush()
        await self._step_irq()
        close_graded_window(self.logger)
        await self._step_end()
        self._grade_nonvac()
        self.chk.finish()

    def _log_draws(self) -> None:
        p = self.plan
        log = self.logger.info
        log("DRAW n=%d m=%d", p.n_drawn, p.m_drawn)
        log("DRAW err_first udf=%d ovf=%d", p.err_first[0], p.err_first[1])
        log("DRAW flush_order=%s flush_one km=%d sep=%d", p.flush_order, *p.flush_one_fifo)
        log("DRAW irq_enable_s=0x%02x src_order=%s", p.irq_enable_s, p.src_order)
        for k, words in enumerate(p.out_pass):
            log("DRAW out_pass%d=%s", k, [_h(w) for w in words])
        for k, words in enumerate(p.in_pass):
            log("DRAW in_pass%d=%s", k, [_h(w) for w in words])
        log("DRAW out_overflow=%s", [_h(w) for w in p.out_overflow])
        for c in range(len(p.out_flush)):
            log(
                "DRAW flush_cell%d out=%s in=%s",
                c,
                [_h(w) for w in p.out_flush[c]],
                [_h(w) for w in p.in_flush[c]],
            )
        for r, words in enumerate(p.out_irq):
            log("DRAW out_irq%d=%s", r, [_h(w) for w in words])
        log(
            "DRAW extra_in=%s irq_in=%s",
            [_h(w) for w in self.hd.extra],
            [_h(w) for w in self.hd.irq_in],
        )

    def _check_image(self, seed: int) -> None:
        """The image layout matches the host, and the staged image holds this seed's block."""
        template = m.TEMPLATE.read_text(encoding="ascii")
        bad = m.check_image(template)
        if bad:
            raise AssertionError("IMG-MBOX-KM layout differs from the host: " + "; ".join(bad))
        want = kip.staged_text(m.TEMPLATE, TEST, seed)
        staged = Path.cwd() / m.STAGED_NAME
        if not staged.is_file():
            raise AssertionError(f"{staged} is missing: the prestage did not stage the block")
        got = staged.read_text(encoding="ascii")
        if got != want:
            raise AssertionError(f"{staged} does not hold the parameter block of seed {seed}")
        self.logger.info(
            "LOG KM-IMG-PARAM item=%s seed=%d template_sha256=%s staged_sha256=%s",
            TEST,
            seed,
            kip.identity(template),
            kip.identity(got),
        )

    # Step 2.
    async def _step_reset(self) -> None:
        await self._wait((m.PH_RST,), "the reset phase", _BOOT_BOUND)
        r = self._report(8)
        want = (m.check_word(TEST, self.random_seed()), self.plan.n_drawn, self.plan.m_drawn)
        if (r[5], r[6], r[7]) != want:
            raise AssertionError(
                f"IMG-MBOX-KM read block check={_h(r[5])} n={r[6]} m={r[7]}, plan has "
                f"check={_h(want[0])} n={want[1]} m={want[2]}"
            )
        self.rst = r[:5]
        self.chk.obs("KMBOX-RST-LEVEL", level_logged=f"0x{r[4] & m.IRQ_LEVEL:x}")
        self._rsvd("KM_STATUS", r[0], m.ST_FIELDS)
        self._rsvd("KM_CTRL", r[1], m.CTRL_FIELDS)
        self._rsvd("KM_IRQ_ENABLE", r[2], m.EN_FIELDS)
        self._rsvd("KM_WRITE_SEPARATOR", r[3], m.WSEP_FIELDS)
        self._rsvd("KM_IRQ_STATUS", r[4], m.IRQ_FIELDS)
        await self._sync()

    def _grade_reset(self) -> None:
        st, ctrl, en, wsep, irq = self.rst
        push = self.lv_push & m.IRQ_LEVEL
        drain = self.lv_drain & m.IRQ_LEVEL
        self._ctrl("KMBOX-RST-LEVEL-MOVES", push != drain, push=f"0x{push:x}", drain=f"0x{drain:x}")
        ok = (
            (st & m.ST_FIELDS) == m.ST_RESET
            and (ctrl & m.CTRL_FIELDS) == m.CTRL_RESET
            and (en & m.EN_FIELDS) == m.EN_RESET
            and (wsep & m.WSEP_FIELDS) == m.WSEP_RESET
            and (irq & m.IRQ_STICKY) == 0
            and push == m.IRQ_LEVEL
            and drain == m.IRQ_SRC[1]
        )
        self.chk.ok(
            "KMBOX-RST",
            ok,
            km_status=_h(st & m.ST_FIELDS),
            want_status=_h(m.ST_RESET),
            km_ctrl=f"0x{ctrl & m.CTRL_FIELDS:x}",
            km_irq_enable=f"0x{en & m.EN_FIELDS:x}",
            km_write_separator=f"0x{wsep & m.WSEP_FIELDS:x}",
            sticky_irq=f"0x{irq & m.IRQ_STICKY:x}",
            level_logged=f"0x{irq & m.IRQ_LEVEL:x}",
            level_after_push=f"0x{push:x}",
            level_after_drain=f"0x{drain:x}",
        )

    # Step 3.
    async def _step_out(self) -> None:
        p = self.plan
        for k, n in enumerate((*m.OUT_COUNTS, p.n_drawn)):
            words = p.out_pass[k][:n]
            await self._wait((m.PH_OUT,), f"outbound pass {k}")
            r = self._report(5)
            if (r[0], r[1]) != (k, n):
                raise AssertionError(f"IMG-MBOX-KM outbound pass {r[0]} n={r[1]}, host {k} n={n}")
            for i, w in enumerate(words):
                self.mb.outb.push(w, sep=i == n - 1)
            got, seps = [], []
            for _ in range(n):
                got.append(await self._sep_rd(KM_MBOX_READ_DATA))
                seps.append(m.fld(await self._sep_rd(KM_MBOX_STATUS), m.S_OUT_SEP))
            final = await self._sep_rd(KM_MBOX_STATUS)
            model = [self.mb.outb.pop() for _ in range(n)]
            equal = sum(1 for a, b in zip(got, model) if a == b)
            depth = m.fld(r[4], m.ST_OUT_DEPTH)
            full = m.fld(r[4], m.ST_OUT_FULL)
            empty = m.fld(r[4], m.ST_OUT_EMPTY)
            set_reads = [m.fld(r[2], m.WSEP_SET), m.fld(r[3], m.WSEP_SET)]
            empty_after = m.fld(final, m.S_OUT_EMPTY) == 1 and m.sep_depths(final)[0] == 0
            ok = (
                depth == n
                and empty == 0
                and full == int(n == m.DEPTH)
                and set_reads == [1, 0]
                and empty_after
            )
            self.chk.ok(
                "KMBOX-OUT",
                ok,
                n=n,
                words_equal=equal,
                words_control=1,
                depth=depth,
                full=full,
                empty=empty,
                set_reads=set_reads,
                empty_after=empty_after,
                control_sep_flag_last=seps[-1],
                control_sep_flags_before_last=sum(seps[:-1]),
            )
            self._rsvd("KM_WRITE_SEPARATOR", r[2] | r[3], m.WSEP_FIELDS)
            self._rsvd("KM_STATUS", r[4], m.ST_FIELDS)
            await self._sync()

    # Step 4.
    async def _step_in(self) -> None:
        p = self.plan
        for k, cnt in enumerate((*m.IN_COUNTS, p.m_drawn)):
            words = p.in_pass[k][:cnt]
            await self._wait((m.PH_IN_READY,), f"inbound pass {k} ready")
            for i, w in enumerate(words):
                if i == cnt - 1:
                    await self._sep_wr(KM_MBOX_WRITE_SEPARATOR, 1)
                await self._sep_wr(KM_MBOX_WRITE_DATA, w)
                self.mb.inb.push(w, sep=i == cnt - 1)
            await self._wait((m.PH_IN_MID,), f"inbound pass {k} words read")
            extra = self.hd.extra[k]
            await self._sep_wr(KM_MBOX_WRITE_DATA, extra)
            await self._wait((m.PH_IN,), f"inbound pass {k} extra word read")
            r = self._report(7 + 2 * cnt)
            if (r[0], r[1]) != (k, cnt):
                raise AssertionError(f"IMG-MBOX-KM inbound pass {r[0]} m={r[1]}, host {k} m={cnt}")
            data = [r[5 + 2 * i] for i in range(cnt)]
            sts = [r[6 + 2 * i] for i in range(cnt)]
            model = [self.mb.inb.pop() for _ in range(cnt)]
            self.mb.inb.push(extra)
            model_extra = self.mb.inb.pop()
            equal = sum(1 for a, b in zip(data, model) if a == b)
            seps = [m.fld(s, m.ST_IN_SEP) for s in sts]
            ext_data, ext_st = r[5 + 2 * cnt], r[6 + 2 * cnt]
            not_sticky = m.fld(ext_st, m.ST_IN_SEP) == 0
            depth = m.fld(r[2], m.ST_IN_DEPTH)
            full = m.fld(r[2], m.ST_IN_FULL)
            empty = m.fld(r[2], m.ST_IN_EMPTY)
            ok = (
                depth == cnt
                and empty == 0
                and full == int(cnt == m.DEPTH)
                and seps == [0] * (cnt - 1) + [1]
                and not_sticky
            )
            self.chk.ok(
                "KMBOX-IN",
                ok,
                m=cnt,
                words_equal=equal,
                words_control=1,
                extra_equal=ext_data == model_extra,
                depth=depth,
                full=full,
                empty=empty,
                inbound_sep=seps[-1],
                sep_before_last=sum(seps[:-1]),
                not_sticky=not_sticky,
            )
            for s in (r[2], *sts, ext_st):
                self._rsvd("KM_STATUS", s, m.ST_FIELDS)
            if k == 0:
                self.lv_push, self.lv_drain = r[3], r[4]
                self._rsvd("KM_IRQ_STATUS", r[3] | r[4], m.IRQ_FIELDS)
            await self._sync()

    # Steps 5 to 7.
    async def _step_err(self) -> None:
        p = self.plan
        for idx in range(4):
            ovf = idx >= 2
            cond = "ovf" if ovf else "udf"
            first = p.err_first[1 if ovf else 0]
            resp = first if idx % 2 == 0 else 1 - first
            st_bit, irq_bit = (m.ST_OUT_OVF, m.IRQ_OUT_OVF) if ovf else (m.ST_IN_UDF, m.IRQ_IN_UDF)
            ctrl_val = resp * (m.CTRL_OVF_RESP if ovf else m.CTRL_UDF_RESP)
            await self._wait((m.PH_ERR,), f"error pass {idx}")
            r = self._report(19)
            if (r[0], r[1], r[2]) != (idx, int(ovf), resp):
                raise AssertionError(
                    f"IMG-MBOX-KM error pass {r[:3]}, host {[idx, int(ovf), resp]}"
                )
            self._ctrl(
                "KMBOX-ERR-PRE",
                not (r[4] & st_bit) and not (r[5] & irq_bit) and not (r[6] & m.CSR_SLVERR),
                condition=cond,
                resp=resp,
                km_status=_h(r[4]),
                km_irq_status=_h(r[5]),
                irq_status=_h(r[6]),
            )
            self._ctrl(
                "KMBOX-ERR-CTRL",
                (r[3] & m.CTRL_FIELDS) == ctrl_val,
                condition=cond,
                km_ctrl=_h(r[3]),
            )
            if ovf:
                self._ctrl(
                    "KMBOX-ERR-FULL",
                    m.fld(r[7], m.ST_OUT_FULL) == 1 and m.km_depths(r[7])[0] == m.DEPTH,
                    km_status=_h(r[7]),
                )
                for w in p.out_overflow[: m.DEPTH]:
                    self.mb.outb.push(w)
                for w in p.out_overflow[m.DEPTH :]:
                    if self.mb.outb.push(w):
                        raise AssertionError("FIFO model accepted a word into a full FIFO")
                s0 = await self._sep_rd(KM_MBOX_STATUS)
                got = [await self._sep_rd(KM_MBOX_READ_DATA) for _ in range(m.DEPTH)]
                s1 = await self._sep_rd(KM_MBOX_STATUS)
                model = [self.mb.outb.pop() for _ in range(m.DEPTH)]
                kept_words = sum(1 for a, b in zip(got, model) if a == b)
                queue_ok = (
                    m.km_depths(r[9])[0] == m.DEPTH
                    and m.sep_depths(s0)[0] == m.DEPTH
                    and kept_words == m.DEPTH
                    and m.fld(s1, m.S_OUT_EMPTY) == 1
                    and m.sep_depths(s1)[0] == 0
                )
                queue = kept_words
            else:
                if self.mb.inb.pop() is not None:
                    raise AssertionError("FIFO model holds an inbound word before the underflow")
                queue_ok = m.km_depths(r[9])[1] == 0 and m.fld(r[9], m.ST_IN_EMPTY) == 1
                queue = m.km_depths(r[9])[1]
                self.chk.obs(
                    "KMBOX-UDF-DATA", resp=resp, first_read=_h(r[7]), second_read=_h(r[14])
                )
            sticky = [int(bool(r[9] & st_bit)), int(bool(r[10] & irq_bit))]
            slverr = int(bool(r[8] & m.CSR_SLVERR))
            pre_clear = [int(bool(r[11] & irq_bit)), int(bool(r[16] & st_bit))]
            zero_keeps = bool(r[10] & irq_bit) and bool(r[11] & irq_bit)
            w1c = bool(pre_clear[0]) and not (r[12] & irq_bit)
            st_clear = bool(pre_clear[1]) and not (r[17] & st_bit)
            ok = (
                sticky == [1, 1]
                and slverr == int(resp == 0)
                and queue_ok
                and zero_keeps
                and w1c
                and st_clear
            )
            self.chk.ok(
                "KMBOX-ERR",
                ok,
                condition=cond,
                resp=resp,
                sticky=sticky,
                slverr=slverr,
                queue_kept=queue,
                zero_keeps=zero_keeps,
                w1c_clears=w1c,
                km_status_clear=st_clear,
                pre_clear_reads=pre_clear,
            )
            self.chk.obs(
                "KMBOX-COUPLING",
                condition=cond,
                km_status_after_irq_clear=int(bool(r[13] & st_bit)),
                km_irq_after_status_clear=int(bool(r[18] & irq_bit)),
                slverr_second=int(bool(r[15] & m.CSR_SLVERR)),
            )
            for i in (4, 9, 13, 16, 17):
                self._rsvd("KM_STATUS", r[i], m.ST_FIELDS)
            for i in (5, 10, 11, 12, 18):
                self._rsvd("KM_IRQ_STATUS", r[i], m.IRQ_FIELDS)
            self._rsvd("KM_CTRL", r[3], m.CTRL_FIELDS)
            await self._sync()

    # Step 8.
    def _cell_fill(self, cell: int) -> tuple[int, int]:
        """(outbound filled, inbound filled) of a flush cell."""
        kind = m.CELL_FILL[cell]
        if kind == 0:
            return 0, 0
        if kind == 2:
            return 1, 1
        which = self.plan.flush_one_fifo[0 if m.CELL_INIT[cell] == "km" else 1]
        return (0, 1) if which else (1, 0)

    async def _step_flush(self) -> None:
        p = self.plan
        fill_names = {(0, 0): "empty", (1, 0): "out", (0, 1): "in", (1, 1): "both"}
        for pos in range(kip.MboxPlan.FLUSH_CELLS):
            cell = p.flush_order[pos]
            init = m.CELL_INIT[cell]
            out_fill, in_fill = self._cell_fill(cell)
            await self._wait((m.PH_FL_FILLED,), f"flush cell {cell} filled")
            if out_fill:
                for w in p.out_flush[cell]:
                    self.mb.outb.push(w)
            if init == "km":
                await self._sep_wr(KM_MBOX_IRQ_STATUS, m.S_FLUSHED_BY_KM)
                peer_pre = await self._sep_rd(KM_MBOX_IRQ_STATUS)
                if in_fill:
                    for w in p.in_flush[cell]:
                        await self._sep_wr(KM_MBOX_WRITE_DATA, w)
                        self.mb.inb.push(w)
                sep_pre = await self._sep_rd(KM_MBOX_STATUS)
                await self._sync()
                await self._wait((m.PH_FL_DONE,), f"flush cell {cell} done")
                r = self._report(13)
                self.mb.flush()
                sep_post = await self._sep_rd(KM_MBOX_STATUS)
                peer = []
                for wv in (None, 0, m.S_FLUSHED_BY_KM):
                    if wv is not None:
                        await self._sep_wr(KM_MBOX_IRQ_STATUS, wv)
                    peer.append(
                        int(bool(await self._sep_rd(KM_MBOX_IRQ_STATUS) & m.S_FLUSHED_BY_KM))
                    )
                peer_pre_bit = int(bool(peer_pre & m.S_FLUSHED_BY_KM))
                polls = None
                sep_ctrl_last = None
            else:
                if in_fill:
                    for w in p.in_flush[cell]:
                        await self._sep_wr(KM_MBOX_WRITE_DATA, w)
                        self.mb.inb.push(w)
                await self._sync()
                await self._wait((m.PH_FL_PRE,), f"flush cell {cell} pre-flush status")
                sep_pre = await self._sep_rd(KM_MBOX_STATUS)
                keep = await self._sep_rd(KM_MBOX_CTRL)
                await self._sep_wr(KM_MBOX_CTRL, (keep & m.S_CTRL_FIELDS) | m.S_CTRL_FLUSH)
                polls = 0
                sep_ctrl_last = m.S_CTRL_FLUSH
                while polls < _SEP_FLUSH_POLL and sep_ctrl_last & m.S_CTRL_FLUSH:
                    sep_ctrl_last = await self._sep_rd(KM_MBOX_CTRL)
                    polls += 1
                sep_post = await self._sep_rd(KM_MBOX_STATUS)
                self.mb.flush()
                await self._sync()
                await self._wait((m.PH_FL_DONE,), f"flush cell {cell} done")
                r = self._report(13)
                peer = [int(bool(r[i] & m.IRQ_FLUSHED)) for i in (8, 9, 10)]
                peer_pre_bit = int(bool(r[2] & m.IRQ_FLUSHED))
            if (r[0], r[1]) != (pos, cell):
                raise AssertionError(f"IMG-MBOX-KM flush cell {r[:2]}, host {[pos, cell]}")
            km_pre = list(m.km_depths(r[3]))
            sep_pre_d = list(m.sep_depths(sep_pre))
            # The sync word sits behind the inbound fill words when the KM reads
            # KM_STATUS, and also when the host reads SEP_STATUS before a SEP flush.
            fill = kip.MboxPlan.FLUSH_FILL
            sep_in = (fill + int(init == "sep")) * in_fill
            self._ctrl(
                "KMBOX-FLUSH-PRE",
                peer_pre_bit == 0
                and km_pre == [fill * out_fill, (fill + 1) * in_fill]
                and sep_pre_d == [fill * out_fill, sep_in],
                init=init,
                cell=cell,
                peer_pre=peer_pre_bit,
                km_depths=km_pre,
                sep_depths=sep_pre_d,
            )
            km_post = list(m.km_depths(r[7]))
            sep_post_d = list(m.sep_depths(sep_post))
            zero_keeps = bool(peer[0]) and bool(peer[1])
            w1c = bool(peer[1]) and not peer[2]
            fields = {
                "init": init,
                "fill": fill_names[(out_fill, in_fill)],
                "peer_flag": peer[0],
                "zero_keeps": zero_keeps,
                "w1c_clears": w1c,
            }
            if init == "km":
                flush_bit = int(bool(r[5] & m.CTRL_FLUSH))
                ok = (
                    km_post == [0, 0]
                    and m.fld(r[7], m.ST_OUT_EMPTY) == 1
                    and m.fld(r[7], m.ST_IN_EMPTY) == 1
                    and sep_post_d == [0, 0]
                    and flush_bit == 0
                    and peer[0] == 1
                    and zero_keeps
                    and w1c
                )
                fields.update(km_depths=km_post, sep_depths=sep_post_d, km_flush_bit=flush_bit)
                self.chk.obs("KMBOX-FLUSH-TIME", init=init, cell=cell, km_ctrl_polls=r[6])
            else:
                poll_ok = not (sep_ctrl_last & m.S_CTRL_FLUSH)
                ok = (
                    km_post[0] == 0
                    and m.fld(r[7], m.ST_OUT_EMPTY) == 1
                    and sep_post_d[0] == 0
                    and m.fld(sep_post, m.S_OUT_EMPTY) == 1
                    and poll_ok
                    and peer[0] == 1
                    and zero_keeps
                    and w1c
                )
                fields.update(
                    km_out_depth=km_post[0],
                    sep_out_depth=sep_post_d[0],
                    control_km_in_depth=km_post[1],
                    control_sep_in_depth=sep_post_d[1],
                    control_sep_flush_bit=int(bool(sep_ctrl_last & m.S_CTRL_FLUSH)),
                    flushed_seen=r[11],
                )
                self.chk.obs("KMBOX-FLUSH-TIME", init=init, cell=cell, sep_ctrl_polls=polls)
            self.chk.ok("KMBOX-FLUSH", ok, **fields)
            for i in (3, 7):
                self._rsvd("KM_STATUS", r[i], m.ST_FIELDS)
            if init == "km":
                self._rsvd("KM_CTRL", r[4] | r[5] | r[12], m.CTRL_FIELDS)
            else:
                self._rsvd("KM_IRQ_STATUS", r[2] | r[8] | r[9] | r[10], m.IRQ_FIELDS)
            await self._sync()

    # Steps 9 to 13.
    async def _step_irq(self) -> None:
        p = self.plan
        await self._wait((m.PH_IRQ_START,), "the interrupt phase")
        r = self._report(4)
        both = m.CTRL_OVF_RESP | m.CTRL_UDF_RESP
        self._ctrl("KMBOX-IRQ-RESP", (r[0] & m.CTRL_FIELDS) == both, km_ctrl=_h(r[0]))
        self._ctrl(
            "KMBOX-IRQ-START",
            (r[2] & m.CSR_IRQ_FIELDS) == 0 and (r[3] & m.CSR_EN_FIELDS) == 0,
            irq_status_before=_h(r[1]),
            irq_status=_h(r[2]),
            irq_enable=_h(r[3]),
        )
        await self._sync()
        runs = []
        for run in range(2):
            en5 = p.irq_enable_s if run == 0 else (~p.irq_enable_s) & 0x1F
            needs = [s for s in [*p.src_order, 4] if s in (0, 1, 4)]
            while True:
                ph = await self._wait((m.PH_IRQ_NEED, m.PH_IRQ_RUN), f"interrupt run {run}")
                if ph == m.PH_IRQ_RUN:
                    break
                aux = self._word(m.W_AUX)
                want = needs.pop(0) if needs else None
                if (aux >> 8, aux & 0xFF) != (run, want):
                    raise AssertionError(
                        f"IMG-MBOX-KM asked for run {aux >> 8} source {aux & 0xFF}, host expects "
                        f"run {run} source {want}"
                    )
                await self._raise(run, want)
            if needs:
                raise AssertionError(f"interrupt run {run} ended before sources {needs}")
            r = self._report(m.IRQ_RUN_CYCLE_BASE + m.N_CYCLES * m.CYCLE_WORDS)
            if (r[0], r[1]) != (run, en5):
                raise AssertionError(f"IMG-MBOX-KM interrupt run {r[:2]}, host {[run, en5]}")
            runs.append((run, en5, r))
            await self._sync()
        await self._wait((m.PH_IRQ_CTL,), "the KMCSR route control")
        c = self._report(8)
        bit3_ok = bool(c[2] & m.CSR_DRBG) and c[4] == 1
        self._ctrl(
            "KMBOX-IRQ-BIT3",
            bit3_ok,
            irq_status=_h(c[2]),
            bit3_count=c[4],
            bit4_count=c[3],
        )
        self.logger.info(
            "LOG KMBOX-IRQ-CTL irq_status_after_clear=%s irq_enable=%s km_irq_enable=%s",
            _h(c[5]),
            _h(c[6]),
            _h(c[7]),
        )
        await self._sync()
        live = {}
        for run, en5, r in runs:
            self._grade_run(run, en5, r, bit3_ok, live)
        self._ctrl(
            "KMBOX-IRQ-LIVE",
            len(live) == 5 and all(live.values()),
            sources=[int(live.get(s, False)) for s in range(5)],
        )

    async def _raise(self, run: int, src: int) -> None:
        """The host action that raises source ``src`` of interrupt run ``run``."""
        if src == 0:
            await self._sep_wr(KM_MBOX_WRITE_DATA, self.hd.irq_in[run])
        elif src == 1:
            word = await self._sep_rd(KM_MBOX_READ_DATA)
            self.logger.info(
                "LOG KMBOX-IRQ run=%d src1_word=%s plan=%s",
                run,
                _h(word),
                _h(self.plan.out_irq[run][0]),
            )
        else:
            keep = await self._sep_rd(KM_MBOX_CTRL)
            await self._sep_wr(KM_MBOX_CTRL, (keep & m.S_CTRL_FIELDS) | m.S_CTRL_FLUSH)
            last = m.S_CTRL_FLUSH
            for _ in range(_SEP_FLUSH_POLL):
                last = await self._sep_rd(KM_MBOX_CTRL)
                if not last & m.S_CTRL_FLUSH:
                    break
            if last & m.S_CTRL_FLUSH:
                raise AssertionError(f"SEP_CTRL.flush did not read 0 in {_SEP_FLUSH_POLL} reads")
            await self._sync()

    def _grade_run(self, run: int, en5: int, r: list[int], bit3_ok: bool, live: dict) -> None:
        en = m.en_value(en5)
        steps = m.run_steps(self.plan.src_order)
        self._ctrl(
            "KMBOX-IRQ-FULL",
            m.fld(r[7], m.ST_OUT_FULL) == 1 and m.km_depths(r[7])[0] == m.DEPTH,
            run=run,
            km_status=_h(r[7]),
        )
        bad = []
        rise = drop = 0
        quiet = True
        bit3_const = True
        irq_status = 0
        for c, (kind, src, exp) in enumerate(steps):
            base = m.IRQ_RUN_CYCLE_BASE + c * m.CYCLE_WORDS
            kirq, ken, irqst, d4, d3 = r[base : base + m.CYCLE_WORDS]
            line = m.enabled(exp, en)
            irq_status |= irqst & m.CSR_IRQ_FIELDS
            if d3 != 0:
                bit3_const = False
            if not line and d4 != 0:
                quiet = False
            if kind == "raise" and (en & m.EN_SRC[src]) and d4 == 1:
                rise += 1
                live[src] = True
            elif kind == "raise" and (en & m.EN_SRC[src]):
                live.setdefault(src, False)
            if kind == "clear" and not line and d4 == 0:
                drop += 1
            match = (
                (kirq & m.IRQ_FIELDS) == exp
                and (ken & m.EN_FIELDS) == en
                and (irqst & m.CSR_IRQ_FIELDS) == 0
                and d4 == int(line)
                and d3 == 0
            )
            if c == 0:
                self._ctrl("KMBOX-IRQ-IDLE", exp == 0 and d4 == 0, run=run, km_irq=_h(kirq), d4=d4)
            if not match:
                bad.append(
                    f"{kind}{'' if src < 0 else m.SRC_NAMES[src]}:km_irq={_h(kirq)},"
                    f"want={_h(exp)},en={_h(ken)},irq={_h(irqst)},d4={d4},line={int(line)},d3={d3}"
                )
            self._rsvd("KM_IRQ_STATUS", kirq, m.IRQ_FIELDS)
            self._rsvd("KM_IRQ_ENABLE", ken, m.EN_FIELDS)
        self.chk.ok(
            "KMBOX-IRQ",
            not bad and bit3_ok,
            en=f"0x{en5:02x}",
            run="S" if run == 0 else "notS",
            cycles=len(steps),
            enabled_rise=rise,
            disabled_quiet=quiet,
            drop_after_clear=drop,
            irq_status=f"0x{irq_status:03x}",
            ctrl_irq_set_bit3=bit3_ok,
            bit3_const_during_mbox=bit3_const,
            mismatches=len(bad),
        )
        for line in bad:
            self.logger.info("LOG KMBOX-IRQ-MISMATCH run=%d %s", run, line)
        self.logger.info(
            "LOG KMBOX-IRQ run=%d km_status_after_clear=%s km_irq_after_clear=%s src0_word=%s "
            "src0_plan=%s src3_data=%s",
            run,
            _h(r[2]),
            _h(r[3]),
            _h(r[4]),
            _h(self.hd.irq_in[run]),
            _h(r[5]),
        )

    # Step 14.
    async def _step_end(self) -> None:
        await self._wait((m.PH_END,), "the end of the script")
        r = self._report(1)
        st = await self._sep_rd(KM_MBOX_STATUS)
        drained = 0
        while not m.fld(st, m.S_OUT_EMPTY) and drained < m.DEPTH:
            await self._sep_rd(KM_MBOX_READ_DATA)
            drained += 1
            st = await self._sep_rd(KM_MBOX_STATUS)
        self.logger.info(
            "LOG KMBOX-DRAIN km_status=%s sep_status=%s outbound_drained=%d inbound_left=%d",
            _h(r[0]),
            _h(st),
            drained,
            m.sep_depths(st)[1],
        )
        for name, (bits, fields) in sorted(self.rsvd.items()):
            self.logger.info(
                "LOG rsvd reg=%s bits=%s mask=%s", name, _h(bits), _h(~fields & m.WORD)
            )

    def _grade_nonvac(self) -> None:
        self._ctrl(
            "KMBOX-BUS-CLEAN",
            self.bus_seen > 0 and not self.bus_bad,
            publishes=self.bus_seen,
            bad=self.bus_bad,
        )
        self.chk.ok(
            "NONVAC",
            bool(self.controls) and all(self.controls.values()),
            controls=len(self.controls),
            missing=sorted(k for k, v in self.controls.items() if not v),
        )

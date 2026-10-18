# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A sense response with its status bit set leaves one shadow word at reset; a late program response.

Leg A: a shim response whose status bit is set during sensing still advances the
sensing word counter and leaves that shadow word unwritten, so it reads its reset
value 0x0, and sense done still rises. Every other word loads its staged value.
Leg B: a program request that waits for its shim response, with the program timeout
disabled, shows ``program_busy`` and not ``program_done`` while it waits, and shows
``program_done`` with ``program_status`` 0 and no busy after the response.

Sources: ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (section Fuse Sensing and Boot
Sequencing, the sensing sequence: a strobe with its status bit set advances the counter
and leaves that word unwritten); ``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc``
(reset value 0x0 of every field except ``LC_STATE``);
``hw/ip/efuse/regs/gen/adoc/efuse_interface_ctrl.adoc`` (``EFUSE_INTERFACE_CTRL_STATUS``,
``EFUSE_PROGRAM_CTRL``, ``EFUSE_PROGRAM_REQ_TIMEOUT``); ``hw/ip/efuse/doc/interface.adoc``
(section Fuse Command Protocol, the response status bit).

Image: fixed TEST_DEV image of ``env/sep_efuse_plan.py`` (non-zero distinct words in
shadow words 10 to 254, no lock bit), written before the first reset. Draws:
``plan(test, seed)`` (word class and word w, spare bits a, b, c, timeout cycles T, hold
multiple m).

Hooks: ``efuse_sense_status_inject_i`` with ``efuse_sense_status_word_i`` (status bit on
the sense response of word w) and ``efuse_shim_resp_hold_i`` (the shim response of a
program request is withheld while it is high).

Checkers:
  CHK-SENSE-STATUS  in the injected sense, sense done rises within the bound, word w
                    reads 0x0 at ``efuse_shadow_probe_o`` and at the frontdoor, every
                    other word equals its staged value, and ``efuse_sense_done`` reads 1.
                    Control: the first sense loads word w with its non-zero staged value.
  CHK-PROG-LIFE     with the response held, ``program_busy`` 1 and ``program_done`` 0 at
                    every clock of the window and every frontdoor read; after the
                    release done 1, status 0, busy 0 and the bit reads 1 at the direct
                    read. Control: the same program without a hold completes and burns.
                    Hook control: the held window shows at least two program commands to
                    the bit at ``efuse_shim_command_req_o`` (``CHK-HOOK FAIL`` otherwise).

Log-only: ``CHK-PROG-TIMEOUT INFO`` (busy, done and status after m x T clocks of a held
program with the timeout enabled; the specification does not state the report).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_image import SHADOW_BASE
from env.sep_efuse_plan import (
    PROGRAM_CTRL_ADDR,
    STATUS_ADDR,
    T_SHIM_FAULT,
    plan,
    program_ctrl_word,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    clocks_to_sense,
    direct_word,
    probe_words,
    rst_pulse,
    set_shadow_golden,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL

TEST = T_SHIM_FAULT

_IC = EFUSE_INTERFACE_CTRL
_PG_TMO_ADDR = _IC.addr("EFUSE_PROGRAM_REQ_TIMEOUT")
_TMO_EN = _IC.field_mask("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_enable")
_TMO_CYC = _IC.field_mask("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_cycles")
_TMO_CYC_RESET = _IC.field_reset("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_cycles")
_M_SENSE_DONE = _IC.field_mask("EFUSE_INTERFACE_CTRL_STATUS", "efuse_sense_done")
_M_PG_BUSY = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_busy")
_M_PG_DONE = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_M_PG_STATUS = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_status")
_WORD = 0xFFFF_FFFF
_N_WORDS = 256

# Test parameters (the contract leaves them to the test).
_FIRST_SENSE_BOUND = 20_000
_SENSE_BOUND_MULT = 4  # injected-sense bound, in sense times
_HOLD_MULT = 2  # held window, in sense times (over the 64-clock sampler window)
_HOLD_READS = 4  # frontdoor reads of EFUSE_PROGRAM_CTRL inside the held window
_POLL_BOUND_MULT = 4  # bound of a program_done or busy poll, in sense times
_REL_SETTLE = 128  # clocks after the release done (over the 64-clock sampler window)
_RST_HOLD = 20


def _b(v: int, m: int) -> int:
    return int(bool(v & m))


@pyuvm.test()
class sep_efuse_shim_response_fault_test(sep_base_test):
    """Sense status bit on one word; program lifecycle with a withheld shim response."""

    required_evidence = ("CHK-SENSE-STATUS", "CHK-PROG-LIFE")

    async def _rd(self, addr: int) -> int:
        return await self.fd.rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.fd.wr(addr, data)

    async def _direct_bit(self, spare: dict) -> tuple[int, int]:
        """(word, bit) of a programmed spare bit at the direct OTP read."""
        word = await direct_word(self, spare["addr"] // 32)
        return word, (word >> spare["bit"]) & 1

    def _probe_words(self) -> list[int]:
        return probe_words(self, cocotb.top.efuse_shadow_probe_o, _N_WORDS)

    async def _poll_pg(self, mask: int, bound: int) -> int | None:
        """Read ``EFUSE_PROGRAM_CTRL`` until every bit of ``mask`` is 1; None at the bound."""
        dut = cocotb.top
        start = self.clk
        while self.clk - start < bound:
            v = await self._rd(PROGRAM_CTRL_ADDR)
            if v & mask == mask:
                return v
            await ClockCycles(dut.clk_i, 8)
        return None

    async def _clk_counter(self) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_i)
            self.clk += 1

    def _set_golden(self) -> None:
        """Post-sense shadow golden of the base test: the staged image plus burned bits."""
        set_shadow_golden(self, self.p.image, burned=[b["addr"] for b in self.burned])

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.seed = seed = self.random_seed()
        self.p = p = plan(TEST, seed)
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        w = int(p.leg["word"])
        staged = list(p.image.words)
        if not (10 <= w <= 254) or staged[w] == 0 or staged[w + 1] == 0:
            raise AssertionError(f"SETUP FAIL seed={seed} reason=word_filter w={w}")
        a, b, c = p.leg["spare_a"], p.leg["spare_b"], p.leg["spare_c"]
        t_cyc, m = int(p.leg["timeout_T"]), int(p.leg["hold_m"])
        self.burned: list[dict] = []
        close_graded_window(self.logger)
        dut.efuse_sense_status_inject_i.value = 0
        dut.efuse_sense_status_word_i.value = 0
        dut.efuse_shim_resp_hold_i.value = 0
        self.clk = 0
        cocotb.start_soon(self._clk_counter())

        # Steps 2-3: fixed image, strap 0; control sense with both injects low.
        self.write_efuse_image(p.image)
        timer = cocotb.start_soon(clocks_to_sense(self, _FIRST_SENSE_BOUND, started=False))
        await self.bring_up_no_cpu(max_cycles=_FIRST_SENSE_BOUND)
        t_sense = await timer
        if t_sense is None:
            raise AssertionError("sense time not measured")
        await ClockCycles(dut.clk_i, 1)
        self.suppress_host_axi_transaction_info()
        sense_bound = _SENSE_BOUND_MULT * t_sense
        poll_bound = _POLL_BOUND_MULT * t_sense
        hold_win = _HOLD_MULT * t_sense
        self.logger.info(
            "SHIM PARAM seed=%d t_sense=%d sense_bound=%d hold_win=%d hold_reads=%d "
            "poll_bound=%d rel_settle=%d",
            seed,
            t_sense,
            sense_bound,
            hold_win,
            _HOLD_READS,
            poll_bound,
            _REL_SETTLE,
        )
        ctl_probe = self._probe_words()
        ctl_w = await self._rd(SHADOW_BASE + 4 * w)
        ctl_w1 = await self._rd(SHADOW_BASE + 4 * (w + 1))
        ctl_ok = ctl_probe == staged and ctl_w == staged[w] and ctl_w1 == staged[w + 1]
        self.chk.ctrl(
            "SENSE-STATUS",
            ctl_ok,
            word=w,
            ctl_word=f"0x{ctl_w:08x}",
            ctl_next=f"0x{ctl_w1:08x}",
            staged=f"0x{staged[w]:08x}",
            probe_equal=sum(int(x == y) for x, y in zip(ctl_probe, staged)),
        )

        # Steps 4-5: injected sense at word w.
        dut.efuse_sense_status_word_i.value = w
        dut.efuse_sense_status_inject_i.value = 1
        open_graded_window(TEST, self.logger)
        await rst_pulse(self, hold=_RST_HOLD)
        n = await clocks_to_sense(self, sense_bound, started=True)
        await ClockCycles(dut.clk_i, 20)
        close_graded_window(self.logger)
        probe = self._probe_words()
        got_w = await self._rd(SHADOW_BASE + 4 * w)
        got_w1 = await self._rd(SHADOW_BASE + 4 * (w + 1))
        status = await self._rd(STATUS_ADDR)
        dut.efuse_sense_status_inject_i.value = 0
        others = [i for i in range(_N_WORDS) if i != w and probe[i] != staged[i]]
        self.chk.ok(
            "SENSE-STATUS",
            n is not None
            and ctl_ok
            and probe[w] == 0
            and got_w == 0
            and got_w1 == staged[w + 1]
            and not others
            and _b(status, _M_SENSE_DONE) == 1,
            word=w,
            word_class=p.leg["word_class"],
            got_probe=f"0x{probe[w]:x}",
            got_read=f"0x{got_w:x}",
            staged=f"0x{staged[w]:08x}",
            next_read=f"0x{got_w1:08x}",
            others_equal=int(not others),
            others_bad=",".join(str(i) for i in others[:8]) or "none",
            sense_done=int(n is not None),
            t_sense_inj="none" if n is None else n,
            status_sense_done=_b(status, _M_SENSE_DONE),
            ctl_word=f"0x{ctl_w:08x}",
        )

        # Step 6: control program of a, no hold.
        await self.pulse_rst_ni(max_sense_cycles=sense_bound)
        await self._wr(_PG_TMO_ADDR, _TMO_CYC_RESET)
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(a["addr"], data=1, read_back=0))
        pg = await self._poll_pg(_M_PG_DONE, poll_bound)
        pg = await self._rd(PROGRAM_CTRL_ADDR) if pg is not None else None
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        ctl_word_a, ctl_bit = await self._direct_bit(a)
        ctl_done = pg is not None and _b(pg, _M_PG_DONE) == 1
        ctl_clean = pg is not None and _b(pg, _M_PG_STATUS) == 0 and _b(pg, _M_PG_BUSY) == 0
        self.chk.ctrl(
            "PROG-LIFE",
            ctl_done and ctl_clean and ctl_bit == 1,
            bit_addr=a["addr"],
            ctl_done=int(ctl_done),
            ctl_pg="none" if pg is None else f"0x{pg:08x}",
            ctl_bit_read=ctl_bit,
            ctl_word=f"0x{ctl_word_a:08x}",
        )
        self.burned.append(a)
        self._set_golden()

        # Steps 7-9: held program of b.
        await self.pulse_rst_ni(max_sense_cycles=sense_bound)
        pg_reset = await self._rd(PROGRAM_CTRL_ADDR)
        await self._wr(_PG_TMO_ADDR, _TMO_CYC_RESET)
        cmds = SepShimCmdMonitor(dut).start()
        m_go = cmds.mark()
        dut.efuse_shim_resp_hold_i.value = 1
        open_graded_window(TEST, self.logger)
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(b["addr"], data=1))
        busy_seen = None
        start = self.clk
        while self.clk - start < poll_bound:
            v = await self._rd(PROGRAM_CTRL_ADDR)
            if _b(v, _M_PG_BUSY) and self.rd(dut.efuse_program_busy_o):
                busy_seen = v
                break
        held = {"n": 0, "bad": 0, "first_bad": None}

        async def _sample() -> None:
            for _ in range(hold_win):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                held["n"] += 1
                busy = self.rd(dut.efuse_program_busy_o)
                done = self.rd(dut.efuse_program_done_o)
                if busy != 1 or done != 0:
                    held["bad"] += 1
                    if held["first_bad"] is None:
                        held["first_bad"] = (held["n"], busy, done)

        reads: list[int] = []
        if busy_seen is not None:
            task = cocotb.start_soon(_sample())
            gap = hold_win // (_HOLD_READS + 1)
            for _ in range(_HOLD_READS):
                await ClockCycles(dut.clk_i, gap)
                reads.append(await self._rd(PROGRAM_CTRL_ADDR))
            await task
            await ClockCycles(dut.clk_i, 1)
        held_cmds = len(cmds.programs_since(m_go, address=b["addr"]))
        held_busy = int(
            busy_seen is not None
            and held["bad"] == 0
            and held["n"] == hold_win
            and len(reads) == _HOLD_READS
            and all(_b(r, _M_PG_BUSY) for r in reads)
        )
        held_done = int(busy_seen is None or any(_b(r, _M_PG_DONE) for r in reads))
        dut.efuse_shim_resp_hold_i.value = 0
        rel = await self._poll_pg(_M_PG_DONE, poll_bound)
        rel = await self._rd(PROGRAM_CTRL_ADDR) if rel is not None else None
        await ReadOnly()
        p_busy = self.rd(dut.efuse_program_busy_o)
        p_done = self.rd(dut.efuse_program_done_o)
        p_err = self.rd(dut.efuse_program_error_o)
        await ClockCycles(dut.clk_i, _REL_SETTLE)
        close_graded_window(self.logger)
        await cmds.stop()
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        word_b, bit_b = await self._direct_bit(b)
        hook = held_cmds >= 2
        fields = {"check": "PROG-LIFE", "held_prog_cmds": held_cmds, "bit_addr": b["addr"]}
        if hook:
            self.chk.ctrl("HOOK", True, **fields)
        else:
            self.chk.ok("HOOK", False, **fields)
        rel_done = rel is not None and _b(rel, _M_PG_DONE) == 1
        rel_status = None if rel is None else _b(rel, _M_PG_STATUS)
        rel_busy = None if rel is None else _b(rel, _M_PG_BUSY)
        self.chk.ok(
            "PROG-LIFE",
            hook
            and held_busy == 1
            and held_done == 0
            and rel_done
            and rel_status == 0
            and rel_busy == 0
            and bit_b == 1
            and ctl_done
            and ctl_clean
            and ctl_bit == 1,
            bit_addr=b["addr"],
            held_busy=held_busy,
            held_done=held_done,
            held_samples=held["n"],
            held_bad=held["bad"],
            held_first_bad="none" if held["first_bad"] is None else held["first_bad"],
            held_reads=",".join(f"0x{r:08x}" for r in reads) or "none",
            rel_done=int(rel_done),
            rel_status="none" if rel_status is None else rel_status,
            rel_busy="none" if rel_busy is None else rel_busy,
            rel_probe=f"{p_busy}{p_done}{p_err}",
            bit_read=bit_b,
            word_read=f"0x{word_b:08x}",
            ctl_done=int(ctl_done),
            ctl_bit_read=ctl_bit,
            pg_after_reset=f"0x{pg_reset:08x}",
        )
        self.burned.append(b)
        self._set_golden()

        # Step 10: timeout cell, logged only.
        await self.pulse_rst_ni(max_sense_cycles=sense_bound)
        await self._wr(_PG_TMO_ADDR, _TMO_EN | (t_cyc & _TMO_CYC))
        dut.efuse_shim_resp_hold_i.value = 1
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(c["addr"], data=1))
        await ClockCycles(dut.clk_i, m * t_cyc)
        v = await self._rd(PROGRAM_CTRL_ADDR)
        dut.efuse_shim_resp_hold_i.value = 0
        self.logger.info(
            "CHK-PROG-TIMEOUT INFO seed=%d cycles=%d held=%dx busy=%d done=%d status=%d bit_addr=%d",
            seed,
            t_cyc,
            m,
            _b(v, _M_PG_BUSY),
            _b(v, _M_PG_DONE),
            _b(v, _M_PG_STATUS),
            c["addr"],
        )
        await ClockCycles(dut.clk_i, 64)
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        self.chk.finish()

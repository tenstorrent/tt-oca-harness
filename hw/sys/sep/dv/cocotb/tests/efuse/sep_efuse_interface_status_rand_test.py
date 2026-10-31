# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read and program interface status flags, empty program, accepted twins, no program before sense done.

A read go with ``read_enable`` clear sets ``read_status``. A read or program address
of 8192 or more sets its own address-error flag (and ``read_status`` for a read), and
the flag clears by write-one. A request that a lock blocks sets ``efuse_req_error`` and
neither address-error flag. ``program_enable`` keeps a read from reaching the bank. No
bank bit changes from reset release until sense completes. A program with data 0
programs nothing and sets no flag.

Sources: ``hw/ip/efuse/regs/gen/adoc/efuse_interface_ctrl.adoc``
(``EFUSE_INTERFACE_CTRL_STATUS``, ``EFUSE_PROGRAM_CTRL``, ``EFUSE_READ_CTRL``; field
``efuse_data``: a program with data 0 is ignored); ``hw/ip/efuse/doc/architecture.adoc``
(section Command-path ownership); ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (opening
section: the command multiplexer gives automatic sensing priority until it completes;
section Fuse Fields: 256 words of 32 bits, so 8192 bits); ``hw/ip/efuse/doc/interface.adoc``
(total storage capacity).

Image: prestaged from ``plan(test, seed)`` of ``env/sep_efuse_plan.py``: TEST_DEV, a
burned write-lock slot and a burned read-lock slot, filter-legal pair. The plan also
draws the case order, the out-of-range address and every program and read bit.

"Run a program" / "run a read" is one control write with enable, address and go, a
wait of the full window W (``_W_MULT`` x the sense time measured at the first sense,
no early exit), then reads of ``EFUSE_INTERFACE_CTRL_STATUS``, ``EFUSE_READ_CTRL`` and
``EFUSE_PROGRAM_CTRL``; both busy bits must read 0.

Checkers:
  CHK-IF-STATUS    the error flags and ``read_status`` of each refusal case and of the
                   data-0 program equal the case golden (the lock-blocked read grades
                   the three error flags, not ``read_status``); each clear bit clears
                   its flag only.
  CTRL-IF-GO-LANDED  after each refused go (pre-sense, each JTAG pre-sense leg, both
                   enables, data 0) the software-owned fields of the written control
                   register read back as written, so a go that did not land fails.
  CHK-IF-CMD       the data-0 program leaves the bank unchanged; the program of a 0 bit
                   of the write-locked field leaves the bank unchanged
                   (``efuse_program_go``: ignored when the lock bit is set;
                   ``hw/sys/sep/doc/otp_fuse_controller.adoc``: a write-lock blocks
                   fuse programming); no read command at
                   ``efuse_shim_command_req_o`` for the lock-blocked read (go to end of
                   W) and the both-enables read (go to the cold reset assertion); the
                   accepted read twin of each shows its read command.
  CHK-IF-CTRL      every case starts with clean flags (case frame), and each refusal
                   case has an accepted twin that completes (program twins change the
                   bank by exactly their bit at ``otp_bank_probe_o``).
  CHK-IF-PRESENSE  a JTAG program go issued before sense done changes no bank bit and
                   sends no program command from reset release to the sense-done rise;
                   the post-sense twin lands with its command. ``CHK-HOOK FAIL`` when
                   ``t_go + t_land`` is not shorter than ``t_sense``. The core is held
                   in reset until sensing completes (``hw/sys/sep/doc/reset_controller.adoc``),
                   so the go runs on the OTP JTAG port; its response is logged in
                   ``OBS-IF-STATUS-FLAGS`` (``go_resp``).
  CHK-IF-PRESENSE-JTAG  from the reset release to the sense-done rise, a JTAG read
                   of a shadow-map word is not OKAY and does not return the staged
                   word, and a JTAG program go sends no program command and changes
                   no bank bit; sense done reads 0 when each JTAG access completes.
                   The same line carries the positive probes: after the rise the
                   same JTAG read is OKAY and returns the staged word, the sensed
                   shadow word equals it, and the JTAG program twin
                   (``CTRL-IF-PRESENSE-JTAG-TWIN``) landed. ``CHK-HOOK FAIL ...
                   check=IF-PRESENSE-JTAG`` when a JTAG access completes after the
                   rise. The refused map read returns SLVERR. Golden:
                   ``hw/sys/sep/doc/otp_fuse_controller.adoc:103`` (until sense
                   done, APB accesses to the MAP window return SLVERR), ``:41-44``
                   (the JTAG port merges into the same AXI-Lite to APB bridge;
                   the lifecycle filter answers only a blocked access),
                   ``:130-131`` (programming only after LOCKS is sensed);
                   ``hw/sys/sep/doc/lifecycle_controller.adoc:714-721`` (TEST_DEV
                   JTAG reaches the shadow map and the program controls, so the
                   filter blocks neither access; nothing on the path executes
                   before sensing completes). The response of the JTAG program
                   write is logged (``OBS-IF-PRESENSE-JTAG-RESP``).

The JTAG case runs right after the pre-sense case. Its first leg is graded with
the FCOV owner window closed; only when that leg passed does a second leg run with
the window open from before the ``rst_ni`` fall to its own grade, and it is graded
the same way.

FCOV owner window (``env/sep_fcov_gate.py``): the first FAIL or missing control
closes it, and it stays closed for the rest of the run. Every sample of the leaf
(``sep_efuse_if_status_cg`` and ``x_jtag_presense``) is held with the tag of its
graded step (``set_ef_hold_tag``) and samples only when the leaf writes that tag
to the pass label (``set_ef_hold_pass``) after every check of the step passed. An
event outside a graded step is dropped.

Log-only: the flags of the pre-sense and both-enables cases
(``OBS-IF-STATUS-FLAGS``), ``read_status`` (``OBS-IF-LOCK-READ-STATUS``) and the data of
the lock-blocked read, the bank
diff after the out-of-range program cases (``OBS-IF-CMD``), the
count of post-guard commands (``efuse_shim_cmd_*_o``) of each out-of-range read and
program (``OBS-IF-OOB-CMD``). ``OBS-EFUSE-SHIM-DBG`` logs ``efuse_debug_bus_o``
sampled on every ``clk_i`` from the first case frame to the end of the leaf: the OR of
the write and read counter-error bits [12] and [4], the write and read FSM states
[11:8] and [3:0] seen, and the OR of the other bits. No legal stimulus makes a
counter error, so the line shows only that the bits stay 0 under these reads and
programs; it cannot show that a counter error sets them.
Two bench records grade nothing: the procedure gives the out-of-range program no
accepted twin (``INFO-IF-CTRL-NO-TWIN``), and after the both-enables case the leaf
clears ``read_enable`` before ``program_enable`` (``INFO-IF-ENABLE-CLEAR-ORDER``).
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import (
    PROGRAM_COMMANDS,
    SepEfuseBank,
    SepEfuseBankWatch,
    SepShimCmdMonitor,
    bank_diff,
    diff_is_exactly,
    diff_log,
    is_command_edge,
)
from env.sep_efuse_plan import (
    FIELD_NAMES,
    LOCK_SLOT_FIELD,
    PROGRAM_CTRL_ADDR,
    READ_CTRL_ADDR,
    SPARE_FIELDS,
    STATUS_ADDR,
    T_IF_STATUS,
    bit_address,
    field_n_words,
    field_word,
    plan,
    program_ctrl_word,
    read_ctrl_word,
    shadow_addr,
    zero_bits,
)
from env.sep_efuse_test_lib import (
    M32,
    SepEfuseFd,
    clocks_to_sense,
    rst_pulse,
    set_shadow_golden,
    shadow_word,
)
from env.sep_fabric_common import RESP_NAME, RESP_OKAY, RESP_SLVERR
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_ef_hold_pass,
    set_ef_hold_tag,
)
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL

TEST = T_IF_STATUS

_IC = EFUSE_INTERFACE_CTRL
_ST = "EFUSE_INTERFACE_CTRL_STATUS"
_M_RE = _IC.field_mask(_ST, "efuse_req_error")
_M_PAE = _IC.field_mask(_ST, "efuse_program_addr_error")
_M_RAE = _IC.field_mask(_ST, "efuse_read_addr_error")
_M_CLR_RE = _IC.field_mask(_ST, "efuse_req_error_clear")
_M_CLR_PAE = _IC.field_mask(_ST, "efuse_program_addr_error_clear")
_M_CLR_RAE = _IC.field_mask(_ST, "efuse_read_addr_error_clear")
_M_RS = _IC.field_mask("EFUSE_READ_CTRL", "read_status")
_M_RD_BUSY = _IC.field_mask("EFUSE_READ_CTRL", "read_busy")
_M_RD_DONE = _IC.field_mask("EFUSE_READ_CTRL", "read_done")
_M_PG_BUSY = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_busy")
_M_PG_DONE = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_M_PG_STATUS = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_status")
# Software-owned (sw=rw, hw=r) fields of each control register: they read back as written.
_M_PG_RW = (
    _IC.field_mask("EFUSE_PROGRAM_CTRL", "efuse_addr")
    | _IC.field_mask("EFUSE_PROGRAM_CTRL", "efuse_data")
    | _IC.field_mask("EFUSE_PROGRAM_CTRL", "efuse_program_read_back")
    | _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_enable")
)
_M_RD_RW = _IC.field_mask("EFUSE_READ_CTRL", "efuse_addr") | _IC.field_mask(
    "EFUSE_READ_CTRL", "read_enable"
)
_BIT_8191 = 8191  # last bit of the 8192-bit OTP (256 words of 32 bits)

# Test parameters (the contract leaves them to the test).
_W_MULT = 2  # W = _W_MULT x sense time
_SENSE_BOUND_MULT = 4  # bound of a sense wait, in sense times
_FIRST_SENSE_BOUND = 20_000
_BOTH_WAIT = 2048  # clocks after the both-enables go (over the 1024-clock sampler window)
_CLEAR_SETTLE = 16  # clocks after a status clear write before the next write
_RST_HOLD = 20
_FCOV_SETTLE = 4  # clocks after the sense-done rise before the post-sense JTAG read
_PASS_HOLD = 2  # clocks the step tag stays on the pass label
# efuse_debug_bus_o: {3'b0, write counter err, write FSM, 3'b0, read counter err, read FSM}.
_DBG_WR_ERR = 1 << 12
_DBG_RD_ERR = 1 << 4
_DBG_OTHER = 0xE0E0


def _b(v: int, m: int) -> int:
    return int(bool(v & m))


@pyuvm.test()
class sep_efuse_interface_status_rand_test(sep_base_test):
    """Interface status per refusal case, accepted twins, empty program, pre-sense program."""

    required_evidence = (
        "CHK-IF-STATUS",
        "CHK-IF-CMD",
        "CHK-IF-CTRL",
        "CHK-IF-PRESENSE",
        "CHK-IF-PRESENSE-JTAG",
    )

    # -- grading and the owner window ----------------------------------------

    def _grade(self, name: str, cond: bool, **fields: Any) -> bool:
        """Grade one check; a FAIL closes the owner window first, for the rest of the run."""
        cond = bool(cond)
        if not cond:
            close_graded_window(self.logger)
            self._fcov_dead = True
        return self.chk.ok(name, cond, **fields)

    def _ctrl(self, name: str, cond: bool, **fields: Any) -> bool:
        """Log one control; a missing control closes the owner window like a FAIL."""
        cond = bool(cond)
        if not cond:
            close_graded_window(self.logger)
            self._fcov_dead = True
        return self.chk.ctrl(name, cond, **fields)

    def _open_window(self) -> None:
        """Open the owner window, unless a check or control of this run has failed."""
        if self._fcov_dead:
            self.logger.info("FCOV-GATE stays closed after a FAIL")
            return
        open_graded_window(TEST, self.logger)

    def _step(self) -> int:
        """Start a graded step: every later sample carries a new hold tag."""
        self._tag += 1
        set_ef_hold_tag(self._tag, self.logger)
        return self._tag

    async def _pass(self, tag: int, ok: bool) -> None:
        """End step ``tag``; its held samples sample only when ``ok`` and no FAIL so far."""
        set_ef_hold_tag(0, self.logger)
        if not ok or self._fcov_dead:
            return
        set_ef_hold_pass(tag, self.logger)
        await ClockCycles(cocotb.top.clk_i, _PASS_HOLD)
        set_ef_hold_pass(0, self.logger)

    # -- frontdoor ----------------------------------------------------------

    async def _rd(self, addr: int) -> int:
        return await self.fd.rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.fd.wr(addr, data)

    async def _flags(self) -> dict[str, int]:
        """Status, read-control and program-control bits after a case."""
        st = await self._rd(STATUS_ADDR)
        rc = await self._rd(READ_CTRL_ADDR)
        pg = await self._rd(PROGRAM_CTRL_ADDR)
        return {
            "rs": _b(rc, _M_RS),
            "rae": _b(st, _M_RAE),
            "pae": _b(st, _M_PAE),
            "re": _b(st, _M_RE),
            "rd_busy": _b(rc, _M_RD_BUSY),
            "rd_done": _b(rc, _M_RD_DONE),
            "pg_busy": _b(pg, _M_PG_BUSY),
            "pg_done": _b(pg, _M_PG_DONE),
            "pg_status": _b(pg, _M_PG_STATUS),
        }

    @staticmethod
    def _s4(f: dict[str, int]) -> str:
        """{read_status, efuse_read_addr_error, efuse_program_addr_error, efuse_req_error}."""
        return f"0b{f['rs']}{f['rae']}{f['pae']}{f['re']}"

    @staticmethod
    def _idle(f: dict[str, int]) -> bool:
        return f["rd_busy"] == 0 and f["pg_busy"] == 0

    async def _run_program(self, bit_addr: int, *, data: int = 1) -> dict[str, int]:
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(bit_addr, data=data))
        await ClockCycles(cocotb.top.clk_i, self.w)
        return await self._flags()

    async def _run_read(self, bit_addr: int, *, enable: int = 1) -> dict[str, int]:
        await self._wr(READ_CTRL_ADDR, read_ctrl_word(bit_addr, enable=enable))
        await ClockCycles(cocotb.top.clk_i, self.w)
        return await self._flags()

    async def _clear(self, mask: int) -> dict[str, int]:
        await self._wr(STATUS_ADDR, mask)
        await ClockCycles(cocotb.top.clk_i, _CLEAR_SETTLE)
        return await self._flags()

    def _landed(self, case: str, reg: str, wrote: int, got: int) -> bool:
        """CTRL-IF-GO-LANDED: the software-owned fields of a refused go read back as written."""
        m = _M_PG_RW if reg == "EFUSE_PROGRAM_CTRL" else _M_RD_RW
        return self._ctrl(
            "IF-GO-LANDED",
            (got & m) == (wrote & m),
            case=case,
            reg=reg,
            wrote=f"0x{wrote & m:08x}",
            readback=f"0x{got & m:08x}",
        )

    # -- reset and sense ----------------------------------------------------

    async def _rst_pulse(self) -> int:
        """Cold reset with no sense wait; returns the shim-monitor clock at the fall."""
        await RisingEdge(cocotb.top.clk_i)
        c_fall = self.cmds.clk
        await rst_pulse(self, hold=_RST_HOLD)
        return c_fall

    def _golden_from_bank(self) -> None:
        """Post-sense shadow golden of the base test: the bank as it stands now.

        Programs of earlier cases stay in the bank, and the pre-sense case does not
        say whether its held program runs after sense, so the next sense loads the
        current bank content.
        """
        set_shadow_golden(self, self.p.image, words=self.bank.read())

    async def _cold_reset(self) -> None:
        self._golden_from_bank()
        await self.pulse_rst_ni(max_sense_cycles=self.sense_bound)

    # -- case frame ---------------------------------------------------------

    async def _clean_ctrl(self) -> None:
        """Both control registers 0 and every error flag cleared."""
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        await self._wr(READ_CTRL_ADDR, 0)
        await self._wr(STATUS_ADDR, _M_CLR_RE | _M_CLR_PAE | _M_CLR_RAE)
        await ClockCycles(cocotb.top.clk_i, _CLEAR_SETTLE)

    async def _frame(self, case: str) -> tuple[int, ...]:
        """Procedure step 4: clean flags, one accepted read, bank snapshot."""
        close_graded_window(self.logger)
        await self._clean_ctrl()
        f = await self._run_read(self.reads["frame"]["addr"])
        clean = self._s4(f) == "0b0000" and f["rd_done"] == 1 and self._idle(f)
        self._grade(
            "IF-CTRL",
            clean,
            case=f"frame.{case}",
            accepted=1,
            flags=self._s4(f),
            landed="na",
            read_done=f["rd_done"],
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )
        snap = self.bank.read()
        self._open_window()
        return snap

    def _twin_program(self, case: str, f: dict[str, int], diff: list, addr: int) -> bool:
        landed = diff_is_exactly(diff, addr)
        ok = (
            f["pg_done"] == 1
            and self._idle(f)
            and self._s4(f) == "0b0000"
            and f["pg_status"] == 0
            and landed
        )
        self._grade(
            "IF-CTRL",
            ok,
            case=case,
            accepted=1,
            flags=self._s4(f),
            landed=int(landed),
            read_done="na",
            bit_addr=addr,
            pg_done=f["pg_done"],
            pg_status=f["pg_status"],
            diff=diff_log(diff),
        )
        return ok

    def _twin_read(self, case: str, f: dict[str, int], addr: int, read_cmds: int) -> bool:
        """Accepted read: one READ at ``addr`` on the shim tap, read_done=1, idle, flags 0.

        read_done stays 1 from the frame read, so the shim command count is the
        evidence that this go made a new read.
        """
        ok = read_cmds == 1 and f["rd_done"] == 1 and self._idle(f) and self._s4(f) == "0b0000"
        self._grade(
            "IF-CTRL",
            ok,
            case=case,
            accepted=1,
            flags=self._s4(f),
            landed="na",
            read_done=f["rd_done"],
            read_cmds=read_cmds,
            bit_addr=addr,
        )
        return ok

    async def _accepted_read(self, case: str, bit_addr: int) -> tuple[int, bool]:
        """Run an enabled read and grade it as the accepted twin; returns (READ count, pass)."""
        mark = self.cmds.mark()
        f = await self._run_read(bit_addr)
        n = len(self.cmds.reads_since(mark, address=bit_addr))
        return n, self._twin_read(case, f, bit_addr, n)

    def _status(
        self, case: str, addr: int, f: dict[str, int], exp: str, cleared: Any, ok_clear: bool
    ) -> bool:
        return self._grade(
            "IF-STATUS",
            self._s4(f) == exp and self._idle(f) and ok_clear,
            case=case,
            addr=addr,
            status=self._s4(f),
            exp=exp,
            cleared=cleared,
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )

    # -- cases --------------------------------------------------------------

    async def _case_presense(self) -> None:
        """Steps 6-7: program go before sense done, then the post-sense twin."""
        dut = cocotb.top
        bit = self.progs["pre_sense"]["addr"]
        self._golden_from_bank()
        self._open_window()
        tag = self._step()
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, _RST_HOLD)
        task, win = self._start_presense_monitor(self.bank.read())
        dut.rst_ni.value = 1
        # First access after the release: one write with enable, data 1, address, go.
        # The core is held in reset until sensing completes, so the go runs on
        # the OTP JTAG port, the master that exists then.
        go = program_ctrl_word(bit, data=1)
        go_resp, _ = await self.jtag_axil_op(write=True, addr=PROGRAM_CTRL_ADDR, wdata=go)
        sense_at_go = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        t_go = win["n"]
        await task
        t_sense = win["t_sense"]
        await ClockCycles(dut.clk_i, self.w)
        landed = self._landed(
            "pre_sense", "EFUSE_PROGRAM_CTRL", go, await self._rd(PROGRAM_CTRL_ADDR)
        )
        f = await self._flags()
        self.chk.obs(
            "IF-STATUS-FLAGS",
            case="pre_sense",
            addr=bit,
            go_resp=RESP_NAME.get(go_resp, go_resp),
            status=self._s4(f),
            pg_done=f["pg_done"],
            pg_busy=f["pg_busy"],
            graded=0,
        )
        # Cold reset again so that no held request carries over; then the twin.
        await self._cold_reset()
        twin = self.progs["pre_sense_twin"]["addr"]
        snap = self.bank.read()
        watch = SepEfuseBankWatch(dut).start(reference=snap)
        m_cmd = self.cmds.mark()
        m0 = watch.mark()
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(twin, data=1))
        m1 = watch.mark()
        await ClockCycles(dut.clk_i, self.w)
        f2 = await self._flags()
        first = watch.first_change_since(m0)
        await watch.stop()
        t_land = None if first is None else first[0] - m1.clk
        diff = self.bank.diff_since(snap)
        ctl_cmd = len(self.cmds.programs_since(m_cmd, address=twin))
        twin_ok = self._twin_program("pre_sense_twin", f2, diff, twin)
        pre_diff = win["changed"]
        ok = self._grade(
            "IF-PRESENSE",
            t_sense is not None
            and sense_at_go == 0
            and not pre_diff
            and not win["progs"]
            and twin_ok
            and ctl_cmd >= 1,
            sense_done_at_go=sense_at_go,
            otp_diff_at_sense_done="none" if not pre_diff else diff_log(pre_diff[0][1]),
            ctl_diff=diff_log(diff),
            t_go=t_go,
            t_land="none" if t_land is None else t_land,
            t_sense="none" if t_sense is None else t_sense,
            prog_cmds_presense=len(win["progs"]),
            ctl_cmd=ctl_cmd,
            bit_addr=bit,
        )
        hook = t_land is not None and t_sense is not None and t_go + t_land < t_sense
        fields = {
            "check": "IF-PRESENSE",
            "t_go": t_go,
            "t_land": t_land if t_land is not None else "none",
            "t_sense": t_sense if t_sense is not None else "none",
        }
        if hook:
            self._ctrl("HOOK", True, **fields)
        else:
            self._grade("HOOK", False, **fields)
        await self._pass(tag, ok and hook and landed)

    def _start_presense_monitor(self, ref: Any) -> tuple[Any, dict[str, Any]]:
        """Start the per-clock monitor of a pre-sense window; ``rst_ni`` is low.

        From the next clock (the caller releases ``rst_ni`` right after) to the
        first clock with ``sep_fuse_sense_done_o`` at 1, or ``sense_bound``
        clocks: ``n`` counts the clocks, ``changed`` holds the bank diffs against
        ``ref`` (first 8), ``progs`` every program command at
        ``efuse_shim_cmd_*_o``, and ``t_sense`` the clock of the rise (None
        when the bound expired).
        """
        dut = cocotb.top
        win: dict[str, Any] = {"n": 0, "changed": [], "progs": [], "t_sense": None}
        bound = self.sense_bound

        async def _window() -> None:
            prev = None
            while win["n"] < bound:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                win["n"] += 1
                words = self.bank.read()
                if words != ref and len(win["changed"]) < 8:
                    win["changed"].append((win["n"], bank_diff(ref, words)))
                valid = self.rd(dut.efuse_shim_cmd_valid_o)
                cur = (
                    (
                        1,
                        self.rd(dut.efuse_shim_cmd_command_o),
                        self.rd(dut.efuse_shim_cmd_address_o),
                        self.rd(dut.efuse_shim_cmd_program_data_o),
                        self.rd(dut.efuse_shim_cmd_len_o),
                    )
                    if valid
                    else (0, 0, 0, 0, 0)
                )
                if is_command_edge(prev, cur) and cur[1] in PROGRAM_COMMANDS:
                    win["progs"].append((win["n"], cur[2]))
                prev = cur
                if self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True):
                    win["t_sense"] = win["n"]
                    return

        return cocotb.start_soon(_window()), win

    # -- JTAG before sense done ----------------------------------------------

    def _jtag_draws(self) -> None:
        """Draws of the JTAG pre-sense case, appended to the plan stream after ``plan()``.

        Three program bits, pairwise different and 0 in the staged image, in spare
        fields that no lock slot of this image burns and that no other case
        programs: the bit of the graded leg, the bit of the window leg and the bit
        of the program twin. One shadow word whose staged value is not 0, in a
        field that is not read-locked, not write-locked, not ``LC_STATE`` and that
        no case programs, so the shadow holds the staged word at every sense.
        """
        p = self.p
        d = p.draw
        n0 = len(p.draws)
        locked = {
            LOCK_SLOT_FIELD[p.leg["write_lock_slot"]],
            LOCK_SLOT_FIELD[p.leg["read_lock_slot"]],
        }
        used = {r["field"] for r in self.progs.values()}
        free = [f for f in SPARE_FIELDS if f not in locked and f not in used]
        bits = [(f, w, b) for f in free for (w, b) in zero_bits(p.image, f)]
        picks = d.sample("jtag_presense.program_bits", bits, 3)
        self.jtag_bits = {
            role: bit_address(f, w, b)
            for role, (f, w, b) in zip(("graded", "window", "twin"), picks)
        }
        busy = locked | used | {f for f, _w, _b in picks} | {"LC_STATE"}
        cands = [
            (f, w)
            for f in FIELD_NAMES
            if f not in busy
            for w in range(field_n_words(f))
            if p.image.words[field_word(f) + w] != 0
        ]
        f, w = d.choice("jtag_presense.read_word", cands)
        idx = field_word(f) + w
        self.jtag_rd = {
            "field": f,
            "word": w,
            "idx": idx,
            "addr": shadow_addr(f, w),
            "staged": int(p.image.words[idx]),
        }
        for k, v in list(p.draws.items())[n0:]:
            self.logger.info("INFO-DRAW seed=%d name=%s value=%s", self.seed, k, v)

    async def _jtag_program_twin(self) -> bool:
        """Post-sense JTAG program of the twin bit: the JTAG program path works.

        One JTAG write of ``EFUSE_PROGRAM_CTRL`` (enable, data 1, address, go),
        a wait of W, then the frontdoor flags. The control passes on an OKAY
        write response, exactly one program command (at the twin address), a
        bank diff of exactly the twin bit, program done, both busy bits 0, no
        error flag and ``program_status`` 0. The owner window is closed.
        """
        dut = cocotb.top
        bit = self.jtag_bits["twin"]
        await self._clean_ctrl()
        snap = self.bank.read()
        mark = self.cmds.mark()
        resp, _ = await self.jtag_axil_op(
            write=True, addr=PROGRAM_CTRL_ADDR, wdata=program_ctrl_word(bit, data=1)
        )
        await ClockCycles(dut.clk_i, self.w)
        f = await self._flags()
        diff = self.bank.diff_since(snap)
        n_at = len(self.cmds.programs_since(mark, address=bit))
        n_all = len(self.cmds.programs_since(mark))
        landed = diff_is_exactly(diff, bit)
        ok = (
            resp == RESP_OKAY
            and n_at == 1
            and n_all == 1
            and landed
            and f["pg_done"] == 1
            and self._idle(f)
            and self._s4(f) == "0b0000"
            and f["pg_status"] == 0
        )
        return self._ctrl(
            "IF-PRESENSE-JTAG-TWIN",
            ok,
            bit_addr=bit,
            wr_resp=RESP_NAME.get(resp, resp),
            prog_cmds_at_bit=n_at,
            prog_cmds=n_all,
            landed=int(landed),
            diff=diff_log(diff),
            flags=self._s4(f),
            pg_done=f["pg_done"],
            pg_status=f["pg_status"],
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )

    async def _jtag_presense_leg(self, leg: str, prog_bit: int, twin_ok: bool) -> bool:
        """One JTAG leg: ``rst_ni`` pulse, JTAG map read and program go, sense-done rise.

        ``leg`` is ``graded`` (owner window closed) or ``window`` (owner window
        open from before the ``rst_ni`` fall to the grade of the leg; its samples
        are held and sample only when the grade passed). After the rise the same
        JTAG read runs again and the
        sensed shadow word is read; then a wait of W lets a held go finish before
        the next reset. Returns the CHK-IF-PRESENSE-JTAG result.
        """
        dut = cocotb.top
        rd = self.jtag_rd
        staged = rd["staged"]
        self._golden_from_bank()
        tag = 0
        if leg == "window":
            self._open_window()
            tag = self._step()
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, _RST_HOLD)
        task, win = self._start_presense_monitor(self.bank.read())
        dut.rst_ni.value = 1
        r_resp, r_data = await self.jtag_axil_op(write=False, addr=rd["addr"])
        r_data &= M32
        t_rd = None if task.done() else win["n"]
        s_rd = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        go = program_ctrl_word(prog_bit, data=1)
        w_resp, _ = await self.jtag_axil_op(write=True, addr=PROGRAM_CTRL_ADDR, wdata=go)
        t_wr = None if task.done() else win["n"]
        s_wr = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        if not task.done():
            await task
        t_sense = win["t_sense"]
        await ClockCycles(dut.clk_i, _FCOV_SETTLE)
        p_resp, p_data = await self.jtag_axil_op(write=False, addr=rd["addr"])
        p_data &= M32
        probe = shadow_word(self, rd["idx"])
        await ClockCycles(dut.clk_i, self.w)
        landed = self._landed(
            f"pre_sense_jtag.{leg}", "EFUSE_PROGRAM_CTRL", go, await self._rd(PROGRAM_CTRL_ADDR)
        )
        self.chk.obs(
            "IF-PRESENSE-JTAG-RESP",
            leg=leg,
            map_resp=RESP_NAME.get(r_resp, r_resp),
            prog_resp=RESP_NAME.get(w_resp, w_resp),
            graded=0,
        )
        pre_diff = win["changed"]
        refused = r_resp == RESP_SLVERR and r_data != staged
        pre_sense_ok = (
            t_sense is not None
            and s_rd == 0
            and s_wr == 0
            and refused
            and not pre_diff
            and not win["progs"]
        )
        probes = p_resp == RESP_OKAY and p_data == staged and probe == staged and staged != 0
        ok = self._grade(
            "IF-PRESENSE-JTAG",
            pre_sense_ok and probes and twin_ok,
            leg=leg,
            addr=f"0x{rd['addr']:08x}",
            staged=f"0x{staged:08x}",
            sense_done_at_rd=s_rd,
            sense_done_at_wr=s_wr,
            map_resp=RESP_NAME.get(r_resp, r_resp),
            map_data=f"0x{r_data:08x}",
            prog_bit=prog_bit,
            prog_cmds_presense=len(win["progs"]),
            otp_diff_at_sense_done="none" if not pre_diff else diff_log(pre_diff[0][1]),
            t_rd="after_rise" if t_rd is None else t_rd,
            t_wr="after_rise" if t_wr is None else t_wr,
            t_sense="none" if t_sense is None else t_sense,
            post_map_resp=RESP_NAME.get(p_resp, p_resp),
            post_map_data=f"0x{p_data:08x}",
            post_probe=f"0x{probe:08x}",
            prog_twin=int(twin_ok),
            prog_twin_bit=self.jtag_bits["twin"],
        )
        hook = (
            t_rd is not None
            and t_wr is not None
            and t_sense is not None
            and t_rd < t_sense
            and t_wr < t_sense
        )
        fields = {
            "check": "IF-PRESENSE-JTAG",
            "leg": leg,
            "t_rd": "after_rise" if t_rd is None else t_rd,
            "t_wr": "after_rise" if t_wr is None else t_wr,
            "t_sense": "none" if t_sense is None else t_sense,
        }
        if hook:
            self._ctrl("HOOK", True, **fields)
        else:
            self._grade("HOOK", False, **fields)
        if leg == "window":
            await self._pass(tag, ok and hook and landed)
            close_graded_window(self.logger)
        return ok and hook and landed

    async def _case_presense_jtag(self) -> None:
        """JTAG map read and JTAG program go before sense done, with their post-sense twins.

        The program twin and the graded leg run with the owner window closed. The
        window leg runs only when the graded leg passed, so the
        ``x_jtag_presense`` samples come from a run whose check already passed.
        A cold reset at the end drops a held go.
        """
        close_graded_window(self.logger)
        twin_ok = await self._jtag_program_twin()
        if await self._jtag_presense_leg("graded", self.jtag_bits["graded"], twin_ok):
            await self._jtag_presense_leg("window", self.jtag_bits["window"], twin_ok)
        else:
            self.chk.info("IF-PRESENSE-JTAG-WINDOW-SKIP", reason="graded_leg_failed")
        await self._cold_reset()

    async def _case_read_go_no_enable(self) -> None:
        """Step 8: read go with read_enable 0 sets read_status only."""
        bit = self.reads["read_go_no_enable"]["addr"]
        await self._frame("read_go_no_enable")
        tag = self._step()
        f = await self._run_read(bit, enable=0)
        ok = self._status("read_go_no_enable", bit, f, "0b1000", "na", True)
        await self._pass(tag, ok)
        tag = self._step()
        _n, ok = await self._accepted_read("read_go_no_enable", bit)
        await self._pass(tag, ok)

    async def _case_oor_read(self) -> None:
        """Step 9: accepted read of bit 8191, then reads at the three out-of-range addresses."""
        await self._frame("oor_read")
        tag = self._step()
        _n, ok = await self._accepted_read("oor_read", _BIT_8191)
        await self._pass(tag, ok)
        for a in self.oor:
            snap = await self._frame("oor_read")
            tag = self._step()
            m_cmd = self.cmds.mark()
            f = await self._run_read(a)
            diff = self.bank.diff_since(snap)
            self.logger.info(
                "OBS-IF-CMD LOG seed=%d case=read_oob addr=%d otp_diff=%s",
                self.seed,
                a,
                "none" if not diff else diff_log(diff),
            )
            self.logger.info(
                "OBS-IF-OOB-CMD LOG seed=%d case=read_oob addr=%d post_guard_cmds=%d",
                self.seed,
                a,
                len(self.cmds.commands_since(m_cmd)),
            )
            fc = await self._clear(_M_CLR_RAE)
            ok_clear = fc["rae"] == 0 and fc["pae"] == f["pae"] and fc["re"] == f["re"]
            ok = self._status("oor_read", a, f, "0b1100", int(ok_clear), ok_clear)
            await self._pass(tag, ok)

    async def _case_oor_program(self) -> None:
        """Step 10: programs at the three out-of-range addresses."""
        for a in self.oor:
            snap = await self._frame("oor_program")
            tag = self._step()
            m_cmd = self.cmds.mark()
            f = await self._run_program(a)
            diff = self.bank.diff_since(snap)
            self.logger.info(
                "OBS-IF-CMD LOG seed=%d case=prog_oob addr=%d otp_diff=%s",
                self.seed,
                a,
                "none" if not diff else diff_log(diff),
            )
            self.logger.info(
                "OBS-IF-OOB-CMD LOG seed=%d case=prog_oob addr=%d post_guard_cmds=%d",
                self.seed,
                a,
                len(self.cmds.commands_since(m_cmd)),
            )
            fc = await self._clear(_M_CLR_PAE)
            ok_clear = fc["pae"] == 0 and fc["rae"] == f["rae"] and fc["re"] == f["re"]
            ok = self._status("oor_program", a, f, "0b0010", int(ok_clear), ok_clear)
            await self._pass(tag, ok)
        self.chk.info(
            "IF-CTRL-NO-TWIN", case="oor_program", reason="procedure_gives_no_accepted_twin"
        )

    async def _case_lock_program(self) -> None:
        """Step 11: program on the write-locked field, then the unlocked twin."""
        bit = self.lock_prog["addr"]
        snap = await self._frame("lock_program")
        tag = self._step()
        pre_bit = (snap[bit >> 5] >> (bit & 31)) & 1
        f = await self._run_program(bit)
        diff = self.bank.diff_since(snap)
        ok_cmd = self._grade(
            "IF-CMD",
            pre_bit == 0 and not diff,
            case="prog_wlocked",
            addr=bit,
            pre_bit=pre_bit,
            otp_diff="none" if not diff else diff_log(diff),
        )
        fc = await self._clear(_M_CLR_RE)
        ok_clear = self._s4(fc) == "0b0000"
        ok = self._status("lock_program", bit, f, "0b0001", int(ok_clear), ok_clear)
        await self._pass(tag, ok and ok_cmd)
        twin = self.progs["lock_twin"]["addr"]
        tag = self._step()
        snap = self.bank.read()
        f = await self._run_program(twin)
        ok = self._twin_program("lock_program", f, self.bank.diff_since(snap), twin)
        await self._pass(tag, ok)

    async def _case_lock_read(self) -> None:
        """Step 12: read on the read-locked field, then the unlocked twin."""
        bit = self.lock_read["addr"]
        await self._frame("lock_read")
        tag = self._step()
        mark = self.cmds.mark()
        f = await self._run_read(bit)
        n_reads = len(self.cmds.reads_since(mark))
        # In range and blocked by the read lock: efuse_req_error only of the three
        # status flags. read_status is not stated for this case (logged), and the
        # clear of efuse_req_error must keep it.
        fc = await self._clear(_M_CLR_RE)
        ok_clear = fc["re"] == 0 and fc["rs"] == f["rs"] and fc["rae"] == 0 and fc["pae"] == 0
        self.chk.obs("IF-LOCK-READ-STATUS", addr=bit, read_status=f["rs"], graded=0)
        ok_st = self._grade(
            "IF-STATUS",
            f["re"] == 1 and f["rae"] == 0 and f["pae"] == 0 and self._idle(f) and ok_clear,
            case="lock_read",
            addr=bit,
            status=self._s4(f),
            exp="0bx001",
            cleared=int(ok_clear),
            status_after_clear=self._s4(fc),
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )
        twin = self.reads["lock_read_twin"]["addr"]
        ctl, ok_twin = await self._accepted_read("lock_read", twin)
        ok_cmd = self._grade(
            "IF-CMD",
            n_reads == 0 and ctl == 1,
            case="read_rlocked",
            read_cmds=n_reads,
            ctl_twin_cmd=ctl,
            addr=bit,
            twin_addr=twin,
        )
        await self._pass(tag, ok_st and ok_twin and ok_cmd)

    async def _case_both_enables(self) -> None:
        """Step 13: read go with program_enable set; no read command until the cold reset."""
        dut = cocotb.top
        bit = self.reads["both_enables"]["addr"]
        await self._frame("both_enables")
        tag = self._step()
        mark = self.cmds.mark()
        pg_go = program_ctrl_word(0, data=0, enable=1, go=0)
        rd_go = read_ctrl_word(bit, enable=1)
        await self._wr(PROGRAM_CTRL_ADDR, pg_go)
        await self._wr(READ_CTRL_ADDR, rd_go)
        await ClockCycles(dut.clk_i, _BOTH_WAIT)
        st = await self._rd(STATUS_ADDR)
        rc = await self._rd(READ_CTRL_ADDR)
        pg = await self._rd(PROGRAM_CTRL_ADDR)
        landed = self._landed("both_enables", "EFUSE_READ_CTRL", rd_go, rc)
        landed = self._landed("both_enables", "EFUSE_PROGRAM_CTRL", pg_go, pg) and landed
        self.chk.obs(
            "IF-STATUS-FLAGS",
            case="both_enables",
            addr=bit,
            status=f"0x{st:08x}",
            read_ctrl=f"0x{rc:08x}",
            graded=0,
        )
        # The contract does not order the two enable-clear writes. read_enable goes
        # first, so that dropping program_enable cannot hand the held read to the bank
        # before the reset; the order is logged, not graded.
        await self._wr(READ_CTRL_ADDR, 0)
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        self.chk.info(
            "IF-ENABLE-CLEAR-ORDER", first="read_enable", second="program_enable", graded=0
        )
        self._golden_from_bank()
        c_fall = await self._rst_pulse()
        n = await clocks_to_sense(self, self.sense_bound, started=True)
        await ClockCycles(dut.clk_i, 20)
        if n is None:
            raise AssertionError(f"sense did not complete within {self.sense_bound} clocks")
        self._check_efuse_shadow_after_sense()
        n_reads = len([c for c in self.cmds.reads_since(mark) if c.clk <= c_fall + 1])
        await self._frame("both_enables")
        ctl, ok_twin = await self._accepted_read("both_enables", bit)
        ok = self._grade(
            "IF-CMD",
            n_reads == 0 and ctl == 1,
            case="both_enables",
            read_cmds=n_reads,
            ctl_twin_cmd=ctl,
            addr=bit,
        )
        await self._pass(tag, ok and ok_twin and landed)

    async def _case_data0(self) -> None:
        """Step 14: program with data 0 changes no bank bit; then the data-1 twin."""
        bit = self.progs["data0"]["addr"]
        snap = await self._frame("data0")
        tag = self._step()
        go = program_ctrl_word(bit, data=0)
        f = await self._run_program(bit, data=0)
        landed = self._landed("data0", "EFUSE_PROGRAM_CTRL", go, await self._rd(PROGRAM_CTRL_ADDR))
        diff = self.bank.diff_since(snap)
        ok_st = self._status("data0", bit, f, "0b0000", "na", True)
        ok = self._grade(
            "IF-CMD",
            not diff and self._idle(f),
            case="prog_data0",
            otp_diff="none" if not diff else diff_log(diff),
            addr=bit,
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )
        await self._pass(tag, ok and ok_st and landed)
        tag = self._step()
        snap = self.bank.read()
        f = await self._run_program(bit, data=1)
        ok = self._twin_program("data0", f, self.bank.diff_since(snap), bit)
        await self._pass(tag, ok)

    # -- leaf ---------------------------------------------------------------

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.seed = seed = self.random_seed()
        self.p = p = plan(TEST, seed)
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        self._fcov_dead = False
        self._tag = 0
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        self.progs = p.leg["programs"]
        self.reads = p.leg["reads"]
        self.lock_prog = p.leg["lock_program"]
        self.lock_read = p.leg["lock_read"]
        self.oor = list(p.leg["oor_addresses"])
        self._jtag_draws()
        close_graded_window(self.logger)
        set_ef_hold_tag(0, self.logger)
        set_ef_hold_pass(0, self.logger)

        # Steps 2-3: staged image, strap 0, reset release; measure the sense time.
        self.write_efuse_image(p.image)
        timer = cocotb.start_soon(clocks_to_sense(self, _FIRST_SENSE_BOUND, started=False))
        await self.bring_up_no_cpu(max_cycles=_FIRST_SENSE_BOUND)
        t_sense = await timer
        if t_sense is None:
            raise AssertionError("sense time not measured")
        await ClockCycles(dut.clk_i, 1)
        self.w = _W_MULT * t_sense
        self.sense_bound = max(_FIRST_SENSE_BOUND, _SENSE_BOUND_MULT * t_sense)
        self.suppress_host_axi_transaction_info()
        self.logger.info(
            "INFO-IF-STATUS PARAM seed=%d t_sense=%d w=%d w_mult=%d sense_bound=%d both_wait=%d",
            seed,
            t_sense,
            self.w,
            _W_MULT,
            self.sense_bound,
            _BOTH_WAIT,
        )
        self.bank = SepEfuseBank(dut)
        self.cmds = SepShimCmdMonitor(dut).start()
        dbg = {"on": True, "clocks": 0, "unknown": 0, "or": 0, "wr": set(), "rd": set()}
        dbg_task = cocotb.start_soon(self._debug_bus_watch(dbg))
        await ClockCycles(dut.clk_i, 2)

        cases = {
            "pre_sense": self._case_presense,
            "read_go_no_enable": self._case_read_go_no_enable,
            "oor_read": self._case_oor_read,
            "oor_program": self._case_oor_program,
            "lock_program": self._case_lock_program,
            "lock_read": self._case_lock_read,
            "both_enables": self._case_both_enables,
            "data0": self._case_data0,
        }
        for name in p.leg["case_order"]:
            self.logger.info("INFO-IF-STATUS CASE seed=%d case=%s", seed, name)
            await cases[name]()
            if name == "pre_sense":
                self.logger.info("INFO-IF-STATUS CASE seed=%d case=pre_sense_jtag", seed)
                await self._case_presense_jtag()
        close_graded_window(self.logger)
        await self.cmds.stop()
        dbg["on"] = False
        await dbg_task
        self.chk.obs(
            "EFUSE-SHIM-DBG",
            clocks=dbg["clocks"],
            unknown=dbg["unknown"],
            wr_cnt_err=_b(dbg["or"], _DBG_WR_ERR),
            rd_cnt_err=_b(dbg["or"], _DBG_RD_ERR),
            wr_states=sorted(dbg["wr"]),
            rd_states=sorted(dbg["rd"]),
            other_bits=f"0x{dbg['or'] & _DBG_OTHER:04x}",
        )
        self.chk.finish()

    async def _debug_bus_watch(self, st: dict[str, Any]) -> None:
        """Sample ``efuse_debug_bus_o`` on every ``clk_i`` while ``st["on"]``."""
        dut = cocotb.top
        while st["on"]:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            st["clocks"] += 1
            v = dut.efuse_debug_bus_o.value
            if not v.is_resolvable:
                st["unknown"] += 1
                continue
            v = int(v)
            st["or"] |= v
            st["wr"].add((v >> 8) & 0xF)
            st["rd"].add(v & 0xF)
        await NextTimeStep()

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read and program interface status flags, empty program, accepted twins, no program before sense done.

A read go with ``read_enable`` clear sets ``read_status``. A read or program address
of 8192 or more sets its own address-error flag (and ``read_status`` for a read), and
the flag clears by write-one. A request that a lock blocks sets ``efuse_req_error``.
``program_enable`` keeps a read from reaching the bank. No bank bit changes from reset
release until sense completes. A program with data 0 programs nothing.

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
  CHK-IF-STATUS    the error flags and ``read_status`` of each refusal case equal the
                   case golden; each clear bit clears its flag only.
  CHK-IF-CMD       the data-0 program leaves the bank unchanged; no read command at
                   ``efuse_shim_command_req_o`` for the lock-blocked read (go to end of
                   W) and the both-enables read (go to the cold reset assertion); the
                   accepted read twin of each shows its read command.
  CHK-IF-CTRL      every case starts with clean flags (case frame), and each refusal
                   case has an accepted twin that completes (program twins change the
                   bank by exactly their bit at ``otp_bank_probe_o``).
  CHK-IF-PRESENSE  a program go issued before sense done changes no bank bit and sends
                   no program command from reset release to the sense-done rise; the
                   post-sense twin lands with its command. ``CHK-HOOK FAIL`` when
                   ``t_go + t_land`` is not shorter than ``t_sense``.

Log-only: the flags of the pre-sense, data-0 and both-enables cases
(``OBS-IF-STATUS-FLAGS``), the other flags and data of the lock-blocked read, the bank
diff after the out-of-range and lock-blocked program cases (``CHK-IF-CMD INFO``).
Two points the contract leaves open are logged, not graded: the out-of-range program
has no accepted twin in the procedure (``OBS-IF-CTRL-NO-TWIN``), and the order of the
two enable-clear writes after the both-enables case is not stated (the leaf clears
``read_enable`` first; ``OBS-IF-ENABLE-CLEAR-ORDER``).
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
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
    PROGRAM_CTRL_ADDR,
    READ_CTRL_ADDR,
    STATUS_ADDR,
    T_IF_STATUS,
    plan,
    program_ctrl_word,
    read_ctrl_word,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    clocks_to_sense,
    rst_pulse,
    set_shadow_golden,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
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
_BIT_8191 = 8191  # last bit of the 8192-bit OTP (256 words of 32 bits)

# Test parameters (the contract leaves them to the test).
_W_MULT = 2  # W = _W_MULT x sense time
_SENSE_BOUND_MULT = 4  # bound of a sense wait, in sense times
_FIRST_SENSE_BOUND = 20_000
_BOTH_WAIT = 2048  # clocks after the both-enables go (over the 1024-clock sampler window)
_CLEAR_SETTLE = 16  # clocks after a status clear write before the next write
_RST_HOLD = 20


def _b(v: int, m: int) -> int:
    return int(bool(v & m))


@pyuvm.test()
class sep_efuse_interface_status_rand_test(sep_base_test):
    """Interface status per refusal case, accepted twins, empty program, pre-sense program."""

    required_evidence = ("CHK-IF-STATUS", "CHK-IF-CMD", "CHK-IF-CTRL", "CHK-IF-PRESENSE")

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

    async def _frame(self, case: str) -> tuple[int, ...]:
        """Procedure step 4: clean flags, one accepted read, bank snapshot."""
        close_graded_window(self.logger)
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        await self._wr(READ_CTRL_ADDR, 0)
        await self._wr(STATUS_ADDR, _M_CLR_RE | _M_CLR_PAE | _M_CLR_RAE)
        await ClockCycles(cocotb.top.clk_i, _CLEAR_SETTLE)
        f = await self._run_read(self.reads["frame"]["addr"])
        clean = self._s4(f) == "0b0000" and f["rd_done"] == 1 and self._idle(f)
        self.chk.ok(
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
        open_graded_window(TEST, self.logger)
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
        self.chk.ok(
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

    def _twin_read(self, case: str, f: dict[str, int], addr: int) -> bool:
        ok = f["rd_done"] == 1 and self._idle(f) and self._s4(f) == "0b0000"
        self.chk.ok(
            "IF-CTRL",
            ok,
            case=case,
            accepted=1,
            flags=self._s4(f),
            landed="na",
            read_done=f["rd_done"],
            bit_addr=addr,
        )
        return ok

    def _status(
        self, case: str, addr: int, f: dict[str, int], exp: str, cleared: Any, ok_clear: bool
    ) -> None:
        self.chk.ok(
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
        open_graded_window(TEST, self.logger)
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, _RST_HOLD)
        ref = self.bank.read()
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

        task = cocotb.start_soon(_window())
        dut.rst_ni.value = 1
        # First access after the release: one write with enable, data 1, address, go.
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(bit, data=1))
        sense_at_go = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        t_go = win["n"]
        await task
        t_sense = win["t_sense"]
        await ClockCycles(dut.clk_i, self.w)
        f = await self._flags()
        self.chk.obs(
            "IF-STATUS-FLAGS",
            case="pre_sense",
            addr=bit,
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
        self.chk.ok(
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
            self.chk.ctrl("HOOK", True, **fields)
        else:
            self.chk.ok("HOOK", False, **fields)

    async def _case_read_go_no_enable(self) -> None:
        """Step 8: read go with read_enable 0 sets read_status only."""
        bit = self.reads["read_go_no_enable"]["addr"]
        await self._frame("read_go_no_enable")
        f = await self._run_read(bit, enable=0)
        self._status("read_go_no_enable", bit, f, "0b1000", "na", True)
        f = await self._run_read(bit, enable=1)
        self._twin_read("read_go_no_enable", f, bit)

    async def _case_oor_read(self) -> None:
        """Step 9: accepted read of bit 8191, then reads at the three out-of-range addresses."""
        await self._frame("oor_read")
        f = await self._run_read(_BIT_8191)
        self._twin_read("oor_read", f, _BIT_8191)
        for a in self.oor:
            snap = await self._frame("oor_read")
            f = await self._run_read(a)
            diff = self.bank.diff_since(snap)
            self.logger.info(
                "CHK-IF-CMD INFO seed=%d case=read_oob addr=%d otp_diff=%s",
                self.seed,
                a,
                "none" if not diff else diff_log(diff),
            )
            fc = await self._clear(_M_CLR_RAE)
            ok_clear = fc["rae"] == 0 and fc["pae"] == f["pae"] and fc["re"] == f["re"]
            self._status("oor_read", a, f, "0b1100", int(ok_clear), ok_clear)

    async def _case_oor_program(self) -> None:
        """Step 10: programs at the three out-of-range addresses."""
        for a in self.oor:
            snap = await self._frame("oor_program")
            f = await self._run_program(a)
            diff = self.bank.diff_since(snap)
            self.logger.info(
                "CHK-IF-CMD INFO seed=%d case=prog_oob addr=%d otp_diff=%s",
                self.seed,
                a,
                "none" if not diff else diff_log(diff),
            )
            fc = await self._clear(_M_CLR_PAE)
            ok_clear = fc["pae"] == 0 and fc["rae"] == f["rae"] and fc["re"] == f["re"]
            self._status("oor_program", a, f, "0b0010", int(ok_clear), ok_clear)
        self.chk.obs(
            "IF-CTRL-NO-TWIN", case="oor_program", reason="procedure_gives_no_accepted_twin"
        )

    async def _case_lock_program(self) -> None:
        """Step 11: program on the write-locked field, then the unlocked twin."""
        bit = self.lock_prog["addr"]
        snap = await self._frame("lock_program")
        f = await self._run_program(bit)
        diff = self.bank.diff_since(snap)
        self.logger.info(
            "CHK-IF-CMD INFO seed=%d case=prog_wlocked addr=%d otp_diff=%s",
            self.seed,
            bit,
            "none" if not diff else diff_log(diff),
        )
        fc = await self._clear(_M_CLR_RE)
        ok_clear = self._s4(fc) == "0b0000"
        self._status("lock_program", bit, f, "0b0001", int(ok_clear), ok_clear)
        twin = self.progs["lock_twin"]["addr"]
        snap = self.bank.read()
        f = await self._run_program(twin)
        self._twin_program("lock_program", f, self.bank.diff_since(snap), twin)

    async def _case_lock_read(self) -> None:
        """Step 12: read on the read-locked field, then the unlocked twin."""
        bit = self.lock_read["addr"]
        await self._frame("lock_read")
        mark = self.cmds.mark()
        f = await self._run_read(bit)
        n_reads = len(self.cmds.reads_since(mark))
        self.chk.ok(
            "IF-STATUS",
            f["re"] == 1 and self._idle(f),
            case="lock_read",
            addr=bit,
            status=self._s4(f),
            exp="0bxxx1",
            cleared="na",
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )
        await self._clear(_M_CLR_RE)
        twin = self.reads["lock_read_twin"]["addr"]
        m2 = self.cmds.mark()
        f = await self._run_read(twin)
        ctl = len(self.cmds.reads_since(m2, address=twin))
        self._twin_read("lock_read", f, twin)
        self.chk.ok(
            "IF-CMD",
            n_reads == 0 and ctl >= 1,
            case="read_rlocked",
            read_cmds=n_reads,
            ctl_twin_cmd=ctl,
            addr=bit,
            twin_addr=twin,
        )

    async def _case_both_enables(self) -> None:
        """Step 13: read go with program_enable set; no read command until the cold reset."""
        dut = cocotb.top
        bit = self.reads["both_enables"]["addr"]
        await self._frame("both_enables")
        mark = self.cmds.mark()
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(0, data=0, enable=1, go=0))
        await self._wr(READ_CTRL_ADDR, read_ctrl_word(bit, enable=1))
        await ClockCycles(dut.clk_i, _BOTH_WAIT)
        st = await self._rd(STATUS_ADDR)
        rc = await self._rd(READ_CTRL_ADDR)
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
        self.chk.obs(
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
        m2 = self.cmds.mark()
        f = await self._run_read(bit)
        ctl = len(self.cmds.reads_since(m2, address=bit))
        self._twin_read("both_enables", f, bit)
        self.chk.ok(
            "IF-CMD",
            n_reads == 0 and ctl >= 1,
            case="both_enables",
            read_cmds=n_reads,
            ctl_twin_cmd=ctl,
            addr=bit,
        )

    async def _case_data0(self) -> None:
        """Step 14: program with data 0 changes no bank bit; then the data-1 twin."""
        bit = self.progs["data0"]["addr"]
        snap = await self._frame("data0")
        f = await self._run_program(bit, data=0)
        diff = self.bank.diff_since(snap)
        self.chk.obs("IF-STATUS-FLAGS", case="data0", addr=bit, status=self._s4(f), graded=0)
        self.chk.ok(
            "IF-CMD",
            not diff and self._idle(f),
            case="prog_data0",
            otp_diff="none" if not diff else diff_log(diff),
            addr=bit,
            busy=f"{f['rd_busy']}{f['pg_busy']}",
        )
        snap = self.bank.read()
        f = await self._run_program(bit, data=1)
        self._twin_program("data0", f, self.bank.diff_since(snap), bit)

    # -- leaf ---------------------------------------------------------------

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
        self.progs = p.leg["programs"]
        self.reads = p.leg["reads"]
        self.lock_prog = p.leg["lock_program"]
        self.lock_read = p.leg["lock_read"]
        self.oor = list(p.leg["oor_addresses"])
        close_graded_window(self.logger)

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
            "IF-STATUS PARAM seed=%d t_sense=%d w=%d w_mult=%d sense_bound=%d both_wait=%d",
            seed,
            t_sense,
            self.w,
            _W_MULT,
            self.sense_bound,
            _BOTH_WAIT,
        )
        self.bank = SepEfuseBank(dut)
        self.cmds = SepShimCmdMonitor(dut).start()
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
            self.logger.info("IF-STATUS CASE seed=%d case=%s", seed, name)
            await cases[name]()
        close_graded_window(self.logger)
        await self.cmds.stop()
        self.chk.finish()

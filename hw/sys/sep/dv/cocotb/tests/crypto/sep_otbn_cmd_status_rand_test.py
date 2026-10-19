# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN commands, status codes, INSN_CNT, the done line and the ignored writes follow the register text.

Spec: ``vendor/lowRISC/opentitan/overlay/regs/otbn/regs/gen/adoc/otbn.adoc``
(``INTR_STATE`` :34, ``INTR_ENABLE`` :44, ``INTR_TEST`` :54, ``CMD`` codes
:79-81, ``CTRL`` :96, ``STATUS`` :106-118, ``ERR_BITS`` :122,
``FATAL_ALERT_CAUSE`` :149, ``INSN_CNT`` :171);
``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/otbn.hjson`` :463-464 (``CMD``
writes are ignored if OTBN is not idle; unrecognized commands are ignored);
``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/csr.yml`` :173 (an ``RND`` read
stalls until a number arrives from the EDN); ``hw/sys/sep/doc/trng.adoc`` :189
(native requests get no acknowledgement during the TRNG adapter clear);
``hw/sys/sep/doc/interrupts.adoc`` :22 and :164-166 (vector bit 29 is PIC
source 30, OTBN done);
``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/doc/theory_of_operation.md``
(``ToO`` below) and ``otbn.hjson`` / ``base-insns.yml`` in the same ``otbn`` tree
for the reset wipe, the errors and the locked state; ``hw/sys/sep/doc/otbn.adoc``
:66-70 (the FIPS tag that OTBN RND gets is tied high).

Legs (one seed draws the plan, logged in one ``PLAN`` line):
  command    3 to 5 commands from EXECUTE, SEC_WIPE_DMEM and SEC_WIPE_IMEM (each
             at least once), each at IDLE after a drawn gap.
  INSN_CNT   the compute program with a and b extra independent ADD
             instructions, each run after an OTBN reset.
  done line  two EXECUTE runs (enable 1 and enable 0, drawn order), then the
             ``INTR_TEST`` sub-leg.
  busy write an ``RND`` read held by the TRNG reset keeps ``STATUS`` at 0x01;
             k ``CTRL`` writes and j ``CMD`` = SEC_WIPE_DMEM writes.
  sw error   the ``unimp`` program (``CSRRW x0, 0xC00, x0`` then ``ecall``) with
             ``CTRL.software_errs_fatal`` = 1, a ``CMD`` write at LOCKED, an
             OTBN reset; then the same program with ``software_errs_fatal`` = 0.
  ignored    one unrecognised ``CMD`` value at IDLE, with ``ERR_BITS`` still
             holding the error of the sw error leg; then a write of a drawn
             value to ``ERR_BITS`` at IDLE.

Checkers:
  CHK-OTBN-CMD-END     each command returns to IDLE, never 0xFF on the way,
                       ``done`` = 1 (read 0 before), ``ERR_BITS`` and
                       ``FATAL_ALERT_CAUSE`` = 0.
  CHK-OTBN-CMD-BUSY    the first non-IDLE code on the OTBN status probe after
                       the ``CMD`` write is the busy code of the command.
  CHK-OTBN-INSN        ``INSN_CNT`` reads 0 after a reset, equals the length of
                       each straight-line program (``ecall`` included), differs
                       by b - a for the two programs, each DMEM result equals the
                       operator golden, and each reset shows 0x04 then 0x00 on
                       the probe.
  CHK-OTBN-DONE-LINE   vector bit 29 equals ``done`` AND ``INTR_ENABLE.done`` at
                       every sample of the done-line leg. With the enable set,
                       the first rise after the ``CMD`` write is at or after the
                       start of the last ``INTR_STATE`` read that showed
                       ``done`` = 0, and at the latest 64 clocks after the
                       reads that show ``done`` = 1 and ``STATUS`` IDLE.
  CHK-OTBN-CMD-IGNORE  an unrecognised ``CMD`` at IDLE starts nothing for
                       4 x t_cmd; a ``CMD`` write at 0x01 leaves ``STATUS`` 0x01.
  CHK-OTBN-BUSYWR      ``CTRL.software_errs_fatal`` written at 0x01 reads 0;
                       ``STATUS`` stays 0x01; not 0xFF after the release.
  CHK-OTBN-INITDONE    after the first OTBN reset the probe shows 0x04 at the
                       first clock after the release, then 0x00. "After reset,
                       OTBN is busy with the internal secure wipe and the
                       STATUS register is set to BUSY_SEC_WIPE_INT." (ToO:103,
                       0x04 per ``otbn.hjson`` :540); "After reset (init), OTBN
                       performs a secure wipe of the internal state and then
                       becomes idle." (ToO:98); "If OTBN is idle, the STATUS
                       register is set to IDLE." (ToO:104, 0x00 per
                       ``otbn.hjson`` :536).
  CHK-OTBN-SWERR-FATAL with ``software_errs_fatal`` = 1 the ``unimp`` program ends
                       with ``STATUS`` = 0xFF, ``done`` = 1, ``ERR_BITS`` non-zero
                       with ``fatal_software`` (bit 23) set and
                       ``FATAL_ALERT_CAUSE.fatal_software`` (bit 7) set.
                       "If csr isn't the index of a valid CSR, this results in
                       an error (setting bit illegal_insn in ERR_BITS)."
                       (``base-insns.yml`` :494; ``unimp`` is CSRRW of 0xC00 and
                       "Triggers an illegal instruction error", :681-690);
                       ILLEGAL_INSN is class "software" (ToO:226-229);
                       "When CTRL.software_errs_fatal is set, software errors
                       become fatal errors." (ToO:154); "Fatal errors are
                       treated as described in the section Reaction to Fatal
                       Errors." (ToO:156); "The ERR_BITS register is set to a
                       non-zero value that describes the error." (ToO:186); "The
                       current operation is marked as complete by setting
                       INTR_STATE.done." (ToO:187); "The STATUS register is set
                       to LOCKED." (ToO:188); FATAL_SOFTWARE "A software error
                       was seen and CTRL.software_errs_fatal was set."
                       (ToO:296-298); "The error that caused the alert can be
                       determined by reading the FATAL_ALERT_CAUSE register. If
                       OTBN was running, this value will also be reflected in
                       the ERR_BITS register." (ToO:312-313).
  CHK-OTBN-LOCKED-HOLD a ``CMD`` = EXECUTE write at LOCKED leaves ``STATUS`` at
                       0xFF for 4 x t_cmd and ``FATAL_ALERT_CAUSE`` unchanged;
                       after an OTBN reset the probe shows 0x04 then 0x00 and
                       ``FATAL_ALERT_CAUSE`` reads 0. "The locked state is a
                       terminal state; transitioning out of it requires an OTBN
                       reset." (ToO:114); "Writes are ignored if OTBN is not
                       idle." (``otbn.hjson`` :463); "the value of this register
                       does not change until OTBN is reset." (``otbn.hjson``
                       :672-673, reset value 0).
  CHK-OTBN-SWERR-RECOV with ``software_errs_fatal`` = 0 the same program ends with
                       ``STATUS`` = 0x00 (never 0xFF), ``done`` = 1 and
                       ``ERR_BITS.illegal_insn`` (bit 3) set. "All software
                       errors are treated as recoverable, unless
                       CTRL.software_errs_fatal is set" (ToO:153); ToO:168-170
                       (ERR_BITS non-zero, done set, STATUS set to IDLE).
  CHK-OTBN-ERRCLR      a write of a drawn value to ``ERR_BITS`` at IDLE makes it
                       read 0. "Writing any value to ERR_BITS clears this
                       register to zero." (ToO:317); ``otbn.hjson`` :562-563.
  CHK-OTBN-BUSYWR-ERR  after the RND program ends, ``ERR_BITS`` reads 0 in every
                       bit except ``rnd_rep_chk_fail`` (bit 6). "The ERR_BITS
                       register is set to indicate either a successful execution
                       (value 0), or to indicate the error that was observed"
                       (ToO:137); the program ends with ``ecall`` and the FIPS
                       tag is tied high (``otbn.adoc`` :67-69). Bit 6 is set when
                       two EDN words are equal (ToO:246-251), a chance outcome,
                       so it is logged only.
  CHK-OTBN-CMDIGN-ERR  the unrecognised ``CMD`` at IDLE leaves ``ERR_BITS`` at its
                       value before the write (non-zero). "Unrecognized commands
                       are ignored." (``otbn.hjson`` :464); ``ERR_BITS`` is set at
                       the end of an operation (ToO:137).

Controls: ``CTRL-OTBN-BUSYWR`` (the idle write reads back 1),
``CTRL-OTBN-DONE-LINE`` (enable-set ``INTR_TEST`` cell), ``CTRL-OTBN-CMD-IGNORE``
(a recognised command of the same seed sets ``done``), ``CTRL-OTBN-INITDONE``
(after the power-on wipe ``STATUS`` reads 0x00 and the probe holds 0x00 up to the
clock before the gated reset falls, so the 0x04 comes from the reset pulse; "After
reset (init), OTBN performs a secure wipe of the internal state and then becomes
idle." ToO:98; "If OTBN is idle, the STATUS register is set to IDLE." ToO:104,
0x00 per ``otbn.hjson`` :536), ``CTRL-OTBN-SWERR-FATAL`` (the same program with
``software_errs_fatal`` = 0 ends at 0x00), ``CTRL-OTBN-SWERR-RECOV`` (each
compute run of the command leg ends with ``ERR_BITS`` = 0),
``CTRL-OTBN-LOCKED-HOLD`` (a recognised command at IDLE starts an operation),
``CTRL-OTBN-ERRCLR``, ``CTRL-OTBN-CMDIGN-ERR`` (``ERR_BITS`` is non-zero before the
write), ``CTRL-OTBN-BUSYWR-ERR`` (the recoverable error run sets ``ERR_BITS``).
Log-only: ``OBS-OTBN-STATUS-SEQ``; ``OBS-OTBN-INITDONE-DONE`` (``INTR_STATE.done``
after the post-reset wipe: no sentence states its value); ``OBS-OTBN-BUSYWR-RNDREP`` (bit 6 after the RND
program, a chance outcome); ``OBS-OTBN-SWERR-CAUSE`` (the full ``ERR_BITS`` and
``FATAL_ALERT_CAUSE`` of the recoverable run: no sentence states the bits other
than ``illegal_insn``, or ``FATAL_ALERT_CAUSE`` after a recoverable error).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense +esrc_noise_force``.
Bounds: ``_OUTER_CLK`` is the outer limit of the clean-time measurement of the
command leg (logged ``bound=``); later waits use multiples of t_cmd.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_bit_watch import BitMark, BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_edge_timer import SepEdgeTimer
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_rv32_asm import ECALL, ZERO, add, csrw
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import ot_rdl_table_code
from sep_base_test import sep_base_test
from sep_reg_meta import OTBN
from seq_lib.sep_otbn_compute_seq import OPS, golden_result, otbn_compute_prog
from seq_lib.sep_otbn_seq import OTBN_RND_PROG, SepOtbn
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_otbn_cmd_status_rand_test"

# Codes of otbn.adoc CMD (:79-81) and STATUS (:113-118), from the value tables of the
# otbn.rdl field descriptions; the STATUS reset value from the generated register map.
CMD_EXECUTE = ot_rdl_table_code("otbn", "CMD", "EXECUTE")
CMD_SEC_WIPE_DMEM = ot_rdl_table_code("otbn", "CMD", "SEC_WIPE_DMEM")
CMD_SEC_WIPE_IMEM = ot_rdl_table_code("otbn", "CMD", "SEC_WIPE_IMEM")
COMMANDS = (CMD_EXECUTE, CMD_SEC_WIPE_DMEM, CMD_SEC_WIPE_IMEM)
ST_IDLE = ot_rdl_table_code("otbn", "STATUS", "IDLE")
ST_BUSY_EXECUTE = ot_rdl_table_code("otbn", "STATUS", "BUSY_EXECUTE")
ST_BUSY = {
    CMD_EXECUTE: ST_BUSY_EXECUTE,
    CMD_SEC_WIPE_DMEM: ot_rdl_table_code("otbn", "STATUS", "BUSY_SEC_WIPE_DMEM"),
    CMD_SEC_WIPE_IMEM: ot_rdl_table_code("otbn", "STATUS", "BUSY_SEC_WIPE_IMEM"),
}
ST_SEC_WIPE_INT = ot_rdl_table_code("otbn", "STATUS", "BUSY_SEC_WIPE_INT")
ST_LOCKED = ot_rdl_table_code("otbn", "STATUS", "LOCKED")
ST_RESET = OTBN.reset32("STATUS")  # otbn.adoc:106

A_INTR_STATE = OTBN.addr("INTR_STATE")
A_INTR_ENABLE = OTBN.addr("INTR_ENABLE")
A_INTR_TEST = OTBN.addr("INTR_TEST")
A_CMD = OTBN.addr("CMD")
A_CTRL = OTBN.addr("CTRL")
A_STATUS = OTBN.addr("STATUS")
A_ERR_BITS = OTBN.addr("ERR_BITS")
A_FATAL = OTBN.addr("FATAL_ALERT_CAUSE")
A_INSN_CNT = OTBN.addr("INSN_CNT")
M_DONE = OTBN.field_mask("INTR_STATE", "done")
M_EN_DONE = OTBN.field_mask("INTR_ENABLE", "done")
M_TEST_DONE = OTBN.field_mask("INTR_TEST", "done")
M_STATUS = OTBN.field_mask("STATUS", "status")
M_CTRL_SWERR = OTBN.field_mask("CTRL", "software_errs_fatal")
M_INSN = OTBN.field_mask("INSN_CNT", "insn_cnt")
M_ERR_BITS = OTBN.mask32("ERR_BITS")
M_FATAL = OTBN.mask32("FATAL_ALERT_CAUSE")
M_ERR_ILLEGAL = OTBN.field_mask("ERR_BITS", "illegal_insn")
M_ERR_RND_REP = OTBN.field_mask("ERR_BITS", "rnd_rep_chk_fail")
M_ERR_FATAL_SW = OTBN.field_mask("ERR_BITS", "fatal_software")
M_FATAL_SW = OTBN.field_mask("FATAL_ALERT_CAUSE", "fatal_software")

# ``unimp`` (base-insns.yml :681-690): CSRRW x0, 0xC00, x0. 0xC00 is not an OTBN CSR
# (csr.yml), so the instruction is an ILLEGAL_INSN software error. The ``ecall``
# after it ends the program cleanly if the error is not raised.
CSR_CYCLE = 0xC00
OTBN_UNIMP_PROG = (csrw(CSR_CYCLE, ZERO), ECALL)

# Vector bit 29 is PIC source 30, OTBN done (interrupts.adoc:22, :164-166).
VEC_OTBN_DONE = 29

# DMEM layout of the compute program: [0] = a, [4] = b, [8] = result.
DMEM_A, DMEM_B, DMEM_RES = 0x0, 0x4, 0x8

# Leaf choices (not from the specification).
_OUTER_CLK = 200_000  # outer limit of a clean-time wait
_T_MULT = 8  # bound of a later command wait, in t_cmd
_DONE_WIN_MULT = 2  # enable-clear watch window of the done-line leg, in t_cmd
_IGNORE_WIN_MULT = 4  # ignored-command window, in t_cmd (contract)
_RST_BOUND_CLK = 1_000  # gated reset release wait
_LINE_BOUND_CLK = 64  # vector bit 29 follow wait after a register write


@dataclass(frozen=True)
class Plan:
    seq: tuple[int, ...]
    gaps: tuple[int, ...]
    op: str
    opa: int
    opb: int
    a: int
    b: int
    en_order: tuple[int, int]
    k: int
    bad_cmd: int
    j: int
    errclr: int

    def line(self, seed: int) -> str:
        return (
            f"PLAN seed={seed} seq={','.join(f'0x{c:02x}' for c in self.seq)} "
            f"gaps={','.join(map(str, self.gaps))} op={self.op} opa=0x{self.opa:08x} "
            f"opb=0x{self.opb:08x} a={self.a} b={self.b} "
            f"en_order={','.join(map(str, self.en_order))} k={self.k} "
            f"bad_cmd=0x{self.bad_cmd:02x} j={self.j} errclr=0x{self.errclr:08x}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    n = rng.randrange(3, 6)
    seq = list(COMMANDS)
    rng.shuffle(seq)
    seq += [rng.choice(COMMANDS) for _ in range(n - len(COMMANDS))]
    rng.shuffle(seq)
    gaps = tuple(rng.randrange(0, 201) for _ in seq)
    op = rng.choice(OPS)
    opa = rng.getrandbits(32)
    opb = rng.getrandbits(32)
    a = rng.randrange(0, 40)
    b = rng.randrange(a + 1, 41)
    en_order = [1, 0]
    rng.shuffle(en_order)
    k = rng.randrange(1, 5)
    bad_cmd = rng.choice([c for c in range(256) if c not in COMMANDS])
    j = rng.randrange(1, 5)
    errclr = rng.getrandbits(32)
    return Plan(
        tuple(seq), gaps, op, opa, opb, a, b, (en_order[0], en_order[1]), k, bad_cmd, j, errclr
    )


def prog_with_extra(op: str, k: int) -> tuple[int, ...]:
    """The compute program with k extra independent ``add x13, x13, x0`` before ``ecall``."""
    base = otbn_compute_prog(op)
    return base[:-1] + (add(13, 13, ZERO),) * k + base[-1:]


def _now_ps() -> int:
    return int(get_sim_time("ps"))


def _runs(vals: list[int]) -> str:
    """Run-length form of a list of polled codes, for a log line."""
    out: list[str] = []
    for v in vals:
        s = f"0x{v:02x}"
        if not out or out[-1] != s:
            out.append(s)
    return ",".join(out) or "-"


@pyuvm.test()
class sep_otbn_cmd_status_rand_test(sep_base_test):
    """OTBN commands, status codes, INSN_CNT, the done line and the ignored writes."""

    required_evidence = (
        "CHK-OTBN-CMD-END",
        "CHK-OTBN-CMD-BUSY",
        "CHK-OTBN-INSN",
        "CHK-OTBN-DONE-LINE",
        "CHK-OTBN-CMD-IGNORE",
        "CHK-OTBN-BUSYWR",
        "CHK-OTBN-INITDONE",
        "CHK-OTBN-SWERR-FATAL",
        "CHK-OTBN-LOCKED-HOLD",
        "CHK-OTBN-SWERR-RECOV",
        "CHK-OTBN-ERRCLR",
        "CHK-OTBN-BUSYWR-ERR",
        "CHK-OTBN-CMDIGN-ERR",
    )

    # ------------------------------------------------------------- helpers
    async def _rd(self, addr: int, mask: int = 0xFFFF_FFFF) -> int:
        return (await self.otbn._rd(addr)) & mask

    async def _wr(self, addr: int, val: int) -> None:
        await self.otbn._wr(addr, val)

    def _clk(self) -> int:
        return self.irq.clk

    async def _poll_status(self, pred, bound: int, *, gap: int = 0) -> tuple[bool, list[int], int]:
        """Read STATUS until ``pred(code)``; returns (met, codes read, clocks)."""
        start = self._clk()
        vals: list[int] = []
        while True:
            st = await self._rd(A_STATUS, M_STATUS)
            vals.append(st)
            if pred(st):
                return True, vals, self._clk() - start
            if self._clk() - start > bound:
                return False, vals, self._clk() - start
            if gap:
                await ClockCycles(cocotb.top.clk_i, gap)

    async def _poll_done_marked(self, bound: int) -> tuple[bool, BitMark | None]:
        """Read INTR_STATE until ``done`` reads 1; return (seen, mark before the last 0 read).

        A read that shows ``done`` = 0 was sampled after its mark, so with the enable set
        the line cannot have risen before that mark.
        """
        start = self._clk()
        last0 = None
        while True:
            m = self.irq.mark()
            if await self._rd(A_INTR_STATE, M_DONE):
                return True, last0
            last0 = m
            if self._clk() - start > bound:
                return False, last0

    async def _wait_idle(self, bound: int, *, gap: int = 0) -> tuple[bool, list[int], int]:
        return await self._poll_status(lambda s: s == ST_IDLE, bound, gap=gap)

    async def _reset_otbn(self, tag: str) -> tuple[bool, str]:
        """Pulse the OTBN bit of SW_RESET_N, wait IDLE; return (reset arc ok, detail)."""
        t0 = _now_ps()
        await self.swrst.park("otbn")
        await self.swrst.release("otbn")
        dut = cocotb.top
        released = False
        for _ in range(_RST_BOUND_CLK):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.otbn_gated_rst_n_probe_o, mask=1):
                released = True
                break
        rises = self.rst_t.rises(t0, bit=0) if released else []
        ok, vals, clks = await self._wait_idle(self.idle_bound, gap=4)
        self.logger.info(
            "OTBN-RESET %s released=%d idle=%d clk=%d status=%s",
            tag,
            int(released),
            int(ok),
            clks,
            _runs(vals),
        )
        if not rises or not ok:
            return False, f"released={int(released)} rise={len(rises)} idle={int(ok)}"
        t_first = rises[-1] + self.period_ps
        first = self.status_t.value_at(t_first)
        after = [c.value for c in self.status_t.since(t_first + 1)]
        arc_ok = first == ST_SEC_WIPE_INT and after[:1] == [ST_IDLE]
        nxt = "none" if not after else ("X" if after[0] is None else f"0x{after[0]:02x}")
        first_s = "X" if first is None else f"0x{first:02x}"
        return arc_ok, f"arc={first_s},{nxt}"

    async def _clear_done(self) -> int:
        await self._wr(A_INTR_STATE, M_DONE)
        return await self._rd(A_INTR_STATE, M_DONE)

    async def _stage_compute(self, prog: tuple[int, ...]) -> int:
        """Load ``prog``, stage the operands, pre-seed the result with ~golden."""
        p = self.plan
        golden = golden_result(p.op, p.opa, p.opb)
        await self.otbn.load_program(prog)
        await self.otbn.write_dmem(DMEM_A, p.opa)
        await self.otbn.write_dmem(DMEM_B, p.opb)
        await self.otbn.write_dmem(DMEM_RES, golden ^ 0xFFFF_FFFF)
        return golden

    def _line(self) -> int:
        lvl = self.irq.level("done")
        return -1 if lvl is None else lvl

    async def _line_settle(self) -> int:
        await ClockCycles(cocotb.top.clk_i, 4)
        return self._line()

    # ----------------------------------------------------- bring-up helpers
    async def _bring_up_chain(self, sinks: dict) -> None:
        close_graded_window(self.logger)
        await self.bring_up_entropy(strict=True, score_km=False, score_sinks=sinks)
        self.start_fifo_drain()

    async def _retire_chain(self) -> None:
        """Grade the running chain, then end its scoreboard before a TRNG reset."""
        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.drbg_sb.stop()

    # ------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("aes", "hmac", "kmac", "abr"))
        self.suppress_host_axi_transaction_info()
        self.swrst = getattr(self, "swrst", None) or SepSwReset(self)
        # SepEntropyCfg() selects the internal source in EXT_TRNG_SRC_SEL.
        await self._bring_up_chain({"otbn_urnd": "observe"})
        baseline = await self.swrst.read_back()
        self.swrst.value = baseline
        self.logger.info("BASELINE SW_RESET_N=0x%08x ext_trng_src_sel=internal", baseline)

        seed = self.random_seed()
        self.plan = plan = draw_plan(seed)
        self.logger.info(plan.line(seed))
        self.chk = SepChkLog(self, TEST, seed)
        self.otbn = SepOtbn(self)

        await RisingEdge(dut.clk_i)
        t_a = _now_ps()
        await RisingEdge(dut.clk_i)
        self.period_ps = _now_ps() - t_a
        self.irq = SepBitWatch(dut.sep_internal_interrupts_probe_o, {"done": VEC_OTBN_DONE}).start()
        self.status_t = SepEdgeTimer(dut.otbn_status_probe_o, name="otbn_status").start()
        self.rst_t = SepEdgeTimer(dut.otbn_gated_rst_n_probe_o, name="otbn_gated_rst_n").start()
        self.idle_bound = _OUTER_CLK

        # Steps 3-4: the power-on wipe ends at IDLE (ToO:98), then reset, wipe then IDLE;
        # the done bit of the wipe is logged only.
        pre_idle, pre_vals, _ = await self._wait_idle(self.idle_bound, gap=4)
        t_pre = _now_ps()
        pre_status = self.rd(dut.otbn_status_probe_o, mask=M_STATUS)
        init_arc_ok, init_arc = await self._reset_otbn("initial")
        self.chk.ok("OTBN-INITDONE", init_arc_ok, seed=seed, reset_arc=init_arc)
        # The probe holds IDLE from the read before the pulse up to the clock before the
        # gated reset falls, so the 0x04 after the release is caused by the pulse.
        pre_falls = self.rst_t.falls(t_pre, bit=0)
        t_fall = pre_falls[0] if pre_falls else None
        pre_moves = None if t_fall is None else len(self.status_t.since(t_pre, until_ps=t_fall - 1))
        at_fall = None if t_fall is None else self.status_t.value_at(t_fall - 1)
        self.chk.ctrl(
            "OTBN-INITDONE",
            pre_idle and pre_status == ST_IDLE and pre_moves == 0 and at_fall == ST_IDLE,
            seed=seed,
            pre_idle=int(pre_idle),
            status_before_reset=f"0x{pre_status:02x}",
            pre_polled=_runs(pre_vals),
            moves_to_fall="none" if pre_moves is None else pre_moves,
            status_at_fall="none" if at_fall is None else f"0x{at_fall:02x}",
        )
        # No sentence states INTR_STATE.done after the post-reset wipe.
        init_done = await self._rd(A_INTR_STATE, M_DONE)
        after = await self._clear_done()
        self.chk.obs(
            "OTBN-INITDONE-DONE",
            seed=seed,
            done=init_done,
            done_after_w1c=after,
            reason="done_after_reset_wipe_unstated",
        )

        open_graded_window(TEST, self.logger)
        cmd_end_pass = await self._command_leg(seed)
        self.idle_bound = max(_T_MULT * self.t_cmd, 1)
        await self._insn_leg(seed)
        await self._done_line_leg(seed)
        busy_ok = await self._busy_write_leg(seed)
        recov_err = await self._sw_error_leg(seed)
        await self._ignored_leg(seed)
        close_graded_window(self.logger)

        self.chk.ctrl(
            "OTBN-CMD-IGNORE",
            cmd_end_pass and busy_ok,
            seed=seed,
            cmd_end_done=int(cmd_end_pass),
            busy_status_0x01=int(busy_ok),
        )
        self.chk.ctrl(
            "OTBN-LOCKED-HOLD", cmd_end_pass, seed=seed, cmd_at_idle_done=int(cmd_end_pass)
        )
        self.chk.ctrl(
            "OTBN-SWERR-RECOV", cmd_end_pass, seed=seed, cmd_end_err_bits_0=int(cmd_end_pass)
        )
        self.chk.ctrl(
            "OTBN-BUSYWR-ERR", recov_err != 0, seed=seed, recov_err_bits=f"0x{recov_err:x}"
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        await self.irq.stop()
        await self.status_t.stop()
        await self.rst_t.stop()
        self.chk.finish()

    # ---------------------------------------------------------- command leg
    async def _command_leg(self, seed: int) -> bool:
        """Steps 5-9. Returns True when a command set ``done`` from a cleared state."""
        p = self.plan
        counts: list[int] = []
        any_pass = False
        for idx, (cmd, gap) in enumerate(zip(p.seq, p.gaps, strict=True)):
            if gap:
                await ClockCycles(cocotb.top.clk_i, gap)
            if cmd == CMD_EXECUTE:
                await self._stage_compute(otbn_compute_prog(p.op))
            done_before = await self._rd(A_INTR_STATE, M_DONE)
            pre = await self._rd(A_STATUS, M_STATUS)
            t0 = _now_ps()
            await self._wr(A_CMD, cmd)
            ok, vals, clks = await self._wait_idle(_OUTER_CLK)
            busy = [c.value for c in self.status_t.since(t0) if c.value != ST_IDLE]
            first = busy[0] if busy else None
            first_s = "none" if not busy else ("X" if first is None else f"0x{first:02x}")
            self.chk.obs(
                "OTBN-STATUS-SEQ", seed=seed, idx=idx, cmd=f"0x{cmd:02x}", polled=_runs(vals)
            )
            self.chk.ok(
                "OTBN-CMD-BUSY",
                first == ST_BUSY[cmd],
                seed=seed,
                idx=idx,
                cmd=f"0x{cmd:02x}",
                first_busy=first_s,
                expect=f"0x{ST_BUSY[cmd]:02x}",
            )
            if not ok:
                self.chk.ok(
                    "OTBN-CMD-END",
                    False,
                    seed=seed,
                    idx=idx,
                    cmd=f"0x{cmd:02x}",
                    reason="timeout",
                    bound=_OUTER_CLK,
                    last=f"0x{vals[-1]:02x}",
                )
                await self._reset_otbn(f"cmd{idx}-timeout")
                await self._clear_done()
                continue
            counts.append(clks)
            done = await self._rd(A_INTR_STATE, M_DONE)
            err = await self._rd(A_ERR_BITS, M_ERR_BITS)
            fatal = await self._rd(A_FATAL, M_FATAL)
            cleared = await self._clear_done()
            cond = (
                pre == ST_IDLE
                and done_before == 0
                and ST_LOCKED not in vals
                and done == 1
                and err == 0
                and fatal == 0
            )
            any_pass = any_pass or cond
            self.chk.ok(
                "OTBN-CMD-END",
                cond,
                seed=seed,
                idx=idx,
                cmd=f"0x{cmd:02x}",
                pre=f"0x{pre:02x}",
                final=f"0x{vals[-1]:02x}",
                locked_seen=int(ST_LOCKED in vals),
                done_state=done,
                err_bits=f"0x{err:x}",
                fatal_cause=f"0x{fatal:x}",
                ctrl_done_before=done_before,
                clk=clks,
                done_after_w1c=cleared,
            )
        self.t_cmd = max(counts) if counts else _OUTER_CLK
        self.logger.info("OTBN t_cmd=%d clocks (bound=%d)", self.t_cmd, _OUTER_CLK)
        return any_pass

    # ---------------------------------------------------------- INSN_CNT leg
    async def _insn_leg(self, seed: int) -> None:
        """Steps 10-12 for P(a) and P(b)."""
        p = self.plan
        cnt: dict[str, int] = {}
        n_prog: dict[str, int] = {}
        resets: dict[str, int] = {}
        res_ok: dict[str, bool] = {}
        arcs: dict[str, str] = {}
        arcs_ok = True
        timeout = False
        for name, k in (("a", p.a), ("b", p.b)):
            arc_ok, arc = await self._reset_otbn(f"insn-{name}")
            arcs_ok = arcs_ok and arc_ok
            arcs[name] = arc
            await self._clear_done()
            resets[name] = await self._rd(A_INSN_CNT, M_INSN)
            prog = prog_with_extra(p.op, k)
            n_prog[name] = len(prog)
            golden = await self._stage_compute(prog)
            await self._wr(A_CMD, CMD_EXECUTE)
            ok, vals, _ = await self._wait_idle(self.idle_bound)
            if not ok:
                timeout = True
                self.chk.ok(
                    "OTBN-INSN",
                    False,
                    seed=seed,
                    run=name,
                    k=k,
                    reason="timeout",
                    bound=self.idle_bound,
                    last=f"0x{vals[-1]:02x}",
                )
                await self._reset_otbn(f"insn-{name}-timeout")
                continue
            cnt[name] = await self._rd(A_INSN_CNT, M_INSN)
            got = await self.otbn.read_dmem(DMEM_RES)
            res_ok[name] = got == golden
            self.logger.info(
                "OTBN INSN run=%s k=%d insn_cnt=%d result=0x%08x golden=0x%08x",
                name,
                k,
                cnt[name],
                got,
                golden,
            )
        if timeout:
            return
        diff = cnt["b"] - cnt["a"]
        cond = (
            resets["a"] == 0
            and resets["b"] == 0
            and diff == p.b - p.a
            and cnt["a"] == n_prog["a"]
            and cnt["b"] == n_prog["b"]
            and res_ok["a"]
            and res_ok["b"]
            and arcs_ok
        )
        self.chk.ok(
            "OTBN-INSN",
            cond,
            seed=seed,
            a=p.a,
            b=p.b,
            cnt_reset=f"{resets['a']},{resets['b']}",
            cnt_a=cnt["a"],
            cnt_b=cnt["b"],
            expect_cnt=f"{n_prog['a']},{n_prog['b']}",
            diff=diff,
            expect=p.b - p.a,
            result_eq_golden=f"{int(res_ok['a'])},{int(res_ok['b'])}",
            reset_arc=f"a:{arcs['a']} b:{arcs['b']}",
        )

    # --------------------------------------------------------- done-line leg
    async def _done_line_leg(self, seed: int) -> None:
        """Steps 13-16."""
        p = self.plan
        bound = self.idle_bound
        win = _DONE_WIN_MULT * self.t_cmd
        for en in p.en_order:
            await self._reset_otbn(f"done-en{en}")
            st0 = await self._clear_done()
            vec0 = await self._line_settle()
            await self._wr(A_INTR_ENABLE, M_EN_DONE if en else 0)
            st1 = await self._rd(A_INTR_STATE, M_DONE)
            await self._stage_compute(otbn_compute_prog(p.op))
            mark = self.irq.mark()
            await self._wr(A_CMD, CMD_EXECUTE)
            last0 = None
            if en:
                _, last0 = await self._poll_done_marked(bound)
            ok, vals, _ = await self._wait_idle(bound)
            done = await self._rd(A_INTR_STATE, M_DONE)
            if not ok or done != 1:
                self.chk.ok(
                    "OTBN-DONE-LINE",
                    False,
                    seed=seed,
                    enable=en,
                    reason="timeout",
                    bound=bound,
                    state=done,
                    last=f"0x{vals[-1]:02x}",
                )
                await self._reset_otbn(f"done-en{en}-timeout")
                continue
            if en == 0:
                await ClockCycles(cocotb.top.clk_i, win)
                high = self.irq.high_clocks_since(mark, "done")
                m2 = self.irq.mark()
                await self._wr(A_INTR_ENABLE, M_EN_DONE)
                try:
                    await self.irq.wait_rise(m2, _LINE_BOUND_CLK, "done")
                    rose = 1
                except AssertionError:
                    rose = 0
                state_en = await self._rd(A_INTR_STATE, M_DONE)
                vec_en = self._line()
                # The line equals done AND enable at every sample: no fall from the
                # enable write to the W1C write while both bits are 1.
                falls = self.irq.fall_clks_since(m2, "done")
                await self._wr(A_INTR_STATE, M_DONE)
                st_clr = await self._rd(A_INTR_STATE, M_DONE)
                vec_clr = await self._line_settle()
                cond = (
                    st0 == 0
                    and vec0 == 0
                    and st1 == 0
                    and high == 0
                    and rose == 1
                    and state_en == 1
                    and vec_en == 1
                    and not falls
                    and st_clr == 0
                    and vec_clr == 0
                )
                self.chk.ok(
                    "OTBN-DONE-LINE",
                    cond,
                    seed=seed,
                    via="cmd",
                    enable=0,
                    vec29_falls_before_w1c=len(falls),
                    state=done,
                    vec29_high_clk=high,
                    window_clk=win,
                    then_enable=1,
                    vec29_rose=rose,
                    vec29=vec_en,
                    then_w1c_state=st_clr,
                    w1c_vec29=vec_clr,
                    pre_state=st0,
                    pre_vec29=vec0,
                )
            else:
                try:
                    rise_clk = await self.irq.wait_rise(mark, _LINE_BOUND_CLK, "done")
                except BitWatchTimeout:
                    rise_clk = None
                rose = int(rise_clk is not None)
                in_order = int(rose == 1 and last0 is not None and rise_clk >= last0.clk)
                vec_en = self._line()
                # No fall from the rise to the W1C write while done and enable are both 1.
                falls = self.irq.fall_clks_since(mark, "done")
                await self._wr(A_INTR_STATE, M_DONE)
                st_clr = await self._rd(A_INTR_STATE, M_DONE)
                vec_clr = await self._line_settle()
                cond = (
                    st0 == 0
                    and vec0 == 0
                    and st1 == 0
                    and rose == 1
                    and in_order == 1
                    and vec_en == 1
                    and not falls
                    and st_clr == 0
                    and vec_clr == 0
                )
                self.chk.ok(
                    "OTBN-DONE-LINE",
                    cond,
                    seed=seed,
                    via="cmd",
                    enable=1,
                    state=done,
                    vec29_rose=rose,
                    rise_clk=rise_clk if rise_clk is not None else "none",
                    last_done0_clk=last0.clk if last0 is not None else "none",
                    cmd_clk=mark.clk,
                    rise_after_done0=in_order,
                    vec29=vec_en,
                    vec29_falls_before_w1c=len(falls),
                    then_w1c_state=st_clr,
                    w1c_vec29=vec_clr,
                    pre_state=st0,
                    pre_vec29=vec0,
                )
        await self._intr_test_leg(seed, win)

    async def _intr_test_leg(self, seed: int, win: int) -> None:
        """Step 16: the line follows the enable with the state set by INTR_TEST."""
        await self._wr(A_INTR_ENABLE, 0)
        mark = self.irq.mark()
        await self._wr(A_INTR_TEST, M_TEST_DONE)
        st_set = await self._rd(A_INTR_STATE, M_DONE)
        await ClockCycles(cocotb.top.clk_i, win)
        high = self.irq.high_clocks_since(mark, "done")
        m_on = self.irq.mark()
        await self._wr(A_INTR_ENABLE, M_EN_DONE)
        try:
            await self.irq.wait_rise(m_on, _LINE_BOUND_CLK, "done")
            rose = 1
        except AssertionError:
            rose = 0
        # No fall from the enable write to the enable-0 write while both bits are 1.
        on_falls = self.irq.fall_clks_since(m_on, "done")
        await self._wr(A_INTR_ENABLE, 0)
        try:
            await self.irq.wait_level(0, _LINE_BOUND_CLK, "done")
            fell = 1
        except AssertionError:
            fell = 0
        await self._wr(A_INTR_STATE, M_DONE)
        st_clr = await self._rd(A_INTR_STATE, M_DONE)
        vec_clr = await self._line_settle()
        cond = (
            st_set == 1
            and high == 0
            and rose == 1
            and not on_falls
            and fell == 1
            and st_clr == 0
            and vec_clr == 0
        )
        self.chk.ok(
            "OTBN-DONE-LINE",
            cond,
            seed=seed,
            via="test",
            enable=0,
            state=st_set,
            vec29_high_clk=high,
            window_clk=win,
            then_enable=1,
            vec29_rose=rose,
            vec29_falls_while_enabled=len(on_falls),
            then_enable0_vec29_fell=fell,
            then_w1c_enable0_state=st_clr,
            w1c_vec29=vec_clr,
        )
        # Enable-set INTR_TEST cell: control of this leg.
        await self._wr(A_INTR_ENABLE, M_EN_DONE)
        m_c = self.irq.mark()
        await self._wr(A_INTR_TEST, M_TEST_DONE)
        try:
            await self.irq.wait_rise(m_c, _LINE_BOUND_CLK, "done")
            c_rose = 1
        except AssertionError:
            c_rose = 0
        c_falls = self.irq.fall_clks_since(m_c, "done")
        await self._wr(A_INTR_STATE, M_DONE)
        await self._rd(A_INTR_STATE, M_DONE)
        c_clr = await self._line_settle()
        self.chk.ctrl(
            "OTBN-DONE-LINE",
            c_rose == 1 and not c_falls and c_clr == 0,
            seed=seed,
            via="test",
            enable=1,
            vec29_rose=c_rose,
            vec29_falls_before_w1c=len(c_falls),
            w1c_vec29=c_clr,
        )
        await self._wr(A_INTR_ENABLE, 0)

    # -------------------------------------------------------- busy-write leg
    async def _busy_write_leg(self, seed: int) -> bool:
        """Steps 17-22. Returns True when STATUS read 0x01 before the busy writes."""
        p = self.plan
        dut = cocotb.top
        await self._reset_otbn("busywr")
        await self._clear_done()
        ctrl_pre = await self._rd(A_CTRL, M_CTRL_SWERR)
        await self.otbn.load_program(OTBN_RND_PROG)

        # The TRNG reset clears the chain under the running scoreboard: grade it first.
        close_graded_window(self.logger)
        await self._retire_chain()
        open_graded_window(TEST, self.logger)

        await self.swrst.park("trng")
        for _ in range(_RST_BOUND_CLK):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.trng_reset_active_probe_o, mask=1):
                break
        await self._wr(A_CMD, CMD_EXECUTE)
        busy, vals, clks = await self._poll_status(lambda s: s == ST_BUSY_EXECUTE, self.idle_bound)
        ctrl_reads: list[int] = []
        st_after_ctrl: list[int] = []
        st_after_cmd: list[int] = []
        if busy:
            for _ in range(p.k):
                await self._wr(A_CTRL, M_CTRL_SWERR)
                ctrl_reads.append(await self._rd(A_CTRL, M_CTRL_SWERR))
                st_after_ctrl.append(await self._rd(A_STATUS, M_STATUS))
            for _ in range(p.j):
                await self._wr(A_CMD, CMD_SEC_WIPE_DMEM)
                st_after_cmd.append(await self._rd(A_STATUS, M_STATUS))
            self.chk.ok(
                "OTBN-CMD-IGNORE",
                all(s == ST_BUSY_EXECUTE for s in st_after_cmd),
                seed=seed,
                case="busy_wipe",
                cmd=f"0x{CMD_SEC_WIPE_DMEM:02x}",
                status=",".join(f"0x{s:02x}" for s in st_after_cmd),
                done="n/a",
                window_clk="n/a",
                writes=p.j,
            )

        # Steps 21-22: release the TRNG reset, bring the chain up, finish.
        await self.swrst.release("trng")
        await self._bring_up_chain({"otbn_rnd": "observe"})
        open_graded_window(TEST, self.logger)
        idle, ivals, _ = await self._wait_idle(_OUTER_CLK, gap=4)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        # Bit 6 (two equal EDN words) is a chance outcome: logged, not graded.
        self.chk.obs(
            "OTBN-BUSYWR-RNDREP", seed=seed, rnd_rep_chk_fail=int(bool(err & M_ERR_RND_REP))
        )
        err_graded = err & ~M_ERR_RND_REP
        self.chk.ok(
            "OTBN-BUSYWR-ERR",
            idle and err_graded == 0,
            seed=seed,
            idle_after_release=int(idle),
            err_bits=f"0x{err:x}",
            err_bits_without_rnd_rep=f"0x{err_graded:x}",
            expect="0x0",
        )
        st_rel = await self._rd(A_STATUS, M_STATUS)
        await self._wr(A_CTRL, M_CTRL_SWERR)
        ctrl_idle = await self._rd(A_CTRL, M_CTRL_SWERR)
        self.chk.ctrl("OTBN-BUSYWR", ctrl_idle == 1, seed=seed, ctrl_after_idle_write=ctrl_idle)
        if not busy:
            self.chk.ok(
                "OTBN-BUSYWR",
                False,
                seed=seed,
                reason="timeout",
                bound=self.idle_bound,
                status=_runs(vals),
                clk=clks,
            )
        else:
            cond = (
                ctrl_pre == 0
                and all(c == 0 for c in ctrl_reads)
                and all(s == ST_BUSY_EXECUTE for s in st_after_ctrl)
                and idle
                and st_rel != ST_LOCKED
            )
            self.chk.ok(
                "OTBN-BUSYWR",
                cond,
                seed=seed,
                ctrl_pre=ctrl_pre,
                busy_status=f"0x{ST_BUSY_EXECUTE:02x}",
                busy_writes=p.k,
                ctrl_after_busy_write=",".join(map(str, ctrl_reads)),
                status_after_busy_write=",".join(f"0x{s:02x}" for s in st_after_ctrl),
                idle_after_release=int(idle),
                status_after_release=f"0x{st_rel:02x}",
                ctrl_after_idle_write=ctrl_idle,
                release_status=_runs(ivals),
            )
        await self._reset_otbn("busywr-end")
        return busy

    # ---------------------------------------------------- software-error leg
    async def _run_unimp(self, fatal_cfg: int) -> tuple[int, int, list[int], int]:
        """Write CTRL at IDLE, run the ``unimp`` program; return (ctrl, done_before, codes, clk).

        The poll ends at the first IDLE or LOCKED read.
        """
        await self._clear_done()
        await self._wr(A_CTRL, M_CTRL_SWERR if fatal_cfg else 0)
        ctrl = await self._rd(A_CTRL, M_CTRL_SWERR)
        await self.otbn.load_program(OTBN_UNIMP_PROG)
        done_before = await self._rd(A_INTR_STATE, M_DONE)
        await self._wr(A_CMD, CMD_EXECUTE)
        _, vals, clks = await self._poll_status(
            lambda s: s in (ST_IDLE, ST_LOCKED), self.idle_bound
        )
        return ctrl, done_before, vals, clks

    async def _sw_error_leg(self, seed: int) -> int:
        """The ``unimp`` program, fatal then recoverable. Returns ERR_BITS of the recoverable run."""
        win = _IGNORE_WIN_MULT * self.t_cmd
        # Fatal: software_errs_fatal = 1.
        ctrl, done0, vals, clks = await self._run_unimp(1)
        st = vals[-1]
        done = await self._rd(A_INTR_STATE, M_DONE)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        fatal = await self._rd(A_FATAL, M_FATAL)
        self.chk.ok(
            "OTBN-SWERR-FATAL",
            ctrl == 1
            and done0 == 0
            and st == ST_LOCKED
            and done == 1
            and err != 0
            and bool(err & M_ERR_FATAL_SW)
            and bool(fatal & M_FATAL_SW),
            seed=seed,
            ctrl=ctrl,
            status=_runs(vals),
            final=f"0x{st:02x}",
            expect=f"0x{ST_LOCKED:02x}",
            done=done,
            pre_done=done0,
            err_bits=f"0x{err:x}",
            fatal_cause=f"0x{fatal:x}",
            clk=clks,
            bound=self.idle_bound,
        )
        # LOCKED hold: a recognised command at LOCKED, then the OTBN reset exit.
        await self._wr(A_CMD, CMD_EXECUTE)
        _, hvals, hclks = await self._poll_status(lambda s: s != ST_LOCKED, win)
        fatal_hold = await self._rd(A_FATAL, M_FATAL)
        exit_ok, exit_arc = await self._reset_otbn("swerr-fatal-exit")
        st_exit = await self._rd(A_STATUS, M_STATUS)
        fatal_exit = await self._rd(A_FATAL, M_FATAL)
        self.chk.ok(
            "OTBN-LOCKED-HOLD",
            st == ST_LOCKED
            and all(v == ST_LOCKED for v in hvals)
            and fatal_hold == fatal
            and exit_ok
            and st_exit == ST_IDLE
            and fatal_exit == 0,
            seed=seed,
            cmd=f"0x{CMD_EXECUTE:02x}",
            hold_status=_runs(hvals),
            hold_polls=len(hvals),
            window_clk=hclks,
            fatal_before=f"0x{fatal:x}",
            fatal_after_cmd=f"0x{fatal_hold:x}",
            reset_arc=exit_arc,
            status_after_reset=f"0x{st_exit:02x}",
            fatal_after_reset=f"0x{fatal_exit:x}",
        )
        # Recoverable: software_errs_fatal = 0, same program.
        rctrl, rdone0, rvals, rclks = await self._run_unimp(0)
        rst = rvals[-1]
        rdone = await self._rd(A_INTR_STATE, M_DONE)
        rerr = await self._rd(A_ERR_BITS, M_ERR_BITS)
        rfatal = await self._rd(A_FATAL, M_FATAL)
        self.chk.ok(
            "OTBN-SWERR-RECOV",
            rctrl == 0
            and rdone0 == 0
            and rst == ST_IDLE
            and ST_LOCKED not in rvals
            and rdone == 1
            and bool(rerr & M_ERR_ILLEGAL),
            seed=seed,
            ctrl=rctrl,
            status=_runs(rvals),
            final=f"0x{rst:02x}",
            expect=f"0x{ST_IDLE:02x}",
            done=rdone,
            pre_done=rdone0,
            illegal_insn=int(bool(rerr & M_ERR_ILLEGAL)),
            clk=rclks,
            bound=self.idle_bound,
        )
        # No sentence states the other ERR_BITS bits, or FATAL_ALERT_CAUSE, here.
        self.chk.obs(
            "OTBN-SWERR-CAUSE", seed=seed, err_bits=f"0x{rerr:x}", fatal_cause=f"0x{rfatal:x}"
        )
        self.chk.ctrl(
            "OTBN-SWERR-FATAL",
            rst == ST_IDLE and ST_LOCKED not in rvals,
            seed=seed,
            software_errs_fatal=0,
            final=f"0x{rst:02x}",
        )
        return rerr

    # ------------------------------------------------------ ignored-cmd leg
    async def _ignored_leg(self, seed: int) -> None:
        """Step 23, then the ERR_BITS clear at IDLE."""
        p = self.plan
        win = _IGNORE_WIN_MULT * self.t_cmd
        ok, _, _ = await self._wait_idle(self.idle_bound)
        st0 = await self._clear_done()
        err_pre = await self._rd(A_ERR_BITS, M_ERR_BITS)
        t0 = _now_ps()
        await self._wr(A_CMD, p.bad_cmd)
        _, vals, clks = await self._poll_status(lambda s: s != ST_IDLE, win)
        done = await self._rd(A_INTR_STATE, M_DONE)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        fatal = await self._rd(A_FATAL, M_FATAL)
        probe = [c.value for c in self.status_t.since(t0)]
        self.chk.ok(
            "OTBN-CMDIGN-ERR",
            err == err_pre,
            seed=seed,
            cmd=f"0x{p.bad_cmd:02x}",
            err_bits_before=f"0x{err_pre:x}",
            err_bits=f"0x{err:x}",
        )
        self.chk.ctrl("OTBN-CMDIGN-ERR", err_pre != 0, seed=seed, err_bits_before=f"0x{err_pre:x}")
        # ERR_BITS clear: a write of the drawn value at IDLE.
        st_clr = await self._rd(A_STATUS, M_STATUS)
        await self._wr(A_ERR_BITS, p.errclr)
        err_clr = await self._rd(A_ERR_BITS, M_ERR_BITS)
        self.chk.ok(
            "OTBN-ERRCLR",
            st_clr == ST_IDLE and err_clr == 0,
            seed=seed,
            status=f"0x{st_clr:02x}",
            written=f"0x{p.errclr:08x}",
            err_bits_before=f"0x{err:x}",
            err_bits_after=f"0x{err_clr:x}",
        )
        self.chk.ctrl("OTBN-ERRCLR", err != 0, seed=seed, err_bits_before=f"0x{err:x}")
        cond = ok and st0 == 0 and all(v == ST_IDLE for v in vals) and done == 0
        self.chk.ok(
            "OTBN-CMD-IGNORE",
            cond,
            seed=seed,
            case="idle_unrecognised",
            cmd=f"0x{p.bad_cmd:02x}",
            status=_runs(vals),
            polls=len(vals),
            done=done,
            window_clk=clks,
            writes=1,
            pre_done=st0,
            fatal_cause=f"0x{fatal:x}",
            probe_changes=len(probe),
        )

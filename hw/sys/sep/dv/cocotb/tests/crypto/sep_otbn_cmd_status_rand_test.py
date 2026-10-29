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
:66-70 (the FIPS tag that OTBN RND gets is tied high);
``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/doc/registers.md`` (``registers.md``
below) :173, :205-206, :246-247; ``hw/sys/sep/doc/crypto.adoc`` :141 (OTBN alert
receivers ``[2:1]`` of the crypto alert pulse vector).

Legs (one seed draws the plan, logged in one ``PLAN`` line):
  command    3 to 5 commands from EXECUTE, SEC_WIPE_DMEM and SEC_WIPE_IMEM (each
             at least once), each at IDLE after a drawn gap. In shard 3: 3 to 5
             EXECUTE commands, each at IDLE after a drawn gap.
  INSN_CNT   the compute program with a and b extra independent ADD
             instructions, each run after an OTBN reset.
  done line  two EXECUTE runs (enable 1 and enable 0, drawn order), then the
             ``INTR_TEST`` sub-leg.
  busy write an ``RND`` read held by the TRNG reset keeps ``STATUS`` at 0x01;
             k ``CTRL`` writes and j ``CMD`` = SEC_WIPE_DMEM writes.
  integrity  the compute program twice under ``+sep_otbn_intg_flip``: once with one
             drawn bit (0 to 38) of every IMEM word that the core fetches inverted,
             once with one drawn bit of a DMEM word that a ``lw`` of the program
             reads (word 0 or 1 of the line, bit 0 to 38 of the word) inverted. The
             flip is armed at the first clock that the OTBN status probe shows
             BUSY_EXECUTE and dropped at LOCKED; OTBN then stays LOCKED for a
             fixed window of 256 clocks before an OTBN reset.
  sw error   the ``unimp`` program (``CSRRW x0, 0xC00, x0`` then ``ecall``) with
             ``CTRL.software_errs_fatal`` = 1, a ``CMD`` write at LOCKED, an
             OTBN reset; then the same program with ``software_errs_fatal`` = 0.
             In shard 3: only the run with ``software_errs_fatal`` = 0.
  ignored    one unrecognised ``CMD`` value at IDLE, with ``ERR_BITS`` still
             holding the error of the sw error leg; then a write of a drawn
             value to ``ERR_BITS`` at IDLE.
  RND clean  after the busy-write leg, with the chain up and the TRNG running: the
             ``RND`` program after an OTBN reset, to its end at IDLE.
  sw kind    after the ignored leg: one drawn software error of four, each
             program followed by ``ecall``, with ``CTRL.software_errs_fatal`` = 0
             after an OTBN reset: BAD_DATA_ADDR (``lw`` at a drawn offset 1 to 3
             from address 0), BAD_INSN_ADDR (``jalr`` to PC 2), CALL_STACK
             (``jalr x0, x1, 0`` with an empty call stack), LOOP (``loopi`` with
             zero iterations).
  bus access the last leg (it locks OTBN): the ``RND`` program held at
             BUSY_EXECUTE by the TRNG reset, then one host read of a drawn IMEM
             or DMEM word that holds a non-zero value; then an OTBN reset.

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
                       reads that show ``done`` = 1 and ``STATUS`` IDLE. Each
                       write of 1 to ``INTR_STATE.done`` (RW1C, ``otbn.adoc``
                       :34) leaves ``done`` = 0 and the line 0; with ``done`` = 1
                       the line rises after ``INTR_ENABLE.done`` is set and
                       falls after it is cleared (``otbn.adoc`` :44).
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
  CHK-OTBN-IMEM-INTG   the IMEM run ends with ``STATUS`` = LOCKED (0xFF) on the bus
                       and on the OTBN status probe, ``done`` = 1 (read 0 before),
                       ``ERR_BITS.imem_intg_violation`` (bit 16) and
                       ``FATAL_ALERT_CAUSE.imem_intg_violation`` (bit 0) set, no
                       pulse on crypto alert ``[2:1]`` from the program load to the
                       ``CMD`` write, at least one pulse from the ``CMD`` write to
                       the LOCKED read, and at least one rise on ``[2:1]`` in the
                       LOCKED window (after the LOCKED reads and the flip drop,
                       before the OTBN reset), so the alert repeats after the error
                       without new stimulus; after the reset the probe shows 0x04 then
                       0x00, ``STATUS`` reads IDLE and ``FATAL_ALERT_CAUSE`` reads 0.
                       IMEM_INTG_VIOLATION "Data read from the instruction memory
                       failed the integrity checks." is fatal (ToO:261-263); "A
                       fatal error is raised whenever a data integrity violation is
                       detected" (ToO:371-373); ToO:180-189 (``ERR_BITS`` non-zero,
                       ``done``, LOCKED, fatal alert); "A fatal alert is a
                       continuously triggered alert" ... "can only be cleared by
                       resetting OTBN" (ToO:311-314); the receiver "pulses
                       ``alert_o`` when the handshake starts" (``crypto.adoc``
                       :125-126), so each repeat is a rise; ``registers.md`` :206
                       (``ERR_BITS`` bit 16), :247 (``FATAL_ALERT_CAUSE`` bit 0),
                       :173 (LOCKED 0xFF "must be reset to unlock it again");
                       ``crypto.adoc`` :141 (OTBN receivers ``[2:1]``).
  CHK-OTBN-DMEM-INTG   the same for the DMEM run, with ``ERR_BITS.dmem_intg_violation``
                       (bit 17) and ``FATAL_ALERT_CAUSE.dmem_intg_violation`` (bit 1).
                       DMEM_INTG_VIOLATION "Data read from the data memory failed
                       the integrity checks." is fatal (ToO:266-268); ToO:371-373,
                       :180-189, :311-314; ``registers.md`` :205, :246, :173;
                       ``crypto.adoc`` :141.
  CHK-OTBN-RND-CLEAN   the ``RND`` run reads ``software_errs_fatal`` = 0 and
                       ``done`` = 0 before the ``CMD`` write, ends at IDLE (never
                       0xFF) with ``done`` = 1 and at least one acknowledge of the
                       OTBN RND client (crypto EDN client 2, ``trng.adoc`` :90-91)
                       between the ``CMD`` write and IDLE, and ``ERR_BITS`` reads 0
                       in every bit except ``rnd_rep_chk_fail`` (bit 6). ToO:137;
                       "A high tag prevents a FIPS-tag failure for that response"
                       (``otbn.adoc`` :68-69).
  CHK-OTBN-SWERR-KIND  the program of the drawn error reads
                       ``software_errs_fatal`` = 0 and ``done`` = 0 before the
                       ``CMD`` write, ends at IDLE (never 0xFF) with ``done`` = 1,
                       and the ``ERR_BITS`` field of that error is set:
                       BAD_DATA_ADDR "if the computed address is not a valid 4-byte
                       aligned DMEM address" (``base-insns.yml`` :284), BAD_INSN_ADDR
                       "if the computed address is not a valid PC" (:380), CALL_STACK
                       "from using x1 as grs1 when the call stack is empty" (:38),
                       LOOP "if iterations is zero" (:636); all four are class
                       software (ToO:211-236); ToO:153, :168-170.
  CHK-OTBN-ILLEGAL-BUS phase lock: the OTBN status probe shows BUSY_EXECUTE at the
                       start of the host read and never IDLE after it, the read
                       returns 0 while the word holds a non-zero value, ``STATUS``
                       reads LOCKED (0xFF), and ``ERR_BITS.illegal_bus_access`` and
                       ``FATAL_ALERT_CAUSE.illegal_bus_access`` are set. "reads return
                       zero" ... "a memory access when OTBN is neither idle nor
                       locked will cause OTBN to generate a fatal error with code
                       ILLEGAL_BUS_ACCESS" (ToO:30-31); class fatal (ToO:286-288);
                       ToO:312-313. Phase exit: after an OTBN reset the probe shows
                       0x04 then 0x00, ``STATUS`` reads IDLE and
                       ``FATAL_ALERT_CAUSE`` reads 0 (ToO:114; ``otbn.hjson``
                       :672-673).

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
write), ``CTRL-OTBN-BUSYWR-ERR`` (the recoverable error run sets ``ERR_BITS``),
``CTRL-OTBN-IMEM-INTG`` and ``CTRL-OTBN-DMEM-INTG`` (the flip was armed during
BUSY_EXECUTE and ``otbn_intg_flip_count_o`` is non-zero at LOCKED, so a corrupted
read response reached the integrity check), ``CTRL-OTBN-SWERR-KIND`` (the same
program with a legal instruction in place of the faulting one ends at IDLE with
``ERR_BITS`` = 0), ``CTRL-OTBN-ILLEGAL-BUS`` (the same host read at IDLE returns the
non-zero staged word).
Log-only: ``OBS-OTBN-STATUS-SEQ``; ``OBS-OTBN-INITDONE-DONE`` (``INTR_STATE.done``
after the post-reset wipe: no sentence states its value); ``INFO-OTBN-BUSYWR-RNDREP`` (bit 6 after the RND
program, a chance outcome); ``OBS-OTBN-SWERR-CAUSE`` (the full ``ERR_BITS`` and
``FATAL_ALERT_CAUSE`` of the recoverable run: no sentence states the bits other
than ``illegal_insn``, or ``FATAL_ALERT_CAUSE`` after a recoverable error);
``OBS-OTBN-INTG-ALERT-IDX`` (the high clocks of each index of ``[2:1]`` after the
``CMD`` write and the rises of each index in the LOCKED window: no sentence names the
fatal index or the repeat period), ``OBS-OTBN-INTG-CAUSE`` (the full ``ERR_BITS`` and
``FATAL_ALERT_CAUSE`` of each integrity run: "a non-zero value that describes the
error", ToO:186, does not fix the other bits; also the alert high clocks in a fixed
window after the OTBN reset); ``INFO-OTBN-RND-CLEAN-RNDREP`` (bit 6 after the
clean RND run, a chance outcome); ``OBS-OTBN-SWERR-KIND-CAUSE`` (the full
``ERR_BITS`` and ``FATAL_ALERT_CAUSE`` of the drawn error: no sentence states the
other bits); ``OBS-OTBN-ILLEGAL-BUS-CAUSE`` (the full ``ERR_BITS`` and
``FATAL_ALERT_CAUSE`` at LOCKED, and the response code of the host read: no
sentence states the code); ``OBS-OTBN-WIPE-MEM`` (two words of the wiped memory
read after each SEC_WIPE command: the wipe leaves pseudo-random content, so no
value is stated).

Shards (``env/sep_shard.py``): ``+sep_shard=1`` runs every leg except RND clean
and sw kind; ``+sep_shard=2`` runs only RND clean and sw kind, with no
SEC_WIPE command and no LOCKED state; ``+sep_shard=3`` runs the initial reset, the
command leg with EXECUTE only, INSN_CNT, done line, busy write, the
``software_errs_fatal`` = 0 run of sw error, and ignored, with no LOCKED state and
no SEC_WIPE command at IDLE (the busy-write leg keeps its SEC_WIPE_DMEM writes at
0x01, which ``CHK-OTBN-CMD-IGNORE`` grades as ignored). Shard 3 grades every check
of these legs, and logs their controls, as the whole leaf does; its t_cmd is the
longest of its EXECUTE commands. Without the plusarg the leaf runs every leg.

FCOV: the graded window opens after the initial reset leg; a FAIL or a missing
control closes it for the rest of the run. The sampler holds each owned outcome of
``sep_otbn_op_cg`` and ``sep_otbn_err_lock_cg`` as pending at its DUT event; after a
check passes, and only while no check or control has failed, the leaf writes the
``otbn_cmd_pass`` bit of that check (``set_otbn_cmd_pass``) for two clocks, and only
then do the outcomes that check grades sample. ``cp_sw_err_kind`` follows
``otbn_sw_err_pass`` the same way; ``cp_rnd_clean`` samples at the graded
``ERR_BITS`` read, which the leaf takes last and only with the window open.
The ``otbn_done`` cells of ``sep_crypto_intr_cg`` are held the same way:
``cp_hw_raise`` waits for the ``CHK-OTBN-CMD-END`` bit; ``x_line_gate``,
``cp_w1c_clear`` and ``cp_enable_flip`` wait for the ``CHK-OTBN-DONE-LINE`` bit, which
the leaf writes after each passing done-line run and after the passing ``INTR_TEST``
sub-leg. An OTBN reset drops the line cells still held, so the line events of the
other legs never sample; ``fall_without_write`` samples at once.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense +esrc_noise_force
+sep_otbn_intg_flip``. The flip hook acts only while the leaf drives
``otbn_intg_flip_en_i`` to 1.
Bounds: ``_OUTER_CLK`` is the outer limit of the clean-time measurement of the
command leg (logged ``bound=``); later waits use multiples of t_cmd.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import BitMark, BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_edge_timer import SepEdgeTimer
from env.sep_fcov_gate import (
    OTBN_CMD_PASS_BUSYWR,
    OTBN_CMD_PASS_CMD_BUSY,
    OTBN_CMD_PASS_CMD_END,
    OTBN_CMD_PASS_DMEM_INTG,
    OTBN_CMD_PASS_DONE_LINE,
    OTBN_CMD_PASS_ERRCLR,
    OTBN_CMD_PASS_IGN_ERR,
    OTBN_CMD_PASS_IGNORE,
    OTBN_CMD_PASS_ILLEGAL_BUS,
    OTBN_CMD_PASS_IMEM_INTG,
    OTBN_CMD_PASS_INSN,
    OTBN_CMD_PASS_LOCKED_HOLD,
    OTBN_CMD_PASS_SWERR_FATAL,
    OTBN_CMD_PASS_SWERR_RECOV,
    close_graded_window,
    open_graded_window,
    set_otbn_cmd_pass,
    set_otbn_sw_err_pass,
)
from env.sep_rv32_asm import A0, ECALL, RA, ZERO, add, addi, csrw, jal, jalr, lw
from env.sep_seeded_rng import SepSeededRng
from env.sep_shard import sep_shard
from env.sep_spec_tables import ot_rdl_table_code
from sep_base_test import sep_base_test
from sep_reg_meta import OTBN
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_otbn_compute_seq import OPS, golden_result, loopi, otbn_compute_prog
from seq_lib.sep_otbn_seq import (
    OTBN_DMEM_BASE,
    OTBN_DMEM_RND_BASE,
    OTBN_IMEM_BASE,
    OTBN_RND_PROG,
    OTBN_RND_READS,
    SepOtbn,
)
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
M_ERR_IMEM_INTG = OTBN.field_mask("ERR_BITS", "imem_intg_violation")
M_ERR_DMEM_INTG = OTBN.field_mask("ERR_BITS", "dmem_intg_violation")
M_FATAL_IMEM_INTG = OTBN.field_mask("FATAL_ALERT_CAUSE", "imem_intg_violation")
M_FATAL_DMEM_INTG = OTBN.field_mask("FATAL_ALERT_CAUSE", "dmem_intg_violation")
M_ERR_ILLEGAL_BUS = OTBN.field_mask("ERR_BITS", "illegal_bus_access")
M_FATAL_ILLEGAL_BUS = OTBN.field_mask("FATAL_ALERT_CAUSE", "illegal_bus_access")

# The four software errors of the sw-kind leg, in the drawn order, and their
# ERR_BITS fields.
SW_KINDS = ("bad_data_addr", "bad_insn_addr", "call_stack", "loop")
M_ERR_SW_KIND = tuple(OTBN.field_mask("ERR_BITS", k) for k in SW_KINDS)

# OTBN alert receivers [2:1] of crypto_alert_pulse_probe_o (crypto.adoc:141).
OTBN_ALERT_IDX = (1, 2)

# Selector values of otbn_intg_flip_mem_i, and the 39-bit memory word of the bench
# hook (32 data bits and 7 integrity bits; DMEM word w of the read line is bits 39w
# to 39w+38).
FLIP_IMEM, FLIP_DMEM = 0, 1
INTG_WORD_BITS = 39

# ``unimp`` (base-insns.yml :681-690): CSRRW x0, 0xC00, x0. 0xC00 is not an OTBN CSR
# (csr.yml), so the instruction is an ILLEGAL_INSN software error. The ``ecall``
# after it ends the program cleanly if the error is not raised.
CSR_CYCLE = 0xC00
OTBN_UNIMP_PROG = (csrw(CSR_CYCLE, ZERO), ECALL)

# ``nop`` is ``ADDI x0, x0, 0`` (base-insns.yml :639-645).
NOP = addi(ZERO, ZERO, 0)


def sw_kind_progs(kind: int, off: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """(program that raises software error ``kind``, the same program with a legal
    instruction in place of the faulting one)."""
    if kind == 0:  # BAD_DATA_ADDR: address ``off`` (1 to 3) is not 4-byte aligned.
        return (lw(A0, ZERO, off), ECALL), (lw(A0, ZERO, 0), ECALL)
    if kind == 1:  # BAD_INSN_ADDR: PC 2 is not 4-byte aligned; PC 4 is the ``ecall``.
        return (jalr(ZERO, ZERO, 2), ECALL), (jalr(ZERO, ZERO, 4), ECALL)
    if kind == 2:  # CALL_STACK: a pop from the empty stack; the legal form pushes first.
        return (jalr(ZERO, RA, 0), ECALL), (jal(RA, 8), ECALL, jalr(ZERO, RA, 0))
    # LOOP: zero iterations; the legal form runs the body once.
    return (loopi(0, 1), NOP, ECALL), (loopi(1, 1), NOP, ECALL)


# Vector bit 29 is PIC source 30, OTBN done (interrupts.adoc:22, :164-166).
VEC_OTBN_DONE = 29

# DMEM layout of the compute program: [0] = a, [4] = b, [8] = result.
DMEM_A, DMEM_B, DMEM_RES = 0x0, 0x4, 0x8

# Native crypto EDN client of OTBN RND, bit 2 of crypto_edn_ack_o (trng.adoc:90-91).
EDN_OTBN_RND = 2

# Memory of the host read of the bus-access leg.
IBA_IMEM, IBA_DMEM = 0, 1

# Leaf choices (not from the specification).
_OUTER_CLK = 200_000  # outer limit of a clean-time wait
_T_MULT = 8  # bound of a later command wait, in t_cmd
_DONE_WIN_MULT = 2  # enable-clear watch window of the done-line leg, in t_cmd
_IGNORE_WIN_MULT = 4  # ignored-command window, in t_cmd (contract)
_RST_BOUND_CLK = 1_000  # gated reset release wait
_LINE_BOUND_CLK = 64  # vector bit 29 follow wait after a register write
_ALERT_OBS_CLK = 256  # alert watch window after the integrity-run reset (log only)
_ALERT_LOCKED_CLK = 256  # LOCKED window before the integrity-run reset (rise count)
_IBA_DMEM_WORDS = 16  # the bus-access DMEM word is drawn below this word index
_PASS_LABEL_CLK = 2  # clocks the pass label stays set


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
    imem_bit: int
    dmem_word: int
    dmem_bit: int
    sw_kind: int
    swk_off: int
    iba_mem: int
    iba_imem_idx: int
    iba_dmem_idx: int
    iba_dmem_val: int
    seq3: tuple[int, ...]
    gaps3: tuple[int, ...]

    def line(self, seed: int) -> str:
        return (
            f"PLAN seed={seed} seq={','.join(f'0x{c:02x}' for c in self.seq)} "
            f"gaps={','.join(map(str, self.gaps))} op={self.op} opa=0x{self.opa:08x} "
            f"opb=0x{self.opb:08x} a={self.a} b={self.b} "
            f"en_order={','.join(map(str, self.en_order))} k={self.k} "
            f"bad_cmd=0x{self.bad_cmd:02x} j={self.j} errclr=0x{self.errclr:08x} "
            f"imem_bit={self.imem_bit} dmem_word={self.dmem_word} dmem_bit={self.dmem_bit} "
            f"sw_kind={SW_KINDS[self.sw_kind]} swk_off={self.swk_off} "
            f"iba_mem={'imem' if self.iba_mem == IBA_IMEM else 'dmem'} "
            f"iba_imem_idx={self.iba_imem_idx} iba_dmem_idx={self.iba_dmem_idx} "
            f"iba_dmem_val=0x{self.iba_dmem_val:08x} "
            f"seq3={','.join(f'0x{c:02x}' for c in self.seq3)} "
            f"gaps3={','.join(map(str, self.gaps3))}"
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
    imem_bit = rng.randrange(0, INTG_WORD_BITS)
    # The compute program loads DMEM words 0 (lw x10, 0(x6)) and 1 (lw x11, 4(x6)).
    dmem_word = rng.randrange(0, 2)
    dmem_bit = rng.randrange(0, INTG_WORD_BITS)
    sw_kind = rng.randrange(len(SW_KINDS))
    swk_off = rng.randrange(1, 4)
    iba_mem = rng.randrange(2)
    iba_imem_idx = rng.randrange(len(OTBN_RND_PROG))
    # Above the words that the RND program stores.
    iba_dmem_idx = rng.randrange(OTBN_DMEM_RND_BASE // 4 + OTBN_RND_READS, _IBA_DMEM_WORDS)
    iba_dmem_val = rng.randrange(1, 1 << 32)
    # The command leg of shard 3: EXECUTE only.
    seq3 = (CMD_EXECUTE,) * rng.randrange(3, 6)
    gaps3 = tuple(rng.randrange(0, 201) for _ in seq3)
    return Plan(
        tuple(seq),
        gaps,
        op,
        opa,
        opb,
        a,
        b,
        (en_order[0], en_order[1]),
        k,
        bad_cmd,
        j,
        errclr,
        imem_bit,
        dmem_word,
        dmem_bit,
        sw_kind,
        swk_off,
        iba_mem,
        iba_imem_idx,
        iba_dmem_idx,
        iba_dmem_val,
        seq3,
        gaps3,
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


# The checks of the RND-clean and sw-kind legs (shard 2).
_ERR_LEG_CHECKS = ("CHK-OTBN-RND-CLEAN", "CHK-OTBN-SWERR-KIND")
# The checks of the EXECUTE-only legs (shard 3).
_EXEC_LEG_CHECKS = (
    "CHK-OTBN-CMD-END",
    "CHK-OTBN-CMD-BUSY",
    "CHK-OTBN-INSN",
    "CHK-OTBN-DONE-LINE",
    "CHK-OTBN-CMD-IGNORE",
    "CHK-OTBN-BUSYWR",
    "CHK-OTBN-INITDONE",
    "CHK-OTBN-SWERR-RECOV",
    "CHK-OTBN-ERRCLR",
    "CHK-OTBN-BUSYWR-ERR",
    "CHK-OTBN-CMDIGN-ERR",
)


@pyuvm.test()
class sep_otbn_cmd_status_rand_test(sep_base_test):
    """OTBN commands, status codes, INSN_CNT, the done line and the ignored writes."""

    required_evidence = (
        "CHK-OTBN-RND-CLEAN",
        "CHK-OTBN-SWERR-KIND",
        "CHK-OTBN-ILLEGAL-BUS",
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
        "CHK-OTBN-IMEM-INTG",
        "CHK-OTBN-DMEM-INTG",
    )

    # ------------------------------------------------------------- helpers
    def _open_window(self) -> None:
        """Open the graded window unless a check or a control has failed."""
        if self.chk.failures == 0:
            open_graded_window(TEST, self.logger)

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check; a FAIL closes the graded window before it is recorded."""
        if not cond:
            close_graded_window(self.logger)
        return self.chk.ok(name, cond, **fields)

    async def _pass_label(self, bits: int) -> None:
        """Write the ``otbn_cmd_pass`` bits of a check that passed, then 0.

        Only while no check or control of the run has failed, so the window is
        open. The sampler holds each outcome of the check as pending at its DUT
        event and samples it at the rise of its bit.
        """
        if self.chk.failures:
            return
        set_otbn_cmd_pass(bits, self.logger)
        await ClockCycles(cocotb.top.clk_i, _PASS_LABEL_CLK)
        set_otbn_cmd_pass(0, self.logger)
        await ClockCycles(cocotb.top.clk_i, 1)

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """Log one control; a missing control closes the graded window first."""
        if not cond:
            close_graded_window(self.logger)
        return self.chk.ctrl(name, cond, **fields)

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
            "INFO-OTBN-RESET %s released=%d idle=%d clk=%d status=%s",
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
        shard = sep_shard(
            self,
            {
                1: tuple(c for c in self.required_evidence if c not in _ERR_LEG_CHECKS),
                2: _ERR_LEG_CHECKS,
                3: _EXEC_LEG_CHECKS,
            },
        )
        # full_legs: the legs with a SEC_WIPE command at IDLE or a LOCKED state.
        full_legs = shard in (None, 1)
        exec_legs = shard in (None, 1, 3)
        err_legs = shard in (None, 2)
        await self.bring_up_no_cpu(park=("aes", "hmac", "kmac", "abr"))
        self.suppress_host_axi_transaction_info()
        self.swrst = getattr(self, "swrst", None) or SepSwReset(self)
        # SepEntropyCfg() selects the internal source in EXT_TRNG_SRC_SEL. Without the
        # busy-write leg, the RND sink is scored from the start.
        sinks = {"otbn_urnd": "observe"}
        if not exec_legs:
            sinks["otbn_rnd"] = "observe"
        await self._bring_up_chain(sinks)
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

        if exec_legs:
            await self._init_leg(seed)
        self._open_window()
        if exec_legs:
            if full_legs:
                cmd_end_pass = await self._command_leg(seed, plan.seq, plan.gaps)
            else:
                cmd_end_pass = await self._command_leg(seed, plan.seq3, plan.gaps3)
            self.idle_bound = max(_T_MULT * self.t_cmd, 1)
            await self._insn_leg(seed)
            await self._done_line_leg(seed)
            busy_ok = await self._busy_write_leg(seed)
        if err_legs:
            await self._rnd_clean_leg(seed)
        if full_legs:
            await self._intg_leg(seed, FLIP_IMEM)
            await self._intg_leg(seed, FLIP_DMEM)
        if exec_legs:
            recov_err = await self._sw_error_leg(seed, fatal=full_legs)
            await self._ignored_leg(seed)
        if err_legs:
            await self._sw_kind_leg(seed)
        if full_legs:
            await self._illegal_bus_leg(seed)
        close_graded_window(self.logger)

        if exec_legs:
            self._ctrl(
                "OTBN-CMD-IGNORE",
                cmd_end_pass and busy_ok,
                seed=seed,
                cmd_end_done=int(cmd_end_pass),
                busy_status_0x01=int(busy_ok),
            )
            if full_legs:
                self._ctrl(
                    "OTBN-LOCKED-HOLD",
                    cmd_end_pass,
                    seed=seed,
                    cmd_at_idle_done=int(cmd_end_pass),
                )
            self._ctrl(
                "OTBN-SWERR-RECOV", cmd_end_pass, seed=seed, cmd_end_err_bits_0=int(cmd_end_pass)
            )
            self._ctrl(
                "OTBN-BUSYWR-ERR", recov_err != 0, seed=seed, recov_err_bits=f"0x{recov_err:x}"
            )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        await self.irq.stop()
        await self.status_t.stop()
        await self.rst_t.stop()
        self.chk.finish()

    async def _init_leg(self, seed: int) -> None:
        """Steps 3-4: the power-on wipe ends at IDLE (ToO:98), then reset, wipe then IDLE;
        the done bit of the wipe is logged only."""
        dut = cocotb.top
        pre_idle, pre_vals, _ = await self._wait_idle(self.idle_bound, gap=4)
        t_pre = _now_ps()
        pre_status = self.rd(dut.otbn_status_probe_o, mask=M_STATUS)
        init_arc_ok, init_arc = await self._reset_otbn("initial")
        self._grade("OTBN-INITDONE", init_arc_ok, seed=seed, reset_arc=init_arc)
        # The probe holds IDLE from the read before the pulse up to the clock before the
        # gated reset falls, so the 0x04 after the release is caused by the pulse.
        pre_falls = self.rst_t.falls(t_pre, bit=0)
        t_fall = pre_falls[0] if pre_falls else None
        pre_moves = None if t_fall is None else len(self.status_t.since(t_pre, until_ps=t_fall - 1))
        at_fall = None if t_fall is None else self.status_t.value_at(t_fall - 1)
        self._ctrl(
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

    # ---------------------------------------------------------- command leg
    async def _command_leg(self, seed: int, seq: tuple[int, ...], gaps: tuple[int, ...]) -> bool:
        """Steps 5-9. Returns True when a command set ``done`` from a cleared state."""
        p = self.plan
        counts: list[int] = []
        any_pass = False
        for idx, (cmd, gap) in enumerate(zip(seq, gaps, strict=True)):
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
            if self._grade(
                "OTBN-CMD-BUSY",
                first == ST_BUSY[cmd],
                seed=seed,
                idx=idx,
                cmd=f"0x{cmd:02x}",
                first_busy=first_s,
                expect=f"0x{ST_BUSY[cmd]:02x}",
            ):
                await self._pass_label(OTBN_CMD_PASS_CMD_BUSY)
            if not ok:
                self._grade(
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
            if cmd != CMD_EXECUTE:
                if cmd == CMD_SEC_WIPE_DMEM:
                    mem, addrs = "dmem", (OTBN_DMEM_BASE + DMEM_A, OTBN_DMEM_BASE + DMEM_RES)
                else:
                    mem, addrs = "imem", (OTBN_IMEM_BASE, OTBN_IMEM_BASE + 4)
                words = [f"0x{await self._rd(a):08x}" for a in addrs]
                self.chk.obs(
                    "OTBN-WIPE-MEM", seed=seed, idx=idx, cmd=f"0x{cmd:02x}", mem=mem, words=words
                )
            cond = (
                pre == ST_IDLE
                and done_before == 0
                and ST_LOCKED not in vals
                and done == 1
                and err == 0
                and fatal == 0
            )
            any_pass = any_pass or cond
            end_ok = self._grade(
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
            if end_ok:
                await self._pass_label(OTBN_CMD_PASS_CMD_END)
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
                self._grade(
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
        insn_ok = self._grade(
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
        if insn_ok:
            await self._pass_label(OTBN_CMD_PASS_INSN)

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
                self._grade(
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
                line_ok = self._grade(
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
                line_ok = self._grade(
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
            if line_ok:
                await self._pass_label(OTBN_CMD_PASS_DONE_LINE)
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
        test_ok = self._grade(
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
        if test_ok:
            await self._pass_label(OTBN_CMD_PASS_DONE_LINE)
        # Enable-set INTR_TEST cell: control of this leg. Its line cells stay held
        # and the next OTBN reset drops them.
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
        self._ctrl(
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
        self._open_window()

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
            if self._grade(
                "OTBN-CMD-IGNORE",
                all(s == ST_BUSY_EXECUTE for s in st_after_cmd),
                seed=seed,
                case="busy_wipe",
                cmd=f"0x{CMD_SEC_WIPE_DMEM:02x}",
                status=",".join(f"0x{s:02x}" for s in st_after_cmd),
                done="n/a",
                window_clk="n/a",
                writes=p.j,
            ):
                await self._pass_label(OTBN_CMD_PASS_IGNORE)

        # Steps 21-22: release the TRNG reset, bring the chain up, finish.
        await self.swrst.release("trng")
        await self._bring_up_chain({"otbn_rnd": "observe"})
        self._open_window()
        idle, ivals, _ = await self._wait_idle(_OUTER_CLK, gap=4)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        # Bit 6 (two equal EDN words) is a chance outcome: logged, not graded.
        self.chk.info(
            "OTBN-BUSYWR-RNDREP", seed=seed, rnd_rep_chk_fail=int(bool(err & M_ERR_RND_REP))
        )
        err_graded = err & ~M_ERR_RND_REP
        self._grade(
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
        self._ctrl("OTBN-BUSYWR", ctrl_idle == 1, seed=seed, ctrl_after_idle_write=ctrl_idle)
        if not busy:
            self._grade(
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
            busywr_ok = self._grade(
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
            if busywr_ok:
                await self._pass_label(OTBN_CMD_PASS_BUSYWR)
        await self._reset_otbn("busywr-end")
        return busy

    # ------------------------------------------------------- RND-clean leg
    async def _rnd_clean_leg(self, seed: int) -> None:
        """The RND program with the chain up; grade ERR_BITS at its end.

        Every value the check grades except ``ERR_BITS`` is read before the
        ``ERR_BITS`` read; when one of them fails, the window closes before that
        read, so the read that the sampler takes is the graded read.
        """
        dut = cocotb.top
        close_graded_window(self.logger)
        arc_ok, arc = await self._reset_otbn("rnd-clean")
        await self._clear_done()
        ctrl = await self._rd(A_CTRL, M_CTRL_SWERR)
        prog = OTBN_RND_PROG
        await self.otbn.load_program(prog)
        done0 = await self._rd(A_INTR_STATE, M_DONE)
        ack = SepBitWatch(dut.crypto_edn_ack_o, {"rnd": EDN_OTBN_RND}, name="otbn_rnd_ack").start()
        self._open_window()
        m_cmd = ack.mark()
        await self._wr(A_CMD, CMD_EXECUTE)
        idle, vals, clks = await self._wait_idle(_OUTER_CLK, gap=4)
        acks = ack.rises_since(m_cmd, "rnd")
        await ack.stop()
        done = await self._rd(A_INTR_STATE, M_DONE)
        pre_ok = (
            arc_ok
            and ctrl == 0
            and done0 == 0
            and idle
            and ST_LOCKED not in vals
            and done == 1
            and acks > 0
        )
        if not pre_ok:
            close_graded_window(self.logger)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        err_graded = err & ~M_ERR_RND_REP
        self._grade(
            "OTBN-RND-CLEAN",
            pre_ok and err_graded == 0,
            seed=seed,
            reset_arc=arc,
            ctrl=ctrl,
            pre_done=done0,
            status=_runs(vals),
            idle=int(idle),
            done=done,
            rnd_ack_rises=acks,
            err_bits=f"0x{err:x}",
            err_bits_without_rnd_rep=f"0x{err_graded:x}",
            expect="0x0",
            clk=clks,
            bound=_OUTER_CLK,
        )
        # Bit 6 (two equal EDN words) is a chance outcome: logged, not graded.
        self.chk.info(
            "OTBN-RND-CLEAN-RNDREP", seed=seed, rnd_rep_chk_fail=int(bool(err & M_ERR_RND_REP))
        )

    # ------------------------------------------------------ integrity legs
    async def _arm_flip_on_busy(self, bound: int) -> int | None:
        """Drive ``otbn_intg_flip_en_i`` to 1 at the first clock the status probe shows
        BUSY_EXECUTE; return that clock count, or None after ``bound`` clocks."""
        dut = cocotb.top
        for i in range(bound):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.otbn_status_probe_o, mask=M_STATUS) == ST_BUSY_EXECUTE:
                dut.otbn_intg_flip_en_i.value = 1
                return i
        return None

    def _alert_high(self, watch: SepBitWatch, mark: BitMark) -> dict[int, int]:
        return {i: watch.high_clocks_since(mark, f"a{i}") for i in OTBN_ALERT_IDX}

    async def _intg_leg(self, seed: int, mem: int) -> None:
        """One EXECUTE of the compute program with one bit of each core read word of
        ``mem`` inverted ahead of the integrity check; grade the fatal reaction."""
        p = self.plan
        dut = cocotb.top
        if mem == FLIP_IMEM:
            name, tag = "OTBN-IMEM-INTG", "imem"
            flip_bit = p.imem_bit
            m_err, m_fatal = M_ERR_IMEM_INTG, M_FATAL_IMEM_INTG
        else:
            name, tag = "OTBN-DMEM-INTG", "dmem"
            flip_bit = INTG_WORD_BITS * p.dmem_word + p.dmem_bit
            m_err, m_fatal = M_ERR_DMEM_INTG, M_FATAL_DMEM_INTG
        dut.otbn_intg_flip_en_i.value = 0
        dut.otbn_intg_flip_mem_i.value = mem
        dut.otbn_intg_flip_bit_i.value = flip_bit
        alert = SepBitWatch(
            dut.crypto_alert_pulse_probe_o,
            {f"a{i}": i for i in OTBN_ALERT_IDX},
            name=f"otbn_alert_{tag}",
        ).start()
        m_pre = alert.mark()
        await self._clear_done()
        await self._stage_compute(otbn_compute_prog(p.op))
        done0 = await self._rd(A_INTR_STATE, M_DONE)
        pre_high = self._alert_high(alert, m_pre)
        arm = cocotb.start_soon(self._arm_flip_on_busy(self.idle_bound))
        m_cmd = alert.mark()
        await self._wr(A_CMD, CMD_EXECUTE)
        _, vals, clks = await self._poll_status(
            lambda s: s in (ST_IDLE, ST_LOCKED), self.idle_bound
        )
        arm_clk = await arm
        st = vals[-1]
        st_probe = self.rd(dut.otbn_status_probe_o, mask=M_STATUS)
        done = await self._rd(A_INTR_STATE, M_DONE)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        fatal = await self._rd(A_FATAL, M_FATAL)
        flips = self.rd(dut.otbn_intg_flip_count_o)
        post_high = self._alert_high(alert, m_cmd)
        dut.otbn_intg_flip_en_i.value = 0
        m_locked = alert.mark()
        await ClockCycles(dut.clk_i, _ALERT_LOCKED_CLK)
        locked_rises = {i: alert.rises_since(m_locked, f"a{i}") for i in OTBN_ALERT_IDX}
        exit_ok, exit_arc = await self._reset_otbn(f"intg-{tag}-exit")
        st_exit = await self._rd(A_STATUS, M_STATUS)
        fatal_exit = await self._rd(A_FATAL, M_FATAL)
        m_after = alert.mark()
        await ClockCycles(dut.clk_i, _ALERT_OBS_CLK)
        after_high = self._alert_high(alert, m_after)
        await alert.stop()
        self._ctrl(
            name,
            arm_clk is not None and flips > 0,
            seed=seed,
            mem=tag,
            flip_bit=flip_bit,
            armed_clk_after_cmd="none" if arm_clk is None else arm_clk,
            flip_count=flips,
        )
        cond = (
            arm_clk is not None
            and done0 == 0
            and st == ST_LOCKED
            and st_probe == ST_LOCKED
            and done == 1
            and bool(err & m_err)
            and bool(fatal & m_fatal)
            and sum(pre_high.values()) == 0
            and sum(post_high.values()) > 0
            and sum(locked_rises.values()) > 0
            and exit_ok
            and st_exit == ST_IDLE
            and fatal_exit == 0
        )
        intg_ok = self._grade(
            name,
            cond,
            seed=seed,
            mem=tag,
            flip_bit=flip_bit,
            status=_runs(vals),
            final=f"0x{st:02x}",
            probe=f"0x{st_probe:02x}",
            expect=f"0x{ST_LOCKED:02x}",
            done=done,
            pre_done=done0,
            err_bit=int(bool(err & m_err)),
            err_mask=f"0x{m_err:x}",
            fatal_bit=int(bool(fatal & m_fatal)),
            fatal_mask=f"0x{m_fatal:x}",
            alert_high_before_cmd=sum(pre_high.values()),
            alert_high_after_cmd=sum(post_high.values()),
            alert_rises_locked=sum(locked_rises.values()),
            locked_window_clk=_ALERT_LOCKED_CLK,
            reset_arc=exit_arc,
            status_after_reset=f"0x{st_exit:02x}",
            fatal_after_reset=f"0x{fatal_exit:x}",
            clk=clks,
            bound=self.idle_bound,
        )
        if intg_ok:
            await self._pass_label(
                OTBN_CMD_PASS_IMEM_INTG if mem == FLIP_IMEM else OTBN_CMD_PASS_DMEM_INTG
            )
        self.chk.obs(
            "OTBN-INTG-ALERT-IDX",
            seed=seed,
            mem=tag,
            **{f"a{i}_high_clk": post_high[i] for i in OTBN_ALERT_IDX},
            **{f"a{i}_rises_locked": locked_rises[i] for i in OTBN_ALERT_IDX},
        )
        self.chk.obs(
            "OTBN-INTG-CAUSE",
            seed=seed,
            mem=tag,
            err_bits=f"0x{err:x}",
            fatal_cause=f"0x{fatal:x}",
            alert_high_after_reset=sum(after_high.values()),
            window_clk=_ALERT_OBS_CLK,
        )

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

    async def _sw_error_leg(self, seed: int, *, fatal: bool) -> int:
        """The ``unimp`` program, fatal (with ``fatal``) then recoverable.

        Returns ERR_BITS of the recoverable run.
        """
        if fatal:
            await self._sw_error_fatal(seed)
        return await self._sw_error_recov(seed)

    async def _sw_error_fatal(self, seed: int) -> None:
        """The ``unimp`` program with ``software_errs_fatal`` = 1, the LOCKED hold, the exit."""
        win = _IGNORE_WIN_MULT * self.t_cmd
        ctrl, done0, vals, clks = await self._run_unimp(1)
        st = vals[-1]
        done = await self._rd(A_INTR_STATE, M_DONE)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        fatal = await self._rd(A_FATAL, M_FATAL)
        fatal_ok = self._grade(
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
        if fatal_ok:
            await self._pass_label(OTBN_CMD_PASS_SWERR_FATAL)
        # LOCKED hold: a recognised command at LOCKED, then the OTBN reset exit.
        await self._wr(A_CMD, CMD_EXECUTE)
        _, hvals, hclks = await self._poll_status(lambda s: s != ST_LOCKED, win)
        fatal_hold = await self._rd(A_FATAL, M_FATAL)
        exit_ok, exit_arc = await self._reset_otbn("swerr-fatal-exit")
        st_exit = await self._rd(A_STATUS, M_STATUS)
        fatal_exit = await self._rd(A_FATAL, M_FATAL)
        hold_ok = self._grade(
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
        if hold_ok:
            await self._pass_label(OTBN_CMD_PASS_LOCKED_HOLD)

    async def _sw_error_recov(self, seed: int) -> int:
        """The ``unimp`` program with ``software_errs_fatal`` = 0; returns its ERR_BITS."""
        rctrl, rdone0, rvals, rclks = await self._run_unimp(0)
        rst = rvals[-1]
        rdone = await self._rd(A_INTR_STATE, M_DONE)
        rerr = await self._rd(A_ERR_BITS, M_ERR_BITS)
        rfatal = await self._rd(A_FATAL, M_FATAL)
        recov_ok = self._grade(
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
        if recov_ok:
            await self._pass_label(OTBN_CMD_PASS_SWERR_RECOV)
        # No sentence states the other ERR_BITS bits, or FATAL_ALERT_CAUSE, here.
        self.chk.obs(
            "OTBN-SWERR-CAUSE", seed=seed, err_bits=f"0x{rerr:x}", fatal_cause=f"0x{rfatal:x}"
        )
        self._ctrl(
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
        ign_err_ok = self._grade(
            "OTBN-CMDIGN-ERR",
            err == err_pre,
            seed=seed,
            cmd=f"0x{p.bad_cmd:02x}",
            err_bits_before=f"0x{err_pre:x}",
            err_bits=f"0x{err:x}",
        )
        self._ctrl("OTBN-CMDIGN-ERR", err_pre != 0, seed=seed, err_bits_before=f"0x{err_pre:x}")
        if ign_err_ok:
            await self._pass_label(OTBN_CMD_PASS_IGN_ERR)
        # ERR_BITS clear: a write of the drawn value at IDLE.
        st_clr = await self._rd(A_STATUS, M_STATUS)
        await self._wr(A_ERR_BITS, p.errclr)
        err_clr = await self._rd(A_ERR_BITS, M_ERR_BITS)
        clr_ok = self._grade(
            "OTBN-ERRCLR",
            st_clr == ST_IDLE and err_clr == 0,
            seed=seed,
            status=f"0x{st_clr:02x}",
            written=f"0x{p.errclr:08x}",
            err_bits_before=f"0x{err:x}",
            err_bits_after=f"0x{err_clr:x}",
        )
        self._ctrl("OTBN-ERRCLR", err != 0, seed=seed, err_bits_before=f"0x{err:x}")
        if clr_ok:
            await self._pass_label(OTBN_CMD_PASS_ERRCLR)
        cond = ok and st0 == 0 and all(v == ST_IDLE for v in vals) and done == 0
        ign_ok = self._grade(
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
        if ign_ok:
            await self._pass_label(OTBN_CMD_PASS_IGNORE)

    # ------------------------------------------------------- sw-kind leg
    async def _run_sw_prog(self, prog: tuple[int, ...], tag: str, *, graded: bool) -> dict:
        """Reset OTBN, run ``prog`` with ``software_errs_fatal`` = 0, read the end state.

        With ``graded`` the window opens before the ``CMD`` write. Every value of the
        check except ``ERR_BITS`` is read before the ``ERR_BITS`` read; when one of
        them fails, the window closes before that read.
        """
        arc_ok, arc = await self._reset_otbn(tag)
        await self._clear_done()
        ctrl = await self._rd(A_CTRL, M_CTRL_SWERR)
        await self.otbn.load_program(prog)
        done0 = await self._rd(A_INTR_STATE, M_DONE)
        if graded:
            self._open_window()
        await self._wr(A_CMD, CMD_EXECUTE)
        met, vals, clks = await self._poll_status(
            lambda s: s in (ST_IDLE, ST_LOCKED), self.idle_bound
        )
        done = await self._rd(A_INTR_STATE, M_DONE)
        pre_ok = (
            arc_ok
            and ctrl == 0
            and done0 == 0
            and met
            and vals[-1] == ST_IDLE
            and ST_LOCKED not in vals
            and done == 1
        )
        if graded and not pre_ok:
            close_graded_window(self.logger)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        fatal = await self._rd(A_FATAL, M_FATAL)
        return {
            "pre_ok": pre_ok,
            "reset_arc": arc,
            "ctrl": ctrl,
            "pre_done": done0,
            "status": _runs(vals),
            "final": f"0x{vals[-1]:02x}",
            "done": done,
            "err": err,
            "fatal": fatal,
            "clk": clks,
        }

    async def _sw_kind_leg(self, seed: int) -> None:
        """One drawn recoverable software error; the pass label follows the passing check."""
        p = self.plan
        kind = p.sw_kind
        mask = M_ERR_SW_KIND[kind]
        prog, legal = sw_kind_progs(kind, p.swk_off)
        close_graded_window(self.logger)
        t = await self._run_sw_prog(legal, "swkind-legal", graded=False)
        self._ctrl(
            "OTBN-SWERR-KIND",
            t["pre_ok"] and t["err"] == 0,
            seed=seed,
            kind=SW_KINDS[kind],
            program="legal",
            status=t["status"],
            done=t["done"],
            err_bits=f"0x{t['err']:x}",
        )
        r = await self._run_sw_prog(prog, "swkind", graded=True)
        passed = self._grade(
            "OTBN-SWERR-KIND",
            r["pre_ok"] and bool(r["err"] & mask),
            seed=seed,
            kind=SW_KINDS[kind],
            off=p.swk_off,
            reset_arc=r["reset_arc"],
            ctrl=r["ctrl"],
            pre_done=r["pre_done"],
            status=r["status"],
            final=r["final"],
            expect=f"0x{ST_IDLE:02x}",
            done=r["done"],
            err_bits=f"0x{r['err']:x}",
            err_mask=f"0x{mask:x}",
            kind_bit=int(bool(r["err"] & mask)),
            clk=r["clk"],
            bound=self.idle_bound,
        )
        if passed:
            # The sampler samples the kind of this label only at its rise.
            set_otbn_sw_err_pass(kind + 1, self.logger)
            await ClockCycles(cocotb.top.clk_i, _PASS_LABEL_CLK)
            set_otbn_sw_err_pass(0, self.logger)
        # No sentence states the other ERR_BITS bits, or FATAL_ALERT_CAUSE, here.
        self.chk.obs(
            "OTBN-SWERR-KIND-CAUSE",
            seed=seed,
            kind=SW_KINDS[kind],
            err_bits=f"0x{r['err']:x}",
            fatal_cause=f"0x{r['fatal']:x}",
        )

    # ------------------------------------------------------ bus-access leg
    async def _illegal_bus_leg(self, seed: int) -> None:
        """A host IMEM or DMEM read while OTBN executes; the last leg, it locks OTBN.

        Every value of the lock phase except ``ERR_BITS`` and ``FATAL_ALERT_CAUSE``
        is read before those two reads; when one of them fails, the window closes
        before them.
        """
        p = self.plan
        dut = cocotb.top
        close_graded_window(self.logger)
        arc_ok, arc = await self._reset_otbn("iba")
        await self._clear_done()
        prog = OTBN_RND_PROG
        await self.otbn.load_program(prog)
        if p.iba_mem == IBA_IMEM:
            mem, idx = "imem", p.iba_imem_idx
            addr = OTBN_IMEM_BASE + 4 * idx
            staged = prog[idx]
        else:
            mem, idx = "dmem", p.iba_dmem_idx
            addr = OTBN_DMEM_BASE + 4 * idx
            staged = p.iba_dmem_val
            await self.otbn.write_dmem(4 * idx, staged)
        st_twin = await self._rd(A_STATUS, M_STATUS)
        twin = await self._rd(addr)
        self._ctrl(
            "OTBN-ILLEGAL-BUS",
            arc_ok and st_twin == ST_IDLE and staged != 0 and twin == staged,
            seed=seed,
            mem=mem,
            idx=idx,
            status=f"0x{st_twin:02x}",
            staged=f"0x{staged:08x}",
            rdata_at_idle=f"0x{twin:08x}",
        )

        # The TRNG reset clears the chain under the running scoreboard: grade it first.
        await self._retire_chain()
        await self.swrst.park("trng")
        trng_held = False
        for _ in range(_RST_BOUND_CLK):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.trng_reset_active_probe_o, mask=1):
                trng_held = True
                break
        self._open_window()
        await self._wr(A_CMD, CMD_EXECUTE)
        busy, bvals, bclks = await self._poll_status(
            lambda s: s == ST_BUSY_EXECUTE, self.idle_bound
        )
        t0 = _now_ps()
        rd = SepAxiAccessSeq(
            "otbn_iba_rd",
            op=SepAxiOp.READ,
            addr=addr,
            length=4,
            size=2,
            allow_ungraded_read_resp=True,
        )
        await self.start_seq(rd)
        st_at_rd = self.status_t.value_at(t0)
        locked, lvals, lclks = await self._poll_status(lambda s: s == ST_LOCKED, self.idle_bound)
        moves = [c.value for c in self.status_t.since(t0)]
        pre_ok = (
            trng_held
            and busy
            and st_at_rd == ST_BUSY_EXECUTE
            and ST_IDLE not in moves
            and None not in moves
            and staged != 0
            and rd.rdata == 0
            and locked
        )
        if not pre_ok:
            close_graded_window(self.logger)
        err = await self._rd(A_ERR_BITS, M_ERR_BITS)
        fatal = await self._rd(A_FATAL, M_FATAL)
        iba_ok = self._grade(
            "OTBN-ILLEGAL-BUS",
            pre_ok and bool(err & M_ERR_ILLEGAL_BUS) and bool(fatal & M_FATAL_ILLEGAL_BUS),
            seed=seed,
            phase="lock",
            mem=mem,
            idx=idx,
            trng_held=int(trng_held),
            busy_polled=_runs(bvals),
            status_at_ar="X" if st_at_rd is None else f"0x{st_at_rd:02x}",
            probe_after_rd=",".join("X" if v is None else f"0x{v:02x}" for v in moves) or "-",
            staged=f"0x{staged:08x}",
            rdata=f"0x{rd.rdata:08x}",
            expect_rdata="0x00000000",
            status=_runs(lvals),
            expect=f"0x{ST_LOCKED:02x}",
            err_bit=int(bool(err & M_ERR_ILLEGAL_BUS)),
            err_mask=f"0x{M_ERR_ILLEGAL_BUS:x}",
            fatal_bit=int(bool(fatal & M_FATAL_ILLEGAL_BUS)),
            fatal_mask=f"0x{M_FATAL_ILLEGAL_BUS:x}",
            clk=bclks + lclks,
            bound=self.idle_bound,
        )
        if iba_ok:
            await self._pass_label(OTBN_CMD_PASS_ILLEGAL_BUS)
        # No sentence states the response code of the read, or the other bits.
        self.chk.obs(
            "OTBN-ILLEGAL-BUS-CAUSE",
            seed=seed,
            mem=mem,
            resp_code=rd.resp_code,
            err_bits=f"0x{err:x}",
            fatal_cause=f"0x{fatal:x}",
        )
        close_graded_window(self.logger)

        # Exit: release the TRNG reset, bring the chain up, reset OTBN.
        await self.swrst.release("trng")
        await self._bring_up_chain({"otbn_urnd": "observe"})
        exit_ok, exit_arc = await self._reset_otbn("iba-exit")
        st_exit = await self._rd(A_STATUS, M_STATUS)
        fatal_exit = await self._rd(A_FATAL, M_FATAL)
        self._grade(
            "OTBN-ILLEGAL-BUS",
            exit_ok and st_exit == ST_IDLE and fatal_exit == 0,
            seed=seed,
            phase="exit",
            reset_arc=exit_arc,
            status_after_reset=f"0x{st_exit:02x}",
            fatal_after_reset=f"0x{fatal_exit:x}",
        )

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""EDN boot-mode precedence, the EDN and CSRNG software command handshakes and
status, the invalid command sequence alert, the command header, the CTRL field and
command alerts, the reseed limit and the GENBITS gate.

Contract (``vendor/lowRISC/opentitan/overlay/regs/edn/regs/gen/adoc/edn.adoc``: CTRL,
BOOT_INS_CMD, SW_CMD_REQ, SW_CMD_STS, HW_CMD_STS;
``vendor/lowRISC/opentitan/overlay/regs/csrng/regs/gen/adoc/csrng.adoc``: CMD_REQ,
SW_CMD_STS, RECOV_ALERT_STS; ``hw/sys/sep/doc/interrupts.adoc``: source N on vector
bit N - 1):
  * With ``CTRL.BOOT_REQ_MODE`` true EDN reports ``HW_CMD_STS.BOOT_MODE`` = 1 and
    ``AUTO_MODE`` = 0, also with ``AUTO_REQ_MODE`` true (boot mode takes precedence).
  * ``INTR_STATE.edn_cmd_req_done``: "Asserted when a software CSRNG request has
    completed." (``vendor/lowRISC/opentitan/upstream/hw/ip/edn/data/edn.hjson``
    :30-31). Each software command the leaf grades at its ``CMD_ACK``, also one
    acked with an error status and the instantiate of the auto trial, sets it.
  * With ``AUTO_REQ_MODE`` true and ``BOOT_REQ_MODE`` false, after the software
    instantiate, ``HW_CMD_STS.AUTO_MODE`` reads 1 and the first hardware
    command is ``GENERATE_CMD`` ("the first ``generate`` command is sent out
    automatically", edn.adoc:107). With ``MAX_NUM_REQS_BETWEEN_RESEEDS`` = 0
    the first hardware command is logged only (``OBS-EDN-AUTO-ZERO``): edn.adoc:107
    says the first command is a generate, and edn.hjson:480-484 describes a
    down-counter that requests a reseed when it reaches zero.
  * Reseed after N generates (edn.adoc:107, "a ``reseed`` command is sent after
    every MAX_NUM_REQS_BETWEEN_RESEEDS number of ``generate`` commands";
    edn.adoc:258-262, the down-counter "triggering an automatic ``reseed``
    request when it reaches zero"): with ``MAX_NUM_REQS_BETWEEN_RESEEDS`` = N
    the commands that EDN hands to CSRNG after the software instantiate are N
    generates, one reseed, then a generate.
  * EDN instantiate and the seed (``doc/programmer/src/sep-programming.adoc``
    :466-468): "CSRNG cannot acknowledge that command until it has accepted a
    complete ESRC seed", in the sequence of :457-462 (``AUTO_REQ_MODE`` true,
    ``CMD_STS`` reports success).
  * With both modes false EDN is in software port mode: ``CMD_REG_RDY`` and
    ``CMD_RDY`` are 1 before a command, ``CMD_ACK`` rises once CSRNG acknowledges
    it, and ``INTR_STATE.edn_cmd_req_done`` sets.
  * The CSRNG software instance follows the same handshake (``CMD_RDY``,
    ``CMD_ACK``, ``INTR_STATE.cs_cmd_req_done``).
  * An instantiate (0x901, the RDL reset value of ``BOOT_INS_CMD``) sent to an
    instantiated state sets ``RECOV_ALERT_STS`` bit 14
    (``CMD_STAGE_INVALID_CMD_SEQ_ALERT``); a write of 0 clears it. The text
    also says the command "is ignored and CSRNG continues to operate"; it gives
    no register value that shows this, so the leaf does not grade it.
  * Command header (``vendor/lowRISC/opentitan/upstream/hw/ip/csrng/doc/
    theory_of_operation.md``:156-188, :211-279): "3:0 acmd", "7:4 clen",
    "11:8 flag0", "23:12 glen"; "Instantiate 0x1", "Reseed 0x2", "Generate
    0x3", "Uninstantiate 0x5", "Reserved 0x0,0x6-0xf". "When sending an
    unsupported or illegal command, `CMD_STAGE_INVALID_ACMD_ALERT` will be
    triggered. Furthermore, CSRNG will respond with the appropriate error status
    response on the relevant interface." (theory_of_operation.md:50-51). "Several control fields
    use MuBi4 encodings, for which true is `0x6` and false is `0x9`."
    (``doc/programmer/src/sep-programming.adoc``:390-391). Every command word of
    the leaf is built from these fields.
  * EDN boot words (edn.adoc:128-131, :142-145): ``BOOT_INS_CMD`` resets to
    0x901 and ``BOOT_GEN_CMD`` to 0xFFF003; "the hardware only supports a value
    of 0 for the `clen` field".
  * EDN software status: "write an Instantiate command with no additional data
    to `EDN.SW_CMD_REQ`. Poll `CMD_ACK` ... and require `CMD_STS` to report
    success." (sep-programming.adoc:459-462). EDN ``CMD_STS`` uses the CSRNG
    codes (edn.adoc:172-176): "0 SUCCESS", "1 INVALID_ACMD ... the issued
    application command doesn't represent a valid operation", "4
    RESEED_CNT_EXCEEDED ... This happens only for Generate commands."
    (``vendor/lowRISC/opentitan/upstream/hw/ip/csrng/data/csrng.hjson``:406-440).
  * ``CTRL`` field alerts: "This bit is set when the <field> field in the !!CTRL
    register is set to a value other than kMultiBitBool4True or
    kMultiBitBool4False. Writing a zero resets this status bit." (csrng.adoc
    ``RECOV_ALERT_STS`` bits 0-3, :343-356; edn.adoc bits 0-3, :280-291).
  * Command alerts (csrng.adoc ``RECOV_ALERT_STS``): bit 4 "is set when the
    FLAG0 field in the Application Command is set to a value other than
    kMultiBitBool4True or kMultiBitBool4False" (:343-345); bit 13 "is set when
    an unsupported/illegal CSRNG command is received by the main state
    machine" (:335-338); bit 15 "is set when the maximum number of generate
    requests between reseeds is exceeded" (:325-328).
  * Reseed limit (csrng.adoc ``RESEED_INTERVAL``:138-144): the register sets
    "the number of generate requests that can be made to CSRNG before a reseed
    request needs to be made" (:138-139), and the counter "counts the number of
    generate commands between reseed or instantiate commands. If the counter
    reaches the value of this register, the violating command will be
    acknowledged with a status error." (:141-144). K Generates can be made, so
    the violating command is Generate K + 1.
  * ``GENBITS`` (csrng.adoc:223-225): "for !!GENBITS to be able to deliver
    random numbers, also !!CTRL.SW_APP_ENABLE needs to be set to
    `kMultiBitBool4True`. ... Otherwise, the register reads as 0."

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. Baseline ``SW_RESET_N`` = 0x20 (TRNG released; the Key
Manager and every engine held) and ``EXT_TRNG_SRC_SEL`` = 0x0. The clean start of
every group is a TRNG reset, the open entropy bring-up without the EDN step, a
CSRNG ``CTRL`` write with ``ENABLE`` and ``SW_APP_ENABLE`` true, and a
``RECOV_ALERT_STS`` read with bit 14 at 0. The entropy scoreboard runs non-strict
for the bring-up only: this leaf grades register state, not data.

Randomization (``SepSeededRng`` from the run seed, drawn before the first stimulus):
the order of the boot group, the EDN software port leg and the CSRNG software
instance leg, and the idle gap (0 to 16 clocks) before each poll read; after them,
the invalid value of each ``CTRL`` field, the invalid ``flag0``, the reserved
``acmd`` (0x0, 0x6, 0x7, 0x8, 0xe or 0xf: the reserved values whose bits [2:0] are
also a reserved value), the ``RESEED_INTERVAL`` value K (3 or 4) and the
``SW_APP_ENABLE`` value that is not True for the ``GENBITS`` read, the 384-bit
seed of the known-answer Generate, then the reseed count N of the second auto
sequence trial (2 to 4) and the hold H of the instantiate-seed leg (256 to 2048
clocks). The reserved
values 0x9 to 0xd carry a defined command code in bits [2:0]; the leaf sends 0x9 on
every seed in its last leg (no draw) and logs the result only. The checked values do
not depend on the seed; the known-answer control compares with the golden of the
drawn seed.

The three groups run in the drawn order. Then the leaf runs, in this order, the
``CTRL`` alert leg (a TRNG reset, no bring-up), the command header leg, the
reseed leg, the auto leg (the first-command trial, the auto sequence trial with
N = 1 on every seed, the auto sequence trial with the drawn N, the logged N = 0
trial), the instantiate-seed leg (a TRNG reset, ESRC configured with its
generators off) and, last, the reserved acmd 0x9 leg (each from a clean start).
The 0x9 leg runs after every other check, so its result does not change the
stimulus of another check. After it come the enable-order leg, then, from one
clean start, the bus compare replay leg and the counter-wrap leg. The counter-wrap
leg draws its seed words from its own ``SepSeededRng`` stream (the run seed XOR a
leg salt), so the plan draws above keep their seed mapping.

Only reserved values whose bits [2:0] are also reserved are graded. The text
reserves 0x0 and 0x6 to 0xf of the 4-bit acmd field, but the OpenTitan CSRNG
decodes bits [2:0] only, and its designers state that bit 3 is claimed for future
use and that a reserved value gives an undefined result (lowRISC/opentitan issue
16203). No text states the result of 0x9 to 0xd, so the 0x9 leg is an observation.

Checkers:
  CHK-EDN-BOOT   for each graded boot (AUTO_REQ_MODE true, then false) the first
                 ``HW_CMD_STS`` read with ``BOOT_MODE`` = 1 has ``AUTO_MODE`` = 0,
                 within 16 x the reference boot time t0. Each graded boot runs
                 twice from a clean start, the second time only after the first
                 passed. Every boot uses ``BOOT_INS_CMD`` = 0x601 (flag0 True,
                 clen 0: a zero seed, theory_of_operation.md:226).
  CHK-EDN-SW-HS  ``CMD_REG_RDY`` and ``CMD_RDY`` 1 before the command; ``CMD_ACK``
                 1 after it; ``edn_cmd_req_done`` and vector bit 27 read 0 before
                 the command, and 1 (a rise of bit 27) after it. ``CMD_RDY`` in the
                 read that shows ``CMD_ACK`` is logged only
                 (``OBS-EDN-RDY-AFTER-ACK``): the text states only that firmware
                 polls ``CMD_RDY`` before a command.
  CHK-EDN-INVSEQ the second instantiate through EDN sets CSRNG bit 14, bit 14 still
                 reads 1 before the clear, and a write of 0 clears it. Control: bit
                 14 reads 0 after the first command.
  CHK-CSRNG-SW   the same handshake for the CSRNG software instance (vector bit
                 23; ``CMD_RDY`` at the acknowledge logged as
                 ``OBS-CSRNG-RDY-AFTER-ACK``), and bit 14 on the second command; that command also
                 completes, so ``cs_cmd_req_done`` and vector bit 23 read 0
                 before it and 1 (a rise of bit 23) after it
                 (theory_of_operation.md:286, :421). Control: bit 14 reads 0
                 after the first command.
  CHK-EDN-BOOT-CMD  before any write, ``BOOT_INS_CMD`` reads 0x901 and
                 ``BOOT_GEN_CMD`` 0xFFF003; decoded with the header layout, acmd
                 0x1 and 0x3, clen 0 in both, glen 0xFFF.
  CTRL-EDN-STS   a reserved acmd through ``SW_CMD_REQ`` reads ``CMD_STS`` = 1
                 (INVALID_ACMD, csrng.hjson:413-416) at its ack, so the non-zero
                 ack of ``CHK-EDN-ACK-ERR`` is the stated code. ``CMD_STS`` at the
                 ack of the first EDN instantiate is logged only
                 (``OBS-EDN-STS``): the success code is stated only for the
                 sequence with ``AUTO_REQ_MODE`` = true
                 (``doc/programmer/src/sep-programming.adoc:457-462``), and this
                 leg enables EDN with ``AUTO_REQ_MODE`` = false and the endpoints
                 in reset.
  CHK-EDN-ACK-ERR  after that reserved acmd acks with a non-zero ``CMD_STS``,
                 EDN ``RECOV_ALERT_STS.CSRNG_ACK_ERR`` reads 1: "This bit is set
                 when the CSRNG returns an acknowledgement where the status
                 signal is non-zero. Writing a zero resets this status bit."
                 (``vendor/lowRISC/opentitan/upstream/hw/ip/edn/data/edn.hjson``
                 :542-543, the same text in ``edn.rdl`` ``RECOV_ALERT_STS``); code
                 1 "Request completed with an invalid application command error.
                 This error indicates that the issued application command
                 doesn't represent a valid operation." (``csrng.hjson``:415-416).
                 The command goes after an EDN disable and enable: an ack with a
                 non-zero status (the second instantiate) holds the software
                 port (``OBS-EDN-PORT-HELD``). Control: after a write of 0 and
                 before the command, the bit reads 0.
  CHK-EDN-ACMD-INV  after the ack of that reserved acmd, CSRNG bit 13 reads 1
                 ("When sending an unsupported or illegal command,
                 `CMD_STAGE_INVALID_ACMD_ALERT` will be triggered",
                 theory_of_operation.md:50-51), EDN ``edn_cmd_req_done``
                 reads 1 and, with its enable read as 1, vector bit 27 rises.
                 Control: before the command, bit 13 reads 0 after a write of 0,
                 and ``edn_cmd_req_done`` and vector bit 27 read 0 after a write
                 of 1.
  CHK-CSRNG-CTRL-MUBI, CHK-EDN-CTRL-MUBI  per ``CTRL`` field, a write of a value
                 other than 6 or 9 sets the field alert bit; after the legal
                 value is back, a write of 0 clears it. Control: the bit reads 0
                 with the legal value, before the write.
  CHK-CSRNG-ACMD-INV  a drawn reserved acmd sets bit 13 and acks with ``CMD_STS``
                 = 1; a write of 0 clears bit 13. Control: bit 13 reads 0 after an
                 instantiate.
  OBS-CSRNG-ACMD-HI  after an instantiate, the reserved acmd 0x9 (word 0x909):
                 its ``CMD_STS`` and ``RECOV_ALERT_STS`` are logged, not graded
                 (see the 3-bit decode note above).
  CHK-CSRNG-FLAG0  an instantiate with an invalid value in flag0 [11:8] sets
                 bit 4; after an uninstantiate and an instantiate with flag0 0x9
                 (the field back to a legal value), a write of 0 clears it.
                 Control: bit 4 reads 0 after an instantiate with flag0 0x9 and
                 after one with flag0 0x6. The write-0 readback at the ack of the
                 invalid instantiate is logged only (``OBS-CSRNG-FLAG0-HELD``):
                 the text does not say how long the field stays set.
  CHK-CSRNG-RESEED-LIMIT  with ``RESEED_INTERVAL`` = K, the first Generate
                 that acks with ``CMD_STS`` = 4 is Generate K + 1, and bit 15
                 reads 1 at that ack; a write of 0 clears bit 15. K is the
                 number of Generates that "can be made" before a reseed
                 (csrng.adoc:138-139), so a refusal at Generate K or earlier,
                 or no refusal by K + 1, fails.
                 Control: the first Generate (index 1 < K) acks with
                 ``CMD_STS`` other than 4 and bit 15 at 0.
  CHK-CSRNG-RESEED-HDR  after a Reseed word (acmd 0x2, clen 0, flag0 0x9, the
                 header that EDN ``RESEED_CMD`` also takes, edn.adoc:225-230)
                 the counter restarts ("counts the number of generate commands
                 between reseed or instantiate commands", csrng.adoc:141-142), so
                 the next Generate (glen 1) succeeds: it acks with ``CMD_STS`` = 0
                 ("If the command is successful, the ``csrng_rsp_sts`` signal will
                 indicate the value 0 (``SUCCESS``)", theory_of_operation.md:287;
                 "Request completed successfully.", csrng.hjson:406-410), bit 15
                 reads 0, and ``GENBITS`` gives four words (GEN1_WORDS; GENBITS
                 "must be read four times for each request made",
                 csrng.hjson:475-476): the leg counts ``GENBITS`` reads while
                 ``GENBITS_VLD`` = 1, up to one read past four. Control: the
                 Generate before the Reseed was refused, ``GENBITS`` was
                 drained until ``GENBITS_VLD`` read 0 before the Reseed, and the
                 Reseed acked with ``CMD_STS`` = 0 (the same success code).
  CHK-CSRNG-GENBITS-GATE  with a Generate pending, ``CTRL.SW_APP_ENABLE`` set
                 to a value other than 6: four ``GENBITS`` reads return 0, and
                 that Generate (the second since the Reseed, inside the
                 interval) acks with ``CMD_STS`` = 0, and ``RECOV_ALERT_STS``
                 bit 1 reads 0 before the write and, after it, 1 for a value
                 other than 6 or 9 and 0 for 9 (csrng.adoc:351-353). Control: ``GENBITS`` is first drained (read while
                 ``GENBITS_VLD`` = 1, at most four reads per earlier Generate)
                 until ``GENBITS_VLD`` reads 0, and it reads 1 only after the
                 leg's own Generate.
  CHK-CSRNG-KAT  with ``SW_APP_ENABLE`` True, a known-answer Generate
                 (instantiate with flag0 True and twelve drawn seed words, "Only
                 provided additional data will be used as seed",
                 theory_of_operation.md:227) returns the four ``GENBITS`` words of
                 the SP 800-90A CTR_DRBG golden (AES-CTR-DRBG,
                 ``hw/ip/drbg/doc/architecture.adoc``:14; AES-256, "This block does
                 not use a derivation function", README.md:47; word order
                 programmers_guide.md:37-114), golden ``env/sep_ctr_drbg_golden.py``,
                 and the Generate acks with ``CMD_STS`` = 0.
  CHK-EDN-AUTO-SEQ  with ``AUTO_REQ_MODE`` true and
                 ``MAX_NUM_REQS_BETWEEN_RESEEDS`` = N (N = 1, then the drawn N),
                 the command headers on the EDN to CSRNG port after the
                 instantiate are exactly N generates, one reseed and a generate
                 (edn.adoc:107, :258-262). Control (``CTRL-EDN-AUTO-TAP``): the
                 first command on the port is the software instantiate.
  CHK-EDN-INST-SEED  ESRC generators off, CSRNG on, EDN on with
                 ``AUTO_REQ_MODE`` true; an instantiate to ``SW_CMD_REQ`` reaches
                 the EDN to CSRNG port, then for the drawn hold H no seed
                 handshake (``drbg_seed_valid`` and ``drbg_es_ack``), no
                 ``CMD_ACK`` and no rise of vector bit 27. After the generators
                 are on, the first seed handshake comes before the rise of bit
                 27; then ``CMD_ACK`` = 1, ``CMD_STS`` = 0,
                 ``edn_cmd_req_done`` = 1, the next command on the port is a
                 generate and ``HW_CMD_STS`` reads ``AUTO_MODE`` = 1,
                 ``BOOT_MODE`` = 0 (sep-programming.adoc:457-462, :466-468;
                 edn.adoc:107). In the hold both seed handshake signals are
                 read with no unknown bit allowed; an X or Z on either fails.
The unstated effects are logged only (``OBS-EDN-*``, ``OBS-CSRNG-*``,
``OBS-DRBG-*``). The
``CMD_STS`` of the CSRNG instantiate stays an observation (``OBS-CSRNG-STS``): no
sentence states that a first instantiate on the software instance succeeds.
``OBS-CSRNG-GENBITS-GATE`` also logs the two CSRNG gate inputs at the DRBG instance
(``csrng_sw_app_read_en_o``, ``csrng_lc_hw_debug_en_o``) and the run's lifecycle
source: hw/ip/drbg/doc/architecture.adoc:47 says these signals gate the software
read, and no text states their value per lifecycle state.

Open-value legs (logged, not graded; each control fails the leaf):
  CTRL-CSRNG-BUS-CMP  two known-answer Generates with the same seed (an
                 Uninstantiate and an Instantiate between them) give two 4-word
                 blocks equal to the golden block, both acknowledge with
                 ``CMD_STS`` = 0, and ``RECOV_ALERT_STS`` bit 12 reads 0 after a
                 write of 0 before the second Generate. ``OBS-CSRNG-BUS-CMP`` logs
                 bit 12 after the second Generate: it is set when the value equals
                 "the prior valid value on the bus" (csrng.hjson:655-656), and no
                 text states whether that value survives an Uninstantiate.
  CTRL-CSRNG-VCTR-WRAP  an Instantiate (flag0 True, clen 12) whose seed sets
                 V[31:0] to 0xfffffffe, then a Generate with glen 2: block 1
                 (V[31:0] = 0xffffffff) equals the golden block and the Generate
                 acknowledges with ``CMD_STS`` = 0. ``OBS-CSRNG-VCTR-WRAP`` logs
                 block 2 with the ctr_len 32 and ctr_len 128 candidates (SP 800-90A
                 10.2.1.2) and ``match=<32|128|none>``: no document states ctr_len.

Graded after the counter-wrap control:
  CHK-CSRNG-VCTR-DISTINCT  block 2 differs from block 1. SP 800-90A
                 10.2.1.5.1 step 4.1 increments V modulo 2^ctr_len for every
                 allowed ctr_len, and AES-256 under one key is a permutation, so
                 two consecutive blocks of one Generate never repeat
                 (csrng/README.md:34 claims the SP 800-90A CTR_DRBG).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, NextTimeStep, ReadOnly, RisingEdge
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_ctr_drbg_golden import BLOCK_LEN, SepCtrDrbgGolden
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_drbg_seq_drop,
    set_drbg_seq_pass,
    set_open_value_leg_pass,
)
from env.sep_reg_meta import CSRNG, EDN, SEP_CPU_CTRL, sym
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, wait_until
from models.entropy_noise_model import EntropyNoiseModel
from sep_base_test import sep_base_test
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_drbg_mode_bringup_seq import drbg_bring_up
from seq_lib.sep_esrc_bringup_seq import SepEsrcConfigSeq, SepEsrcEnableGeneratorsSeq
from seq_lib.sep_irq_aggregator_seq import IRQ_TABLE

TEST = "sep_drbg_cmd_sequence_rand_test"

MUBI_TRUE = 0x6
MUBI_FALSE = 0x9

EXT_TRNG_SRC_SEL = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")

CSRNG_CTRL = sym("CSRNG_CTRL_REG_ADDR")
CSRNG_CMD_REQ = sym("CSRNG_CMD_REQ_REG_ADDR")
CSRNG_SW_CMD_STS = sym("CSRNG_SW_CMD_STS_REG_ADDR")
CSRNG_RECOV_ALERT_STS = sym("CSRNG_RECOV_ALERT_STS_REG_ADDR")
CSRNG_INTR_STATE = sym("CSRNG_INTR_STATE_REG_ADDR")
CSRNG_INTR_ENABLE = sym("CSRNG_INTR_ENABLE_REG_ADDR")
CSRNG_HW_EXC_STS = sym("CSRNG_HW_EXC_STS_REG_ADDR")
CSRNG_ERR_CODE = sym("CSRNG_ERR_CODE_REG_ADDR")
CSRNG_MAIN_SM_STATE = sym("CSRNG_MAIN_SM_STATE_REG_ADDR")
EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
EDN_SW_CMD_REQ = sym("EDN_SW_CMD_REQ_REG_ADDR")
EDN_SW_CMD_STS = sym("EDN_SW_CMD_STS_REG_ADDR")
EDN_HW_CMD_STS = sym("EDN_HW_CMD_STS_REG_ADDR")
EDN_INTR_STATE = sym("EDN_INTR_STATE_REG_ADDR")
EDN_INTR_ENABLE = sym("EDN_INTR_ENABLE_REG_ADDR")
EDN_RECOV_ALERT_STS = sym("EDN_RECOV_ALERT_STS_REG_ADDR")
EDN_ERR_CODE = sym("EDN_ERR_CODE_REG_ADDR")
EDN_MAIN_SM_STATE = sym("EDN_MAIN_SM_STATE_REG_ADDR")

# Field bits from the generated register headers (csrng.rdl, edn.rdl).
CS_STS_RDY = CSRNG.fields("SW_CMD_STS")["CMD_RDY"]["bm"]
CS_STS_ACK = CSRNG.fields("SW_CMD_STS")["CMD_ACK"]["bm"]
CS_STS_STS = CSRNG.fields("SW_CMD_STS")["CMD_STS"]
CS_INVSEQ = CSRNG.fields("RECOV_ALERT_STS")["CMD_STAGE_INVALID_CMD_SEQ_ALERT"]["bm"]
CS_DONE = CSRNG.fields("INTR_STATE")["CS_CMD_REQ_DONE"]["bm"]
CS_HW_INST_EXC = CSRNG.fields("INTR_STATE")["CS_HW_INST_EXC"]["bm"]
ED_STS_REG_RDY = EDN.fields("SW_CMD_STS")["CMD_REG_RDY"]["bm"]
ED_STS_RDY = EDN.fields("SW_CMD_STS")["CMD_RDY"]["bm"]
ED_STS_ACK = EDN.fields("SW_CMD_STS")["CMD_ACK"]["bm"]
ED_STS_STS = EDN.fields("SW_CMD_STS")["CMD_STS"]
ED_BOOT_MODE = EDN.fields("HW_CMD_STS")["BOOT_MODE"]["bm"]
ED_AUTO_MODE = EDN.fields("HW_CMD_STS")["AUTO_MODE"]["bm"]
ED_DONE = EDN.fields("INTR_STATE")["EDN_CMD_REQ_DONE"]["bm"]
ED_ACK_ERR = EDN.fields("RECOV_ALERT_STS")["CSRNG_ACK_ERR"]["bm"]

# The instantiate word: the RDL reset value of EDN BOOT_INS_CMD (edn.adoc BOOT_INS_CMD).
CMD_INSTANTIATE = EDN.reset("BOOT_INS_CMD")

CSRNG_CTRL_ON = CSRNG.value("CTRL", ENABLE=MUBI_TRUE, SW_APP_ENABLE=MUBI_TRUE)

CSRNG_GENBITS_VLD = sym("CSRNG_GENBITS_VLD_REG_ADDR")
CSRNG_GENBITS = sym("CSRNG_GENBITS_REG_ADDR")
CSRNG_RESEED_INTERVAL = sym("CSRNG_RESEED_INTERVAL_REG_ADDR")
EDN_BOOT_INS_CMD = sym("EDN_BOOT_INS_CMD_REG_ADDR")
EDN_BOOT_GEN_CMD = sym("EDN_BOOT_GEN_CMD_REG_ADDR")
EDN_RESEED_CMD = sym("EDN_RESEED_CMD_REG_ADDR")
EDN_GENERATE_CMD = sym("EDN_GENERATE_CMD_REG_ADDR")
EDN_MAX_REQS = sym("EDN_MAX_NUM_REQS_BETWEEN_RESEEDS_REG_ADDR")
ED_HW_TYPE = EDN.fields("HW_CMD_STS")["CMD_TYPE"]
ED_HW_ACK = EDN.fields("HW_CMD_STS")["CMD_ACK"]["bm"]

GB_VLD = CSRNG.fields("GENBITS_VLD")["GENBITS_VLD"]["bm"]
_CS_RECOV = CSRNG.fields("RECOV_ALERT_STS")
CS_FLAG0_INV = _CS_RECOV["ACMD_FLAG0_FIELD_ALERT"]["bm"]
CS_ACMD_INV = _CS_RECOV["CMD_STAGE_INVALID_ACMD_ALERT"]["bm"]
CS_RESEED_CNT = _CS_RECOV["CMD_STAGE_RESEED_CNT_ALERT"]["bm"]
CS_BUS_CMP = _CS_RECOV["CS_BUS_CMP_ALERT"]["bm"]
_ED_RECOV = EDN.fields("RECOV_ALERT_STS")
# CTRL field -> its RECOV_ALERT_STS field alert bit (csrng.adoc and edn.adoc RECOV_ALERT_STS).
CS_CTRL_ALERT = {
    "ENABLE": _CS_RECOV["ENABLE_FIELD_ALERT"]["bm"],
    "SW_APP_ENABLE": _CS_RECOV["SW_APP_ENABLE_FIELD_ALERT"]["bm"],
    "READ_INT_STATE": _CS_RECOV["READ_INT_STATE_FIELD_ALERT"]["bm"],
    "FIPS_FORCE_ENABLE": _CS_RECOV["FIPS_FORCE_ENABLE_FIELD_ALERT"]["bm"],
}
ED_CTRL_ALERT = {
    "EDN_ENABLE": _ED_RECOV["EDN_ENABLE_FIELD_ALERT"]["bm"],
    "BOOT_REQ_MODE": _ED_RECOV["BOOT_REQ_MODE_FIELD_ALERT"]["bm"],
    "AUTO_REQ_MODE": _ED_RECOV["AUTO_REQ_MODE_FIELD_ALERT"]["bm"],
    "CMD_FIFO_RST": _ED_RECOV["CMD_FIFO_RST_FIELD_ALERT"]["bm"],
}
MUBI_INVALID = tuple(v for v in range(16) if v not in (MUBI_TRUE, MUBI_FALSE))

# Command header (theory_of_operation.md:156-188) and application commands (:211-279).
ACMD_INSTANTIATE = 0x1
ACMD_RESEED = 0x2
ACMD_GENERATE = 0x3
ACMD_UNINSTANTIATE = 0x5
ACMD_RESERVED = (0x0, *range(0x6, 0x10))
# The drawn reserved values: those whose bits [2:0] are also a reserved value.
ACMD_RESERVED_DRAW = tuple(v for v in ACMD_RESERVED if v & 0x7 in ACMD_RESERVED)
# The reserved value of the last leg: bits [2:0] carry the Instantiate code. The
# CSRNG decodes acmd bits [2:0] only, and no text states the result of a reserved
# value whose bits [2:0] are a defined command, so this value is logged, not graded.
ACMD_RESERVED_HI = 0x9
# CMD_STS codes (csrng.hjson SW_CMD_STS.CMD_STS; edn.adoc SW_CMD_STS links to them).
STS_SUCCESS = 0
STS_INVALID_ACMD = 1
STS_RESEED_CNT_EXCEEDED = 4
# EDN RECOV_ALERT_STS.CSRNG_ACK_ERR after an ack with a non-zero status (edn.hjson:542).
EXP_ACK_ERR = 1
# EDN boot command reset values (edn.rdl BOOT_INS_CMD, BOOT_GEN_CMD).
BOOT_INS_RESET = EDN.reset("BOOT_INS_CMD")
BOOT_GEN_RESET = EDN.reset("BOOT_GEN_CMD")
# GENBITS reads for one Generate with glen 1: glen 1 "returns 1 * 128 bits of entropy"
# (theory_of_operation.md:185) and GENBITS "must be read four times for each request
# made" (csrng.hjson:475-476).
GEN1_WORDS = 4
# Known-answer instantiate: flag0 True with clen 12 uses "Only provided additional
# data ... as seed" (theory_of_operation.md:227), a 384-bit seed of twelve words.
KAT_SEED_BITS = 384
KAT_CLEN = KAT_SEED_BITS // 32
# Reseed counts of the auto sequence trials: N = 1 on every seed, then a drawn N in
# AUTO_N_LO..AUTO_N_HI (the two reseed cells of the auto command coverpoint).
AUTO_N_FORCED = 1
AUTO_N_LO = 2
AUTO_N_HI = 4
# Hold of the instantiate-seed leg, in clocks, with the ESRC generators off. The
# lower end is the hold the coverage cell requires (cov/sv/sep_fcov.sv CzIaHold).
INST_HOLD_MIN = 256
INST_HOLD_MAX = 2048
# Counter-wrap leg: Instantiate sets V[31:0] to VCTR_PRE_WRAP, so block 1 of a glen 2
# Generate runs at V[31:0] = 0xffffffff and block 2 is the first block after the wrap.
# The leg draws its seed from its own stream, so the plan draws keep their mapping.
VCTR_PRE_WRAP = 0xFFFF_FFFE
VCTR_WRAP_SALT = 0x5743_5452
VCTR_GLEN = 2
VCTR_CTR_LENS = (32, BLOCK_LEN)
# Clocks the open-value leg pass label stays set.
OV_LABEL_CLOCKS = 2


def cmd_word(acmd: int, *, clen: int = 0, flag0: int = MUBI_FALSE, glen: int = 0) -> int:
    """Command header: acmd [3:0], clen [7:4], flag0 [11:8], glen [23:12]."""
    return ((glen & 0xFFF) << 12) | ((flag0 & 0xF) << 8) | ((clen & 0xF) << 4) | (acmd & 0xF)


def decode_hdr(word: int) -> dict[str, int]:
    """The header fields of ``word`` at the stated positions."""
    return {
        "acmd": word & 0xF,
        "clen": (word >> 4) & 0xF,
        "flag0": (word >> 8) & 0xF,
        "glen": (word >> 12) & 0xFFF,
    }


CMD_GENERATE_1 = cmd_word(ACMD_GENERATE, glen=1)
# Boot-time instantiate of the boot legs: flag0 True, clen 0, "Seed of zero is used
# (no entropy source seed used)" (theory_of_operation.md:226). CHK-EDN-BOOT grades
# BOOT_MODE and AUTO_MODE only, so the boot instantiate is not the 0x901 word whose
# hardware-port acknowledge the FCOV instantiate-outcome cell counts.
BOOT_INS_ZERO_SEED = cmd_word(ACMD_INSTANTIATE, flag0=MUBI_TRUE)
CSRNG_CTRL_OFF = CSRNG.value(
    "CTRL",
    ENABLE=MUBI_FALSE,
    SW_APP_ENABLE=MUBI_FALSE,
    READ_INT_STATE=MUBI_FALSE,
    FIPS_FORCE_ENABLE=MUBI_FALSE,
)


def _edn_ctrl(boot: bool, auto: bool, enable: bool, fifo_rst: bool = False) -> int:
    return EDN.value(
        "CTRL",
        EDN_ENABLE=MUBI_TRUE if enable else MUBI_FALSE,
        BOOT_REQ_MODE=MUBI_TRUE if boot else MUBI_FALSE,
        AUTO_REQ_MODE=MUBI_TRUE if auto else MUBI_FALSE,
        CMD_FIFO_RST=MUBI_TRUE if fifo_rst else MUBI_FALSE,
    )


_IRQ = {s.name: s.agg_idx for s in IRQ_TABLE}
VEC_EDN_DONE = _IRQ["edn_cmd_req_done"]
VEC_CS_DONE = _IRQ["csrng_cmd_req_done"]
VEC_CS_HW_INST_EXC = _IRQ["csrng_hw_inst_exc"]

GROUPS = ("boot", "edn_sw", "csrng_sw")
N_GAPS = 256

# Outer caps of a first measurement (design rule: 20 x the clean value of the logs).
TRNG_RESET_CAP = 4_000
FIRST_CAP = 20_000
# A hardware generate or reseed waits on entropy after the instantiate ack.
AUTO_CAP = 60_000
# The instantiate-seed leg: the seed bound of wait_seed_ready (60 000 clocks from the
# generator enable) plus the first-command bound.
INST_ACK_CAP = 60_000 + FIRST_CAP
VEC_CAP = 2_000
BOUND_FACTOR = 16
# Outer cap of a field-alert poll: the alert bit decodes a register field, so it
# needs no command to run.
ALERT_CAP = 2_000


@dataclass(frozen=True)
class Plan:
    seed: int
    groups: tuple[str, ...]
    gaps: tuple[int, ...]
    cs_bad: tuple[int, ...]
    ed_bad: tuple[int, ...]
    bad_flag0: int
    bad_acmd: int
    reseed_k: int
    gen_off: int
    kat_seed: int
    auto_n: int
    inst_hold: int

    def describe(self) -> str:
        return (
            f"groups={','.join(self.groups)} gaps[0:8]={list(self.gaps[:8])}"
            f" cs_bad={[hex(v) for v in self.cs_bad]} ed_bad={[hex(v) for v in self.ed_bad]}"
            f" bad_flag0=0x{self.bad_flag0:x} bad_acmd=0x{self.bad_acmd:x}"
            f" reseed_k={self.reseed_k} gen_off=0x{self.gen_off:x}"
            f" kat_seed=0x{self.kat_seed:096x}"
            f" auto_n={self.auto_n} inst_hold={self.inst_hold}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    groups = list(GROUPS)
    rng.shuffle(groups)
    gaps = tuple(rng.randrange(0, 17) for _ in range(N_GAPS))
    cs_bad = tuple(rng.choice(MUBI_INVALID) for _ in CS_CTRL_ALERT)
    ed_bad = tuple(rng.choice(MUBI_INVALID) for _ in ED_CTRL_ALERT)
    bad_flag0 = rng.choice(MUBI_INVALID)
    bad_acmd = rng.choice(ACMD_RESERVED_DRAW)
    reseed_k = rng.randrange(3, 5)
    gen_off = rng.choice(tuple(v for v in range(16) if v != MUBI_TRUE))
    kat_seed = rng.getrandbits(KAT_SEED_BITS)
    auto_n = rng.randrange(AUTO_N_LO, AUTO_N_HI + 1)
    inst_hold = rng.randrange(INST_HOLD_MIN, INST_HOLD_MAX + 1)
    return Plan(
        seed,
        tuple(groups),
        gaps,
        cs_bad,
        ed_bad,
        bad_flag0,
        bad_acmd,
        reseed_k,
        gen_off,
        kat_seed,
        auto_n,
        inst_hold,
    )


class _CtrLenDrbg(SepCtrDrbgGolden):
    """CTR_DRBG golden whose V increment wraps the rightmost ``ctr_len`` bits.

    SP 800-90A 10.2.1.2: rightmost(V, ctr_len) + 1 mod 2^ctr_len, the leftmost
    BLOCK_LEN - ctr_len bits kept. No document states the ctr_len of the CSRNG,
    so a block after a wrap is a candidate for a log line, never an expected value.
    """

    def __init__(self, ctr_len: int) -> None:
        super().__init__()
        self.ctr_len = ctr_len

    def _v_increment(self) -> None:
        mask = (1 << self.ctr_len) - 1
        self.v = (self.v & ~mask) | ((self.v + 1) & mask)


class _Reg(SepAxiRegDriver):
    _DRIVER_TAG = "DRBG"


def _field(value: int, meta: dict[str, int]) -> int:
    return (value & meta["bm"]) >> meta["bp"]


class _NoiseDrive:
    """Raw-noise driver of ``start_esrc_noise_driver`` with a cooperative stop.

    ``stop`` clears the run flag and waits for the loop to leave at its next clock
    edge, so no trigger is cancelled while it is pending.
    """

    def __init__(self) -> None:
        self._gen = EntropyNoiseModel()
        self._gen.configure("unbiased", seed_base=0x1234_5678)
        self._run = True
        self._task = cocotb.start_soon(self._drive())

    async def _drive(self) -> None:
        dut = cocotb.top
        while self._run:
            await RisingEdge(dut.clk_i)
            if not self._run:
                break
            await NextTimeStep()
            dut.esrc_noise_ext_i.value = self._gen.step_all()

    async def stop(self) -> None:
        self._run = False
        await self._task


class _SeedIngress:
    """Per-clock count of ESRC entropy words offered to the DRBG seed packer.

    Each clock with ``esrc_compress_vld_o`` = 1 counts as accepted when
    ``drbg_seed_word_ready_o`` = 1 and as dropped otherwise. ``depth`` is the
    number of accepted words before the first offered word with ready = 0.
    ``stop`` lets the loop leave at its next clock edge.
    """

    def __init__(self, test) -> None:
        self.t = test
        self.accepted = 0
        self.dropped = 0
        self.depth: int | None = None
        self._run = True
        self._task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        dut = cocotb.top
        rd = self.t.rd
        while self._run:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not rd(dut.esrc_compress_vld_o, allow_unknown=True):
                continue
            if rd(dut.drbg_seed_word_ready_o, allow_unknown=True):
                self.accepted += 1
            else:
                self.dropped += 1
                if self.depth is None:
                    self.depth = self.accepted

    async def stop(self) -> None:
        self._run = False
        await self._task


class _InstSeedWatch:
    """Per-clock record of the instantiate-seed leg on one clock count.

    It records the first clock with the instantiate word valid on the EDN to CSRNG
    port (``edn_csrng_cmd_*``), the first seed handshake (``drbg_seed_valid_o`` and
    ``drbg_es_ack_o`` both 1), the first rise of the ``edn_cmd_req_done`` vector bit,
    and the first command header handed over after the instantiate (additional-data
    words skipped by clen). While ``in_hold`` is set, both seed handshake signals are
    read on every clock with no unknown bit allowed: the hold grades the absence of a
    handshake, so an X or Z must not read as 0. An unknown bit records ``hold_x``.
    A seed handshake, an unknown seed handshake bit or a rise of the vector bit in the
    hold closes the coverage window before the next clock edge.
    """

    def __init__(self, test) -> None:
        self.t = test
        self.clk = 0
        self.ins: int | None = None
        self.ins_hs = False
        self.hs: int | None = None
        self.ack: int | None = None
        self.next_word: int | None = None
        self.next_clk: int | None = None
        self.vec_first: int | None = None
        self.in_hold = True
        self.hold_break: int | None = None
        self.hold_x: int | None = None
        self._run = True
        self._vec_lvl: int | None = None
        self._rem = 0

    def stop(self) -> None:
        self._run = False

    async def run(self) -> None:
        dut = cocotb.top
        rd = self.t.rd
        while self._run:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            vec = rd(dut.sep_internal_interrupts_probe_o, mask=1 << VEC_EDN_DONE) >> VEC_EDN_DONE
            if self.vec_first is None:
                self.vec_first = vec
            if self._vec_lvl == 0 and vec == 1 and self.ack is None:
                self.ack = self.clk
            self._vec_lvl = vec
            valid = rd(dut.edn_csrng_cmd_valid_o, allow_unknown=True)
            ready = rd(dut.edn_csrng_cmd_ready_o, allow_unknown=True)
            if valid:
                word = rd(dut.edn_csrng_cmd_bus_o)
                if self.ins is None and word == CMD_INSTANTIATE:
                    self.ins = self.clk
                if ready and self.ins is not None:
                    if not self.ins_hs:
                        self.ins_hs = True
                        self._rem = decode_hdr(word)["clen"]
                    elif self._rem:
                        self._rem -= 1
                    elif self.next_word is None:
                        self.next_word = word
                        self.next_clk = self.clk
            if self.in_hold:
                seed_valid_sig = dut.drbg_seed_valid_o
                try:
                    seed_hs = rd(seed_valid_sig) & rd(dut.drbg_es_ack_o)
                except AssertionError as exc:
                    seed_hs = 0
                    if self.hold_x is None:
                        self.hold_x = self.clk
                        self.t.logger.info(
                            "INFO-INST-SEED-HOLD read at clock %d: %s", self.clk, exc
                        )
            else:
                seed_hs = 0
                if rd(dut.drbg_seed_valid_o, allow_unknown=True):
                    seed_hs = rd(dut.drbg_es_ack_o, allow_unknown=True)
            if self.hs is None and seed_hs:
                self.hs = self.clk
            if self.in_hold and self.hold_break is None:
                if self.hs is not None or self.ack is not None or self.hold_x is not None:
                    self.hold_break = self.clk
                    await FallingEdge(dut.clk_i)
                    close_graded_window(self.t.logger)


@pyuvm.test()
class sep_drbg_cmd_sequence_rand_test(sep_base_test):
    """EDN boot precedence, EDN and CSRNG software handshakes, invalid sequence alert."""

    required_evidence = (
        "CHK-EDN-BOOT",
        "CHK-EDN-SW-HS",
        "CHK-EDN-INVSEQ",
        "CHK-CSRNG-SW",
        "CHK-EDN-BOOT-CMD",
        "CHK-EDN-ACK-ERR",
        "CHK-EDN-ACMD-INV",
        "CHK-CSRNG-CTRL-MUBI",
        "CHK-EDN-CTRL-MUBI",
        "CHK-CSRNG-ACMD-INV",
        "CHK-CSRNG-FLAG0",
        "CHK-CSRNG-RESEED-LIMIT",
        "CHK-CSRNG-RESEED-HDR",
        "CHK-CSRNG-GENBITS-GATE",
        "CHK-EDN-AUTO",
        "CHK-CSRNG-KAT",
        "CHK-EDN-AUTO-SEQ",
        "CHK-EDN-INST-SEED",
        "CHK-CSRNG-VCTR-DISTINCT",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac", "abr"))
        self.reg = _Reg(self)
        await self.reg._wr(EXT_TRNG_SRC_SEL, 0)
        self.logger.info("INFO-BASELINE sw_reset_n=0x%02x ext_trng_src_sel=0x0", self.swrst.value)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("INFO-PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self._seq_mark = 0
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.vec = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {"edn_done": VEC_EDN_DONE, "cs_done": VEC_CS_DONE, "cs_exc": VEC_CS_HW_INST_EXC},
            name="sep_internal_interrupts_probe_o",
        ).start()
        self._gap_i = 0
        self.sb = None
        ingress = _SeedIngress(self)
        failed = True
        try:
            await self._boot_cmd_reset()
            for group in plan.groups:
                if group == "boot":
                    await self._boot_group()
                elif group == "edn_sw":
                    await self._edn_sw_leg()
                else:
                    await self._csrng_sw_leg()
            await self._ctrl_mubi_leg()
            await self._hdr_leg()
            await self._reseed_leg()
            await self._auto_leg()
            await self._inst_seed_leg()
            await self._acmd_hi_leg()
            await self._enable_order_leg()
            await self._bus_cmp_leg()
            await self._vctr_wrap_leg()
            failed = False
        finally:
            if failed:
                # A failure may resume from ReadOnly, where no value can be written.
                await NextTimeStep()
            close_graded_window(self.logger)
            if self.sb is not None:
                self.sb.stop()
        await ingress.stop()
        self.chk.obs(
            "DRBG-SEED-INGRESS",
            accepted=ingress.accepted,
            dropped=ingress.dropped,
            depth="na" if ingress.depth is None else ingress.depth,
        )
        await self.vec.stop()
        await self.clk.stop()
        self.chk.finish()

    # --- waits ----------------------------------------------------------------------
    def _now(self) -> int:
        return self.clk.clk

    def _next_gap(self) -> int:
        gap = self.plan.gaps[self._gap_i % N_GAPS]
        self._gap_i += 1
        return gap

    def _reader(self, addr: int):
        async def read() -> int:
            gap = self._next_gap()
            if gap:
                await ClockCycles(cocotb.top.clk_i, gap)
            return await self.reg._rd(addr)

        return read

    async def _wait(self, addr: int, mask: int, want: int, bound: int, what: str):
        """Poll ``addr`` with the drawn gaps until ``(value & mask) == want``.

        Returns ``(clocks, last value)``; raises ``TrialTimeout`` at the bound.
        """
        t0 = self._now()
        samples = await wait_until(self._reader(addr), self._now, mask, want, bound, what)
        return samples[-1][0] - t0, samples[-1][1]

    async def _wait_vec(self, mark, bit: str, bound: int) -> int:
        """Clocks from ``mark`` to the first rise of the vector bit after it. The caller
        reads the bit as 0 at the mark, so only a 0 -> 1 change counts."""
        rise = await self.vec.wait_rise(mark, bound, bit)
        return rise - mark.clk

    # --- clean start ----------------------------------------------------------------
    async def _wait_probe(self, sig, want_zero: bool, what: str) -> int:
        dut = cocotb.top
        for clk in range(TRNG_RESET_CAP):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if (self.rd(sig, allow_unknown=True) == 0) == want_zero:
                return clk
        raise AssertionError(f"{what}: no change within {TRNG_RESET_CAP} clocks")

    async def _trng_reset(self) -> None:
        dut = cocotb.top
        if self.sb is not None:
            self.sb.stop()
            self.sb = None
        await self.swrst.park("trng")
        rise = await self._wait_probe(dut.trng_reset_active_probe_o, False, "trng reset rise")
        await RisingEdge(dut.clk_i)
        await self.swrst.release("trng")
        fall = await self._wait_probe(dut.trng_reset_active_probe_o, True, "trng reset fall")
        await RisingEdge(dut.clk_i)
        self.logger.info(
            "INFO-TRNG-RESET: rise_clk=%d fall_clk=%d cap=%d", rise, fall, TRNG_RESET_CAP
        )

    async def _clean_start(self, group: str) -> int:
        """TRNG reset, bring-up without the EDN step, CSRNG enable. Returns bit 14."""
        close_graded_window(self.logger)
        await self._trng_reset()
        self.sb = await drbg_bring_up(self, edn_ctrl=None, strict=False)
        await self.reg._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
        recov = await self.reg._rd(CSRNG_RECOV_ALERT_STS)
        bit14 = int(bool(recov & CS_INVSEQ))
        self.chk.ctrl("CLEAN-START", bit14 == 0, group=group, csrng_invseq=bit14)
        await self._main_sm("idle")
        return bit14

    async def _main_sm(self, step: str) -> None:
        """OBS-DRBG-MAIN-SM: the CSRNG and EDN ``MAIN_SM_STATE`` readbacks at ``step``.
        No text states the encoding of either state machine."""
        for unit, addr in (("csrng", CSRNG_MAIN_SM_STATE), ("edn", EDN_MAIN_SM_STATE)):
            state = await self.reg._rd(addr)
            self.chk.obs("DRBG-MAIN-SM", unit=unit, step=step, state=f"0x{state:x}")

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check inside a coverage window: a FAIL is logged, then the window closes."""
        res = self.chk.ok(name, cond, **fields)
        if not cond:
            close_graded_window(self.logger)
        return res

    async def _release(self) -> None:
        """Pulse the FCOV pass label ``drbg_seq_pass`` when every check and control
        since the last call passed; otherwise pulse its drop value. The sampler
        holds each sample of this leaf's windows until the pass pulse, drops every
        held sample on the drop pulse, and also drops it when the next window
        opens, so a sample reaches a bin only after the check that grades its
        instance passed, and a later pass cannot release the sample of a failed
        instance. The caller runs it after the checks of a window and before the
        next window opens."""
        failures = self.chk.failures
        passed = failures == self._seq_mark
        self._seq_mark = failures
        clk = cocotb.top.clk_i
        if not passed:
            await FallingEdge(clk)
            set_drbg_seq_drop(True, self.logger)
            await RisingEdge(clk)
            await FallingEdge(clk)
            set_drbg_seq_drop(False, self.logger)
            return
        await FallingEdge(clk)
        set_drbg_seq_pass(True, self.logger)
        await RisingEdge(clk)
        await FallingEdge(clk)
        set_drbg_seq_pass(False, self.logger)

    # --- auto request mode ----------------------------------------------------------
    async def _auto_hw(self, what: str) -> int:
        """Poll HW_CMD_STS with no idle gap; return the first read with AUTO_MODE = 1
        whose CMD_TYPE is a hardware command (not the software instantiate, not 0).

        The command stays in flight while its data or its entropy is outstanding, so
        back-to-back reads see the first hardware command. A drawn gap could miss it.
        """
        t0 = self._now()
        while self._now() - t0 <= AUTO_CAP:
            value = await self.reg._rd(EDN_HW_CMD_STS)
            if value & ED_AUTO_MODE and _field(value, ED_HW_TYPE) not in (0, ACMD_INSTANTIATE):
                return value
        raise TrialTimeout(what, AUTO_CAP)

    async def _auto_setup(self, kind: str, max_reqs: int) -> None:
        """Clean start, then EDN off with AUTO_REQ_MODE true, the command FIFOs reset,
        GENERATE_CMD (generate, glen 1), RESEED_CMD (reseed) and MAX_NUM_REQS staged."""
        await self._clean_start(f"edn_auto_{kind}")
        await self.reg._wr(EDN_CTRL, _edn_ctrl(False, False, False, fifo_rst=True))
        await self.reg._wr(EDN_CTRL, _edn_ctrl(False, True, False))
        await self.reg._wr(EDN_GENERATE_CMD, CMD_GENERATE_1)
        await self.reg._wr(EDN_RESEED_CMD, cmd_word(ACMD_RESEED))
        await self.reg._wr(EDN_MAX_REQS, max_reqs)

    async def _edn_cmd_watch(self, want: int, bound: int) -> tuple[list[int], str]:
        """Record the command headers on the EDN to CSRNG port (``edn_csrng_cmd_*``).

        A header is the word at a clock with valid and ready 1; the clen
        additional-data words after it are skipped. Returns at the ReadOnly phase of
        the clock that shows the ``want``-th header, before the clock edge that takes
        that handshake. Returns ``(headers, reason)``; ``reason`` is set when
        ``bound`` clocks pass with no handshake.
        """
        dut = cocotb.top
        hdrs: list[int] = []
        rem = 0
        last = self._now()
        while len(hdrs) < want:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self._now() - last > bound:
                return hdrs, f"timeout:edn_cmd bound={bound} seen={len(hdrs)}"
            valid = self.rd(dut.edn_csrng_cmd_valid_o, allow_unknown=True)
            ready = self.rd(dut.edn_csrng_cmd_ready_o, allow_unknown=True)
            if not (valid and ready):
                continue
            word = self.rd(dut.edn_csrng_cmd_bus_o)
            last = self._now()
            if rem:
                rem -= 1
                continue
            hdrs.append(word)
            rem = decode_hdr(word)["clen"]
        return hdrs, ""

    async def _auto_seq_trial(self, n: int) -> None:
        """CHK-EDN-AUTO-SEQ with MAX_NUM_REQS_BETWEEN_RESEEDS = ``n``.

        The commands on the EDN to CSRNG port after the software instantiate are
        exactly ``n`` GENERATE_CMD words, the RESEED_CMD word and a GENERATE_CMD word
        (edn.adoc:107, :258-262). The watch returns before the clock edge that takes
        the last handshake, so the check grades first; the coverage window is open
        only for that one edge, and only after a PASS.
        """
        dut = cocotb.top
        r = self.reg
        max_reqs = n
        await self._auto_setup(f"seq{n}", max_reqs)
        await r._wr(EDN_CTRL, _edn_ctrl(False, True, True))
        rdy = ED_STS_REG_RDY | ED_STS_RDY
        reseed_word = cmd_word(ACMD_RESEED)
        want = [CMD_GENERATE_1] * n + [reseed_word, CMD_GENERATE_1]
        hdrs: list[int] = []
        reason = ""
        watch = None
        try:
            await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, f"auto_seq{n}_rdy")
            watch = cocotb.start_soon(self._edn_cmd_watch(1 + len(want), AUTO_CAP))
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            hdrs, reason = await watch
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
            if watch is not None:
                watch.cancel()
        first = hdrs[0] if hdrs else None
        self.chk.ctrl(
            "EDN-AUTO-TAP",
            first == CMD_INSTANTIATE,
            n=n,
            first_word="na" if first is None else f"0x{first:x}",
            expected=f"0x{CMD_INSTANTIATE:x}",
        )
        seq = hdrs[1:]
        fields = {
            "n": n,
            "max_num_reqs": max_reqs,
            "gens": next((i for i, w in enumerate(seq) if w != CMD_GENERATE_1), len(seq)),
            "acmds": [decode_hdr(w)["acmd"] for w in seq],
            "words": [f"0x{w:x}" for w in seq],
            "expected": [f"0x{w:x}" for w in want],
        }
        if reason:
            fields["reason"] = reason
        passed = self.chk.ok(
            "EDN-AUTO-SEQ", not reason and first == CMD_INSTANTIATE and seq == want, **fields
        )
        if passed:
            await FallingEdge(dut.clk_i)
            open_graded_window(TEST, self.logger)
            await RisingEdge(dut.clk_i)
            await FallingEdge(dut.clk_i)
            close_graded_window(self.logger)
        await self._release()
        await r._wr(EDN_CTRL, _edn_ctrl(False, False, False))

    async def _auto_trial(self, kind: str, max_reqs: int) -> tuple[int, int]:
        """One auto-mode session. Returns (AUTO_MODE before the instantiate, HW_CMD_STS)."""
        self._auto_done = None
        self._auto_done_pre = None
        await self._auto_setup(kind, max_reqs)
        # Only the graded trial (max_reqs 1) is a coverage sample; the value 0 is logged.
        graded = max_reqs != 0
        if graded:
            await self.reg._wr(EDN_INTR_STATE, ED_DONE)
            self._auto_done_pre = int(bool(await self.reg._rd(EDN_INTR_STATE) & ED_DONE))
            open_graded_window(TEST, self.logger)
        await self.reg._wr(EDN_CTRL, _edn_ctrl(False, True, True))
        pre = await self.reg._rd(EDN_HW_CMD_STS)
        rdy = ED_STS_REG_RDY | ED_STS_RDY
        await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, f"auto_{kind}_rdy")
        await self.reg._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
        await self._wait(EDN_SW_CMD_STS, ED_STS_ACK, ED_STS_ACK, FIRST_CAP, f"auto_{kind}_sw_ack")
        if graded:
            self._auto_done = int(bool(await self.reg._rd(EDN_INTR_STATE) & ED_DONE))
        hw = await self._auto_hw(f"auto_{kind}")
        if graded:
            close_graded_window(self.logger)
        await self._main_sm("edn_auto")
        await self.reg._wr(EDN_CTRL, _edn_ctrl(False, False, False))
        return int(bool(pre & ED_AUTO_MODE)), hw

    async def _auto_leg(self) -> None:
        """The first hardware command with MAX_NUM_REQS = 1 (graded), the command
        sequence with N = 1 and with the drawn N (graded), then MAX_NUM_REQS = 0
        (logged)."""
        gen_pre = None
        gen_hw = None
        rs_hw = None
        reason = ""
        zero_reason = ""
        try:
            gen_pre, gen_hw = await self._auto_trial("generate", 1)
        except TrialTimeout as exc:
            close_graded_window(self.logger)
            reason = f"timeout:{exc.what} bound={exc.bound}"
            await self.reg._wr(EDN_CTRL, _edn_ctrl(False, False, False))

        def _typ(value: int | None) -> int | None:
            return None if value is None else _field(value, ED_HW_TYPE)

        def _bit(value: int | None, mask: int) -> int | None:
            return None if value is None else int(bool(value & mask))

        # The first-command trial is graded before the next window opens, so its
        # held samples release on its own pass.
        self.chk.ctrl(
            "EDN-AUTO",
            gen_pre == 0 and self._auto_done_pre == 0,
            auto_before=gen_pre,
            sw_done_before=self._auto_done_pre,
        )
        fields = {
            "sw_done": self._auto_done,
            "first_type": _typ(gen_hw),
            "first_auto": _bit(gen_hw, ED_AUTO_MODE),
            "first_boot": _bit(gen_hw, ED_BOOT_MODE),
            "first_ack": _bit(gen_hw, ED_HW_ACK),
            "expected_type": ACMD_GENERATE,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "EDN-AUTO",
            not reason
            and _typ(gen_hw) == ACMD_GENERATE
            and _bit(gen_hw, ED_AUTO_MODE) == 1
            and _bit(gen_hw, ED_BOOT_MODE) == 0
            and self._auto_done == 1,
            **fields,
        )
        await self._release()
        await self._auto_seq_trial(AUTO_N_FORCED)
        await self._auto_seq_trial(self.plan.auto_n)
        try:
            _, rs_hw = await self._auto_trial("zero", 0)
        except TrialTimeout as exc:
            zero_reason = f"timeout:{exc.what} bound={exc.bound}"
            await self.reg._wr(EDN_CTRL, _edn_ctrl(False, False, False))
        self.chk.obs(
            "EDN-AUTO-ZERO",
            max_num_reqs=0,
            first_type=_typ(rs_hw),
            first_auto=_bit(rs_hw, ED_AUTO_MODE),
            first_boot=_bit(rs_hw, ED_BOOT_MODE),
            first_ack=_bit(rs_hw, ED_HW_ACK),
            reason=zero_reason or "na",
        )

    # --- EDN instantiate and the ESRC seed ------------------------------------------
    async def _inst_seed_leg(self) -> None:
        """CHK-EDN-INST-SEED: "CSRNG cannot acknowledge that command until it has
        accepted a complete ESRC seed" (sep-programming.adoc:466-468).

        A TRNG reset, then ESRC configured with its generators off (no seed), CSRNG
        on and EDN on in the stated sequence (``AUTO_REQ_MODE`` true,
        sep-programming.adoc:457-462). The instantiate to ``SW_CMD_REQ`` must reach
        the EDN to CSRNG port, then the drawn hold H passes with no seed handshake,
        no ``CMD_ACK`` and no rise of vector bit 27. The generators then go on: the
        first seed handshake comes before the rise of bit 27, ``CMD_ACK`` = 1 with
        ``CMD_STS`` = 0 (success), ``edn_cmd_req_done`` = 1, the next command on the
        port is ``GENERATE_CMD`` (edn.adoc:107) and ``HW_CMD_STS`` reads
        ``AUTO_MODE`` = 1, ``BOOT_MODE`` = 0. A seed handshake or a rise of bit 27
        in the hold closes the coverage window at once.
        """
        hold = self.plan.inst_hold
        close_graded_window(self.logger)
        await self._trng_reset()
        # The TRNG reset stops the scoreboard and its noise driver, and this leg runs
        # no scoreboard, so it drives the raw noise itself; with a static noise port
        # ESRC never fills a seed after the generators go on.
        # The driver ends on its own at a clock edge and the leg waits for it. On
        # Verilator a cancel of this driver makes the next AXI write time out one
        # time step after it starts.
        noise = _NoiseDrive()
        try:
            await self.assert_noise_force_active()
            await self._inst_seed_body(hold)
        finally:
            await noise.stop()

    async def _inst_seed_body(self, hold: int) -> None:
        dut = cocotb.top
        r = self.reg
        await self.start_seq(SepEsrcConfigSeq("inst_seed_esrc_config", reset_trng=False))
        await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
        await r._wr(EDN_CTRL, _edn_ctrl(False, False, False))
        await r._wr(EDN_CTRL, _edn_ctrl(False, True, True))
        await r._wr(EDN_INTR_ENABLE, ED_DONE)
        await r._wr(EDN_INTR_STATE, ED_DONE)
        f: dict = {"hold": hold}
        f["enable"] = int(bool(await r._rd(EDN_INTR_ENABLE) & ED_DONE))
        f["edn_done_pre0"] = int(not await r._rd(EDN_INTR_STATE) & ED_DONE)
        rdy = ED_STS_REG_RDY | ED_STS_RDY
        watch = _InstSeedWatch(self)
        reason = ""
        step = "rdy"
        try:
            _, pre = await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, "inst_seed_rdy")
            f["cmd_reg_rdy"] = int(bool(pre & ED_STS_REG_RDY))
            f["cmd_rdy"] = int(bool(pre & ED_STS_RDY))
            cocotb.start_soon(watch.run())
            await RisingEdge(dut.clk_i)
            open_graded_window(TEST, self.logger)
            step = "hold"
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            t_wr = watch.clk
            await ClockCycles(dut.clk_i, hold)
            sts = await r._rd(EDN_SW_CMD_STS)
            f["hold_clocks"] = watch.clk - t_wr
            f["hold_cmd_ack"] = int(bool(sts & ED_STS_ACK))
            f["ins_req_clk"] = "na" if watch.ins is None else watch.ins - t_wr
            if watch.hold_x is not None:
                reason = "unknown_seed_handshake_in_hold"
                f["hold_x_clk"] = watch.hold_x - t_wr
            elif watch.hs is not None:
                reason = "seed_handshake_in_hold"
            elif watch.ack is not None or sts & ED_STS_ACK:
                reason = "ack_in_hold"
            elif watch.ins is None:
                reason = "no_instantiate_on_port"
            if not reason:
                step = "ack"
                watch.in_hold = False
                t_en = watch.clk
                await self.start_seq(SepEsrcEnableGeneratorsSeq("inst_seed_enable_gens"))
                for _ in range(INST_ACK_CAP):
                    if watch.ack is not None:
                        break
                    await RisingEdge(dut.clk_i)
                if watch.ack is None:
                    raise TrialTimeout("inst_seed_ack", INST_ACK_CAP)
                step = "next_cmd"
                for _ in range(AUTO_CAP):
                    if watch.next_word is not None:
                        break
                    await RisingEdge(dut.clk_i)
                if watch.next_word is None:
                    raise TrialTimeout("inst_seed_next_cmd", AUTO_CAP)
                done = await r._rd(EDN_SW_CMD_STS)
                f["cmd_ack"] = int(bool(done & ED_STS_ACK))
                f["cmd_sts"] = _field(done, ED_STS_STS)
                f["edn_done"] = int(bool(await r._rd(EDN_INTR_STATE) & ED_DONE))
                hw = await r._rd(EDN_HW_CMD_STS)
                f["auto_mode"] = int(bool(hw & ED_AUTO_MODE))
                f["boot_mode"] = int(bool(hw & ED_BOOT_MODE))
                f["hs_clk"] = "na" if watch.hs is None else watch.hs - t_en
                f["ack_clk"] = watch.ack - t_en
                f["next_word"] = f"0x{watch.next_word:x}"
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound} step={step}"
        watch.stop()
        f["vec27_pre0"] = int(watch.vec_first == 0)
        if reason:
            f["reason"] = reason
        ok = (
            not reason
            and watch.hs is not None
            and watch.ack is not None
            and watch.hs < watch.ack
            and f.get("cmd_ack") == 1
            and f.get("cmd_sts") == STS_SUCCESS
            and f.get("next_word") is not None
            and decode_hdr(watch.next_word or 0)["acmd"] == ACMD_GENERATE
            and f.get("auto_mode") == 1
            and f.get("boot_mode") == 0
            and all(
                f.get(k) == 1
                for k in (
                    "enable",
                    "edn_done_pre0",
                    "vec27_pre0",
                    "cmd_reg_rdy",
                    "cmd_rdy",
                    "edn_done",
                )
            )
        )
        self._grade("EDN-INST-SEED", ok, **f, expected_sts=STS_SUCCESS)
        close_graded_window(self.logger)
        await self._release()
        await r._wr(EDN_CTRL, _edn_ctrl(False, False, False))

    # --- boot group -----------------------------------------------------------------
    async def _boot(
        self, auto: bool, bound: int, graded: bool = True
    ) -> tuple[int | None, int, int, int | None]:
        """One boot with BOOT_REQ_MODE true. Returns (clocks to BOOT_MODE or None, the
        HW_CMD_STS read that first shows BOOT_MODE, the CTRL word, the CTRL readback
        after that read or None). Only a ``graded`` boot, one that CHK-EDN-BOOT grades,
        opens the coverage window."""
        off = _edn_ctrl(boot=True, auto=auto, enable=False)
        on = _edn_ctrl(boot=True, auto=auto, enable=True)
        await self.reg._wr(EDN_BOOT_INS_CMD, BOOT_INS_ZERO_SEED)
        if graded:
            open_graded_window(TEST, self.logger)
        await self.reg._wr(EDN_CTRL, off)
        await self.reg._wr(EDN_CTRL, on)
        try:
            clk, sts = await self._wait(
                EDN_HW_CMD_STS, ED_BOOT_MODE, ED_BOOT_MODE, bound, "boot_mode"
            )
        except TrialTimeout:
            close_graded_window(self.logger)
            return None, 0, on, None
        ctrl_rb = await self.reg._rd(EDN_CTRL)
        close_graded_window(self.logger)
        return clk, sts, on, ctrl_rb

    async def _boot_group(self) -> None:
        await self._clean_start("boot_ref")
        t0, sts, ctrl, _ = await self._boot(auto=False, bound=FIRST_CAP, graded=False)
        if t0 is None:
            self.chk.ok(
                "EDN-BOOT",
                False,
                run="reference",
                ctrl=f"0x{ctrl:04x}",
                reason=f"timeout:boot_mode bound={FIRST_CAP}",
            )
            return
        t0 = max(t0, 1)
        self.chk.info("EDN-TSEED", tseed_clk=t0, auto_mode=int(bool(sts & ED_AUTO_MODE)))
        bound = BOUND_FACTOR * t0
        # Each boot runs twice from a clean start: first with the coverage window
        # closed, then, only after that boot passed CHK-EDN-BOOT, once more with the
        # window open and graded again.
        for auto in (True, False):
            for graded in (False, True):
                await self._clean_start(f"boot_auto{int(auto)}{'_cov' if graded else ''}")
                clk, sts, ctrl, ctrl_rb = await self._boot(auto=auto, bound=bound, graded=graded)
                self.chk.ctrl(
                    "EDN-BOOT",
                    ctrl_rb == ctrl,
                    instance="cov" if graded else "first",
                    ctrl=f"0x{ctrl:04x}",
                    ctrl_rb="na" if ctrl_rb is None else f"0x{ctrl_rb:04x}",
                )
                fields = {
                    "instance": "cov" if graded else "first",
                    "ctrl": f"0x{ctrl:04x}",
                    "boot_mode": int(bool(sts & ED_BOOT_MODE)),
                    "auto_mode": int(bool(sts & ED_AUTO_MODE)),
                    "boot_clk": clk if clk is not None else "na",
                    "clean": t0,
                    "bound": bound,
                    "rsvd": f"0x{sts & ~EDN.mask('HW_CMD_STS') & 0xFFFF_FFFF:x}",
                }
                if clk is None:
                    fields["reason"] = f"timeout:boot_mode bound={bound}"
                ok = clk is not None and not sts & ED_AUTO_MODE
                passed = self.chk.ok("EDN-BOOT", ok, **fields)
                await self._release()
                if not passed:
                    break

    # --- EDN software port leg -----------------------------------------------------
    async def _edn_sw_leg(self) -> None:
        await self._clean_start("edn_sw")
        r = self.reg
        open_graded_window(TEST, self.logger)
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=False))
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=True))
        await r._wr(EDN_INTR_ENABLE, ED_DONE)
        enable = int(bool(await r._rd(EDN_INTR_ENABLE) & ED_DONE))
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        hs = {"cmd_reg_rdy": 0, "cmd_rdy": 0, "ack_done": 0, "edn_done": 0}
        hs.update({"enable": enable, "vec27": 0})
        # Before the command: edn_cmd_req_done (W1C) and vector bit 27 read 0, so the
        # rise after the command is a change the command causes.
        await r._wr(EDN_INTR_STATE, ED_DONE)
        hs["edn_done_pre0"] = int(not await r._rd(EDN_INTR_STATE) & ED_DONE)
        hs["vec27_pre0"] = int(self.vec.level("edn_done") == 0)
        reason = ""
        t_cmd = None
        self._edn_first_sts = None
        try:
            _, pre = await self._wait(EDN_SW_CMD_STS, rdy_mask, rdy_mask, FIRST_CAP, "edn_rdy")
            hs["cmd_reg_rdy"] = int(bool(pre & ED_STS_REG_RDY))
            hs["cmd_rdy"] = int(bool(pre & ED_STS_RDY))
            t_wr = self._now()
            m = self.vec.mark()
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            ack0 = await r._rd(EDN_SW_CMD_STS)
            self.chk.obs("EDN-ACK0", ack_first_read=int(bool(ack0 & ED_STS_ACK)))
            _, done = await self._wait(EDN_SW_CMD_STS, ED_STS_ACK, ED_STS_ACK, FIRST_CAP, "edn_ack")
            t_cmd = max(self._now() - t_wr, 1)
            hs["ack_done"] = int(bool(done & ED_STS_ACK))
            # No sentence states CMD_RDY after the acknowledge (edn.adoc
            # SW_CMD_STS: firmware polls it before a command), so it is logged.
            self.chk.obs("EDN-RDY-AFTER-ACK", cmd_rdy=int(bool(done & ED_STS_RDY)))
            state = await r._rd(EDN_INTR_STATE)
            hs["edn_done"] = int(bool(state & ED_DONE))
            vclk = await self._wait_vec(m, "edn_done", VEC_CAP)
            hs["vec27"] = 1
            hs["vec_clk"] = vclk
            self._edn_first_sts = _field(done, ED_STS_STS)
            self.chk.obs("EDN-VEC", vec23=self.vec.level("cs_done"))
            await r._wr(EDN_INTR_STATE, ED_DONE)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        except BitWatchTimeout:
            reason = f"timeout:vec27 bound={VEC_CAP}"
        close_graded_window(self.logger)
        if reason:
            hs["reason"] = reason
        self.chk.ok(
            "EDN-SW-HS",
            not reason
            and all(
                hs[k] == 1
                for k in (
                    "cmd_reg_rdy",
                    "cmd_rdy",
                    "ack_done",
                    "edn_done",
                    "enable",
                    "vec27",
                    "edn_done_pre0",
                    "vec27_pre0",
                )
            ),
            **hs,
        )
        await self._release()
        if reason:
            self.chk.ok("EDN-INVSEQ", False, reason=f"no_first_command:{reason}")
            return
        await self._edn_invseq(t_cmd)
        await self._edn_sts(t_cmd)

    async def _edn_sts(self, t_cmd: int) -> None:
        """CTRL-EDN-STS: a reserved acmd through the port reads INVALID_ACMD (1) at
        its ack. OBS-EDN-STS: the code of the first instantiate (no sentence states
        it for ``AUTO_REQ_MODE`` = false with the endpoints in reset).

        CHK-EDN-ACK-ERR: that non-zero ack sets ``CSRNG_ACK_ERR``. Control: the bit
        reads 0 after a write of 0, before the command.

        CHK-EDN-ACMD-INV: after that ack, CSRNG ``RECOV_ALERT_STS`` bit 13 reads 1,
        EDN ``INTR_STATE.edn_cmd_req_done`` reads 1 and, with
        ``INTR_ENABLE.edn_cmd_req_done`` read as 1, vector bit 27 rises. Control:
        before the command, bit 13 reads 0 after a write of 0, and
        ``edn_cmd_req_done`` and vector bit 27 read 0 after a write of 1 to
        ``edn_cmd_req_done``."""
        r = self.reg
        bound = BOUND_FACTOR * t_cmd
        word = cmd_word(self.plan.bad_acmd)
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        reason = ""
        bad_sts = None
        ack_err = None
        acmd13 = None
        done = None
        # The second instantiate acked with a non-zero status, so the software port
        # does not take a command until EDN is disabled; disable and enable it.
        held = await r._rd(EDN_SW_CMD_STS)
        self.chk.obs("EDN-PORT-HELD", cmd_rdy=int(bool(held & ED_STS_RDY)))
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=False))
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=True))
        await r._wr(EDN_RECOV_ALERT_STS, 0)
        pre_ack_err = int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR))
        await r._wr(CSRNG_RECOV_ALERT_STS, 0)
        pre_acmd13 = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_ACMD_INV))
        await r._wr(EDN_INTR_STATE, ED_DONE)
        pre_done = int(bool(await r._rd(EDN_INTR_STATE) & ED_DONE))
        pre_vec27 = int(self.vec.level("edn_done") != 0)
        enable = int(bool(await r._rd(EDN_INTR_ENABLE) & ED_DONE))
        vec27 = None
        vec_clk = None
        open_graded_window(TEST, self.logger)
        try:
            await self._wait(EDN_SW_CMD_STS, rdy_mask, rdy_mask, bound, "edn_rdy3")
            m = self.vec.mark()
            await r._wr(EDN_SW_CMD_REQ, word)
            _, sts = await self._wait(EDN_SW_CMD_STS, ED_STS_ACK, ED_STS_ACK, bound, "edn_ack3")
            bad_sts = _field(sts, ED_STS_STS)
            ack_err = int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR))
            acmd13 = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_ACMD_INV))
            done = int(bool(await r._rd(EDN_INTR_STATE) & ED_DONE))
            try:
                vec_clk = await self._wait_vec(m, "edn_done", VEC_CAP)
                vec27 = 1
            except BitWatchTimeout:
                vec27 = 0
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        self.chk.ctrl("EDN-ACK-ERR", pre_ack_err == 0, ctrl_pre_ack_err=pre_ack_err)
        ack_fields = {
            "word": f"0x{word:x}",
            "cmd_sts": "na" if bad_sts is None else bad_sts,
            "ack_err": "na" if ack_err is None else ack_err,
            "expected": EXP_ACK_ERR,
            "ctrl_pre_ack_err": pre_ack_err,
        }
        if reason:
            ack_fields["reason"] = reason
        self.chk.ok(
            "EDN-ACK-ERR",
            not reason and bad_sts not in (None, STS_SUCCESS) and ack_err == EXP_ACK_ERR,
            **ack_fields,
        )
        ctrl = {"word": f"0x{word:x}", "cmd_sts": "na" if bad_sts is None else bad_sts}
        if reason:
            ctrl["reason"] = reason
        self.chk.ctrl("EDN-STS", bad_sts == STS_INVALID_ACMD, **ctrl)
        self.chk.ctrl(
            "EDN-ACMD-INV",
            pre_acmd13 == 0 and pre_done == 0 and pre_vec27 == 0,
            ctrl_pre_acmd13=pre_acmd13,
            ctrl_pre_edn_done=pre_done,
            ctrl_pre_vec27=pre_vec27,
        )
        inv = {
            "word": f"0x{word:x}",
            "csrng_acmd_alert": "na" if acmd13 is None else acmd13,
            "edn_done": "na" if done is None else done,
            "enable": enable,
            "vec27": "na" if vec27 is None else vec27,
            "vec_clk": "na" if vec_clk is None else vec_clk,
            "ctrl_pre_acmd13": pre_acmd13,
            "ctrl_pre_edn_done": pre_done,
            "ctrl_pre_vec27": pre_vec27,
        }
        if reason:
            inv["reason"] = reason
        self.chk.ok(
            "EDN-ACMD-INV",
            not reason and acmd13 == 1 and done == 1 and enable == 1 and vec27 == 1,
            **inv,
        )
        self.chk.obs(
            "EDN-STS",
            cmd_sts=self._edn_first_sts,
            word=f"0x{CMD_INSTANTIATE:x}",
            auto_req_mode="false",
            reason="success_stated_only_with_auto_req_mode_true",
        )
        await self._release()

    async def _edn_invseq(self, t_cmd: int) -> None:
        r = self.reg
        bound = BOUND_FACTOR * t_cmd
        first = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        self.chk.ctrl("EDN-INVSEQ", first == 0, ctrl_first_invseq=first)
        # The second instantiate runs with the coverage window closed: no stated value
        # grades its acknowledge. The window opens for the bit 14 read and clear only
        # once that acknowledge has been read back.
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        invseq = 0
        cleared = 0
        set_before_clear = 0
        reason = ""
        try:
            await self._wait(EDN_SW_CMD_STS, rdy_mask, rdy_mask, bound, "edn_rdy2")
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            _, recov = await self._wait(
                CSRNG_RECOV_ALERT_STS, CS_INVSEQ, CS_INVSEQ, bound, "csrng_invseq"
            )
            invseq = int(bool(recov & CS_INVSEQ))
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        sts = await r._rd(EDN_SW_CMD_STS)
        self.chk.obs(
            "EDN-INVSEQ",
            cmd_ack=int(bool(sts & ED_STS_ACK)),
            cmd_sts=_field(sts, ED_STS_STS),
            ack_err=int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR)),
            hw_exc=f"0x{await r._rd(CSRNG_HW_EXC_STS):x}",
            hw_inst_exc=int(bool(await r._rd(CSRNG_INTR_STATE) & CS_HW_INST_EXC)),
            vec25=self.vec.level("cs_exc"),
            cmd_rdy_after=int(bool(sts & ED_STS_RDY)),
        )
        await self._main_sm("edn_invseq")
        if sts & ED_STS_ACK:
            open_graded_window(TEST, self.logger)
        set_before_clear = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        await r._wr(CSRNG_RECOV_ALERT_STS, 0)
        after = await r._rd(CSRNG_RECOV_ALERT_STS)
        cleared = int(not after & CS_INVSEQ)
        close_graded_window(self.logger)
        fields = {
            "ctrl_first_invseq": first,
            "csrng_invseq": invseq,
            "set_before_clear": set_before_clear,
            "cleared_by_write0": cleared,
            "bound": bound,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "EDN-INVSEQ",
            not reason and invseq == 1 and set_before_clear == 1 and cleared == 1,
            **fields,
        )
        await self._release()

    # --- CSRNG software instance leg ---------------------------------------------
    async def _csrng_sw_leg(self) -> None:
        await self._clean_start("csrng_sw")
        r = self.reg
        open_graded_window(TEST, self.logger)
        await r._wr(CSRNG_INTR_ENABLE, CS_DONE)
        enable = int(bool(await r._rd(CSRNG_INTR_ENABLE) & CS_DONE))
        hs = {"cmd_rdy": 0, "ack": 0, "done": 0, "enable": enable, "vec23": 0}
        hs.update({"done2_pre0": 0, "vec23_2_pre0": 0, "done2": 0, "vec23_2": 0})
        # Before the command: cs_cmd_req_done (W1C) and vector bit 23 read 0, so the
        # rise after the command is a change the command causes.
        await r._wr(CSRNG_INTR_STATE, CS_DONE)
        hs["done_pre0"] = int(not await r._rd(CSRNG_INTR_STATE) & CS_DONE)
        hs["vec23_pre0"] = int(self.vec.level("cs_done") == 0)
        reason = ""
        first = 1
        invseq = 0
        cleared = 0
        try:
            _, pre = await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, FIRST_CAP, "rdy")
            hs["cmd_rdy"] = int(bool(pre & CS_STS_RDY))
            t_wr = self._now()
            m = self.vec.mark()
            await r._wr(CSRNG_CMD_REQ, CMD_INSTANTIATE)
            ack0 = await r._rd(CSRNG_SW_CMD_STS)
            self.chk.obs("CSRNG-ACK0", ack_first_read=int(bool(ack0 & CS_STS_ACK)))
            _, done = await self._wait(CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "ack")
            t_cmd = max(self._now() - t_wr, 1)
            hs["ack"] = int(bool(done & CS_STS_ACK))
            # CMD_RDY after the acknowledge is not stated (csrng.adoc SW_CMD_STS:
            # firmware polls it before a command), so it is logged.
            self.chk.obs("CSRNG-RDY-AFTER-ACK", cmd_rdy=int(bool(done & CS_STS_RDY)))
            state = await r._rd(CSRNG_INTR_STATE)
            hs["done"] = int(bool(state & CS_DONE))
            hs["vec_clk"] = await self._wait_vec(m, "cs_done", VEC_CAP)
            hs["vec23"] = 1
            self.chk.obs("CSRNG-STS", cmd_sts=_field(done, CS_STS_STS), t_cmd=t_cmd)
            await self._main_sm("csrng_inst_ack")
            await r._wr(CSRNG_INTR_STATE, CS_DONE)
            # Control: bit 14 is 0 after the first command.
            first = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
            self.chk.ctrl("CSRNG-SW", first == 0, ctrl_first_invseq=first)
            bound = BOUND_FACTOR * t_cmd
            hs["bound"] = bound
            # A command completes "successfully or unsuccessfully"
            # (theory_of_operation.md:286), and cs_cmd_req_done "will assert when a
            # CSRNG command has been completed" (:421): after the repeated
            # instantiate the state bit sets and vector bit 23 rises again. Before
            # it, both read 0.
            hs["done2_pre0"] = int(not await r._rd(CSRNG_INTR_STATE) & CS_DONE)
            hs["vec23_2_pre0"] = int(self.vec.level("cs_done") == 0)
            await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, bound, "rdy2")
            m2 = self.vec.mark()
            await r._wr(CSRNG_CMD_REQ, CMD_INSTANTIATE)
            _, recov = await self._wait(CSRNG_RECOV_ALERT_STS, CS_INVSEQ, CS_INVSEQ, bound, "inv")
            invseq = int(bool(recov & CS_INVSEQ))
            await self._wait(CSRNG_INTR_STATE, CS_DONE, CS_DONE, bound, "done2")
            hs["done2"] = int(bool(await r._rd(CSRNG_INTR_STATE) & CS_DONE))
            hs["vec_clk2"] = await self._wait_vec(m2, "cs_done", VEC_CAP)
            hs["vec23_2"] = 1
            sts = await r._rd(CSRNG_SW_CMD_STS)
            self.chk.obs(
                "CSRNG-INVSEQ",
                cmd_sts=_field(sts, CS_STS_STS),
                hw_exc=f"0x{await r._rd(CSRNG_HW_EXC_STS):x}",
            )
            await self._main_sm("csrng_invseq")
            await r._wr(CSRNG_RECOV_ALERT_STS, 0)
            cleared = int(not await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        except BitWatchTimeout:
            reason = f"timeout:vec23 bound={VEC_CAP}"
        close_graded_window(self.logger)
        hs.update({"ctrl_first_invseq": first, "invseq": invseq, "cleared_by_write0": cleared})
        if reason:
            hs["reason"] = reason
        ok = not reason and all(
            hs[k] == 1
            for k in (
                "cmd_rdy",
                "ack",
                "done",
                "enable",
                "vec23",
                "invseq",
                "done_pre0",
                "vec23_pre0",
                "done2_pre0",
                "vec23_2_pre0",
                "done2",
                "vec23_2",
            )
        )
        self.chk.ok("CSRNG-SW", ok and first == 0 and cleared == 1, **hs)
        await self._release()

    # --- EDN boot command words at reset ----------------------------------------
    async def _boot_cmd_reset(self) -> None:
        """CHK-EDN-BOOT-CMD: the reset values of the two boot words, decoded with
        the header layout. Runs before any write to EDN."""
        r = self.reg
        open_graded_window(TEST, self.logger)
        ins = await r._rd(EDN_BOOT_INS_CMD)
        gen = await r._rd(EDN_BOOT_GEN_CMD)
        close_graded_window(self.logger)
        hi = decode_hdr(ins)
        hg = decode_hdr(gen)
        self.chk.ok(
            "EDN-BOOT-CMD",
            ins == BOOT_INS_RESET
            and gen == BOOT_GEN_RESET
            and hi["acmd"] == ACMD_INSTANTIATE
            and hg["acmd"] == ACMD_GENERATE
            and hi["clen"] == 0
            and hg["clen"] == 0
            and hg["glen"] == 0xFFF,
            boot_ins=f"0x{ins:x}",
            boot_gen=f"0x{gen:x}",
            ins_acmd=hi["acmd"],
            ins_clen=hi["clen"],
            ins_flag0=f"0x{hi['flag0']:x}",
            gen_acmd=hg["acmd"],
            gen_clen=hg["clen"],
            gen_glen=f"0x{hg['glen']:x}",
        )
        await self._release()

    # --- CTRL field alerts --------------------------------------------------------
    async def _ctrl_mubi_leg(self) -> None:
        """CHK-CSRNG-CTRL-MUBI and CHK-EDN-CTRL-MUBI, one trial per CTRL field."""
        close_graded_window(self.logger)
        await self._trng_reset()
        units = (
            (
                "CSRNG-CTRL-MUBI",
                CSRNG,
                CSRNG_CTRL,
                CSRNG_RECOV_ALERT_STS,
                CS_CTRL_ALERT,
                self.plan.cs_bad,
            ),
            ("EDN-CTRL-MUBI", EDN, EDN_CTRL, EDN_RECOV_ALERT_STS, ED_CTRL_ALERT, self.plan.ed_bad),
        )
        r = self.reg
        for name, meta, ctrl_addr, recov_addr, alerts, bad in units:
            legal = meta.value("CTRL", **{f: MUBI_FALSE for f in alerts})
            for (field, bit), value in zip(alerts.items(), bad):
                open_graded_window(TEST, self.logger)
                await r._wr(ctrl_addr, legal)
                pre = int(bool(await r._rd(recov_addr) & bit))
                self.chk.ctrl(name, pre == 0, field=field, legal=f"0x{legal:x}", alert_pre=pre)
                word = meta.value("CTRL", **{**{f: MUBI_FALSE for f in alerts}, field: value})
                await r._wr(ctrl_addr, word)
                reason = ""
                recov = 0
                try:
                    _, recov = await self._wait(recov_addr, bit, bit, ALERT_CAP, f"{field}_alert")
                except TrialTimeout as exc:
                    reason = f"timeout:{exc.what} bound={exc.bound}"
                await r._wr(ctrl_addr, legal)
                await r._wr(recov_addr, 0)
                cleared = int(not await r._rd(recov_addr) & bit)
                close_graded_window(self.logger)
                fields = {
                    "field": field,
                    "value": f"0x{value:x}",
                    "ctrl": f"0x{word:x}",
                    "alert_set": int(bool(recov & bit)),
                    "recov": f"0x{recov:x}",
                    "cleared_by_write0": cleared,
                }
                if reason:
                    fields["reason"] = reason
                self.chk.ok(name, not reason and bool(recov & bit) and cleared == 1, **fields)
                await self._release()

    # --- CSRNG software commands ----------------------------------------------------
    async def _sw_cmd(self, word: int, bound: int, what: str, wait_ack: bool = True):
        """Write ``word`` to CMD_REQ once CMD_RDY reads 1. With ``wait_ack``, wait for
        CMD_ACK and return ``(clocks, CMD_STS)``; else return ``(0, None)``."""
        await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, bound, f"{what}_rdy")
        t_wr = self._now()
        await self.reg._wr(CSRNG_CMD_REQ, word)
        if not wait_ack:
            return 0, None
        _, sts = await self._wait(CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, bound, f"{what}_ack")
        return max(self._now() - t_wr, 1), _field(sts, CS_STS_STS)

    async def _sw_generate(self, bound: int) -> tuple[int, int, int]:
        """One Generate of one 128-bit block. Reads GENBITS while GENBITS_VLD is 1
        until CMD_ACK, so the acknowledge can follow the data. Returns
        ``(CMD_STS, RECOV_ALERT_STS at the ack, words read)``."""
        r = self.reg
        await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, bound, "gen_rdy")
        await r._wr(CSRNG_CMD_REQ, CMD_GENERATE_1)
        t0 = self._now()
        words = 0
        while True:
            sts = await self._reader(CSRNG_SW_CMD_STS)()
            if sts & CS_STS_ACK:
                break
            if self._now() - t0 > bound:
                raise TrialTimeout("gen_ack", bound)
            if await r._rd(CSRNG_GENBITS_VLD) & GB_VLD:
                await r._rd(CSRNG_GENBITS)
                words += 1
        recov = await r._rd(CSRNG_RECOV_ALERT_STS)
        return _field(sts, CS_STS_STS), recov, words

    async def _clear_bit(self, bit: int) -> int:
        """Write 0 to RECOV_ALERT_STS; 1 if ``bit`` then reads 0."""
        await self.reg._wr(CSRNG_RECOV_ALERT_STS, 0)
        return int(not await self.reg._rd(CSRNG_RECOV_ALERT_STS) & bit)

    # --- command header leg: reserved acmd and flag0 ---------------------------------
    async def _hdr_leg(self) -> None:
        await self._clean_start("hdr")
        r = self.reg
        plan = self.plan
        step = "ins_f9"
        acmd = {"word": f"0x{cmd_word(plan.bad_acmd):x}", "alert_set": 0, "cmd_sts": "na"}
        flag0 = {"word": f"0x{cmd_word(ACMD_INSTANTIATE, flag0=plan.bad_flag0):x}"}
        flag0["alert_set"] = 0
        reason = ""
        try:
            # The first instantiate runs with the window closed: no check of this leg
            # grades its handshake or its cs_cmd_req_done.
            t_cmd, sts = await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), FIRST_CAP, step)
            bound = BOUND_FACTOR * t_cmd
            recov = await r._rd(CSRNG_RECOV_ALERT_STS)
            self.chk.obs("CSRNG-HDR-INS", flag0="0x9", cmd_sts=sts, t_cmd=t_cmd)
            self.chk.ctrl(
                "CSRNG-ACMD-INV", not recov & CS_ACMD_INV, recov=f"0x{recov:x}", after="instantiate"
            )
            self.chk.ctrl(
                "CSRNG-FLAG0", not recov & CS_FLAG0_INV, flag0="0x9", recov=f"0x{recov:x}"
            )
            open_graded_window(TEST, self.logger)
            # Reserved acmd: bit 13 and CMD_STS INVALID_ACMD.
            step = "acmd_inv"
            _, sts = await self._sw_cmd(cmd_word(plan.bad_acmd), bound, step)
            acmd["cmd_sts"] = sts
            _, recov = await self._wait(
                CSRNG_RECOV_ALERT_STS, CS_ACMD_INV, CS_ACMD_INV, bound, "acmd_alert"
            )
            acmd["alert_set"] = 1
            acmd["cleared_by_write0"] = await self._clear_bit(CS_ACMD_INV)
            # Uninstantiate, then an instantiate with flag0 True: bit 4 stays 0.
            step = "uninst1"
            _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), bound, step)
            self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="acmd_inv")
            step = "ins_f6"
            _, sts = await self._sw_cmd(cmd_word(ACMD_INSTANTIATE, flag0=MUBI_TRUE), bound, step)
            recov = await r._rd(CSRNG_RECOV_ALERT_STS)
            self.chk.obs("CSRNG-HDR-INS", flag0="0x6", cmd_sts=sts, recov=f"0x{recov:x}")
            self.chk.ctrl(
                "CSRNG-FLAG0", not recov & CS_FLAG0_INV, flag0="0x6", recov=f"0x{recov:x}"
            )
            step = "uninst2"
            _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), bound, step)
            self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="ins_f6")
            # Instantiate with an invalid flag0: bit 4.
            step = "ins_fbad"
            word = cmd_word(ACMD_INSTANTIATE, flag0=plan.bad_flag0)
            await self._sw_cmd(word, bound, step, wait_ack=False)
            _, recov = await self._wait(
                CSRNG_RECOV_ALERT_STS, CS_FLAG0_INV, CS_FLAG0_INV, bound, "flag0_alert"
            )
            flag0["alert_set"] = 1
            sts = await r._rd(CSRNG_SW_CMD_STS)
            self.chk.obs(
                "CSRNG-FLAG0-CMD",
                cmd_ack=int(bool(sts & CS_STS_ACK)),
                cmd_sts=_field(sts, CS_STS_STS),
                recov=f"0x{recov:x}",
            )
            _, sts = await self._wait(CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, bound, "fbad_ack")
            held = await self._clear_bit(CS_FLAG0_INV)
            self.chk.obs(
                "CSRNG-FLAG0-HELD", cmd_sts=_field(sts, CS_STS_STS), cleared_after_ack=held
            )
            # An instantiate with a legal flag0 sets the field back to a legal value.
            step = "uninst3"
            _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), bound, step)
            self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="ins_fbad")
            step = "ins_f9b"
            _, sts = await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), bound, step)
            self.chk.obs("CSRNG-HDR-INS", flag0="0x9", cmd_sts=sts, after="ins_fbad")
            flag0["cleared_by_write0"] = await self._clear_bit(CS_FLAG0_INV)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound} step={step}"
        close_graded_window(self.logger)
        for fields in (acmd, flag0):
            fields.setdefault("cleared_by_write0", 0)
            if reason:
                fields["reason"] = reason
        self.chk.ok(
            "CSRNG-ACMD-INV",
            not reason
            and acmd["alert_set"] == 1
            and acmd["cmd_sts"] == STS_INVALID_ACMD
            and acmd["cleared_by_write0"] == 1,
            **acmd,
        )
        self.chk.ok(
            "CSRNG-FLAG0",
            not reason and flag0["alert_set"] == 1 and flag0["cleared_by_write0"] == 1,
            **flag0,
        )
        await self._release()

    # --- reseed leg: limit, reseed header, GENBITS gate -------------------------------
    async def _reseed_leg(self) -> None:
        await self._clean_start("reseed")
        r = self.reg
        plan = self.plan
        k = plan.reseed_k
        await r._wr(CSRNG_RESEED_INTERVAL, k)
        gens: list[tuple[int, int, int]] = []
        refused = None
        lim = {"k": k, "max_generates": k + 1, "expected_refused_index": k + 1}
        hdr = {"word": f"0x{cmd_word(ACMD_RESEED):x}"}
        gate = {"sw_app_enable": f"0x{plan.gen_off:x}"}
        kat: dict = {}
        reason = ""
        step = "ins"
        try:
            # The instantiate runs with the window closed: no check of this leg grades
            # its handshake or its cs_cmd_req_done.
            await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), FIRST_CAP, step)
            open_graded_window(TEST, self.logger)
            for i in range(1, k + 2):
                step = f"gen{i}"
                sts, recov, words = await self._sw_generate(FIRST_CAP)
                gens.append((sts, int(bool(recov & CS_RESEED_CNT)), words))
                if i == 1:
                    self.chk.ctrl(
                        "CSRNG-RESEED-LIMIT",
                        sts != STS_RESEED_CNT_EXCEEDED and not recov & CS_RESEED_CNT,
                        index=1,
                        cmd_sts=sts,
                        alert15=int(bool(recov & CS_RESEED_CNT)),
                        words=words,
                    )
                if sts == STS_RESEED_CNT_EXCEEDED:
                    refused = i
                    break
            lim["refused_index"] = refused if refused is not None else "none"
            lim["cmd_sts"] = [g[0] for g in gens]
            lim["alert15"] = [g[1] for g in gens]
            lim["words"] = [g[2] for g in gens]
            lim["cleared_by_write0"] = await self._clear_bit(CS_RESEED_CNT)
            # The earlier Generates leave words in GENBITS (_sw_generate stops at the
            # ack), so drain GENBITS until GENBITS_VLD reads 0 before the Reseed: the
            # words counted below then come only from the Generate after the Reseed.
            hdr_drain_max = 4 * len(gens)
            hdr_drained = 0
            hdr_left = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
            while hdr_left and hdr_drained < hdr_drain_max:
                await r._rd(CSRNG_GENBITS)
                hdr_drained += 1
                hdr_left = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
            hdr.update({"pre_drained": hdr_drained, "pre_vld": hdr_left})
            # Reseed with the stated header, then one Generate.
            step = "reseed"
            _, sts = await self._sw_cmd(cmd_word(ACMD_RESEED), FIRST_CAP, step)
            hdr["reseed_cmd_sts"] = sts
            step = "gen_after_reseed"
            sts, recov, words = await self._sw_generate(FIRST_CAP)
            # Words still pending after the ack count to the same request. The bound is
            # one read past GEN1_WORDS, so an extra word from the DUT shows as a count of
            # GEN1_WORDS + 1.
            while words <= GEN1_WORDS and await r._rd(CSRNG_GENBITS_VLD) & GB_VLD:
                await r._rd(CSRNG_GENBITS)
                words += 1
            hdr.update(
                {"cmd_sts": sts, "alert15": int(bool(recov & CS_RESEED_CNT)), "words": words}
            )
            # GENBITS gate. The earlier Generates leave words in GENBITS, so drain it
            # first: GENBITS_VLD "is set when genbits are available" and GENBITS "must
            # be read four times for each request made" (csrng.hjson). Each Generate of
            # this leg asks for one block, so at most four words per Generate remain.
            step = "gate"
            drain_max = 4 * (len(gens) + 1)
            drained = 0
            left = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
            while left and drained < drain_max:
                await r._rd(CSRNG_GENBITS)
                drained += 1
                left = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
            gate.update({"drained": drained, "vld_after_drain": left})
            gate["sw_app_alert_pre"] = int(
                bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_CTRL_ALERT["SW_APP_ENABLE"])
            )
            # Then this leg's own Generate, with data pending, then SW_APP_ENABLE not True.
            await self._sw_cmd(CMD_GENERATE_1, FIRST_CAP, step, wait_ack=False)
            try:
                _, vld = await self._wait(CSRNG_GENBITS_VLD, GB_VLD, GB_VLD, FIRST_CAP, "gate_vld")
            except TrialTimeout:
                vld = 0
            self.chk.ctrl(
                "CSRNG-GENBITS-GATE",
                not left and bool(vld & GB_VLD),
                drained=drained,
                vld_after_drain=left,
                genbits_vld=vld & GB_VLD,
            )
            await r._wr(
                CSRNG_CTRL, CSRNG.value("CTRL", ENABLE=MUBI_TRUE, SW_APP_ENABLE=plan.gen_off)
            )
            # Control: the block is still pending after the CTRL write, so the gated reads
            # hit pending data. GENBITS_VLD "is set when genbits are available on this
            # application interface after a generate command has been issued"
            # (csrng.hjson GENBITS_VLD); the text gives it no SW_APP_ENABLE term.
            vld_gated = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
            self.chk.ctrl(
                "CSRNG-GENBITS-GATE",
                bool(vld_gated),
                pending_after_ctrl=vld_gated,
                sw_app_enable=f"0x{plan.gen_off:x}",
            )
            gate["genbits"] = [f"0x{await r._rd(CSRNG_GENBITS):x}" for _ in range(4)]
            self.chk.obs(
                "CSRNG-GENBITS-GATE",
                genbits_vld_after=await r._rd(CSRNG_GENBITS_VLD) & GB_VLD,
                sw_app_read_en=f"0x{self.rd(cocotb.top.csrng_sw_app_read_en_o):02x}",
                lc_hw_debug_en=f"0x{self.rd(cocotb.top.csrng_lc_hw_debug_en_o):x}",
                lc_source="skip_fuse_sense" if "skip_fuse_sense" in cocotb.plusargs else "fuse",
            )
            # The CTRL write sets bit 1 when SW_APP_ENABLE is neither True nor False
            # (csrng.adoc:351-353); the bit is RW0C, so one read after the write sees it.
            gate["sw_app_alert"] = int(
                bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_CTRL_ALERT["SW_APP_ENABLE"])
            )
            # The gate Generate is the second since the Reseed, inside the interval
            # (k >= 3), so it completes with CMD_STS success; a missing acknowledge
            # times out and fails the check.
            _, gen_sts = await self._wait(
                CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "gate_ack"
            )
            gate["gen_cmd_sts"] = _field(gen_sts, CS_STS_STS)
            step = "kat"
            kat = await self._genbits_kat(drain_max)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound} step={step}"
        close_graded_window(self.logger)
        for fields in (lim, hdr, gate):
            if reason:
                fields["reason"] = reason
        last = gens[-1] if gens else (None, 0, 0)
        lim_ok = (
            not reason and refused == k + 1 and last[1] == 1 and lim.get("cleared_by_write0") == 1
        )
        self.chk.ok("CSRNG-RESEED-LIMIT", lim_ok, **lim)
        self.chk.ctrl(
            "CSRNG-RESEED-HDR",
            refused is not None
            and hdr.get("pre_vld") == 0
            and hdr.get("reseed_cmd_sts") == STS_SUCCESS,
            refused_index=lim.get("refused_index"),
            pre_drained=hdr.get("pre_drained"),
            pre_vld=hdr.get("pre_vld"),
            reseed_cmd_sts=hdr.get("reseed_cmd_sts"),
            expected_reseed_sts=STS_SUCCESS,
        )
        self.chk.ok(
            "CSRNG-RESEED-HDR",
            not reason
            and hdr.get("cmd_sts") == STS_SUCCESS
            and hdr.get("alert15") == 0
            and hdr.get("words") == GEN1_WORDS,
            **hdr,
            expected_sts=STS_SUCCESS,
            expected_words=GEN1_WORDS,
        )
        words = gate.get("genbits", [])
        plan_app_alert = plan.gen_off in MUBI_INVALID
        self.chk.ok(
            "CSRNG-KAT",
            not reason
            and bool(kat)
            and kat["genbits"] == kat["expected"]
            and kat["gen_cmd_sts"] == STS_SUCCESS,
            **kat,
            expected_gen_sts=STS_SUCCESS,
            **({"reason": reason} if reason else {}),
        )
        self.chk.ok(
            "CSRNG-GENBITS-GATE",
            not reason
            and len(words) == 4
            and all(w == "0x0" for w in words)
            and gate.get("gen_cmd_sts") == STS_SUCCESS
            and gate.get("sw_app_alert_pre") == 0
            and gate.get("sw_app_alert") == int(plan_app_alert),
            **gate,
            expected_gen_sts=STS_SUCCESS,
            expected_sw_app_alert=int(plan_app_alert),
        )
        await self._release()

    async def _genbits_kat(self, drain_max: int, clear_recov: bool = False) -> dict:
        """Known-answer Generate with SW_APP_ENABLE True: the GENBITS words equal the
        SP 800-90A CTR_DRBG golden (AES-256, no derivation function) of the drawn seed.

        The instance is uninstantiated and instantiated with flag0 True and clen 12,
        so "Only provided additional data will be used as seed"
        (theory_of_operation.md:227); "This block does not use a derivation function"
        (README.md:47). The seed bytes B1 (most significant) .. B48 go to CMD_REQ
        least significant word first, and GENBITS returns each 128-bit block least
        significant word first (programmers_guide.md:37-114).

        With ``clear_recov``, ``RECOV_ALERT_STS`` is written 0 and read back
        between the Instantiate acknowledge and the Generate, and read again after
        the Generate acknowledge (``recov_clear``, ``recov_after``).
        """
        r = self.reg
        seed = self.plan.kat_seed
        extra: dict = {}
        await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
        drained = 0
        while await r._rd(CSRNG_GENBITS_VLD) & GB_VLD and drained < drain_max:
            await r._rd(CSRNG_GENBITS)
            drained += 1
        await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "kat_uni")
        ins = cmd_word(ACMD_INSTANTIATE, clen=KAT_CLEN, flag0=MUBI_TRUE)
        await self._sw_cmd(ins, FIRST_CAP, "kat_ins_rdy", wait_ack=False)
        for i in range(KAT_CLEN):
            await r._wr(CSRNG_CMD_REQ, (seed >> (32 * i)) & 0xFFFF_FFFF)
        _, ins_sts = await self._wait(
            CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "kat_ins_ack"
        )
        if clear_recov:
            await r._wr(CSRNG_RECOV_ALERT_STS, 0)
            extra["recov_clear"] = await r._rd(CSRNG_RECOV_ALERT_STS)
        await self._sw_cmd(CMD_GENERATE_1, FIRST_CAP, "kat_gen", wait_ack=False)
        got = []
        for i in range(GEN1_WORDS):
            await self._wait(CSRNG_GENBITS_VLD, GB_VLD, GB_VLD, FIRST_CAP, f"kat_vld{i}")
            got.append(await r._rd(CSRNG_GENBITS))
        # The window is open across this Generate, so its acknowledge is graded too:
        # a fresh instance completes the Generate with CMD_STS success.
        _, gen_sts = await self._wait(
            CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "kat_gen_ack"
        )
        if clear_recov:
            extra["recov_after"] = await r._rd(CSRNG_RECOV_ALERT_STS)
        golden = SepCtrDrbgGolden()
        golden.instantiate(0, additional_input=seed)
        block = golden.generate(1)[0]
        expected = [(block >> (32 * i)) & 0xFFFF_FFFF for i in range(GEN1_WORDS)]
        return {
            "drained": drained,
            "ins_cmd_sts": _field(ins_sts, CS_STS_STS),
            "gen_cmd_sts": _field(gen_sts, CS_STS_STS),
            "genbits": [f"0x{w:08x}" for w in got],
            "expected": [f"0x{w:08x}" for w in expected],
            **extra,
        }

    # --- reserved acmd 0x9: the last leg ---------------------------------------------
    async def _acmd_hi_leg(self) -> None:
        """OBS-CSRNG-ACMD-HI: after an instantiate, log the ``CMD_STS`` and
        ``RECOV_ALERT_STS`` of the reserved acmd 0x9. Not graded: the CSRNG decodes
        acmd bits [2:0] only, and no text states the result of 0x9."""
        await self._clean_start("acmd_hi")
        word = cmd_word(ACMD_RESERVED_HI)
        hi = {"word": f"0x{word:x}", "cmd_sts": "na", "recov": "na"}
        step = "ins"
        try:
            t_cmd, _ = await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), FIRST_CAP, step)
            step = "acmd_hi"
            _, sts = await self._sw_cmd(word, BOUND_FACTOR * t_cmd, step)
            hi["cmd_sts"] = sts
            hi["recov"] = f"0x{await self.reg._rd(CSRNG_RECOV_ALERT_STS):x}"
        except TrialTimeout as exc:
            hi["reason"] = f"timeout:{exc.what} bound={exc.bound} step={step}"
        self.chk.obs("CSRNG-ACMD-HI", **hi)

    async def _enable_order_leg(self) -> None:
        """OBS-DRBG-ENABLE-ORDER: EDN on first, then CSRNG, then ESRC, and one EDN
        software instantiate. No text states the result of this order, so the status
        registers are logged."""
        close_graded_window(self.logger)
        await self._trng_reset()
        r = self.reg
        f: dict = {"ack_seen": 0}
        # The TRNG reset stops the scoreboard and its noise driver; this leg drives
        # the raw noise itself, as the instantiate-seed leg does.
        noise = _NoiseDrive()
        try:
            await self.assert_noise_force_active()
            await r._wr(EDN_CTRL, _edn_ctrl(False, False, True))
            await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
            await self.start_seq(SepEsrcConfigSeq("enable_order_esrc_config", reset_trng=False))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("enable_order_enable_gens"))
            rdy = ED_STS_REG_RDY | ED_STS_RDY
            try:
                await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, "enable_order_rdy")
                await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
                await self._wait(
                    EDN_SW_CMD_STS, ED_STS_ACK, ED_STS_ACK, FIRST_CAP, "enable_order_ack"
                )
                f["ack_seen"] = 1
            except TrialTimeout as exc:
                f["reason"] = f"timeout:{exc.what} bound={exc.bound}"
            f["edn_sw_cmd_sts"] = f"0x{await r._rd(EDN_SW_CMD_STS):x}"
            f["csrng_sw_cmd_sts"] = f"0x{await r._rd(CSRNG_SW_CMD_STS):x}"
            f["edn_err_code"] = f"0x{await r._rd(EDN_ERR_CODE):x}"
            f["csrng_err_code"] = f"0x{await r._rd(CSRNG_ERR_CODE):x}"
            f["edn_recov"] = f"0x{await r._rd(EDN_RECOV_ALERT_STS):x}"
            f["csrng_recov"] = f"0x{await r._rd(CSRNG_RECOV_ALERT_STS):x}"
            self.chk.obs("DRBG-ENABLE-ORDER", **f)
            await r._wr(EDN_CTRL, _edn_ctrl(False, False, False))
        finally:
            await noise.stop()

    # --- open-value legs: bus compare replay and V counter wrap ------------------------
    async def _leg_cov(self, leg: str) -> None:
        """Pass label of an open-value leg whose control passed."""
        set_open_value_leg_pass(leg, self.logger)
        await ClockCycles(cocotb.top.clk_i, OV_LABEL_CLOCKS)
        set_open_value_leg_pass(None, self.logger)

    async def _bus_cmp_leg(self) -> None:
        """CTRL-CSRNG-BUS-CMP and OBS-CSRNG-BUS-CMP: two known-answer Generates with
        the same seed put two equal consecutive blocks on the software port.

        ``RECOV_ALERT_STS`` is written 0 between the second Instantiate and the second
        Generate. The control: both 4-word blocks equal the golden block, so they
        equal each other, and bit 12 reads 0 after the clear. Bit 12 after the second
        Generate is logged: ``CS_BUS_CMP_ALERT`` is set when the genbits value equals
        "the prior valid value on the bus" (csrng.hjson:655-656), and no text states
        whether that value survives the Uninstantiate between the two blocks
        (theory_of_operation.md:270 zeroes the instance values).
        """
        await self._clean_start("bus_cmp")
        f: dict = {}
        ok = False
        step = "ins"
        try:
            await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), FIRST_CAP, "bus_cmp_ins")
            step = "kat1"
            first = await self._genbits_kat(GEN1_WORDS)
            step = "kat2"
            second = await self._genbits_kat(GEN1_WORDS, clear_recov=True)
            blk_eq = first["genbits"] == second["genbits"]
            bit12_clear = int(bool(second["recov_clear"] & CS_BUS_CMP))
            f = {
                "blk1": first["genbits"],
                "blk2": second["genbits"],
                "golden": first["expected"],
                "blk1_eq_blk2": int(blk_eq),
                "bit12_after_clear": bit12_clear,
                "gen_cmd_sts": [first["gen_cmd_sts"], second["gen_cmd_sts"]],
            }
            ok = (
                blk_eq
                and first["genbits"] == first["expected"]
                and bit12_clear == 0
                and first["gen_cmd_sts"] == STS_SUCCESS
                and second["gen_cmd_sts"] == STS_SUCCESS
            )
            recov = second["recov_after"]
        except TrialTimeout as exc:
            f["reason"] = f"timeout:{exc.what} bound={exc.bound} step={step}"
        if self.chk.ctrl("CSRNG-BUS-CMP", ok, **f):
            self.chk.obs(
                "CSRNG-BUS-CMP",
                bit12=int(bool(recov & CS_BUS_CMP)),
                recov=f"0x{recov:x}",
                blk1=f["blk1"],
                blk2=f["blk2"],
            )
            await self._leg_cov("csrng_bus_cmp_replay")

    async def _vctr_wrap_leg(self) -> None:
        """CTRL-CSRNG-VCTR-WRAP and OBS-CSRNG-VCTR-WRAP: a Generate of two blocks
        across the wrap of V[31:0].

        With flag0 True and clen 12 the seed alone sets the instance
        (theory_of_operation.md:227) and no derivation function runs (README.md:47),
        so V = C XOR seed[127:0] with C fixed (SP 800-90A 10.2.1.3.1). Seed word 0 =
        C[31:0] XOR VCTR_PRE_WRAP puts block 1 at V[31:0] = 0xffffffff. The control:
        block 1 equals the golden block and the Generate acknowledges with
        ``CMD_STS`` = 0. Block 2 follows the increment of V[31:0] = 0xffffffff, which
        depends on ctr_len, and no document states ctr_len: it is logged with the
        ctr_len 32 and ctr_len 128 candidates and the one it matches. For every
        ctr_len the increment is modulo 2^ctr_len (SP 800-90A 10.2.1.5.1 step 4.1),
        so block 2 runs on a V other than block 1 under the same key and differs
        from it (CHK-CSRNG-VCTR-DISTINCT). The leg ends
        with an Uninstantiate. Runs after the bus compare leg, on its instance.
        """
        r = self.reg
        rest = SepSeededRng(self.plan.seed ^ VCTR_WRAP_SALT).getrandbits(KAT_SEED_BITS)
        rest &= ~0xFFFF_FFFF
        base = SepCtrDrbgGolden()
        base.instantiate(0, additional_input=rest)
        w0 = (base.v & 0xFFFF_FFFF) ^ VCTR_PRE_WRAP
        seed = rest | w0
        golden = SepCtrDrbgGolden()
        golden.instantiate(0, additional_input=seed)
        assert golden.v & 0xFFFF_FFFF == VCTR_PRE_WRAP, "counter-wrap seed: bench error"
        gold1 = golden.generate_one()
        cands = {}
        for ctr_len in VCTR_CTR_LENS:
            g = _CtrLenDrbg(ctr_len)
            g.instantiate(0, additional_input=seed)
            g.generate_one()
            cands[ctr_len] = g.generate_one()
        wrote_w0 = seed & 0xFFFF_FFFF
        f: dict = {"seed_w0": f"0x{wrote_w0:08x}", "expect_w0": f"0x{w0:08x}"}
        got: list[int] = []
        step = "uni"
        try:
            await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
            await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "vctr_uni")
            step = "ins"
            ins = cmd_word(ACMD_INSTANTIATE, clen=KAT_CLEN, flag0=MUBI_TRUE)
            await self._sw_cmd(ins, FIRST_CAP, "vctr_ins_rdy", wait_ack=False)
            for i in range(KAT_CLEN):
                await r._wr(CSRNG_CMD_REQ, (seed >> (32 * i)) & 0xFFFF_FFFF)
            await self._wait(CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "vctr_ins_ack")
            step = "gen"
            gen = cmd_word(ACMD_GENERATE, glen=VCTR_GLEN)
            await self._sw_cmd(gen, FIRST_CAP, "vctr_gen", wait_ack=False)
            for i in range(VCTR_GLEN * GEN1_WORDS):
                await self._wait(CSRNG_GENBITS_VLD, GB_VLD, GB_VLD, FIRST_CAP, f"vctr_vld{i}")
                got.append(await r._rd(CSRNG_GENBITS))
            _, gen_sts = await self._wait(
                CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "vctr_gen_ack"
            )
            f["gen_cmd_sts"] = _field(gen_sts, CS_STS_STS)
            step = "uni_end"
            await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "vctr_uni_end")
        except TrialTimeout as exc:
            f["reason"] = f"timeout:{exc.what} bound={exc.bound} step={step}"

        def _blk(words: list[int]) -> int:
            return sum(w << (32 * i) for i, w in enumerate(words))

        def _txt(block: int) -> list[str]:
            return [f"0x{(block >> (32 * i)) & 0xFFFF_FFFF:08x}" for i in range(GEN1_WORDS)]

        blk1 = _blk(got[:GEN1_WORDS]) if len(got) >= GEN1_WORDS else None
        f["block1"] = _txt(blk1) if blk1 is not None else "none"
        f["golden1"] = _txt(gold1)
        ok = blk1 == gold1 and f.get("gen_cmd_sts") == STS_SUCCESS and "reason" not in f
        if self.chk.ctrl("CSRNG-VCTR-WRAP", ok, **f):
            blk2 = _blk(got[GEN1_WORDS:])
            self._grade(
                "CSRNG-VCTR-DISTINCT",
                blk2 != blk1,
                block1=_txt(blk1),
                block2=_txt(blk2),
                expect="block2!=block1",
            )
            match = next((str(n) for n, c in cands.items() if c == blk2), "none")
            self.chk.obs(
                "CSRNG-VCTR-WRAP",
                block2=_txt(blk2),
                cand_ctr32=_txt(cands[32]),
                cand_ctr128=_txt(cands[BLOCK_LEN]),
                match=match,
            )
            await self._leg_cov("csrng_vctr_wrap")

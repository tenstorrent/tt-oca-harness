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
    automatically", edn.adoc:107). With ``MAX_NUM_REQS_BETWEEN_RESEEDS`` = 0 EDN
    issues no generate: "The reset value is `0`, which means no `generate` commands
    are issued." (``vendor/lowRISC/opentitan/upstream/hw/ip/edn/doc/
    theory_of_operation.md``:86). The commands it sends instead are logged only
    (``OBS-EDN-AUTO-ZERO``).
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
clocks); last, the reseed count N of the large-N auto sequence trial (64 to 128)
and, per ``CTRL`` field, six more invalid values distinct from the first (seven of
the fourteen invalid MuBi4 values per field per seed), then the 384-bit
additional data of the known-answer Update. The reserved
values 0x9 to 0xd carry a defined command code in bits [2:0]; the leaf sends 0x9 on
every seed in its last leg (no draw) and logs the result only. The checked values do
not depend on the seed; the known-answer checks compare with the golden of the
drawn seed and the drawn Update data.

The three groups run in the drawn order. Then the leaf runs, in this order, the
``CTRL`` alert leg (a TRNG reset, no bring-up), the command header leg, the
reseed leg, the auto leg (the first-command trial, the auto sequence trial with
N = 1 on every seed, the auto sequence trial with the drawn N, the large-N auto
sequence trial, the N = 0 trial), the instantiate-seed leg (a TRNG reset, ESRC configured with its
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
  CHK-CSRNG-CTRL-MUBI, CHK-EDN-CTRL-MUBI  per ``CTRL`` field and per drawn
                 invalid value (seven distinct values per field), a write of a
                 value other than 6 or 9 sets the field alert bit; after the
                 legal value is back, a write of 0 clears it. Each value is one
                 trial with its own check and coverage release. Control: the bit
                 reads 0 with the legal value, before the write.
  CHK-CSRNG-ACMD-INV  a drawn reserved acmd sets bit 13 and acks with ``CMD_STS``
                 = 1; a write of 0 clears bit 13. Control: bit 13 reads 0 after an
                 instantiate.
  OBS-CSRNG-ACMD-HI  after an instantiate, the reserved acmd 0x9 (word 0x909):
                 its ``CMD_STS`` and ``RECOV_ALERT_STS`` are logged, not graded
                 (see the 3-bit decode note above).
  CHK-CSRNG-FLAG0  an instantiate with an invalid value in flag0 [11:8] sets
                 bit 4; after an uninstantiate and an instantiate with flag0 0x9
                 (the field back to a legal value) that acknowledges with
                 ``CMD_STS`` 0, bit 4 still reads 1 and a write of 0 clears it.
                 No write of 0 to bit 4 comes between the invalid instantiate
                 and that read: the live probe writes 1 to bit 4, which leaves
                 it set. Control: bit 4 reads 0 after an instantiate with
                 flag0 0x9 and after one with flag0 0x6. After the graded clear,
                 an uninstantiate and a repeat of the invalid instantiate, a write
                 of 0 at its ack and the readback are logged only
                 (``OBS-CSRNG-FLAG0-HELD``): the text does not say whether a write
                 of 0 clears the bit while the field still holds the invalid
                 value.
  CHK-CSRNG-FLAG0-ACK  the invalid-flag0 instantiate acknowledges (``CMD_ACK``
                 = 1: a command completes "successfully or unsuccessfully",
                 theory_of_operation.md:286), and bit 4 still reads 1 at that
                 ack, before any write ("Writing a zero resets this status bit.",
                 csrng.rdl:371-373). Its ``CMD_STS`` is logged only
                 (``OBS-CSRNG-FLAG0-HELD``): the code table has no flag0 entry.
  CHK-CSRNG-UNINST-RESET  the instantiate after each Uninstantiate of the
                 header leg (after the reserved acmd, flag0 0x6; after the
                 invalid-flag0 instantiate, flag0 0x9) leaves bit 14 at 0: the
                 Uninstantiate "Resets an instance", the instance status bit is
                 cleared, "clearing any errors that it may have encountered due
                 to bad command syntax" (theory_of_operation.md:269-272), and bit
                 14 is set only for an instantiate "sent for a state that was
                 already instantiated" (csrng.rdl:397-398). Control
                 (``CTRL-CSRNG-UNINST-RESET``): before each Uninstantiate the
                 instance is instantiated: with bit 14 at 0, a probe instantiate
                 sets bit 14 (a probe that leaves it 0 instantiated the instance,
                 and one more probe follows; ``probes`` logs the count), and a
                 write of 0 to bit 14 only clears it again; bit 14 reads 0 before
                 each of the two graded instantiates; a 1 left by the
                 Uninstantiate (logged as ``raw_uni``) is cleared first by a write
                 of 0 to bit 14 only. The ``CMD_STS`` of each Uninstantiate is
                 logged only (``OBS-CSRNG-UNINST``).
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
                 ``MAX_NUM_REQS_BETWEEN_RESEEDS`` = N (N = 1, the drawn N of 2 to
                 4, then the drawn N of 64 to 128), the command headers on the EDN
                 to CSRNG port after the instantiate are exactly N generates, one
                 reseed and a generate (edn.adoc:107, :258-262). Control
                 (``CTRL-EDN-AUTO-TAP``): the first command on the port is the
                 software instantiate. The large-N trial pops the entropy pool
                 while it runs (STATUS, then as many pops as the level shows; never
                 a pop at level 0, ``hw/sys/sep/doc/entropy_pool.adoc``:31-32), so
                 EDN does not stall on full endpoint FIFOs. Control
                 (``CTRL-EDN-AUTO-INTERVAL``): before that trial CSRNG
                 ``RESEED_INTERVAL`` reads N or more; N "must be chosen smaller than
                 or equal to the value configured in the ``RESEED_INTERVAL``
                 register of CSRNG" (``vendor/lowRISC/opentitan/upstream/hw/ip/edn/
                 data/edn.hjson``:486), and the trial starts from a TRNG reset.
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
  CHK-EDN-AUTO-ZERO  with ``AUTO_REQ_MODE`` true and
                 ``MAX_NUM_REQS_BETWEEN_RESEEDS`` = 0, none of the first
                 AUTO_ZERO_HDRS (3) command headers on the EDN to CSRNG port after
                 the instantiate is a generate; a port with no handshake for 60000
                 clocks ends the watch early. Control (``CTRL-EDN-AUTO-ZERO``): the
                 first header on the port is the software instantiate, and
                 ``HW_CMD_STS.AUTO_MODE`` reads 1 after the watch (edn.adoc:213).
  CHK-CSRNG-HW-INST-EXC  the second instantiate through EDN is a sequencing error
                 on hardware instance 0: ``INTR_STATE.cs_hw_inst_exc`` reads 1
                 after it (theory_of_operation.md:425).
  CHK-CSRNG-HW-EXC-STS  after the same command ``HW_EXC_STS`` bit 0 reads 1
                 (csrng.rdl:327-332, bit 0 is HW0; architecture.adoc:58, EDN is on
                 port 0). Control for both (``CTRL-CSRNG-HW-EXC``): both read 0
                 after their clear, before the command, and bit 14 rose. Its
                 ``CMD_STS`` stays logged (``OBS-EDN-INVSEQ``), as does
                 ``HW_EXC_STS`` after the repeated software instantiate
                 (``OBS-CSRNG-INVSEQ``): the register names hardware instances
                 only.
  CHK-CSRNG-ACK-CLR  in the counter-wrap leg, ``CMD_ACK`` reads 0 between the
                 Instantiate header (clen 12) and its first data word ("It is set
                 to low each time a new command is written to !!CMD_REQ",
                 csrng.rdl:215). Control (``CTRL-CSRNG-ACK-CLR``): it reads 1 after
                 the Uninstantiate acknowledge, before the header. The first read
                 after a command write in the software legs stays logged
                 (``OBS-CSRNG-ACK0``, ``OBS-EDN-ACK0``): ``CMD_ACK`` is 0 before
                 those writes and no text states the acknowledge latency.
  CHK-DRBG-FIPS-PROV  the FIPS/CC flag of the words follows flag0 of the
                 instance that made them. flag0 True "will render the instance
                 non-FIPS compliant until it is re-instantiated"
                 (theory_of_operation.md:217), ``GENBITS_FIPS`` "is set when
                 genbits are FIPS/CC compliant" (csrng.hjson:459), and the SEP
                 seed adapter attaches the provisional flag 1, forwarded to each
                 endpoint (``hw/sys/sep/doc/trng.adoc``:138-141). Graded legs:
                 ``GENBITS_FIPS`` at the first ``GENBITS_VLD`` read with
                 ``GENBITS_VLD`` = 1 reads 1 after a flag0-False software
                 instantiate (a Generate in the CSRNG software leg; the first
                 Generate of the reseed leg) and 0 after each flag0-True
                 known-answer instantiate (reseed leg, bus compare leg);
                 ``pool_edn_fips_o`` reads 0 on every pool handshake
                 (``pool_edn_req_o`` and ``pool_edn_ack_o``) from the EDN enable
                 of the reference boot (``BOOT_INS_CMD`` 0x601, flag0 True) to the
                 first one, and 1 on every pool handshake of the large-N auto
                 trial (EDN instance from the 0x901 instantiate). Each pool leg
                 needs one handshake or more. Control (``CTRL-DRBG-FIPS-PROV``):
                 before each leg ``FIPS_FORCE`` reads its reset value and
                 ``CTRL.FIPS_FORCE_ENABLE`` reads False, so no force applies
                 (csrng.hjson ``FIPS_FORCE``: the force needs
                 ``CTRL.FIPS_FORCE_ENABLE`` True).
  CHK-CSRNG-UPDATE  in the reseed leg, after Generate K + 1 was refused and bit
                 15 cleared: an Update (acmd 0x4, clen 1, flag0 False, one data
                 word) acknowledges with ``CMD_STS`` = 0, ``GENBITS_VLD`` reads 0
                 after it, and the next Generate acknowledges with ``CMD_STS`` = 4
                 and bit 15 at 1; a write of 0 then clears bit 15. The Update
                 "does the same function as the Reseed command, except that: ...
                 only the additional data provided will be used ... the Update
                 command does not reset the reseed counter"
                 (theory_of_operation.md:255-263), so the counter stays at K or
                 more. Control (``CTRL-CSRNG-UPDATE``): Generate K + 1 was
                 refused, and ``GENBITS`` was read until ``GENBITS_VLD`` read 0
                 before the Update. Leg ``known_answer``, after the reseed-leg
                 window closed: an Instantiate with flag0 True and clen 12 of the
                 known-answer seed, an Update with clen 12 of the drawn 384-bit
                 additional data, and one Generate (glen 1). All three acknowledge
                 with ``CMD_STS`` = 0, and the four ``GENBITS`` words equal the
                 first block of the SP 800-90A CTR_DRBG golden after the update
                 function on that data (theory_of_operation.md:255-263,
                 programmers_guide.md:37-61, hw/ip/drbg/doc/architecture.adoc:14).
                 Control (``CTRL-CSRNG-UPDATE``, leg ``known_answer``): that golden
                 block differs from the golden block without the Update, and
                 ``GENBITS_VLD`` reads 0 before the Instantiate.
  CHK-CSRNG-UNINST-REFUSE  a Generate (glen 1) to a software instance that is
                 not instantiated acknowledges with ``CMD_STS`` = 3
                 (INVALID_CMD_SEQ: "a command other than Instantiate was issued
                 without sending an Instantiate command first", csrng.hjson
                 :427-433), sets bit 14 ("any command other than instantiate is
                 sent for a state that wasn't instantiated yet. The invalid command
                 is ignored", csrng.hjson:670-675), returns no ``GENBITS`` word
                 before the acknowledge, leaves ``GENBITS_VLD`` at 0, and a write
                 of 0 clears bit 14. Two legs of the reseed leg: before
                 its first Instantiate, and after the known-answer Generate and an
                 Uninstantiate (the Uninstantiate "Resets an instance", its status
                 bit cleared, theory_of_operation.md:269-272). Bit 15 is logged.
                 Control (``CTRL-CSRNG-UNINST-REFUSE``): bit 14 and
                 ``GENBITS_VLD`` read 0 before each refused Generate.
  CHK-CSRNG-ENTROPY-REQ  in the CSRNG software leg, with EDN not enabled since
                 the clean start, ``INTR_STATE.cs_entropy_req`` reads 1 after the
                 acknowledge of the flag0-False instantiate: it asserts "whenever
                 the instance requests entropy from ENTROPY_SRC" in non-deterministic
                 mode (programmers_guide.md:19; theory_of_operation.md:423).
                 Control (``CTRL-CSRNG-ENTROPY-REQ``): the bit reads 0 after a write
                 of 1 before that instantiate, and in the reseed leg it reads 0
                 after a write of 1 and the flag0-True known-answer instantiate,
                 which uses "Only provided additional data" as seed
                 (theory_of_operation.md:227).
  OBS-CSRNG-UNINST-STATE  with ``CTRL.READ_INT_STATE`` True, the 14
                 ``INT_STATE_VAL`` words of each ``INT_STATE_NUM`` index, before
                 and after the Uninstantiate of the second refusal leg, as a
                 non-zero flag and a digest. The Uninstantiate zeroes the instance
                 values (theory_of_operation.md:270), but the read also needs the
                 OTP read gate (csrng.hjson:560-563), whose SEP value and the
                 software instance index are not stated, so a 0 read does not show
                 the zeroing.
  OBS-EDN-ENDPOINT  per EDN mode, the endpoint pushes on
                 ``drbg_adapter_push_o`` (count per endpoint, the order of the
                 first sixteen): boot, from the EDN enable of the reference boot to
                 the first pool handshake; auto, the large-N trial from the
                 software instantiate to its last header. No text states which
                 requesting endpoint EDN serves first.
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
from env.sep_chk_log import SepChkLog, word_digest
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
from sep_base_test import sep_base_test
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_drbg_mode_bringup_seq import drbg_bring_up
from seq_lib.sep_entropy_pool_seq import POOL_POP, RESP_OKAY, SepEntropyPool, pool_level
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
# EDN is on CSRNG hardware application port 0 (hw/ip/drbg/doc/architecture.adoc:58), and
# HW_EXC_STS bit 0 is instance HW0 (csrng.rdl HW_EXC_STS).
EDN_CSRNG_APP = 0
CS_HW_EXC_EDN = 1 << (CSRNG.fields("HW_EXC_STS")["HW_EXC_STS"]["bp"] + EDN_CSRNG_APP)
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
CSRNG_CTRL_READ_STATE = CSRNG.value(
    "CTRL", ENABLE=MUBI_TRUE, SW_APP_ENABLE=MUBI_TRUE, READ_INT_STATE=MUBI_TRUE
)

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
GB_FIPS = CSRNG.fields("GENBITS_VLD")["GENBITS_FIPS"]["bm"]
CS_ENTROPY_REQ = CSRNG.fields("INTR_STATE")["CS_ENTROPY_REQ"]["bm"]
RESEED_INTERVAL_RESET = CSRNG.reset("RESEED_INTERVAL")
# FIPS/CC flag force (csrng.hjson FIPS_FORCE): one bit per instance, effective only
# with CTRL.FIPS_FORCE_ENABLE True.
CSRNG_FIPS_FORCE = sym("CSRNG_FIPS_FORCE_REG_ADDR")
FIPS_FORCE_RESET = CSRNG.reset("FIPS_FORCE")
CS_FIPS_FORCE_EN = CSRNG.fields("CTRL")["FIPS_FORCE_ENABLE"]
# FIPS/CC flag of words from an instance: flag0 True makes the instance non-FIPS
# (theory_of_operation.md:217); the SEP seed adapter marks its seeds FIPS
# (hw/sys/sep/doc/trng.adoc:138-141).
FIPS_FLAG0_TRUE = 0
FIPS_FLAG0_FALSE = 1
# Internal state readback (csrng.hjson INT_STATE_NUM, INT_STATE_VAL): "the internal
# state field is 448 bits wide, it will require 14 reads".
CSRNG_INT_STATE_NUM = sym("CSRNG_INT_STATE_NUM_REG_ADDR")
CSRNG_INT_STATE_VAL = sym("CSRNG_INT_STATE_VAL_REG_ADDR")
INT_STATE_WORDS = 448 // 32
# The observation walks every instance index of FIPS_FORCE (one bit per instance)
# and one more: the index of the software instance is not stated.
INT_STATE_IDX = range(CSRNG.fields("FIPS_FORCE")["FIPS_FORCE"]["bw"] + 1)
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
# Invalid values per CTRL field per seed: half of MUBI_INVALID, so the field x value
# coverage cross closes over merged regressions.
MUBI_PER_FIELD = 7

# Command header (theory_of_operation.md:156-188) and application commands (:211-279).
ACMD_INSTANTIATE = 0x1
ACMD_RESEED = 0x2
ACMD_GENERATE = 0x3
ACMD_UPDATE = 0x4
ACMD_UNINSTANTIATE = 0x5
# The Update of the reseed leg carries one additional-data word: "only the additional
# data provided will be used" (theory_of_operation.md:255-263).
UPDATE_CLEN = 1
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
STS_INVALID_CMD_SEQ = 3
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
# Reseed count of the large-N auto sequence trial. With it the endpoint FIFOs and
# the pool fill before the reseed, so the trial pops the pool while it runs.
AUTO_N_BIG_LO = 64
AUTO_N_BIG_HI = 128
# Clocks between pool STATUS reads while the pool level reads 0.
POOL_EMPTY_WAIT = 16
# Endpoint pushes whose order OBS-EDN-ENDPOINT logs.
EP_SEQ_LEN = 16
# Headers after the instantiate that the MAX_NUM_REQS_BETWEEN_RESEEDS = 0 trial reads.
# The first-command trial sees its generate as the first of them.
AUTO_ZERO_HDRS = 3
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
    auto_n_big: int
    cs_mubi: tuple[tuple[int, ...], ...]
    ed_mubi: tuple[tuple[int, ...], ...]
    upd_data: int

    def describe(self) -> str:
        def _vals(per_field: tuple[tuple[int, ...], ...]) -> list[list[str]]:
            return [[hex(v) for v in field] for field in per_field]

        return (
            f"groups={','.join(self.groups)} gaps[0:8]={list(self.gaps[:8])}"
            f" cs_bad={[hex(v) for v in self.cs_bad]} ed_bad={[hex(v) for v in self.ed_bad]}"
            f" bad_flag0=0x{self.bad_flag0:x} bad_acmd=0x{self.bad_acmd:x}"
            f" reseed_k={self.reseed_k} gen_off=0x{self.gen_off:x}"
            f" kat_seed_sha={word_digest(self.kat_seed)}"
            f" auto_n={self.auto_n} inst_hold={self.inst_hold}"
            f" auto_n_big={self.auto_n_big}"
            f" cs_mubi={_vals(self.cs_mubi)} ed_mubi={_vals(self.ed_mubi)}"
            f" upd_data_sha={word_digest(self.upd_data)}"
        )


def _mubi_values(rng: SepSeededRng, first: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    """Per field, ``first`` then MUBI_PER_FIELD - 1 other distinct invalid values."""
    return tuple(
        (b, *rng.sample([v for v in MUBI_INVALID if v != b], MUBI_PER_FIELD - 1)) for b in first
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
    auto_n_big = rng.randrange(AUTO_N_BIG_LO, AUTO_N_BIG_HI + 1)
    cs_mubi = _mubi_values(rng, cs_bad)
    ed_mubi = _mubi_values(rng, ed_bad)
    upd_data = rng.getrandbits(KAT_SEED_BITS)
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
        auto_n_big,
        cs_mubi,
        ed_mubi,
        upd_data,
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


class _EdnTap:
    """Per-clock record of the EDN outputs on the pool port and the endpoint pushes.

    A pool handshake is a clock with ``pool_edn_req_o`` and ``pool_edn_ack_o`` both
    1; its ``pool_edn_fips_o`` counts under 0, 1 or ``"x"`` (an unknown tag is
    never read as 0 or 1). Each set bit of ``drbg_adapter_push_o`` is one endpoint
    push: ``per_ep`` counts them per endpoint and ``seq`` keeps the endpoint index
    of the first EP_SEQ_LEN pushes. ``halt`` ends the record at the next clock edge
    without a wait; ``stop`` halts and waits for the loop, which leaves outside the
    ReadOnly phase.
    """

    def __init__(self, test) -> None:
        self.t = test
        self.pool_hs = 0
        self.pool_fips: dict[int | str, int] = {0: 0, 1: 0, "x": 0}
        self.per_ep = [0] * len(cocotb.top.drbg_adapter_push_o)
        self.seq: list[int] = []
        self._run = True
        self._task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        dut = cocotb.top
        rd = self.t.rd
        while True:
            await RisingEdge(dut.clk_i)
            if not self._run:
                break
            await ReadOnly()
            push = rd(dut.drbg_adapter_push_o, allow_unknown=True)
            for ep in range(len(self.per_ep)):
                if (push >> ep) & 1:
                    self.per_ep[ep] += 1
                    if len(self.seq) < EP_SEQ_LEN:
                        self.seq.append(ep)
            if rd(dut.pool_edn_req_o, allow_unknown=True) and rd(
                dut.pool_edn_ack_o, allow_unknown=True
            ):
                self.pool_hs += 1
                try:
                    self.pool_fips[rd(dut.pool_edn_fips_o)] += 1
                except AssertionError:
                    self.pool_fips["x"] += 1

    def halt(self) -> None:
        self._run = False

    async def stop(self) -> None:
        self._run = False
        await self._task

    def endpoint_fields(self) -> dict:
        return {"pushes": sum(self.per_ep), "per_ep": list(self.per_ep), "seq": list(self.seq)}


class _PoolDrain:
    """Entropy-pool reader that keeps EDN generating while a trial runs.

    The loop reads the pool STATUS and pops as many words as its level shows. It
    never pops at level 0: an empty pop returns SLVERR
    (``hw/sys/sep/doc/entropy_pool.adoc``:31-32). ``halt`` ends the loop after the
    access in flight; ``join`` waits for it.
    """

    def __init__(self, test) -> None:
        self.pool = SepEntropyPool(test)
        self.pops = 0
        self.pop_errors = 0
        self.status_reads = 0
        self._run = True
        self._task = cocotb.start_soon(self._drain())

    async def _drain(self) -> None:
        while self._run:
            level = pool_level(await self.pool.status())
            self.status_reads += 1
            if not level:
                await ClockCycles(cocotb.top.clk_i, POOL_EMPTY_WAIT)
                continue
            for _ in range(level):
                if not self._run:
                    break
                seq = await self.pool.access(POOL_POP)
                if seq.resp_code == RESP_OKAY:
                    self.pops += 1
                else:
                    self.pop_errors += 1

    def halt(self) -> None:
        self._run = False

    async def join(self) -> None:
        await self._task

    def fields(self) -> dict:
        return {
            "pool_pops": self.pops,
            "pool_pop_errors": self.pop_errors,
            "pool_status_reads": self.status_reads,
        }


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
        "CHK-CSRNG-HW-INST-EXC",
        "CHK-CSRNG-HW-EXC-STS",
        "CHK-EDN-AUTO-ZERO",
        "CHK-CSRNG-FLAG0-ACK",
        "CHK-CSRNG-UNINST-RESET",
        "CHK-CSRNG-ACK-CLR",
        "CHK-DRBG-FIPS-PROV",
        "CHK-CSRNG-UPDATE",
        "CHK-CSRNG-UNINST-REFUSE",
        "CHK-CSRNG-ENTROPY-REQ",
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

    # --- FIPS/CC flag provenance ----------------------------------------------------
    async def _fips_force_pre(self) -> dict:
        """``FIPS_FORCE`` and ``CTRL.FIPS_FORCE_ENABLE`` read before a FIPS leg."""
        force = await self.reg._rd(CSRNG_FIPS_FORCE)
        enable = _field(await self.reg._rd(CSRNG_CTRL), CS_FIPS_FORCE_EN)
        return {"fips_force": force, "fips_force_enable": enable}

    def _fips_grade(self, leg: str, pre: dict, ok: bool, **fields) -> None:
        """CTRL-DRBG-FIPS-PROV (no force applies), then CHK-DRBG-FIPS-PROV of ``leg``."""
        force = pre.get("fips_force")
        enable = pre.get("fips_force_enable")
        self.chk.ctrl(
            "DRBG-FIPS-PROV",
            force == FIPS_FORCE_RESET and enable == MUBI_FALSE,
            leg=leg,
            fips_force="na" if force is None else f"0x{force:x}",
            fips_force_enable="na" if enable is None else f"0x{enable:x}",
            expected_fips_force=f"0x{FIPS_FORCE_RESET:x}",
            expected_fips_force_enable=f"0x{MUBI_FALSE:x}",
        )
        self.chk.ok("DRBG-FIPS-PROV", ok, leg=leg, **fields)

    def _fips_genbits_grade(
        self, leg: str, pre: dict, fips: int | None, expected: int, reason: str = ""
    ) -> None:
        """``GENBITS_FIPS`` at the first ``GENBITS_VLD`` read with ``GENBITS_VLD`` = 1."""
        f: dict = {"genbits_fips": "na" if fips is None else fips, "expected": expected}
        if reason:
            f["reason"] = reason
        self._fips_grade(leg, pre, not reason and fips == expected, **f)

    def _fips_kat_grade(self, leg: str, kat: dict) -> None:
        """``GENBITS_FIPS`` of a known-answer Generate (flag0-True instance)."""
        pre = {k: kat.get(k) for k in ("fips_force", "fips_force_enable")}
        self._fips_genbits_grade(leg, pre, kat.get("genbits_fips"), FIPS_FLAG0_TRUE)

    def _fips_pool_grade(self, leg: str, pre: dict, tap: _EdnTap, expected: int, **extra) -> None:
        """``pool_edn_fips_o`` on every pool handshake ``tap`` recorded; one or more."""
        f = {
            "handshakes": tap.pool_hs,
            "fips0": tap.pool_fips[0],
            "fips1": tap.pool_fips[1],
            "fips_x": tap.pool_fips["x"],
            "expected": expected,
            **extra,
        }
        self._fips_grade(leg, pre, tap.pool_hs >= 1 and tap.pool_fips[expected] == tap.pool_hs, **f)

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
        only for that one edge, and only after a PASS. The tap halts after that edge
        on both paths, so its record holds the clock of the last handshake and the
        clock after it.

        For ``n`` above AUTO_N_HI (the large-N trial) the trial reads CSRNG
        ``RESEED_INTERVAL`` first (``CTRL-EDN-AUTO-INTERVAL``), records the pool
        port and the endpoint pushes from the instantiate up to and including the
        clock edge that takes the last header (``CHK-DRBG-FIPS-PROV`` leg
        ``edn_auto``, ``OBS-EDN-ENDPOINT`` mode ``auto``), and pops the pool from the
        instantiate write to the last header.
        """
        dut = cocotb.top
        r = self.reg
        big = n > AUTO_N_HI
        max_reqs = n
        await self._auto_setup(f"seq{n}", max_reqs)
        fips_pre: dict = {}
        if big:
            interval = await r._rd(CSRNG_RESEED_INTERVAL)
            self.chk.ctrl(
                "EDN-AUTO-INTERVAL",
                interval >= n,
                n=n,
                reseed_interval=f"0x{interval:x}",
                expected_reset=f"0x{RESEED_INTERVAL_RESET:x}",
            )
            fips_pre = await self._fips_force_pre()
        await r._wr(EDN_CTRL, _edn_ctrl(False, True, True))
        rdy = ED_STS_REG_RDY | ED_STS_RDY
        reseed_word = cmd_word(ACMD_RESEED)
        want = [CMD_GENERATE_1] * n + [reseed_word, CMD_GENERATE_1]
        hdrs: list[int] = []
        reason = ""
        watch = None
        tap = None
        drain = None
        try:
            await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, f"auto_seq{n}_rdy")
            watch = cocotb.start_soon(self._edn_cmd_watch(1 + len(want), AUTO_CAP))
            if big:
                tap = _EdnTap(self)
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            if big:
                drain = _PoolDrain(self)
            hdrs, reason = await watch
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
            if watch is not None:
                watch.cancel()
        if drain is not None:
            drain.halt()
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
        elif tap is not None:
            await RisingEdge(dut.clk_i)
            await FallingEdge(dut.clk_i)
        if tap is not None:
            tap.halt()
        if big:
            await self._auto_big_grade(fips_pre, tap, drain)
        await self._release()
        await r._wr(EDN_CTRL, _edn_ctrl(False, False, False))

    async def _auto_big_grade(
        self, fips_pre: dict, tap: _EdnTap | None, drain: _PoolDrain | None
    ) -> None:
        """The pool-tag leg and the endpoint log of the large-N trial, after the
        drain and the tap have stopped (no register access of the drain is left)."""
        extra: dict = {}
        if drain is not None:
            await drain.join()
            extra = drain.fields()
        if tap is None:
            self.chk.blocked("DRBG-FIPS-PROV", "edn_auto: the trial ended before the instantiate")
            return
        await tap.stop()
        self._fips_pool_grade("edn_auto", fips_pre, tap, FIPS_FLAG0_FALSE, **extra)
        self.chk.obs("EDN-ENDPOINT", mode="auto", **tap.endpoint_fields())

    async def _auto_trial(self, kind: str, max_reqs: int) -> tuple[int, int]:
        """One auto-mode session. Returns (AUTO_MODE before the instantiate, HW_CMD_STS)."""
        self._auto_done = None
        self._auto_done_pre = None
        await self._auto_setup(kind, max_reqs)
        await self.reg._wr(EDN_INTR_STATE, ED_DONE)
        self._auto_done_pre = int(bool(await self.reg._rd(EDN_INTR_STATE) & ED_DONE))
        open_graded_window(TEST, self.logger)
        await self.reg._wr(EDN_CTRL, _edn_ctrl(False, True, True))
        pre = await self.reg._rd(EDN_HW_CMD_STS)
        rdy = ED_STS_REG_RDY | ED_STS_RDY
        await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, f"auto_{kind}_rdy")
        await self.reg._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
        await self._wait(EDN_SW_CMD_STS, ED_STS_ACK, ED_STS_ACK, FIRST_CAP, f"auto_{kind}_sw_ack")
        self._auto_done = int(bool(await self.reg._rd(EDN_INTR_STATE) & ED_DONE))
        hw = await self._auto_hw(f"auto_{kind}")
        close_graded_window(self.logger)
        await self._main_sm("edn_auto")
        await self.reg._wr(EDN_CTRL, _edn_ctrl(False, False, False))
        return int(bool(pre & ED_AUTO_MODE)), hw

    async def _auto_zero_trial(self) -> None:
        """CHK-EDN-AUTO-ZERO with MAX_NUM_REQS_BETWEEN_RESEEDS = 0, its reset value:
        "The reset value is `0`, which means no `generate` commands are issued."
        (edn theory_of_operation.md:86).

        The watch records the command headers on the EDN to CSRNG port after the
        software instantiate, until AUTO_ZERO_HDRS headers or AUTO_CAP clocks with
        no handshake. No header may carry the Generate acmd. Control
        (``CTRL-EDN-AUTO-ZERO``): the first header is the software instantiate, so
        the watch sees the port, and ``HW_CMD_STS.AUTO_MODE`` reads 1 after the
        watch ("0b1: The EDN is in the hardware controlled part of auto mode.",
        edn.adoc:213), so a quiet port is not an EDN that never left software
        port mode. The headers EDN sends are logged
        (``OBS-EDN-AUTO-ZERO``): no text states them for the value 0. The trial
        opens no coverage window, so the check has its own release.
        """
        dut = cocotb.top
        r = self.reg
        await self._auto_setup("zero", 0)
        await r._wr(EDN_CTRL, _edn_ctrl(False, True, True))
        rdy = ED_STS_REG_RDY | ED_STS_RDY
        hdrs: list[int] = []
        reason = ""
        watch = None
        try:
            await self._wait(EDN_SW_CMD_STS, rdy, rdy, FIRST_CAP, "auto_zero_rdy")
            watch = cocotb.start_soon(self._edn_cmd_watch(1 + AUTO_ZERO_HDRS, AUTO_CAP))
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            hdrs, reason = await watch
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
            if watch is not None:
                watch.cancel()
        await FallingEdge(dut.clk_i)
        first = hdrs[0] if hdrs else None
        seq = hdrs[1:]
        # A quiet port after the instantiate ends the watch with no generate seen.
        quiet = reason.startswith("timeout:edn_cmd") and first is not None
        hw = await r._rd(EDN_HW_CMD_STS)
        f = {
            "max_num_reqs": 0,
            "first_word": "na" if first is None else f"0x{first:x}",
            "headers": len(seq),
            "acmds": [decode_hdr(w)["acmd"] for w in seq],
            "generates": sum(decode_hdr(w)["acmd"] == ACMD_GENERATE for w in seq),
            "expected_generates": 0,
            "end": reason or "headers",
            "auto_mode": int(bool(hw & ED_AUTO_MODE)),
            "expected_auto_mode": 1,
        }
        self.chk.ctrl("EDN-AUTO-ZERO", first == CMD_INSTANTIATE and f["auto_mode"] == 1, **f)
        self.chk.ok(
            "EDN-AUTO-ZERO",
            (not reason or quiet) and first == CMD_INSTANTIATE and f["generates"] == 0,
            **f,
        )
        self.chk.obs(
            "EDN-AUTO-ZERO",
            words=[f"0x{w:x}" for w in seq],
            hw_type=_field(hw, ED_HW_TYPE),
            hw_boot=int(bool(hw & ED_BOOT_MODE)),
            hw_ack=int(bool(hw & ED_HW_ACK)),
        )
        await self._release()
        await self._main_sm("edn_auto")
        await r._wr(EDN_CTRL, _edn_ctrl(False, False, False))

    async def _auto_leg(self) -> None:
        """The first hardware command with MAX_NUM_REQS = 1, the command sequence with
        N = 1, the drawn N and the drawn large N, then MAX_NUM_REQS = 0 (no
        generate)."""
        gen_pre = None
        gen_hw = None
        reason = ""
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
        await self._auto_seq_trial(self.plan.auto_n_big)
        await self._auto_zero_trial()

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
        noise = self.start_esrc_noise_driver()
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

    async def _boot_pool_grade(self, tap: _EdnTap, fips_pre: dict, booted: bool) -> None:
        """CHK-DRBG-FIPS-PROV leg ``edn_boot`` and OBS-EDN-ENDPOINT mode ``boot``.

        After the reference boot read ``BOOT_MODE``, wait at most FIRST_CAP clocks
        for the first pool handshake; every pool handshake from the EDN enable to
        that point carries the flag of the flag0-True boot instance (0x601)."""
        if not booted:
            await tap.stop()
            self.chk.blocked("DRBG-FIPS-PROV", "edn_boot: the reference boot showed no BOOT_MODE")
            return
        waited = 0
        while not tap.pool_hs and waited < FIRST_CAP:
            await RisingEdge(cocotb.top.clk_i)
            waited += 1
        await tap.stop()
        extra: dict = {"waited_clk": waited}
        if not tap.pool_hs:
            extra["reason"] = f"timeout:pool_handshake bound={FIRST_CAP}"
        self._fips_pool_grade("edn_boot", fips_pre, tap, FIPS_FLAG0_TRUE, **extra)
        self.chk.obs("EDN-ENDPOINT", mode="boot", **tap.endpoint_fields())

    async def _boot_group(self) -> None:
        await self._clean_start("boot_ref")
        fips_pre = await self._fips_force_pre()
        tap = _EdnTap(self)
        t0, sts, ctrl, _ = await self._boot(auto=False, bound=FIRST_CAP, graded=False)
        await self._boot_pool_grade(tap, fips_pre, t0 is not None)
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
        # Before the second instantiate: HW_EXC_STS written 0 and cs_hw_inst_exc
        # written 1 (W1C), both read back, so a 1 after it comes from that command.
        await r._wr(CSRNG_HW_EXC_STS, 0)
        await r._wr(CSRNG_INTR_STATE, CS_HW_INST_EXC)
        exc_pre = {
            "pre_hw_exc": await r._rd(CSRNG_HW_EXC_STS),
            "pre_hw_inst_exc": int(bool(await r._rd(CSRNG_INTR_STATE) & CS_HW_INST_EXC)),
        }
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
        hw_exc = await r._rd(CSRNG_HW_EXC_STS)
        hw_inst_exc = int(bool(await r._rd(CSRNG_INTR_STATE) & CS_HW_INST_EXC))
        self.chk.obs(
            "EDN-INVSEQ",
            cmd_ack=int(bool(sts & ED_STS_ACK)),
            cmd_sts=_field(sts, ED_STS_STS),
            ack_err=int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR)),
            hw_exc=f"0x{hw_exc:x}",
            hw_inst_exc=hw_inst_exc,
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
        await self._hw_exc_grade(exc_pre, hw_exc, hw_inst_exc, invseq, reason)

    async def _hw_exc_grade(
        self, pre: dict, hw_exc: int, hw_inst_exc: int, invseq: int, reason: str
    ) -> None:
        """CHK-CSRNG-HW-INST-EXC and CHK-CSRNG-HW-EXC-STS for the second instantiate
        through EDN, a command sequencing error on the hardware instance of EDN.

        "The `cs_hw_inst_exc` interrupt will assert when any of the
        hardware-controlled CSRNG instances encounters an exception while executing a
        command, either due to errors on the command sequencing" (csrng
        theory_of_operation.md:425): ``INTR_STATE.cs_hw_inst_exc`` reads 1.
        ``HW_EXC_STS`` "indicates whether one of the CSRNG HW instances has
        encountered an exception", "bit 0 corresponding to instance HW0"
        (csrng.rdl:327-332), and EDN is on hardware application port 0
        (hw/ip/drbg/doc/architecture.adoc:58): bit 0 reads 1. Control
        (``CTRL-CSRNG-HW-EXC``): both read 0 after their clear, before the command,
        and bit 14 shows that the command was the sequencing error. The second
        instantiate runs with the coverage window closed, so these checks have
        their own release.
        """
        f = {
            **pre,
            "invseq": invseq,
            "hw_exc": f"0x{hw_exc:x}",
            "hw_inst_exc": hw_inst_exc,
        }
        if reason:
            f["reason"] = reason
        self.chk.ctrl(
            "CSRNG-HW-EXC",
            not pre["pre_hw_exc"] & CS_HW_EXC_EDN and pre["pre_hw_inst_exc"] == 0 and invseq == 1,
            **f,
        )
        self.chk.ok("CSRNG-HW-INST-EXC", not reason and hw_inst_exc == 1, **f, expected=1)
        self.chk.ok(
            "CSRNG-HW-EXC-STS",
            not reason and bool(hw_exc & CS_HW_EXC_EDN),
            **f,
            expected_bit=f"0x{CS_HW_EXC_EDN:x}",
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
        # cs_entropy_req (W1C) reads 0 before the flag0-False instantiate, so a 1 at
        # its acknowledge comes from that instantiate.
        await r._wr(CSRNG_INTR_STATE, CS_ENTROPY_REQ)
        ent_pre = int(bool(await r._rd(CSRNG_INTR_STATE) & CS_ENTROPY_REQ))
        ent = None
        fips_pre = await self._fips_force_pre()
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
            ent = int(bool(state & CS_ENTROPY_REQ))
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
        # The instance is still instantiated with flag0 False (the repeated
        # instantiate is ignored), so one Generate gives the FIPS/CC flag of its words.
        fips = None
        fips_reason = ""
        if not reason:
            fips, fips_reason = await self._sw_fips_generate("csrng_sw_fips")
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
        if ent is None:
            self.chk.blocked("CSRNG-ENTROPY-REQ", f"no instantiate acknowledge: {reason}")
        else:
            self.chk.ctrl("CSRNG-ENTROPY-REQ", ent_pre == 0, leg="csrng_sw", ent_pre=ent_pre)
            self.chk.ok(
                "CSRNG-ENTROPY-REQ",
                ent == 1,
                word=f"0x{CMD_INSTANTIATE:x}",
                cs_entropy_req=ent,
                expected=1,
                ent_pre=ent_pre,
            )
        if reason:
            self.chk.blocked("DRBG-FIPS-PROV", f"csrng_sw_flag0_false: {reason}")
        else:
            self._fips_genbits_grade(
                "csrng_sw_flag0_false", fips_pre, fips, FIPS_FLAG0_FALSE, fips_reason
            )
        await self._release()

    async def _sw_fips_generate(self, what: str) -> tuple[int | None, str]:
        """One Generate (glen 1) on the instantiated software instance, with
        ``GENBITS_VLD`` read 0 first. Returns ``GENBITS_FIPS`` of the first
        ``GENBITS_VLD`` read with ``GENBITS_VLD`` = 1, and a reason when a wait
        timed out or ``GENBITS_VLD`` was not 0 before the Generate. The four words
        are read and the acknowledge is awaited."""
        r = self.reg
        try:
            if await r._rd(CSRNG_GENBITS_VLD) & GB_VLD:
                return None, "genbits_vld_before_generate"
            await self._sw_cmd(CMD_GENERATE_1, FIRST_CAP, f"{what}_gen", wait_ack=False)
            fips = None
            for i in range(GEN1_WORDS):
                _, vld = await self._wait(
                    CSRNG_GENBITS_VLD, GB_VLD, GB_VLD, FIRST_CAP, f"{what}_vld{i}"
                )
                if fips is None:
                    fips = int(bool(vld & GB_FIPS))
                await r._rd(CSRNG_GENBITS)
            await self._wait(CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, f"{what}_ack")
        except TrialTimeout as exc:
            return None, f"timeout:{exc.what} bound={exc.bound}"
        return fips, ""

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
        """CHK-CSRNG-CTRL-MUBI and CHK-EDN-CTRL-MUBI, one trial per CTRL field and
        drawn invalid value. Each trial holds its field alert coverage sample in its
        own window and releases it after its check."""
        close_graded_window(self.logger)
        await self._trng_reset()
        units = (
            (
                "CSRNG-CTRL-MUBI",
                CSRNG,
                CSRNG_CTRL,
                CSRNG_RECOV_ALERT_STS,
                CS_CTRL_ALERT,
                self.plan.cs_mubi,
            ),
            ("EDN-CTRL-MUBI", EDN, EDN_CTRL, EDN_RECOV_ALERT_STS, ED_CTRL_ALERT, self.plan.ed_mubi),
        )
        for name, meta, ctrl_addr, recov_addr, alerts, per_field in units:
            legal = meta.value("CTRL", **{f: MUBI_FALSE for f in alerts})
            for (field, bit), values in zip(alerts.items(), per_field):
                for value in values:
                    await self._ctrl_mubi_trial(
                        name, meta, ctrl_addr, recov_addr, alerts, legal, field, bit, value
                    )

    async def _ctrl_mubi_trial(
        self,
        name: str,
        meta,
        ctrl_addr: int,
        recov_addr: int,
        alerts: dict[str, int],
        legal: int,
        field: str,
        bit: int,
        value: int,
    ) -> None:
        r = self.reg
        open_graded_window(TEST, self.logger)
        await r._wr(ctrl_addr, legal)
        pre = int(bool(await r._rd(recov_addr) & bit))
        self.chk.ctrl(
            name, pre == 0, field=field, value=f"0x{value:x}", legal=f"0x{legal:x}", alert_pre=pre
        )
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

    async def _sw_generate(self, bound: int) -> tuple[int, int, int, int | None]:
        """One Generate of one 128-bit block. Reads GENBITS while GENBITS_VLD is 1
        until CMD_ACK, so the acknowledge can follow the data. Returns
        ``(CMD_STS, RECOV_ALERT_STS at the ack, words read, first GENBITS_VLD read
        with GENBITS_VLD = 1 or None)``."""
        r = self.reg
        await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, bound, "gen_rdy")
        await r._wr(CSRNG_CMD_REQ, CMD_GENERATE_1)
        t0 = self._now()
        words = 0
        first_vld = None
        while True:
            sts = await self._reader(CSRNG_SW_CMD_STS)()
            if sts & CS_STS_ACK:
                break
            if self._now() - t0 > bound:
                raise TrialTimeout("gen_ack", bound)
            vld = await r._rd(CSRNG_GENBITS_VLD)
            if vld & GB_VLD:
                if first_vld is None:
                    first_vld = vld
                await r._rd(CSRNG_GENBITS)
                words += 1
        recov = await r._rd(CSRNG_RECOV_ALERT_STS)
        return _field(sts, CS_STS_STS), recov, words, first_vld

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
        flag0_ack: dict = {"word": flag0["word"], "cmd_ack": "na", "held_at_ack": "na"}
        ack_sts: object = "na"
        uni: dict = {}
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
            step = "live_f6"
            await self._live_probe(uni, "f6", bound)
            step = "uninst1"
            _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), bound, step)
            self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="acmd_inv")
            uni["raw_uni_f6"] = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
            uni["pre_f6"] = await self._invseq_pre()
            step = "ins_f6"
            _, sts = await self._sw_cmd(cmd_word(ACMD_INSTANTIATE, flag0=MUBI_TRUE), bound, step)
            recov = await r._rd(CSRNG_RECOV_ALERT_STS)
            uni["post_f6"] = int(bool(recov & CS_INVSEQ))
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
            flag0_ack["cmd_ack"] = int(bool(sts & CS_STS_ACK))
            ack_recov = await r._rd(CSRNG_RECOV_ALERT_STS)
            flag0_ack["held_at_ack"] = int(bool(ack_recov & CS_FLAG0_INV))
            flag0_ack["recov"] = f"0x{ack_recov:x}"
            ack_sts = _field(sts, CS_STS_STS)
            # An instantiate with a legal flag0 sets the field back to a legal value.
            step = "live_f9b"
            await self._live_probe(uni, "f9b", bound)
            step = "uninst3"
            _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), bound, step)
            self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="ins_fbad")
            uni["raw_uni_f9b"] = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
            uni["pre_f9b"] = await self._invseq_pre()
            step = "ins_f9b"
            _, sts = await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), bound, step)
            uni["post_f9b"] = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
            self.chk.obs("CSRNG-HDR-INS", flag0="0x9", cmd_sts=sts, after="ins_fbad")
            flag0["legal_ins_sts"] = sts
            recov = await r._rd(CSRNG_RECOV_ALERT_STS)
            flag0["set_before_clear"] = int(bool(recov & CS_FLAG0_INV))
            flag0["cleared_by_write0"] = await self._clear_bit(CS_FLAG0_INV)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound} step={step}"
        close_graded_window(self.logger)
        flag0.setdefault("legal_ins_sts", "na")
        flag0.setdefault("set_before_clear", 0)
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
            not reason
            and flag0["alert_set"] == 1
            and flag0["legal_ins_sts"] == STS_SUCCESS
            and flag0["set_before_clear"] == 1
            and flag0["cleared_by_write0"] == 1,
            **flag0,
        )
        for fields in (flag0_ack, uni):
            if reason:
                fields["reason"] = reason
        self.chk.ok(
            "CSRNG-FLAG0-ACK",
            not reason and flag0_ack["cmd_ack"] == 1 and flag0_ack["held_at_ack"] == 1,
            **flag0_ack,
            expected_held=1,
        )
        self.chk.ctrl(
            "CSRNG-UNINST-RESET",
            all(
                uni.get(f"{k}_{leg}") == want
                for leg in ("f6", "f9b")
                for k, want in (("probe_pre", 0), ("live", 1), ("live_clr", 0), ("pre", 0))
            ),
            **uni,
        )
        self.chk.ok(
            "CSRNG-UNINST-RESET",
            not reason and uni.get("post_f6") == 0 and uni.get("post_f9b") == 0,
            **uni,
            expected_post=0,
        )
        # A write of 0 while flag0 holds the invalid value runs on a repeat of the
        # invalid instantiate after the graded clear, so no graded read follows it.
        held: dict = {"cmd_sts": ack_sts, "repeat_cmd_sts": "na", "cleared_after_ack": "na"}
        if reason:
            held["reason"] = reason
        else:
            try:
                step = "uninst4"
                _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), bound, step)
                self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="flag0_clear")
                step = "ins_fbad2"
                await self._sw_cmd(word, bound, step, wait_ack=False)
                await self._wait(
                    CSRNG_RECOV_ALERT_STS, CS_FLAG0_INV, CS_FLAG0_INV, bound, "flag0_alert2"
                )
                _, sts = await self._wait(
                    CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, bound, "fbad2_ack"
                )
                held["repeat_cmd_sts"] = _field(sts, CS_STS_STS)
                held["cleared_after_ack"] = await self._clear_bit(CS_FLAG0_INV)
            except TrialTimeout as exc:
                held["reason"] = f"timeout:{exc.what} bound={exc.bound} step={step}"
        self.chk.obs("CSRNG-FLAG0-HELD", **held)
        await self._release()

    async def _live_probe(self, uni: dict, leg: str, bound: int) -> None:
        """Show that the instance is instantiated before the Uninstantiate of ``leg``.

        Bit 14 is set for an instantiate "sent for a state that was already
        instantiated" (csrng.rdl:396-398). Bit 14 reads 0 first; then an instantiate
        is sent. A probe that leaves bit 14 at 0 instantiated the instance itself, so
        one more probe follows. The last probe must set bit 14, which is then cleared
        by a write of 0 to bit 14 only. Records ``probe_pre``, ``probes``, ``live``
        and ``live_clr`` of ``leg`` in ``uni``.
        """
        r = self.reg
        uni[f"probe_pre_{leg}"] = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        live = probes = 0
        while probes < 2 and not live:
            probes += 1
            await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), bound, f"live_{leg}_{probes}")
            live = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        uni[f"probes_{leg}"] = probes
        uni[f"live_{leg}"] = live
        uni[f"live_clr_{leg}"] = await self._invseq_pre()

    async def _invseq_pre(self) -> int:
        """Bit 14 before an instantiate. Read it; when it reads 1, write 0 to bit 14
        only (the other RW0C bits get 1, which leaves them) and read it again. Returns
        the last read."""
        r = self.reg
        bit = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        if bit:
            await r._wr(CSRNG_RECOV_ALERT_STS, ~CS_INVSEQ & 0xFFFF_FFFF)
            bit = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        return bit

    # --- reseed leg: limit, reseed header, GENBITS gate -------------------------------
    async def _reseed_leg(self) -> None:
        await self._clean_start("reseed")
        r = self.reg
        plan = self.plan
        k = plan.reseed_k
        await r._wr(CSRNG_RESEED_INTERVAL, k)
        # No Instantiate has reached the software instance since the clean start.
        await self._refused_generate("before_instantiate")
        gens: list[tuple[int, int, int]] = []
        refused = None
        lim = {"k": k, "max_generates": k + 1, "expected_refused_index": k + 1}
        hdr = {"word": f"0x{cmd_word(ACMD_RESEED):x}"}
        gate = {"sw_app_enable": f"0x{plan.gen_off:x}"}
        kat: dict = {}
        upd: dict = {}
        gen1_vld = None
        reason = ""
        step = "ins"
        fips_pre = await self._fips_force_pre()
        try:
            # The instantiate runs with the window closed: no check of this leg grades
            # its handshake or its cs_cmd_req_done.
            await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), FIRST_CAP, step)
            open_graded_window(TEST, self.logger)
            for i in range(1, k + 2):
                step = f"gen{i}"
                sts, recov, words, vld = await self._sw_generate(FIRST_CAP)
                gens.append((sts, int(bool(recov & CS_RESEED_CNT)), words))
                if i == 1:
                    # The words wait in GENBITS when the acknowledge came first.
                    gen1_vld = vld if vld is not None else await r._rd(CSRNG_GENBITS_VLD)
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
            if refused is not None:
                step = "update"
                upd = await self._update_after_refusal(4 * len(gens))
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
            sts, recov, words, _ = await self._sw_generate(FIRST_CAP)
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
            kat = await self._genbits_kat(drain_max, entropy_ctrl=True)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound} step={step}"
        if reason:
            self.chk.blocked("CSRNG-UNINST-REFUSE", f"after_uninstantiate: {reason}")
        else:
            await self._uninst_refuse_leg()
        close_graded_window(self.logger)
        upd_kat: dict = {}
        if not reason:
            upd_kat = await self._update_kat()
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
        if gens:
            gen1_fips = None
            if gen1_vld is not None and gen1_vld & GB_VLD:
                gen1_fips = int(bool(gen1_vld & GB_FIPS))
            self._fips_genbits_grade(
                "reseed_flag0_false",
                fips_pre,
                gen1_fips,
                FIPS_FLAG0_FALSE,
                "" if gen1_fips is not None else "no_genbits_vld_read_with_vld_1",
            )
        else:
            self.chk.blocked("DRBG-FIPS-PROV", f"reseed_flag0_false: {reason}")
        if kat:
            self._fips_kat_grade("kat_reseed_flag0_true", kat)
            self.chk.ctrl(
                "CSRNG-ENTROPY-REQ",
                kat.get("ent_pre") == 0 and kat.get("ent_after_ins") == 0,
                leg="kat_flag0_true",
                ent_pre=kat.get("ent_pre"),
                ent_after_ins=kat.get("ent_after_ins"),
                expected=0,
            )
        else:
            self.chk.blocked("DRBG-FIPS-PROV", f"kat_reseed_flag0_true: {reason}")
        self._update_grade(upd, refused, reason)
        self._update_kat_grade(upd_kat, reason)
        await self._release()

    def _update_grade(self, upd: dict, refused: int | None, reason: str) -> None:
        """CTRL-CSRNG-UPDATE and CHK-CSRNG-UPDATE from ``_update_after_refusal``."""
        if not upd:
            why = reason or f"no_refused_generate refused_index={refused}"
            self.chk.blocked("CSRNG-UPDATE", why)
            return
        self.chk.ctrl(
            "CSRNG-UPDATE",
            refused is not None and upd.get("pre_vld") == 0,
            refused_index=refused,
            pre_drained=upd.get("pre_drained"),
            pre_vld=upd.get("pre_vld"),
        )
        self.chk.ok(
            "CSRNG-UPDATE",
            "reason" not in upd
            and upd.get("cmd_ack") == 1
            and upd.get("cmd_sts") == STS_SUCCESS
            and upd.get("vld_after") == 0
            and upd.get("gen_cmd_sts") == STS_RESEED_CNT_EXCEEDED
            and upd.get("alert15") == 1
            and upd.get("alert15_cleared") == 1,
            **upd,
            expected_sts=STS_SUCCESS,
            expected_vld_after=0,
            expected_gen_sts=STS_RESEED_CNT_EXCEEDED,
            expected_alert15=1,
        )

    async def _update_kat(self) -> dict:
        """Known-answer leg of CHK-CSRNG-UPDATE: an Update on a known state.

        Runs after the reseed-leg window closed, on the software instance that the
        refusal leg left uninstantiated. An Instantiate with flag0 True and clen 12
        of the known-answer seed sets the state from the seed alone
        (theory_of_operation.md:227), with no derivation function (README.md:47).
        An Update with clen 12 carries the drawn 384-bit additional data, least
        significant word first (programmers_guide.md:37-61). The Update uses "only
        the additional data provided" in the update function
        (theory_of_operation.md:255-263), the SP 800-90A 10.2.1.2 CTR_DRBG update of
        the AES-CTR-DRBG (hw/ip/drbg/doc/architecture.adoc:14). One Generate (glen
        1) follows; its four ``GENBITS`` words, least significant word first
        (programmers_guide.md:108-114), are compared with the golden first block
        after the Update. The leg ends with an Uninstantiate."""
        r = self.reg
        seed = self.plan.kat_seed
        data = self.plan.upd_data
        f: dict = {"leg": "known_answer", "data_sha": word_digest(data)}
        step = "ins"
        try:
            await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
            f["vld_pre"] = int(bool(await r._rd(CSRNG_GENBITS_VLD) & GB_VLD))
            ins = cmd_word(ACMD_INSTANTIATE, clen=KAT_CLEN, flag0=MUBI_TRUE)
            await self._sw_cmd(ins, FIRST_CAP, "upd_kat_ins_rdy", wait_ack=False)
            for i in range(KAT_CLEN):
                await r._wr(CSRNG_CMD_REQ, (seed >> (32 * i)) & 0xFFFF_FFFF)
            _, sts = await self._wait(
                CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "upd_kat_ins_ack"
            )
            f["ins_cmd_sts"] = _field(sts, CS_STS_STS)
            step = "update"
            await self._sw_cmd(
                cmd_word(ACMD_UPDATE, clen=KAT_CLEN), FIRST_CAP, "upd_kat_rdy", wait_ack=False
            )
            for i in range(KAT_CLEN):
                await r._wr(CSRNG_CMD_REQ, (data >> (32 * i)) & 0xFFFF_FFFF)
            _, sts = await self._wait(
                CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "upd_kat_ack"
            )
            f["cmd_sts"] = _field(sts, CS_STS_STS)
            step = "gen"
            await self._sw_cmd(CMD_GENERATE_1, FIRST_CAP, "upd_kat_gen", wait_ack=False)
            got = []
            for i in range(GEN1_WORDS):
                await self._wait(CSRNG_GENBITS_VLD, GB_VLD, GB_VLD, FIRST_CAP, f"upd_kat_vld{i}")
                got.append(await r._rd(CSRNG_GENBITS))
            f["genbits"] = [f"0x{w:08x}" for w in got]
            _, sts = await self._wait(
                CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "upd_kat_gen_ack"
            )
            f["gen_cmd_sts"] = _field(sts, CS_STS_STS)
            step = "uni"
            await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "upd_kat_uni")
        except TrialTimeout as exc:
            f["reason"] = f"timeout:{exc.what} bound={exc.bound} step={step}"
        return f

    def _update_kat_grade(self, f: dict, reason: str) -> None:
        """CTRL-CSRNG-UPDATE and CHK-CSRNG-UPDATE of leg ``known_answer``.

        The control: the golden first block after the Update differs from the
        golden first block without it, so a DUT that acknowledges the Update and
        does not apply it fails the check, and ``GENBITS_VLD`` read 0 before the
        Instantiate. The check: the Instantiate, the Update and the Generate
        acknowledge with ``CMD_STS`` = 0, and the four ``GENBITS`` words equal the
        golden after the Update."""
        if not f:
            self.chk.blocked("CSRNG-UPDATE", f"known_answer: {reason}")
            return
        seed = self.plan.kat_seed
        plain = SepCtrDrbgGolden()
        plain.instantiate(0, additional_input=seed)
        updated = SepCtrDrbgGolden()
        updated.instantiate(0, additional_input=seed)
        updated._update(self.plan.upd_data)

        def _txt(block: int) -> list[str]:
            return [f"0x{(block >> (32 * i)) & 0xFFFF_FFFF:08x}" for i in range(GEN1_WORDS)]

        expected = _txt(updated.generate_one())
        no_update = _txt(plain.generate_one())
        self.chk.ctrl(
            "CSRNG-UPDATE",
            expected != no_update and f.get("vld_pre") == 0,
            leg="known_answer",
            vld_pre=f.get("vld_pre"),
            golden_after_update=expected,
            golden_without_update=no_update,
        )
        self.chk.ok(
            "CSRNG-UPDATE",
            "reason" not in f
            and f.get("ins_cmd_sts") == STS_SUCCESS
            and f.get("cmd_sts") == STS_SUCCESS
            and f.get("gen_cmd_sts") == STS_SUCCESS
            and f.get("genbits") == expected,
            **f,
            expected=expected,
            expected_sts=STS_SUCCESS,
        )

    async def _update_after_refusal(self, drain_max: int) -> dict:
        """The Update after the refused Generate K + 1, then one Generate.

        ``GENBITS`` is read until ``GENBITS_VLD`` reads 0, so a ``GENBITS_VLD`` of
        1 after the Update would come from the Update. The Update carries one
        additional-data word (the low word of the known-answer seed). After the
        Generate, a write of 0 clears bit 15 before the Reseed of the leg."""
        r = self.reg
        f: dict = {}
        drained = 0
        left = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
        while left and drained < drain_max:
            await r._rd(CSRNG_GENBITS)
            drained += 1
            left = await r._rd(CSRNG_GENBITS_VLD) & GB_VLD
        f.update({"pre_drained": drained, "pre_vld": int(bool(left))})
        word = cmd_word(ACMD_UPDATE, clen=UPDATE_CLEN)
        f["word"] = f"0x{word:x}"
        try:
            await self._sw_cmd(word, FIRST_CAP, "upd", wait_ack=False)
            await r._wr(CSRNG_CMD_REQ, self.plan.kat_seed & 0xFFFF_FFFF)
            _, sts = await self._wait(
                CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "upd_ack"
            )
            f["cmd_ack"] = int(bool(sts & CS_STS_ACK))
            f["cmd_sts"] = _field(sts, CS_STS_STS)
            f["vld_after"] = int(bool(await r._rd(CSRNG_GENBITS_VLD) & GB_VLD))
            gen_sts, recov, words, _ = await self._sw_generate(FIRST_CAP)
            f["gen_cmd_sts"] = gen_sts
            f["alert15"] = int(bool(recov & CS_RESEED_CNT))
            f["gen_words"] = words
            f["alert15_cleared"] = await self._clear_bit(CS_RESEED_CNT)
        except TrialTimeout as exc:
            f["reason"] = f"timeout:{exc.what} bound={exc.bound}"
        return f

    async def _refused_generate(self, leg: str) -> None:
        """CHK-CSRNG-UNINST-REFUSE of one leg: a Generate (glen 1) to a software
        instance that is not instantiated acknowledges with ``CMD_STS`` = 3, sets bit
        14, returns no ``GENBITS`` word before the acknowledge and leaves
        ``GENBITS_VLD`` at 0; a write of 0 clears bit 14. Control
        (``CTRL-CSRNG-UNINST-REFUSE``): bit 14 and ``GENBITS_VLD`` read 0 first."""
        r = self.reg
        f: dict = {"leg": leg}
        f["invseq_pre"] = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        f["vld_pre"] = int(bool(await r._rd(CSRNG_GENBITS_VLD) & GB_VLD))
        try:
            sts, recov, words, _ = await self._sw_generate(FIRST_CAP)
            f["cmd_sts"] = sts
            f["invseq"] = int(bool(recov & CS_INVSEQ))
            f["alert15"] = int(bool(recov & CS_RESEED_CNT))
            f["words"] = words
            f["vld_after"] = int(bool(await r._rd(CSRNG_GENBITS_VLD) & GB_VLD))
            f["cleared_by_write0"] = await self._clear_bit(CS_INVSEQ)
        except TrialTimeout as exc:
            f["reason"] = f"timeout:{exc.what} bound={exc.bound}"
        self.chk.ctrl(
            "CSRNG-UNINST-REFUSE",
            f["invseq_pre"] == 0 and f["vld_pre"] == 0,
            leg=leg,
            invseq_pre=f["invseq_pre"],
            vld_pre=f["vld_pre"],
        )
        self.chk.ok(
            "CSRNG-UNINST-REFUSE",
            "reason" not in f
            and f.get("cmd_sts") == STS_INVALID_CMD_SEQ
            and f.get("invseq") == 1
            and f.get("words") == 0
            and f.get("vld_after") == 0
            and f.get("cleared_by_write0") == 1,
            **f,
            expected_sts=STS_INVALID_CMD_SEQ,
            expected_words=0,
        )

    async def _uninst_refuse_leg(self) -> None:
        """OBS-CSRNG-UNINST-STATE before and after an Uninstantiate of the
        instantiated software instance, then the refused Generate of
        CHK-CSRNG-UNINST-REFUSE leg ``after_uninstantiate``."""
        await self._int_state_obs("pre")
        try:
            _, sts = await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "refuse_uni")
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
            self.chk.ok("CSRNG-UNINST-REFUSE", False, leg="after_uninstantiate", reason=reason)
            return
        self.chk.obs("CSRNG-UNINST", cmd_sts=sts, after="kat")
        await self._int_state_obs("post")
        await self._refused_generate("after_uninstantiate")

    async def _int_state_obs(self, phase: str) -> None:
        """OBS-CSRNG-UNINST-STATE at ``phase``: with ``CTRL.READ_INT_STATE`` True,
        the INT_STATE_WORDS ``INT_STATE_VAL`` reads of each ``INT_STATE_NUM`` index
        (written, then read back). ``CTRL`` returns to ``CSRNG_CTRL_ON`` after."""
        r = self.reg
        top = cocotb.top
        await r._wr(CSRNG_CTRL, CSRNG_CTRL_READ_STATE)
        for idx in INT_STATE_IDX:
            await r._wr(CSRNG_INT_STATE_NUM, idx)
            num_rb = await r._rd(CSRNG_INT_STATE_NUM)
            words = [await r._rd(CSRNG_INT_STATE_VAL) for _ in range(INT_STATE_WORDS)]
            self.chk.obs(
                "CSRNG-UNINST-STATE",
                phase=phase,
                idx=idx,
                idx_rb=num_rb,
                nonzero=int(any(words)),
                digest=word_digest(words),
                sw_app_read_en=f"0x{self.rd(top.csrng_sw_app_read_en_o):02x}",
                lc_hw_debug_en=f"0x{self.rd(top.csrng_lc_hw_debug_en_o):x}",
            )
        await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)

    async def _genbits_kat(
        self, drain_max: int, clear_recov: bool = False, entropy_ctrl: bool = False
    ) -> dict:
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

        The dict also carries ``FIPS_FORCE`` and ``CTRL.FIPS_FORCE_ENABLE`` read
        before the Instantiate and ``genbits_fips``, the ``GENBITS_FIPS`` bit of the
        first ``GENBITS_VLD`` read with ``GENBITS_VLD`` = 1. With ``entropy_ctrl``,
        ``cs_entropy_req`` is written 1 before the Uninstantiate and read after that
        write (``ent_pre``) and after the Instantiate acknowledge (``ent_after_ins``).
        """
        r = self.reg
        seed = self.plan.kat_seed
        extra: dict = {}
        await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
        extra.update(await self._fips_force_pre())
        drained = 0
        while await r._rd(CSRNG_GENBITS_VLD) & GB_VLD and drained < drain_max:
            await r._rd(CSRNG_GENBITS)
            drained += 1
        if entropy_ctrl:
            await r._wr(CSRNG_INTR_STATE, CS_ENTROPY_REQ)
            extra["ent_pre"] = int(bool(await r._rd(CSRNG_INTR_STATE) & CS_ENTROPY_REQ))
        await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "kat_uni")
        ins = cmd_word(ACMD_INSTANTIATE, clen=KAT_CLEN, flag0=MUBI_TRUE)
        await self._sw_cmd(ins, FIRST_CAP, "kat_ins_rdy", wait_ack=False)
        for i in range(KAT_CLEN):
            await r._wr(CSRNG_CMD_REQ, (seed >> (32 * i)) & 0xFFFF_FFFF)
        _, ins_sts = await self._wait(
            CSRNG_SW_CMD_STS, CS_STS_ACK, CS_STS_ACK, FIRST_CAP, "kat_ins_ack"
        )
        if entropy_ctrl:
            extra["ent_after_ins"] = int(bool(await r._rd(CSRNG_INTR_STATE) & CS_ENTROPY_REQ))
        if clear_recov:
            await r._wr(CSRNG_RECOV_ALERT_STS, 0)
            extra["recov_clear"] = await r._rd(CSRNG_RECOV_ALERT_STS)
        await self._sw_cmd(CMD_GENERATE_1, FIRST_CAP, "kat_gen", wait_ack=False)
        got = []
        for i in range(GEN1_WORDS):
            _, vld = await self._wait(CSRNG_GENBITS_VLD, GB_VLD, GB_VLD, FIRST_CAP, f"kat_vld{i}")
            if i == 0:
                extra["genbits_fips"] = int(bool(vld & GB_FIPS))
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
        noise = self.start_esrc_noise_driver()
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
            self._fips_kat_grade("kat_bus_cmp1_flag0_true", first)
            self._fips_kat_grade("kat_bus_cmp2_flag0_true", second)
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

        CHK-CSRNG-ACK-CLR: ``CMD_ACK`` "is set to low each time a new command is
        written to !!CMD_REQ" (csrng.rdl:215). The Instantiate header carries clen 12
        and its seed is the additional data alone (theory_of_operation.md:227), so it
        cannot complete before its data words; a read between the header and the
        first data word reads ``CMD_ACK`` = 0. Control (``CTRL-CSRNG-ACK-CLR``): the
        read after the Uninstantiate acknowledge, before the header, reads 1.
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
        f: dict = {"seed_w0_sha": word_digest(wrote_w0), "expect_w0_sha": word_digest(w0)}
        ack: dict = {"ack_before": "na", "ack_after_hdr": "na", "clen": KAT_CLEN}
        got: list[int] = []
        step = "uni"
        try:
            await r._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
            await self._sw_cmd(cmd_word(ACMD_UNINSTANTIATE), FIRST_CAP, "vctr_uni")
            ack["ack_before"] = int(bool(await r._rd(CSRNG_SW_CMD_STS) & CS_STS_ACK))
            step = "ins"
            ins = cmd_word(ACMD_INSTANTIATE, clen=KAT_CLEN, flag0=MUBI_TRUE)
            await self._sw_cmd(ins, FIRST_CAP, "vctr_ins_rdy", wait_ack=False)
            ack["ack_after_hdr"] = int(bool(await r._rd(CSRNG_SW_CMD_STS) & CS_STS_ACK))
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
            ack["reason"] = f["reason"]
        self.chk.ctrl("CSRNG-ACK-CLR", ack["ack_before"] == 1, **ack)
        self.chk.ok("CSRNG-ACK-CLR", ack["ack_after_hdr"] == 0, **ack, expected_after_hdr=0)

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

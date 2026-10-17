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
  * Reseed limit (csrng.adoc ``RESEED_INTERVAL``:141-144): the counter "counts
    the number of generate commands between reseed or instantiate commands. If
    the counter reaches the value of this register, the violating command will
    be acknowledged with a status error."
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
``SW_APP_ENABLE`` value that is not True for the ``GENBITS`` read. The reserved
values 0x9 to 0xd carry a defined command code in bits [2:0]; the leaf sends 0x9 on
every seed in its last leg (no draw) and logs the result only. The checked values do
not depend on the seed.

The three groups run in the drawn order. Then the leaf runs, in this order, the
``CTRL`` alert leg (a TRNG reset, no bring-up), the command header leg, the
reseed leg and, last, the reserved acmd 0x9 leg (each from a clean start). The 0x9
leg runs after every other check, so its result does not change the stimulus of
another check.

Only reserved values whose bits [2:0] are also reserved are graded. The text
reserves 0x0 and 0x6 to 0xf of the 4-bit acmd field, but the OpenTitan CSRNG
decodes bits [2:0] only, and its designers state that bit 3 is claimed for future
use and that a reserved value gives an undefined result (lowRISC/opentitan issue
16203). No text states the result of 0x9 to 0xd, so the 0x9 leg is an observation.

Checkers:
  CHK-EDN-BOOT   for each graded boot (AUTO_REQ_MODE true, then false) the first
                 ``HW_CMD_STS`` read with ``BOOT_MODE`` = 1 has ``AUTO_MODE`` = 0,
                 within 16 x the reference boot time t0.
  CHK-EDN-SW-HS  ``CMD_REG_RDY`` and ``CMD_RDY`` 1 before the command; ``CMD_ACK``
                 and ``CMD_RDY`` 1 after it; ``edn_cmd_req_done`` and vector bit 27
                 read 0 before the command, and 1 (a rise of bit 27) after it.
  CHK-EDN-INVSEQ the second instantiate through EDN sets CSRNG bit 14 and a write
                 of 0 clears it. Control: bit 14 reads 0 after the first command.
  CHK-CSRNG-SW   the same handshake for the CSRNG software instance (vector bit
                 23), and bit 14 on the second command. Control: bit 14 reads 0
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
  CHK-CSRNG-RESEED-LIMIT  with ``RESEED_INTERVAL`` = K, a Generate within the
                 first K + 1 acks with ``CMD_STS`` = 4 and bit 15 reads 1 at
                 that ack; a write of 0 clears bit 15. The counter reaches K
                 after K or K + 1 Generates, whichever reading of "reaches"
                 holds, so K + 1 Generates bound the leg. The index of the
                 refused Generate is logged only (``OBS-CSRNG-RESEED-IDX``).
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
                 to a value other than 6: four ``GENBITS`` reads return 0.
                 Control: ``GENBITS`` is first drained (read while
                 ``GENBITS_VLD`` = 1, at most four reads per earlier Generate)
                 until ``GENBITS_VLD`` reads 0, and it reads 1 only after the
                 leg's own Generate.
The unstated effects are logged only (``OBS-EDN-*``, ``OBS-CSRNG-*``). The
``CMD_STS`` of the CSRNG instantiate stays an observation (``OBS-CSRNG-STS``): no
sentence states that a first instantiate on the software instance succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_reg_meta import CSRNG, EDN, SEP_CPU_CTRL, sym
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, wait_until
from sep_base_test import sep_base_test
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_drbg_mode_bringup_seq import drbg_bring_up
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
EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
EDN_SW_CMD_REQ = sym("EDN_SW_CMD_REQ_REG_ADDR")
EDN_SW_CMD_STS = sym("EDN_SW_CMD_STS_REG_ADDR")
EDN_HW_CMD_STS = sym("EDN_HW_CMD_STS_REG_ADDR")
EDN_INTR_STATE = sym("EDN_INTR_STATE_REG_ADDR")
EDN_INTR_ENABLE = sym("EDN_INTR_ENABLE_REG_ADDR")
EDN_RECOV_ALERT_STS = sym("EDN_RECOV_ALERT_STS_REG_ADDR")

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

GB_VLD = CSRNG.fields("GENBITS_VLD")["GENBITS_VLD"]["bm"]
_CS_RECOV = CSRNG.fields("RECOV_ALERT_STS")
CS_FLAG0_INV = _CS_RECOV["ACMD_FLAG0_FIELD_ALERT"]["bm"]
CS_ACMD_INV = _CS_RECOV["CMD_STAGE_INVALID_ACMD_ALERT"]["bm"]
CS_RESEED_CNT = _CS_RECOV["CMD_STAGE_RESEED_CNT_ALERT"]["bm"]
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
CSRNG_CTRL_OFF = CSRNG.value(
    "CTRL",
    ENABLE=MUBI_FALSE,
    SW_APP_ENABLE=MUBI_FALSE,
    READ_INT_STATE=MUBI_FALSE,
    FIPS_FORCE_ENABLE=MUBI_FALSE,
)


def _edn_ctrl(boot: bool, auto: bool, enable: bool) -> int:
    return EDN.value(
        "CTRL",
        EDN_ENABLE=MUBI_TRUE if enable else MUBI_FALSE,
        BOOT_REQ_MODE=MUBI_TRUE if boot else MUBI_FALSE,
        AUTO_REQ_MODE=MUBI_TRUE if auto else MUBI_FALSE,
        CMD_FIFO_RST=MUBI_FALSE,
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

    def describe(self) -> str:
        return (
            f"groups={','.join(self.groups)} gaps[0:8]={list(self.gaps[:8])}"
            f" cs_bad={[hex(v) for v in self.cs_bad]} ed_bad={[hex(v) for v in self.ed_bad]}"
            f" bad_flag0=0x{self.bad_flag0:x} bad_acmd=0x{self.bad_acmd:x}"
            f" reseed_k={self.reseed_k} gen_off=0x{self.gen_off:x}"
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
    return Plan(seed, tuple(groups), gaps, cs_bad, ed_bad, bad_flag0, bad_acmd, reseed_k, gen_off)


class _Reg(SepAxiRegDriver):
    _DRIVER_TAG = "DRBG"


def _field(value: int, meta: dict[str, int]) -> int:
    return (value & meta["bm"]) >> meta["bp"]


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
        "CHK-CSRNG-CTRL-MUBI",
        "CHK-EDN-CTRL-MUBI",
        "CHK-CSRNG-ACMD-INV",
        "CHK-CSRNG-FLAG0",
        "CHK-CSRNG-RESEED-LIMIT",
        "CHK-CSRNG-RESEED-HDR",
        "CHK-CSRNG-GENBITS-GATE",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac", "abr"))
        self.reg = _Reg(self)
        await self.reg._wr(EXT_TRNG_SRC_SEL, 0)
        self.logger.info("BASELINE sw_reset_n=0x%02x ext_trng_src_sel=0x0", self.swrst.value)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.vec = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {"edn_done": VEC_EDN_DONE, "cs_done": VEC_CS_DONE, "cs_exc": VEC_CS_HW_INST_EXC},
            name="sep_internal_interrupts_probe_o",
        ).start()
        self._gap_i = 0
        self.sb = None
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
            await self._acmd_hi_leg()
        finally:
            close_graded_window(self.logger)
            if self.sb is not None:
                self.sb.stop()
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
        self.logger.info("TRNG reset: rise_clk=%d fall_clk=%d cap=%d", rise, fall, TRNG_RESET_CAP)

    async def _clean_start(self, group: str) -> int:
        """TRNG reset, bring-up without the EDN step, CSRNG enable. Returns bit 14."""
        close_graded_window(self.logger)
        await self._trng_reset()
        self.sb = await drbg_bring_up(self, edn_ctrl=None, strict=False)
        await self.reg._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
        recov = await self.reg._rd(CSRNG_RECOV_ALERT_STS)
        bit14 = int(bool(recov & CS_INVSEQ))
        self.chk.ctrl("CLEAN-START", bit14 == 0, group=group, csrng_invseq=bit14)
        return bit14

    # --- boot group -----------------------------------------------------------------
    async def _boot(self, auto: bool, bound: int) -> tuple[int | None, int, int]:
        """One boot with BOOT_REQ_MODE true. Returns (clocks to BOOT_MODE or None, the
        HW_CMD_STS read that first shows BOOT_MODE, the CTRL word)."""
        off = _edn_ctrl(boot=True, auto=auto, enable=False)
        on = _edn_ctrl(boot=True, auto=auto, enable=True)
        open_graded_window(TEST, self.logger)
        await self.reg._wr(EDN_CTRL, off)
        await self.reg._wr(EDN_CTRL, on)
        try:
            clk, sts = await self._wait(
                EDN_HW_CMD_STS, ED_BOOT_MODE, ED_BOOT_MODE, bound, "boot_mode"
            )
        except TrialTimeout:
            close_graded_window(self.logger)
            return None, 0, on
        close_graded_window(self.logger)
        return clk, sts, on

    async def _boot_group(self) -> None:
        await self._clean_start("boot_ref")
        t0, sts, ctrl = await self._boot(auto=False, bound=FIRST_CAP)
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
        self.chk.obs("EDN-TSEED", tseed_clk=t0, auto_mode=int(bool(sts & ED_AUTO_MODE)))
        bound = BOUND_FACTOR * t0
        for auto in (True, False):
            await self._clean_start(f"boot_auto{int(auto)}")
            clk, sts, ctrl = await self._boot(auto=auto, bound=bound)
            fields = {
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
            self.chk.ok("EDN-BOOT", clk is not None and not sts & ED_AUTO_MODE, **fields)

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
        hs = {"cmd_reg_rdy": 0, "cmd_rdy": 0, "ack_done": 0, "rdy_done": 0, "edn_done": 0}
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
            want = ED_STS_ACK | ED_STS_RDY
            _, done = await self._wait(EDN_SW_CMD_STS, want, want, FIRST_CAP, "edn_ack")
            t_cmd = max(self._now() - t_wr, 1)
            hs["ack_done"] = int(bool(done & ED_STS_ACK))
            hs["rdy_done"] = int(bool(done & ED_STS_RDY))
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
                    "rdy_done",
                    "edn_done",
                    "enable",
                    "vec27",
                    "edn_done_pre0",
                    "vec27_pre0",
                )
            ),
            **hs,
        )
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
        reads 0 after a write of 0, before the command."""
        r = self.reg
        bound = BOUND_FACTOR * t_cmd
        word = cmd_word(self.plan.bad_acmd)
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        reason = ""
        bad_sts = None
        ack_err = None
        # The second instantiate acked with a non-zero status, so the software port
        # does not take a command until EDN is disabled; disable and enable it.
        held = await r._rd(EDN_SW_CMD_STS)
        self.chk.obs("EDN-PORT-HELD", cmd_rdy=int(bool(held & ED_STS_RDY)))
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=False))
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=True))
        await r._wr(EDN_RECOV_ALERT_STS, 0)
        pre_ack_err = int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR))
        open_graded_window(TEST, self.logger)
        try:
            await self._wait(EDN_SW_CMD_STS, rdy_mask, rdy_mask, bound, "edn_rdy3")
            await r._wr(EDN_SW_CMD_REQ, word)
            _, sts = await self._wait(EDN_SW_CMD_STS, ED_STS_ACK, ED_STS_ACK, bound, "edn_ack3")
            bad_sts = _field(sts, ED_STS_STS)
            ack_err = int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR))
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        self.chk.obs(
            "EDN-ACMD-INV",
            word=f"0x{word:x}",
            csrng_acmd_alert=int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_ACMD_INV)),
        )
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
        self.chk.obs(
            "EDN-STS",
            cmd_sts=self._edn_first_sts,
            word=f"0x{CMD_INSTANTIATE:x}",
            auto_req_mode="false",
            reason="success_stated_only_with_auto_req_mode_true",
        )

    async def _edn_invseq(self, t_cmd: int) -> None:
        r = self.reg
        bound = BOUND_FACTOR * t_cmd
        first = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        self.chk.ctrl("EDN-INVSEQ", first == 0, ctrl_first_invseq=first)
        open_graded_window(TEST, self.logger)
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        invseq = 0
        cleared = 0
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
        await r._wr(CSRNG_RECOV_ALERT_STS, 0)
        after = await r._rd(CSRNG_RECOV_ALERT_STS)
        cleared = int(not after & CS_INVSEQ)
        close_graded_window(self.logger)
        fields = {
            "ctrl_first_invseq": first,
            "csrng_invseq": invseq,
            "cleared_by_write0": cleared,
            "bound": bound,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("EDN-INVSEQ", not reason and invseq == 1 and cleared == 1, **fields)

    # --- CSRNG software instance leg ---------------------------------------------
    async def _csrng_sw_leg(self) -> None:
        await self._clean_start("csrng_sw")
        r = self.reg
        open_graded_window(TEST, self.logger)
        await r._wr(CSRNG_INTR_ENABLE, CS_DONE)
        enable = int(bool(await r._rd(CSRNG_INTR_ENABLE) & CS_DONE))
        hs = {"cmd_rdy": 0, "ack": 0, "rdy_done": 0, "done": 0, "enable": enable, "vec23": 0}
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
            want = CS_STS_ACK | CS_STS_RDY
            _, done = await self._wait(CSRNG_SW_CMD_STS, want, want, FIRST_CAP, "ack")
            t_cmd = max(self._now() - t_wr, 1)
            hs["ack"] = int(bool(done & CS_STS_ACK))
            hs["rdy_done"] = int(bool(done & CS_STS_RDY))
            state = await r._rd(CSRNG_INTR_STATE)
            hs["done"] = int(bool(state & CS_DONE))
            hs["vec_clk"] = await self._wait_vec(m, "cs_done", VEC_CAP)
            hs["vec23"] = 1
            self.chk.obs("CSRNG-STS", cmd_sts=_field(done, CS_STS_STS), t_cmd=t_cmd)
            await r._wr(CSRNG_INTR_STATE, CS_DONE)
            # Control: bit 14 is 0 after the first command.
            first = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
            self.chk.ctrl("CSRNG-SW", first == 0, ctrl_first_invseq=first)
            bound = BOUND_FACTOR * t_cmd
            hs["bound"] = bound
            await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, bound, "rdy2")
            await r._wr(CSRNG_CMD_REQ, CMD_INSTANTIATE)
            _, recov = await self._wait(CSRNG_RECOV_ALERT_STS, CS_INVSEQ, CS_INVSEQ, bound, "inv")
            invseq = int(bool(recov & CS_INVSEQ))
            sts = await r._rd(CSRNG_SW_CMD_STS)
            self.chk.obs(
                "CSRNG-INVSEQ",
                cmd_sts=_field(sts, CS_STS_STS),
                hw_exc=f"0x{await r._rd(CSRNG_HW_EXC_STS):x}",
            )
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
                "rdy_done",
                "done",
                "enable",
                "vec23",
                "invseq",
                "done_pre0",
                "vec23_pre0",
            )
        )
        self.chk.ok("CSRNG-SW", ok and first == 0 and cleared == 1, **hs)

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
        open_graded_window(TEST, self.logger)
        step = "ins_f9"
        acmd = {"word": f"0x{cmd_word(plan.bad_acmd):x}", "alert_set": 0, "cmd_sts": "na"}
        flag0 = {"word": f"0x{cmd_word(ACMD_INSTANTIATE, flag0=plan.bad_flag0):x}"}
        flag0["alert_set"] = 0
        reason = ""
        try:
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

    # --- reseed leg: limit, reseed header, GENBITS gate -------------------------------
    async def _reseed_leg(self) -> None:
        await self._clean_start("reseed")
        r = self.reg
        plan = self.plan
        k = plan.reseed_k
        await r._wr(CSRNG_RESEED_INTERVAL, k)
        open_graded_window(TEST, self.logger)
        gens: list[tuple[int, int, int]] = []
        refused = None
        lim = {"k": k, "max_generates": k + 1}
        hdr = {"word": f"0x{cmd_word(ACMD_RESEED):x}"}
        gate = {"sw_app_enable": f"0x{plan.gen_off:x}"}
        reason = ""
        step = "ins"
        try:
            await self._sw_cmd(cmd_word(ACMD_INSTANTIATE), FIRST_CAP, step)
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
            self.chk.obs("CSRNG-RESEED-IDX", k=k, refused_index=lim["refused_index"])
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
            gate["genbits"] = [f"0x{await r._rd(CSRNG_GENBITS):x}" for _ in range(4)]
            self.chk.obs(
                "CSRNG-GENBITS-GATE",
                genbits_vld_after=await r._rd(CSRNG_GENBITS_VLD) & GB_VLD,
            )
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound} step={step}"
        close_graded_window(self.logger)
        for fields in (lim, hdr, gate):
            if reason:
                fields["reason"] = reason
        last = gens[-1] if gens else (None, 0, 0)
        lim_ok = (
            not reason
            and refused is not None
            and last[1] == 1
            and lim.get("cleared_by_write0") == 1
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
        self.chk.ok(
            "CSRNG-GENBITS-GATE",
            not reason and len(words) == 4 and all(w == "0x0" for w in words),
            **gate,
        )

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

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ABR combined commands park and re-arm, single-step results do not depend on order, ACVP rejects hold.

Contract (``hw/sys/sep/doc/adams_bridge.adoc``, OCAH Modifications: the
sequencer parks at the end state of an operation with ``STATUS.VALID`` set, and
``STATUS.READY`` re-asserts only after a zeroize or a reset;
``integration/rdl/sep/abr_reg.rdl``: ``MLDSA_CTRL.CTRL`` 100 is KEYGEN+SIGN,
``MLKEM_CTRL.CTRL`` 100 is KEYGEN+DECAPS, ``ZEROIZE`` zeroizes all internal
registers and memories, ``MLDSA_VERIFY_RES`` equals c~ only for a verified
signature, ``MLKEM_SHARED_KEY`` holds the 8-word shared key). Expected values
are the published NIST ACVP vectors that ``env/sep_abr_nist.py`` and
``env/sep_abr_kem_nist.py`` load (FIPS 204 ML-DSA-87 external mu, FIPS 203
ML-KEM-1024).

Each seed runs three trials in drawn order: ML-DSA KEYGEN+SIGN, ML-KEM
KEYGEN+DECAPS and one drawn single-step cell (ML-DSA KEYGEN, SIGNING or
VERIFYING; ML-KEM KEYGEN, ENCAPS or DECAPS). Each trial ends with a drawn
re-arm, a ZEROIZE or an ABR reset (``SW_RESET_N`` bit 6). Then the leaf
verifies the combined signature (logged only), runs the ACVP accept case as
the tamper control, one drawn ACVP external-mu sigVer reject case of a drawn
reason class, the ACVP valid decapsulation case as the KEM control, and two
drawn ACVP modified-ciphertext decapsulation cases.

Checkers:
  CHK-ABR-COMBO     a combined command shows VALID=1 and READY=0 at the first
                    VALID read.
  CHK-ABR-PARK      after the result reads and before the re-arm READY reads 0;
                    a combined cell also holds VALID=1.
  CHK-ABR-REARM     after a combined cell, ZEROIZE or an ABR reset gives
                    READY=1; after ZEROIZE every secret output window that held
                    a non-zero word reads 0. The ML-KEM KEYGEN+DECAPS cell grades
                    the wipe: its ZEROIZE leg needs at least one window that held a
                    non-zero word, else the check fails. ML-DSA KEYGEN+SIGN fills no
                    secret output window, so its ZEROIZE leg grades READY and logs
                    the wipe part as ``OBS-BLOCKED`` when every window is empty.
  CHK-ABR-ORDER     the single-step result equals its ACVP vector whatever ran
                    before it.
  CHK-ABR-TAMPER    for the drawn reject case ``MLDSA_VERIFY_RES`` differs from
                    c~ (the first 16 signature words as written).
  CHK-ABR-KEM-FLIP  each drawn modified-ciphertext case returns its ACVP key K.
  CHK-ABR-PARKED-CMD
                    a command Y written to the CTRL of a parked block (VALID 1,
                    READY 0) is not run: after a wait of 2 x T_Y + VALID_GAP
                    clocks every output window of Y equals its value at the
                    park, and STATUS still reads VALID 1 and READY 0
                    (``abr_reg.rdl``:77, :81-83, :328, ``swwe = abr_ready`` on
                    the command fields; :91-92, :340-341, READY is "ready to
                    take a control command"; ``adams_bridge.adoc``:186-190).
                    Y is ML-DSA VERIFYING (output ``MLDSA_VERIFY_RES``) after
                    KEYGEN+SIGN, and ML-KEM ENCAPS (outputs
                    ``MLKEM_CIPHERTEXT``, ``MLKEM_SHARED_KEY``) after
                    KEYGEN+DECAPS. Y's inputs are staged before X; the leg
                    writes no input while parked. T_Y is the time of Y alone,
                    measured from READY on the same block before X with the
                    graded window closed.

``STATUS.ERROR`` is logged and not graded. The RDL describes the bit
(``integration/rdl/sep/abr_reg.rdl``:97 and :344, "the process ended with an
error"; field text :106 and :352, "Status error bit") and states no rule for
the value at the end of a combined command, and ``adams_bridge.adoc``:186-189
names only ``VALID`` and ``READY``. CHK-ABR-COMBO and CHK-ABR-PARK carry it in
an ``obs_error`` field.

Controls: ``CTRL-ABR-PARK`` (READY reads 1 after the re-arm of the
single-step cell), ``CTRL-ABR-VALID-PRE`` (VALID reads 0 at the READY read
before each command write, so the VALID wait sees the VALID of that command), ``CTRL-ABR-TAMPER`` (the ACVP accept case gives c~),
``CTRL-ABR-KEM-FLIP`` (the valid decapsulation case gives its K).
Controls of CHK-ABR-PARKED-CMD: ``CTRL-ABR-PARKED-Y`` (Y alone from READY
completes: ML-DSA ``MLDSA_VERIFY_RES`` equals c~ of the signature it verifies,
``abr_reg.rdl``:171-173; ML-KEM VALID rises and both outputs hold a non-zero
word), ``CTRL-ABR-PARKED-INPUTS`` (at the park Y's readable inputs equal the
pre-run inputs: ML-DSA ``MLDSA_PUBKEY`` and ``MLDSA_SIGNATURE``, ML-KEM
``MLKEM_ENCAPS_KEY``), ``CTRL-ABR-PARKED-DIFF`` (the parked outputs differ
from Y's outputs G, so a run of Y changes a graded window) and
``CTRL-ABR-PARKED-BOUND`` (the wait exceeds T_Y). ``MLDSA_EXTERNAL_MU`` is
write-only (``abr_reg.rdl``:190); the leaf writes the same mu both times.
``OBS-ABR-PARKED-MSG`` logs the ``MLKEM_MSG`` readback at the park and grades
nothing.
``CTRL-ABR-SECRET-PRE`` logs which secret windows held a non-zero word before a
ZEROIZE; a window that held none logs ``OBS-ABR-SECRET-EMPTY`` and is not
graded. A zero window proves that the window is not readable, not that the
memory is wiped.

Waits are bounded. A wait that times out logs the owning check as FAIL with
``reason=timeout``, resets ABR and continues with the next step; the leaf fails
at the end. The first FAIL or missing control closes the graded window for the
rest of the leaf.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``. RAND-REP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.sep_abr_kem_nist import (
    NIST_KEM_DEC_MODIFIED,
    NIST_KEM_DEC_OK_C,
    NIST_KEM_DEC_OK_DK,
    NIST_KEM_DEC_OK_K,
    NIST_KEM_ENC_C,
    NIST_KEM_ENC_EK,
    NIST_KEM_ENC_K,
    NIST_KEM_ENC_M,
    NIST_KEM_KG_D,
    NIST_KEM_KG_DK,
    NIST_KEM_KG_EK,
    NIST_KEM_KG_Z,
)
from env.sep_abr_nist import (
    NIST_KG_PK,
    NIST_KG_SEED,
    NIST_SG_MU,
    NIST_SG_SIG,
    NIST_SG_SK,
    NIST_SV_OK_MU,
    NIST_SV_OK_PK,
    NIST_SV_OK_SIG,
    NIST_SV_REJECTS,
)
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_abr_cmd_pass,
    set_abr_reject_class,
)
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import abr_ctrl_cmd, abr_off
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_BASE,
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_EXTERNAL_MU,
    ABR_PRIVKEY_IN,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_SIGNATURE,
    ABR_STATUS,
    ABR_VERIFY_RES,
    CMD_KEYGEN,
    CMD_SIGN,
    CMD_VERIFY,
    CTRL_EXTERNAL_MU,
    CTRL_ZEROIZE,
    ENTROPY_WORDS,
    PK_WORDS,
    SIG_WORDS,
    SK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    VERIFY_RES_WORDS,
    SepAbr,
)
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_DECAPS,
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN,
    KEM_CMD_KEYGEN_DECAPS,
    KEM_CT_WORDS,
    KEM_CTRL_ZEROIZE,
    KEM_DK_WORDS,
    KEM_EK_WORDS,
    KEM_K_WORDS,
    KEM_MSG_WORDS,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_DECAPS_KEY,
    MLKEM_ENCAPS_KEY,
    MLKEM_MSG,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_SHARED_KEY,
    MLKEM_STATUS,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_abr_command_matrix_rand_test"

# Values of the FCOV pass label ``abr_cmd_pass`` (cov/sv/sep_fcov.sv), per block
# (0 ML-DSA, 1 ML-KEM): the sampler holds an outcome at its DUT event and samples
# it only when the label rises to its value after the check of that outcome
# passed. COMBO_PASS + b: CHK-ABR-COMBO (cp_combined_cmd); SINGLE_PASS + b:
# CHK-ABR-PARK of the single-step cell with its result windows equal to the
# vector (x_op_protocol single-step cells); REARM_PASS + b: CHK-ABR-REARM
# (x_op_protocol ready-after-zeroize and ready-after-reset cells).
COMBO_PASS, SINGLE_PASS, REARM_PASS = 1, 3, 5
# clk_i edges the label stays at its value, so the sampler sees the rise.
PASS_HOLD_CYCLES = 2

# MLDSA_CTRL.CTRL 100 = KEYGEN+SIGN (abr_reg.rdl:75), parsed from the RDL text.
CMD_KEYGEN_SIGN = abr_ctrl_cmd("MLDSA_CTRL", "KEYGEN_SIGN")
# Secret output window of ML-DSA KEYGEN (abr_reg.rdl MLDSA_PRIVKEY_OUT).
ABR_PRIVKEY_OUT = ABR_BASE + abr_off("MLDSA_PRIVKEY_OUT")

# Secret output windows read around a re-arm (vplan procedure step 8).
SECRET_WINDOWS = (
    ("MLDSA_PRIVKEY_OUT", ABR_PRIVKEY_OUT, SK_WORDS),
    ("MLKEM_DECAPS_KEY", MLKEM_DECAPS_KEY, KEM_DK_WORDS),
    ("MLKEM_SHARED_KEY", MLKEM_SHARED_KEY, KEM_K_WORDS),
)

COMBINED = ("dsa_keygen_sign", "kem_keygen_decaps")
SINGLE = ("dsa_keygen", "dsa_sign", "dsa_verify", "kem_keygen", "kem_encaps", "kem_decaps")
REARMS = ("zeroize", "reset")
# The four ACVP reason values of the external-mu sigVer reject cases.
REASON_CLASSES = (
    "modified message",
    "modified signature - commitment",
    "modified signature - hint",
    "modified signature - z",
)
# ACVP rows that the open single-step tests grade; the draws exclude them.
OPEN_SV_REJECT_TCID = 151
OPEN_KEM_MODIFIED_TCID = 96

# Outer limits of the bounded waits (environment choice, logged as bound=).
# The VALID limit is 8000 polls of 200 clocks: about 15 times the longest
# command of a clean run, so a command that never completes fails in minutes.
VALID_POLLS = 8_000
VALID_GAP = 200
READY_POLLS = 4_000
READY_GAP = 20

# Command Y of the parked leg of each combined cell: (CTRL value, output
# windows as (name, address, words)). A run of Y changes one of these windows
# from its value at the park (CTRL-ABR-PARKED-DIFF).
PARKED_Y: dict[str, tuple[int, tuple[tuple[str, int, int], ...]]] = {
    "dsa_keygen_sign": (
        CMD_VERIFY | CTRL_EXTERNAL_MU,
        (("MLDSA_VERIFY_RES", ABR_VERIFY_RES, VERIFY_RES_WORDS),),
    ),
    "kem_keygen_decaps": (
        KEM_CMD_ENCAPS,
        (
            ("MLKEM_CIPHERTEXT", MLKEM_CIPHERTEXT, KEM_CT_WORDS),
            ("MLKEM_SHARED_KEY", MLKEM_SHARED_KEY, KEM_K_WORDS),
        ),
    ),
}
# Inputs of Y staged before X. ML-DSA VERIFYING also reads ``MLDSA_EXTERNAL_MU``
# (X's mu) and ``MLDSA_SIGNATURE`` (X's signature).
PARKED_Y_INPUTS: dict[str, tuple[tuple[int, list[int]], ...]] = {
    "dsa_keygen_sign": ((ABR_PUBKEY, NIST_KG_PK),),
    "kem_keygen_decaps": ((MLKEM_ENCAPS_KEY, NIST_KEM_KG_EK), (MLKEM_MSG, NIST_KEM_ENC_M)),
}


def _row(row, *names):
    """A field of a loader row, by attribute or by key (first name that exists)."""
    for name in names:
        if isinstance(row, dict) and name in row:
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
    raise KeyError(f"loader row has none of {names}")


def _tcid(row) -> int:
    return int(_row(row, "tcid", "tc_id", "tcId"))


# One row per single-step cell: (inputs, expected result windows). ``inputs`` is
# a tuple of (window, words); ``expected`` is a tuple of (window name, address,
# words). The tables of the open helpers hold one row per cell.
_DSA_VERIFY_ROWS = ((NIST_SV_OK_PK, NIST_SV_OK_MU, NIST_SV_OK_SIG),)
SINGLE_ROWS: dict[str, tuple] = {
    "dsa_keygen": ((NIST_KG_SEED, NIST_KG_PK),),
    "dsa_sign": ((NIST_SG_SK, NIST_SG_MU, NIST_SG_SIG),),
    "dsa_verify": _DSA_VERIFY_ROWS,
    "kem_keygen": ((NIST_KEM_KG_D, NIST_KEM_KG_Z, NIST_KEM_KG_EK, NIST_KEM_KG_DK),),
    "kem_encaps": ((NIST_KEM_ENC_EK, NIST_KEM_ENC_M, NIST_KEM_ENC_C, NIST_KEM_ENC_K),),
    "kem_decaps": ((NIST_KEM_DEC_OK_DK, NIST_KEM_DEC_OK_C, NIST_KEM_DEC_OK_K),),
}


@dataclass
class Plan:
    seed: int
    single: str
    order: list[str]
    rearm: dict[str, str]
    row: int
    reason: str
    reject: object
    kem_rows: list = field(default_factory=list)
    entropy: list[int] = field(default_factory=list)

    def line(self) -> str:
        kem = ",".join(str(_tcid(r)) for r in self.kem_rows)
        rearm = ",".join(f"{c}:{self.rearm[c]}" for c in self.order)
        return (
            f"PLAN seed={self.seed} single={self.single} order={','.join(self.order)} "
            f"rearm={rearm} row={self.row} reason='{self.reason}' "
            f"reject_tcid={_tcid(self.reject)} kem_tcids={kem}"
        )


def draw_plan(seed: int) -> Plan:
    """The whole stimulus plan of one seed, drawn in a fixed order. No simulator access."""
    rng = SepSeededRng(seed)
    single = rng.choice(SINGLE)
    order = [*COMBINED, single]
    rng.shuffle(order)
    rearm = {cell: rng.choice(REARMS) for cell in order}
    row = rng.randrange(len(SINGLE_ROWS[single]))
    reason = rng.choice(REASON_CLASSES)
    rejects = [
        r
        for r in NIST_SV_REJECTS
        if _row(r, "reason") == reason and _tcid(r) != OPEN_SV_REJECT_TCID
    ]
    reject = rng.choice(rejects)
    kem_pool = [r for r in NIST_KEM_DEC_MODIFIED if _tcid(r) != OPEN_KEM_MODIFIED_TCID]
    kem_rows = rng.sample(kem_pool, 2)
    entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
    return Plan(seed, single, order, rearm, row, reason, reject, kem_rows, entropy)


@dataclass(frozen=True)
class _Block:
    name: str
    ctrl: int
    status: int
    ready: int
    valid: int
    error: int
    zeroize: int


DSA = _Block("dsa", ABR_CTRL, ABR_STATUS, ST_READY, ST_VALID, ST_ERROR, CTRL_ZEROIZE)
KEM = _Block(
    "kem", MLKEM_CTRL, MLKEM_STATUS, KEM_ST_READY, KEM_ST_VALID, KEM_ST_ERROR, KEM_CTRL_ZEROIZE
)


def _block(cell: str) -> _Block:
    return DSA if cell.startswith("dsa") else KEM


def _first_diff(got: list[int], exp: list[int]) -> int | None:
    if len(got) != len(exp):
        return min(len(got), len(exp))
    return next((i for i, (g, e) in enumerate(zip(got, exp)) if g != e), None)


@pyuvm.test()
class sep_abr_command_matrix_rand_test(sep_base_test):
    """Combined ABR commands park and re-arm; single-step order independence; ACVP rejects."""

    required_evidence = (
        "CHK-ABR-COMBO",
        "CHK-ABR-PARK",
        "CHK-ABR-REARM",
        "CHK-ABR-ORDER",
        "CHK-ABR-TAMPER",
        "CHK-ABR-KEM-FLIP",
        "CHK-ABR-PARKED-CMD",
    )

    # --- graded window ------------------------------------------------------
    def _win(self, on: bool) -> None:
        if on and self._win_dead:
            return
        if on == self._win_open:
            return
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)
        self._win_open = on

    def _ok(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check. A FAIL closes the graded window for the rest of the leaf."""
        if not cond:
            self._win(False)
            self._win_dead = True
        return self.chk.ok(name, cond, **fields)

    def _ctl(self, name: str, cond: bool, **fields) -> bool:
        """Log one control. A missing control closes the graded window for the rest of the leaf."""
        if not cond:
            self._win(False)
            self._win_dead = True
        return self.chk.ctrl(name, cond, **fields)

    async def _pass_label(self, base: int, blk: _Block) -> None:
        """Write the FCOV pass label of ``blk`` after its check passed, hold it, write 0.

        Called only after the owning check passed, with the graded window open.
        """
        if not self._win_open:
            return
        set_abr_cmd_pass(base + (0 if blk is DSA else 1), self.logger)
        await ClockCycles(cocotb.top.clk_i, PASS_HOLD_CYCLES)
        set_abr_cmd_pass(0, self.logger)
        await ClockCycles(cocotb.top.clk_i, 1)

    def _clk_now(self) -> int:
        """Simulation time in whole ``clk_i`` periods."""
        return int(get_sim_time("ps")) // self._clk_ps

    # --- register access ----------------------------------------------------
    async def _status(self, blk: _Block) -> int:
        return await self.abr.rd32(blk.status) & (blk.ready | blk.valid | blk.error)

    async def _poll(self, blk: _Block, mask: int, polls: int, gap: int) -> int | None:
        """First STATUS read with a bit of ``mask`` set; None when the bound expires."""
        for _ in range(polls):
            st = await self._status(blk)
            if st & mask:
                return st
            await ClockCycles(cocotb.top.clk_i, gap)
        return None

    async def _wait_ready(self, blk: _Block) -> int | None:
        return await self._poll(blk, blk.ready, READY_POLLS, READY_GAP)

    async def _wait_valid(self, blk: _Block) -> int | None:
        return await self._poll(blk, blk.valid | blk.error, VALID_POLLS, VALID_GAP)

    def _fields(self, blk: _Block, st: int) -> dict:
        return {
            "valid": int(bool(st & blk.valid)),
            "ready": int(bool(st & blk.ready)),
            "obs_error": int(bool(st & blk.error)),
        }

    async def _abr_reset(self) -> None:
        """ABR software reset: SW_RESET_N bit 6 low, then high."""
        await self.swrst.park("abr")
        await self.swrst.release("abr")

    async def _recover(self, where: str) -> None:
        """Clean-up after a timed-out wait: ABR reset, bounded READY wait on both blocks."""
        was_open = self._win_open
        self._win(False)
        self.logger.info("ABR-RECOVER seed=%d where=%s", self.seed, where)
        await self._abr_reset()
        for blk in (DSA, KEM):
            if await self._wait_ready(blk) is None:
                raise AssertionError(
                    f"ABR {blk.name} READY did not return within {READY_POLLS}x{READY_GAP} "
                    f"clocks after the recovery reset ({where})"
                )
        self._win(was_open)

    async def _command(self, blk: _Block, inputs, cmd: int) -> tuple[int | None, str]:
        """READY wait, input writes, command write, VALID wait.

        Returns ``(STATUS, "")`` at the first read with VALID or ERROR set, or
        ``(None, reason)`` when a bounded wait expired. ``self.cmd_clocks``
        holds the clocks from the end of the command write to that read.
        """
        st_pre = await self._wait_ready(blk)
        if st_pre is None:
            return None, f"ready_timeout bound={READY_POLLS}x{READY_GAP}"
        self._ctl(
            "ABR-VALID-PRE",
            not st_pre & blk.valid,
            block=blk.name,
            cmd=f"0x{cmd:x}",
            valid=int(bool(st_pre & blk.valid)),
            ready=int(bool(st_pre & blk.ready)),
        )
        for addr, words in inputs:
            await self.abr.write_words(addr, list(words))
        await self.abr.wr32(blk.ctrl, cmd)
        t_b = self._clk_now()
        st = await self._wait_valid(blk)
        if st is None:
            return None, f"valid_timeout bound={VALID_POLLS}x{VALID_GAP}"
        self.cmd_clocks = self._clk_now() - t_b
        return st, ""

    async def _zeroize(self, blk: _Block) -> int | None:
        """ZEROIZE of ``blk`` and a bounded READY wait; STATUS at READY or None."""
        await self.abr.wr32(blk.ctrl, blk.zeroize)
        return await self._wait_ready(blk)

    async def _windows(self) -> dict[str, list[int]]:
        return {name: await self.abr.read_words(addr, n) for name, addr, n in SECRET_WINDOWS}

    # --- parked command (CHK-ABR-PARKED-CMD) --------------------------------
    async def _read_out(self, outs) -> dict[str, list[int]]:
        return {name: await self.abr.read_words(addr, n) for name, addr, n in outs}

    async def _parked_pre(self, cell: str) -> None:
        """Y alone from READY on the block of ``cell``, graded window closed.

        Records T_Y (``self.pk_ty``) and Y's outputs G (``self.pk_g``). ML-DSA
        VERIFYING verifies the signature that X leaves, so X runs alone first
        and its signature is the pre-run input (``self.pk_sig_pre``).
        """
        blk = _block(cell)
        ycmd, outs = PARKED_Y[cell]
        base = {"block": blk.name, "cmd": f"0x{ycmd:x}"}
        was_open = self._win_open
        self._win(False)
        y_inputs = list(PARKED_Y_INPUTS[cell])
        if cell == "dsa_keygen_sign":
            _, x_inputs, x_cmd = self._cell_inputs(cell, self.plan.row)
            st, why = await self._command(blk, x_inputs, x_cmd)
            if st is None:
                self._ctl("ABR-PARKED-Y", False, **base, step="x_alone", reason=why)
                await self._recover(f"{cell}/parked-pre-x")
                return
            self.pk_sig_pre = await self.abr.read_words(ABR_SIGNATURE, SIG_WORDS)
            if await self._zeroize(blk) is None:
                self._ctl("ABR-PARKED-Y", False, **base, step="x_zeroize", reason="ready_timeout")
                await self._recover(f"{cell}/parked-pre-x")
                return
            y_inputs += [(ABR_EXTERNAL_MU, NIST_SG_MU), (ABR_SIGNATURE, self.pk_sig_pre)]
        st, why = await self._command(blk, y_inputs, ycmd)
        if st is None:
            self._ctl("ABR-PARKED-Y", False, **base, step="y_alone", reason=why)
            await self._recover(f"{cell}/parked-pre-y")
            return
        t_y = self.cmd_clocks
        g = await self._read_out(outs)
        valid = int(bool(st & blk.valid))
        if cell == "dsa_keygen_sign":
            # A verified signature: MLDSA_VERIFY_RES == c~ (abr_reg.rdl:171-173).
            c_tilde = self.pk_sig_pre[:VERIFY_RES_WORDS]
            bad = _first_diff(g["MLDSA_VERIFY_RES"], c_tilde)
            ok = valid == 1 and bad is None
            detail = {
                "verify_res_eq_c": int(bad is None),
                "first_diff": "none" if bad is None else bad,
            }
        else:
            # No published vector for this key and message: Y completes and both
            # outputs hold a non-zero word.
            nz = {name: int(any(words)) for name, words in g.items()}
            ok = valid == 1 and all(nz.values())
            detail = {f"{name.lower()}_nonzero": v for name, v in nz.items()}
        ok = self._ctl("ABR-PARKED-Y", ok and t_y > 0, **base, valid=valid, t_y=t_y, **detail)
        if await self._zeroize(blk) is None:
            self._ctl("ABR-PARKED-Y", False, **base, step="y_zeroize", reason="ready_timeout")
            await self._recover(f"{cell}/parked-pre-y")
            return
        if ok:
            self.pk_ty[cell] = t_y
            self.pk_g[cell] = g
        self._win(was_open)

    async def _parked_leg(self, cell: str, park_ok: bool) -> None:
        """Y's CTRL written while X is parked; Y must not run.

        Order: P and the input probes, Y's CTRL (no ZEROIZE), a wait of
        2 x T_Y + VALID_GAP clocks with no STATUS read, the output windows
        (== P), then one STATUS read (VALID 1, READY 0). The STATUS read is the
        event that ``sep_abr_completion_cg.cp_parked_cmd`` samples, so it runs
        only after the window compare passed.
        """
        blk = _block(cell)
        ycmd, outs = PARKED_Y[cell]
        name = "ABR-PARKED-CMD"
        base = {"block": blk.name, "cmd": f"0x{ycmd:x}"}
        if not park_ok:
            self._ok(name, False, **base, reason="not_parked")
            return
        if cell not in self.pk_g:
            self._ok(name, False, **base, reason="no_pre_run")
            return
        g = self.pk_g[cell]
        t_y = self.pk_ty[cell]
        p = await self._read_out(outs)

        if cell == "dsa_keygen_sign":
            pk = await self.abr.read_words(ABR_PUBKEY, PK_WORDS)
            sig = list(self.combo_sig or [])
            pk_bad = _first_diff(pk, list(NIST_KG_PK))
            sig_bad = _first_diff(sig, list(self.pk_sig_pre or []))
            inputs_ok = pk_bad is None and sig_bad is None
            probe = {
                "pubkey_first_diff": "none" if pk_bad is None else pk_bad,
                "signature_first_diff": "none" if sig_bad is None else sig_bad,
            }
        else:
            ek = await self.abr.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
            ek_bad = _first_diff(ek, list(NIST_KEM_KG_EK))
            inputs_ok = ek_bad is None
            probe = {"encaps_key_first_diff": "none" if ek_bad is None else ek_bad}
            msg = await self.abr.read_words(MLKEM_MSG, KEM_MSG_WORDS)
            self.chk.obs(
                "ABR-PARKED-MSG",
                block=blk.name,
                match=sum(int(a == b) for a, b in zip(msg, NIST_KEM_ENC_M)),
                words=KEM_MSG_WORDS,
                nonzero=int(any(msg)),
            )
        if not self._ctl("ABR-PARKED-INPUTS", inputs_ok, **base, **probe):
            return
        differ = [n for n in p if p[n] != g[n]]
        if not self._ctl(
            "ABR-PARKED-DIFF", bool(differ), **base, differ=",".join(differ) or "none"
        ):
            return

        # Y's command while parked; no ZEROIZE bit. ``wr32`` raises unless the
        # write response is OKAY, so ``ctrl_b=okay`` shows that the write reached ABR.
        await self.abr.wr32(blk.ctrl, ycmd)
        base["ctrl_b"] = "okay"
        w = 2 * t_y + VALID_GAP
        if not self._ctl("ABR-PARKED-BOUND", t_y > 0 and w > t_y, **base, t_y=t_y, w=w):
            return
        await ClockCycles(cocotb.top.clk_i, w)

        got = await self._read_out(outs)
        sizes = ",".join(f"{n}:{len(p[n])}" for n in p)
        moved = [(n, _first_diff(got[n], p[n])) for n in p if got[n] != p[n]]
        if moved:
            n, i = moved[0]
            g_w = got[n][i] if i < len(got[n]) else None
            self._ok(
                name,
                False,
                **base,
                t_y=t_y,
                w=w,
                windows=sizes,
                reason="window_changed",
                first_diff=f"{n}@{i}:got={g_w!s}/exp=0x{p[n][i]:08x}",
            )
            return
        st = await self._status(blk)
        f = self._fields(blk, st)
        self._ok(
            name,
            f["valid"] == 1 and f["ready"] == 0,
            **base,
            t_y=t_y,
            w=w,
            windows=sizes,
            first_diff="none",
            **f,
        )

    # --- cells --------------------------------------------------------------
    def _cell_inputs(self, cell: str, row: int) -> tuple[_Block, list, int]:
        ent = (ABR_ENTROPY, self.plan.entropy)
        if cell == "dsa_keygen_sign":
            return (
                DSA,
                [
                    *PARKED_Y_INPUTS[cell],
                    (ABR_SEED, NIST_KG_SEED),
                    (ABR_EXTERNAL_MU, NIST_SG_MU),
                    ent,
                ],
                CMD_KEYGEN_SIGN | CTRL_EXTERNAL_MU,
            )
        if cell == "kem_keygen_decaps":
            return (
                KEM,
                [
                    *PARKED_Y_INPUTS[cell],
                    (MLKEM_SEED_D, NIST_KEM_KG_D),
                    (MLKEM_SEED_Z, NIST_KEM_KG_Z),
                    (MLKEM_CIPHERTEXT, NIST_KEM_DEC_OK_C),
                ],
                KEM_CMD_KEYGEN_DECAPS,
            )
        r = SINGLE_ROWS[cell][row]
        if cell == "dsa_keygen":
            return DSA, [(ABR_SEED, r[0]), ent], CMD_KEYGEN
        if cell == "dsa_sign":
            return (
                DSA,
                [(ABR_PRIVKEY_IN, r[0]), (ABR_EXTERNAL_MU, r[1]), ent],
                CMD_SIGN | CTRL_EXTERNAL_MU,
            )
        if cell == "dsa_verify":
            return (
                DSA,
                [(ABR_PUBKEY, r[0]), (ABR_EXTERNAL_MU, r[1]), (ABR_SIGNATURE, r[2])],
                CMD_VERIFY | CTRL_EXTERNAL_MU,
            )
        if cell == "kem_keygen":
            return KEM, [(MLKEM_SEED_D, r[0]), (MLKEM_SEED_Z, r[1])], KEM_CMD_KEYGEN
        if cell == "kem_encaps":
            return KEM, [(MLKEM_ENCAPS_KEY, r[0]), (MLKEM_MSG, r[1])], KEM_CMD_ENCAPS
        if cell == "kem_decaps":
            return KEM, [(MLKEM_DECAPS_KEY, r[0]), (MLKEM_CIPHERTEXT, r[1])], KEM_CMD_DECAPS
        raise KeyError(cell)

    def _cell_expect(self, cell: str, row: int) -> list[tuple[str, int, list[int]]]:
        """The result windows the open helper of ``cell`` compares, with the vector."""
        r = SINGLE_ROWS[cell][row]
        if cell == "dsa_keygen":
            return [("MLDSA_PUBKEY", ABR_PUBKEY, list(r[1]))]
        if cell == "dsa_sign":
            return [("MLDSA_SIGNATURE", ABR_SIGNATURE, list(r[2]))]
        if cell == "dsa_verify":
            return [("MLDSA_VERIFY_RES", ABR_VERIFY_RES, list(r[2][:VERIFY_RES_WORDS]))]
        if cell == "kem_keygen":
            return [
                ("MLKEM_ENCAPS_KEY", MLKEM_ENCAPS_KEY, list(r[2])),
                ("MLKEM_DECAPS_KEY", MLKEM_DECAPS_KEY, list(r[3])),
            ]
        if cell == "kem_encaps":
            return [
                ("MLKEM_CIPHERTEXT", MLKEM_CIPHERTEXT, list(r[2])),
                ("MLKEM_SHARED_KEY", MLKEM_SHARED_KEY, list(r[3])),
            ]
        if cell == "kem_decaps":
            return [("MLKEM_SHARED_KEY", MLKEM_SHARED_KEY, list(r[2]))]
        raise KeyError(cell)

    async def _trial(self, cell: str, via: str) -> None:
        """Steps 4-9 of one trial: inputs, command, results, park read, re-arm."""
        combined = cell in COMBINED
        owner = "ABR-COMBO" if combined else "ABR-ORDER"
        blk, inputs, cmd = self._cell_inputs(cell, self.plan.row)
        if combined:
            await self._parked_pre(cell)
        self.ops.append(cell)

        st, why = await self._command(blk, inputs, cmd)
        if st is None:
            self._ok(owner, False, cell=cell, reason="timeout", detail=why, ops=self._ops())
            if not combined:
                self.order_done = True
            await self._recover(f"{cell}/command")
            return
        f = self._fields(blk, st)
        if combined:
            # First STATUS read with VALID: VALID=1 and READY=0 (adams_bridge.adoc:186-189).
            combo_ok = self._ok(
                "ABR-COMBO", f["valid"] == 1 and f["ready"] == 0, cell=cell, via=via, **f
            )
            if combo_ok:
                await self._pass_label(COMBO_PASS, blk)
        else:
            self.chk.obs("ABR-SINGLE-STATUS", cell=cell, **f)

        # Step 6: result windows.
        if cell == "dsa_keygen_sign":
            self.combo_sig = await self.abr.read_words(ABR_SIGNATURE, SIG_WORDS)
        elif not combined:
            mism = []
            for name, addr, exp in self._cell_expect(cell, self.plan.row):
                got = await self.abr.read_words(addr, len(exp))
                bad = _first_diff(got, exp)
                if bad is not None:
                    g = got[bad] if bad < len(got) else None
                    mism.append(f"{name}@{bad}:got={g!s}/exp=0x{exp[bad]:08x}")
            self.single_result = mism

        # Step 7: park read before the re-arm.
        st_park = await self._status(blk)
        fp = self._fields(blk, st_park)
        park_ok = fp["ready"] == 0 and (fp["valid"] == 1 if combined else True)
        park_pass = self._ok("ABR-PARK", park_ok, cell=cell, **fp)
        if park_pass and not combined and self.single_result == []:
            # The single-step outcome samples only after its park read passed and
            # its result windows equal the vector (the compare CHK-ABR-ORDER grades).
            await self._pass_label(SINGLE_PASS, blk)
        if combined:
            await self._parked_leg(cell, park_ok)

        pre: dict[str, list[int]] = {}
        if combined and via == "zeroize":
            pre = await self._windows()
            for name, words in pre.items():
                self.logger.info(
                    "CTRL-ABR-SECRET-PRE seed=%d cell=%s window=%s nonzero=%d",
                    self.seed,
                    cell,
                    name,
                    int(any(words)),
                )

        # Step 8 or 9: the re-arm.
        if via == "zeroize":
            st_r = await self._zeroize(blk)
        else:
            await self._abr_reset()
            st_r = await self._wait_ready(blk)
        if st_r is None:
            if combined:
                self._ok(
                    "ABR-REARM",
                    False,
                    cell=cell,
                    via=via,
                    ready=0,
                    reason="timeout",
                    bound=f"{READY_POLLS}x{READY_GAP}",
                )
            else:
                self._ctl("ABR-PARK", False, cell=cell, via=via, ready_after_rearm=0)
            await self._recover(f"{cell}/rearm")
            return
        fr = self._fields(blk, st_r)
        self.chk.obs("ABR-VALID", cell=cell, via=via, valid=fr["valid"])
        if not combined:
            self._ctl("ABR-PARK", fr["ready"] == 1, cell=cell, via=via, ready_after_rearm=1)
            return

        post = await self._windows()
        if via == "reset":
            for name, words in post.items():
                self.chk.obs("ABR-RESET-WINDOW", cell=cell, window=name, nonzero=int(any(words)))
            if self._ok("ABR-REARM", True, cell=cell, via=via, ready=1, secret_window="n/a"):
                await self._pass_label(REARM_PASS, blk)
            return
        live = []
        states = []
        graded = 0
        for name, words in post.items():
            if not any(pre[name]):
                self.chk.obs("ABR-SECRET-EMPTY", cell=cell, window=name)
                states.append(f"{name}:empty")
                continue
            graded += 1
            nz = [i for i, w in enumerate(words) if w]
            states.append(f"{name}:{'0' if not nz else 'live'}")
            if nz:
                live.append(f"{name}@{nz[0]}=0x{words[nz[0]]:08x}")
        # The KEM cell outputs DECAPS_KEY and SHARED_KEY, so its leg must grade a window.
        min_graded = 1 if cell == "kem_keygen_decaps" else 0
        if graded == 0 and min_graded == 0:
            self.chk.blocked("ABR-REARM", f"secret_wipe_{cell}_fills_no_secret_window")
        rearm_ok = self._ok(
            "ABR-REARM",
            not live and graded >= min_graded,
            cell=cell,
            via=via,
            ready=1,
            secret_window=",".join(states),
            graded_windows=graded,
            min_graded=min_graded,
            live=",".join(live) or "none",
        )
        if rearm_ok:
            await self._pass_label(REARM_PASS, blk)

    def _ops(self) -> str:
        return ">".join(self.ops) or "none"

    # --- after the trials ---------------------------------------------------
    async def _verify(self, pk, mu, sig) -> tuple[list[int] | None, int | None, str]:
        """ML-DSA VERIFYING with external mu; returns (VERIFY_RES, STATUS, reason)."""
        st, why = await self._command(
            DSA,
            [(ABR_PUBKEY, pk), (ABR_EXTERNAL_MU, mu), (ABR_SIGNATURE, sig)],
            CMD_VERIFY | CTRL_EXTERNAL_MU,
        )
        if st is None:
            return None, None, why
        res = await self.abr.read_words(ABR_VERIFY_RES, VERIFY_RES_WORDS)
        return res, st, ""

    async def _zeroize_or_recover(self, blk: _Block, where: str) -> None:
        if await self._zeroize(blk) is None:
            self.chk.obs("ABR-ZEROIZE-TIMEOUT", where=where, bound=f"{READY_POLLS}x{READY_GAP}")
            await self._recover(where)

    async def _combo_verify(self) -> None:
        """Steps 10-11: verify the combined signature; logged only."""
        if self.combo_sig is None:
            self.chk.obs("ABR-COMBO-VERIFY", verify="n/a", reason="no_signature")
            return
        st, why = await self._command(
            DSA, [(ABR_SEED, NIST_KG_SEED), (ABR_ENTROPY, self.plan.entropy)], CMD_KEYGEN
        )
        if st is None:
            self.chk.obs("ABR-COMBO-VERIFY", verify="n/a", reason=why)
            await self._recover("combo-verify/keygen")
            return
        pk = await self.abr.read_words(ABR_PUBKEY, PK_WORDS)
        await self._zeroize_or_recover(DSA, "combo-verify/keygen")
        res, st, why = await self._verify(pk, NIST_SG_MU, self.combo_sig)
        if res is None:
            self.chk.obs("ABR-COMBO-VERIFY", verify="n/a", reason=why)
            await self._recover("combo-verify/verify")
            return
        accept = res == list(self.combo_sig[:VERIFY_RES_WORDS])
        self.chk.obs("ABR-COMBO-VERIFY", verify="accept" if accept else "reject")
        await self._zeroize_or_recover(DSA, "combo-verify/verify")

    async def _tamper(self) -> None:
        """Steps 12-13: accept control, then the drawn ACVP reject case."""
        res, st, why = await self._verify(NIST_SV_OK_PK, NIST_SV_OK_MU, NIST_SV_OK_SIG)
        control_accept = 0
        if res is None:
            self._ctl("ABR-TAMPER", False, case="accept", reason=why)
            await self._recover("tamper/control")
        else:
            c_ok = list(NIST_SV_OK_SIG[:VERIFY_RES_WORDS])
            control_accept = int(res == c_ok)
            self._ctl("ABR-TAMPER", bool(control_accept), case="accept", eq_c=control_accept)
            await self._zeroize_or_recover(DSA, "tamper/control")

        # Error injection: the published reject case (modified mu or signature part).
        rej = self.plan.reject
        tcid = _tcid(rej)
        sig = list(_row(rej, "sig", "signature"))
        self._win(True)
        # FCOV stimulus label of the reject verify: 1-based index of the ACVP reason
        # class (the order of REASON_CLASSES is the sampler's class order). It stays
        # set until the reject verify has ended, and is 0 for every other verify.
        set_abr_reject_class(REASON_CLASSES.index(self.plan.reason) + 1, self.logger)
        res, st, why = await self._verify(_row(rej, "pk"), _row(rej, "mu"), sig)
        if res is None:
            self._ok("ABR-TAMPER", False, tcid=tcid, reason_class=self.plan.reason, reason=why)
            await self._recover("tamper/reject")
            set_abr_reject_class(0, self.logger)
            return
        c_tilde = sig[:VERIFY_RES_WORDS]
        bad = _first_diff(res, c_tilde)
        self.chk.obs("ABR-TAMPER-ERROR", tcid=tcid, error=int(bool(st & ST_ERROR)))
        self._ok(
            "ABR-TAMPER",
            bad is not None and len(res) == VERIFY_RES_WORDS,
            tcid=tcid,
            reason=self.plan.reason.replace(" ", "_"),
            verify_res_eq_c=int(bad is None),
            first_diff_word=bad if bad is not None else "none",
            res="".join(f"{w:08x}" for w in res),
            c="".join(f"{w:08x}" for w in c_tilde),
            control_accept=control_accept,
        )
        await self._zeroize_or_recover(DSA, "tamper/reject")
        set_abr_reject_class(0, self.logger)

    async def _decaps(self, dk, c) -> tuple[list[int] | None, str]:
        st, why = await self._command(
            KEM, [(MLKEM_DECAPS_KEY, dk), (MLKEM_CIPHERTEXT, c)], KEM_CMD_DECAPS
        )
        if st is None:
            return None, why
        return await self.abr.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS), ""

    async def _kem_flip(self) -> None:
        """Steps 14-15: valid-decapsulation control, then two modified-ciphertext cases."""
        self._win(False)
        ss, why = await self._decaps(NIST_KEM_DEC_OK_DK, NIST_KEM_DEC_OK_C)
        if ss is None:
            self._ctl("ABR-KEM-FLIP", False, case="valid", reason=why)
            await self._recover("kem/control")
        else:
            ok = ss == list(NIST_KEM_DEC_OK_K)
            self._ctl("ABR-KEM-FLIP", ok, case="valid", ss_eq_k=int(ok))
            await self._zeroize_or_recover(KEM, "kem/control")

        self._win(True)
        for row in self.plan.kem_rows:
            tcid = _tcid(row)
            k_exp = list(_row(row, "K", "k", "ss"))
            ss, why = await self._decaps(_row(row, "dk"), _row(row, "c", "ct"))
            if ss is None:
                self._ok("ABR-KEM-FLIP", False, tcid=tcid, reason=why)
                await self._recover(f"kem/{tcid}")
                continue
            eq = ss == k_exp
            self._ok(
                "ABR-KEM-FLIP",
                eq,
                tcid=tcid,
                **{"ss==K": int(eq)},
                ss="".join(f"{w:08x}" for w in ss),
                k="".join(f"{w:08x}" for w in k_exp),
            )
            await self._zeroize_or_recover(KEM, f"kem/{tcid}")

    # --- scenario -----------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.plan = draw_plan(self.seed)
        self.chk = SepChkLog(self, TEST, self.seed)
        self._win_open = False
        self._win_dead = False
        self._clk_ps = round(self.cfg.sys_clk_period_ns * 1000)
        self.cmd_clocks = 0
        self.pk_ty: dict[str, int] = {}
        self.pk_g: dict[str, dict[str, list[int]]] = {}
        self.pk_sig_pre: list[int] | None = None
        self.ops: list[str] = []
        self.combo_sig: list[int] | None = None
        self.single_result: list[str] | None = None
        self.order_done = False

        # Step 1: KMAC, AES, HMAC and OTBN parked; ABR (bit 6) released.
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))
        if getattr(self, "swrst", None) is None:
            self.swrst = SepSwReset(self)
        await self.swrst.release("abr")
        base = await self.swrst.read_back()
        self.logger.info("SW_RESET_N baseline seed=%d value=0x%08x", self.seed, base)
        self.abr = SepAbr(self)

        # Step 2.
        self.logger.info("%s", self.plan.line())

        try:
            await self._graded_steps()
        except BaseException:
            self._win(False)
            self._win_dead = True
            raise
        self.chk.finish()

    async def _graded_steps(self) -> None:
        """Steps 3-15. On a raise, ``run_scenario`` closes the graded window before the error propagates."""
        # Steps 3-9.
        self._win(True)
        for cell in self.plan.order:
            await self._trial(cell, self.plan.rearm[cell])

        if not self.order_done:
            mism = self.single_result
            self._ok(
                "ABR-ORDER",
                mism is not None and not mism,
                cell=self.plan.single,
                ops=self._ops(),
                all_match=int(mism is not None and not mism),
                mismatch=";".join(mism or []) or "none",
            )

        # Steps 10-11 (logged only) and the tamper control: window closed.
        self._win(False)
        await self._combo_verify()
        await self._tamper()
        await self._kem_flip()
        self._win(False)

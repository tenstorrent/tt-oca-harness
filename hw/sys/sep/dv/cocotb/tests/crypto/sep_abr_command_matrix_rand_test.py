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
                    a non-zero word reads 0.
  CHK-ABR-ORDER     the single-step result equals its ACVP vector whatever ran
                    before it.
  CHK-ABR-TAMPER    for the drawn reject case ``MLDSA_VERIFY_RES`` differs from
                    c~ (the first 16 signature words as written).
  CHK-ABR-KEM-FLIP  each drawn modified-ciphertext case returns its ACVP key K.

``STATUS.ERROR`` is logged and not graded. The RDL describes the bit
(``integration/rdl/sep/abr_reg.rdl``:97 and :344, "the process ended with an
error"; field text :106 and :352, "Status error bit") and states no rule for
the value at the end of a combined command, and ``adams_bridge.adoc``:186-189
names only ``VALID`` and ``READY``. CHK-ABR-COMBO and CHK-ABR-PARK carry it in
an ``obs_error`` field.

Controls: ``CTRL-ABR-PARK`` (READY reads 1 after the re-arm of the
single-step cell), ``CTRL-ABR-TAMPER`` (the ACVP accept case gives c~),
``CTRL-ABR-KEM-FLIP`` (the valid decapsulation case gives its K).
``CTRL-ABR-SECRET-PRE`` logs which secret windows held a non-zero word before a
ZEROIZE; a window that held none logs ``OBS-ABR-SECRET-EMPTY`` and is not
graded. A zero window proves that the window is not readable, not that the
memory is wiped.

Waits are bounded. A wait that times out logs the owning check as FAIL with
``reason=timeout``, resets ABR and continues with the next step; the leaf fails
at the end.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``. RAND-REP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
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
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_abr_reject_class
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
    KEM_CTRL_ZEROIZE,
    KEM_DK_WORDS,
    KEM_K_WORDS,
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
    )

    # --- graded window ------------------------------------------------------
    def _win(self, on: bool) -> None:
        if on == self._win_open:
            return
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)
        self._win_open = on

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
        ``(None, reason)`` when a bounded wait expired.
        """
        if await self._wait_ready(blk) is None:
            return None, f"ready_timeout bound={READY_POLLS}x{READY_GAP}"
        for addr, words in inputs:
            await self.abr.write_words(addr, list(words))
        await self.abr.wr32(blk.ctrl, cmd)
        st = await self._wait_valid(blk)
        if st is None:
            return None, f"valid_timeout bound={VALID_POLLS}x{VALID_GAP}"
        return st, ""

    async def _zeroize(self, blk: _Block) -> int | None:
        """ZEROIZE of ``blk`` and a bounded READY wait; STATUS at READY or None."""
        await self.abr.wr32(blk.ctrl, blk.zeroize)
        return await self._wait_ready(blk)

    async def _windows(self) -> dict[str, list[int]]:
        return {name: await self.abr.read_words(addr, n) for name, addr, n in SECRET_WINDOWS}

    # --- cells --------------------------------------------------------------
    def _cell_inputs(self, cell: str, row: int) -> tuple[_Block, list, int]:
        ent = (ABR_ENTROPY, self.plan.entropy)
        if cell == "dsa_keygen_sign":
            return (
                DSA,
                [(ABR_SEED, NIST_KG_SEED), (ABR_EXTERNAL_MU, NIST_SG_MU), ent],
                CMD_KEYGEN_SIGN | CTRL_EXTERNAL_MU,
            )
        if cell == "kem_keygen_decaps":
            return (
                KEM,
                [
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
        self.ops.append(cell)

        st, why = await self._command(blk, inputs, cmd)
        if st is None:
            self.chk.ok(owner, False, cell=cell, reason="timeout", detail=why, ops=self._ops())
            if not combined:
                self.order_done = True
            await self._recover(f"{cell}/command")
            return
        f = self._fields(blk, st)
        if combined:
            # First STATUS read with VALID: VALID=1 and READY=0 (adams_bridge.adoc:186-189).
            self.chk.ok("ABR-COMBO", f["valid"] == 1 and f["ready"] == 0, cell=cell, via=via, **f)
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
        self.chk.ok("ABR-PARK", park_ok, cell=cell, **fp)

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
                self.chk.ok(
                    "ABR-REARM",
                    False,
                    cell=cell,
                    via=via,
                    ready=0,
                    reason="timeout",
                    bound=f"{READY_POLLS}x{READY_GAP}",
                )
            else:
                self.chk.ctrl("ABR-PARK", False, cell=cell, via=via, ready_after_rearm=0)
            await self._recover(f"{cell}/rearm")
            return
        fr = self._fields(blk, st_r)
        self.chk.obs("ABR-VALID", cell=cell, via=via, valid=fr["valid"])
        if not combined:
            self.chk.ctrl("ABR-PARK", fr["ready"] == 1, cell=cell, via=via, ready_after_rearm=1)
            return

        post = await self._windows()
        if via == "reset":
            for name, words in post.items():
                self.chk.obs("ABR-RESET-WINDOW", cell=cell, window=name, nonzero=int(any(words)))
            self.chk.ok("ABR-REARM", True, cell=cell, via=via, ready=1, secret_window="n/a")
            return
        live = []
        states = []
        for name, words in post.items():
            if not any(pre[name]):
                self.chk.obs("ABR-SECRET-EMPTY", cell=cell, window=name)
                states.append(f"{name}:empty")
                continue
            nz = [i for i, w in enumerate(words) if w]
            states.append(f"{name}:{'0' if not nz else 'live'}")
            if nz:
                live.append(f"{name}@{nz[0]}=0x{words[nz[0]]:08x}")
        self.chk.ok(
            "ABR-REARM",
            not live,
            cell=cell,
            via=via,
            ready=1,
            secret_window=",".join(states),
            live=",".join(live) or "none",
        )

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
            self.chk.ctrl("ABR-TAMPER", False, case="accept", reason=why)
            await self._recover("tamper/control")
        else:
            c_ok = list(NIST_SV_OK_SIG[:VERIFY_RES_WORDS])
            control_accept = int(res == c_ok)
            self.chk.ctrl("ABR-TAMPER", bool(control_accept), case="accept", eq_c=control_accept)
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
            self.chk.ok("ABR-TAMPER", False, tcid=tcid, reason_class=self.plan.reason, reason=why)
            await self._recover("tamper/reject")
            set_abr_reject_class(0, self.logger)
            return
        c_tilde = sig[:VERIFY_RES_WORDS]
        bad = _first_diff(res, c_tilde)
        self.chk.obs("ABR-TAMPER-ERROR", tcid=tcid, error=int(bool(st & ST_ERROR)))
        self.chk.ok(
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
            self.chk.ctrl("ABR-KEM-FLIP", False, case="valid", reason=why)
            await self._recover("kem/control")
        else:
            ok = ss == list(NIST_KEM_DEC_OK_K)
            self.chk.ctrl("ABR-KEM-FLIP", ok, case="valid", ss_eq_k=int(ok))
            await self._zeroize_or_recover(KEM, "kem/control")

        self._win(True)
        for row in self.plan.kem_rows:
            tcid = _tcid(row)
            k_exp = list(_row(row, "K", "k", "ss"))
            ss, why = await self._decaps(_row(row, "dk"), _row(row, "c", "ct"))
            if ss is None:
                self.chk.ok("ABR-KEM-FLIP", False, tcid=tcid, reason=why)
                await self._recover(f"kem/{tcid}")
                continue
            eq = ss == k_exp
            self.chk.ok(
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

        # Steps 3-9.
        self._win(True)
        for cell in self.plan.order:
            await self._trial(cell, self.plan.rearm[cell])

        if not self.order_done:
            mism = self.single_result
            self.chk.ok(
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

        self.chk.finish()

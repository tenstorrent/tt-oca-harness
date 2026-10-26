# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ABR ML-DSA-87 keyGen returns the NIST ACVP public key, and ZEROIZE then clears it.

no_cpu / +skip_fuse_sense, host AXI. Software-written seed path only. The public
key is compared word-for-word against the NIST ACVP vector in
``env/sep_abr_nist.py``. ZEROIZE must drop VALID, and the pubkey window must
then read zero. A second keyGen on the ACVP seed with one bit flipped runs
after ZEROIZE; its public key has no golden in the tree, so it is logged as
``OBS-ABR-KEYGEN-SENSITIVITY`` and not graded. ML-KEM, sign/verify, and the
key-vault seed path are not claimed, and neither is the ABR_ZEROIZE memory walk
itself -- see CHK-ZEROIZE below.

Interrupt legs, inside the graded window of this leaf: PIC source 35 (ABR
error, vector bit 34) rises after an ``error_intr_trig_r`` write and falls
after the ``error_internal_intr_r`` write-one-to-clear; PIC source 36 (ABR
notification, vector bit 35) rises once after the keyGen command and falls
after the ``notif_internal_intr_r`` write-one-to-clear. A per-clock watcher of
the whole vector grades that at each rise of bit 34 or 35 every other vector
bit keeps its value of one clock before. The ``cp_src_exclusive_other`` rise
of each source is held and samples only after its CHK-SRC35-EXCL or
CHK-SRC36-EXCL passed (``exo_pass``, ``env/sep_fcov_gate.set_exo_pass``).
Each ``cp_abr_pic`` edge is held and samples only after the check of that
edge passed (``abr_pic_pass``, ``env/sep_fcov_gate.set_abr_pic_pass``):
CHK-PIC-ERROR-RISE and CHK-PIC-NOTIF-RISE with their exactly-one-rise term,
CHK-PIC-ERROR-W1C and CHK-PIC-NOTIF-W1C. Each label value is held
``_LABEL_CLK`` clocks, so every release samples before the next step.

RANDCFG: masking entropy and the flipped seed bit of the logged keyGen come from
the run seed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_abr_nist import NIST_KG_PK, NIST_KG_SEED
from env.sep_bit_watch import SepVecWatch, VecMark, pic_vector_watch
from env.sep_fcov_gate import (
    ABR_PIC_ERROR_RISE,
    ABR_PIC_ERROR_W1C,
    ABR_PIC_NOTIF_RISE,
    ABR_PIC_NOTIF_W1C,
    close_graded_window,
    exo_pass_bit,
    open_graded_window,
    set_abr_pic_pass,
    set_exo_pass,
)
from env.sep_pic_map import vec_bit, vec_mask
from env.sep_spec_tables import pic
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_ERROR_INTR,
    ABR_NAME0,
    ABR_NAME1,
    ABR_NOTIF_INTR,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    ABR_VERSION0,
    ABR_VERSION1,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    ERROR_INTERNAL_STS,
    IRQ_ABR_ERROR,
    IRQ_ABR_NOTIF,
    NOTIF_CMD_DONE_STS,
    PK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
    SepAbrKeygenCfg,
)

TEST = "sep_abr_mldsa_keygen_kat_test"
# CHK-NIST-PK and CHK-ZEROIZE read MLDSA_PUBKEY at its RDL size; the ACVP
# vector must be the same length.
if PK_WORDS != len(NIST_KG_PK):
    raise ValueError(f"MLDSA_PUBKEY is {PK_WORDS} words, the keyGen vector {len(NIST_KG_PK)}")

# Status poll: 32-bit beat on an odd-word offset, with a cycle gap so a long
# keyGen does not spend the budget on back-to-back AXI. 20000 * 200 cycles is
# the backstop; a hang fails this wait rather than the sim timeout. The whole
# READY + VALID wait stays below the 1 << 24 clock command bound of the
# cp_abr_pic sampler (cov/sv/sep_fcov.sv, CxAbrDoneBound).
_POLL_ITERS = 20000
_POLL_GAP = 200
# Clocks a line has to rise after a trigger write, or to fall after a
# write-one-to-clear, once the write returns. Below the 1024-clock trigger and
# clear bound of the cp_abr_pic sampler (cov/sv/sep_fcov.sv, CyAlertBound).
_LINE_POLLS = 64
# Clocks a pass-label value is held after a check passed. The sampler takes a
# release on the first clock edge after the write; the other clocks drain it,
# so a FAIL that ends the sim right after still finds the release sampled.
_LABEL_CLK = 3

# PIC sources (hw/sys/sep/doc/interrupts.adoc:177-178 source 33 Crypto alert,
# :194-196 source 35 Adams Bridge error, :198-200 source 36 Adams Bridge
# notification); vector bit i is PIC source i + 1 (:22-23).
_SRC_CRYPTO_ALERT = pic("Crypto alert")
_SRC_ABR_ERROR = pic("Adams Bridge error")
_SRC_ABR_NOTIF = pic("Adams Bridge notification")
# Vector bits that may change in the clock of an own-bit rise: the crypto alert
# and the other Adams Bridge line. The cp_src_exclusive_other sampler exempts
# the same bits (cov/sv/sep_fcov.sv, exo_same), so a sample is a rise this
# check passes.
_SAME_CLK_ERROR = vec_mask([_SRC_CRYPTO_ALERT, _SRC_ABR_NOTIF])
_SAME_CLK_NOTIF = vec_mask([_SRC_CRYPTO_ALERT, _SRC_ABR_ERROR])
# Fields of the two status registers (integration/rdl/sep/abr_reg.rdl:515-544,
# one field each, "Sticky, level assertion, write-1-to-clear" at :518 and
# :534). The other bits have no field and no stated value: logged, not graded.
_ERR_RSVD = 0xFFFF_FFFF & ~ERROR_INTERNAL_STS
_NOTIF_RSVD = 0xFFFF_FFFF & ~NOTIF_CMD_DONE_STS


@pyuvm.test()
class sep_abr_mldsa_keygen_kat_test(sep_base_test):
    """ML-DSA-87 keyGen: NIST pk match, PIC sources 35/36, ZEROIZE clears VALID."""

    def _grade(self, name: str, ok: bool, detail: str) -> None:
        """Log CHK-<name> PASS; on FAIL close the graded window first, then raise."""
        if ok:
            self.logger.info("CHK-%s PASS: %s", name, detail)
            return
        close_graded_window(self.logger)
        self.logger.error("CHK-%s FAIL: %s", name, detail)
        raise AssertionError(f"CHK-{name} FAIL: {detail}")

    async def _release_pic(self, bit: int) -> None:
        """Add the abr_pic_pass bit of a cp_abr_pic edge whose check passed; hold it."""
        self._pic_pass |= 1 << bit
        set_abr_pic_pass(self._pic_pass, self.logger)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLK)

    async def _irq(self, idx: int) -> int:
        await RisingEdge(cocotb.top.clk_i)
        # Only bit ``idx`` must be known: it is the bit the must-be-0 and
        # must-be-1 legs compare, and an X there raises instead of reading 0.
        return self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, 1 << idx) >> idx

    async def _poll_irq(self, idx: int, want: int) -> int:
        """Clocks until vector bit ``idx`` reads ``want``, or -1 after _LINE_POLLS clocks."""
        for n in range(1, _LINE_POLLS + 1):
            if await self._irq(idx) == want:
                return n
        return -1

    async def _wait_status(self, abr: SepAbr, mask: int, expect: int, *, what: str) -> int:
        for _ in range(_POLL_ITERS):
            st = await abr.rd32(ABR_STATUS)
            if (st & mask) == expect:
                return st
            if st & ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR set (0x{st:08x})")
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        raise AssertionError(
            f"{what}: STATUS mask 0x{mask:x} never 0x{expect:x} in {_POLL_ITERS} polls"
        )

    async def _load(
        self, abr: SepAbr, seed_words: list[int], entropy: list[int], what: str
    ) -> None:
        """Wait for READY, then write the seed and the masking entropy of one keyGen."""
        await self._wait_status(abr, ST_READY, ST_READY, what=f"{what} READY")
        await abr.write_words(ABR_SEED, seed_words)
        await abr.write_words(ABR_ENTROPY, entropy)

    async def _run_keygen(self, abr: SepAbr, what: str) -> list[int]:
        """Write the keyGen command, wait for VALID with ERROR 0, read the public key."""
        await abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what=f"{what} VALID")
        assert (st & ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        return await abr.read_words(ABR_PUBKEY, PK_WORDS)

    def _grade_exclusive(
        self, name: str, vec: SepVecWatch, mark: VecMark, key: str, same_clock: int, want: int
    ) -> None:
        """Every rise of ``key`` since ``mark`` leaves the other graded vector bits as they were."""
        rises = vec.rises_since(mark, key)
        # smears_since raises when the own bit did not rise; the count term
        # below grades that case as a FAIL line instead.
        smeared = vec.smears_since(mark, key, same_clock=same_clock) if rises else []
        self._grade(
            name,
            len(rises) == want and not smeared,
            f"bit={vec.own[key]} rises={len(rises)} want={want} same_clock=0x{same_clock:011x} "
            f"ignored=0x{vec.ignore_mask:011x} rise_clk={[r.clk for r in rises]} "
            f"before={[f'0x{r.before:011x}' for r in rises]} "
            f"after={[f'0x{r.after:011x}' for r in rises]} "
            f"moved={[f'{c}:0x{m:011x}' for c, m in smeared]}",
        )

    async def _error_leg(self, abr: SepAbr, vec: SepVecWatch) -> None:
        """PIC source 35: rise after the trigger write, status set, fall after the W1C."""
        mark = vec.mark()
        await abr.trigger_error()
        n_rise = await self._poll_irq(IRQ_ABR_ERROR, 1)
        rises = vec.rises_since(mark, "abr_error")
        # integration/rdl/sep/abr_reg.rdl:569-573: the trigger write pulses the
        # trigger bit, which sets the status bit; :518 the status is a level,
        # and :670, :679 and :682 it reaches the error line with both enables set.
        self._grade(
            "PIC-ERROR-RISE",
            n_rise > 0 and len(rises) == 1,
            f"vec[{IRQ_ABR_ERROR}] 0->1 after error_intr_trig_r write: high after {n_rise} "
            f"clocks (bound {_LINE_POLLS}), rises={len(rises)} "
            f"rise_clk_from_write={[r.clk - mark.clk for r in rises]}",
        )
        await self._release_pic(ABR_PIC_ERROR_RISE)

        err_set = await abr.rd32(ABR_ERROR_INTR)
        pre = await self._irq(IRQ_ABR_ERROR)
        await abr.wr32(ABR_ERROR_INTR, ERROR_INTERNAL_STS)
        n_fall = await self._poll_irq(IRQ_ABR_ERROR, 0)
        # integration/rdl/sep/abr_reg.rdl:518: sticky, level, write-1-to-clear.
        self._grade(
            "PIC-ERROR-W1C",
            pre == 1 and n_fall > 0,
            f"vec[{IRQ_ABR_ERROR}]={pre} before the error_internal_intr_r W1C, low after "
            f"{n_fall} clocks (bound {_LINE_POLLS})",
        )
        await self._release_pic(ABR_PIC_ERROR_W1C)
        err_clr = await abr.rd32(ABR_ERROR_INTR)
        self._grade(
            "PIC-ERROR-STS",
            (err_set & ERROR_INTERNAL_STS) == ERROR_INTERNAL_STS
            and (err_clr & ERROR_INTERNAL_STS) == 0,
            f"error_internal_sts=0x{err_set & ERROR_INTERNAL_STS:x} after trigger "
            f"(want 0x{ERROR_INTERNAL_STS:x}), 0x{err_clr & ERROR_INTERNAL_STS:x} after W1C "
            "(want 0)",
        )
        self.logger.info(
            "OBS-ABR-ERROR-INTR-RSVD: error_internal_intr_r bits outside error_internal_sts "
            "0x%08x after trigger, 0x%08x after W1C",
            err_set & _ERR_RSVD,
            err_clr & _ERR_RSVD,
        )

    async def _notif_w1c_leg(self, abr: SepAbr) -> None:
        """PIC source 36: status set after keyGen, fall after the W1C."""
        notif_set = await abr.rd32(ABR_NOTIF_INTR)
        pre = await self._irq(IRQ_ABR_NOTIF)
        await abr.wr32(ABR_NOTIF_INTR, NOTIF_CMD_DONE_STS)
        n_fall = await self._poll_irq(IRQ_ABR_NOTIF, 0)
        # integration/rdl/sep/abr_reg.rdl:534: sticky, level, write-1-to-clear.
        self._grade(
            "PIC-NOTIF-W1C",
            pre == 1 and n_fall > 0,
            f"vec[{IRQ_ABR_NOTIF}]={pre} before the notif_internal_intr_r W1C, low after "
            f"{n_fall} clocks (bound {_LINE_POLLS})",
        )
        await self._release_pic(ABR_PIC_NOTIF_W1C)
        notif_clr = await abr.rd32(ABR_NOTIF_INTR)
        self._grade(
            "PIC-NOTIF-STS",
            (notif_set & NOTIF_CMD_DONE_STS) == NOTIF_CMD_DONE_STS
            and (notif_clr & NOTIF_CMD_DONE_STS) == 0,
            f"notif_cmd_done_sts=0x{notif_set & NOTIF_CMD_DONE_STS:x} after keyGen "
            f"(want 0x{NOTIF_CMD_DONE_STS:x}), 0x{notif_clr & NOTIF_CMD_DONE_STS:x} after W1C "
            "(want 0)",
        )
        self.logger.info(
            "OBS-ABR-NOTIF-INTR-RSVD: notif_internal_intr_r bits outside notif_cmd_done_sts "
            "0x%08x after keyGen, 0x%08x after W1C",
            notif_set & _NOTIF_RSVD,
            notif_clr & _NOTIF_RSVD,
        )

    async def _graded_irq_legs(self, abr: SepAbr, vec: SepVecWatch) -> list[int]:
        """The graded window: error leg, NIST keyGen with the notification rise, notification W1C.

        The keyGen inputs are written before the window opens; the window
        holds the command write and what it grades.
        """
        mark_open = vec.mark()
        self._pic_pass = 0
        await self._error_leg(abr, vec)

        mark_cmd = vec.mark()
        pk = await self._run_keygen(abr, "nist-keygen")
        mismatch = next((i for i, (g, e) in enumerate(zip(pk, NIST_KG_PK)) if g != e), None)
        self._grade(
            "NIST-PK",
            mismatch is None,
            f"{PK_WORDS}-word public key vs ACVP keyGen vector, first mismatch at word "
            f"{mismatch}"
            + (
                ""
                if mismatch is None
                else f" got=0x{pk[mismatch]:08x} exp=0x{NIST_KG_PK[mismatch]:08x}"
            ),
        )
        self.logger.info("CHK-STATUS-VALID PASS: VALID, ERROR=0")

        rises = vec.rises_since(mark_cmd, "abr_notif")
        # integration/rdl/sep/abr_reg.rdl:543 command-done status bit, :534
        # level, :671, :680 and :683 the notification line with both enables set.
        self._grade(
            "PIC-NOTIF-RISE",
            len(rises) == 1,
            f"vec[{IRQ_ABR_NOTIF}] rises after the keyGen command write={len(rises)} (want 1) "
            f"rise_clk_from_write={[r.clk - mark_cmd.clk for r in rises]}",
        )
        await self._release_pic(ABR_PIC_NOTIF_RISE)
        err_lvl = await self._irq(IRQ_ABR_ERROR)
        notif_lvl = await self._irq(IRQ_ABR_NOTIF)
        self._grade(
            "PIC-NOTIF",
            notif_lvl == 1 and err_lvl == 0,
            f"after keyGen [{IRQ_ABR_NOTIF}]={notif_lvl} (want 1) [{IRQ_ABR_ERROR}]={err_lvl} "
            "(want 0; the error line rose and fell in this window)",
        )

        await self._notif_w1c_leg(abr)

        # hw/sys/sep/doc/interrupts.adoc:22-23 (bit i is source i + 1) and :33-34
        # (slots 1-43 individually assigned): a source raises its own bit only.
        # The held cp_src_exclusive_other rise of each source samples only
        # after its EXCL check passed: the bit of the source joins exo_pass.
        self._grade_exclusive("SRC35-EXCL", vec, mark_open, "abr_error", _SAME_CLK_ERROR, want=1)
        await self._release_exo(exo_pass_bit(_SRC_ABR_ERROR))
        self._grade_exclusive("SRC36-EXCL", vec, mark_open, "abr_notif", _SAME_CLK_NOTIF, want=1)
        await self._release_exo(exo_pass_bit(_SRC_ABR_ERROR) | exo_pass_bit(_SRC_ABR_NOTIF))
        set_exo_pass(0, self.logger)
        set_abr_pic_pass(0, self.logger)
        return pk

    async def _release_exo(self, mask: int) -> None:
        """Write the exo_pass bits of the EXCL checks that passed and hold them _LABEL_CLK clocks."""
        set_exo_pass(mask, self.logger)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLK)

    async def run_scenario(self) -> None:
        cfg = SepAbrKeygenCfg(self.random_seed())
        self.logger.info("abr mldsa keygen: %s", cfg.summary())

        await self.bring_up_no_cpu()
        abr = SepAbr(self)

        # Logged for the record, not graded: abr_reg.rdl declares NAME and
        # VERSION sw=r with no reset, and no SEP document gives their values.
        name0 = await abr.rd32(ABR_NAME0)
        name1 = await abr.rd32(ABR_NAME1)
        ver0 = await abr.rd32(ABR_VERSION0)
        ver1 = await abr.rd32(ABR_VERSION1)
        self.logger.info(
            "ABR ML-DSA identity words (information only): NAME0=0x%08x NAME1=0x%08x "
            "VERSION0=0x%08x VERSION1=0x%08x",
            name0,
            name1,
            ver0,
            ver1,
        )

        st0 = await abr.rd32(ABR_STATUS)
        assert (st0 & ST_READY) and not (st0 & ST_VALID) and not (st0 & ST_ERROR), (
            f"post-reset STATUS=0x{st0:08x}, expected READY, not VALID, not ERROR"
        )
        self.logger.info("CHK-RESET-STATUS PASS: STATUS=0x%08x READY, not VALID, not ERROR", st0)

        await abr.enable_notif()
        assert await self._irq(IRQ_ABR_ERROR) == 0
        assert await self._irq(IRQ_ABR_NOTIF) == 0

        await self._load(abr, list(NIST_KG_SEED), cfg.entropy, "nist-keygen")
        vec = pic_vector_watch(
            {"abr_error": vec_bit(_SRC_ABR_ERROR), "abr_notif": vec_bit(_SRC_ABR_NOTIF)}
        ).start()
        # The window opens one clock before the first graded write and closes
        # two clocks after the last graded edge, or at the first FAIL.
        open_graded_window(TEST, self.logger)
        await ClockCycles(cocotb.top.clk_i, 1)
        try:
            await self._graded_irq_legs(abr, vec)
        except BaseException:
            close_graded_window(self.logger)
            raise
        await ClockCycles(cocotb.top.clk_i, 2)
        close_graded_window(self.logger)
        await vec.stop()

        # MLDSA_STATUS.READY is driven by abr_ready = (abr_prog_cntr ==
        # ABR_RESET) (abr_ctrl.sv), which is LOW through the ABR_ZEROIZE walk --
        # abr_idle is a different signal and is not in STATUS -- so a
        # READY-high wait here would hang rather than pass vacuously. VALID
        # must fall, and the pubkey window must then read zero.
        #
        # Scope of the pubkey half: the read port is gated on mldsa_valid_reg
        # (abr_ctrl.sv api_pubkey_re), so once VALID is 0 the window returns 0
        # whether or not the memory walk ran. This proves the window is no
        # longer readable, NOT that the RAM was wiped. Proving the wipe needs a
        # probe on the pubkey RAM or on zeroize_mem_done; it is not claimed.
        #
        # VALID is read set just before the ZEROIZE write, after the IRQ probe
        # reads and the notif W1C, so the 1->0 change is shown around the write.
        st_pre = await abr.rd32(ABR_STATUS)
        assert (st_pre & ST_VALID) and not (st_pre & ST_ERROR), (
            f"CHK-ZEROIZE FAIL: pre-zeroize STATUS=0x{st_pre:08x}, expected VALID=1 "
            "ERROR=0: VALID must be set before ZEROIZE for its drop to be credited "
            "to ZEROIZE"
        )
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        st_z = await self._wait_status(abr, ST_VALID, 0, what="post-zeroize VALID clear")
        assert (st_z & ST_ERROR) == 0, f"post-zeroize STATUS=0x{st_z:08x}, expected VALID=0 ERROR=0"
        # Read the whole window, not a prefix: ZEROIZE must clear all of it, and
        # the KAT already pays for a full-window read.
        pk_z = await abr.read_words(ABR_PUBKEY, PK_WORDS)
        live = [(i, w) for i, w in enumerate(pk_z) if w != 0]
        assert not live, (
            f"post-zeroize pubkey still live in {len(live)} of {PK_WORDS} words, "
            f"first at index {live[0][0]}=0x{live[0][1]:08x}"
        )
        self.logger.info(
            "CHK-ZEROIZE PASS: STATUS=0x%08x (VALID=1) before ZEROIZE, 0x%08x "
            "(VALID=0) after, and all %d pubkey words read 0 (read-gated, not a "
            "proven RAM wipe)",
            st_pre,
            st_z,
            PK_WORDS,
        )

        # Logged for the record, not graded. MLDSA_SEED is sw = w with hwclr
        # (integration/rdl/sep/abr_reg.rdl:133-135) and ZEROIZE clears all
        # internal registers (:77-79), so the seed cannot be read back, and the
        # tree holds one ML-DSA-87 keyGen case only: the public key of the
        # flipped seed has no golden. A key that differs from the vector does
        # not show that the flipped seed landed.
        flipped = cfg.flipped_seed(list(NIST_KG_SEED))
        await self._load(abr, flipped, cfg.entropy, "sensitivity-keygen")
        pk2 = await self._run_keygen(abr, "sensitivity-keygen")
        same = sum(1 for a, b in zip(pk2, NIST_KG_PK, strict=True) if a == b)
        nonzero = sum(1 for w in pk2 if w != 0)
        self.logger.info(
            "OBS-ABR-KEYGEN-SENSITIVITY: seed word %d bit %d flipped; public key "
            "word 0=0x%08x, %d of %d words equal the NIST vector, %d non-zero",
            cfg.flip_word,
            cfg.flip_bit,
            pk2[0],
            same,
            PK_WORDS,
            nonzero,
        )

        self.logger.info("abr mldsa keygen ALL CHECKS PASS")

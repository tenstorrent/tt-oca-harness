# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse -> Lifecycle-Controller lc_state stitch test (OSS).

Walks the
lifecycle state up the monotonic OTP W1S chain TEST_DEV -> PROD -> RMA_SIP_1 ->
RMA_CHIP_1 and, at each step, proves the eFuse-sensed lc_state is stitched into
the lifecycle controller and decoded into the right feature-control vector:

  * the LC_STATE shadow register reads back the differential-encoded state, and
  * FEAT_CTRL reads back exactly ``feat_ctrl_expected(...)`` from the LCC golden
    model (the spec-derived decode of lc_state x SIP_DIS x SYS_DIS).

After the initial preload, state advances are driven through EFUSE_PROGRAM_CTRL
and a resense. The RMA_SIP/RMA_CHIPLET steps first perform the matching token
operation so the LC_STATE token gates authorize the OTP bit program. SIP_DIS
and SYS_DIS are pinned to distinct non-zero vectors so the decoded FEAT_CTRL
differs per state and the golden check cannot pass vacuously.

The observed lc_state sequence is also validated against the LCC encoding /
W1S-monotonic / valid-transition rules; the fixed monotonic chain covers the
forward-only and terminal-stability properties.

After the initial TEST_DEV sense (TEST_EN strap = 0) the test raises the
frontdoor ``test_en_strap_i``, re-senses, and proves the latched
``secure_tm_o`` follows the strap while ``FEAT_CTRL`` stays on the same
golden (SECURE_TM does not qualify feature control). The same legs also
score ``dbg_disable.dft_secure`` against Case 3 of the DTP ladder: the
strap is not a term, so the bit must not follow ``secure_tm``. The strap
is then lowered; the rest of the walk runs at ``secure_tm=0`` so LC_STATE
programming is not blocked by ``efuse_guard``.

``lc_sigint_err`` has no legal OTP stimulus -- sense regenerates ``{~raw, raw}``.
The test injects a broken pair at the LCC decoder input through the tb_top
``lc_sigint_inject_i`` port after the walk. Observation is the DUT
``lc_sigint_err_o`` probe plus an AXI ``FEAT_CTRL`` readback of 0 (fail-closed),
then release and both restore.
"""

from __future__ import annotations

import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_field_map import spec_secret_regs
from env.sep_efuse_image import LC_WORD_IDX, SepEfuseImage
from env.sep_lcc_golden import (
    LC_PROD,
    LC_RMA_CHIP_1,
    LC_RMA_SIP_1,
    LC_TEST_DEV,
    SIP_DBG_BIT,
    dbg_disable_expected,
    dbg_disable_sample,
    is_legal_lc,
    is_valid_lc_transition,
    lc_state_name,
)
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, EFUSE_MMR, sym
from seq_lib.sep_efuse_rma_token_seq import (
    EOP_RMA_CHIPLET,
    EOP_RMA_SIP,
    TOKEN_MATCH,
)
from seq_lib.sep_lcc_stitch_check_seq import sep_lcc_stitch_check_seq

_MAX_SENSE_CYCLES = 20_000

# KM-secret fields named in otp_fuse_controller.adoc (Key Manager subset). The
# SECURE_TM block list is LOCK / LC_STATE / SIP_DIS / SYS_DIS; these four
# are the secrets the stitch grades for disconnect.
_SECRET_FIELDS = spec_secret_regs()

# Monotonic lifecycle chain exercised.
_LC_CHAIN = (LC_TEST_DEV, LC_PROD, LC_RMA_SIP_1, LC_RMA_CHIP_1)

# Distinct, non-zero disable vectors so each decoded FEAT_CTRL is a different,
# non-trivial value (guards every golden check against a vacuous pass).
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF

# Block bases from the generated map.
_EFUSE_PROGRAM_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_CTRL")
_PG_ADDR = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_addr")
_PG_DATA = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_data")
_PG_GO = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_program_go")
_PG_READ_BACK = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_program_read_back")
_PG_ENABLE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_enable")
_PG_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_status")
_RMA_SIP_TOKEN_I = sym("EFUSE_MMR_RMA_SIP_TOKEN_I_0__REG_ADDR")
_RMA_CHIPLET_TOKEN_I = sym("EFUSE_MMR_RMA_CHIPLET_TOKEN_I_0__REG_ADDR")
_TOKEN_EOP = sym("EFUSE_MMR_TOKEN_EOP_REG_ADDR")
_RMA_SIP_TOKEN_MATCH = sym("EFUSE_MMR_RMA_SIP_TOKEN_MATCH_REG_ADDR")
_RMA_CHIPLET_TOKEN_MATCH = sym("EFUSE_MMR_RMA_CHIPLET_TOKEN_MATCH_REG_ADDR")
# Match-status encoding is a periphs.adoc value the RDL does not express; take the
# shared DV-owned constant rather than a second copy of it. The field it lands in
# is generated, so the mask comes from the export.
_TOKEN_MATCH_STATUS = EFUSE_MMR.field_mask("TOKEN_MATCH", "token_match_status")

_RMA_SIP_TOKEN_DIGEST = sym("SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_REG_ADDR")
_RMA_CHIPLET_TOKEN_DIGEST = sym("SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_REG_ADDR")
# otp_fuse_controller.adoc: LC_STATE starts at bit 96. efuse_guard gates program addresses BASE+1
# (RMA_SIP token) and BASE+2 (RMA_CHIPLET token) on a token match.
# LC_WORD_IDX * 32 so the program address tracks the generated LC_STATE word.
_LC_STATE_BIT_BASE = LC_WORD_IDX * 32

_TOKEN_RMA_SIP = 0
_TOKEN_RMA_CHIPLET = 1
_TOKEN_VALUE = {
    _TOKEN_RMA_SIP: int("111122223333444455556666777788889999aaaabbbbccccddddeeeeffff0001", 16),
    _TOKEN_RMA_CHIPLET: int("22223333444455556666777788889999aaaabbbbccccddddeeeeffff00011111", 16),
}


class _lcc_otp_program_seq(pyuvm.uvm_sequence):
    """Frontdoor OTP bit program sequence for the LCC LC_STATE walk."""

    def __init__(
        self,
        bit_addr: int,
        *,
        token_kind: int | None = None,
        max_attempts: int = 10,
        name: str = "lcc_otp_program_seq",
    ) -> None:
        super().__init__(name)
        self.bit_addr = bit_addr
        self.token_kind = token_kind
        self.max_attempts = max_attempts
        # Number of injected program failures observed for this bit (each forces
        # one retry). Read back by the test to prove the retry path was actually
        # exercised rather than passing vacuously.
        self.retry_count = 0
        # Last PROGRAM_CTRL status word. The blocked-strap path inspects
        # PROGRAM_DONE+PROGRAM_ERR here instead of inferring a bank write
        # from fail-injection credit (that credit re-arms on every rst_ni).
        self.last_status = 0

    async def _access(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        data: int = 0,
        expected: int | None = None,
        label: str = "axi",
    ) -> int:
        item = SepAxiItem(f"{label}_0x{addr:08x}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def _write(self, addr: int, data: int, label: str) -> None:
        await self._access(SepAxiOp.WRITE, addr, data=data, label=label)

    async def _read(self, addr: int, label: str) -> int:
        return await self._access(SepAxiOp.READ, addr, label=label)

    async def _write_u256_le(self, base: int, value: int, label: str) -> None:
        for i in range(8):
            await self._write(base + 4 * i, (value >> (32 * i)) & 0xFFFF_FFFF, label)

    @staticmethod
    def _token_digest(token: int) -> int:
        digest = hashlib.sha256(token.to_bytes(32, "big")).digest()
        return int.from_bytes(digest, "big")

    async def _match_token(self) -> None:
        assert self.token_kind is not None
        token = _TOKEN_VALUE[self.token_kind]
        if self.token_kind == _TOKEN_RMA_SIP:
            digest_base = _RMA_SIP_TOKEN_DIGEST
            token_base = _RMA_SIP_TOKEN_I
            eop_value = EOP_RMA_SIP
            match_addr = _RMA_SIP_TOKEN_MATCH
            token_name = "RMA_SIP"
        else:
            digest_base = _RMA_CHIPLET_TOKEN_DIGEST
            token_base = _RMA_CHIPLET_TOKEN_I
            eop_value = EOP_RMA_CHIPLET
            match_addr = _RMA_CHIPLET_TOKEN_MATCH
            token_name = "RMA_CHIPLET"

        await self._write_u256_le(digest_base, self._token_digest(token), "token_digest")
        await self._write_u256_le(token_base, token, "token_input")
        await self._write(_TOKEN_EOP, eop_value, "token_eop")

        for _ in range(200):
            await ClockCycles(cocotb.top.clk_i, 1)
            result = await self._read(match_addr, "token_match") & _TOKEN_MATCH_STATUS
            if result == TOKEN_MATCH:
                cocotb.log.info("[lcc] %s token matched", token_name)
                return
        raise AssertionError(f"{token_name} token did not match")

    async def body(self) -> None:
        if self.token_kind is not None:
            await self._match_token()

        # Field masks from the generated export, like the register address above,
        # so a field move in the RDL moves the programming word with it.
        wdata = (self.bit_addr & _PG_ADDR) | _PG_DATA | _PG_GO | _PG_READ_BACK | _PG_ENABLE
        saw_retry = False
        for attempt in range(1, self.max_attempts + 1):
            await self._write(_EFUSE_PROGRAM_CTRL, wdata, "program_ctrl")

            for _ in range(200):
                await ClockCycles(cocotb.top.clk_i, 1)
                status = await self._read(_EFUSE_PROGRAM_CTRL, "program_status")
                self.last_status = status
                if not (status & _PG_DONE):
                    continue

                await self._write(_EFUSE_PROGRAM_CTRL, 0, "program_ctrl_clear")
                if (status & _PG_STATUS) == 0:
                    if saw_retry:
                        cocotb.log.info(
                            "CHK-OTP-RETRY PASS: OTP bit[%d] programmed after retry",
                            self.bit_addr,
                        )
                    cocotb.log.info("[lcc] OTP bit[%d] programmed via frontdoor", self.bit_addr)
                    return

                if attempt == self.max_attempts:
                    raise AssertionError(
                        f"OTP program bit {self.bit_addr} failed after "
                        f"{self.max_attempts} attempts: status=0x{status:08x}"
                    )

                saw_retry = True
                self.retry_count += 1
                cocotb.log.info(
                    "[lcc] OTP bit[%d] program failed on attempt %d; retrying",
                    self.bit_addr,
                    attempt,
                )
                break
            else:
                raise AssertionError(
                    f"OTP program bit {self.bit_addr} did not complete on attempt {attempt}"
                )


@pyuvm.test()
class sep_efuse_lcc_lc_state_stitch_test(sep_base_test):
    """Stitch eFuse lc_state through the LCC and verify decoded FEAT_CTRL."""

    async def _sense_initial_state(self, image: SepEfuseImage, raw: int) -> None:
        image.set_lc_state(raw)
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

    async def _program_state_and_resense(self, image: SepEfuseImage, raw: int) -> None:
        bit_addr = {
            LC_PROD: _LC_STATE_BIT_BASE + 0,
            LC_RMA_SIP_1: _LC_STATE_BIT_BASE + 1,
            LC_RMA_CHIP_1: _LC_STATE_BIT_BASE + 2,
        }[raw]
        token_kind = {
            LC_PROD: None,
            LC_RMA_SIP_1: _TOKEN_RMA_SIP,
            LC_RMA_CHIP_1: _TOKEN_RMA_CHIPLET,
        }[raw]
        seq = _lcc_otp_program_seq(bit_addr, token_kind=token_kind)
        await self.start_seq(seq)
        self._total_program_retries += seq.retry_count
        if raw == LC_PROD:
            assert self._secure_tm_prog_blocked, (
                "test bug: PROD program ran without a strap-up block attempt"
            )
        image.set_lc_state(raw)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)

    def _check_dbg_disable(self, feat_ctrl: int, *, secure_tm: int, tag: str) -> None:
        """dbg_disable against the DTP ladder for this same FEAT_CTRL.

        ``dft_secure`` is Case 3 (SIP_DBG & CHIPLET_DBG & SEP_DBG), inverted.
        The TEST_EN strap is not a term: the same FEAT_CTRL must produce the
        same bit at both polarities. A formula of ``!secure_tm`` fails here
        whenever Case 3 and the strap disagree.
        """
        got = dbg_disable_sample(cocotb.top)
        want = dbg_disable_expected(feat_ctrl)
        for name, exp in want.items():
            assert got[name] == exp, (
                f"{tag}: dbg_disable.{name}={got[name]} expected {exp} for "
                f"FEAT_CTRL=0x{feat_ctrl:016x} secure_tm={secure_tm} "
                f"(sep_dbg={feat_ctrl & 1} chiplet_dbg={(feat_ctrl >> 1) & 1} "
                f"sip_dbg={(feat_ctrl >> SIP_DBG_BIT) & 1})"
            )
        self.logger.info(
            "CHK-DFT-SECURE PASS: %s dft_secure=%d (Case 3, independent of "
            "secure_tm=%d; sep_dbg=%d chiplet_dbg=%d sip_dbg=%d)",
            tag,
            got["dft_secure"],
            secure_tm,
            feat_ctrl & 1,
            (feat_ctrl >> 1) & 1,
            (feat_ctrl >> SIP_DBG_BIT) & 1,
        )

    def _sensed_secret(self, image: SepEfuseImage, name: str) -> int:
        """Read one KM-secret field out of the sensed shadow array by backdoor."""
        sensed = int(cocotb.top.efuse_shadow_probe_o.value)
        fld = image.field(name)
        val = 0
        for i in range(fld.n_words):
            word = (sensed >> (32 * (fld.word + i))) & 0xFFFF_FFFF
            val |= word << (32 * i)
        return val

    async def _check_state(
        self,
        image: SepEfuseImage,
        raw: int,
        *,
        secure_tm: int,
        sigint_err: int = 0,
        prev_raw: int | None,
    ) -> int:
        """Value-check LC shadow + FEAT_CTRL; return the DUT-observed LC code."""
        observed_sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        observed_tm = int(cocotb.top.secure_tm_o.value) & 0x1
        observed_sigint = int(cocotb.top.lcc_sigint_err_probe_o.value) & 0x1
        assert observed_sec_dis == 0, (
            f"sec_dis={observed_sec_dis} but this walk presents no SEC_DISABLE token (LC=0x{raw:x})"
        )
        assert observed_tm == secure_tm, (
            f"secure_tm_o={observed_tm} after TEST_EN strap={secure_tm} (LC=0x{raw:x})"
        )
        assert observed_sigint == sigint_err, (
            f"lc_sigint_err={observed_sigint} expected {sigint_err} at LC=0x{raw:x}"
        )
        seq = sep_lcc_stitch_check_seq(
            image,
            secure_tm=secure_tm,
            sec_dis=0,
            sigint_err=sigint_err,
        )
        mark = self.sb_mark()
        await self.start_seq(seq)
        tag = f"{lc_state_name(raw)} tm={secure_tm} sigint={sigint_err}"
        self.assert_sb_judged(mark, f"CHK-GOLDEN {tag}")
        assert seq.observed_feat is not None, "sequence did not publish AXI FEAT_CTRL"
        feat = seq.observed_feat
        self._last_observed_feat = feat
        if not sigint_err:
            self._feat_by_state[raw] = feat

        if raw == LC_TEST_DEV and not sigint_err:
            self._test_dev_feat_by_tm[secure_tm] = feat
            if secure_tm:
                self.logger.info(
                    "CHK-SECURE-TM-ON PASS: secure_tm_o=1, FEAT_CTRL=0x%016x "
                    "(same TEST_DEV golden; SECURE_TM does not qualify feat_ctrl)",
                    feat,
                )
            else:
                self.logger.info(
                    "CHK-SECURE-TM-OFF PASS: secure_tm_o=0, FEAT_CTRL=0x%016x",
                    feat,
                )
        self._check_dbg_disable(
            feat,
            secure_tm=secure_tm,
            tag=f"{lc_state_name(raw)} tm={secure_tm} sigint={sigint_err}",
        )
        if sigint_err:
            assert feat == 0, (
                f"sigint fail-closed expects AXI FEAT_CTRL=0, got 0x{feat:016x} "
                f"(lcc_sigint_err_probe_o={observed_sigint} sec_dis={observed_sec_dis})"
            )
            self.logger.info(
                "CHK-SIGINT PASS: inject took: lcc_sigint_err_probe_o=%d, "
                "AXI FEAT_CTRL=0x%016x (fail-closed)",
                observed_sigint,
                feat,
            )

        if sigint_err:
            return prev_raw if prev_raw is not None else raw

        observed = seq.observed_lc_raw
        assert observed is not None, "sequence did not publish an observed LC code"
        assert is_legal_lc(observed), (
            f"DUT returned an illegal LC code 0x{observed:x} (programmed {lc_state_name(raw)})"
        )
        if prev_raw is not None:
            assert is_valid_lc_transition(prev_raw, observed), (
                f"illegal LC transition {lc_state_name(prev_raw)} -> "
                f"{lc_state_name(observed)} (as observed on the DUT)"
            )
        self.logger.info(
            "CHK-LC-INPUT PASS: %s observed LC code 0x%x reached the "
            "controller (legal encoding, legal transition)",
            lc_state_name(observed),
            observed,
        )
        self.logger.info(
            "CHK-GOLDEN PASS: %s FEAT_CTRL=0x%016x matches the golden decode",
            lc_state_name(raw),
            feat,
        )
        return observed

    async def run_scenario(self) -> None:
        # Pinned disable vectors + seeded-random data; LC_STATE set per step.
        image = SepEfuseImage().randomize(
            self.random_seed(),
            lc_raw=LC_TEST_DEV,
            fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS},
        )
        # Count of injected OTP-program failures the program sequences had to
        # retry past. The testlist arms deterministic failure injection
        # (+sep_efuse_prog_fail_count), so a zero count means the retry path was
        # never exercised -- asserted at the end so the retry check is non-vacuous.
        self._total_program_retries = 0
        self._secure_tm_prog_blocked = False
        self._feat_by_state: dict[int, int] = {}
        self._test_dev_feat_by_tm: dict[int, int] = {}
        prev_raw: int | None = None

        for i, raw in enumerate(_LC_CHAIN):
            assert is_legal_lc(raw), f"test bug: illegal LC code 0x{raw:x}"
            if i == 0:
                await self._sense_initial_state(image, raw)
                prev_raw = await self._check_state(
                    image,
                    raw,
                    secure_tm=0,
                    prev_raw=prev_raw,
                )
                # CHK-SECRET-BLANK, first half: with the strap low every
                # KM-secret field must be present in the sensed shadow.
                # Captured BEFORE the strap goes up so the disconnect below is
                # a transition on one image rather than an observation that
                # could also be satisfied by a DUT that never sensed them.
                open_secrets: dict[str, int] = {}
                for name in _SECRET_FIELDS:
                    staged = image.field_int(name)
                    assert staged != 0, (
                        f"test bug: staged {name} is zero, so the disconnect "
                        f"check below would pass on a DUT that ignores secure_tm"
                    )
                    sensed = self._sensed_secret(image, name)
                    assert sensed == staged, (
                        f"{name} at secure_tm=0 sensed 0x{sensed:x} != staged 0x{staged:x}"
                    )
                    open_secrets[name] = sensed

                # Latch TEST_EN on the next sense-done. resense pulses rst_ni
                # (clears the latch flop) then re-samples the strap.
                cocotb.top.test_en_strap_i.value = 1
                await self.resense(max_cycles=_MAX_SENSE_CYCLES)
                prev_raw = await self._check_state(
                    image,
                    raw,
                    secure_tm=1,
                    prev_raw=prev_raw,
                )
                # Second half: the same image, every KM-secret field, strap high.
                # otp_fuse_controller.adoc names the four fields and the TEST_EN disconnect
                # of fuse-bank outputs; it does not require a zero readback.
                for name in _SECRET_FIELDS:
                    blanked = self._sensed_secret(image, name)
                    assert blanked != open_secrets[name], (
                        f"{name} still reads the staged secret 0x{open_secrets[name]:x} "
                        f"while secure_tm=1 (got 0x{blanked:x})"
                    )
                    self.logger.info(
                        "CHK-SECRET-BLANK PASS: %s sensed 0x%x at secure_tm=0 and "
                        "0x%x at secure_tm=1 (not the staged secret)",
                        name,
                        open_secrets[name],
                        blanked,
                    )

                # CHK-SECURE-TM-PROG-BLOCK: while the strap is up, efuse_guard
                # empties the fuse command request and the program interface
                # completes with PROGRAM_DONE+ERR because secure_tm_blocked_i
                # is set. That is a failed completion, not a starved DONE.
                # The one-shot injection (percent 0) can fail only the first
                # bank write after the resense. Two failed attempts therefore
                # cannot both be that injection: a guard that let the command
                # through would complete the second attempt.
                blocked = _lcc_otp_program_seq(_LC_STATE_BIT_BASE + 0, max_attempts=2)
                try:
                    await self.start_seq(blocked)
                except AssertionError as exc:
                    status = blocked.last_status
                    done = int(bool(status & _PG_DONE))
                    err = int(bool(status & _PG_STATUS))
                    if not (done and err):
                        raise AssertionError(
                            "CHK-SECURE-TM-PROG-BLOCK: expected PROGRAM_DONE+ERR "
                            "(secure_tm_blocked completes the program FSM with "
                            f"error); status=0x{status:08x} ({exc})"
                        ) from exc
                    if blocked.retry_count < 1:
                        raise AssertionError(
                            "CHK-SECURE-TM-PROG-BLOCK: one PROGRAM_DONE+ERR is "
                            "the one-shot program-fail injection; the guard "
                            f"must fail a second attempt (retry_count="
                            f"{blocked.retry_count})"
                        )
                    self._secure_tm_prog_blocked = True
                    self.logger.info(
                        "CHK-SECURE-TM-PROG-BLOCK PASS: OTP bit[%d] failed "
                        "%d attempt(s) with PROGRAM_DONE+ERR (status=0x%08x) "
                        "while secure_tm=1; one injection cannot cover both",
                        _LC_STATE_BIT_BASE,
                        blocked.retry_count + 1,
                        status,
                    )
                else:
                    raise AssertionError(
                        f"OTP bit[{_LC_STATE_BIT_BASE}] programmed while secure_tm=1; "
                        f"efuse_guard must block every fuse command under the strap"
                    )

                # Drop the strap before the walk resumes. LC_STATE carries
                # SECURE_TM_LOCK and the guard blanks the command interface outright,
                # so programming and secure_tm cannot both hold -- the strap phase is
                # scoped to the DFT-column and secret-disconnect checks
                # above. The same bit programs for real in the next iteration, which
                # is what makes the refusal above a gate rather than a dead path.
                cocotb.top.test_en_strap_i.value = 0
                await self.resense(max_cycles=_MAX_SENSE_CYCLES)
                prev_raw = await self._check_state(
                    image,
                    raw,
                    secure_tm=0,
                    prev_raw=prev_raw,
                )
            else:
                await self._program_state_and_resense(image, raw)
                prev_raw = await self._check_state(
                    image,
                    raw,
                    secure_tm=0,
                    prev_raw=prev_raw,
                )

        # Broken-pair inject: no legal OTP image can present one. Force the
        # LCC decoder input, prove fail-closed, then release and restore.
        last_raw = _LC_CHAIN[-1]
        # secure_tm=0 here: the TEST_EN strap is dropped after the first state so the
        # walk can program LC_STATE at all. _check_state asserts the observed strap,
        # so these must match the DUT rather than the earlier phase.
        cocotb.top.lc_sigint_inject_i.value = 1
        await ClockCycles(cocotb.top.clk_i, 2)
        await self._check_state(
            image,
            last_raw,
            secure_tm=0,
            sigint_err=1,
            prev_raw=prev_raw,
        )
        cocotb.top.lc_sigint_inject_i.value = 0
        await ClockCycles(cocotb.top.clk_i, 2)
        await self._check_state(
            image,
            last_raw,
            secure_tm=0,
            sigint_err=0,
            prev_raw=prev_raw,
        )
        self.logger.info(
            "CHK-SIGINT-RELEASE PASS: lcc_sigint_err_probe_o=0, AXI FEAT_CTRL=0x%016x restored",
            self._last_observed_feat,
        )

        assert self._total_program_retries >= 1, (
            "OTP-program retry path never exercised: no program failures were "
            "injected/retried across the LC walk (expected deterministic "
            "injection via +sep_efuse_prog_fail_count). The CHK-OTP-RETRY check "
            "would pass vacuously."
        )

        feats = [self._feat_by_state[r] for r in _LC_CHAIN]
        assert len(set(feats)) == len(_LC_CHAIN), (
            f"CHK-NONVAC FAIL: pinned overrides did not produce distinct FEAT_CTRL words: {feats}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: four FEAT_CTRL words are mutually distinct (%s)",
            ", ".join(f"{lc_state_name(r)}=0x{self._feat_by_state[r]:016x}" for r in _LC_CHAIN),
        )
        assert set(self._test_dev_feat_by_tm) == {0, 1}, (
            "CHK-SECURE-TM FAIL: TEST_DEV FEAT_CTRL was not observed at both secure_tm "
            f"values (seen {sorted(self._test_dev_feat_by_tm)})"
        )
        feat_tm0 = self._test_dev_feat_by_tm[0]
        feat_tm1 = self._test_dev_feat_by_tm[1]
        assert feat_tm0 == feat_tm1, (
            f"CHK-SECURE-TM FAIL: TEST_DEV FEAT_CTRL 0x{feat_tm0:016x} at secure_tm=0 "
            f"!= 0x{feat_tm1:016x} at secure_tm=1"
        )
        self.logger.info(
            "CHK-SECURE-TM PASS: TEST_DEV FEAT_CTRL 0x%016x identical at secure_tm=0 and 1",
            feat_tm0,
        )
        self.logger.info(
            "LCC stitch: walked %d states (%s); FEAT_CTRL matched golden at each; "
            "secure_tm off/on and lc_sigint inject proven; "
            "OTP-program retry path exercised %d time(s)",
            len(_LC_CHAIN),
            " -> ".join(lc_state_name(r) for r in _LC_CHAIN),
            self._total_program_retries,
        )

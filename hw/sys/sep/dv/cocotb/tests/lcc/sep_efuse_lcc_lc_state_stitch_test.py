# SPDX-License-Identifier: Apache-2.0
"""SEP eFuse -> Lifecycle-Controller lc_state stitch test (OSS).

OSS port of the reference UVM ``sep_efuse_lcc_lc_state_stitch_test``. Walks the
lifecycle state up the monotonic OTP W1S chain TEST_DEV -> PROD -> RMA_SIP_1 ->
RMA_CHIP_1 and, at each step, proves the eFuse-sensed lc_state is stitched into
the lifecycle controller and decoded into the right feature-control vector
(interconnect edge E4/E11):

  * the LC_STATE shadow register reads back the differential-encoded state, and
  * FEAT_CTRL reads back exactly ``feat_ctrl_expected(...)`` from the LCC golden
    model (the spec/RTL decode of lc_state x SIP_DIS x SYS_DIS).

After the initial preload, state advances are driven through EFUSE_PROGRAM_CTRL
and a resense. The RMA_SIP/RMA_CHIPLET steps first perform the matching token
operation so the RTL LC_STATE token gates authorize the OTP bit program. SIP_DIS
and SYS_DIS are pinned to distinct non-zero vectors so the decoded FEAT_CTRL
differs per state and the golden check cannot pass vacuously.

The observed lc_state sequence is also validated against the LCC encoding /
W1S-monotonic / valid-transition rules (the test-level mirror of the RTL SVA
state checker); the fixed monotonic chain covers the SVA forward-only and
terminal-stability properties implicitly.

Scope vs the reference suite: differential-decode integrity (``lc_sigint_err``)
is not checked directly -- that port is internal to ``sep`` and unreachable from
cocotb.top -- but it is covered indirectly, since a spurious sigint forces
``feat_ctrl`` to 0 and the exact feat_ctrl check would flag the mismatch.
"""

from __future__ import annotations

from sep_reg_meta import sym

import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from sep_base_test import sep_base_test
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import (
    LC_TEST_DEV, LC_PROD, LC_RMA_SIP_1, LC_RMA_CHIP_1,
    is_legal_lc, is_valid_lc_transition, lc_state_name,
)
from seq_lib.sep_lcc_stitch_check_seq import sep_lcc_stitch_check_seq

_MAX_SENSE_CYCLES = 20_000

# Monotonic lifecycle chain exercised (matches the reference test's PROD/RMA walk).
_LC_CHAIN = (LC_TEST_DEV, LC_PROD, LC_RMA_SIP_1, LC_RMA_CHIP_1)

# Distinct, non-zero disable vectors so each decoded FEAT_CTRL is a different,
# non-trivial value (guards every golden check against a vacuous pass).
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF

_SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
_EFUSE_CTRL_BASE = _SHADOW_BASE + 0x400
_EFUSE_MMR_BASE = _SHADOW_BASE + 0x500
_EFUSE_PROGRAM_CTRL = _EFUSE_CTRL_BASE + 0x4
_RMA_SIP_TOKEN_I = _EFUSE_MMR_BASE + 0x00
_RMA_CHIPLET_TOKEN_I = _EFUSE_MMR_BASE + 0x20
_TOKEN_EOP = _EFUSE_MMR_BASE + 0x60
_RMA_SIP_TOKEN_MATCH = _EFUSE_MMR_BASE + 0x64
_RMA_CHIPLET_TOKEN_MATCH = _EFUSE_MMR_BASE + 0x68
_TOKEN_MATCH = 0x15

_RMA_SIP_TOKEN_DIGEST = _SHADOW_BASE + 0x024
_RMA_CHIPLET_TOKEN_DIGEST = _SHADOW_BASE + 0x044
_LC_STATE_BIT_BASE = 2 * 32

_TOKEN_RMA_SIP = 0
_TOKEN_RMA_CHIPLET = 1
_TOKEN_VALUE = {
    _TOKEN_RMA_SIP: int(
        "111122223333444455556666777788889999aaaabbbbccccddddeeeeffff0001", 16
    ),
    _TOKEN_RMA_CHIPLET: int(
        "22223333444455556666777788889999aaaabbbbccccddddeeeeffff00011111", 16
    ),
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
            eop_value = 0x0000_0001
            match_addr = _RMA_SIP_TOKEN_MATCH
            token_name = "RMA_SIP"
        else:
            digest_base = _RMA_CHIPLET_TOKEN_DIGEST
            token_base = _RMA_CHIPLET_TOKEN_I
            eop_value = 0x0000_0100
            match_addr = _RMA_CHIPLET_TOKEN_MATCH
            token_name = "RMA_CHIPLET"

        await self._write_u256_le(digest_base, self._token_digest(token), "token_digest")
        await self._write_u256_le(token_base, token, "token_input")
        await self._write(_TOKEN_EOP, eop_value, "token_eop")

        for _ in range(200):
            await ClockCycles(cocotb.top.clk_i, 1)
            result = await self._read(match_addr, "token_match") & 0x3F
            if result == _TOKEN_MATCH:
                cocotb.log.info("[lcc] %s token matched", token_name)
                return
        raise AssertionError(f"{token_name} token did not match")

    async def body(self) -> None:
        if self.token_kind is not None:
            await self._match_token()

        wdata = (
            (self.bit_addr & 0xFFFF)
            | (1 << 16)   # efuse_data
            | (1 << 17)   # efuse_program_go
            | (1 << 18)   # efuse_program_read_back
            | (1 << 27)   # program_enable
        )
        saw_retry = False
        for attempt in range(1, self.max_attempts + 1):
            await self._write(_EFUSE_PROGRAM_CTRL, wdata, "program_ctrl")

            for _ in range(200):
                await ClockCycles(cocotb.top.clk_i, 1)
                status = await self._read(_EFUSE_PROGRAM_CTRL, "program_status")
                if not (status & (1 << 25)):
                    continue

                await self._write(_EFUSE_PROGRAM_CTRL, 0, "program_ctrl_clear")
                if ((status >> 26) & 1) == 0:
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
        image.set_lc_state(raw)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)

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
        # security_disable is a DUT output; feed the real value to the golden
        # model instead of assuming. secure_tm is internal and 0 for this image.
        prev_raw: int | None = None

        for i, raw in enumerate(_LC_CHAIN):
            # Guards the stimulus table itself; the DUT-side legality check is below.
            assert is_legal_lc(raw), f"test bug: illegal LC code 0x{raw:x}"
            if i == 0:
                await self._sense_initial_state(image, raw)
            else:
                await self._program_state_and_resense(image, raw)

            # security_disable feeds the golden; default 0 if the port is not
            # exposed (a wrong value is still caught by the exact feat_ctrl check,
            # which would otherwise expect the all-ones sec_dis override).
            # security_disable_o is not brought out to the testbench, so reading it
            # would return 0 unconditionally while looking like a DUT observation.
            # Pass the known value explicitly instead: this image never sets it, and a
            # wrong assumption is caught anyway by the exact feat_ctrl compare, which
            # would otherwise expect the all-ones security-disable override.
            sec_dis = 0
            seq = sep_lcc_stitch_check_seq(image, secure_tm=0, sec_dis=sec_dis)
            await self.start_seq(seq)

            # Legality and transition rules are applied to the code the DUT
            # returned over the frontdoor, not to the _LC_CHAIN literal we
            # programmed. Checking the literal would compare two test-side
            # constants and could never fail, whatever the DUT did.
            observed = seq.observed_lc_raw
            assert observed is not None, "sequence did not publish an observed LC code"
            assert is_legal_lc(observed), (
                f"DUT returned an illegal LC code 0x{observed:x} "
                f"(programmed {lc_state_name(raw)})"
            )
            if prev_raw is not None:
                assert is_valid_lc_transition(prev_raw, observed), (
                    f"illegal LC transition {lc_state_name(prev_raw)} -> "
                    f"{lc_state_name(observed)} (as observed on the DUT)"
                )
            self.logger.info(
                "[lcc] observed LC code 0x%x (%s) after programming %s",
                observed, lc_state_name(observed), lc_state_name(raw),
            )
            prev_raw = observed

        assert self._total_program_retries >= 1, (
            "OTP-program retry path never exercised: no program failures were "
            "injected/retried across the LC walk (expected deterministic "
            "injection via +sep_efuse_prog_fail_count). The CHK-OTP-RETRY check "
            "would pass vacuously."
        )

        self.logger.info(
            "LCC stitch: walked %d states (%s); FEAT_CTRL matched golden at each; "
            "OTP-program retry path exercised %d time(s)",
            len(_LC_CHAIN), " -> ".join(lc_state_name(r) for r in _LC_CHAIN),
            self._total_program_retries,
        )

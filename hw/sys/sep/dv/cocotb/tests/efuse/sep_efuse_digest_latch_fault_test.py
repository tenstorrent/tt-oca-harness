# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An RMA_SIP token presentation latches its SHA-256 digest, and test_en freezes the latch.

no_cpu, real fuse sense (PROD image). A frontdoor RMA_SIP token presentation
latches SHA-256 of the token into the sticky digest and sets valid. While
test_en is injected, the valid and latch enables stay 0, and the sticky digest
and valid hold their captured values through a full token operation.

Checkers:
  CHK-DIGEST-LATCH  the record for the whole contract above (DUT probes on the
                    tb_top token_digest_* ports).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from env.sep_lcc_golden import LC_PROD
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_RMA_SIP,
    SepRmaTokenCfg,
    SepRmaTokenMatchSeq,
)

_BOUND = 20_000


@pyuvm.test()
class sep_efuse_digest_latch_fault_test(sep_base_test):
    """The digest latch captures the token hash and holds it while test_en is injected."""

    # The whole contract is one record, so name it: a refactor that stops
    # reaching the freeze leg would otherwise still exit clean.
    required_evidence = ("CHK-DIGEST-LATCH",)
    min_evidence = 1

    async def _present_and_watch(
        self,
        token: int,
        *,
        frozen_digest: int | None = None,
        frozen_valid: int | None = None,
    ) -> SepRmaTokenMatchSeq:
        dut = cocotb.top
        seq = SepRmaTokenMatchSeq(TOKEN_RMA_SIP, token)
        task = cocotb.start_soon(self.start_seq(seq))
        saw_valid_event = False
        saw_digest_event = False

        for _ in range(_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            valid_pre = int(dut.token_digest_valid_en_pre_o.value)
            digest_pre = int(dut.token_digest_latch_en_pre_o.value)
            saw_valid_event |= bool(valid_pre)
            saw_digest_event |= bool(digest_pre)

            if frozen_digest is not None:
                assert int(dut.token_digest_test_en_o.value) == 1
                assert int(dut.token_digest_valid_en_o.value) == 0
                assert int(dut.token_digest_latch_en_o.value) == 0
                assert int(dut.token_digest_sticky_o.value) == frozen_digest
                assert int(dut.token_digest_valid_o.value) == frozen_valid

            if saw_valid_event and saw_digest_event:
                break
        else:
            raise AssertionError(
                "digest operation did not activate both valid and digest latch-enable antecedents"
            )

        await task
        return seq

    async def run_scenario(self) -> None:
        dut = cocotb.top
        cfg = SepRmaTokenCfg(self.random_seed())
        image = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_BOUND)

        normal = await self._present_and_watch(cfg.sip_token)
        assert normal.matched is True
        await ReadOnly()
        captured_digest = int(dut.token_digest_sticky_o.value)
        captured_valid = int(dut.token_digest_valid_o.value)
        assert captured_valid == 1
        assert captured_digest == cfg.sip_digest, (
            f"CHK-DIGEST-LATCH FAIL: sticky digest 0x{captured_digest:064x} "
            f"!= independent SHA-256 of the presented token 0x{cfg.sip_digest:064x}"
        )

        for _ in range(2):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            assert int(dut.token_digest_latch_en_o.value) == 0
            assert int(dut.token_digest_valid_en_o.value) == 0
            assert int(dut.token_digest_sticky_o.value) == captured_digest
            assert int(dut.token_digest_valid_o.value) == captured_valid

        await NextTimeStep()
        dut.token_digest_test_en_inject_i.value = 1
        await RisingEdge(dut.clk_i)
        await RisingEdge(dut.clk_i)
        await self._present_and_watch(
            cfg.sip_token ^ 1,
            frozen_digest=captured_digest,
            frozen_valid=captured_valid,
        )
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        assert int(dut.token_digest_sticky_o.value) == captured_digest
        assert int(dut.token_digest_valid_o.value) == captured_valid

        await NextTimeStep()
        dut.token_digest_test_en_inject_i.value = 0
        await RisingEdge(dut.clk_i)
        self.logger.info(
            "CHK-DIGEST-LATCH PASS: frontdoor capture activated; idle held; "
            "frontdoor start/hash-done events occurred while test_en held both latch gates closed"
        )

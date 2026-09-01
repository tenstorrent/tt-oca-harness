# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared TRNG reset, pool scrub, and ordered recovery.

The test fills the fabric entropy pool from the internal ESRC->CSRNG->EDN path,
holds every entropy consumer before resetting TRNG, proves the pool is empty
and its stale data cannot be read, fully reinitializes the entropy complex while
consumers remain held, and restores consumers only after fresh pool progress.
It also proves all three internal CSR ports return DECERR while isolated, then
resets with all external-source mux legs selected and proves the external TRNG
CSR responder and source-select register remain outside the reset domain. The
new JTAG reset pair is exercised to hold and release the same coordinated reset.

When software clears SW_RESET_N.trng_sw_rst_n, the coordinator stops accepting
new ESRC/CSRNG/EDN CSR traffic, drains accepted transactions on all three
converted AXI-Lite paths, and asserts the shared reset only after every path
reports isolated.
Buffered post-mux and pool entropy is cleared with the reset. While held, new
CSR accesses receive DECERR. Setting trng_sw_rst_n releases the internal blocks,
releases their isolation, and restores normal CSR traffic; firmware must
reconfigure ESRC, CSRNG, and EDN before using entropy.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, with_timeout

from env.sep_axi_agent import SepAxiOp
from env.sep_reg_meta import sym
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_entropy_pool_seq import POOL_POP, POOL_STATUS
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from ocah_axi_vip.cocotb.ocah_axi_results import worst_resp
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset


# RDL-described addresses come from the generated SEP map. The external TRNG
# responder is an integration aperture rather than a register block.
ESRC_COMPONENT_ID = sym("ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR")
ESRC_CTRL = sym("ENTROPY_SOURCE_CTRL_REG_ADDR")
ESRC_FIPS_LOCK = sym("ENTROPY_SOURCE_FIPS_LOCK_REG_ADDR")
CSRNG_INTR_STATE = sym("CSRNG_INTR_STATE_REG_ADDR")
CSRNG_INTR_ENABLE = sym("CSRNG_INTR_ENABLE_REG_ADDR")
EDN_INTR_STATE = sym("EDN_INTR_STATE_REG_ADDR")
EDN_INTR_ENABLE = sym("EDN_INTR_ENABLE_REG_ADDR")
EXT_TRNG_CSR = 0x1091_7000
EXT_TRNG_SRC_SEL = sym("SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_REG_ADDR")


@pyuvm.test()
class sep_trng_reset_recovery_test(sep_base_test):
    """Prove pool scrub and fresh-only ordered TRNG recovery."""

    async def _read(
        self, addr: int, *, length: int = 4, expect_error: bool = False
    ) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"trng_rd_{addr:08x}",
            op=SepAxiOp.READ,
            addr=addr,
            length=length,
            expect_error=expect_error,
        )
        await self.start_seq(seq)
        return seq

    async def _write(self, addr: int, data: int) -> None:
        seq = SepAxiAccessSeq(
            f"trng_wr_{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
        )
        await self.start_seq(seq)
        assert seq.resp_ok, f"AXI write failed @0x{addr:08x}"

    async def _wait_pool_level(self, *, nonzero: bool, timeout: int = 80_000) -> int:
        for _ in range(timeout // 20):
            seq = await self._read(POOL_STATUS)
            assert seq.resp_ok, "entropy-pool status read failed"
            level = seq.rdata & 0x3F
            if bool(level) == nonzero:
                return level
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError(
            f"entropy pool did not become {'nonempty' if nonzero else 'empty'}"
        )

    async def _wait_packer_depth(self, expected: int, timeout: int = 80_000) -> None:
        for _ in range(timeout):
            if int(cocotb.top.entropy_pool_packer_depth_o.value) == expected:
                return
            await ClockCycles(cocotb.top.clk_i, 1)
        raise AssertionError(f"entropy pool packer did not reach depth {expected}")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await self.bring_up_entropy(strict=False, score_km=False)
        assert await self.wait_genbits(), "initial DRBG did not produce genbits"
        assert (await self._read(ESRC_FIPS_LOCK)).rdata & 0x1, (
            "initial entropy bring-up did not lock the certified ESRC configuration"
        )

        initial_level = await self._wait_pool_level(nonzero=True)
        self.logger.info("initial entropy-pool level=%d", initial_level)

        resets = SepSwReset(self)
        saved = await resets.read_back()
        resets.value = saved
        await resets.park("aes", "kmac", "otbn", "km")

        # Stop the pool leg on the idle external source while its 32->64 packer
        # contains exactly one word. If a second word races the source-select
        # write, retry from the internal source. Once external is selected, the
        # half-word remains stable until reset, making this non-probabilistic.
        for _ in range(32):
            await self._write(EXT_TRNG_SRC_SEL, 0x0)
            await self._wait_packer_depth(1)
            await self._write(EXT_TRNG_SRC_SEL, 0x7)
            await ClockCycles(cocotb.top.clk_i, 2)
            if int(cocotb.top.entropy_pool_packer_depth_o.value) == 1:
                break
        else:
            raise AssertionError("could not park one half-packed entropy word")

        assert ((await self._read(EXT_TRNG_SRC_SEL)).rdata & 0x7) == 0x7
        self.env.axi_monitor.arm_expected_decerr(1)
        ext_csr_before = await self._read(EXT_TRNG_CSR, expect_error=True)
        assert ext_csr_before.resp_code == 3, "external TRNG CSR did not return DECERR"

        # Queue one access to each internal CSR aperture before the SW reset
        # write. The AXI master can have these reads outstanding together while
        # the coordinator drains all three isolates. Accepted reads complete;
        # any not yet accepted are terminated with DECERR, and none may hang.
        axi_driver = self.env.axi_agent.driver
        self.env.axi_monitor.arm_expected_decerr(3)
        drain_reads = [
            axi_driver.axi.init_read(address=addr, length=4, size=2)
            for addr in (ESRC_COMPONENT_ID, CSRNG_INTR_STATE, EDN_INTR_STATE)
        ]
        reset_task = cocotb.start_soon(resets.park("trng"))

        for _ in range(1_000):
            if int(cocotb.top.trng_gated_rst_n_probe_o.value) == 0:
                assert int(cocotb.top.trng_axi_isolated_probe_o.value) == 0x7, (
                    "shared TRNG reset asserted before all three AXI-Lite paths isolated"
                )
                break
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            raise AssertionError("coordinated TRNG reset did not assert")

        await reset_task
        drain_responses = []
        for event in drain_reads:
            await with_timeout(event.wait(), 10_000, "ns")
            drain_responses.append(event.data)
        drain_codes = [
            worst_resp(getattr(response, "resp", None)) for response in drain_responses
        ]
        # Return credits for accesses that drained without DECERR.
        self.env.axi_monitor.release_expected_decerr(
            3 - sum(1 for code in drain_codes if code == 3)
        )
        assert all(code in (0, 3) for code in drain_codes), (
            f"in-flight TRNG CSR accesses returned unexpected responses {drain_codes}"
        )
        assert 0 in drain_codes, "no pre-reset TRNG CSR access drained successfully"

        await ClockCycles(cocotb.top.clk_i, 20)
        assert int(cocotb.top.entropy_pool_packer_depth_o.value) == 0, (
            "TRNG reset did not scrub the half-packed entropy word"
        )

        # Once the coordinated reset is active, each internal CSR isolate must
        # reject new traffic without forwarding it into the reset domain.
        self.env.axi_monitor.arm_expected_decerr(3)
        for name, addr in (
            ("esrc", ESRC_COMPONENT_ID),
            ("csrng", CSRNG_INTR_ENABLE),
            ("edn", EDN_INTR_ENABLE),
        ):
            isolated_csr = await self._read(addr, expect_error=True)
            assert isolated_csr.resp_code == 3, (
                f"{name} CSR did not return DECERR while TRNG was isolated"
            )

        self.env.axi_monitor.arm_expected_decerr(1)
        ext_csr_during = await self._read(EXT_TRNG_CSR, expect_error=True)
        assert ext_csr_during.resp_code == ext_csr_before.resp_code, (
            "internal TRNG reset changed the external TRNG CSR response"
        )
        assert ((await self._read(EXT_TRNG_SRC_SEL)).rdata & 0x7) == 0x7, (
            "internal TRNG reset changed the external source selection"
        )

        # JTAG overrides the final reset after the isolation sequence.
        # Release software reset underneath it and prove isolation clears while
        # the final reset remains asserted.
        jtag_reset = cocotb.top.jtag_trng_rst_hold_i
        jtag_reset.value = 1
        await resets.release("trng")
        for _ in range(1_000):
            assert int(cocotb.top.trng_gated_rst_n_probe_o.value) == 0, (
                "software release bypassed the final JTAG TRNG reset override"
            )
            if int(cocotb.top.trng_axi_isolated_probe_o.value) == 0:
                break
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            raise AssertionError("TRNG isolation did not clear during JTAG reset")

        jtag_reset.value = 0
        await ClockCycles(cocotb.top.clk_i, 4)
        assert int(cocotb.top.trng_gated_rst_n_probe_o.value) == 1, (
            "TRNG reset did not release after the final JTAG override cleared"
        )

        held = await resets.read_back()
        for consumer in ("km", "otbn", "aes", "kmac"):
            assert not (held & (1 << SW_RESET_N_BIT[consumer])), (
                f"{consumer} was released before fresh entropy recovery"
            )
        assert held & (1 << SW_RESET_N_BIT["trng"]), (
            "TRNG was not released for ordered reinitialization"
        )
        assert not ((await self._read(ESRC_FIPS_LOCK)).rdata & 0x1), (
            "shared TRNG reset did not clear ESRC FIPS_LOCK"
        )
        assert ((await self._read(CSRNG_INTR_ENABLE)).rdata & 0xFFFF_FFFF) == 0
        assert ((await self._read(EDN_INTR_ENABLE)).rdata & 0xFFFF_FFFF) == 0

        # CTRL[0] is reserved RAZ/WI; writing it must not alter neighboring
        # fields.
        esrc_ctrl = (await self._read(ESRC_CTRL)).rdata & 0xFFFF_FFFF
        await self._write(ESRC_CTRL, esrc_ctrl | 0x1)
        esrc_ctrl_after = (await self._read(ESRC_CTRL)).rdata & 0xFFFF_FFFF
        assert esrc_ctrl_after == esrc_ctrl, "reserved ESRC CTRL[0] is not RAZ/WI"

        # TRNG is released for reinitialization, but EDN is reset/disabled and
        # consumers remain held. The synchronous clear must have removed every
        # cached word and any half-packed input. Reconfiguration below switches
        # all three source legs back to the internal DRBG.
        await self._wait_pool_level(nonzero=False)
        empty_pop = await self._read(POOL_POP, length=8, expect_error=True)
        assert empty_pop.resp_code != 0, "empty pool returned OKAY after TRNG reset"
        assert empty_pop.rdata == 0, "empty pool exposed stale pre-reset entropy"

        cfg = self.entropy_cfg
        await self.start_seq(
            SepEsrcConfigSeq("esrc_reconfig", cfg=cfg, reset_trng=False)
        )
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_restart_gens"))
        assert await self.wait_seed_ready(), (
            "ESRC did not produce a fresh seed after reset"
        )
        await self.start_seq(SepEsrcEnableEdnSeq("edn_restart"))
        assert (await self._read(ESRC_FIPS_LOCK)).rdata & 0x1, (
            "recovery did not restore ESRC FIPS_LOCK"
        )

        fresh_level = await self._wait_pool_level(nonzero=True)
        fresh_pop = await self._read(POOL_POP, length=8)
        assert fresh_pop.resp_ok, "fresh entropy-pool read failed after recovery"
        await self.check_entropy_alerts_zero()

        await resets.restore_after_trng_reinit(saved)
        assert await resets.read_back() == saved, "consumer resets were not restored"
        self.logger.info(
            "CHK-TRNG-RECOVERY PASS: pool %d->0->%d, stale read rejected, "
            "fresh data delivered before consumers restored",
            initial_level,
            fresh_level,
        )

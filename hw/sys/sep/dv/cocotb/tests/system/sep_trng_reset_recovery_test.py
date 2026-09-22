# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared TRNG reset, pool scrub, and ordered recovery.

The test fills the fabric entropy pool from the internal ESRC->CSRNG->EDN path,
holds every entropy consumer before resetting TRNG, proves the pool is empty
and its stale data cannot be read, fully reinitializes the entropy complex while
consumers remain held, and restores consumers only after fresh pool progress.
It also proves all three internal CSR ports return SLVERR while isolated, then
writes a non-reset source-select value and proves that register remains
outside the reset domain. The external TRNG passthrough window is an
adopter aperture; intra-window decode is not graded here. The JTAG reset
pair holds and releases the same coordinated reset.

When software clears SW_RESET_N.trng_sw_rst_n, the coordinator stops accepting
new ESRC/CSRNG/EDN CSR traffic, drains accepted transactions on all three
converted AXI-Lite paths, and asserts the shared reset only after every path
reports isolated.
Buffered post-mux and pool entropy is cleared with the reset. While held, new
CSR accesses receive SLVERR. Setting trng_sw_rst_n releases the internal blocks,
releases their isolation, and restores normal CSR traffic; firmware must
reconfigure ESRC, CSRNG, and EDN before using entropy.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, with_timeout
from env.sep_axi_agent import SepAxiOp
from env.sep_reg_meta import CSRNG, EDN, ENTROPY_SOURCE, SEP_CPU_CTRL, sym
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_entropy_pool_seq import EDN_CTRL_DISABLE, POOL_POP, POOL_STATUS, RESP_SLVERR
from seq_lib.sep_esrc_bringup_seq import (
    EDN_CTRL,
    EDN_CTRL_AUTO,
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

# RDL-described addresses come from the generated SEP map. EXT_TRNG_SRC_SEL
# is a SEP CPU-ctrl register outside the coordinated TRNG reset. The
# 0x1091_7000 passthrough window is an adopter aperture and is not read here.
ESRC_COMPONENT_ID = sym("ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR")
ESRC_CTRL = sym("ENTROPY_SOURCE_CTRL_REG_ADDR")
ESRC_FIPS_LOCK = sym("ENTROPY_SOURCE_FIPS_LOCK_REG_ADDR")
CSRNG_INTR_STATE = sym("CSRNG_INTR_STATE_REG_ADDR")
CSRNG_INTR_ENABLE = sym("CSRNG_INTR_ENABLE_REG_ADDR")
EDN_INTR_STATE = sym("EDN_INTR_STATE_REG_ADDR")
EDN_INTR_ENABLE = sym("EDN_INTR_ENABLE_REG_ADDR")
EXT_TRNG_SRC_SEL = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
# Park uses the RDL reset to freeze the packer; the domain-membership
# check then writes a non-reset value.
_SRC_SEL_MASK = SEP_CPU_CTRL.field_mask("EXT_TRNG_SRC_SEL", "sel")
_SRC_SEL_RESET = SEP_CPU_CTRL.reset("EXT_TRNG_SRC_SEL")
# sel is one bit per stream, not an encoding: bit0 Key Manager, bit1 crypto
# blocks, bit2 entropy pool, with 0 = internal DRBG and 1 = external TRNG
# (sep_cpu_ctrl.rdl EXT_TRNG_SRC_SEL). Only bit2 feeds the pool packer, so the
# fill and the park differ in that bit alone.
_POOL_STREAM_BIT = 1 << 2
# Every stream on the internal DRBG: this is what actually advances the pool
# packer. Clearing bit2 alone does not -- the pool leg only fills while the
# internal DRBG is being driven for the other streams as well.
_SRC_SEL_FILL = 0x0
# Pool back on the idle external source so the half-word freezes, with the Key
# Manager stream left internal so the value is NOT the RDL reset. Both are
# required at once: a frozen packer, and a sel a post-reset read can tell apart
# from the reset value.
_SRC_SEL_PARKED = (_SRC_SEL_RESET | _POOL_STREAM_BIT) & ~0x1
_FIPS_LOCK_BIT = ENTROPY_SOURCE.fields("FIPS_LOCK")["LOCK"]["bm"]
_ESRC_CTRL_RSVD0 = ENTROPY_SOURCE.fields("CTRL")["RSVD0"]["bm"]


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
        raise AssertionError(f"entropy pool did not become {'nonempty' if nonzero else 'empty'}")

    def _packer_depth(self) -> int:
        val = cocotb.top.entropy_pool_packer_depth_o.value
        assert val.is_resolvable, "entropy_pool_packer_depth_o is unresolvable"
        return int(val)

    async def _wait_packer_depth(self, expected: int, timeout: int = 80_000) -> None:
        for _ in range(timeout):
            if self._packer_depth() == expected:
                return
            await ClockCycles(cocotb.top.clk_i, 1)
        raise AssertionError(
            f"entropy pool packer did not reach depth {expected} "
            f"(observed {self._packer_depth()})"
        )

    async def _unstick_packer(self) -> None:
        """A full packed word with a full pool never returns to depth 1."""
        if self._packer_depth() != 2:
            return
        await ClockCycles(cocotb.top.clk_i, 8)
        if self._packer_depth() != 2:
            return
        pop = await self._read(POOL_POP, length=8)
        assert pop.resp_ok, "pool pop to unstick packer depth 2 failed"

    async def _commit_parked_sel(self) -> int | None:
        await self._write(EXT_TRNG_SRC_SEL, _SRC_SEL_PARKED)
        await ClockCycles(cocotb.top.clk_i, 2)
        parked_sel = (await self._read(EXT_TRNG_SRC_SEL)).rdata & _SRC_SEL_MASK
        if parked_sel == _SRC_SEL_PARKED and self._packer_depth() == 1:
            return parked_sel
        return None

    async def _park_half_packed_word(self) -> int:
        """Leave the 32->64 packer holding one word, with a non-reset sel.

        An AXI source-select write is not a freeze: EDN can deliver the pairing
        word while that write is in flight. ``EDN_ENABLE=False`` stops further
        acks; the mux write then only programs the post-reset sel baseline.
        One arm freezes from depth 1 (no extra ack in the disable window). The
        other freezes from depth 0 (one extra ack in that window). Either EDN
        rate lands on depth 1.
        """
        await self._write(EXT_TRNG_SRC_SEL, _SRC_SEL_FILL)
        for phase in range(32):
            await self._write(EDN_CTRL, EDN_CTRL_AUTO)
            await self._unstick_packer()
            await self._wait_packer_depth(1)
            await ClockCycles(cocotb.top.clk_i, phase)
            if self._packer_depth() == 1:
                await self._write(EDN_CTRL, EDN_CTRL_DISABLE)
                await ClockCycles(cocotb.top.clk_i, 4)
                if self._packer_depth() == 1:
                    parked = await self._commit_parked_sel()
                    if parked is not None:
                        return parked
            await self._write(EDN_CTRL, EDN_CTRL_AUTO)
            await ClockCycles(cocotb.top.clk_i, 4 + phase)
            if self._packer_depth() == 0:
                await self._write(EDN_CTRL, EDN_CTRL_DISABLE)
                await ClockCycles(cocotb.top.clk_i, 4)
                if self._packer_depth() == 1:
                    parked = await self._commit_parked_sel()
                    if parked is not None:
                        return parked
        raise AssertionError("could not park one half-packed entropy word")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await self.bring_up_entropy(strict=False, score_km=False)
        assert await self.wait_genbits(), "initial DRBG did not produce genbits"
        assert (await self._read(ESRC_FIPS_LOCK)).rdata & _FIPS_LOCK_BIT, (
            "initial entropy bring-up did not lock the certified ESRC configuration"
        )

        initial_level = await self._wait_pool_level(nonzero=True)
        self.logger.info(
            "CHK-TRNG-FILL PASS: genbits produced, ESRC FIPS_LOCK set, pool level=%d",
            initial_level,
        )

        # Both INTR_ENABLEs reset to 0, so a 0-before/0-after read
        # proves nothing. Drive them to their full implemented masks first, so the
        # post-reset zero is a real 1->0 return to the register-map reset.
        csrng_ie = CSRNG.mask("INTR_ENABLE")
        edn_ie = EDN.mask("INTR_ENABLE")
        await self._write(CSRNG_INTR_ENABLE, csrng_ie)
        await self._write(EDN_INTR_ENABLE, edn_ie)
        csrng_ie_set = (await self._read(CSRNG_INTR_ENABLE)).rdata & csrng_ie
        edn_ie_set = (await self._read(EDN_INTR_ENABLE)).rdata & edn_ie
        assert csrng_ie_set == csrng_ie, (
            f"CSRNG INTR_ENABLE did not take 0x{csrng_ie:x} before the reset: 0x{csrng_ie_set:x}"
        )
        assert edn_ie_set == edn_ie, (
            f"EDN INTR_ENABLE did not take 0x{edn_ie:x} before the reset: 0x{edn_ie_set:x}"
        )

        resets = SepSwReset(self)
        saved = await resets.read_back()
        resets.value = saved
        await resets.park("aes", "kmac", "otbn", "km")

        # Hold both at the reset: the 32->64 packer parked half full, and a sel
        # a post-reset read can distinguish from the RDL reset. EDN_ENABLE=False
        # stops further acks so the half-word cannot complete during the
        # source-select write; that write only sets the non-reset sel.
        parked_sel = await self._park_half_packed_word()
        assert parked_sel != _SRC_SEL_RESET, (
            "test bug: parked source-select equals the RDL reset, so a "
            "post-reset match cannot prove the CSR is outside the domain"
        )

        # Queue one access to each internal CSR aperture before the SW reset
        # write. The AXI master can have these reads outstanding together while
        # the coordinator drains all three isolates. Accepted reads complete;
        # any not yet accepted are terminated with SLVERR, and none may hang.
        axi_driver = self.env.axi_agent.driver
        drain_reads = [
            axi_driver.axi.init_read(address=addr, length=4, size=2)
            for addr in (ESRC_COMPONENT_ID, CSRNG_INTR_STATE, EDN_INTR_STATE)
        ]
        assert self._packer_depth() == 1, (
            "packer depth was not 1 immediately before the TRNG reset; "
            "CHK-TRNG-PACKER requires a parked half-packed word"
        )
        reset_task = cocotb.start_soon(resets.park("trng"))

        isolate_seen = False
        outstanding_at_isolate = 0
        for _ in range(1_000):
            isolated = int(cocotb.top.trng_axi_isolated_probe_o.value)
            # Sample when ALL three paths are isolated, which is the moment the
            # record below names. Sampling on the first bit would let the drain
            # finish before 0x7 and still report a read as outstanding.
            if isolated == 0x7 and not isolate_seen:
                isolate_seen = True
                outstanding_at_isolate = sum(1 for event in drain_reads if not event.is_set())
            if int(cocotb.top.trng_gated_rst_n_probe_o.value) == 0:
                assert isolated == 0x7, (
                    "shared TRNG reset asserted before all three AXI-Lite paths isolated"
                )
                assert isolate_seen and outstanding_at_isolate > 0, (
                    "no pre-reset CSR read was still outstanding at the cycle all "
                    "three paths reported isolated"
                )
                self.logger.info(
                    "CHK-TRNG-ISOLATE-ALL PASS: all three AXI-Lite paths reported "
                    "isolated before the shared TRNG reset asserted "
                    "(%d drain read(s) still outstanding)",
                    outstanding_at_isolate,
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
        drain_codes = [worst_resp(getattr(response, "resp", None)) for response in drain_responses]
        assert all(code in (0, RESP_SLVERR) for code in drain_codes), (
            f"in-flight TRNG CSR accesses returned unexpected responses {drain_codes}"
        )
        assert 0 in drain_codes, "no pre-reset TRNG CSR access drained successfully"
        self.logger.info(
            "CHK-TRNG-DRAIN PASS: in-flight ESRC/CSRNG/EDN reads resolved %s "
            "(no hang, no DECERR); at least one drained OKAY",
            drain_codes,
        )

        await ClockCycles(cocotb.top.clk_i, 20)
        assert self._packer_depth() == 0, (
            "TRNG reset did not scrub the half-packed entropy word"
        )
        self.logger.info(
            "CHK-TRNG-PACKER PASS: the parked half-packed entropy word was scrubbed "
            "by the coordinated reset"
        )

        # Once the coordinated reset is active, each internal CSR isolate must
        # reject new traffic without forwarding it into the reset domain.
        for name, addr in (
            ("esrc", ESRC_COMPONENT_ID),
            ("csrng", CSRNG_INTR_ENABLE),
            ("edn", EDN_INTR_ENABLE),
        ):
            isolated_csr = await self._read(addr, expect_error=True)
            assert isolated_csr.resp_code == RESP_SLVERR, (
                f"{name} CSR did not return SLVERR while TRNG was isolated"
            )
        self.logger.info(
            "CHK-TRNG-SLVERR PASS: all three internal CSR apertures returned SLVERR "
            "while isolated, none forwarded into the reset domain"
        )

        sel_after = (await self._read(EXT_TRNG_SRC_SEL)).rdata & _SRC_SEL_MASK
        assert sel_after == _SRC_SEL_PARKED, (
            f"internal TRNG reset changed EXT_TRNG_SRC_SEL from "
            f"{_SRC_SEL_PARKED:#x} to {sel_after:#x}"
        )
        self.logger.info(
            "CHK-TRNG-EXTERNAL PASS: EXT_TRNG_SRC_SEL still reads the non-reset "
            "value 0x%x after the internal reset, so the source-select CSR is "
            "outside the TRNG reset domain",
            sel_after,
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
        self.logger.info(
            "CHK-TRNG-JTAG PASS: the JTAG override held the coordinated reset through a "
            "software release, isolation cleared under it, and the reset lifted when it dropped"
        )

        held = await resets.read_back()
        for consumer in ("km", "otbn", "aes", "kmac"):
            assert not (held & (1 << SW_RESET_N_BIT[consumer])), (
                f"{consumer} was released before fresh entropy recovery"
            )
        assert held & (1 << SW_RESET_N_BIT["trng"]), (
            "TRNG was not released for ordered reinitialization"
        )
        self.logger.info(
            "CHK-TRNG-CONSUMERS-HELD PASS: km/otbn/aes/kmac stayed held while TRNG was "
            "released for reinitialization (SW_RESET_N=0x%08x)",
            held,
        )
        assert not ((await self._read(ESRC_FIPS_LOCK)).rdata & _FIPS_LOCK_BIT), (
            "shared TRNG reset did not clear ESRC FIPS_LOCK"
        )
        csrng_ie_after = (await self._read(CSRNG_INTR_ENABLE)).rdata & csrng_ie
        edn_ie_after = (await self._read(EDN_INTR_ENABLE)).rdata & edn_ie
        assert csrng_ie_after == 0, (
            f"CSRNG INTR_ENABLE did not return to its reset: 0x{csrng_ie_set:x} -> "
            f"0x{csrng_ie_after:x}"
        )
        assert edn_ie_after == 0, (
            f"EDN INTR_ENABLE did not return to its reset: 0x{edn_ie_set:x} -> 0x{edn_ie_after:x}"
        )

        # CTRL[0] is reserved RAZ/WI: it reads 0, a write of 1 is ignored,
        # and neighboring fields do not move.
        esrc_ctrl = (await self._read(ESRC_CTRL)).rdata & 0xFFFF_FFFF
        assert (esrc_ctrl & _ESRC_CTRL_RSVD0) == 0, (
            f"reserved ESRC CTRL[0] is not RAZ before the write: 0x{esrc_ctrl:x}"
        )
        await self._write(ESRC_CTRL, esrc_ctrl | _ESRC_CTRL_RSVD0)
        esrc_ctrl_after = (await self._read(ESRC_CTRL)).rdata & 0xFFFF_FFFF
        assert (esrc_ctrl_after & _ESRC_CTRL_RSVD0) == 0, (
            f"reserved ESRC CTRL[0] took a write of 1: 0x{esrc_ctrl_after:x}"
        )
        assert esrc_ctrl_after == esrc_ctrl, (
            f"writing reserved ESRC CTRL[0] changed neighboring fields: "
            f"0x{esrc_ctrl:x} -> 0x{esrc_ctrl_after:x}"
        )
        self.logger.info(
            "CHK-TRNG-CSR-RESET PASS: ESRC FIPS_LOCK cleared, CSRNG INTR_ENABLE "
            "0x%x->0x%x and EDN 0x%x->0x%x returned to reset, CTRL[0] RAZ then WI",
            csrng_ie_set,
            csrng_ie_after,
            edn_ie_set,
            edn_ie_after,
        )

        # TRNG is released for reinitialization, but EDN is reset/disabled and
        # consumers remain held. The synchronous clear must have removed every
        # cached word and any half-packed input. Reconfiguration below switches
        # all three source legs back to the internal DRBG.
        await self._wait_pool_level(nonzero=False)
        empty_pop = await self._read(POOL_POP, length=8, expect_error=True)
        # A live empty pool refuses the pop with SLVERR. DECERR would mean the
        # aperture decoded as unused or reset-isolated, which is the opposite
        # of recovery. The VPLAN CHK-TRNG-STALE row states that pin.
        assert empty_pop.resp_code == RESP_SLVERR, (
            f"empty pool resp={empty_pop.resp_code} after TRNG reset, expected SLVERR"
        )
        assert empty_pop.rdata == 0, "empty pool exposed stale pre-reset entropy"
        self.logger.info(
            "CHK-TRNG-STALE PASS: pool drained to 0 and the empty pop was refused with "
            "rdata=0, so no pre-reset entropy survived"
        )

        cfg = self.entropy_cfg
        await self.start_seq(SepEsrcConfigSeq("esrc_reconfig", cfg=cfg, reset_trng=False))
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_restart_gens"))
        assert await self.wait_seed_ready(), "ESRC did not produce a fresh seed after reset"
        await self.start_seq(SepEsrcEnableEdnSeq("edn_restart"))
        assert (await self._read(ESRC_FIPS_LOCK)).rdata & _FIPS_LOCK_BIT, (
            "recovery did not restore ESRC FIPS_LOCK"
        )

        fresh_level = await self._wait_pool_level(nonzero=True)
        fresh_pop = await self._read(POOL_POP, length=8)
        assert fresh_pop.resp_ok, "fresh entropy-pool read failed after recovery"
        self.logger.info(
            "CHK-TRNG-FRESH PASS: ESRC produced a fresh seed, FIPS_LOCK was restored, "
            "and the pool refilled to %d and served an OKAY pop",
            fresh_level,
        )
        await self.check_entropy_alerts_zero()

        await resets.restore_after_trng_reinit(saved)
        assert await resets.read_back() == saved, "consumer resets were not restored"
        self.logger.info(
            "CHK-TRNG-RECOVERY PASS: pool %d->0->%d, stale read rejected, "
            "fresh data delivered before consumers restored",
            initial_level,
            fresh_level,
        )

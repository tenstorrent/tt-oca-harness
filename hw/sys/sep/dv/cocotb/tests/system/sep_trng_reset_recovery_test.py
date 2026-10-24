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

FCOV: the graded window of this leaf opens right before the drain reads and
closes after CHK-TRNG-FRESH; a FAIL closes it first. The cp_trng_drain answers
sample only on the rise of the pass label that CHK-TRNG-DRAIN writes after it
passes.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import (
    ClockCycles,
    FallingEdge,
    NextTimeStep,
    ReadOnly,
    RisingEdge,
    Timer,
    with_timeout,
)
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_trng_drain_pass
from env.sep_reg_meta import CSRNG, EDN, ENTROPY_SOURCE, SEP_CPU_CTRL, sym
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_entropy_pool_seq import (
    EDN_CTRL_DISABLE,
    POOL_POP,
    POOL_STATUS,
    RESP_OKAY,
    RESP_SLVERR,
    pool_level,
)
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
# Read data of a new transaction on an isolated path: SLVERR with 0x1501A7ED in
# each 32-bit word (hw/sys/sep/doc/reset_controller.adoc:127-129). No generated
# constant holds it.
ISO_DATA = 0x1501_A7ED

TEST = "sep_trng_reset_recovery_test"

# Issue slot of the CSRNG and EDN drain reads, drawn from the seed: slot 0
# issues the read before the SW_RESET_N write, as the ESRC read always is;
# slot k > 0 issues it k - 1 clk_i edges after the reset write starts. Late
# slots put the read near the isolation request, so the isolate either
# accepts and drains it (OKAY) or refuses it (SLVERR); CHK-TRNG-DRAIN grades
# whichever answer each read gets. DV-owned range: no text fixes the latency
# from the write to the isolation request.
_DRAIN_LATE_SLOTS = 16


@pyuvm.test()
class sep_trng_reset_recovery_test(sep_base_test):
    """Prove pool scrub and fresh-only ordered TRNG recovery."""

    def _grade(self, name: str, ok: bool, detail: str) -> None:
        """Log one PASS or FAIL line; a FAIL closes the graded window, then raises."""
        if ok:
            self.logger.info("%s PASS: %s", name, detail)
            return
        self.logger.error("%s FAIL: %s", name, detail)
        close_graded_window(self.logger)
        raise AssertionError(f"{name} FAIL: {detail}")

    async def _watch_seed(self) -> None:
        """Count clk_i edges and the edges with drbg_seed_valid_o not 0 (X counts as set)."""
        sig = cocotb.top.drbg_seed_valid_o
        while True:
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            self._seed_clocks += 1
            val = sig.value
            if not val.is_resolvable or int(val) != 0:
                self._seed_high += 1

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
            level = pool_level(seq.rdata)
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
            f"entropy pool packer did not reach depth {expected} (observed {self._packer_depth()})"
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

        # A read that equals the reset value before and after the reset proves
        # nothing. Drive both INTR_ENABLEs to their full implemented masks first,
        # so the post-reset read is a real return to the RDL reset value.
        csrng_ie = CSRNG.mask("INTR_ENABLE")
        edn_ie = EDN.mask("INTR_ENABLE")
        assert csrng_ie != CSRNG.reset("INTR_ENABLE") & csrng_ie, (
            "test bug: the CSRNG INTR_ENABLE mask equals its reset value"
        )
        assert edn_ie != EDN.reset("INTR_ENABLE") & edn_ie, (
            "test bug: the EDN INTR_ENABLE mask equals its reset value"
        )
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

        seed = self.random_seed()
        rng = SepSeededRng(seed)
        self._drain_slots = (
            0,
            rng.randrange(0, _DRAIN_LATE_SLOTS + 1),
            rng.randrange(0, _DRAIN_LATE_SLOTS + 1),
        )
        self.logger.info(
            "PLAN %s seed=%d drain_slots esrc=%d csrng=%d edn=%d "
            "(0 = before the reset write, k = k-1 clk_i edges after it starts)",
            TEST,
            seed,
            *self._drain_slots,
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
        # The park can pop the pool to free the packer, so read the level the
        # reset must scrub here, with EDN disabled and nothing left to pop.
        pre_reset_status = await self._read(POOL_STATUS)
        assert pre_reset_status.resp_ok, "entropy-pool status read before the reset failed"
        pre_reset_level = pool_level(pre_reset_status.rdata)
        assert pre_reset_level > 0, (
            "pool level is 0 just before the TRNG reset, so the reset has no queued "
            "word to scrub and CHK-TRNG-STALE cannot prove a scrub"
        )

        set_trng_drain_pass(False, self.logger)
        open_graded_window(TEST, self.logger)
        try:
            fresh_level = await self._graded_reset_recovery(
                resets, csrng_ie, edn_ie, csrng_ie_set, edn_ie_set, pre_reset_level
            )
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            close_graded_window(self.logger)
            set_trng_drain_pass(False, self.logger)
            raise
        close_graded_window(self.logger)
        set_trng_drain_pass(False, self.logger)
        await self.check_entropy_alerts_zero()

        await resets.restore_after_trng_reinit(saved)
        assert await resets.read_back() == saved, "consumer resets were not restored"
        self.logger.info(
            "CHK-TRNG-RECOVERY PASS: pool level %d at fill, %d just before the reset, "
            "0 after it, %d after recovery; stale read rejected, fresh data delivered "
            "before consumers restored",
            initial_level,
            pre_reset_level,
            fresh_level,
        )

    async def _graded_reset_recovery(
        self,
        resets: SepSwReset,
        csrng_ie: int,
        edn_ie: int,
        csrng_ie_set: int,
        edn_ie_set: int,
        pre_reset_level: int,
    ) -> int:
        """TRNG reset, drain, isolation, JTAG hold and reinit; returns the fresh pool level."""
        # Queue one access to each internal CSR aperture, before the SW reset
        # write or at the seed-drawn slot after it starts (_DRAIN_LATE_SLOTS).
        # The AXI master can have these reads outstanding together while the
        # coordinator drains all three isolates. Accepted reads complete; any
        # not yet accepted are terminated with SLVERR, and none may hang.
        axi_driver = self.env.axi_agent.driver
        drain_addrs = (ESRC_COMPONENT_ID, CSRNG_INTR_STATE, EDN_INTR_STATE)
        slots = self._drain_slots
        drain_reads = [
            axi_driver.axi.init_read(address=addr, length=4, size=2)
            for addr, slot in zip(drain_addrs, slots, strict=True)
            if slot == 0
        ]
        late = sorted(
            (slot, addr) for addr, slot in zip(drain_addrs, slots, strict=True) if slot != 0
        )
        assert self._packer_depth() == 1, (
            "packer depth was not 1 immediately before the TRNG reset; "
            "CHK-TRNG-PACKER requires a parked half-packed word"
        )
        reset_task = cocotb.start_soon(resets.park("trng"))

        async def _issue_late() -> None:
            edge = 1
            for slot, addr in late:
                if slot > edge:
                    await ClockCycles(cocotb.top.clk_i, slot - edge)
                    edge = slot
                drain_reads.append(axi_driver.axi.init_read(address=addr, length=4, size=2))

        late_task = cocotb.start_soon(_issue_late())

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
                assert int(cocotb.top.trng_reset_active_probe_o.value) == 0, (
                    "TRNG clear followed the asynchronous reset without synchronization"
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
            # Sample one picosecond after each rising edge, so a value read here
            # is the value that edge produced.
            await RisingEdge(cocotb.top.clk_i)
            await Timer(1, units="ps")
        else:
            raise AssertionError("coordinated TRNG reset did not assert")

        # A 2-flop synchronizer samples the inverted TRNG reset and drives
        # trng_reset_active (hw/sys/sep/doc/crypto.adoc:110-111). Edge 0 is the
        # rising clk_i edge after which the gated reset first reads low; the
        # first flop takes the asserted reset on edge 1 and the second flop on
        # edge 2, so the clear asserts after edge 2 and not on another edge.
        # The release side below counts from the release edge the same way.
        clear_expected = 2
        clear_edge = 0
        for edge in (1, 2, 3):
            await RisingEdge(cocotb.top.clk_i)
            await Timer(1, units="ps")
            if int(cocotb.top.trng_reset_active_probe_o.value) == 1:
                clear_edge = edge
                break
        self._grade(
            "CHK-TRNG-CLEAR-SYNC",
            clear_edge == clear_expected,
            f"clear low on the clk_i edge the gated reset fell, then asserted on edge "
            f"{clear_edge or 'none'} after it (0 = still low after edge 3), expected edge "
            f"{clear_expected} (2-flop synchronizer)",
        )

        await reset_task
        await late_task
        # Grade in address order: ESRC, CSRNG, EDN.
        issue_order = [addr for addr, slot in zip(drain_addrs, slots, strict=True) if slot == 0]
        issue_order += [addr for _, addr in late]
        drain_reads = [drain_reads[issue_order.index(addr)] for addr in drain_addrs]
        drain_responses = []
        for event in drain_reads:
            await with_timeout(event.wait(), 10_000, "ns")
            drain_responses.append(event.data)
        drain_codes = [worst_resp(getattr(response, "resp", None)) for response in drain_responses]
        drain_data = [
            int.from_bytes(bytes(response.data), "little") for response in drain_responses
        ]
        # An accepted read drains OKAY; a read the isolate did not accept gets
        # the isolated answer (reset_controller.adoc:127-130).
        refused_data = [
            data for code, data in zip(drain_codes, drain_data, strict=True) if code == RESP_SLVERR
        ]
        # An OKAY drain read of ESRC COMPONENT_ID was forwarded to ESRC, so it
        # returns the RDL reset of that read-only register (entropy_source.rdl
        # COMPONENT_ID). The INTR_STATE reads return live interrupt state that
        # no text fixes at this point, so their OKAY data is logged only.
        cid_golden = ENTROPY_SOURCE.reset("COMPONENT_ID")
        cid_bad = [
            data
            for addr, code, data in zip(drain_addrs, drain_codes, drain_data, strict=True)
            if addr == ESRC_COMPONENT_ID and code == RESP_OKAY and data != cid_golden
        ]
        self._grade(
            "CHK-TRNG-DRAIN",
            len(drain_codes) == 3
            and all(code in (RESP_OKAY, RESP_SLVERR) for code in drain_codes)
            and RESP_OKAY in drain_codes
            and all(data == ISO_DATA for data in refused_data)
            and not cid_bad,
            f"slots={list(slots)} reads={len(drain_codes)} codes={drain_codes} "
            f"data=[{','.join(f'0x{data:08x}' for data in drain_data)}] "
            f"okay={drain_codes.count(RESP_OKAY)} slverr={len(refused_data)} "
            f"expected: 3 reads, each OKAY or SLVERR, at least one OKAY, "
            f"each SLVERR with data 0x{ISO_DATA:08x}, "
            f"an OKAY ESRC COMPONENT_ID read with data 0x{cid_golden:08x}",
        )
        set_trng_drain_pass(True, self.logger)

        await ClockCycles(cocotb.top.clk_i, 20)
        assert self._packer_depth() == 0, "TRNG reset did not scrub the half-packed entropy word"
        self.logger.info(
            "CHK-TRNG-PACKER PASS: the parked half-packed entropy word was scrubbed "
            "by the coordinated reset"
        )

        # Once the coordinated reset is active, each internal CSR isolate must
        # reject new traffic with the isolated answer, without forwarding it
        # into the reset domain.
        iso_golden = ISO_DATA
        iso_answers: list[tuple[str, int, int]] = []
        for name, addr in (
            ("esrc", ESRC_COMPONENT_ID),
            ("csrng", CSRNG_INTR_ENABLE),
            ("edn", EDN_INTR_ENABLE),
        ):
            isolated_csr = await self._read(addr, expect_error=True)
            iso_answers.append((name, isolated_csr.resp_code, isolated_csr.rdata))
        self._grade(
            "CHK-TRNG-SLVERR",
            all(code == RESP_SLVERR and data == iso_golden for _, code, data in iso_answers),
            " ".join(f"{name}=resp{code}/0x{data:08x}" for name, code, data in iso_answers)
            + f" expected: resp{RESP_SLVERR}/0x{iso_golden:08x} on each of esrc, csrng, edn",
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

        # From here to the generator enable the reset domain is held or
        # released but not reinitialized, so ESRC presents no seed
        # (hw/sys/sep/doc/trng.adoc:198-199).
        self._seed_clocks = 0
        self._seed_high = 0
        seed_watch = cocotb.start_soon(self._watch_seed())
        # The override bit reaches the mux through a 2-flop synchronizer
        # (hw/sys/sep/doc/reset_controller.adoc:55-57), clocked by clk_i, the clock
        # the Reset Controller releases its resets on (:45-47). The clear lands between
        # two rising edges, so the first flop takes it on the first edge after the
        # clear, the second flop on the second edge, and the gated reset releases
        # on that second edge and not on another.
        await FallingEdge(cocotb.top.clk_i)
        jtag_reset.value = 0
        await Timer(1, units="ps")
        assert int(cocotb.top.trng_gated_rst_n_probe_o.value) == 0, (
            "TRNG gated reset released before clk_i sampled the cleared JTAG override"
        )
        await ClockCycles(cocotb.top.clk_i, 1)
        await Timer(1, units="ps")
        assert int(cocotb.top.trng_gated_rst_n_probe_o.value) == 0, (
            "TRNG gated reset released on the first clk_i edge after the JTAG override cleared"
        )
        release_edge = 0
        for edge in (2, 3):
            await ClockCycles(cocotb.top.clk_i, 1)
            await Timer(1, units="ps")
            if int(cocotb.top.trng_gated_rst_n_probe_o.value) == 1:
                release_edge = edge
                break
        assert release_edge == 2, (
            f"CHK-TRNG-JTAG FAIL: TRNG gated reset released on clk_i edge {release_edge or 'none'} "
            "after the JTAG override cleared (0 = still held after edge 3), expected edge 2 "
            "(2-flop synchronizer)"
        )
        assert int(cocotb.top.trng_reset_active_probe_o.value) == 1, (
            "TRNG clear released in the same cycle the gated reset released"
        )
        await ClockCycles(cocotb.top.clk_i, 1)
        await Timer(1, units="ps")
        assert int(cocotb.top.trng_reset_active_probe_o.value) == 1, (
            "TRNG clear released before the second synchronizer edge"
        )
        await ClockCycles(cocotb.top.clk_i, 1)
        await Timer(1, units="ps")
        assert int(cocotb.top.trng_reset_active_probe_o.value) == 0, (
            "TRNG clear did not release after two synchronizer edges"
        )
        self.logger.info(
            "CHK-TRNG-JTAG PASS: the JTAG override held the coordinated reset through a "
            "software release, isolation cleared under it, the gated reset released "
            "on clk_i edge %d after the override cleared (expected 2), and clear released "
            "on the second edge after that",
            release_edge,
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
        csrng_ie_reset = CSRNG.reset("INTR_ENABLE") & csrng_ie
        edn_ie_reset = EDN.reset("INTR_ENABLE") & edn_ie
        assert csrng_ie_after == csrng_ie_reset, (
            f"CSRNG INTR_ENABLE did not return to its reset 0x{csrng_ie_reset:x}: "
            f"0x{csrng_ie_set:x} -> 0x{csrng_ie_after:x}"
        )
        assert edn_ie_after == edn_ie_reset, (
            f"EDN INTR_ENABLE did not return to its reset 0x{edn_ie_reset:x}: "
            f"0x{edn_ie_set:x} -> 0x{edn_ie_after:x}"
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
        # A live empty pool refuses the pop with SLVERR (doc/entropy_pool.adoc:31-33).
        # DECERR would mean the aperture decoded as unused or reset-isolated,
        # which is the opposite of recovery. No text states the read data of the
        # refused pop, so the data is logged only.
        self.logger.info(
            "OBS-TRNG-STALE-RDATA rdata=0x%016x resp=%d", empty_pop.rdata, empty_pop.resp_code
        )
        self._grade(
            "CHK-TRNG-STALE",
            empty_pop.resp_code == RESP_SLVERR,
            f"pool level {pre_reset_level} before the reset, 0 after it, empty pop "
            f"resp={empty_pop.resp_code} expected={RESP_SLVERR} (SLVERR), so the pool "
            "holds no pre-reset word",
        )

        cfg = self.entropy_cfg
        await self.start_seq(SepEsrcConfigSeq("esrc_reconfig", cfg=cfg, reset_trng=False))
        seed_watch.kill()
        early_high, early_clocks = self._seed_high, self._seed_clocks
        if early_high:
            self._grade(
                "CHK-TRNG-NO-EARLY-SEED",
                False,
                f"seed_valid_high_clocks={early_high} of watched_clocks={early_clocks} "
                "before the generator enable, expected 0",
            )
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_restart_gens"))
        fresh_seed = await self.wait_seed_ready()
        assert fresh_seed, "ESRC did not produce a fresh seed after reset"
        self._grade(
            "CHK-TRNG-NO-EARLY-SEED",
            early_high == 0 and early_clocks > 0 and fresh_seed,
            f"seed_valid_high_clocks={early_high} of watched_clocks={early_clocks} from the "
            f"JTAG override clear to the generator enable, seed_after_enable={int(fresh_seed)}; "
            "expected 0 high clocks, then a seed",
        )
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
        return fresh_level

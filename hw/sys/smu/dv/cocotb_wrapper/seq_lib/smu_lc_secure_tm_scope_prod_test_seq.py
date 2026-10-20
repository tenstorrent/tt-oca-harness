# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""In PROD the secure test-mode strap opens no debug path, with and without a SEC_DIS match.

Spec: hw/sys/sep/doc/test_mode.adoc (SECURE_TM does not qualify the debug and function bits;
sampling table), hw/sys/sep/doc/security_disable.adoc (SEC_DIS neither qualifies nor overrides
SECURE_TM; reset persistence), hw/sys/sep/doc/lifecycle_controller.adoc (SECURE_TM is not a term of
feat_ctrl_o; PROD and SEC_DIS rows; "DTP path feature gates"), hw/ip/efuse/regs/efuse_mmr.rdl
(token words, TOKEN_EOP, match code), hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG SIBs).

The PROD eFuse shadow image and the TEST_EN strap ``tb_secure_tm_req``, held high from before the
first clock, are the only stimulus besides the JTAG accesses and one chiplet cold reset. The
steps run in this order:

S1, setup: ``tb_secure_tm`` reads 0 on every sample under the SEP reset, then
    ``sep_fuse_sense_done_o`` rises.
S2, profile: ``tb_secure_tm`` reads 1 and ``lcc_feat_ctrl_o`` is the undemoted PROD word.
S3, SIBs closed: the DFT non-secure and DFT secure SIBs capture 0 with the strap high.
S4, token: eight all-zero words, TOKEN_EOP with the go bit and the match read over the SEP OTP
    bridge.
S5, sample: ``lcc_feat_ctrl_o`` is all ones and ``tb_secure_tm`` still reads 1.
S6, SIBs open: the two SIBs capture 1 and their bench cells join the loop.
S7, cold reset with the strap low: ``tb_secure_tm`` reads 0 from the release; ``lcc_feat_ctrl_o``
    stays all ones and the security-disable net stays high; the lifecycle words are measured and
    logged only.
S8, after the reset: the SMC fabric launches and the DFT secure SIB opens.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_dtp_scan_chain_boundary_seq import (
    DTP_IR_SELECT_IJTAG,
    ijtag_chain,
    ijtag_shift,
    ijtag_word,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import COLD_RESET_BOUND, COLD_RESET_HOLD
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    FEAT_CTRL_FUNCTION_ONLY,
    IJTAG_DR_BIT,
    IJTAG_FLUSH_CAPTURE,
    IJTAG_FLUSH_OPEN_REQUEST,
    IJTAG_SCAN_BITS,
    LANE_DISABLED,
    LAUNCHED_AR_AW_B,
    SENSE_DONE_BOUND_CYCLES,
    ExportSpec,
)
from seq_lib.smu_lc_sec_dis_over_sigint_prod_test_seq import (
    IJTAG_FLUSH_OPEN_CHAIN,
    IJTAG_OPEN_SCAN_BITS,
    MATCH_POLL_BOUND,
    SECURITY_DISABLE_HIGH,
    TOKEN_OP_ADMITTED,
    TOKEN_WORD_VALUE,
    smu_lc_sec_dis_over_sigint_prod_test_seq,
)
from seq_lib.smu_sep_sba_peripheral_test_seq import (
    TOKEN_EOP,
    TOKEN_GO,
    TOKEN_MATCH,
    TOKEN_MATCH_CODE,
    TOKEN_STATUS_MASK,
    TOKEN_WORDS,
)

IMAGE = "sep_efuse_shadow_lc_prod.preload"

SPEC = ExportSpec(
    state="PROD",
    tag="PROD",
    image=IMAGE,
    feat_ctrl=FEAT_CTRL_FUNCTION_ONLY,
    lane=LANE_DISABLED,
)

#: hw/sys/sep/doc/test_mode.adoc, sampling table: a cold reset clears SECURE_TM to 0 and the strap
#: sampled at fuse-sense completion sets it to 1.
SECURE_TM_CLEAR = 0
SECURE_TM_SET = 1
#: Samples taken under the SEP reset before ``sep_fuse_sense_done_o`` rises: at least one.
MIN_RESET_SAMPLES = 1
#: hw/sys/sep/doc/security_disable.adoc, "Reset Persistence": the match holds from cold-reset
#: release. ``clk_smu_i`` edges sampled from the release, long enough to cover the primary TAP
#: reset pulses that follow it.
RELEASE_WINDOW_EDGES = 48
#: Waits for the primary SMC reset release after the cold reset, in clock cycles.
PRIMARY_RELEASE_BOUND = 2000
TAP_RESET_TCKS = 16

#: hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc, "iJTAG Network": a SIB that captures 1 is
#: open, one that captures 0 is closed.
SIB_OPEN_CAPTURED = 1
SIB_CLOSED_CAPTURED = 0
BOTH_DFT_SIBS = frozenset({"dft", "dft_secure"})
DFT_SECURE_ONLY = frozenset({"dft_secure"})
NO_SIBS = frozenset()


class SecureTmResetProbe:
    """``tb_secure_tm`` on every ``clk_smu_i`` edge until ``sep_fuse_sense_done_o`` rises.

    Started before the clocks, so the samples under the SEP reset are the ones the leaf checks.
    On a four-state simulator ``tb_secure_tm`` is X until its first clock under the reset; those
    samples are counted as unknown and are neither highs nor graded samples.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.reset_samples = 0
        self.reset_highs = 0
        self.reset_unknown = 0
        self.strap_low_samples = 0
        self.cycles = 0
        self.done = False

    @staticmethod
    def _bit(pin) -> int | None:
        value = pin.value
        return int(value) & 1 if value.is_resolvable else None

    async def run(self) -> None:
        dut = self.dut
        for _ in range(SENSE_DONE_BOUND_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            self.cycles += 1
            if self._bit(dut.sep_fuse_sense_done_o):
                self.done = True
                return
            if self._bit(dut.obs_sep_rst_n_o) == 0:
                secure_tm = self._bit(dut.tb_secure_tm)
                if secure_tm is None:
                    self.reset_unknown += 1
                    continue
                self.reset_samples += 1
                self.reset_highs += secure_tm != SECURE_TM_CLEAR
                self.strap_low_samples += self._bit(dut.tb_secure_tm_req) != 1


class smu_lc_secure_tm_scope_prod_test_seq(smu_lc_sec_dis_over_sigint_prod_test_seq):
    """The strap high in PROD: paths closed before a SEC_DIS match, open after it and a reset."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.spec = SPEC

    async def _select_ijtag(self) -> None:
        await self._tlr()
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG, back_to_rti=True)

    async def _sibs_closed(self, names: frozenset[str], tag: str) -> tuple[dict, bool, int, int]:
        """Shift 1 into ``names`` of the closed DR, then capture: (captures, flush returned,
        host selects of all three SIBs, TCKs seen)."""
        await self._select_ijtag()
        bits = IJTAG_SCAN_BITS
        open_word = ijtag_word(NO_SIBS, names, IJTAG_FLUSH_OPEN_REQUEST, bits)
        cap_word = ijtag_word(NO_SIBS, NO_SIBS, IJTAG_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(NO_SIBS, open_word, bits)[0]
        want_cap = ijtag_shift(NO_SIBS, cap_word, bits)[0]
        got_open, counts_open = await self._ijtag_scan(open_word, f"{tag}_1", bits)
        got_cap, counts_cap = await self._ijtag_scan(cap_word, f"{tag}_2", bits)
        captures = {name: (got_cap >> IJTAG_DR_BIT[name]) & 1 for name in names}
        selects = sum(counts_open[n] + counts_cap[n] for n in IJTAG_DR_BIT)
        tcks = min(counts_open["tck"], counts_cap["tck"])
        self._log(
            f"CELL ijtag_closed {tag} open_request out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x}"
        )
        return captures, got_open == want_open and got_cap == want_cap, selects, tcks

    async def _sibs_open(self, names: frozenset[str], tag: str) -> tuple[dict, bool, dict]:
        """Open ``names`` and scan through the open chain: (captures, both scans match the model,
        host selects of each name)."""
        await self._select_ijtag()
        bits = IJTAG_OPEN_SCAN_BITS
        open_word = ijtag_word(NO_SIBS, names, IJTAG_FLUSH_OPEN_REQUEST, bits)
        cap_word = ijtag_word(names, names, IJTAG_FLUSH_OPEN_CHAIN, bits)
        want_open = ijtag_shift(NO_SIBS, open_word, bits)[0]
        want_cap = ijtag_shift(names, cap_word, bits)[0]
        got_open, _ = await self._ijtag_scan(open_word, f"{tag}_1", bits)
        got_cap, counts = await self._ijtag_scan(cap_word, f"{tag}_2", bits)
        chain = ijtag_chain(names)
        captures = {
            name: (got_cap >> (len(chain) - 1 - chain.index(("sib", name)))) & 1 for name in names
        }
        selects = {name: counts[name] for name in names}
        self._log(
            f"CELL ijtag_open {tag} open_request out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x} chain_cells={len(chain)}"
        )
        return captures, got_open == want_open and got_cap == want_cap, selects

    async def _cold_reset_with_strap_low(self) -> dict:
        """Drop the strap, cycle ``rst_cold_ni`` and sample every ``clk_smu_i`` edge from the
        release."""
        dut = self.dut
        dut.tb_secure_tm_req.value = 0
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        last = "no sample"
        for cycle in range(1, COLD_RESET_BOUND + 1):
            await RisingEdge(dut.clk_ref_i)
            done = self._rd("sep_fuse_sense_done_o")
            rst_n = self._rd("obs_sep_rst_n_o")
            last = f"sep_fuse_sense_done_o={done} obs_sep_rst_n_o={rst_n}"
            if done == 0 and rst_n == 0:
                self._record("reset_assert", COLD_RESET_BOUND, cycle, "clk_ref_i cycles", last)
                break
        else:
            self._record(
                "reset_assert",
                COLD_RESET_BOUND,
                COLD_RESET_BOUND,
                "clk_ref_i cycles",
                last,
                expired=True,
            )
        await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD)
        window = cocotb.start_soon(self._release_window())
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.test.jtag_tap_reset(TAP_RESET_TCKS)
        return await window

    async def _release_window(self) -> dict:
        out = {
            "samples": 0,
            "secure_tm": [],
            "feat": [],
            "net": [],
            "strap": [],
            "words": [],
        }
        for _ in range(RELEASE_WINDOW_EDGES):
            await RisingEdge(self.dut.clk_smu_i)
            out["samples"] += 1
            out["secure_tm"].append(self._rd("tb_secure_tm"))
            out["feat"].append(self._rd("lcc_feat_ctrl_o"))
            out["net"].append(self._net())
            out["strap"].append(self._rd("tb_secure_tm_req"))
            out["words"].append(
                (
                    self._rd("lc_state_o"),
                    self._rd("obs_sep_lc_state_o"),
                    self._rd("smc_lc_state_in_o"),
                    self._rd("sep_fuse_sense_done_o"),
                    self._rd("lcc_dbg_disable_o"),
                )
            )
        self._record(
            "release_window",
            RELEASE_WINDOW_EDGES,
            out["samples"],
            "clk_smu_i edges",
            f"feat={sorted(set(out['feat']))} secure_tm={sorted(set(out['secure_tm']))}",
        )
        return out

    async def _primary_released(self) -> None:
        """Wait for the cold and SMC primary resets to release before the fabric access."""
        dut = self.dut
        for label, sig, clk in (
            ("cold_release", dut.rst_cold_n_o, dut.clk_ref_i),
            ("smc_primary_release", dut.rst_primary_smc_clk_n_o, dut.clk_smu_i),
        ):
            try:
                used = await self.test.wait_signal_high(
                    sig, clk, timeout_cycles=PRIMARY_RELEASE_BOUND, name=label
                )
            except AssertionError as err:
                self._record(
                    label,
                    PRIMARY_RELEASE_BOUND,
                    PRIMARY_RELEASE_BOUND,
                    "cycles",
                    str(err),
                    expired=True,
                )
                raise
            self._record(label, PRIMARY_RELEASE_BOUND, used, "cycles", f"{label} high")

    async def run(self) -> None:
        probe = self.test.reset_probe

        await self._mark(
            "SETUP: PROD image, strap high from time zero, wait for sep_fuse_sense_done_o"
        )
        await self._setup()
        await self.test.reset_probe_task
        self._record(
            "reset_probe",
            SENSE_DONE_BOUND_CYCLES,
            probe.cycles,
            "clk_smu_i cycles",
            f"reset_samples={probe.reset_samples} reset_highs={probe.reset_highs}",
            expired=not probe.done,
        )

        await self._mark("PROFILE: tb_secure_tm and lcc_feat_ctrl_o after sense done")
        await RisingEdge(self.dut.clk_smu_i)
        secure_tm_done = self._rd("tb_secure_tm")
        feat_profile = self._rd("lcc_feat_ctrl_o")
        strap_profile = self._rd("tb_secure_tm_req")
        done = self._rd("sep_fuse_sense_done_o")
        self._check(
            "CHK-LC-SECTM-PROD-PROFILE",
            f"under reset samples={probe.reset_samples} highs={probe.reset_highs} "
            f"unknown={probe.reset_unknown} strap_low_samples={probe.strap_low_samples}; "
            f"after sense done tb_secure_tm="
            f"{secure_tm_done} strap={strap_profile} lcc_feat_ctrl_o=0x{feat_profile:016x} "
            f"want=0x{FEAT_CTRL_FUNCTION_ONLY:016x} sense_done={done}",
            (
                probe.reset_samples >= MIN_RESET_SAMPLES,
                probe.reset_highs,
                probe.strap_low_samples,
                secure_tm_done,
                strap_profile,
                feat_profile,
            ),
            (True, 0, 0, SECURE_TM_SET, 1, FEAT_CTRL_FUNCTION_ONLY),
        )

        await self._mark("SIBS CLOSED: DFT non-secure and DFT secure SIBs with the strap high")
        closed, closed_flush, closed_selects, closed_tcks = await self._sibs_closed(
            BOTH_DFT_SIBS, "closed"
        )
        secure_tm_closed = self._rd("tb_secure_tm")
        self._check(
            "CHK-LC-SECTM-DFT-SIBS-CLOSED-STRAP-HIGH",
            f"tb_secure_tm={secure_tm_closed} SIB captures={closed} want=0 "
            f"flush_returned={int(closed_flush)} host_selects={closed_selects} "
            f"tck_seen={closed_tcks} (witness want >={IJTAG_SCAN_BITS})",
            (
                secure_tm_closed,
                closed,
                closed_flush,
                closed_selects,
                closed_tcks >= IJTAG_SCAN_BITS,
            ),
            (
                SECURE_TM_SET,
                dict.fromkeys(BOTH_DFT_SIBS, SIB_CLOSED_CAPTURED),
                True,
                0,
                True,
            ),
        )

        await self._mark("TOKEN: eight zero words, go bit and match read over the SEP OTP bridge")
        write_ops = [
            await self._sep_otp_write(addr, TOKEN_WORD_VALUE, f"SEC_DISABLE_TOKEN_I[{i}]")
            for i, addr in enumerate(TOKEN_WORDS)
        ]
        eop_op = await self._sep_otp_write(TOKEN_EOP, TOKEN_GO, "TOKEN_EOP go")
        match_reads = 0
        status = -1
        match_op = -1
        for _ in range(MATCH_POLL_BOUND):
            match_op, raw = await self._sep_otp_read(TOKEN_MATCH, "SEC_DISABLE_TOKEN_MATCH")
            status = raw & TOKEN_STATUS_MASK
            match_reads += 1
            if status == TOKEN_MATCH_CODE:
                break
        self._record(
            "token_match",
            MATCH_POLL_BOUND,
            match_reads,
            "polls",
            f"status=0x{status:02x}",
            expired=(status != TOKEN_MATCH_CODE),
        )

        await self._mark("SAMPLE: lcc_feat_ctrl_o and tb_secure_tm after the match")
        feat_match = await self._feat()
        secure_tm_match = self._rd("tb_secure_tm")
        net_match = self._net()
        self._check(
            "CHK-LC-SECTM-SECDIS-NOT-QUALIFIED",
            f"ops writes={write_ops} eop={eop_op} read_match={match_op} match=0x{status:02x} "
            f"want=0x{TOKEN_MATCH_CODE:02x}; lcc_feat_ctrl_o=0x{feat_match:016x} "
            f"want=0x{FEAT_CTRL_ALL_ENABLED:016x} tb_secure_tm={secure_tm_match}",
            (write_ops, eop_op, match_op, status, feat_match, secure_tm_match),
            (
                [TOKEN_OP_ADMITTED] * len(TOKEN_WORDS),
                TOKEN_OP_ADMITTED,
                TOKEN_OP_ADMITTED,
                TOKEN_MATCH_CODE,
                FEAT_CTRL_ALL_ENABLED,
                SECURE_TM_SET,
            ),
        )

        await self._mark("SIBS OPEN: DFT non-secure and DFT secure SIBs with the match held")
        opened, open_flush, open_selects = await self._sibs_open(BOTH_DFT_SIBS, "open")
        feat_joint = await self._feat()
        secure_tm_joint = self._rd("tb_secure_tm")
        self._check(
            "CHK-LC-SECTM-INT-SECDIS-JOINT",
            f"lcc_feat_ctrl_o=0x{feat_joint:016x} want=0x{FEAT_CTRL_ALL_ENABLED:016x} "
            f"tb_secure_tm={secure_tm_joint} SIB captures={opened} (closed before the match: "
            f"{closed}) scans_match_model={int(open_flush)} host_selects={open_selects} "
            f"(want >={IJTAG_OPEN_SCAN_BITS})",
            (
                feat_joint,
                secure_tm_joint,
                opened,
                closed,
                open_flush,
                {name: open_selects[name] >= IJTAG_OPEN_SCAN_BITS for name in open_selects},
            ),
            (
                FEAT_CTRL_ALL_ENABLED,
                SECURE_TM_SET,
                dict.fromkeys(BOTH_DFT_SIBS, SIB_OPEN_CAPTURED),
                dict.fromkeys(BOTH_DFT_SIBS, SIB_CLOSED_CAPTURED),
                True,
                dict.fromkeys(BOTH_DFT_SIBS, True),
            ),
        )

        await self._mark("COLD RESET: strap low, release, sample every edge from the release")
        window = await self._cold_reset_with_strap_low()
        first, last = window["words"][0], window["words"][-1]
        for point, words in (("release", first), ("window end", last)):
            self._log(
                f"OBSERVATION CHK-LC-SECDIS-PERSIST-COLD-RESET-PROD-TM: {point} "
                f"lc_state_o=0x{words[0]:02x} obs_sep_lc_state_o=0x{words[1]:02x} "
                f"smc_lc_state_in_o=0x{words[2]:02x} sep_fuse_sense_done_o={words[3]} "
                f"lcc_dbg_disable_o=0x{words[4]:04x} measured=1 (measured and logged only)"
            )
        self._check(
            "CHK-LC-SECTM-COLD-RESET-CLEARS-STRAP-LOW",
            f"tb_secure_tm samples from the release={sorted(set(window['secure_tm']))} "
            f"over {window['samples']} edges strap={sorted(set(window['strap']))} "
            f"(before the reset tb_secure_tm={secure_tm_match})",
            (
                secure_tm_match,
                window["samples"] > 0,
                sorted(set(window["strap"])),
                sorted(set(window["secure_tm"])),
            ),
            (SECURE_TM_SET, True, [0], [SECURE_TM_CLEAR]),
        )

        await self._mark("AFTER THE RESET: fabric SINGLE_OP read and write, DFT secure SIB")
        await self._primary_released()
        await self._tlr()
        start, end, delta = await self._fabric_deltas(launches=True, tag="_after_reset")
        secure, secure_flush, secure_selects = await self._sibs_open(DFT_SECURE_ONLY, "after_reset")
        self._check(
            "CHK-LC-SECDIS-PERSIST-COLD-RESET-PROD-TM",
            f"before the reset lcc_feat_ctrl_o=0x{feat_match:016x} net={net_match}; from the "
            f"release feat={[f'0x{w:016x}' for w in sorted(set(window['feat']))]} "
            f"net (SMU, SMC)={sorted(set(window['net']))} over {window['samples']} edges; "
            f"AR/AW/B deltas={delta} counts {start}->{end}; DFT secure SIB capture={secure} "
            f"scans_match_model={int(secure_flush)} host_selects={secure_selects} "
            f"(want >={IJTAG_OPEN_SCAN_BITS}); lifecycle words measured and logged only",
            (
                feat_match,
                net_match,
                window["samples"] > 0,
                sorted(set(window["feat"])),
                sorted(set(window["net"])),
                delta,
                secure,
                secure_flush,
                {n: secure_selects[n] >= IJTAG_OPEN_SCAN_BITS for n in secure_selects},
            ),
            (
                FEAT_CTRL_ALL_ENABLED,
                (SECURITY_DISABLE_HIGH, SECURITY_DISABLE_HIGH),
                True,
                [FEAT_CTRL_ALL_ENABLED],
                [(SECURITY_DISABLE_HIGH, SECURITY_DISABLE_HIGH)],
                LAUNCHED_AR_AW_B,
                {"dft_secure": SIB_OPEN_CAPTURED},
                True,
                {"dft_secure": True},
            ),
        )

        labels = [
            "reset_probe",
            "sense_done",
            "ijtag_window_closed_1",
            "ijtag_window_closed_2",
            *["otp_write"] * (len(TOKEN_WORDS) + 1),
            *["otp_read"] * match_reads,
            "token_match",
            "ijtag_window_open_1",
            "ijtag_window_open_2",
            "reset_assert",
            "release_window",
            "cold_release",
            "smc_primary_release",
            "fabric_ar_after_reset",
            "fabric_b_after_reset",
            "ijtag_window_after_reset_1",
            "ijtag_window_after_reset_2",
        ]
        await self._finish(sorted(labels))

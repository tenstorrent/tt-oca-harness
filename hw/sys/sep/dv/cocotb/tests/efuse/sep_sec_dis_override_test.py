# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEC_DIS token-match override of LCC ``FEAT_CTRL``, plus the sense-gated reset.

RAND-NONE. Real fuse sense (no ``+skip_fuse_sense``). The comparator hashes
the written ``SEC_DISABLE_TOKEN_I`` and compares it to the metal expected
digest ``SEP_SEC_DISABLE_TOKEN``. ``tb_top`` binds that parameter to
SHA-256 of the all-zero 32-byte token so a frontdoor write of zeros can
match. A nonzero token still mismatches. On match, ``sec_dis`` asserts and
``FEAT_CTRL`` follows ``feat_ctrl_expected(..., sec_dis=1)`` (all features
on). A later mismatch drops ``sec_dis`` and restores the fail-closed PROD
golden. The test does not
force ``sec_dis``.

hw/sys/sep/doc/security_disable.adoc: a match does not release the SEP
reset. The IC_RESET ``sep_reset_n`` override is an independent step: it
releases both reset probes and leaves feature control closed. The match
then opens feature control without waiting for sensing
(hw/sys/sep/doc/token_processing.adoc) and leaves the reset held. Clearing
the override returns both probes to 0.

The evidence is the two reset probes and ``FEAT_CTRL``. The test drives
``jtag_sep_reset_n_ovrd_i`` and ``jtag_sep_reset_n_val_i``. A read of a
block that reset holds, and a shift of the IC_RESET TDR, are
``sep_sec_dis_reset_reach_test``.

Until sensing completes the SEP core is held in reset
(hw/sys/sep/doc/reset_controller.adoc), so the core load path issues nothing
then. The test uses the masters that exist in that state: the OTP JTAG port
presents the stopped-sense tokens (the match and the CHK-DROP mismatch) and
makes every eFuse access of the retained window, and each frontdoor read of
``FEAT_CTRL`` or the shadow map while sense stays stopped runs inside a release
by the IC_RESET override, which security_disable.adoc names as the release of
a part whose sense does not complete. Each such release ends with both probes
back at 0 before the next step.

While SEC_DIS is active and sensing is still open, a read of the
``LC_STATE`` shadow-map word must return AXI OKAY.

A match while sensing is still open stops the sense: the shim stream does
not reach the shadow registers, so ``sep_fuse_sense_done_o`` stays 0.
SEC_DIS is for a part whose sense is already broken, and the recovery
flow is a reset after the token. The token digest and its valid bit are
latches that ``rst_ni`` does not clear (hw/sys/sep/doc/security_disable.adoc:
the token state is retained across reset), so after that reset SEC_DIS is
still active, sense stays stopped, the map stays open, and the IC_RESET
override still releases the SEP reset. A mismatch token then drops SEC_DIS
and a second reset runs a full sense against the staged image. That sense
is the live control for both stuck windows: it must finish in fewer cycles
than each window waited.

In that retained window (SEC_DIS=1, sense stopped, every shadow at its reset
value) the JTAG AXI-Lite port writes the shadow map. The lifecycle filter
restricts JTAG only in PROD and RMA_SIP, and the held ``LC_STATE`` is
neither, so the port reaches the map. Whether a writable shadow takes the
write is logged (OBS-SECDIS-SHADOW-WR). The
``LC_STATE`` write leaves the word at its reset value 0x0000000f
(CHK-SECDIS-LC-WR): the held word is the INVALID encoding, which is terminal.
Its JTAG write response has no golden and is logged (OBS-SECDIS-LC-WR). The
external debug bus is watched around those writes and in a quiet window on each
side of them and logged (OBS-SECDIS-DBG-BUS): no specification puts eFuse state on that bus.

Before sense and before any token, on the first ``clk_i`` edge with ``rst_ni``
high, ``lc_state_o`` reads the ``LC_STATE`` reset value 0x0F, the INVALID
encoding (CHK-LC-STATE-PORT). The debug and test gate ports are read in two
windows with sense still open: before the token (SEC_DIS 0, the INVALID
profile, every feature closed) and after the stopped-sense match (SEC_DIS 1,
every feature open). ``dbg_disable_<path>_o`` has a stated level in both
(CHK-DBG-DISABLE). No document states the level of ``sep_fuse_dft_disable_o``
and ``smc_fuse_dft_disable_o``, so they are graded against two controls of the
same leaf, read after the full sense: the fail-closed PROD profile (closed) and
the post-sense match (open). The pre-sense read equals the closed control, the
stopped-sense SEC_DIS read equals the open control, and the two controls differ
(CHK-FUSE-DFT-CLASS); OBS-DTP-PORT-LEVEL logs the levels.

After a later full sense, a fresh match on the PROD image opens
``FEAT_CTRL`` with the ``TEST_EN`` strap at 0: the register and the
feature-control probe are all ones and ``secure_tm_o`` is 0.

Checks (``CHK-<ID> PASS`` lines; every failure raises; OBS-SECDIS-LC-WR,
OBS-SECDIS-SHADOW-WR, OBS-SECDIS-DBG-BUS and OBS-DTP-PORT-LEVEL are log lines):

  CHK-LC-STATE-PORT      first clk_i edge after the rst_ni release, sense open:
                         lc_state_o == LC_STATE reset value 0x0F (INVALID)
  CHK-OVR-ALONE          the IC_RESET override alone releases the reset, FEAT_CTRL closed
  CHK-DBG-DISABLE        sense open: every gated dbg_disable path 1 and the ungated
                         paths 0 before the token; every path 0 under the match
  CHK-SENSE-GATED-RESET  a match does not release the sense-gated reset
  CHK-FEAT-PRESENSE      at one clock after the match, with no override, sense not
                         done: lcc_feat_ctrl_probe_o all ones and
                         sep_cpu_reset_n_o = dbg_sep_reset_n_o = 0. Control window:
                         an override release in the same window reads both resets
                         1 and a frontdoor FEAT_CTRL of all ones
  CHK-OVR-AFTER          the override releases the reset after the match
  CHK-MAP-OPEN           LC_STATE shadow read answers OKAY under SEC_DIS
  CHK-SENSE-STUCK        sense stays stopped and the reset held under SEC_DIS
  CHK-RETAIN-*           the same five contracts after rst_ni with the token kept
  CHK-RETAIN-LC-RESET    after that rst_ni the LC_STATE word reads its reset value
                         0x0F (control: the word read a sensed value before it)
  CHK-SECDIS-LC-WR       a JTAG write of PROD to that INVALID word under SEC_DIS
                         leaves it at 0x0000000f (JTAG readback)
  CTRL-SECDIS-JTAG-REACH every JTAG read of that window answers AXI OKAY
  OBS-SECDIS-JTAG-TOKEN-RESP  the JTAG token presentations: accesses not answered
                         OKAY (no TT text states their response code)
  CHK-DROP               a mismatch drops SEC_DIS
  CHK-SENSE-CONTROL      a healthy sense finishes inside each stuck window
  CHK-MISMATCH, CHK-NO-OVERRIDE  mismatch code and the fail-closed PROD FEAT_CTRL
  CHK-MATCH, CHK-OVERRIDE        match code and the all-ones FEAT_CTRL
  CHK-OVERRIDE-TM0       at CHK-OVERRIDE with the strap at 0 (control: CHK-HOOK):
                         FEAT_CTRL == lcc_feat_ctrl_probe_o == all ones, secure_tm_o == 0
  CHK-FUSE-DFT-CLASS     each fuse DFT port: pre-sense read == closed control,
                         stopped-sense SEC_DIS read == open control, controls differ
  CHK-DEACTIVATE, CHK-RESTORE    mismatch code and the PROD FEAT_CTRL again

FCOV owner windows (``env/sep_fcov_gate.py``). The sampler holds each owned
event as pending and samples it only on the rise of its bit of the pass label
``ovr_pass``, which the leaf writes after the check of that event passes. A
FAIL closes the window before the label, which drops the pending event.

* From before the first ``rst_ni`` release to the stopped-sense gate read: the
  port value at the first clock after the release
  (``sep_lc_port_gate_cg.cp_presense_port``) and the before-sense and SEC_DIS
  cells of ``x_cond_gate``. Both points carry their level in ``illegal_bins``
  (the fuse DFT cells record the condition only). The window closes before the
  first override release under SEC_DIS, so the pending events below start
  empty.
* CHK-OVR-AFTER in the first stopped-sense window: the override release with
  SEC_DIS on (``sep_sec_dis_boot_cg.cp_alone`` ``override_open``), released by
  bit 0 after CHK-OVR-AFTER passes.
* After the full sense with the strap at 0, from the match to CHK-OVERRIDE-TM0:
  the entry into SEC_DIS with the feature-control probe all ones
  (``x_secdis_stm_feat`` ``secure_tm_0``), released by bit 1 after
  CHK-OVERRIDE-TM0 passes.

CHK-RETAIN-OVR and the matches after it until the full sense run with no window
open; the stuck-sense match runs in the first window, which closes before any
pass label rises, so its pending ``x_secdis_stm_feat`` event drops: there
``secure_tm_o`` holds its reset value, not a strap sample.
"""

from __future__ import annotations

from collections.abc import Awaitable

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import LC_FIELD_MASK, SepEfuseImage, lc_encode
from env.sep_fcov_gate import (
    OVR_PASS_ALONE_OPEN,
    OVR_PASS_STM0,
    close_graded_window,
    open_graded_window,
    set_override_pass,
)
from env.sep_lcc_golden import (
    DBG_DISABLE_FIELDS,
    LC_PROD,
    M64,
    dbg_disable_expected,
    feat_ctrl_expected,
    fuse_dft_disable_expected,
    is_invalid_lc,
    lc_state_name,
)
from env.sep_rma_token import token_digest
from sep_base_test import sep_base_test
from sep_reg_meta import register_fields, word_reset
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_rma_token_seq import _MATCH_STATUS_LSB as _STATUS_LSB
from seq_lib.sep_efuse_rma_token_seq import _MATCH_STATUS_MASK as _STATUS_MASK
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_MATCH,
    TOKEN_MISMATCH,
    TOKEN_SEC_DISABLE,
    SepRmaTokenMatchSeq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_TEST = "sep_sec_dis_override_test"
_MAX_SENSE_CYCLES = 20_000
# Cycles a stopped sense is watched. CHK-SENSE-CONTROL requires a healthy
# sense after rst_ni release to finish in fewer cycles than this.
_STUCK_CYCLES = 4_000
_RST_HOLD_CYCLES = 20
_RESET_SYNC_CYCLES = 32
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
_MATCH_TOKEN = 0
_MISMATCH_TOKEN = 1
# hw/sys/sep/doc/lifecycle_controller.adoc: the OTP controller initializes
# the shadow output to the INVALID encoding (4'b1111), and the life-cycle
# controller produces the INVALID feature-control profile before sensing
# completes. That encoding is outside the named lifecycle set, so the
# golden's other-encodings row is the closed feature-control value.
_WITHHELD_LC = 0xF
# SHA-256 of 32 zero bytes; must match ``SecDisTbDigest`` in ``tb/tb_top.sv``.
_TB_SEC_DIS_DIGEST = 0x66687AADF862BD776C8FC18B8E9F8E20089714856EE233B3902A591D0D5F2925
# AXI OKAY response code of ``jtag_axil_op``.
_AXI_OKAY = 0
_M32 = 0xFFFF_FFFF
# Cycles the debug bus is watched after the last JTAG write of the event window,
# and the floor of each quiet window (a quiet window is also at least twice the
# event window).
_DBG_SETTLE_CYCLES = 16
_DBG_QUIET_CYCLES = 256
# Clocks the stopped-sense SEC_DIS condition holds before the gate ports are read;
# the FCOV sampler records a gate condition after 8 stable clocks.
_GATE_SETTLE_CYCLES = 16
_FUSE_DFT_PORTS = ("sep_fuse_dft_disable", "smc_fuse_dft_disable")


class _BusChangeWatch:
    """Record every bit of a bus that changes from the start value or between clock edges.

    The value is compared as a 0/1/X/Z string, so an X that appears or clears
    is a change too. No bit position is interpreted.
    """

    def __init__(self, sig, clk) -> None:
        self._sig = sig
        self._clk = clk
        self._stop = False
        self.changed = 0
        self.edges = 0
        self.first = ""
        self.last = ""

    async def _run(self) -> None:
        prev = self.first
        while True:
            await RisingEdge(self._clk)
            await ReadOnly()
            cur = str(self._sig.value)
            if cur != prev:
                width = len(cur)
                for i, (a, b) in enumerate(zip(prev, cur)):
                    if a != b:
                        self.changed |= 1 << (width - 1 - i)
            prev = cur
            self.last = cur
            self.edges += 1
            if self._stop:
                return

    def start(self) -> "_BusChangeWatch":
        # The baseline is the value when the watch starts, so a change on the
        # first sampled edge counts.
        self.first = str(self._sig.value)
        cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        self._stop = True
        await ClockCycles(self._clk, 2)


class _CountedTokenSeq(SepRmaTokenMatchSeq):
    """Token presentation that counts the Idle (0x00) status reads after its go.

    token_processing.adoc, Token Submission: a go clears digest validity, so the
    comparison reads Idle until the new digest is available. A poll that reads
    Idle at least once shows that this go, and not a result kept from an earlier
    one, gave the code it returns.

    With ``jtag`` set, every access goes through that JTAG AXI-Lite op instead
    of the LSU sequencer, and each non-OKAY response is kept in ``bad_resp``.
    """

    def __init__(self, kind: int, token: int, jtag=None) -> None:
        super().__init__(kind, token)
        self.idle_reads = 0
        self._jtag = jtag
        self.bad_resp: list[tuple[str, int, int]] = []

    async def _write(self, addr: int, data: int, label: str) -> None:
        if self._jtag is None:
            await super()._write(addr, data, label)
            return
        resp, _ = await self._jtag(write=True, addr=addr, wdata=data)
        if resp != _AXI_OKAY:
            self.bad_resp.append((label, addr, resp))

    async def _read(self, addr: int, label: str) -> int:
        if self._jtag is None:
            raw = await super()._read(addr, label)
        else:
            resp, raw = await self._jtag(write=False, addr=addr)
            if resp != _AXI_OKAY:
                self.bad_resp.append((label, addr, resp))
        if label == "token_match" and (raw & _STATUS_MASK) >> _STATUS_LSB == 0:
            self.idle_reads += 1
        return raw


@pyuvm.test()
class sep_sec_dis_override_test(sep_base_test):
    """Match opens FEAT_CTRL but does not release the sense-gated reset."""

    async def _present(self, token: int) -> _CountedTokenSeq:
        seq = _CountedTokenSeq(TOKEN_SEC_DISABLE, token)
        await self.start_seq(seq)
        return seq

    async def _present_jtag(self, token: int, label: str) -> _CountedTokenSeq:
        """Present a SEC_DIS token over the OTP JTAG port while the core is held in reset.

        otp_fuse_controller.adoc, Shadow Register and JTAG Access Control: JTAG
        reaches the token block in every lifecycle state, and the held INVALID
        state before sense is not one of the restricted states. No TT text states
        the response code of these accesses, so ``OBS-SECDIS-JTAG-TOKEN-RESP`` logs
        every access that did not answer OKAY; the match code the caller grades
        shows that the token reached the block.
        """
        seq = _CountedTokenSeq(TOKEN_SEC_DISABLE, token, jtag=self.jtag_axil_op)
        await seq.body()
        self.logger.info(
            "OBS-SECDIS-JTAG-TOKEN-RESP %s non_okay=%d %s",
            label,
            len(seq.bad_resp),
            ", ".join(f"({lb}, 0x{a:08x}, {r})" for lb, a, r in seq.bad_resp) or "-",
        )
        return seq

    async def _check_feat(self, sec_dis: int, label: str) -> int:
        observed = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        if sec_dis:
            # hw/sys/sep/doc/lifecycle_controller.adoc: SEC_DIS=1 forces feat_ctrl
            # to all ones; the fail-closed word above is the contrast.
            assert feat == M64, f"{label} FAIL: override golden 0x{feat:016x} is not all ones"
        else:
            assert feat not in (0, M64), (
                f"{label} FAIL: fail-closed golden collapsed to 0x{feat:016x}"
            )
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert observed == sec_dis and ctl.feat_ctrl == feat, (
            f"{label} FAIL: sec_dis={observed} want {sec_dis} "
            f"FEAT_CTRL=0x{ctl.feat_ctrl:016x} want 0x{feat:016x}"
        )
        self.logger.info(
            "%s PASS: %s sec_dis=%d FEAT_CTRL=0x%016x",
            label,
            lc_state_name(LC_PROD),
            observed,
            ctl.feat_ctrl,
        )
        return ctl.feat_ctrl

    def _check_reset_stays_sense_gated(
        self, label: str = "CHK-SENSE-GATED-RESET", *, feat_label: str | None = None
    ) -> None:
        """A SEC_DIS match alone must NOT release the sense-gated reset.

        hw/sys/sep/doc/reset_controller.adoc: ``sep_reset_n`` holds every
        IP in reset until eFuse sensing completes during boot.
        ``ext_boot_seq_done_i`` is already 1, so sense is the only term
        still holding the reset -- this checker fails if a match releases
        it.

        With ``feat_label``, the same clock also grades the open feature
        control: security_disable.adoc, "A match does not release the SEP
        reset, which stays held until fuse sensing completes", and
        lifecycle_controller.adoc (Overrides and Final Gates): SEC_DIS = 1
        forces ``feat_ctrl`` to all ones. So ``lcc_feat_ctrl_probe_o`` reads
        all ones while both reset probes read 0, with the IC_RESET override
        pins at 0.
        """
        dut = cocotb.top
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            f"{label} WINDOW-CLOSED: sense finished during the token "
            "write, so the pre-sense window was never observed. This is not the reset "
            "contract failing -- rerun; if it repeats, present the token earlier"
        )
        assert self.rd(dut.ext_boot_seq_done_i), (
            f"{label} WINDOW-CLOSED: ext_boot_seq_done_i is 0, so sense "
            "is not the only held term and this window does not grade the contract"
        )
        sec_dis = int(dut.lcc_security_disable_probe_o.value) & 0x1
        assert sec_dis == 1, f"{label} FAIL: sec_dis={sec_dis} want 1 before the reset check"
        cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
        probe = self.rd_known(dut.lcc_feat_ctrl_probe_o) if feat_label else 0
        ovrd = self.rd_known(dut.jtag_sep_reset_n_ovrd_i)
        assert cpu_rst == 0 and fabric_rst == 0, (
            f"{label} FAIL: sec_dis=1 sense_done=0 ext_boot_seq_done=1 "
            f"but sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 0/0 "
            f"-- a SEC_DIS match bypassed the sense gate on the reset"
        )
        self.logger.info(
            "%s PASS: sec_dis=1 sense_done=0 ext_boot_seq_done=1 "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0 (match alone leaves the reset held)",
            label,
        )
        if feat_label is None:
            return
        assert ovrd == 0, (
            f"{feat_label} WINDOW-CLOSED: jtag_sep_reset_n_ovrd_i={ovrd}, so the held "
            "reset is not the sense gate alone"
        )
        want = feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=1)
        assert want == M64, f"{feat_label} FAIL: override golden 0x{want:016x} is not all ones"
        assert probe == want, (
            f"{feat_label} FAIL: sec_dis=1 sense_done=0 sep_cpu_reset_n_o=0 "
            f"dbg_sep_reset_n_o=0 lcc_feat_ctrl_probe_o=0x{probe:016x} want 0x{want:016x}"
        )
        self.logger.info(
            "%s PASS: held: sec_dis=1 sense_done=0 ovrd=0 sep_cpu_reset_n_o=0 "
            "dbg_sep_reset_n_o=0 lcc_feat_ctrl_probe_o=0x%016x exp=0x%016x",
            feat_label,
            probe,
            want,
        )

    def _require_sense_open(self, label: str, *, sec_dis: int | None = None) -> None:
        """Fail if fuse sense has already finished, so this window was not observed."""
        dut = cocotb.top
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            f"{label} WINDOW-CLOSED: sense finished before this check. "
            "This is not the contract failing -- rerun; if it repeats, move the check earlier"
        )
        assert self.rd(dut.ext_boot_seq_done_i), (
            f"{label} WINDOW-CLOSED: ext_boot_seq_done_i is 0, so sense is not the only held term"
        )
        if sec_dis is not None:
            got = int(dut.lcc_security_disable_probe_o.value) & 0x1
            assert got == sec_dis, f"{label} FAIL: sec_dis={got} want {sec_dis}"

    def _drive_sep_reset_override(self, ovrd: int, val: int) -> None:
        dut = cocotb.top
        dut.jtag_sep_reset_n_ovrd_i.value = ovrd
        dut.jtag_sep_reset_n_val_i.value = val

    async def _wait_resets(self, want: int, label: str, *, sec_dis: int) -> None:
        """Poll both reset probes until they equal ``want``, while sense stays open."""
        dut = cocotb.top
        for _ in range(_RESET_SYNC_CYCLES):
            await RisingEdge(dut.clk_i)
            self._require_sense_open(label, sec_dis=sec_dis)
            cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
            fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
            if cpu_rst == want and fabric_rst == want:
                return
        cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
        raise AssertionError(
            f"{label} FAIL: sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst} "
            f"want {want}/{want} within {_RESET_SYNC_CYCLES} cycles "
            f"(jtag_sep_reset_n_ovrd_i={int(dut.jtag_sep_reset_n_ovrd_i.value)} "
            f"jtag_sep_reset_n_val_i={int(dut.jtag_sep_reset_n_val_i.value)})"
        )

    async def _check_window_feat(self, sec_dis: int, label: str) -> None:
        """Read FEAT_CTRL while sensing is still open.

        The withheld map presents the invalid lifecycle encoding, so the closed
        golden is that row. ``sec_dis=1`` forces every feature bit on.
        """
        self._require_sense_open(label, sec_dis=sec_dis)
        observed = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=sec_dis)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        self._require_sense_open(label, sec_dis=sec_dis)
        assert observed == sec_dis and ctl.feat_ctrl == feat, (
            f"{label} FAIL: sec_dis={observed} want {sec_dis} "
            f"FEAT_CTRL=0x{ctl.feat_ctrl:016x} want 0x{feat:016x} while sense_done=0"
        )
        self.logger.info(
            "%s PASS: sense_done=0 sec_dis=%d FEAT_CTRL=0x%016x",
            label,
            observed,
            ctl.feat_ctrl,
        )

    async def _first_clock_port(self) -> tuple[str, str]:
        """``lc_state_o`` and sense done on the first clk_i edge with rst_ni high after a low."""
        dut = cocotb.top
        seen_low = False
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            rst = str(dut.rst_ni.value)
            if rst == "0":
                seen_low = True
            elif seen_low and rst == "1":
                return str(dut.lc_state_probe_o.value), str(dut.sep_fuse_sense_done_o.value)

    def _check_presense_port(self, port: str, done: str) -> None:
        """CHK-LC-STATE-PORT: ``lc_state_o`` holds the INVALID reset value before sense.

        lifecycle_controller.adoc: the OTP controller holds the shadow output at
        the INVALID encoding 4'b1111 until fuse sensing completes.
        otp_fuse_controller.adoc (Fuse Fields, ``LC_STATE``) and
        doc/integrator/src/smu-sep.adoc: ``lc_state_o`` is ``{~raw, raw}``.
        sep_efuse_map.rdl: ``lc_state`` resets to 0x0F. The sample is the first
        clk_i edge after the rst_ni release, with sense not done.
        """
        label = "CHK-LC-STATE-PORT"
        lc_addr = SepEfuseImage.field("LC_STATE").shadow_addr
        want = word_reset(lc_addr) & LC_FIELD_MASK
        assert want == lc_encode(_WITHHELD_LC), (
            f"test bug: LC_STATE RDL reset 0x{want:02x} is not INVALID "
            f"0x{lc_encode(_WITHHELD_LC):02x}"
        )
        assert done == "0", (
            f"{label} WINDOW-CLOSED: sep_fuse_sense_done_o={done} on the first clock "
            "after the rst_ni release"
        )
        got = int(port, 2) if set(port) <= {"0", "1"} else None
        assert got == want, (
            f"{label} FAIL: first clk_i edge after the rst_ni release, sense_done=0: "
            f"lc_state_o={port} want 0x{want:02x} (LC_STATE reset value, INVALID)"
        )
        self.logger.info(
            "%s PASS: first clk_i edge after the rst_ni release sense_done=0 "
            "got_port=0x%02x exp=0x%02x",
            label,
            got,
            want,
        )

    def _gate_ports(self) -> dict[str, int]:
        """Every ``dbg_disable_<path>_o`` and both fuse DFT disable ports, read by name."""
        dut = cocotb.top
        ports = {n: self.rd_known(getattr(dut, f"dbg_disable_{n}_o")) for n in DBG_DISABLE_FIELDS}
        for n in _FUSE_DFT_PORTS:
            ports[n] = self.rd_known(getattr(dut, f"{n}_o"))
        return ports

    def _read_gates(self, window: str, feat: int) -> None:
        """Read the gate ports for ``window`` and grade ``dbg_disable`` against ``feat``.

        doc/integrator/src/smu-sep.adoc: ``dbg_disable_o`` is active-high (1 =
        path disabled). lifecycle_controller.adoc (Debug and Test Port Path
        Gating) and hw/sys/dtp/doc/jtag.adoc: each path opens with its case
        (Case 1 SIP_DBG, Case 2 adds CHIPLET_DBG, Case 3 adds SEP_DBG), and the
        OTP JTAG2AXI paths are ungated. ``feat`` is the feature-control golden
        of the window. The fuse DFT ports are kept for CHK-FUSE-DFT-CLASS.
        """
        ports = self._gate_ports()
        want = dbg_disable_expected(feat)
        bad = [f"{n}={ports[n]}/{want[n]}" for n in DBG_DISABLE_FIELDS if ports[n] != want[n]]
        word = "".join(str(ports[n]) for n in DBG_DISABLE_FIELDS)
        assert not bad, (
            f"CHK-DBG-DISABLE FAIL: window={window} feat=0x{feat:016x} "
            f"field=got/want {','.join(bad)} (fields {','.join(DBG_DISABLE_FIELDS)}: {word})"
        )
        self.logger.info(
            "CHK-DBG-DISABLE PASS: window=%s sense_done=0 feat=0x%016x dbg_disable=%s (fields %s)",
            window,
            feat,
            word,
            ",".join(DBG_DISABLE_FIELDS),
        )
        self._gates[window] = (ports, feat)

    def _keep_gates(self, window: str, feat: int) -> None:
        """Read the fuse DFT ports of a control window (feature control known, no grade)."""
        self._gates[window] = (self._gate_ports(), feat)

    def _check_fuse_dft_class(self) -> None:
        """CHK-FUSE-DFT-CLASS: each fuse DFT port sits in the class its window states.

        lifecycle_controller.adoc (Debug and Test Port Path Gating) and
        port_table.adoc: ``sep_fuse_dft_disable_o`` follows Case 3 AND
        SEP_FUSE_DBG, ``smc_fuse_dft_disable_o`` Case 2 AND SMC_FUSE_DBG. No
        text states the port level, so each window is compared with the same
        leaf's closed control (the sensed fail-closed PROD profile) and open
        control (the sensed match). The INVALID profile before sense closes
        every case; the stopped-sense match opens every feature (SEC_DIS =
        1). OBS-DTP-PORT-LEVEL logs the levels.
        """
        label = "CHK-FUSE-DFT-CLASS"
        for window, opened in (("presense", 0), ("sec_dis", 1), ("closed", 0), ("open", 1)):
            feat = self._gates[window][1]
            klass = {n: int(fuse_dft_disable_expected(feat)[n] == 0) for n in _FUSE_DFT_PORTS}
            assert set(klass.values()) == {opened}, (
                f"test bug: window={window} feat=0x{feat:016x} does not put both fuse DFT "
                f"ports in the {'open' if opened else 'closed'} class: {klass}"
            )
        lv = {w: self._gates[w][0] for w in ("presense", "sec_dis", "closed", "open")}
        self.logger.info(
            "OBS-DTP-PORT-LEVEL: sep_open=%d sep_closed=%d smc_open=%d smc_closed=%d "
            "sep_presense=%d sep_sec_dis=%d smc_presense=%d smc_sec_dis=%d",
            *(lv[w][n] for n in _FUSE_DFT_PORTS for w in ("open", "closed")),
            *(lv[w][n] for n in _FUSE_DFT_PORTS for w in ("presense", "sec_dis")),
        )
        for n in _FUSE_DFT_PORTS:
            closed, opened = lv["closed"][n], lv["open"][n]
            pre, sdis = lv["presense"][n], lv["sec_dis"][n]
            assert closed != opened and pre == closed and sdis == opened, (
                f"{label} FAIL: {n}_o closed_ctl={closed} open_ctl={opened} "
                f"presense={pre} (want closed_ctl) sec_dis={sdis} (want open_ctl)"
            )
            self.logger.info(
                "%s PASS: %s_o presense=%d == closed_ctl=%d, sec_dis=%d == open_ctl=%d, "
                "controls differ",
                label,
                n,
                pre,
                closed,
                sdis,
                opened,
            )

    async def _check_override_alone(self) -> None:
        """The override releases reset and leaves feature control closed.

        hw/sys/sep/doc/security_disable.adoc: the override and the token match
        are independent. This step runs before any match.
        """
        self._require_sense_open("CHK-OVR-ALONE", sec_dis=0)
        self._drive_sep_reset_override(1, 1)
        await self._wait_resets(1, "CHK-OVR-ALONE", sec_dis=0)
        await self._check_window_feat(0, "CHK-OVR-ALONE")
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 1 and fabric_rst == 1, (
            f"CHK-OVR-ALONE FAIL: feature control stayed closed but the reset moved "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 1/1"
        )
        self.logger.info(
            "CHK-OVR-ALONE PASS: ovrd=1 sense_done=0 sec_dis=0 "
            "sep_cpu_reset_n_o=1 dbg_sep_reset_n_o=1"
        )
        self._drive_sep_reset_override(0, 0)
        await self._wait_resets(0, "CHK-OVR-ALONE", sec_dis=0)
        self.logger.info(
            "CHK-OVR-ALONE PASS: ovrd=0 sense_done=0 sec_dis=0 "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0"
        )

    async def _check_override_after_match(self, label: str) -> None:
        """The same override inputs release the reset after the match.

        A match has already left both probes at 0. This drives
        ``jtag_sep_reset_n_ovrd_i`` and ``jtag_sep_reset_n_val_i``. The DTP
        IC_RESET register write is not claimed.
        """
        self._require_sense_open(label, sec_dis=1)
        self._drive_sep_reset_override(1, 1)
        await self._wait_resets(1, label, sec_dis=1)
        self.logger.info(
            "%s PASS: ovrd=1 val=1 sense_done=0 sec_dis=1 sep_cpu_reset_n_o=1 dbg_sep_reset_n_o=1",
            label,
        )
        self._drive_sep_reset_override(0, 0)
        await self._wait_resets(0, label, sec_dis=1)
        self.logger.info(
            "%s PASS: ovrd=0 sense_done=0 sec_dis=1 sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0",
            label,
        )

    async def _released(self, label: str, step: Awaitable[int | None]) -> int | None:
        """Run a frontdoor ``step`` while the IC_RESET override releases the SEP reset.

        The LSU master is the SEP core, which does not run while
        ``sep_cpu_reset_n`` is held (reset_controller.adoc: ``sep_reset_n`` holds
        every IP in reset until sensing completes). With sense stopped by
        SEC_DIS, the override is what releases it (security_disable.adoc), so
        each frontdoor access of the stopped-sense window runs inside one
        override release; both probes read 0 again before the next step.
        """
        self._drive_sep_reset_override(1, 1)
        await self._wait_resets(1, label, sec_dis=1)
        result = await step
        self._drive_sep_reset_override(0, 0)
        await self._wait_resets(0, label, sec_dis=1)
        return result

    async def _read_shadow_map(self, label: str) -> int:
        """Require an OKAY read of the LC_STATE shadow word while sense is open.

        The scoreboard does not also grade this response: this checker owns it.
        Returns the read data.
        """
        self._require_sense_open(label, sec_dis=1)
        addr = SepEfuseImage.field("LC_STATE").shadow_addr
        seq = SepAxiAccessSeq(
            "sec_dis_map_rd",
            op=SepAxiOp.READ,
            addr=addr,
            size=2,
            allow_ungraded_read_resp=True,
        )
        await self.start_seq(seq)
        self._require_sense_open(label, sec_dis=1)
        assert seq.resp_ok and not seq.timed_out, (
            f"{label} FAIL: sec_dis=1 sense_done=0 "
            f"LC_STATE @0x{addr:08x} resp_ok={int(seq.resp_ok)} resp={seq.resp_code} "
            f"timed_out={int(seq.timed_out)} rdata=0x{seq.rdata & 0xFFFF_FFFF:08x}, "
            "want AXI OKAY"
        )
        self.logger.info(
            "%s PASS: LC_STATE @0x%08x AXI OKAY rdata=0x%08x while sec_dis=1 sense_done=0",
            label,
            addr,
            seq.rdata & 0xFFFF_FFFF,
        )
        return seq.rdata & 0xFFFF_FFFF

    def _check_lc_reset_after_pulse(self, pre: int, post: int) -> None:
        """CHK-RETAIN-LC-RESET: the rst_ni pulse under SEC_DIS returns LC_STATE to reset.

        security_disable.adoc, Reset Persistence: after a cold reset with the match
        kept, "Fuse sensing then does not start, every shadow register keeps its
        reset value". The reset value is the RDL ``lc_state`` reset 0x0F, the
        INVALID hold that otp_fuse_controller.adoc (Fuse Sensing and Boot
        Sequencing) gives before sensing completes. The control is the read
        before the pulse: the sense that the match stopped had loaded the LC_STATE
        word, so it differs from the reset value, and a DUT that ignores the pulse
        keeps it.
        """
        addr = SepEfuseImage.field("LC_STATE").shadow_addr
        want = word_reset(addr) & 0xFFFF_FFFF
        assert pre != want, (
            f"CHK-RETAIN-LC-RESET FAIL: control: LC_STATE read 0x{pre:08x} before the "
            f"rst_ni pulse, equal to its reset value 0x{want:08x}, so the readback after "
            "the pulse cannot show the reset"
        )
        assert post == want, (
            f"CHK-RETAIN-LC-RESET FAIL: LC_STATE @0x{addr:08x} read 0x{post:08x} after "
            f"rst_ni under SEC_DIS, want its reset value 0x{want:08x} "
            f"(before the pulse 0x{pre:08x})"
        )
        self.logger.info(
            "CHK-RETAIN-LC-RESET PASS: LC_STATE @0x%08x pre=0x%08x post=0x%08x want=0x%08x",
            addr,
            pre,
            post,
            want,
        )

    async def _check_sense_stuck(self, label: str) -> None:
        """Sense must stay open for ``_STUCK_CYCLES`` while SEC_DIS is active.

        Both reset probes must also stay 0: with sense stopped, only the
        IC_RESET override can release the SEP reset.
        """
        dut = cocotb.top
        for _ in range(_STUCK_CYCLES):
            await RisingEdge(dut.clk_i)
            assert not self.rd_known(dut.sep_fuse_sense_done_o), (
                f"{label} FAIL: sep_fuse_sense_done_o rose while sec_dis=1 -- "
                "the match did not stop the sense"
            )
            self._require_sense_open(label, sec_dis=1)
            cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
            fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
            assert cpu_rst == 0 and fabric_rst == 0, (
                f"{label} FAIL: sense stopped but sep_cpu_reset_n_o={cpu_rst} "
                f"dbg_sep_reset_n_o={fabric_rst}, want 0/0"
            )
        self.logger.info(
            "%s PASS: sec_dis=1 sense_done=0 for %d cycles, "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0",
            label,
            _STUCK_CYCLES,
        )

    async def _pulse_rst(self) -> None:
        """Pulse ``rst_ni`` with the clocks running. Does not wait for sense."""
        dut = cocotb.top
        self.logger.info("Pulsing rst_ni")
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, _RST_HOLD_CYCLES)
        dut.rst_ni.value = 1

    async def _healthy_sense_cycles(self) -> int:
        """Pulse ``rst_ni`` with SEC_DIS inactive and count cycles to sense-done."""
        dut = cocotb.top
        await self._pulse_rst()
        for cycle in range(_MAX_SENSE_CYCLES):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.sep_fuse_sense_done_o):
                break
        else:
            raise AssertionError(
                "CHK-SENSE-CONTROL FAIL: sep_fuse_sense_done_o never asserted "
                f"within {_MAX_SENSE_CYCLES} cycles after rst_ni release with sec_dis=0"
            )
        # Runs the post-sense shadow compare against the staged image.
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.cfg.reset_done.set()
        return cycle

    def _check_override_tm0(self, feat_reg: int) -> None:
        """Sample the strap, the probe and ``secure_tm_o`` at the CHK-OVERRIDE read.

        hw/sys/sep/doc/lifecycle_controller.adoc (Overrides and Final Gates):
        "when SEC_DIS = 1, feat_ctrl is forced to all-1s -- every feature
        enabled, regardless of the LC state, the DIS vectors, or the sigint
        result", and "SECURE_TM is *not* a term in feat_ctrl_o".
        hw/sys/sep/doc/security_disable.adoc: "SECURE_TM is not a term in the
        feature-control computation, so SEC_DIS neither qualifies nor overrides
        it." hw/sys/sep/doc/test_mode.adoc: "SECURE_TM does not qualify those
        bits." So with the strap at 0 every feature bit is still 1. The
        test_mode.adoc sampling table loads the strap at fuse-sense completion,
        so after the full sense with the strap at 0, ``secure_tm_o`` is 0.
        """
        label = "CHK-OVERRIDE-TM0"
        dut = cocotb.top
        strap = self.rd_known(dut.test_en_strap_i) & 0x1
        if strap != 0:
            raise AssertionError(
                f"CHK-HOOK FAIL: {label} test_en_strap_i={strap} want 0 -- the "
                "strap-0 cell is not in place, so the check does not grade it"
            )
        sec_dis = self.rd_known(dut.lcc_security_disable_probe_o) & 0x1
        probe = self.rd_known(dut.lcc_feat_ctrl_probe_o)
        stm = self.rd_known(dut.secure_tm_o) & 0x1
        want = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, secure_tm=0, sec_dis=1)
        assert want == M64, f"{label} FAIL: override golden 0x{want:016x} is not all ones"
        assert sec_dis == 1 and feat_reg == want and probe == want and stm == 0, (
            f"{label} FAIL: strap=0 sec_dis={sec_dis} want 1 "
            f"FEAT_CTRL=0x{feat_reg:016x} probe=0x{probe:016x} want 0x{want:016x}, "
            f"secure_tm_o={stm} want 0"
        )
        self.logger.info(
            "%s PASS: %s strap=0 sec_dis=1 secure_tm_o=0 FEAT_CTRL=0x%016x "
            "probe=0x%016x exp=0x%016x",
            label,
            lc_state_name(LC_PROD),
            feat_reg,
            probe,
            want,
        )

    async def _jtag_read_word(self, addr: int, what: str) -> int:
        """CTRL-SECDIS-JTAG-REACH: JTAG 32-bit read of a shadow word while sense is stopped.

        The held INVALID state is not PROD or RMA_SIP, so the JTAG port has the
        access of the fuse field table (otp_fuse_controller.adoc, Shadow Register
        and JTAG Access Control), and ``LC_STATE`` and ``REQUIRED_SIGNERS`` are
        SW readable with no read lock that applies here. The read is legal, so
        it must answer AXI OKAY; a refused or dead JTAG port fails here.
        """
        label = "CTRL-SECDIS-JTAG-REACH"
        self._require_sense_open(label, sec_dis=1)
        resp, data = await self.jtag_axil_op(write=False, addr=addr)
        self._require_sense_open(label, sec_dis=1)
        assert resp == _AXI_OKAY, (
            f"{label} FAIL: sec_dis=1 sense_done=0 JTAG rd {what} @0x{addr:08x} "
            f"resp={resp}, want AXI OKAY"
        )
        return data & _M32

    async def _watch_quiet(self, cycles: int) -> _BusChangeWatch:
        """Watch the debug bus for ``cycles`` with no eFuse access; the result is logged."""
        self._require_sense_open("CTRL-SECDIS-SHADOW-WR", sec_dis=1)
        dut = cocotb.top
        watch = _BusChangeWatch(dut.ext_debug_bus_o, dut.clk_i).start()
        await ClockCycles(dut.clk_i, cycles)
        await watch.stop()
        self._require_sense_open("CTRL-SECDIS-SHADOW-WR", sec_dis=1)
        return watch

    async def _check_jtag_writes_under_sec_dis(self) -> None:
        """JTAG shadow writes in the retained SEC_DIS window, and the debug bus around them.

        Golden (hw/sys/sep/doc, no RTL):

        * security_disable.adoc, Reset Persistence: after the reset with the
          match kept, "Fuse sensing then does not start, every shadow register
          keeps its reset value".
        * otp_fuse_controller.adoc, Shadow Register and JTAG Access Control:
          "In addition to the shadow-register access control defined by
          <<sep-fuse-fields-table>>, the JTAG port shall be further restricted:
          in the PROD and RMA_SIP states it may reach only the eFuse MMR token
          block." The held ``LC_STATE`` reset value, INVALID 4'b1111 in both
          the adoc and the RDL, is neither state, so JTAG has the table's
          access.
        * otp_fuse_controller.adoc, controller overview: the
          ``security_disable_i`` input "skips fuse sensing and opens the shadow
          registers to software". Fuse field table: REQUIRED_SIGNERS is "SW
          writable true"; sep_efuse_map.rdl: ``required_signers`` is
          ``sw = rw; onwrite = woset`` with reset 0, and the LOCKS bits reset to
          0. These lines state the shadow write after sense; no SEP line states
          it before sense under SEC_DIS.
        * LC_STATE: lifecycle_controller.adoc says the shadow output holds the
          INVALID encoding 4'b1111 before sensing, and "Invalid lifecycle
          encodings are terminal" (otp_fuse_controller.adoc, LC_STATE row);
          sep_efuse_map.rdl gives the matching ``lc_state`` reset 0x0f. Every
          text leaves that word unchanged: ``lc_state`` is ``sw = r``
          (sep_efuse_map.rdl:573-577); "LC_STATE bits can only be set" and an
          INVALID encoding is "permanent" (lifecycle_controller.adoc:87, :90),
          and raw 4'b1111 has no bit left to set; "Invalid lifecycle encodings
          are terminal" (otp_fuse_controller.adoc:220-224). CHK-SECDIS-LC-WR
          grades the JTAG readback after the write as the RDL reset word
          0x0000000f. No text states the JTAG write response, so
          OBS-SECDIS-LC-WR logs it without a verdict.

        The core is held in reset in this window, so every read here goes
        through the same JTAG port as the writes. CTRL-SECDIS-JTAG-REACH: each of
        the four reads (both words before and after the writes) answers AXI OKAY,
        because the table gives JTAG read access to both words in this state. A
        filter that refuses the port, or a dead port, fails it, so the unchanged
        LC_STATE word of CHK-SECDIS-LC-WR comes from a port that reaches the map.

        CTRL-SECDIS-SHADOW-WR: before the write the REQUIRED_SIGNERS shadow reads
        its RDL reset value and sense stays stopped. OBS-SECDIS-SHADOW-WR logs the
        readback after the JTAG write and the JTAG write response, without a
        verdict.

        CTRL-SECDIS-JTAG-WR-REACH: the REQUIRED_SIGNERS write, sent on the same
        JTAG port in the same window just before the LC_STATE write, sets its
        bit, and the LC_STATE write completes. So a JTAG shadow write reaches the
        shadow map in this state, and the unchanged LC_STATE word of
        CHK-SECDIS-LC-WR is a write that arrived and did not change the word. The
        two write responses stay logged only.

        No specification puts eFuse state on ``ext_debug_bus_o``
        (port_table.adoc names the port only), so OBS-SECDIS-DBG-BUS logs the
        bits that change while the two JTAG writes run and in a quiet window
        before them and one after them, without a verdict. The writable shadow
        keeps its new bit
        until the rst_ni pulse ahead of the next full sense, which reloads every
        shadow from the staged image before any later check reads it.
        """
        dut = cocotb.top
        rs_addr = SepEfuseImage.field("REQUIRED_SIGNERS").shadow_addr
        lc_addr = SepEfuseImage.field("LC_STATE").shadow_addr
        _width, rs_fields = register_fields(rs_addr)
        rs_field = next(f for f in rs_fields if f.name == "required_signers")
        assert rs_field.one_to_set and rs_field.reset is not None, (
            "test bug: REQUIRED_SIGNERS.required_signers is not woset with a reset in the RDL"
        )
        rs_reset = sum((f.reset or 0) << f.lsb for f in rs_fields)
        free = rs_field.mask & ~rs_reset
        assert free, "test bug: REQUIRED_SIGNERS has no 0 bit at its RDL reset"
        rs_bit = (free & -free).bit_length() - 1
        lc_invalid = lc_encode(_WITHHELD_LC)
        lc_new = lc_encode(LC_PROD)
        assert is_invalid_lc(_WITHHELD_LC) and lc_new != lc_invalid

        rs_pre = await self._jtag_read_word(rs_addr, "required_signers")
        assert rs_pre == rs_reset, (
            f"CTRL-SECDIS-SHADOW-WR FAIL: REQUIRED_SIGNERS @0x{rs_addr:08x} "
            f"pre=0x{rs_pre:08x} want RDL reset 0x{rs_reset:08x} -- the shadow did "
            "not keep its reset value after the reset with the match kept"
        )
        lc_pre = await self._jtag_read_word(lc_addr, "lc_state")

        # The JTAG reads above are the last eFuse accesses before the
        # first quiet window.
        await ClockCycles(dut.clk_i, _DBG_SETTLE_CYCLES)
        pre_quiet = await self._watch_quiet(_DBG_QUIET_CYCLES)

        self._require_sense_open("CTRL-SECDIS-SHADOW-WR", sec_dis=1)
        event = _BusChangeWatch(dut.ext_debug_bus_o, dut.clk_i).start()
        rs_resp, _ = await self.jtag_axil_op(write=True, addr=rs_addr, wdata=1 << rs_bit)
        lc_wdata = (lc_pre & ~LC_FIELD_MASK & _M32) | lc_new
        lc_resp, _ = await self.jtag_axil_op(write=True, addr=lc_addr, wdata=lc_wdata)
        await ClockCycles(dut.clk_i, _DBG_SETTLE_CYCLES)
        await event.stop()
        self._require_sense_open("CTRL-SECDIS-SHADOW-WR", sec_dis=1)

        post_quiet = await self._watch_quiet(max(_DBG_QUIET_CYCLES, 2 * event.edges))

        rs_post = await self._jtag_read_word(rs_addr, "required_signers")
        # No SEP specification line states whether a JTAG shadow write lands before
        # sense under SEC_DIS, so the readback is logged without a verdict.
        self.logger.info(
            "OBS-SECDIS-SHADOW-WR: sec_dis=1 sense_done=0 JTAG wr REQUIRED_SIGNERS "
            "@0x%08x bit=%d resp=%d pre=0x%08x post=0x%08x landed=%d",
            rs_addr,
            rs_bit,
            rs_resp,
            rs_pre,
            rs_post,
            int(rs_post == rs_pre | (1 << rs_bit)),
        )

        rs_landed = rs_post == rs_pre | (1 << rs_bit)
        if not rs_landed:
            raise AssertionError(
                f"CTRL-SECDIS-JTAG-WR-REACH FAIL: the JTAG write of REQUIRED_SIGNERS bit {rs_bit} "
                f"did not land (pre=0x{rs_pre:08x} post=0x{rs_post:08x} resp={rs_resp}), so no "
                "JTAG shadow write is shown to reach the shadow map and CHK-SECDIS-LC-WR "
                "cannot tell a refused LC_STATE write from a write that never arrived"
            )
        self.logger.info(
            "CTRL-SECDIS-JTAG-WR-REACH PASS: sec_dis=1 sense_done=0 JTAG wr REQUIRED_SIGNERS "
            "@0x%08x bit=%d landed=1 resp=%d; LC_STATE wr @0x%08x completed resp=%d",
            rs_addr,
            rs_bit,
            rs_resp,
            lc_addr,
            lc_resp,
        )

        # The LC_STATE shadow word before sense holds INVALID, [7:0] = 0x0f, which
        # is terminal, so the write leaves the word at its reset value. The write
        # response has no golden and is logged.
        lc_post = await self._jtag_read_word(lc_addr, "lc_state")
        self.logger.info(
            "CTRL-SECDIS-JTAG-REACH PASS: sec_dis=1 sense_done=0 JTAG rd REQUIRED_SIGNERS "
            "@0x%08x pre=0x%08x post=0x%08x, LC_STATE @0x%08x pre=0x%08x post=0x%08x, "
            "all resp=OKAY",
            rs_addr,
            rs_pre,
            rs_post,
            lc_addr,
            lc_pre,
            lc_post,
        )
        self.logger.info(
            "OBS-SECDIS-LC-WR: sec_dis=1 sense_done=0 JTAG wr LC_STATE @0x%08x "
            "wdata=0x%08x resp=%d",
            lc_addr,
            lc_wdata,
            lc_resp,
        )
        lc_want = word_reset(lc_addr) & _M32
        assert lc_want & LC_FIELD_MASK == lc_invalid, (
            f"test bug: LC_STATE RDL reset 0x{lc_want:08x} is not INVALID 0x{lc_invalid:02x}"
        )
        assert lc_post == lc_want, (
            f"CHK-SECDIS-LC-WR FAIL: sec_dis=1 sense_done=0 JTAG wr LC_STATE "
            f"@0x{lc_addr:08x} wdata=0x{lc_wdata:08x} pre=0x{lc_pre:08x} "
            f"post=0x{lc_post:08x} want=0x{lc_want:08x}: the terminal INVALID word changed"
        )
        self.logger.info(
            "CHK-SECDIS-LC-WR PASS: sec_dis=1 sense_done=0 LC_STATE @0x%08x "
            "wdata=0x%08x pre=0x%08x post=0x%08x want=0x%08x",
            lc_addr,
            lc_wdata,
            lc_pre,
            lc_post,
            lc_want,
        )

        self.logger.info(
            "OBS-SECDIS-DBG-BUS: event edges=%d changed_bits=%d mask=0x%x; "
            "quiet pre edges=%d mask=0x%x, post edges=%d mask=0x%x",
            event.edges,
            bin(event.changed).count("1"),
            event.changed,
            pre_quiet.edges,
            pre_quiet.changed,
            post_quiet.edges,
            post_quiet.changed,
        )

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)

        zero_digest = token_digest(_MATCH_TOKEN)
        assert zero_digest == _TB_SEC_DIS_DIGEST, (
            "test bug: SHA-256(0)="
            f"0x{zero_digest:064x} want TB digest 0x{_TB_SEC_DIS_DIGEST:064x} "
            "-- the match token and the tb_top bind constant disagree "
            "(DV consistency, not a DUT checker)"
        )

        closed = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        opened = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=1)
        assert closed != opened, "CHK-OVERRIDE FAIL: fail-closed and override goldens are identical"

        self._gates: dict[str, tuple[dict[str, int], int]] = {}
        open_graded_window(_TEST, self.logger)
        first = cocotb.start_soon(self._first_clock_port())
        await self.release_no_cpu_reset()
        self._check_presense_port(*(await first))
        await self._check_override_alone()
        self._require_sense_open("CHK-DBG-DISABLE", sec_dis=0)
        self._read_gates("presense", feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=0))
        # Until sense completes the core is held in reset, so the OTP JTAG port is
        # the master that presents the token, and every frontdoor access while
        # sense stays stopped runs inside an override release (_released).
        pre = await self._present_jtag(_MATCH_TOKEN, "CHK-SENSE-GATED-RESET")
        assert pre.match_code == TOKEN_MATCH, (
            f"CHK-SENSE-GATED-RESET FAIL: zero token code=0x{(pre.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x} before sense-done"
        )
        self._check_reset_stays_sense_gated(feat_label="CHK-FEAT-PRESENSE")
        await ClockCycles(cocotb.top.clk_i, _GATE_SETTLE_CYCLES)
        self._require_sense_open("CHK-DBG-DISABLE", sec_dis=1)
        self._read_gates("sec_dis", feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=1))
        close_graded_window(self.logger)
        # Control window of CHK-FEAT-PRESENSE: the override releases both resets and a
        # frontdoor read shows the same open feature control.
        await self._released("CHK-FEAT-PRESENSE", self._check_window_feat(1, "CHK-FEAT-PRESENSE"))
        await self._graded(self._check_override_after_match("CHK-OVR-AFTER"), OVR_PASS_ALONE_OPEN)
        lc_pre_reset = await self._released("CHK-MAP-OPEN", self._read_shadow_map("CHK-MAP-OPEN"))
        await self._check_sense_stuck("CHK-SENSE-STUCK")

        # Recovery flow: reset with the token kept.
        await self._pulse_rst()
        await ClockCycles(cocotb.top.clk_i, 2)
        self._check_reset_stays_sense_gated("CHK-RETAIN-RESET")
        await self._released("CHK-RETAIN-FEAT", self._check_window_feat(1, "CHK-RETAIN-FEAT"))
        lc_post_reset = await self._released(
            "CHK-RETAIN-MAP-OPEN", self._read_shadow_map("CHK-RETAIN-MAP-OPEN")
        )
        self._check_lc_reset_after_pulse(lc_pre_reset, lc_post_reset)
        await self._check_jtag_writes_under_sec_dis()
        await self._check_override_after_match("CHK-RETAIN-OVR")
        await self._check_sense_stuck("CHK-RETAIN-STUCK")

        drop = await self._present_jtag(_MISMATCH_TOKEN, "CHK-DROP")
        observed = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        assert drop.match_code == TOKEN_MISMATCH and observed == 0, (
            f"CHK-DROP FAIL: token=1 code=0x{(drop.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}, sec_dis={observed} want 0"
        )
        self.logger.info(
            "CHK-DROP PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x sec_dis=0 (sense_done=%d)",
            drop.match_code,
            self.rd_known(cocotb.top.sep_fuse_sense_done_o),
        )

        healthy = await self._healthy_sense_cycles()
        assert healthy < _STUCK_CYCLES, (
            f"CHK-SENSE-CONTROL FAIL: a healthy sense took {healthy} cycles, not fewer "
            f"than the {_STUCK_CYCLES}-cycle stuck windows, so those windows prove nothing"
        )
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 1 and fabric_rst == 1, (
            f"CHK-SENSE-CONTROL FAIL: after sense-done "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 1/1 "
            "-- the pre-sense low check has no live high control without this"
        )
        # _healthy_sense_cycles raises unless the backdoor compare of every staged
        # word against the sensed shadow finds no mismatch.
        self.logger.info(
            "CHK-SENSE-CONTROL PASS: healthy sense done %d cycles after rst_ni release "
            "(< %d-cycle stuck windows); shadow_vs_staged words=%d mismatches=0; "
            "sep_cpu_reset_n_o=%d dbg_sep_reset_n_o=%d",
            healthy,
            _STUCK_CYCLES,
            len(self._efuse_compare_image.words),
            cpu_rst,
            fabric_rst,
        )

        # CHK-DROP left a Mismatch result, which a retained digest gives again after
        # the reset, so the code alone does not show that this go ran.
        mm = await self._present(_MISMATCH_TOKEN)
        assert mm.match_code == TOKEN_MISMATCH and mm.idle_reads >= 1, (
            f"CHK-MISMATCH FAIL: token=1 code=0x{(mm.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}, idle_reads={mm.idle_reads} want >= 1 "
            "(no Idle read after the go: the code can be the result of the earlier go)"
        )
        self.logger.info(
            "CHK-MISMATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1, idle_reads=%d",
            mm.match_code,
            mm.idle_reads,
        )
        self._keep_gates("closed", await self._check_feat(0, "CHK-NO-OVERRIDE"))

        await self._graded(self._match_override_tm0(), OVR_PASS_STM0)
        self._check_fuse_dft_class()
        await self._deactivate_restore()

    async def _graded(self, step: Awaitable[None], bit: int) -> None:
        """Run ``step`` inside the owner window; raise pass label ``bit`` only after it passes.

        A FAIL raises before the label, and the finally clause closes the
        window, which drops the pending event.
        """
        set_override_pass(0, self.logger)
        open_graded_window(_TEST, self.logger)
        try:
            await step
            set_override_pass(bit, self.logger)
            await ClockCycles(cocotb.top.clk_i, 2)
            set_override_pass(0, self.logger)
        finally:
            close_graded_window(self.logger)

    async def _match_override_tm0(self) -> None:
        """CHK-MATCH, CHK-OVERRIDE and CHK-OVERRIDE-TM0 on the sensed PROD image."""
        hit = await self._present(_MATCH_TOKEN)
        assert hit.match_code == TOKEN_MATCH, (
            f"CHK-MATCH FAIL: zero token code=0x{(hit.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x}"
        )
        self.logger.info(
            "CHK-MATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after all-zero token", hit.match_code
        )
        feat_open = await self._check_feat(1, "CHK-OVERRIDE")
        self._keep_gates("open", feat_open)
        self._check_override_tm0(feat_open)

    async def _deactivate_restore(self) -> None:
        """CHK-DEACTIVATE and CHK-RESTORE: a mismatch closes FEAT_CTRL again."""
        deact = await self._present(_MISMATCH_TOKEN)
        assert deact.match_code == TOKEN_MISMATCH, (
            f"CHK-DEACTIVATE FAIL: token=1 code=0x{(deact.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-DEACTIVATE PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1", deact.match_code
        )
        await self._check_feat(0, "CHK-RESTORE")

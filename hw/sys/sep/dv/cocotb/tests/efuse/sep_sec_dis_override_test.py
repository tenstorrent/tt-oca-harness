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
``sep_sec_dis_reset_reach_test``. JTAG ``TOKEN_EOP`` activate is not claimed.

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
restricts JTAG only in PROD and RMA_SIP, and the held INVALID encoding is
neither, so the port reaches the map. A writable shadow takes the write; the
INVALID ``LC_STATE`` is terminal and keeps its value. The external debug bus
must change around those writes and hold still in the quiet windows on each
side of them; no lane position is assumed.

After a later full sense, a fresh match on the PROD image opens
``FEAT_CTRL`` with the ``TEST_EN`` strap at 0: the register and the
feature-control probe are all ones and ``secure_tm_o`` is 0.

Checks (``CHK-<ID> PASS`` lines; every failure raises):

  CHK-OVR-ALONE          the IC_RESET override alone releases the reset, FEAT_CTRL closed
  CHK-SENSE-GATED-RESET  a match does not release the sense-gated reset
  CHK-FEAT-PRESENSE      the match opens FEAT_CTRL before sense-done
  CHK-OVR-AFTER          the override releases the reset after the match
  CHK-MAP-OPEN           LC_STATE shadow read answers OKAY under SEC_DIS
  CHK-SENSE-STUCK        sense stays stopped and the reset held under SEC_DIS
  CHK-RETAIN-*           the same five contracts after rst_ni with the token kept
  CHK-SECDIS-SHADOW-WR   JTAG write of a 0 bit of REQUIRED_SIGNERS lands (frontdoor)
  CHK-SECDIS-LC-WR       JTAG write of LC_STATE leaves the INVALID word unchanged
  CHK-SECDIS-DBG-BUS     ext_debug_bus_o changes around the JTAG writes and not
                         in the quiet windows (control: CHK-HOOK)
  CHK-DROP               a mismatch drops SEC_DIS
  CHK-SENSE-CONTROL      a healthy sense finishes inside each stuck window
  CHK-MISMATCH, CHK-NO-OVERRIDE  mismatch code and the fail-closed PROD FEAT_CTRL
  CHK-MATCH, CHK-OVERRIDE        match code and the all-ones FEAT_CTRL
  CHK-OVERRIDE-TM0       at CHK-OVERRIDE with the strap at 0 (control: CHK-HOOK):
                         FEAT_CTRL == lcc_feat_ctrl_probe_o == all ones, secure_tm_o == 0
  CHK-DEACTIVATE, CHK-RESTORE    mismatch code and the PROD FEAT_CTRL again
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import LC_FIELD_MASK, SepEfuseImage, lc_encode
from env.sep_lcc_golden import (
    LC_PROD,
    M64,
    feat_ctrl_expected,
    is_invalid_lc,
    lc_state_name,
)
from env.sep_rma_token import token_digest
from sep_base_test import sep_base_test
from sep_reg_meta import register_fields
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_MATCH,
    TOKEN_MISMATCH,
    TOKEN_SEC_DISABLE,
    SepRmaTokenMatchSeq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

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


class _BusChangeWatch:
    """Record every bit of a bus that differs between two consecutive clock edges.

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
        prev = ""
        while True:
            await RisingEdge(self._clk)
            await ReadOnly()
            cur = str(self._sig.value)
            if not prev:
                self.first = cur
            elif cur != prev:
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
        cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        self._stop = True
        await ClockCycles(self._clk, 2)


@pyuvm.test()
class sep_sec_dis_override_test(sep_base_test):
    """Match opens FEAT_CTRL but does not release the sense-gated reset."""

    async def _present(self, token: int) -> SepRmaTokenMatchSeq:
        seq = SepRmaTokenMatchSeq(TOKEN_SEC_DISABLE, token)
        await self.start_seq(seq)
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

    def _check_reset_stays_sense_gated(self, label: str = "CHK-SENSE-GATED-RESET") -> None:
        """A SEC_DIS match alone must NOT release the sense-gated reset.

        hw/sys/sep/doc/reset_controller.adoc: ``sep_reset_n`` holds every
        IP in reset until eFuse sensing completes during boot.
        ``ext_boot_seq_done_i`` is already 1, so sense is the only term
        still holding the reset -- this checker fails if a match releases
        it.
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

    async def _read_shadow_map(self, label: str) -> None:
        """Require an OKAY read of the LC_STATE shadow word while sense is open.

        The scoreboard does not also grade this response: this checker owns it.
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

    async def _fd_read_word(self, label: str, addr: int, what: str) -> int:
        """Frontdoor 32-bit read of a shadow word while sense is stopped; OKAY required."""
        self._require_sense_open(label, sec_dis=1)
        seq = SepAxiAccessSeq(
            f"sec_dis_{what}_rd",
            op=SepAxiOp.READ,
            addr=addr,
            size=2,
            allow_ungraded_read_resp=True,
        )
        await self.start_seq(seq)
        self._require_sense_open(label, sec_dis=1)
        assert seq.resp_ok and not seq.timed_out, (
            f"{label} FAIL: sec_dis=1 sense_done=0 {what} @0x{addr:08x} "
            f"resp_ok={int(seq.resp_ok)} resp={seq.resp_code} "
            f"timed_out={int(seq.timed_out)}, want AXI OKAY"
        )
        return seq.rdata & _M32

    async def _watch_quiet(self, cycles: int, which: str) -> _BusChangeWatch:
        """Watch the debug bus for ``cycles`` with no access; any change fails the control."""
        self._require_sense_open("CHK-SECDIS-DBG-BUS", sec_dis=1)
        dut = cocotb.top
        watch = _BusChangeWatch(dut.ext_debug_bus_o, dut.clk_i).start()
        await ClockCycles(dut.clk_i, cycles)
        await watch.stop()
        self._require_sense_open("CHK-SECDIS-DBG-BUS", sec_dis=1)
        if watch.changed:
            raise AssertionError(
                f"CHK-HOOK FAIL: CHK-SECDIS-DBG-BUS {which} quiet window: "
                f"ext_debug_bus_o changed with no eFuse access over {watch.edges} edges "
                f"(changed bits mask=0x{watch.changed:x}). A lane outside the eFuse "
                "state toggles, so a whole-bus change cannot grade the eFuse lane"
            )
        return watch

    async def _check_jtag_writes_under_sec_dis(self) -> None:
        """JTAG shadow writes in the retained SEC_DIS window, and the debug bus around them.

        Golden (hw/sys/sep/doc, no RTL):

        * security_disable.adoc, Reset Persistence: after the reset with the
          match kept, "Fuse sensing then does not start, every shadow register
          keeps its reset value". lifecycle_controller.adoc: "Before fuse
          sensing completes, the shadow output holds the INVALID encoding
          4'b1111", stored as ``{~raw, raw}`` (otp_fuse_controller.adoc fuse
          field table, LC_STATE row).
        * otp_fuse_controller.adoc, Shadow Register and JTAG Access Control:
          "In addition to the shadow-register access control defined by
          <<sep-fuse-fields-table>>, the JTAG port shall be further restricted:
          in the PROD and RMA_SIP states it may reach only the eFuse MMR token
          block." INVALID is neither state, so JTAG has the table's access.
        * otp_fuse_controller.adoc, controller overview: the
          ``security_disable_i`` input "skips fuse sensing and opens the shadow
          registers to software". Fuse field table: REQUIRED_SIGNERS is "SW
          writable true"; sep_efuse_map.rdl: ``required_signers`` is
          ``sw = rw; onwrite = woset`` with reset 0, and the LOCKS bits reset to
          0. So a write of a 0 bit sets that bit and leaves the rest.
        * otp_fuse_controller.adoc, LC_STATE row: "Invalid lifecycle encodings
          are terminal." A write of another encoding leaves the word unchanged.

        Both writes are graded by a frontdoor readback ("A read of the eFuse
        shadow map over the SEP bus completes with OKAY", security_disable.adoc).
        The JTAG write response is logged, not graded: the specification does
        not state it for a write the terminal rule refuses.

        The debug bus has no lane layout in the specification, so it is graded
        layout-free: it must change while the two JTAG writes run, and hold
        still in a quiet window before them and in one after them, each at
        least twice the event window. The writable shadow keeps its new bit
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

        rs_pre = await self._fd_read_word("CHK-SECDIS-SHADOW-WR", rs_addr, "required_signers")
        assert rs_pre == rs_reset, (
            f"CHK-SECDIS-SHADOW-WR FAIL: REQUIRED_SIGNERS @0x{rs_addr:08x} "
            f"pre=0x{rs_pre:08x} want RDL reset 0x{rs_reset:08x} -- the shadow did "
            "not keep its reset value after the reset with the match kept"
        )
        lc_pre = await self._fd_read_word("CHK-SECDIS-LC-WR", lc_addr, "lc_state")
        assert lc_pre & LC_FIELD_MASK == lc_invalid, (
            f"CHK-SECDIS-LC-WR FAIL: LC_STATE @0x{lc_addr:08x} pre=0x{lc_pre:08x} "
            f"want [7:0]=0x{lc_invalid:02x} (INVALID 4'b1111) while sense is stopped"
        )

        # The frontdoor reads above are the last eFuse accesses before the
        # first quiet window.
        await ClockCycles(dut.clk_i, _DBG_SETTLE_CYCLES)
        pre_quiet = await self._watch_quiet(_DBG_QUIET_CYCLES, "pre")

        self._require_sense_open("CHK-SECDIS-SHADOW-WR", sec_dis=1)
        event = _BusChangeWatch(dut.ext_debug_bus_o, dut.clk_i).start()
        rs_resp, _ = await self.jtag_axil_op(write=True, addr=rs_addr, wdata=1 << rs_bit)
        lc_wdata = (lc_pre & ~LC_FIELD_MASK & _M32) | lc_new
        lc_resp, _ = await self.jtag_axil_op(write=True, addr=lc_addr, wdata=lc_wdata)
        await ClockCycles(dut.clk_i, _DBG_SETTLE_CYCLES)
        await event.stop()
        self._require_sense_open("CHK-SECDIS-LC-WR", sec_dis=1)

        post_quiet = await self._watch_quiet(max(_DBG_QUIET_CYCLES, 2 * event.edges), "post")
        assert pre_quiet.edges >= 2 * event.edges, (
            f"CHK-HOOK FAIL: CHK-SECDIS-DBG-BUS pre quiet window {pre_quiet.edges} edges "
            f"is shorter than twice the {event.edges}-edge event window"
        )

        rs_post = await self._fd_read_word("CHK-SECDIS-SHADOW-WR", rs_addr, "required_signers")
        rs_want = rs_pre | (1 << rs_bit)
        assert rs_post == rs_want, (
            f"CHK-SECDIS-SHADOW-WR FAIL: sec_dis=1 sense_done=0 JTAG write "
            f"0x{1 << rs_bit:08x} to REQUIRED_SIGNERS @0x{rs_addr:08x} (resp={rs_resp}): "
            f"pre=0x{rs_pre:08x} post=0x{rs_post:08x} want 0x{rs_want:08x}"
        )
        self.logger.info(
            "CHK-SECDIS-SHADOW-WR PASS: sec_dis=1 sense_done=0 JTAG wr REQUIRED_SIGNERS "
            "@0x%08x bit=%d resp=%d resp_graded=0 pre=0x%08x post=0x%08x exp=0x%08x",
            rs_addr,
            rs_bit,
            rs_resp,
            rs_pre,
            rs_post,
            rs_want,
        )

        lc_post = await self._fd_read_word("CHK-SECDIS-LC-WR", lc_addr, "lc_state")
        assert lc_post == lc_pre, (
            f"CHK-SECDIS-LC-WR FAIL: sec_dis=1 sense_done=0 JTAG write 0x{lc_wdata:08x} "
            f"to LC_STATE @0x{lc_addr:08x} (resp={lc_resp}) changed the INVALID word: "
            f"pre=0x{lc_pre:08x} post=0x{lc_post:08x} want unchanged"
        )
        self.logger.info(
            "CHK-SECDIS-LC-WR PASS: sec_dis=1 sense_done=0 JTAG wr LC_STATE @0x%08x "
            "wdata=0x%08x resp=%d resp_graded=0 pre=0x%08x post=0x%08x (INVALID terminal)",
            lc_addr,
            lc_wdata,
            lc_resp,
            lc_pre,
            lc_post,
        )

        assert event.changed, (
            f"CHK-SECDIS-DBG-BUS FAIL: ext_debug_bus_o did not change over the "
            f"{event.edges}-edge window of the JTAG REQUIRED_SIGNERS and LC_STATE writes "
            f"(value={event.last or '-'}) -- the eFuse debug state does not reach the bus"
        )
        self.logger.info(
            "CHK-SECDIS-DBG-BUS PASS: event edges=%d changed_bits=%d mask=0x%x; "
            "quiet pre edges=%d changed=0, post edges=%d changed=0",
            event.edges,
            bin(event.changed).count("1"),
            event.changed,
            pre_quiet.edges,
            post_quiet.edges,
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

        await self.release_no_cpu_reset()
        await self._check_override_alone()
        pre = await self._present(_MATCH_TOKEN)
        assert pre.match_code == TOKEN_MATCH, (
            f"CHK-SENSE-GATED-RESET FAIL: zero token code=0x{(pre.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x} before sense-done"
        )
        self._check_reset_stays_sense_gated()
        await self._check_window_feat(1, "CHK-FEAT-PRESENSE")
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 0 and fabric_rst == 0, (
            f"CHK-FEAT-PRESENSE FAIL: feature control opened but the reset moved "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 0/0"
        )
        await self._check_override_after_match("CHK-OVR-AFTER")
        await self._read_shadow_map("CHK-MAP-OPEN")
        await self._check_sense_stuck("CHK-SENSE-STUCK")

        # Recovery flow: reset with the token kept.
        await self._pulse_rst()
        await ClockCycles(cocotb.top.clk_i, 2)
        await self._check_window_feat(1, "CHK-RETAIN-FEAT")
        self._check_reset_stays_sense_gated("CHK-RETAIN-RESET")
        await self._read_shadow_map("CHK-RETAIN-MAP-OPEN")
        await self._check_jtag_writes_under_sec_dis()
        await self._check_override_after_match("CHK-RETAIN-OVR")
        await self._check_sense_stuck("CHK-RETAIN-STUCK")

        drop = await self._present(_MISMATCH_TOKEN)
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
        self.logger.info(
            "CHK-SENSE-CONTROL PASS: healthy sense done %d cycles after rst_ni release "
            "(< %d-cycle stuck windows)",
            healthy,
            _STUCK_CYCLES,
        )
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 1 and fabric_rst == 1, (
            f"CHK-SENSE-GATED-RESET FAIL: after sense-done "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 1/1 "
            "-- the pre-sense low check has no live high control without this"
        )

        mm = await self._present(_MISMATCH_TOKEN)
        assert mm.match_code == TOKEN_MISMATCH, (
            f"CHK-MISMATCH FAIL: token=1 code=0x{(mm.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-MISMATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1", mm.match_code
        )
        await self._check_feat(0, "CHK-NO-OVERRIDE")

        hit = await self._present(_MATCH_TOKEN)
        assert hit.match_code == TOKEN_MATCH, (
            f"CHK-MATCH FAIL: zero token code=0x{(hit.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x}"
        )
        self.logger.info(
            "CHK-MATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after all-zero token", hit.match_code
        )
        feat_open = await self._check_feat(1, "CHK-OVERRIDE")
        self._check_override_tm0(feat_open)

        deact = await self._present(_MISMATCH_TOKEN)
        assert deact.match_code == TOKEN_MISMATCH, (
            f"CHK-DEACTIVATE FAIL: token=1 code=0x{(deact.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-DEACTIVATE PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1", deact.match_code
        )
        await self._check_feat(0, "CHK-RESTORE")

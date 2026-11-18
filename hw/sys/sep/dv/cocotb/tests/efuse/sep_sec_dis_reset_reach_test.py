# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP stays reachable through the IC_RESET sep_reset_n override before sense.

RAND-NONE. Real fuse sense (no ``+skip_fuse_sense``). No token match:
hw/sys/sep/doc/security_disable.adoc says the override alone releases the
reset and leaves life-cycle control closed.

The stimulus is ``jtag_ic_reset_reg`` driving the SEP reset-control port.
The port programmed is ``sep_reset_n`` from the integrator SEP-slice table.
The TAP instruction that selects this TDR is outside this DUT. The per-port
override pins stay 0, so a probe that rises is the register's output.

``SW_RESET_N`` sits in the ``sep_reset_n`` domain. After the TDR enables
the override with the reset value released, a read returns the register's
reset default while sensing is still open. Restoring the TDR enable holds
the reset again, graded on the reset probes. Feature control stays the
withheld profile. After sensing completes with the override off, the reset
releases, the same read returns the reset default again, and FEAT_CTRL reads
the PROD golden of the pinned image, so the withheld read is not a register
stuck at zero.

In the same released window, with sensing still open, a 64-bit read of
``SEP_FUSE_SENSE_STATUS`` is logged (OBS-SENSE-STATUS-PRE: response, data, and
sense done before and after the read). No text states the response or value of
that read while sensing runs.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Immediate
from cocotb.triggers import ReadWrite, RisingEdge, Timer
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SEP_FUSE_SENSE_STATUS
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq
from seq_lib.sep_sw_reset_seq import (
    SEP_RESET_CTRL_SW_RESET_N,
    SW_RESET_N_RESET_DEFAULT,
)

_MAX_SENSE_CYCLES = 20_000
_RESET_SYNC_CYCLES = 32
# hw/sys/sep/doc/lifecycle_controller.adoc: INVALID feature-control profile
# before sensing completes.
_WITHHELD_LC = 0xF
# Fixed disable vectors, so the sensed PROD FEAT_CTRL is a known non-zero word.
# SYS_DIS bit 0 stays clear.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
# SEP slice of the IC_RESET chain, TDI to TDO (doc/integrator/src/smu.adoc).
# The first name is nearest TDI; reset_hold is the TDO-end bit and is not a port.
_SEP_SLICE_TDI_TO_TDO = (
    "abr_jtag_rst_n",
    "trng_jtag_rst_n",
    "sep_reset_n",
    "kmac_jtag_rst_n",
    "hmac_jtag_rst_n",
    "aes_jtag_rst_n",
    "otbn_jtag_rst_n",
    "km_jtag_rst_n",
)
_IC_RESET_PORTS = len(_SEP_SLICE_TDI_TO_TDO)
# Port 0 is nearest TDO, so the last table row is port 0.
_SEP_RESET_N_PORT = _IC_RESET_PORTS - 1 - _SEP_SLICE_TDI_TO_TDO.index("sep_reset_n")
# PTAP IC_RESET field table: bit 0 is reset_hold; port n stores reset_enable
# at 2*n+1 and reset_control at 2*n+2. hw/ip/jtag/jtag_ptap/doc/architecture.adoc.
_IC_RESET_BITS = (2 * _IC_RESET_PORTS) + 1
_TCK_HALF_NS = 5


@pyuvm.test()
class sep_sec_dis_reset_reach_test(sep_base_test):
    """An IC_RESET TDR write reaches SW_RESET_N before fuse sensing finishes."""

    def _require_sense_open(self, label: str) -> None:
        dut = cocotb.top
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            f"{label} WINDOW-CLOSED: sense finished before this check. "
            "This is not the contract failing -- rerun; if it repeats, move the check earlier"
        )
        assert self.rd(dut.ext_boot_seq_done_i), (
            f"{label} WINDOW-CLOSED: ext_boot_seq_done_i is 0, so sense is not the only held term"
        )

    def _probes(self) -> tuple[int, int]:
        dut = cocotb.top
        return (
            self.rd_known(dut.sep_cpu_reset_n_o),
            self.rd_known(dut.dbg_sep_reset_n_o),
        )

    async def _wait_probes(self, want: int, label: str) -> None:
        dut = cocotb.top
        for _ in range(_RESET_SYNC_CYCLES):
            await RisingEdge(dut.clk_i)
            self._require_sense_open(label)
            if self._probes() == (want, want):
                return
        cpu_rst, fabric_rst = self._probes()
        raise AssertionError(
            f"{label} FAIL: sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst} "
            f"want {want}/{want} within {_RESET_SYNC_CYCLES} cycles"
        )

    async def _hold_probes(self, want: int, label: str) -> None:
        """Both probes read ``want`` on every edge of the release bound.

        CHK-TDR-RELEASE requires a release within the same bound, so a step
        that released the reset shows inside this window.
        """
        dut = cocotb.top
        for cycle in range(1, _RESET_SYNC_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            self._require_sense_open(label)
            cpu_rst, fabric_rst = self._probes()
            assert (cpu_rst, fabric_rst) == (want, want), (
                f"{label} FAIL: sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst} "
                f"at cycle {cycle} of {_RESET_SYNC_CYCLES}, want {want}/{want} throughout"
            )

    def _pins_stay_clear(self, label: str) -> None:
        dut = cocotb.top
        ovrd = self.rd_known(dut.jtag_sep_reset_n_ovrd_i)
        val = self.rd_known(dut.jtag_sep_reset_n_val_i)
        en = self.rd_known(dut.jtag_ic_reset_tdr_en_i)
        assert ovrd == 0 and val == 0 and en == 1, (
            f"{label} FAIL: path is not the TDR "
            f"(jtag_sep_reset_n_ovrd_i={ovrd} jtag_sep_reset_n_val_i={val} tdr_en={en})"
        )

    async def _tck(self) -> None:
        dut = cocotb.top
        dut.jtag_ic_reset_tck_i.value = 0
        await Timer(_TCK_HALF_NS, unit="ns")
        dut.jtag_ic_reset_tck_i.value = 1
        await Timer(_TCK_HALF_NS, unit="ns")
        dut.jtag_ic_reset_tck_i.value = 0

    async def _reset_tdr(self) -> None:
        """Load the TDR reset value: override off, reset value released."""
        dut = cocotb.top
        dut.jtag_ic_reset_tdr_en_i.value = 0
        dut.jtag_ic_reset_select_i.value = 0
        dut.jtag_ic_reset_shift_en_i.value = 0
        dut.jtag_ic_reset_capture_en_i.value = 0
        dut.jtag_ic_reset_update_en_i.value = 0
        dut.jtag_ic_reset_rst_n_i.value = 0
        dut.jtag_ic_reset_trst_n_i.value = 0
        await Timer(20, unit="ns")
        dut.jtag_ic_reset_rst_n_i.value = 1
        dut.jtag_ic_reset_trst_n_i.value = 1
        await Timer(5, unit="ns")
        # A queued deposit on this input is not the value a later read returns.
        dut.jtag_ic_reset_tdr_en_i.value = Immediate(1)
        await ReadWrite()

    @staticmethod
    def _pack(*, enable_port: int | None, control_port: int | None = None) -> int:
        """All-ones TDR word, optionally with one port's reset_enable or reset_control cleared.

        Bit 0 is reset_hold. Port ``n`` stores reset_enable at ``2*n+1`` and
        reset_control at ``2*n+2``.
        """
        value = (1 << _IC_RESET_BITS) - 1
        if enable_port is not None:
            value &= ~(1 << (2 * enable_port + 1))
        if control_port is not None:
            value &= ~(1 << (2 * control_port + 2))
        return value

    async def _shift_only(self, value: int) -> None:
        """Shift ``value`` in LSB first with no Capture-DR and no Update-DR."""
        dut = cocotb.top
        dut.jtag_ic_reset_select_i.value = 1
        dut.jtag_ic_reset_capture_en_i.value = 0
        dut.jtag_ic_reset_update_en_i.value = 0
        dut.jtag_ic_reset_shift_en_i.value = 1
        for bit in range(_IC_RESET_BITS):
            dut.jtag_ic_reset_tdi_i.value = (value >> bit) & 1
            await self._tck()
        dut.jtag_ic_reset_shift_en_i.value = 0
        dut.jtag_ic_reset_tdi_i.value = 0
        dut.jtag_ic_reset_select_i.value = 0

    async def _capture_shift_update(self, value: int) -> int:
        """Capture-DR, shift LSB first, Update-DR. Returns the captured word."""
        dut = cocotb.top
        dut.jtag_ic_reset_select_i.value = 1
        dut.jtag_ic_reset_capture_en_i.value = 1
        dut.jtag_ic_reset_shift_en_i.value = 0
        dut.jtag_ic_reset_update_en_i.value = 0
        await self._tck()
        dut.jtag_ic_reset_capture_en_i.value = 0
        dut.jtag_ic_reset_shift_en_i.value = 1
        captured = 0
        for bit in range(_IC_RESET_BITS):
            captured |= self.rd_known(dut.jtag_ic_reset_tdo_o) << bit
            dut.jtag_ic_reset_tdi_i.value = (value >> bit) & 1
            await self._tck()
        dut.jtag_ic_reset_shift_en_i.value = 0
        dut.jtag_ic_reset_tdi_i.value = 0
        dut.jtag_ic_reset_update_en_i.value = 1
        await self._tck()
        dut.jtag_ic_reset_update_en_i.value = 0
        dut.jtag_ic_reset_select_i.value = 0
        return captured

    async def _read_sw_reset(self, label: str) -> int:
        seq = SepAxiAccessSeq(
            "sw_reset_n_reach",
            op=SepAxiOp.READ,
            addr=SEP_RESET_CTRL_SW_RESET_N,
            size=2,
            expected=SW_RESET_N_RESET_DEFAULT,
        )
        await self.start_seq(seq)
        cpu_rst, fabric_rst = self._probes()
        got = seq.rdata & 0xFFFF_FFFF
        assert seq.resp_ok and not seq.timed_out and got == SW_RESET_N_RESET_DEFAULT, (
            f"{label} FAIL: SW_RESET_N @0x{SEP_RESET_CTRL_SW_RESET_N:08x} "
            f"resp_ok={int(seq.resp_ok)} timed_out={int(seq.timed_out)} "
            f"rdata=0x{got:08x} want AXI OKAY 0x{SW_RESET_N_RESET_DEFAULT:08x}"
        )
        assert cpu_rst == 1 and fabric_rst == 1, (
            f"{label} FAIL: probes {cpu_rst}/{fabric_rst} during the OKAY read, want 1/1"
        )
        return got

    async def _log_sense_status_pre(self) -> None:
        """OBS-SENSE-STATUS-PRE: SEP_FUSE_SENSE_STATUS read while sensing runs.

        The TDR keeps ``sep_reset_n`` released and no token is presented, so the
        read reaches ``sep_cpu_ctrl`` while the sense is still in progress.
        """
        dut = cocotb.top
        done_before = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        seq = SepAxiAccessSeq(
            "sense_status_pre",
            op=SepAxiOp.READ,
            addr=SEP_FUSE_SENSE_STATUS,
            length=8,
            size=3,
            allow_ungraded_read_resp=True,
            allow_timeout=True,
        )
        await self.start_seq(seq)
        done_after = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        cpu_rst, fabric_rst = self._probes()
        self.logger.info(
            "OBS-SENSE-STATUS-PRE: SEP_FUSE_SENSE_STATUS @0x%08x resp=%d timed_out=%d "
            "rdata=0x%016x sense_done_before=%d sense_done_after=%d "
            "sep_cpu_reset_n_o=%d dbg_sep_reset_n_o=%d",
            SEP_FUSE_SENSE_STATUS,
            seq.resp_code,
            int(seq.timed_out),
            seq.rdata & ((1 << 64) - 1),
            done_before,
            done_after,
            cpu_rst,
            fabric_rst,
        )

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.release_no_cpu_reset()
        self._require_sense_open("CHK-TDR-IDLE")
        cpu_rst, fabric_rst = self._probes()
        assert cpu_rst == 0 and fabric_rst == 0, (
            f"CHK-TDR-IDLE FAIL: probes {cpu_rst}/{fabric_rst} before the TDR, want 0/0"
        )

        await self._reset_tdr()
        self._require_sense_open("CHK-TDR-IDLE")
        await self._hold_probes(0, "CHK-TDR-IDLE")
        self._pins_stay_clear("CHK-TDR-IDLE")
        self.logger.info(
            "CHK-TDR-IDLE PASS: TDR selected at its reset value, "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0 for %d cycles, override pins 0",
            _RESET_SYNC_CYCLES,
        )

        # reset_control first, with reset_enable still at its reset 1, so the
        # mux select does not move on this Update-DR. The next Capture-DR reads
        # the written word back.
        ctrl_word = self._pack(enable_port=None, control_port=_SEP_RESET_N_PORT)
        captured = await self._capture_shift_update(ctrl_word)
        self._require_sense_open("CHK-TDR-CAPTURE")
        idle = (1 << _IC_RESET_BITS) - 1
        assert captured == idle, (
            f"CHK-TDR-CAPTURE FAIL: shifted-out 0x{captured:x} want 0x{idle:x} "
            "(the TDR reset value)"
        )
        self.logger.info(
            "CHK-TDR-CAPTURE PASS: shifted-out 0x%x (reset_hold and every "
            "reset_enable/reset_control at 1)",
            captured,
        )
        await self._hold_probes(0, "CHK-TDR-CTRL")

        # The shift register now holds a word other than the written one, so only a
        # Capture-DR that loads the updated TDR returns the written word.
        decoy = self._pack(enable_port=None)
        await self._shift_only(decoy)
        readback = await self._capture_shift_update(self._pack(enable_port=_SEP_RESET_N_PORT))
        self._require_sense_open("CHK-TDR-CTRL")
        assert decoy != ctrl_word and readback == ctrl_word, (
            f"CHK-TDR-CTRL FAIL: Capture-DR after the reset_control[{_SEP_RESET_N_PORT}]=0 "
            f"Update-DR and a shift of 0x{decoy:x} with no update shifted out "
            f"0x{readback:x}, want the written 0x{ctrl_word:x}"
        )
        self.logger.info(
            "CHK-TDR-CTRL PASS: Update-DR of reset_control[%d]=0 with reset_enable[%d]=1 "
            "leaves sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0 for %d cycles; "
            "after a shift of 0x%x with no update, Capture-DR reads back 0x%x (written 0x%x)",
            _SEP_RESET_N_PORT,
            _SEP_RESET_N_PORT,
            _RESET_SYNC_CYCLES,
            decoy,
            readback,
            ctrl_word,
        )
        self._require_sense_open("CHK-TDR-RELEASE")
        await self._wait_probes(1, "CHK-TDR-RELEASE")
        self._pins_stay_clear("CHK-TDR-RELEASE")
        self.logger.info(
            "CHK-TDR-RELEASE PASS: TDR reset_enable[%d]=0 reset_control[%d]=1 "
            "sep_cpu_reset_n_o=1 dbg_sep_reset_n_o=1 sense_done=0, override pins 0",
            _SEP_RESET_N_PORT,
            _SEP_RESET_N_PORT,
        )

        got = await self._read_sw_reset("CHK-REACH")
        self._require_sense_open("CHK-REACH")
        self.logger.info(
            "CHK-REACH PASS: SW_RESET_N @0x%08x AXI OKAY rdata=0x%08x "
            "while sense_done=0 and sep_reset_n is released by the TDR",
            SEP_RESET_CTRL_SW_RESET_N,
            got,
        )

        await self._log_sense_status_pre()

        self._require_sense_open("CHK-FEAT-CLOSED")
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=0)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        mark = self.sb_mark()
        await self.start_seq(ctl)
        self._require_sense_open("CHK-FEAT-CLOSED")
        assert sec_dis == 0 and ctl.feat_ctrl == feat, (
            f"CHK-FEAT-CLOSED FAIL: sec_dis={sec_dis} FEAT_CTRL=0x{ctl.feat_ctrl:016x} "
            f"want 0 / 0x{feat:016x}"
        )
        self.assert_sb_judged(mark, "CHK-FEAT-CLOSED")
        self.logger.info(
            "CHK-FEAT-CLOSED PASS: sense_done=0 sec_dis=0 FEAT_CTRL=0x%016x",
            ctl.feat_ctrl,
        )

        await self._capture_shift_update(self._pack(enable_port=None))
        self._require_sense_open("CHK-TDR-REHOLD")
        await self._wait_probes(0, "CHK-TDR-REHOLD")
        self._pins_stay_clear("CHK-TDR-REHOLD")
        self.logger.info(
            "CHK-TDR-REHOLD PASS: TDR reset_enable restored, "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0 sense_done=0"
        )

        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        dut = cocotb.top
        for _ in range(_RESET_SYNC_CYCLES):
            await RisingEdge(dut.clk_i)
            if self._probes() == (1, 1):
                break
        else:
            cpu_rst, fabric_rst = self._probes()
            raise AssertionError(
                f"CHK-SENSE-RELEASE FAIL: after sense-done "
                f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 1/1"
            )
        self.logger.info(
            "CHK-SENSE-RELEASE PASS: after sense-done, with the TDR override off, "
            "sep_cpu_reset_n_o=1 dbg_sep_reset_n_o=1"
        )

        got = await self._read_sw_reset("CHK-SENSE-REACH")
        self.logger.info(
            "CHK-SENSE-REACH PASS: SW_RESET_N @0x%08x AXI OKAY rdata=0x%08x "
            "after sense-done with the TDR override off",
            SEP_RESET_CTRL_SW_RESET_N,
            got,
        )

        withheld = feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=0)
        sensed = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, sec_dis=0)
        assert sensed != withheld, (
            f"test bug: sensed PROD golden 0x{sensed:016x} equals the withheld golden, "
            "so CHK-FEAT-SENSED could not tell them apart"
        )
        ctl = SepLccFeatCtrlCheckSeq(sensed)
        mark = self.sb_mark()
        await self.start_seq(ctl)
        assert ctl.feat_ctrl == sensed, (
            f"CHK-FEAT-SENSED FAIL: FEAT_CTRL=0x{ctl.feat_ctrl:016x} after sense-done, "
            f"want the PROD golden 0x{sensed:016x}"
        )
        self.assert_sb_judged(mark, "CHK-FEAT-SENSED")
        self.logger.info(
            "CHK-FEAT-SENSED PASS: after sense-done FEAT_CTRL=0x%016x, the PROD golden; "
            "the same read returned the withheld 0x%016x while sensing was open",
            ctl.feat_ctrl,
            withheld,
        )

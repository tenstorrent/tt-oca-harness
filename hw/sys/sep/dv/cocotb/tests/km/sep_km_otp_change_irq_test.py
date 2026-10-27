# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP-change IRQ: the informational handler runs and the KM does not halt.

no_cpu / real fuse sense / the ``rom_main_otp_change`` image, which is the
bench wipe pair with ``IRQ_ENABLE.otp_change_en`` set at boot.

CHK-OTP-ARM proves the source is armed and the main loop answers. CHK-OTP-PULSE
proves HK-IRQSET fired and ``IRQ_STATUS.otp_change`` reads 1. CHK-OTP-ENTRY
requires the KM CPU to enter the KMCSR interrupt after the pulse, so the handler
ran. CHK-OTP-RETIRE requires PIC vector bit 30 to stay 0 and a following CMD_STAT to complete with
return code 0, since the handler does not halt the KM. OBS-OTP-STICKY logs
``IRQ_STATUS.otp_change`` and its enabled line after the handler; no spec
sentence states their value, so they are not graded.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_km_otp_chg_pass,
)
from env.sep_reg_meta import CHeaderRegBlock, ip_c_header
from env.sep_spec_tables import agg_from_pic
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_STAT,
    KM_RC_SUCCESS,
    SepKmMailbox,
)

_KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
_IRQ = _KM_CSR.fields("IRQ_STATUS_REG")
_EN = _KM_CSR.fields("IRQ_ENABLE_REG")
OTP_CHANGE = int(_IRQ["OTP_CHANGE"]["bm"])
OTP_CHANGE_EN = int(_EN["OTP_CHANGE_EN"]["bm"])
if OTP_CHANGE != OTP_CHANGE_EN:
    raise RuntimeError(
        f"OTP_CHANGE mask 0x{OTP_CHANGE:x} and OTP_CHANGE_EN mask 0x{OTP_CHANGE_EN:x} differ"
    )

KM_UNREC_BIT = agg_from_pic("KM unrecoverable error")
# A handler that returns to the main loop answers CMD_STAT in far fewer clocks than this.
RETIRE_CLKS = 5000
# recv_frame waits ``timeout`` polls of 20 clocks.
_STAT_POLLS = RETIRE_CLKS // 20

TEST = "sep_km_otp_change_irq_test"


@pyuvm.test()
class sep_km_otp_change_irq_test(sep_base_test):
    """One OTP-change IRQ, then PIC bit 30 stays 0 and CMD_STAT completes."""

    def _status(self) -> int:
        return self.rd_known(cocotb.top.km_csr_irq_status_o)

    def _enable(self) -> int:
        return self.rd_known(cocotb.top.km_csr_irq_enable_o)

    def _pic30(self) -> int:
        return self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << KM_UNREC_BIT)

    def _rom_reqs(self) -> int:
        return self.rd_known(cocotb.top.km_rom_req_count_o)

    def _kmcsr_entries(self) -> int:
        return self.rd_known(cocotb.top.km_kmcsr_irq_entry_count_o)

    async def _stat(self, polls: int) -> tuple[bool, int]:
        """CMD_STAT with a bounded wait. ``(answered, rc)``; rc is -1 on timeout."""
        seq = await self.km.send_command(KM_CMD_STAT, [])
        try:
            rc, _arg = await self.km.recv_resp_cmd(
                KM_CMD_STAT, seq, timeout=polls, require_arg=True
            )
        except AssertionError as exc:
            if "timeout waiting for a KM response word" not in str(exc):
                raise
            return False, -1
        await self.km.check_outbound_empty("POST-STAT")
        return True, rc

    async def _pulse(self) -> int:
        top = cocotb.top
        await RisingEdge(top.clk_i)
        top.km_irqset_mask_i.value = OTP_CHANGE
        top.km_irqset_arm_i.value = 1
        fired = 0
        for _ in range(8):
            await RisingEdge(top.clk_i)
            fired = self.rd_known(top.km_irqset_fired_o)
            if fired == 1:
                break
        await RisingEdge(top.clk_i)
        top.km_irqset_arm_i.value = 0
        top.km_irqset_mask_i.value = 0
        await RisingEdge(top.clk_i)
        return fired

    async def _bit_is(self, high: bool, clocks: int) -> bool:
        """Poll ``IRQ_STATUS.otp_change`` until it matches ``high``, or ``clocks`` pass."""
        top = cocotb.top
        want = OTP_CHANGE if high else 0
        for _ in range(clocks):
            if (self._status() & OTP_CHANGE) == want:
                return True
            await RisingEdge(top.clk_i)
        return (self._status() & OTP_CHANGE) == want

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))
        self.km = SepKmMailbox(self)
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        try:
            await self._body()
        finally:
            cocotb.top.km_irqset_arm_i.value = 0
            cocotb.top.km_irqset_mask_i.value = 0
            await self.stop_fifo_drain()

    async def _body(self) -> None:
        await self.swrst.release("km")
        await self.km.wait_km_ready()

        en = self._enable()
        st = self._status()
        pic = self._pic30()
        answered, rc = await self._stat(_STAT_POLLS)
        armed = (en & OTP_CHANGE_EN) == OTP_CHANGE_EN and (st & OTP_CHANGE) == 0 and pic == 0
        arm_ok = armed and answered and rc == KM_RC_SUCCESS
        if arm_ok:
            self.logger.info(
                "CHK-OTP-ARM PASS: en_otp_change=1 status_otp_change=0 pic30=0 stat_rc=0"
            )
        else:
            self.logger.error(
                "CHK-OTP-ARM FAIL: en=0x%x status=0x%x pic30=%d stat_answered=%d stat_rc=%d",
                en,
                st,
                int(pic != 0),
                int(answered),
                rc,
            )
            raise AssertionError(
                "CHK-OTP-ARM FAIL: "
                f"en=0x{en:x} status=0x{st:x} pic30={int(pic != 0)} "
                f"stat_answered={int(answered)} stat_rc={rc}"
            )

        window = False
        try:
            open_graded_window(TEST, self.logger)
            window = True
            rom0 = self._rom_reqs()
            ent0 = self._kmcsr_entries()
            fired = await self._pulse()
            rose = await self._bit_is(True, 64)
            if fired != 1 or not rose:
                self.logger.error(
                    "CHK-OTP-PULSE FAIL: fired=%d status_otp_change=%d mask=0x%x",
                    fired,
                    int(rose),
                    OTP_CHANGE,
                )
                raise AssertionError(
                    "CHK-OTP-PULSE FAIL: "
                    f"fired={fired} status_otp_change={int(rose)} mask=0x{OTP_CHANGE:x}"
                )
            self.logger.info(
                "CHK-OTP-PULSE PASS: fired=1 status_otp_change=1 mask=0x%x", OTP_CHANGE
            )
            await self._bit_is(False, RETIRE_CLKS)
            st = self._status()
            en = self._enable()
            pic = self._pic30()
            line = int((st & en & OTP_CHANGE) != 0)
            bit = int((st & OTP_CHANGE) != 0)
            self.logger.info("OBS-OTP-STICKY LOG status_otp_change=%d line=%d", bit, line)
            entries = self._kmcsr_entries() - ent0
            if entries < 1:
                self.logger.error("CHK-OTP-ENTRY FAIL: kmcsr_irq_entries=%d", entries)
                raise AssertionError(f"CHK-OTP-ENTRY FAIL: kmcsr_irq_entries={entries}")
            self.logger.info("CHK-OTP-ENTRY PASS: kmcsr_irq_entries=%d", entries)
            answered, rc = await self._stat(_STAT_POLLS)
            rom1 = self._rom_reqs()
            ok = pic == 0 and answered and rc == KM_RC_SUCCESS
            fields = (
                f"pic30={int(pic != 0)} stat_answered={int(answered)} stat_rc={rc} "
                f"rom_req_delta={rom1 - rom0} fired={fired}"
            )
            if not ok:
                self.logger.error("CHK-OTP-RETIRE FAIL: %s", fields)
                raise AssertionError(f"CHK-OTP-RETIRE FAIL: {fields}")
            self.logger.info("CHK-OTP-RETIRE PASS: %s", fields)
            set_km_otp_chg_pass(True, self.logger)
            await RisingEdge(cocotb.top.clk_i)
            set_km_otp_chg_pass(False, self.logger)
        finally:
            if window:
                close_graded_window(self.logger)

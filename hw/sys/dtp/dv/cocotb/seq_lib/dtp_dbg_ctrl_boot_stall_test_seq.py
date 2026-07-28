# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_dbg_ctrl_boot_stall_test."""

from __future__ import annotations

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_ctrl_boot_stall_test_seq(dtp_debug_tdr_base_test_seq):
    """Check DEBUG_CONTROL boot-stall override fields."""

    async def check_boot_stall_combo(
        self,
        *,
        boot_stall_ovrd: int,
        boot_stall: int,
        jtag_clock_stop: int = 0,
        cla_clock_stop_en: int = 0,
        context: str = "",
    ) -> None:
        """Write one DEBUG_CONTROL combination and check outputs plus readback."""
        value = self.pack_debug_control(
            boot_stall_ovrd=boot_stall_ovrd,
            boot_stall=boot_stall,
            jtag_clock_stop=jtag_clock_stop,
            cla_clock_stop_en=cla_clock_stop_en,
        )
        self.log.info(
            "%s write DEBUG_CONTROL=0x%02x boot_ovrd=%d boot_stall=%d "
            "jtag_stop=%d cla_stop_en=%d",
            context,
            value,
            boot_stall_ovrd,
            boot_stall,
            jtag_clock_stop,
            cla_clock_stop_en,
        )
        await self.write_debug_control(value)
        await self.wait_sys_cycles()
        await self.expect_signal("jtag_boot_stall_ovrd", boot_stall_ovrd)
        await self.expect_signal("jtag_boot_stall", boot_stall)

        readback = await self.read_debug_control(shift_value=value)
        decoded = self.log_debug_control(f"{context} readback", readback)
        self.assert_equal("DEBUG_CONTROL.boot_stall_ovrd", decoded["boot_stall_ovrd"], boot_stall_ovrd, context)
        self.assert_equal("DEBUG_CONTROL.boot_stall", decoded["boot_stall"], boot_stall, context)
        self.assert_equal("DEBUG_CONTROL.jtag_clock_stop", decoded["jtag_clock_stop"], jtag_clock_stop, context)
        self.assert_equal(
            "DEBUG_CONTROL.cla_clock_stop_en",
            decoded["cla_clock_stop_en"],
            cla_clock_stop_en,
            context,
        )

    async def body(self) -> None:
        self.log_banner("DEBUG_CONTROL Boot Stall")

        self.log_step(1, "Reset TAP and verify boot-stall reset value")
        await self.reset_tap()

        reset_value = await self.read_debug_control()
        self.log_debug_control("After reset", reset_value)
        self.assert_equal("DEBUG_CONTROL reset", reset_value, 0)
        await self.expect_signal("jtag_boot_stall_ovrd", 0)
        await self.expect_signal("jtag_boot_stall", 0)

        self.log_step(2, "Loop all boot_stall_ovrd / boot_stall combinations")
        combinations = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for idx, (boot_stall_ovrd, boot_stall) in enumerate(combinations, start=1):
            self.log_iteration(
                idx,
                len(combinations),
                "boot_stall_ovrd=%d boot_stall=%d",
                boot_stall_ovrd,
                boot_stall,
            )
            await self.check_boot_stall_combo(
                boot_stall_ovrd=boot_stall_ovrd,
                boot_stall=boot_stall,
                context=f"combo#{idx}",
            )

        self.log_step(3, "Check boot_stall can toggle while override remains asserted")
        for idx, boot_stall in enumerate([0, 1, 0, 1], start=1):
            await self.check_boot_stall_combo(
                boot_stall_ovrd=1,
                boot_stall=boot_stall,
                context=f"independent#{idx}",
            )

        self.log_step(4, "Check boot-stall fields are independent of other DEBUG_CONTROL bits")
        interaction_cases = [
            {"jtag_clock_stop": 1, "cla_clock_stop_en": 0},
            {"jtag_clock_stop": 0, "cla_clock_stop_en": 1},
            {"jtag_clock_stop": 1, "cla_clock_stop_en": 1},
        ]
        for idx, extras in enumerate(interaction_cases, start=1):
            await self.check_boot_stall_combo(
                boot_stall_ovrd=1,
                boot_stall=1,
                context=f"interaction#{idx}",
                **extras,
            )

        self.log_step(5, "Cleanup DEBUG_CONTROL")
        await self.write_debug_control(0)
        await self.wait_sys_cycles()
        await self.expect_signal("jtag_boot_stall_ovrd", 0)
        await self.expect_signal("jtag_boot_stall", 0)
        self.log_summary(
            "Boot-stall complete",
            combination_count=len(combinations),
            interaction_count=len(interaction_cases),
        )

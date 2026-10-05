# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
        """Write one DEBUG_CONTROL combination and record outputs plus readback."""
        value = self.pack_debug_control(
            boot_stall_ovrd=boot_stall_ovrd,
            boot_stall=boot_stall,
            jtag_clock_stop=jtag_clock_stop,
            cla_clock_stop_en=cla_clock_stop_en,
        )
        self.log.info(
            "%s write DEBUG_CONTROL=0x%02x boot_ovrd=%d boot_stall=%d jtag_stop=%d cla_stop_en=%d",
            context,
            value,
            boot_stall_ovrd,
            boot_stall,
            jtag_clock_stop,
            cla_clock_stop_en,
        )
        await self.write_debug_control(value)
        await self.wait_sys_cycles()
        await self.expect_dbg_signal("jtag_boot_stall_ovrd", boot_stall_ovrd, context=context)
        await self.expect_dbg_signal("jtag_boot_stall", boot_stall, context=context)

        readback = await self.read_debug_control(shift_value=value)
        decoded = self.log_debug_control(f"{context} readback", readback)
        self.check_debug_control_fields(
            decoded,
            {
                "boot_stall_ovrd": boot_stall_ovrd,
                "boot_stall": boot_stall,
                "jtag_clock_stop": jtag_clock_stop,
                "cla_clock_stop_en": cla_clock_stop_en,
            },
            context=context,
        )

    async def body(self) -> None:
        self.log_banner("DEBUG_CONTROL Boot Stall")
        await self.attach_family_checker({"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"})

        self.log_step(1, "Reset TAP and verify boot-stall reset value")
        await self.reset_to_tlr()
        # The DEBUG_CONTROL reset check below includes the live cla_clock_stop
        # status bit, which mirrors the xtrig_clk_stop_req TB input, so that
        # input must be zero before the read.
        await self.set_clk_stop_requests(0)

        reset_value = await self.read_debug_control()
        self.log_debug_control("After reset", reset_value)
        self.family_check("CHK-DBG-TDR", "DEBUG_CONTROL reset", reset_value, 0)
        await self.expect_dbg_signal("jtag_boot_stall_ovrd", 0, context="after reset")
        await self.expect_dbg_signal("jtag_boot_stall", 0, context="after reset")

        self.log_step(2, "Loop all boot_stall_ovrd / boot_stall combinations")
        # Exhaustive 2x2 sweep in a seeded per-pass order: repeated loops
        # exercise different combination transitions.
        combinations = [(0, 0), (0, 1), (1, 0), (1, 1)]
        self.rng("boot_stall_order").shuffle(combinations)
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

        self.log_step(4, "Check boot-stall fields are independent of the clock-stop bits")
        interaction_cases = [
            {"jtag_clock_stop": 1, "cla_clock_stop_en": 0},
            {"jtag_clock_stop": 0, "cla_clock_stop_en": 1},
            {"jtag_clock_stop": 1, "cla_clock_stop_en": 1},
        ]
        interaction_count = 0
        for boot_stall_ovrd, boot_stall in combinations:
            for extras in interaction_cases:
                interaction_count += 1
                await self.check_boot_stall_combo(
                    boot_stall_ovrd=boot_stall_ovrd,
                    boot_stall=boot_stall,
                    context=f"interaction#{interaction_count}",
                    **extras,
                )

        self.log_step(5, "Reset the TAP over a seeded nonzero DEBUG_CONTROL[3:0]")
        # Capture-DR returns the reset register, 0x00, not the stale value
        # last shifted in.
        stale = self.rng("boot_stall_stale").randint(1, 0xF)
        stale_context = f"stale=0x{stale:x}"
        await self.write_debug_control(stale)
        await self.reset_to_tlr()
        await self.expect_dbg_signal(
            "jtag_boot_stall_ovrd", 0, context=f"after TAP reset {stale_context}"
        )
        await self.expect_dbg_signal(
            "jtag_boot_stall", 0, context=f"after TAP reset {stale_context}"
        )
        readback = await self.read_debug_control()
        self.log_debug_control("After TAP reset", readback)
        self.family_check(
            "CHK-DBG-TDR", "DEBUG_CONTROL after TAP reset", readback, 0, context=stale_context
        )

        self.log_step(6, "Cleanup DEBUG_CONTROL")
        await self.write_debug_control(0)
        await self.wait_sys_cycles()
        await self.expect_dbg_signal("jtag_boot_stall_ovrd", 0, context="cleanup")
        await self.expect_dbg_signal("jtag_boot_stall", 0, context="cleanup")
        self.log_summary(
            "Boot-stall complete",
            combination_count=len(combinations),
            interaction_count=interaction_count,
            stale=f"0x{stale:x}",
        )
        await self.finalize_family_checker()

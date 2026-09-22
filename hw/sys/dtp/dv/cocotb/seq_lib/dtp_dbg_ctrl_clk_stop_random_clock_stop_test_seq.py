# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_ctrl_clk_stop_random_clock_stop_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_NUM_CLK_STOP_REQ

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq(dtp_debug_tdr_base_test_seq):
    """Check directed and randomized DEBUG_CONTROL clock-stop combinations."""

    async def check_combo(
        self,
        *,
        jtag_clock_stop: int,
        cla_clock_stop_en: int,
        clk_stop_req: int,
        context: str = "",
    ) -> None:
        """Apply one clock-stop combination and record outputs and readback."""
        control_value = self.pack_debug_control(
            jtag_clock_stop=jtag_clock_stop,
            cla_clock_stop_en=cla_clock_stop_en,
        )
        self.log.info(
            "%s apply jtag_stop=%d cla_stop_en=%d clk_stop_req=0x%03x control=0x%02x",
            context,
            jtag_clock_stop,
            cla_clock_stop_en,
            clk_stop_req,
            control_value,
        )
        await self.set_clk_stop_requests(clk_stop_req)
        await self.write_debug_control(control_value)
        await self.wait_sys_cycles()

        expected_cla = 1 if clk_stop_req else 0
        expected_stop = jtag_clock_stop | expected_cla
        await self.wait_for_signal_value("stop_clks", expected_stop, context=context)
        await self.expect_dbg_signal("cla_clock_stop_en", cla_clock_stop_en, context=context)

        readback = await self.read_debug_control(shift_value=control_value)
        decoded = self.log_debug_control(f"{context} readback", readback)
        self.check_debug_control_fields(
            decoded,
            {
                "cla_clock_stop": expected_cla,
                "jtag_clock_stop": jtag_clock_stop,
                "cla_clock_stop_en": cla_clock_stop_en,
            },
            context=context,
        )

    async def body(self) -> None:
        self.log_banner("DEBUG_CONTROL Random Clock Stop")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"}, use_monitor=False
        )

        self.log_step(1, "Reset TAP and create deterministic RNG")
        await self.reset_to_tlr()
        rng = self.rng("dbg_ctrl_random_clock_stop")

        self.log_step(2, "Run deterministic per-request and all-control sweep")
        directed_req_values = [0]
        directed_req_values += [1 << idx for idx in range(DTP_NUM_CLK_STOP_REQ)]
        directed_req_values += [
            (1 << DTP_NUM_CLK_STOP_REQ) - 1,
            0b101010101,
            0b010101010,
        ]

        total_directed = len(directed_req_values) * 4
        iteration = 0
        for req in directed_req_values:
            for jtag_clock_stop in (0, 1):
                for cla_clock_stop_en in (0, 1):
                    iteration += 1
                    self.log_iteration(
                        iteration,
                        total_directed,
                        "directed req=0x%03x jtag_stop=%d cla_stop_en=%d",
                        req,
                        jtag_clock_stop,
                        cla_clock_stop_en,
                    )
                    await self.check_combo(
                        jtag_clock_stop=jtag_clock_stop,
                        cla_clock_stop_en=cla_clock_stop_en,
                        clk_stop_req=req,
                        context=f"directed#{iteration}",
                    )

        self.log_step(3, "Run seeded random clock-stop combinations")
        for idx in range(1, self.random_count + 1):
            jtag_clock_stop = rng.randint(0, 1)
            cla_clock_stop_en = rng.randint(0, 1)
            clk_stop_req = rng.getrandbits(DTP_NUM_CLK_STOP_REQ)
            self.log_iteration(
                idx,
                self.random_count,
                "random req=0x%03x jtag_stop=%d cla_stop_en=%d",
                clk_stop_req,
                jtag_clock_stop,
                cla_clock_stop_en,
            )
            await self.check_combo(
                jtag_clock_stop=jtag_clock_stop,
                cla_clock_stop_en=cla_clock_stop_en,
                clk_stop_req=clk_stop_req,
                context=f"random#{idx}",
            )

        self.log_step(4, "Cleanup clock-stop request and DEBUG_CONTROL")
        await self.set_clk_stop_requests(0)
        await self.write_debug_control(0)
        await self.wait_sys_cycles()
        await self.wait_for_signal_value("stop_clks", 0, context="cleanup")
        self.log_summary(
            "Random clock-stop complete",
            directed_iterations=total_directed,
            random_iterations=self.random_count,
        )
        await self.finalize_family_checker()

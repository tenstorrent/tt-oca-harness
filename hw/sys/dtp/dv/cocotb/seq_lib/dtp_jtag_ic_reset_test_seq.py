# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_ic_reset_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_IC_RESET_LEN
from env.dtp_types import ic_reset_after_tlr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_ic_reset_test_seq(dtp_debug_tdr_base_test_seq):
    """Check IC_RESET active-low enable polarity and TLR hold behavior.

    The slice outputs across a Test-Logic-Reset or a TRST are judged before
    the following readback, whose Update-DR writes the expected value back
    into the register.
    """

    PORTS = ("smc", "sep", "ext")

    async def expect_slice(self, name: str, ovrd: int, ctrl_n: int, *, context: str = "") -> None:
        """Record one flattened IC_RESET slice output pair."""
        self.log.info(
            "Expect IC_RESET %s slice: ovrd=%d ctrl_n=%d",
            name.upper(),
            ovrd,
            ctrl_n,
        )
        await self.expect_dbg_signal(f"jtag_ic_reset_{name}_ovrd", ovrd, context=context)
        await self.expect_dbg_signal(f"jtag_ic_reset_{name}_ctrl_n", ctrl_n, context=context)

    async def expect_slices(
        self, reset_enable: dict[str, int], reset_control: dict[str, int], *, context: str
    ) -> None:
        """Every slice output follows the TDR fields of its port.

        ovrd is the inverted active-low enable and ctrl_n is the control bit
        ("IC_RESET Support" table), whatever the other ports hold.
        """
        self.log.info(
            "Expect every IC_RESET slice (%s): enable=%s control=%s",
            context,
            reset_enable,
            reset_control,
        )
        await self.wait_sys_cycles()
        for name in self.PORTS:
            await self.expect_slice(
                name,
                ovrd=1 - reset_enable[name],
                ctrl_n=reset_control[name],
                context=context,
            )

    async def expect_default_outputs(self, *, context: str) -> None:
        """Record that all one-port OSS slices are deasserted."""
        for name in self.PORTS:
            await self.expect_slice(name, ovrd=0, ctrl_n=1, context=context)

    async def body(self) -> None:
        self.log_banner("IC_RESET Override and Hold")
        await self.attach_family_checker({"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"})
        rng = self.rng("ic_reset")

        self.log_step(1, "Reset TAP and verify all IC_RESET fields default to 1")
        await self.reset_to_tlr()

        default_value = self.bit_mask(DTP_IC_RESET_LEN)
        observed = await self.read_ic_reset(shift_value=default_value)
        self.log_ic_reset("Default readback", observed)
        self.family_check("CHK-DBG-TDR", "IC_RESET default", observed, default_value)
        await self.expect_default_outputs(context="after reset")

        self.log_step(2, "Loop each slice through override active and inactive states")
        for idx, name in enumerate(self.PORTS, start=1):
            self.log_iteration(idx, len(self.PORTS), "Enable JTAG override for %s", name.upper())
            await self.write_ic_reset(
                reset_hold=1,
                reset_enable={name: 0},
                reset_control={name: 0},
            )
            await self.expect_slice(name, ovrd=1, ctrl_n=0, context=f"{name} override active")

            self.log_iteration(idx, len(self.PORTS), "Disable JTAG override for %s", name.upper())
            await self.write_ic_reset(
                reset_hold=1,
                reset_enable={name: 1},
                reset_control={name: 1},
            )
            await self.expect_slice(name, ovrd=0, ctrl_n=1, context=f"{name} override released")

        self.log_step(
            3, "Verify reset_hold=0 preserves enable/control bits and outputs through TLR"
        )
        held_enable = {"smc": 0, "sep": 0, "ext": 1}
        held_control = {"smc": 0, "sep": 1, "ext": 0}
        held_pattern = await self.write_ic_reset(
            reset_hold=0,
            reset_enable=held_enable,
            reset_control=held_control,
        )
        self.log_ic_reset("Held pattern before TLR", held_pattern)
        await self.expect_slices(held_enable, held_control, context="reset_hold=0 directed pattern")
        await self.drive_tlr_without_trst()
        await self.expect_slices(
            held_enable, held_control, context="reset_hold=0 in Test-Logic-Reset directed pattern"
        )
        expected = ic_reset_after_tlr(0, held_pattern, default_value)
        held_observed = await self.read_ic_reset(shift_value=expected)
        self.log_ic_reset("Held pattern after TLR", held_observed)
        self.family_check(
            "CHK-DBG-TDR", "IC_RESET reset_hold=0 TLR preserve", held_observed, expected
        )

        self.log_step(4, "Run seeded random reset_hold=0 preservation patterns")
        random_patterns = []
        for _ in range(self.random_count):
            reset_enable = {name: rng.randint(0, 1) for name in self.PORTS}
            reset_control = {name: rng.randint(0, 1) for name in self.PORTS}
            random_patterns.append((reset_enable, reset_control))

        for idx, (reset_enable, reset_control) in enumerate(random_patterns, start=1):
            self.log_iteration(
                idx,
                len(random_patterns),
                "reset_enable=%s reset_control=%s",
                reset_enable,
                reset_control,
            )
            pattern = await self.write_ic_reset(
                reset_hold=0,
                reset_enable=reset_enable,
                reset_control=reset_control,
            )
            self.log_ic_reset("Random held pattern before TLR", pattern)
            await self.expect_slices(
                reset_enable, reset_control, context=f"reset_hold=0 iteration={idx}"
            )
            await self.drive_tlr_without_trst()
            await self.expect_slices(
                reset_enable,
                reset_control,
                context=f"reset_hold=0 in Test-Logic-Reset iteration={idx}",
            )
            expected = ic_reset_after_tlr(0, pattern, default_value)
            observed_random = await self.read_ic_reset(shift_value=expected)
            self.log_ic_reset("Random held pattern after TLR", observed_random)
            self.family_check(
                "CHK-DBG-TDR",
                "IC_RESET random reset_hold=0 preserve",
                observed_random,
                expected,
                context=f"iteration={idx}",
            )

        self.log_step(5, "Verify reset_hold=1 lets TLR restore defaults")
        clearable_pattern = await self.write_ic_reset(
            reset_hold=1,
            reset_enable={"smc": 0, "sep": 0, "ext": 0},
            reset_control={"smc": 0, "sep": 0, "ext": 0},
        )
        self.log_ic_reset("Clearable pattern before TLR", clearable_pattern)
        assert clearable_pattern != default_value
        await self.drive_tlr_without_trst()
        await self.expect_default_outputs(context="reset_hold=1 in Test-Logic-Reset")
        expected = ic_reset_after_tlr(1, clearable_pattern, default_value)
        cleared = await self.read_ic_reset(shift_value=expected)
        self.log_ic_reset("After reset_hold=1 TLR", cleared)
        self.family_check("CHK-DBG-TDR", "IC_RESET reset_hold=1 TLR clear", cleared, expected)

        self.log_step(6, "Verify TRST always restores reset_hold and enable/control defaults")
        await self.write_ic_reset(
            reset_hold=0,
            reset_enable={"smc": 0, "sep": 0, "ext": 0},
            reset_control={"smc": 0, "sep": 0, "ext": 0},
        )
        await self.assert_trst(cycles=5)
        await self.deassert_trst(cycles=2)
        await self.expect_default_outputs(context="after TRST")
        trst_value = await self.read_ic_reset(shift_value=default_value)
        self.log_ic_reset("After TRST", trst_value)
        self.family_check("CHK-DBG-TDR", "IC_RESET TRST reset", trst_value, default_value)

        self.log_summary(
            "IC_RESET complete",
            deterministic_ports=",".join(self.PORTS),
            random_patterns=len(random_patterns),
            default=f"0b{default_value:07b}",
        )
        await self.finalize_family_checker()

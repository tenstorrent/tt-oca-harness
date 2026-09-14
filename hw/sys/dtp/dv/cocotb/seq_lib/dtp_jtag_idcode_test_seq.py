# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_idcode_test.

Verifies the DTP primary TAP IDCODE data register through the OCAH JTAG BFM.
"""

from __future__ import annotations

import random

import cocotb
from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, decode_idcode
from ocah_jtag_vip import OcahJtagChecker

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_idcode_test_seq(dtp_jtag_base_test_seq):
    """Run the DTP IDCODE field verification sequence."""

    def __init__(
        self,
        name: str = "dtp_jtag_idcode_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
        read_loops: int = 4,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.idcode = 0
        self.second_idcode = 0
        self.idcode_fields: dict[str, int] = {}
        self.read_loops = read_loops
        self.checker = OcahJtagChecker(
            name=f"{name}.checker",
            logger=cocotb.log,
            required_ids={
                "CHK-IDCODE-RAW",
                "CHK-IDCODE-STABLE",
                "CHK-IDCODE-MARKER",
                "CHK-IDCODE-VERSION",
                "CHK-IDCODE-PART-NUMBER",
                "CHK-IDCODE-MANUFACTURER",
                "CHK-TAP-RESET-TLR",
                "CHK-TAP-STATE",
                "CHK-NONVAC",
            },
        )
        # TAP resets and raw TMS walks in the random preconditions also emit
        # reference-model evidence (CHK-TAP-RESET-TLR / CHK-TAP-STATE).
        self.attach_tap_checker(self.checker)

    def check_idcode_fields(self) -> None:
        """Check raw IDCODE value and decoded IEEE 1149.1 fields."""
        expected_fields = decode_idcode(DTP_DEFAULT_IDCODE)

        self.checker.expect_equal(
            "CHK-IDCODE-RAW",
            self.idcode,
            DTP_DEFAULT_IDCODE,
            context="final decoded IDCODE",
        )
        self.checker.expect_equal(
            "CHK-IDCODE-MARKER",
            self.idcode_fields["lsb"],
            1,
            context=f"raw=0x{self.idcode:08x} bit=0",
        )
        field_ids = {
            "version": "CHK-IDCODE-VERSION",
            "part_number": "CHK-IDCODE-PART-NUMBER",
            "manufacturer": "CHK-IDCODE-MANUFACTURER",
        }
        for field, check_id in field_ids.items():
            expected = expected_fields[field]
            observed = self.idcode_fields[field]
            self.checker.expect_equal(
                check_id,
                observed,
                expected,
                context=f"field={field} raw=0x{self.idcode:08x}",
            )

        self.log.info(
            "IDCODE fields: version=0x%x part_number=0x%04x manufacturer=0x%03x marker=%d",
            self.idcode_fields["version"],
            self.idcode_fields["part_number"],
            self.idcode_fields["manufacturer"],
            self.idcode_fields["lsb"],
        )

    async def random_precondition(self, rng: random.Random, loop_idx: int) -> None:
        """Randomize the TAP context before reloading and reading IDCODE."""
        # Loop 0 always walks through TLR so the required TAP reset/state
        # evidence executes on every seed; later loops stay randomized.
        if loop_idx == 0:
            action = "tlr_walk"
        else:
            action = rng.choice(["tap_reset", "tlr_walk", "safe_ir", "bypass_scan"])
        self.log.info("IDCODE loop %d precondition: %s", loop_idx, action)

        if action == "tap_reset":
            await self.reset_to_tlr()
        elif action == "tlr_walk":
            await self.reset_to_tlr()
            await self.random_tms_walk(rng.randint(1, 10), rng=rng)
        elif action == "safe_ir":
            instr = rng.choice(
                [
                    DtpJtagInstr.BYPASS_00,
                    DtpJtagInstr.BYPASS_3F,
                    DtpJtagInstr.SAMPLE_PRELOAD,
                ]
            )
            await self.load_ir(instr)
        else:
            pattern = self.random_pattern(32, rng)
            await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, pattern, width=32)

    async def body(self) -> None:
        seed = self.scenario_seed
        self.log.info("Using IDCODE random seed %d", seed)
        rng = random.Random(seed)

        observed_values: list[int] = []
        for loop_idx in range(self.read_loops):
            await self.random_precondition(rng, loop_idx)
            item = await self.read_idcode()
            observed_values.append(item.result)

            self.checker.expect_equal(
                "CHK-IDCODE-RAW",
                item.result,
                DTP_DEFAULT_IDCODE,
                context=f"loop={loop_idx} precondition=randomized",
            )

        self.idcode = observed_values[0]
        self.second_idcode = observed_values[-1]

        self.checker.expect_equal(
            "CHK-IDCODE-STABLE",
            len(set(observed_values)),
            1,
            context=(
                f"reads={len(observed_values)} values="
                + ",".join(f"0x{value:08x}" for value in observed_values)
            ),
        )

        self.idcode_fields = decode_idcode(self.idcode)
        self.check_idcode_fields()
        self.checker.expect_true(
            "CHK-NONVAC",
            len(observed_values) >= 2 and self.idcode not in (0, 0xFFFF_FFFF),
            context=(
                f"reads={len(observed_values)} exact_expected=0x{DTP_DEFAULT_IDCODE:08x} "
                f"observed=0x{self.idcode:08x}"
            ),
        )
        self.checker.finalize()

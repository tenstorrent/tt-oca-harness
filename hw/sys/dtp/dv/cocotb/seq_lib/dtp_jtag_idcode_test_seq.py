# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_idcode_test.

Verifies the DTP primary TAP IDCODE data register through the OCAH JTAG BFM.
"""

from __future__ import annotations

import random

from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, decode_idcode

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

    def check_idcode_fields(self) -> None:
        """Check raw IDCODE value and decoded IEEE 1149.1 fields."""
        expected_fields = decode_idcode(DTP_DEFAULT_IDCODE)

        assert self.idcode == DTP_DEFAULT_IDCODE, (
            f"IDCODE mismatch: expected 0x{DTP_DEFAULT_IDCODE:08x}, "
            f"got 0x{self.idcode:08x}"
        )
        assert self.idcode_fields["lsb"] == 1, (
            f"IDCODE marker bit must be 1, got {self.idcode_fields['lsb']}"
        )
        for field, expected in expected_fields.items():
            observed = self.idcode_fields[field]
            assert observed == expected, (
                f"IDCODE {field} mismatch: expected 0x{expected:x}, got 0x{observed:x}"
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
        action = rng.choice(["tap_reset", "tlr_walk", "safe_ir", "bypass_scan"])
        self.log.info("IDCODE loop %d precondition: %s", loop_idx, action)

        if action == "tap_reset":
            await self.reset_tap()
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
        seed = self.scenario_seed if self.scenario_seed is not None else self.random_seed()
        self.log.info("Using IDCODE random seed %d", seed)
        rng = random.Random(seed)

        observed_values: list[int] = []
        for loop_idx in range(self.read_loops):
            await self.random_precondition(rng, loop_idx)
            item = await self.read_idcode()
            observed_values.append(item.result)

            assert item.result == DTP_DEFAULT_IDCODE, (
                f"IDCODE mismatch in loop {loop_idx}: expected 0x{DTP_DEFAULT_IDCODE:08x}, "
                f"got 0x{item.result:08x}"
            )

        self.idcode = observed_values[0]
        self.second_idcode = observed_values[-1]

        assert len(set(observed_values)) == 1, (
            "IDCODE not stable across randomized read loops: "
            + ", ".join(f"0x{value:08x}" for value in observed_values)
        )

        self.idcode_fields = decode_idcode(self.idcode)
        self.check_idcode_fields()

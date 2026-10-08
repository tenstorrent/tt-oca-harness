# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_idcode_test.

Verifies the DTP primary TAP IDCODE data register through the OCAH JTAG BFM:
one read through the reset-loaded instruction (a DR scan with no IR load
after TAP reset), one through the instruction a power-on reset loads (a
seeded instruction other than IDCODE loaded, then power-on reset with TRST_N
high and TCK idle, then a DR scan with no IR load), then looped reads under
seeded random TAP preconditioning. Every comparison lands as named ``CHK-*``
evidence through the family checker, finalized once per pass.
"""

from __future__ import annotations

import random

from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import RESET_COUNT_CHECK_ID, DtpJtagInstr, decode_idcode
from ocah_jtag_vip import OcahJtagState

from .dtp_jtag_base_test_seq import NON_IDCODE_PRELOADS, dtp_jtag_base_test_seq

IDCODE_MASK = 0xFFFF_FFFF
RECOVERY_CHECK_ID = "CHK-IDCODE-RECOVERY"
POR_CHECK_ID = "CHK-TAP-POR-TLR"
REQUIRED_CHECK_IDS: frozenset[str] = frozenset(
    {
        "CHK-IDCODE-RAW",
        "CHK-IDCODE-STABLE",
        "CHK-IDCODE-MARKER",
        "CHK-IDCODE-VERSION",
        "CHK-IDCODE-PART-NUMBER",
        "CHK-IDCODE-MANUFACTURER",
        RECOVERY_CHECK_ID,
        RESET_COUNT_CHECK_ID,
        "CHK-TAP-RESET-TLR",
        "CHK-TAP-STATE",
        "CHK-NONVAC",
    }
)


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

        self.family_check(
            "CHK-IDCODE-RAW",
            "IDCODE",
            self.idcode,
            DTP_DEFAULT_IDCODE,
            context="final decoded IDCODE",
        )
        self.family_check(
            "CHK-IDCODE-MARKER",
            "IDCODE marker bit",
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
            self.family_check(
                check_id,
                f"IDCODE {field} field",
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

    async def read_after_power_on_reset(self, rng: random.Random) -> int:
        """Power-on reset alone reloads IDCODE over the instruction loaded before it.

        TRST_N stays high and TCK idles across the pulse, so the DR scan with
        no IR load reads through the instruction the power-on reset selected.
        """
        preload = rng.choice(NON_IDCODE_PRELOADS)
        cycles = rng.randint(2, 8)
        context = f"preload=0x{int(preload):02x} por_cycles={cycles}"
        await self.load_ir(preload)
        item = await self.pulse_por(cycles=cycles)
        self.check_tap_state(
            POR_CHECK_ID,
            item.result,
            OcahJtagState.TEST_LOGIC_RESET,
            context=f"during POR {context}",
        )
        self.family_check(
            POR_CHECK_ID,
            "TRST_N deasserted during POR",
            item.signals["jtag_trst"],
            1,
            context=context,
        )
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)
        item = await self.shift_dr(0, 32)
        value = item.result & IDCODE_MASK
        self.family_check(
            RECOVERY_CHECK_ID,
            "IDCODE DR scan after POR, no IR load, TRST high",
            value,
            DTP_DEFAULT_IDCODE,
            context=context,
        )
        return value

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
            await self.load_ir(rng.choice(NON_IDCODE_PRELOADS))
        else:
            pattern = self.random_pattern(32, rng)
            await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, pattern, width=32)
        # CHK-TAP-STATE: the DUT's exported TAP state matches the tracked
        # state after every precondition.
        assert self.current_tap_state is not None
        item = await self.sample_observables()
        self.family_check(
            "CHK-TAP-STATE",
            "TAP state after precondition",
            item.result,
            int(self.current_tap_state),
            context=f"loop={loop_idx} action={action}",
        )

    async def body(self) -> None:
        checker = await self.attach_family_checker(
            set(REQUIRED_CHECK_IDS),
            # The random TMS walks of the preconditions visit Shift-x on
            # their own, so the scan cross-check would count episodes the
            # sequence never issued as scans.
            use_monitor=False,
        )
        rng = self.rng("idcode")

        observed_values: list[int] = []
        # Test-Logic-Reset loads IDCODE into the instruction register, so a DR
        # scan with no IR load reads the device identification through the
        # reset-selected path.
        self.log_step(1, "Reset TAP, then IDCODE with no IR load")
        await self.reset_to_tlr()
        item = await self.shift_dr(0, 32)
        observed_values.append(item.result & IDCODE_MASK)
        self.family_check(
            "CHK-IDCODE-RAW",
            "IDCODE read without IR load",
            observed_values[-1],
            DTP_DEFAULT_IDCODE,
            context="precondition=tap_reset no_ir_load",
        )
        self.log_step(2, "Power-on reset over a non-IDCODE instruction; IDCODE with no IR load")
        observed_values.append(await self.read_after_power_on_reset(self.rng("idcode_por")))
        self.log_step(3, "%d IDCODE reads under seeded TAP preconditions", self.read_loops)
        for loop_idx in range(self.read_loops):
            await self.random_precondition(rng, loop_idx)
            item = await self.read_idcode()
            observed_values.append(item.result)

            self.family_check(
                "CHK-IDCODE-RAW",
                "IDCODE read",
                item.result,
                DTP_DEFAULT_IDCODE,
                context=f"loop={loop_idx} precondition=randomized",
            )

        self.log_step(4, "Every read is identical and the first decodes to the IEEE 1149.1 fields")
        self.idcode = observed_values[0]
        self.second_idcode = observed_values[-1]

        self.family_check(
            "CHK-IDCODE-STABLE",
            "distinct IDCODE reads",
            len(set(observed_values)),
            1,
            context=(
                f"reads={len(observed_values)} values="
                + ",".join(f"0x{value:08x}" for value in observed_values)
            ),
        )

        self.idcode_fields = decode_idcode(self.idcode)
        self.check_idcode_fields()
        checker.expect_true(
            "CHK-NONVAC",
            len(observed_values) >= 2 and self.idcode not in (0, 0xFFFF_FFFF),
            context=(
                f"reads={len(observed_values)} exact_expected=0x{DTP_DEFAULT_IDCODE:08x} "
                f"observed=0x{self.idcode:08x}"
            ),
        )
        await self.finalize_family_checker()

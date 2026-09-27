# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""iJTAG SIB/DFT/DFD scan scenarios.

Every pattern is proved by ``check_ijtag_pattern``: a composed program scan
carrying seeded instrument values, then a marker scan under a temporal
window that yields the control evidence (``CHK-SCAN-WIN``), the measured
chain latency (``CHK-SCAN-LEN``), and the captured SIB states and
instrument registers against the SIB model (``CHK-SCAN-CHAIN``).
"""

from __future__ import annotations

from env.dtp_dbg_disable import IJTAG_SIB_DISABLE

from .dtp_scan_base_test_seq import dtp_scan_base_test_seq


class dtp_ijtag_scan_test_seq(dtp_scan_base_test_seq):
    """Run one iJTAG scenario selected by the public wrapper."""

    # Per-pass evidence every iJTAG pass must record (SV-UVM twin:
    # dtp_ijtag_scan_test_seq.svh).
    REQUIRED_IDS = frozenset(
        {"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-LEN", "CHK-SCAN-CHAIN"}
    )

    async def check_stored_sib_across_gate(
        self, sib: str, open_pattern: int, *, context: str
    ) -> None:
        """Prove a gated Update-DR does not modify stored SIB state and that
        access resumes without TAP reset after the disable clears."""
        disable_field = IJTAG_SIB_DISABLE[sib]
        # Baseline: everything enabled, all SIBs closed.
        await self.check_pattern(0b000, context=f"{context}.baseline")
        # Attempt to open the target SIB while its disable is asserted.
        await self.set_dbg_disable_vector({disable_field: 1})
        await self.program_ijtag_sibs(
            open_pattern,
            dbg_disable={disable_field: 1},
            context=f"{context}.gated_open_attempt",
        )
        # Release the disable without any reset: the gated open attempt must
        # not have stuck (a pre-staged open activating on release would be a
        # delayed-replay hazard).
        await self.enable_all_debug()
        await self.check_ijtag_all_closed(context=f"{context}.post_release")
        # Resume without reset: a sanctioned open now succeeds.
        await self.check_pattern(open_pattern, context=f"{context}.resume")

    def __init__(self, name: str = "dtp_ijtag_scan_test_seq", *, scenario: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario

    async def body(self) -> None:
        # Scenario-owned Shift-x exits: skip the scan-count cross-check.
        await self.attach_family_checker(set(self.REQUIRED_IDS), use_monitor=False)
        await self.enable_all_debug()
        await self.reset_to_tlr()
        await self.enable_all_debug()
        match self.scenario:
            case "sib_all_off":
                await self.run_sib_all_off()
            case "sib_all_on":
                await self.run_sib_all_on()
            case "sib_random":
                await self.run_sib_random()
            case "dft":
                await self.run_dft()
            case "dfd":
                await self.run_dfd()
            case _:
                raise ValueError(f"unknown iJTAG scenario {self.scenario}")
        await self.enable_all_debug()
        await self.program_ijtag_sibs(0, context="cleanup")
        await self.finalize_family_checker()

    async def check_pattern(
        self, pattern: int, *, dbg_disable: dict[str, int] | None = None, context: str
    ) -> None:
        await self.check_ijtag_pattern(pattern, dbg_disable=dbg_disable, context=context)

    async def run_sib_all_off(self) -> None:
        self.log_banner("iJTAG SIB all-off")
        rng = self.rng("ijtag_all_off")
        # A seeded open pattern first, so the all-off captures and the
        # collapse to the three SIB bits are a transition from open SIBs.
        open_pattern = rng.randrange(1, 8)
        self.log_step(
            1, "Open a seeded SIB set 0b%s, then close every SIB", format(open_pattern, "03b")
        )
        await self.check_pattern(open_pattern, context="all_off.open_seed")
        await self.check_pattern(0b000, context="all_off.nominal")
        # Seeded per-pass disable mask: with every SIB closed, any lifecycle
        # gating state must leave the outcome identical (closed stays closed).
        random_disable = {
            "dft_secure": rng.randrange(2),
            "dft_nonsecure": rng.randrange(2),
            "dfd": rng.randrange(2),
        }
        self.log_step(2, "Close every SIB again under the disable mask %s", random_disable)
        await self.check_pattern(
            0b000, dbg_disable=random_disable, context="all_off.random_disable"
        )
        await self.check_ijtag_all_closed(dbg_disable=random_disable, context="all_off.recheck")
        self.log_summary(
            "iJTAG all-off", open_seed=f"0b{open_pattern:03b}", random_disable=random_disable
        )

    async def run_sib_all_on(self) -> None:
        self.log_banner("iJTAG SIB all-on")
        await self.check_pattern(0b111, context="all_on.nominal")
        gate_vectors = [
            ("secure", 0b111, {"dft_secure": 1}),
            ("nonsecure", 0b111, {"dft_nonsecure": 1}),
            ("dfd", 0b111, {"dfd": 1}),
            ("all", 0b111, {"dft_secure": 1, "dft_nonsecure": 1, "dfd": 1}),
        ]
        # Seeded per-pass order: each loop exercises a different gate sequence.
        self.rng("ijtag_all_on_order").shuffle(gate_vectors)
        for label, pattern, dbg in gate_vectors:
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"all_on.gated.{label}")
        # Full chain and scan controls again once every disable is clear.
        await self.check_pattern(0b111, context="all_on.restore")
        self.log_summary("iJTAG all-on", gate_vectors=len(gate_vectors))

    async def run_sib_random(self) -> None:
        self.log_banner("iJTAG SIB deterministic and random sweep")
        for pattern in range(8):
            await self.check_pattern(pattern, context=f"sweep.pattern_{pattern:03b}")
        rng = self.rng("dtp_ijtag_sib_random")
        for idx in range(16):
            pattern = rng.randrange(0, 8)
            dbg = {
                "dft_secure": rng.randrange(0, 2),
                "dft_nonsecure": rng.randrange(0, 2),
                "dfd": rng.randrange(0, 2),
            }
            self.log_iteration(
                idx + 1, 16, "pattern=0b%s dbg_disable=%s", format(pattern, "03b"), dbg
            )
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"random.iter_{idx}")
        self.log_summary("iJTAG random", exhaustive_patterns=8, random_iterations=16)

    async def run_dft(self) -> None:
        self.log_banner("iJTAG DFT secure/non-secure access")
        await self.check_pattern(0b010, context="dft.nonsecure_only")
        await self.check_pattern(0b100, context="dft.secure_only")
        await self.check_pattern(0b110, context="dft.parallel")
        gate_cases = [
            ("secure_gated", 0b100, {"dft_secure": 1}),
            ("nonsecure_gated", 0b010, {"dft_nonsecure": 1}),
            # Cross-resource isolation: gating one DFT SIB must leave the
            # other DFT SIB accessible.
            ("secure_gated_nonsecure_open", 0b110, {"dft_secure": 1}),
            ("nonsecure_gated_secure_open", 0b110, {"dft_nonsecure": 1}),
        ]
        # Seeded per-pass order: each loop exercises a different gate sequence.
        self.rng("ijtag_dft_order").shuffle(gate_cases)
        for label, pattern, dbg in gate_cases:
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"dft.gated.{label}")
        await self.check_stored_sib_across_gate("dft", 0b010, context="dft.stored")
        self.log_summary("iJTAG DFT", gate_cases=len(gate_cases))

    async def run_dfd(self) -> None:
        self.log_banner("iJTAG DFD access and direct-disable gate")
        await self.check_pattern(0b001, context="dfd.enabled")
        await self.check_pattern(0b001, dbg_disable={"dfd": 1}, context="dfd.gated")
        rng = self.rng("dtp_ijtag_dfd")
        for idx in range(8):
            pattern = 0b001 | (rng.randrange(0, 4) << 1)
            dbg = {"dfd": rng.randrange(0, 2)}
            self.log_iteration(
                idx + 1, 8, "pattern=0b%s dbg_disable=%s", format(pattern, "03b"), dbg
            )
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"dfd.random_{idx}")
        await self.check_stored_sib_across_gate("dfd", 0b001, context="dfd.stored")
        self.log_summary("iJTAG DFD", random_iterations=8)

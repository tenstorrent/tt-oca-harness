# SPDX-License-Identifier: Apache-2.0
"""iJTAG SIB/DFT/DFD scan scenarios for GH issue #3213."""

from __future__ import annotations

from env.dtp_scan_ref_model import IJTAG_SIB_ORDER

from .dtp_scan_base_test_seq import dtp_scan_base_test_seq


class dtp_ijtag_scan_test_seq(dtp_scan_base_test_seq):
    """Run one iJTAG scenario selected by the public wrapper."""

    def __init__(self, name: str = "dtp_ijtag_scan_test_seq", *, scenario: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario

    async def body(self) -> None:
        await self.enable_all_debug()
        await self.reset_tap()
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

    async def check_pattern(self, pattern: int, *, dbg_disable: dict[str, int] | None = None, context: str) -> None:
        dbg = dict(dbg_disable or {})
        # Drive the full vector so the model's expectation and the DUT inputs
        # always agree, regardless of what earlier iterations left behind.
        await self.set_dbg_disable_vector(dbg)
        state = await self.program_ijtag_sibs(pattern, context=f"{context}.program", dbg_disable=dbg)
        _, signals = await self.observe_ijtag_controls(pattern, context=f"{context}.observe")
        self.check_ijtag_controls(state, signals, context=context)
        self.assert_equal(f"{context}.chain_len", state.chain_len, 3)

    async def run_sib_all_off(self) -> None:
        self.log_banner("GH #3213 iJTAG SIB all-off")
        await self.check_pattern(0b000, context="all_off.nominal")
        _, signals = await self.observe_ijtag_controls(0, context="all_off.recheck")
        for name in IJTAG_SIB_ORDER:
            prefix = {"dft_secure": "jtag_dft_secure", "dft": "jtag_dft", "dfd": "jtag_dfd"}[name]
            self.check_observable(signals, f"{prefix}_select", 0, context=f"all_off.{name}")
        self.log_summary("iJTAG all-off", pattern="0b000", chain_len=3)

    async def run_sib_all_on(self) -> None:
        self.log_banner("GH #3213 iJTAG SIB all-on")
        await self.check_pattern(0b111, context="all_on.nominal")
        gate_vectors = [
            ("secure", 0b111, {"dft_secure": 1}),
            ("nonsecure", 0b111, {"dft_nonsecure": 1}),
            ("dfd", 0b111, {"dfd": 1}),
        ]
        for label, pattern, dbg in gate_vectors:
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"all_on.gated.{label}")
        self.log_summary("iJTAG all-on", gate_vectors=len(gate_vectors), chain_len=3)

    async def run_sib_random(self) -> None:
        self.log_banner("GH #3213 iJTAG SIB deterministic and random sweep")
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
            self.log_iteration(idx + 1, 16, "pattern=0b%03b dbg_disable=%s", pattern, dbg)
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"random.iter_{idx}")
        self.log_summary("iJTAG random", exhaustive_patterns=8, random_iterations=16)

    async def run_dft(self) -> None:
        self.log_banner("GH #3213 iJTAG DFT secure/non-secure access")
        # Non-secure DFT only.
        await self.check_pattern(0b010, context="dft.nonsecure_only")
        # Secure DFT only.
        await self.check_pattern(0b100, context="dft.secure_only")
        gate_cases = [
            ("secure_gated", 0b100, {"dft_secure": 1}),
            ("nonsecure_gated", 0b010, {"dft_nonsecure": 1}),
            # Cross-resource isolation: gating one DFT SIB must leave the
            # other DFT SIB accessible.
            ("secure_gated_nonsecure_open", 0b110, {"dft_secure": 1}),
            ("nonsecure_gated_secure_open", 0b110, {"dft_nonsecure": 1}),
        ]
        for label, pattern, dbg in gate_cases:
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"dft.gated.{label}")
        self.log_summary("iJTAG DFT", gate_cases=len(gate_cases))

    async def run_dfd(self) -> None:
        self.log_banner("GH #3213 iJTAG DFD access and direct-disable gate")
        await self.check_pattern(0b001, context="dfd.enabled")
        await self.check_pattern(0b001, dbg_disable={"dfd": 1}, context="dfd.gated")
        rng = self.rng("dtp_ijtag_dfd")
        for idx in range(8):
            pattern = 0b001 | (rng.randrange(0, 4) << 1)
            dbg = {"dfd": rng.randrange(0, 2)}
            self.log_iteration(idx + 1, 8, "pattern=0b%03b dbg_disable=%s", pattern, dbg)
            await self.check_pattern(pattern, dbg_disable=dbg, context=f"dfd.random_{idx}")
        self.log_summary("iJTAG DFD", random_iterations=8)


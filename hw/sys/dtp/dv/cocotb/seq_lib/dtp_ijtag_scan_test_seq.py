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
        await self.clear_lifecycle()
        await self.reset_tap()
        await self.clear_lifecycle()
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
        await self.clear_lifecycle()
        await self.program_ijtag_sibs(0, context="cleanup")

    async def check_pattern(self, pattern: int, *, feat_ctrl: dict[str, int] | None = None, context: str) -> None:
        feat = dict(feat_ctrl or {})
        if feat:
            await self.set_lifecycle(**feat)
        else:
            await self.clear_lifecycle()
        state = await self.program_ijtag_sibs(pattern, context=f"{context}.program", feat_ctrl=feat)
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
            ("secure_dft_fuse", 0b111, {"fuse_test": 0}),
            ("nonsecure_soc", 0b111, {"soc_debug": 0}),
            ("dfd_ap", 0b111, {"ap_debug": 0}),
        ]
        for label, pattern, feat in gate_vectors:
            await self.check_pattern(pattern, feat_ctrl=feat, context=f"all_on.gated.{label}")
        self.log_summary("iJTAG all-on", gate_vectors=len(gate_vectors), chain_len=3)

    async def run_sib_random(self) -> None:
        self.log_banner("GH #3213 iJTAG SIB deterministic and random sweep")
        for pattern in range(8):
            await self.check_pattern(pattern, context=f"sweep.pattern_{pattern:03b}")
        rng = self.rng("dtp_ijtag_sib_random")
        for idx in range(16):
            pattern = rng.randrange(0, 8)
            feat = {
                "fuse_test": rng.randrange(0, 2),
                "sep_debug": rng.randrange(0, 2),
                "soc_debug": rng.randrange(0, 2),
                "ap_debug": rng.randrange(0, 2),
            }
            self.log_iteration(idx + 1, 16, "pattern=0b%03b feat=%s", pattern, feat)
            await self.check_pattern(pattern, feat_ctrl=feat, context=f"random.iter_{idx}")
        self.log_summary("iJTAG random", exhaustive_patterns=8, random_iterations=16)

    async def run_dft(self) -> None:
        self.log_banner("GH #3213 iJTAG DFT secure/non-secure access")
        # Non-secure DFT only.
        await self.check_pattern(0b010, context="dft.nonsecure_only")
        # Secure DFT only.
        await self.check_pattern(0b100, context="dft.secure_only")
        gate_cases = [
            ("secure_fuse", 0b100, {"fuse_test": 0}),
            ("secure_sep", 0b100, {"sep_debug": 0}),
            ("secure_soc", 0b100, {"soc_debug": 0}),
            ("secure_ap", 0b100, {"ap_debug": 0}),
            ("nonsecure_soc", 0b010, {"soc_debug": 0}),
            ("nonsecure_ap", 0b010, {"ap_debug": 0}),
        ]
        for label, pattern, feat in gate_cases:
            await self.check_pattern(pattern, feat_ctrl=feat, context=f"dft.gated.{label}")
        self.log_summary("iJTAG DFT", gate_cases=len(gate_cases))

    async def run_dfd(self) -> None:
        self.log_banner("GH #3213 iJTAG DFD access and AP gate")
        await self.check_pattern(0b001, context="dfd.enabled")
        await self.check_pattern(0b001, feat_ctrl={"ap_debug": 0}, context="dfd.ap_gated")
        rng = self.rng("dtp_ijtag_dfd")
        for idx in range(8):
            pattern = 0b001 | (rng.randrange(0, 4) << 1)
            feat = {"ap_debug": rng.randrange(0, 2)}
            self.log_iteration(idx + 1, 8, "pattern=0b%03b feat=%s", pattern, feat)
            await self.check_pattern(pattern, feat_ctrl=feat, context=f"dfd.random_{idx}")
        self.log_summary("iJTAG DFD", random_iterations=8)


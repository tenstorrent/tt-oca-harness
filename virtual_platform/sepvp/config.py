# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SimConfig — declarative inputs for one sep-vp run.

Mirrors the example harness's ``SimConfig`` but adapted to sep-vp's control surface:
boot straps and channel toggles map to ``och_sep_ss1.*`` CCI bools, the OTP fuse-map is a
YAML file, and the SPI flash is a prebuilt raw ``.bin``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from sepvp import fuses
from sepvp.inifile import Override

# friendly boot mode -> primary_chiplet bool
_BOOT_MODES = ("primary", "secondary")

PathLike = Union[str, Path]


@dataclass
class SimConfig:
    """Everything needed to launch one firmware image on sep-vp.

    boot_from_spi (the firmware's decision) = primary_chiplet && !boot_recovery.
    """

    name: str
    elf: PathLike
    flash_image: Optional[PathLike] = None  # prebuilt raw .bin staged to data/flash_memory.bin
    spi_preload: Optional[PathLike] = None  # $readmemh .spi_preload image, loaded VP-side
    otp: Optional[PathLike] = None  # YAML fuse-map path
    # Raw OCA bundle staged into the SMC SRAM window for the recovery / secondary
    # boot path, where the manifest arrives from the SMC rather than SPI flash.
    # A BUNDLE, not a combined SPI image: that path resolves the payload from the
    # manifest's own payload_offset, which for a bundle is already body_size.
    smc_sram_image: Optional[PathLike] = None
    # --- boot straps (och_sep_ss1.smc.*) ---
    boot: str = "secondary"  # "primary" (SPI boot) | "secondary" (wait SMC)
    recovery: bool = False  # boot_recovery: wait for SMC manifest (implies primary)
    rotate_update: bool = False  # use rotated (backup) manifest slot
    bl0_pll_clk: bool = False  # init PLL from fuses vs refclk
    status_report_disable: bool = False  # skip status-ring init (also suppresses SEP_STATUS)
    # --- decoded-output channels ---
    sim_out: bool = True  # [SIM_OUT] debug console (DEBUG firmware builds only)
    sep_status: bool = True  # [SEP_STATUS] production status decoder
    # --- misc ---
    boot_timeout: int = 120  # seconds; sep-vp never self-terminates
    extra_ini: List[Override] = field(default_factory=list)  # raw (section, key, value) overrides

    def __post_init__(self):
        if self.boot not in _BOOT_MODES:
            raise ValueError(f"boot must be one of {_BOOT_MODES}, got {self.boot!r}")

    @property
    def primary_chiplet(self) -> bool:
        # recovery is meaningful only on a primary chiplet (wait for SMC even though Primary).
        return self.boot == "primary" or self.recovery

    def strap_overrides(self) -> List[Override]:
        """Boot straps + channel toggles as ini bool overrides."""
        return [
            ("bool", "och_sep_ss1.smc.primary_chiplet", self.primary_chiplet),
            ("bool", "och_sep_ss1.smc.boot_recovery", self.recovery),
            ("bool", "och_sep_ss1.smc.rotate_update", self.rotate_update),
            ("bool", "och_sep_ss1.smc.bl0_pll_clk", self.bl0_pll_clk),
            ("bool", "och_sep_ss1.smc.status_report_disable", self.status_report_disable),
            # tt-oca-harness-model folded the SIM_OUT / SEP_STATUS decoders into the
            # sep_scratch_cold peripheral, moving both keys under scratch_cold.*. The old
            # names are still *accepted* by CCI as unconsumed presets -- they simply do
            # nothing -- so a stale name here fails silently rather than loudly.
            ("bool", "och_sep_ss1.scratch_cold.sim_out.enable", self.sim_out),
            ("bool", "och_sep_ss1.scratch_cold.sep_status.enable", self.sep_status),
        ]

    def smc_overrides(self) -> List[Override]:
        """SMC-SRAM staged manifest, as an absolute path the platform can open."""
        if not self.smc_sram_image:
            return []
        return [
            ("string", "och_sep_ss1.smcSramBackdoorFile", str(Path(self.smc_sram_image).resolve()))
        ]

    def fuse_overrides(self) -> List[Override]:
        return fuses.load(self.otp) if self.otp else []

    def overrides(self) -> List[Override]:
        """All run-specific overrides (straps + fuses + caller extras).

        Absolute path overrides (targets/configFile) are added by the backend,
        which knows the platform paths; they are kept out of SimConfig on purpose.
        """
        return [
            *self.strap_overrides(),
            *self.smc_overrides(),
            *self.fuse_overrides(),
            *self.extra_ini,
        ]

    def __str__(self):
        return (
            f"SimConfig(name={self.name}, elf={self.elf}, boot={self.boot}, "
            f"recovery={self.recovery}, rotate_update={self.rotate_update}, "
            f"flash={self.flash_image}, otp={self.otp}, "
            f"sim_out={self.sim_out}, sep_status={self.sep_status})"
        )

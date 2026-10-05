# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SimConfig — declarative inputs for one sep-vp run.

Mirrors the example harness's ``SimConfig`` but adapted to sep-vp's control surface:
boot straps and channel toggles map to ``och_sep_ss1.*`` CCI bools, the OTP fuse-map is a
YAML file, and the SPI flash is a prebuilt raw ``.bin``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

from sepvp import fuses
from sepvp.inifile import Override

# friendly boot mode -> primary_chiplet bool
_BOOT_MODES = ("primary", "secondary")

PathLike = Union[str, Path]

# SMC SRAM window size; the model refuses a staged image past it.
SMC_SRAM_SIZE_BYTES = 0x100000
# Default smcSramBackdoorOffset in the model, also the MANIFEST_ADDR it publishes.
SMC_SRAM_DEFAULT_OFFSET = 0x2000


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
    # Raw OCA bundle (not a combined SPI image) staged into the SMC SRAM window for boots that
    # take the manifest from the SMC; the offset defaults to the model's.
    smc_sram_image: Optional[PathLike] = None
    smc_sram_offset: Optional[int] = None
    # --- boot straps (och_sep_ss1.smc.*) ---
    boot: str = "secondary"  # "primary" (SPI boot) | "secondary" (wait SMC)
    recovery: bool = False  # boot_recovery: wait for SMC manifest (implies primary)
    rotate_update: bool = False  # use rotated (backup) manifest slot
    bl0_pll_clk: bool = False  # init PLL from fuses vs refclk
    status_report_disable: bool = False  # skip status-ring init (also suppresses SEP_STATUS)
    # --- decoded-output channels ---
    sim_out: bool = True  # [SIM_OUT] debug console (DEBUG firmware builds only)
    sep_status: bool = True  # [SEP_STATUS] production status decoder
    iss_trace: bool = False  # write the ISS instruction trace to <run dir>/veer_trace.log
    # --- misc ---
    boot_timeout: int = 120  # seconds; sep-vp never self-terminates
    init_writes: List[Tuple[int, int]] = field(default_factory=list)  # ordered pre-boot deposits
    extra_ini: List[Override] = field(default_factory=list)  # raw (section, key, value) overrides

    def __post_init__(self):
        if self.boot not in _BOOT_MODES:
            raise ValueError(f"boot must be one of {_BOOT_MODES}, got {self.boot!r}")
        if self.smc_sram_image is not None:
            if self.smc_sram_offset is not None:
                if type(self.smc_sram_offset) is not int or not (
                    0 <= self.smc_sram_offset < SMC_SRAM_SIZE_BYTES
                ):
                    raise ValueError(
                        "smc_sram_offset must lie inside the 1 MiB SMC SRAM window, got "
                        f"{self.smc_sram_offset!r}"
                    )
                if self.smc_sram_offset % 4:
                    raise ValueError(
                        "smc_sram_offset must be 4-byte aligned; the ROM DMAs the manifest "
                        f"from it, got 0x{self.smc_sram_offset:x}"
                    )
            if self.boot == "primary" and not self.recovery:
                raise ValueError(
                    "smc_sram_image needs a boot that reads the SMC window: a primary "
                    "chiplet outside recovery boots from SPI flash and never looks at it"
                )
        for address, value in self.init_writes:
            if type(address) is not int or not 0 <= address <= 0xFFFFFFFF:
                raise ValueError(
                    f"init_writes address must be a 32-bit unsigned integer, got {address!r}"
                )
            if address % 4:
                raise ValueError(f"init_writes address must be 4-byte aligned, got 0x{address:x}")
            if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(
                    f"init_writes value must be a 32-bit unsigned integer, got {value!r}"
                )

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

    def fuse_overrides(self) -> List[Override]:
        return fuses.load(self.otp) if self.otp else []

    def init_write_overrides(self) -> List[Override]:
        """Ordered pre-boot 32-bit deposits as one model string parameter."""
        if not self.init_writes:
            return []
        deposits = ",".join(f"0x{address:08x}=0x{value:08x}" for address, value in self.init_writes)
        return [("string", "och_sep_ss1.init_writes", deposits)]

    def overrides(self) -> List[Override]:
        """Run-specific overrides: straps, fuses, init writes, then caller extras.

        Path overrides (targets, configFile, SPI/SMC backdoor files, traceFile) come from the
        backend, which owns the run directory.
        """
        return [
            *self.strap_overrides(),
            *self.fuse_overrides(),
            *self.init_write_overrides(),
            *self.extra_ini,
        ]

    def __str__(self):
        return (
            f"SimConfig(name={self.name}, elf={self.elf}, boot={self.boot}, "
            f"recovery={self.recovery}, rotate_update={self.rotate_update}, "
            f"flash={self.flash_image}, otp={self.otp}, "
            f"sim_out={self.sim_out}, sep_status={self.sep_status})"
        )

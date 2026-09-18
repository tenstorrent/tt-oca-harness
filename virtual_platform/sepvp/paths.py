# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Locate the sep-vp binary, the base config, and the SEP firmware trees.

All paths are anchored relative to this file's location
(``virtual_platform/sepvp/paths.py``) so the package is import-location
independent. Environment variables override the defaults:

  SEP_VP_BIN     full path to the sep-vp executable
  SEP_VP_BASE_INI  base accellera_config.ini to @include
"""

import os
from pathlib import Path

# virtual_platform/sepvp/paths.py
_THIS = Path(__file__).resolve()
SEPVP_DIR = _THIS.parent  # .../sepvp
VP_DIR = SEPVP_DIR.parent  # .../virtual_platform
OCAH_ROOT = VP_DIR.parent  # repo root (tt-oca-harness)
SIM_DIR = VP_DIR / "tt-oca-harness-model"  # the SystemC platform source (submodule)

# --- sep-vp platform -------------------------------------------------------
VP_BUILD_DIR = SIM_DIR / "vp" / "build"
DEFAULT_SEP_VP_BIN = VP_BUILD_DIR / "bin" / "sep-vp"
CONFIG_DIR = SIM_DIR / "vp" / "platform" / "sep" / "config"
DEFAULT_BASE_INI = CONFIG_DIR / "accellera_config.ini"
VEERISS_CONFIG = CONFIG_DIR / "veeriss_config.json"

# Runtime env script written by `make env` (sourced by the sw/sep-vp-tests run.sh).
ENV_SCRIPT = VP_DIR / "setup_environment.sh"

# --- SEP boot ROM (the production tree) --------------------------------------
BOOTCODE_DIR = OCAH_ROOT / "hw" / "sys" / "sep" / "bootrom" / "prod"
# The SEP VP models the OpenTitan SPI host only (the Cadence xSPI controller is
# closed-source IP, not modeled), so the VP always uses the OpenTitan boot-ROM
# build in build_ot/ (the Makefile's ot-toolchain-images target), never the
# default build/ (Cadence).
BOOTCODE_OT_BUILD_DIR = "build_ot"
BOOTCODE_ELF = BOOTCODE_DIR / BOOTCODE_OT_BUILD_DIR / "boot_rom.elf"
# OCA boot-manifest images (the format the ROM parses). Raw .bin rather than
# .spi_preload: these are oca-combined SPI images placing the bundle at the slot
# offsets the ROM reads, and SimConfig(flash_image=...) wants the raw form.
# Built by `make -C <bootrom> oca-images`.
OCA_NS_IMAGE = BOOTCODE_DIR / "build" / "oca_non_secure_boot.bin"
OCA_SEC_IMAGE = BOOTCODE_DIR / "build" / "oca_secure_boot.bin"
OCA_ENC_IMAGE = BOOTCODE_DIR / "build" / "oca_encrypted_boot.bin"
OCA_OTP_IMAGE = BOOTCODE_DIR / "build" / "oca_otp_key_boot.bin"
# A bare bundle, for the SMC-SRAM path (see SimConfig.smc_sram_image).
OCA_SMC_BUNDLE = BOOTCODE_DIR / "build" / "oca_smc_bundle.bin"
OCA_ID_IMAGE = BOOTCODE_DIR / "build" / "oca_identity_boot.bin"
OCA_PQC_IMAGE = BOOTCODE_DIR / "build" / "oca_pqc_boot.bin"
OCA_ECDSA_IMAGE = BOOTCODE_DIR / "build" / "oca_ecdsa_boot.bin"
OCA_DER_IMAGE = BOOTCODE_DIR / "build" / "oca_der_boot.bin"
OCA_AES128_IMAGE = BOOTCODE_DIR / "build" / "oca_aes128_boot.bin"
OCA_SIP_KEY_IMAGE = BOOTCODE_DIR / "build" / "oca_sip_key_boot.bin"
OCA_MULTI_IMAGE = BOOTCODE_DIR / "build" / "oca_multi_image_boot.bin"
OCA_NO_BL1_IMAGE = BOOTCODE_DIR / "build" / "oca_no_bl1_boot.bin"
# ROM key slots 1-5, one image per slot, each signed by its own key. Slot 0 is
# OCA_SEC_IMAGE above (ROM key 0), so the six together cover every digest
# key_digests.c pins. Indexed by slot number so a test can parametrise over
# range(6) without a name-to-slot table.
OCA_ROM_KEY_IMAGES = {
    0: OCA_SEC_IMAGE,
    **{n: BOOTCODE_DIR / "build" / f"oca_rom_key{n}_boot.bin" for n in range(1, 6)},
}

# --- SEP DV firmware engine ---------------------------------------------------
# Tests live in hw/sys/sep/dv/fw/tests/ and are built by the shared engine
# (`make ocah-dv-fw-tests TARGET=sep TEST=<name>` at the repo root).
FW_DIR = OCAH_ROOT / "hw" / "sys" / "sep" / "dv" / "fw"
FW_TESTS_DIR = FW_DIR / "tests"
FW_TEST_BUILD_DIR = FW_DIR / "build" / "tests"

# Default per-run working-directory root (logs + staged artifacts land here).
LOGS_DIR = VP_DIR / "logs" / "sepvp"


def default_riscv_toolchain() -> str:
    """Optional RISC-V cross-toolchain prefix for firmware builds.

    Honors the RISCV_TOOLCHAIN environment variable; empty means "use whatever
    is already on PATH" (the plugin's --riscv-toolchain option and all consumers
    tolerate an empty value, and ROM/DV builds fall back to the ocah-toolchain
    container regardless)."""
    return os.environ.get("RISCV_TOOLCHAIN", "")


def sep_vp_bin() -> Path:
    """Path to the sep-vp executable (env SEP_VP_BIN wins)."""
    return Path(os.environ.get("SEP_VP_BIN", DEFAULT_SEP_VP_BIN))


def base_ini() -> Path:
    return Path(os.environ.get("SEP_VP_BASE_INI", DEFAULT_BASE_INI))


def fw_test_elf(test_name: str) -> Path:
    """Where the DV firmware engine drops a test ELF (default link mode: tcm)."""
    return FW_TEST_BUILD_DIR / test_name / f"{test_name}.tcm.elf"


def vp_env() -> dict:
    """Environment for launching sep-vp.

    sep-vp runs standalone: libsystemc resolves via RPATH and Boost/CCI/OpenSSL are
    static. The caller's environment is the contract — whoever built sep-vp with a
    non-default toolchain is responsible for having its runtime (LD_LIBRARY_PATH or
    an activated toolset shell) in the environment pytest/the CLI runs under.
    """
    return dict(os.environ)

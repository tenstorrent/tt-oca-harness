# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse/OTP and clock-control representative CSR precheck."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py), same import pattern
# as smc_cpu_to_sep_axi_test_seq.
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT,
)

# ``_REPO`` / ``_field_mask`` come from the authoritative-map module:
# it is the single place that knows the repo layout and how to read a generated
# PeakRDL C header, and the chip_config block resets live in a block header
# (misc_wrap.h) that ``smc_addr_map`` exposes no named accessor for.
from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import prove_efuse_bank_axil_activity

_MISC_WRAP_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "misc_wrap.h"


def _chip_config_reset(field: str) -> int:
    """RDL reset of a chip_config field from generated ``misc_wrap.h``."""
    return _field_mask(_MISC_WRAP_H, f"CHIP_CONFIG__{field}__{field}_reset")


CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)  # base_config offset 0x18
# Whole-register reset default from the generated PeakRDL Python map, so a field
# the next regeneration adds is included; the baseline CLOCK_GATE_CONTROL read
# is value-checked against it like every other access in this sequence.
CLOCK_GATE_CONTROL_RESET = SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT

# Every proof-path address is imported by per-register symbol from the generated
# PeakRDL map (hw/sys/smc/regs/gen/c/smc_addr.h) -- no base+offset arithmetic, so
# a regenerated map cannot silently move a read off its logged register. Expected
# values come from the generated block header (misc_wrap.h) rather than hand
# literals, so address and value share one regenerated source.
#
# CHIP_ID carries an exact expectation: misc_wrap.h defines
# CHIP_CONFIG__CHIP_ID__CHIP_ID_reset = 0x0 (chip_config.rdl ``chip_id = 0x0``).
# No document states the chip identifier of this reference integration, so the
# bench takes the RDL reset as the expected value, a DV-owned fact: an
# integration that publishes another identifier fails here and is reported.
CHIP_CONFIG_READS = [
    (
        "CHIP_CONFIG_VERSION_LO",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR"),
        _chip_config_reset("VERSION_LO"),
    ),
    (
        "CHIP_CONFIG_VERSION_HI",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR"),
        _chip_config_reset("VERSION_HI"),
    ),
    (
        "CHIP_CONFIG_CHIP_ID",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR"),
        _chip_config_reset("CHIP_ID"),
    ),
]


class smc_efuse_otp_clock_test_seq(SmcCsrSeq):
    """Use chip-config fields as the eFuse/OTP observable proxy."""

    def __init__(self, name: str = "smc_efuse_otp_clock_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # Leg 1 (positive control): make the eFuse-bank AXI-Lite activity probe
        # read 1 under real frontdoor stimulus, so the idle == 0 re-check that
        # check_efuse_otp_observability() runs after this body is a live
        # measurement rather than a stuck-at-0 pass.
        await prove_efuse_bank_axil_activity(self)

        # The baseline read carries the generated reset expectation, so it is a
        # value check as well as the reference for the stability re-check below.
        clock_gate = await self.csr_read(
            "CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=CLOCK_GATE_CONTROL_RESET
        )
        await self.csr_read_many(CHIP_CONFIG_READS)
        await self.csr_read("CLOCK_GATE_CONTROL_RECHECK", CLOCK_GATE_CONTROL, expected=clock_gate)
        assert self.accesses == len(CHIP_CONFIG_READS) + 3, "eFuse proxy read mismatch"
        # Every access above passed `expected` to the scoreboard, which fails
        # the run on any rdata mismatch.
        cocotb.log.info(
            "CHK-EFUSE-OTP-CSR: %d SEP_IN AXI accesses completed OKAY and every "
            "one was exact-compared against a generated-map expected value "
            "(eFuse-shim probe + CLOCK_GATE_CONTROL reset default and stability "
            "re-check + %d chip-config reads incl. CHIP_ID)",
            self.accesses,
            len(CHIP_CONFIG_READS),
        )

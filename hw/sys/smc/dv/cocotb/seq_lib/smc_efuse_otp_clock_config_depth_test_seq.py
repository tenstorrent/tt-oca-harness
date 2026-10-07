# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse/OTP observable clock-config depth test over real SEP_IN AXI.

Two legs, and only the first is a closure claim:

1. **CLOCK_GATE_CONTROL RW depth** (fail-capable, real DUT RTL) -- save, write a
   pattern, read back under a mask, restore, and re-read against the saved
   value. Evidence: ``CHK-EFUSE-CLOCK-GATE-DEPTH``.
2. **CHIP_CONFIG proxy reads** -- fuse-derived mirror registers. ``VERSION_LO`` /
   ``VERSION_HI`` carry their generated RDL resets; ``CHIP_ID`` and ``LC_STATE``
   are observed only (see below).

This sequence also runs :func:`prove_efuse_bank_axil_activity` before the
bounded OTP work. Without it the test's ``tb_axil_efuse_bank_active == 0``
idle assertion in ``check_efuse_otp_observability`` cannot distinguish a
genuinely idle eFuse bank from a dead probe, and the helper logs a WARNING
saying so rather than emitting ``CHK-EFUSE-BANK-IDLE``
([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import prove_efuse_bank_axil_activity

CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)  # base_config offset 0x18
CLOCK_GATE_PATTERN = (1 << 8) | (1 << 11) | (1 << 12)
CLOCK_GATE_MASK = 0x0000_1FFF

_CHIP_CONFIG_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "chip_config.h"
_CHIP_CONFIG = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")

# Generated RDL resets, imported by symbol rather than hand-copied
# ([ADDRESS-FROM-AUTHORITATIVE-MAP]) from chip_config.h, generated from
# hw/sys/smc/regs/blocks/chip_config/chip_config.rdl.
VERSION_LO_RESET = _field_mask(_CHIP_CONFIG_H, "CHIP_CONFIG__VERSION_LO__VERSION_LO_reset")
VERSION_HI_RESET = _field_mask(_CHIP_CONFIG_H, "CHIP_CONFIG__VERSION_HI__VERSION_HI_reset")

# CHIP_ID / LC_STATE are fuse-derived mirrors whose expected
# content is not published in any artifact this bench can read, so they carry no
# expectation and are OBSERVED ONLY -- they prove decode/reachability, nothing
# about their content ([EXACT-EXPECTATION]).
EFUSE_PROXY_READS = [
    ("CHIP_CONFIG_VERSION_LO", _CHIP_CONFIG, VERSION_LO_RESET),
    ("CHIP_CONFIG_VERSION_HI", _CHIP_CONFIG + 0x4, VERSION_HI_RESET),
    ("CHIP_CONFIG_CHIP_ID_OBSERVED_ONLY", _CHIP_CONFIG + 0x8, None),
    ("CHIP_CONFIG_LC_STATE_OBSERVED_ONLY", _CHIP_CONFIG + 0xC, None),
]


class smc_efuse_otp_clock_config_depth_test_seq(SmcCsrSeq):
    """Fuse observability proxies plus clock-gate RW depth."""

    def __init__(self, name: str = "smc_efuse_otp_clock_config_depth_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def body(self) -> None:
        # Positive control for the idle leg the testcase asserts afterwards.
        # One extra SEP_IN AXI access, value-checked against the RDL reset of
        # the eFuse-shim register it reads.
        await prove_efuse_bank_axil_activity(self)

        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_read_many(EFUSE_PROXY_READS)

        pattern = (original & ~CLOCK_GATE_MASK) | CLOCK_GATE_PATTERN
        await self.csr_write("CLOCK_GATE_CONTROL_PATTERN", CLOCK_GATE_CONTROL, pattern)
        got = await self.csr_read("CLOCK_GATE_CONTROL_PATTERN", CLOCK_GATE_CONTROL)
        assert (got & CLOCK_GATE_MASK) == CLOCK_GATE_PATTERN, (
            f"clock gate readback 0x{got:x} does not match mask 0x{CLOCK_GATE_MASK:x}"
        )
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original)
        restored = await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=original
        )

        # The written pattern must actually differ from the saved value inside
        # the mask, or "wrote it, read it back" would hold on a register that
        # ignores writes entirely.
        assert (original & CLOCK_GATE_MASK) != CLOCK_GATE_PATTERN, (
            "CLOCK_GATE_CONTROL already held the probe pattern "
            f"0x{CLOCK_GATE_PATTERN:x} inside mask 0x{CLOCK_GATE_MASK:x} before "
            "the write, so the RW-depth leg cannot discriminate a writable "
            "register from a read-only one"
        )

        # `accesses == expected` alone is loop integrity: every helper bumps it
        # regardless of what the DUT did ([NO-ALWAYS-PASS-CHECKER]).
        # `assert_all_reachable` adds the scoreboard cross-check that carries
        # the claim.
        expected_accesses = len(EFUSE_PROXY_READS) + 6
        self.assert_all_reachable(expected_accesses, "EFUSE_OTP_CLOCK_CONFIG")

        cocotb.log.info(
            "CHK-EFUSE-CLOCK-GATE-DEPTH: SMC_BASE_CONFIG.CLOCK_GATE_CONTROL "
            "@0x%08x save=0x%08x -> wrote 0x%08x -> read 0x%08x "
            "(masked 0x%05x == pattern 0x%05x under mask 0x%08x) -> restored "
            "and re-read 0x%08x == save",
            CLOCK_GATE_CONTROL,
            original,
            pattern,
            got,
            got & CLOCK_GATE_MASK,
            CLOCK_GATE_PATTERN,
            CLOCK_GATE_MASK,
            restored,
        )
        self.chk_seen.add("CHK-EFUSE-CLOCK-GATE-DEPTH")

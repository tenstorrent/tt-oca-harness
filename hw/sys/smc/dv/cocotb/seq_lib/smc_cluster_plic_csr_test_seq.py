# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster PLIC CSR and pending-path test.

The cluster PLIC had no enrolled coverage at all. Nothing in the package read
one of its registers: `smc_hang_detector_plic_route_test` checks the IRQ route
through testbench probes and reads no PLIC register, and `smc_clint_csr_test`
is a CLINT test and is not enrolled. The aperture is `0xC400_0000`, 2 MB
(`smc_reg.py` `SMC_CLUSTER_PLIC_REG_MAP_*`), and it is reachable over SEP_IN
AXI -- it is not inside the `0xC8xx_xxxx` cluster-local window that #1237
folds, which is why this is a plain CSR test and not a deferred one.

Four properties, and the last one is what makes the others worth having.

**Context independence.** The PLIC has eight interrupt contexts -- four cores
times MEIP/SEIP -- each with its own threshold register one 4 KB page apart.
Writing one context's threshold must leave the other seven alone. This design
has two filed aliasing defects already (#585 unmapped registers aliasing onto
live ones, #1237 a whole window folding onto another), so eight same-shaped
registers a page apart is a place where aliasing is plausible rather than
hypothetical. Each context is given a *distinct* value so a readback cannot be
satisfied by the wrong page.

**Source 0 does not exist.** The RISC-V PLIC specification reserves interrupt
ID 0, and its priority register is read-only zero. A write that sticks means
the register file decoded an address the spec says has no storage behind it.

**Pending is read-only to software.** The gateway sets it; software clears by
claiming. A write that sticks is the same class of defect.

**Pending tracks a real interrupt, both directions.** This is the positive
control the rest depend on: without it, every `== 0` read above is satisfied by
a dead aperture that returns zero for everything. The stimulus is the I2C
interrupt path, driven the way `smc_i2c_intr_mask_test` drives it -- set
`INTR_ENABLE.CMD_COMPLETE`, write the `singlepulse` `INTR_TEST` bit -- because
that is a real DUT interrupt with no testbench forcing anywhere in it.
`peripheral_interrupts[23]` is I2C instance 0 (`smc_peripherals.sv:1161`), it
reaches `cpu_interrupts[NUM_EXT_INTERRUPTS + 23]` with
`NUM_EXT_INTERRUPTS = 256` (`smc_4core_cpu_pkg.sv:20`), and a PLIC source ID is
that line index plus one because ID 0 is reserved. So the bit under test is
source 280: `PENDING[8]` bit 24. The expected word and bit are computed from
those constants rather than written as literals, and the whole pending vector
is reported on failure so a wrong mapping is diagnosable instead of opaque.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_0__REG_ADDR,
    SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE0_SEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE1_MEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE1_SEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE2_MEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE2_SEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE3_MEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_CORE3_SEIP_THRESHOLD_REG_ADDR,
    SMC_CLUSTER_PLIC_PENDING_0__REG_ADDR,
    SMC_CLUSTER_PLIC_PRIORITY_0__REG_ADDR,
)

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# The eight interrupt contexts, in the order the register map lays them out.
THRESHOLDS = (
    ("CORE0_MEIP", SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_REG_ADDR),
    ("CORE1_MEIP", SMC_CLUSTER_PLIC_CORE1_MEIP_THRESHOLD_REG_ADDR),
    ("CORE2_MEIP", SMC_CLUSTER_PLIC_CORE2_MEIP_THRESHOLD_REG_ADDR),
    ("CORE3_MEIP", SMC_CLUSTER_PLIC_CORE3_MEIP_THRESHOLD_REG_ADDR),
    ("CORE0_SEIP", SMC_CLUSTER_PLIC_CORE0_SEIP_THRESHOLD_REG_ADDR),
    ("CORE1_SEIP", SMC_CLUSTER_PLIC_CORE1_SEIP_THRESHOLD_REG_ADDR),
    ("CORE2_SEIP", SMC_CLUSTER_PLIC_CORE2_SEIP_THRESHOLD_REG_ADDR),
    ("CORE3_SEIP", SMC_CLUSTER_PLIC_CORE3_SEIP_THRESHOLD_REG_ADDR),
)

PENDING_0 = SMC_CLUSTER_PLIC_PENDING_0__REG_ADDR
PRIORITY_0 = SMC_CLUSTER_PLIC_PRIORITY_0__REG_ADDR
CORE0_MEIP_ENABLE_0 = SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_0__REG_ADDR

# 337 sources -> ceil(337/32) = 11 pending words (PENDING_NUM = 0x0B).
PENDING_WORDS = 11

# I2C instance 0's PLIC source, derived rather than written as a literal.
_PERIPH_IRQ_BASE = 256  # smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS
_I2C0_PERIPH_BIT = 23  # smc_peripherals.sv:1161, peripheral_interrupts[25:23]
I2C0_PLIC_SOURCE = _PERIPH_IRQ_BASE + _I2C0_PERIPH_BIT + 1  # +1: ID 0 reserved
I2C0_PENDING_WORD = I2C0_PLIC_SOURCE // 32
I2C0_PENDING_BIT = I2C0_PLIC_SOURCE % 32

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
I2C_INTR_ENABLE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0)
I2C_INTR_TEST = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_TEST_BASE_ADDR", 0)

_I2C_H = Path(__file__).resolve().parents[6] / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"
CMD_COMPLETE_STATE = _field_mask(_I2C_H, "I2C__INTR_STATE__CMD_COMPLETE_bm")
CMD_COMPLETE_ENABLE = _field_mask(_I2C_H, "I2C__INTR_ENABLE__CMD_COMPLETE_bm")
CMD_COMPLETE_TEST = _field_mask(_I2C_H, "I2C__INTR_TEST__CMD_COMPLETE_bm")

# The IRQ crosses smc_peripherals_cdc's flop and a synchroniser before the
# PLIC gateway. Bounded: expiry is a failure and reports what it last read.
_IRQ_BOUND = 512


class smc_cluster_plic_csr_test_seq(SmcCsrSeq):
    """Cluster PLIC context independence, reserved fields, and pending path."""

    def __init__(self, name: str = "smc_cluster_plic_csr_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def _pending(self) -> list[int]:
        return [
            await self.csr_read(f"PLIC_PENDING_{i}", PENDING_0 + 4 * i)
            for i in range(PENDING_WORDS)
        ]

    async def _wait_pending_bit(self, want: int, label: str) -> list[int]:
        """Wait until the I2C source's pending bit reaches `want`."""
        words = await self._pending()
        for _ in range(_IRQ_BOUND // 32):
            words = await self._pending()
            got = (words[I2C0_PENDING_WORD] >> I2C0_PENDING_BIT) & 0x1
            if got == want:
                return words
            await ClockCycles(cocotb.top.clk_smc_i, 32)
        raise AssertionError(
            f"{label}: PLIC source {I2C0_PLIC_SOURCE} "
            f"(PENDING[{I2C0_PENDING_WORD}] bit {I2C0_PENDING_BIT}) never reached "
            f"{want}; full pending vector "
            + " ".join(f"[{i}]=0x{w:08x}" for i, w in enumerate(words))
        )

    async def body(self) -> None:
        # ---- Aperture live: the control the whole test rests on ------------
        # A write/readback with a distinct value on a source the spec says is
        # real. Without it every `== 0` and every "unchanged" read below is
        # satisfied by an aperture that returns zero for everything
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        prio1_pre = await self.csr_read("PLIC_PRIORITY_1_PRE", PRIORITY_0 + 4)
        await self.csr_write("PLIC_PRIORITY_1_WR", PRIORITY_0 + 4, 0x5)
        prio1 = await self.csr_read("PLIC_PRIORITY_1_RB", PRIORITY_0 + 4)
        assert prio1 == 0x5, (
            f"CHK-PLIC-APERTURE-LIVE: PRIORITY[1] read 0x{prio1:x} after writing "
            f"0x5 (was 0x{prio1_pre:x}). The cluster PLIC aperture at "
            f"0x{PRIORITY_0:08x} does not hold a written value, so nothing else "
            f"in this test could be attributed to the DUT"
        )
        await self.csr_write("PLIC_PRIORITY_1_RESTORE", PRIORITY_0 + 4, prio1_pre)
        cocotb.log.info(
            "CHK-PLIC-APERTURE-LIVE: PRIORITY[1] held 0x5 and was restored to 0x%x",
            prio1_pre,
        )
        self.chk_seen.add("CHK-PLIC-APERTURE-LIVE")

        # ---- Source 0 is reserved by the spec -------------------------------
        await self.csr_write("PLIC_PRIORITY_0_WR", PRIORITY_0, 0xFF)
        prio0 = await self.csr_read("PLIC_PRIORITY_0_RB", PRIORITY_0)
        assert prio0 == 0, (
            f"CHK-PLIC-SOURCE0-RESERVED: PRIORITY[0] read 0x{prio0:x} after a "
            f"0xFF write. The RISC-V PLIC specification reserves interrupt ID 0 "
            f"and its priority register is read-only zero, so storage here means "
            f"the register file decoded an address that should have none"
        )
        cocotb.log.info("CHK-PLIC-SOURCE0-RESERVED: PRIORITY[0] stayed 0 through a 0xFF write")
        self.chk_seen.add("CHK-PLIC-SOURCE0-RESERVED")

        # ---- Enable words are storage ---------------------------------------
        enable_pre = await self.csr_read("PLIC_CORE0_MEIP_EN0_PRE", CORE0_MEIP_ENABLE_0)
        pattern = 0xA5A5_5A5A
        await self.csr_write("PLIC_CORE0_MEIP_EN0_WR", CORE0_MEIP_ENABLE_0, pattern)
        enable_rb = await self.csr_read("PLIC_CORE0_MEIP_EN0_RB", CORE0_MEIP_ENABLE_0)
        assert enable_rb == pattern, (
            f"CHK-PLIC-ENABLE-RW: CORE0_MEIP_ENABLE[0] read 0x{enable_rb:08x} "
            f"after writing 0x{pattern:08x} (was 0x{enable_pre:08x})"
        )
        await self.csr_write("PLIC_CORE0_MEIP_EN0_RESTORE", CORE0_MEIP_ENABLE_0, enable_pre)
        cocotb.log.info(
            "CHK-PLIC-ENABLE-RW: CORE0_MEIP_ENABLE[0] held 0x%08x and was restored to 0x%08x",
            pattern,
            enable_pre,
        )
        self.chk_seen.add("CHK-PLIC-ENABLE-RW")

        # ---- Pending is read-only to software -------------------------------
        pend_pre = await self._pending()
        await self.csr_write("PLIC_PENDING_0_WR", PENDING_0, 0xFFFF_FFFF)
        pend_post = await self.csr_read("PLIC_PENDING_0_RB", PENDING_0)
        assert pend_post == pend_pre[0], (
            f"CHK-PLIC-PENDING-RO: PENDING[0] changed from 0x{pend_pre[0]:08x} to "
            f"0x{pend_post:08x} on a software write. The gateway owns this "
            f"register; software clears by claiming"
        )
        cocotb.log.info(
            "CHK-PLIC-PENDING-RO: PENDING[0] stayed 0x%08x through an all-ones write",
            pend_pre[0],
        )
        self.chk_seen.add("CHK-PLIC-PENDING-RO")

        # ---- Pending tracks a real interrupt, both directions ---------------
        # The positive control every `== 0` read above depends on. Stimulus is
        # the I2C interrupt path, no testbench forcing.
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        state0 = await self.csr_read("I2C_INTR_STATE_PRE", I2C_INTR_STATE)
        if state0 & CMD_COMPLETE_STATE:
            await self.csr_write("I2C_INTR_STATE_W1C_PRE", I2C_INTR_STATE, CMD_COMPLETE_STATE)
        before = await self._wait_pending_bit(0, "pending idle pre-check")

        await self.csr_write("PLIC_I2C_SOURCE_PRIORITY", PRIORITY_0 + 4 * I2C0_PLIC_SOURCE, 1)
        await self.csr_write("I2C_INTR_ENABLE_SET", I2C_INTR_ENABLE, CMD_COMPLETE_ENABLE)
        await self.csr_write("I2C_INTR_TEST_FIRE", I2C_INTR_TEST, CMD_COMPLETE_TEST)
        after = await self._wait_pending_bit(1, "pending set on I2C interrupt")
        cocotb.log.info(
            "CHK-PLIC-PENDING-SET-ON-IRQ: a real I2C CMD_COMPLETE interrupt set "
            "PLIC source %d (PENDING[%d] bit %d): 0x%08x -> 0x%08x. Source id "
            "derived from NUM_EXT_INTERRUPTS=%d + peripheral_interrupts[%d] + 1",
            I2C0_PLIC_SOURCE,
            I2C0_PENDING_WORD,
            I2C0_PENDING_BIT,
            before[I2C0_PENDING_WORD],
            after[I2C0_PENDING_WORD],
            _PERIPH_IRQ_BASE,
            _I2C0_PERIPH_BIT,
        )
        self.chk_seen.add("CHK-PLIC-PENDING-SET-ON-IRQ")

        # And down again, so the set leg cannot be satisfied by a stuck bit.
        await self.csr_write("I2C_INTR_STATE_W1C", I2C_INTR_STATE, CMD_COMPLETE_STATE)
        cleared = await self._wait_pending_bit(0, "pending clear after I2C W1C")
        cocotb.log.info(
            "CHK-PLIC-PENDING-CLEAR-ON-W1C: clearing the I2C source dropped PENDING[%d] to 0x%08x",
            I2C0_PENDING_WORD,
            cleared[I2C0_PENDING_WORD],
        )
        self.chk_seen.add("CHK-PLIC-PENDING-CLEAR-ON-W1C")

        await self.csr_write("I2C_INTR_ENABLE_RESTORE", I2C_INTR_ENABLE, 0)
        await self.csr_write(
            "PLIC_I2C_SOURCE_PRIORITY_RESTORE", PRIORITY_0 + 4 * I2C0_PLIC_SOURCE, 0
        )
        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        # ---- Context independence -------------------------------------------
        # Distinct value per context, so a readback cannot be satisfied by
        # another context's page.
        wrote: dict[str, int] = {}
        for idx, (name, addr) in enumerate(THRESHOLDS):
            value = idx + 1
            await self.csr_write(f"PLIC_{name}_THRESHOLD", addr, value)
            wrote[name] = value
        mismatched = []
        for name, addr in THRESHOLDS:
            got = await self.csr_read(f"PLIC_{name}_THRESHOLD_RB", addr)
            if got != wrote[name]:
                mismatched.append(f"{name}: wrote {wrote[name]}, read {got}")
        assert not mismatched, (
            "CHK-PLIC-CTX-INDEPENDENT: eight interrupt contexts one 4 KB page "
            "apart did not each hold their own threshold — "
            + "; ".join(mismatched)
            + ". Each was given a distinct value, so this is aliasing between "
            "context pages, the same class as #585 and #1237"
        )
        cocotb.log.info(
            "CHK-PLIC-CTX-INDEPENDENT: all %d contexts held their own distinct threshold (%s)",
            len(THRESHOLDS),
            ", ".join(f"{n}={wrote[n]}" for n, _a in THRESHOLDS),
        )
        self.chk_seen.add("CHK-PLIC-CTX-INDEPENDENT")

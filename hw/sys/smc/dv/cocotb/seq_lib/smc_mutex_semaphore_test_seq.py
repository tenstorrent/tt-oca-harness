# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL MUTEX[0]/MUTEX[1]/SEMA[0] take / deny / release over SEP_IN AXI.

EXPECT-SOURCE (SPEC, not RTL): ``hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl``:

* ``reg MUTEX``, ``field ... mutex[0:0] = 0x1``, desc: "HW mutex.
  Reads will attempt to acquire mutex, 1 on success. If the mutex is already
  acquired, the read will return 0. To release the mutex, write any value to
  the register."  ``MUTEX[4] @ 0x240`` -- four *independent* locks.
* ``reg SEMA``, ``field ... sema[15:0] = 0x0``, desc: "16-bit
  semaphore value to inc/dec. Writing to this register will inc/dec the
  semaphore value. The written value is treated as a signed number using 2s
  compliment."  ``SEMA[4] @ 0x260``.

Every address AND every field mask / reset value below is imported by symbol
from the generated PeakRDL output (``smc_addr.h`` / ``blocks/cpu_ctrl.h``), so
a regenerated map moves the test with it ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import cpu_ctrl_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

MUTEX0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR", 0)
MUTEX1 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR", 1)
SEMA0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SEMA_BASE_ADDR", 0)

# `mutex` is a 1-bit field (bw=1); its reset value IS the "available" encoding
# and the RDL desc gives the only other legal read result as 0 ("already
# acquired").
MUTEX_BM = cpu_ctrl_u32("CPU_CTRL__MUTEX__MUTEX_bm")
MUTEX_FREE = cpu_ctrl_u32("CPU_CTRL__MUTEX__MUTEX_reset")
MUTEX_TAKEN = MUTEX_FREE & ~MUTEX_BM  # the 1-bit field's only other value: 0

SEMA_BM = cpu_ctrl_u32("CPU_CTRL__SEMA__SEMA_bm")
SEMA_RESET = cpu_ctrl_u32("CPU_CTRL__SEMA__SEMA_reset")
# Signed 2s-complement increments applied through the SEMA write port, per the
# RDL desc above. +5 then -5 must return the accumulator to its reset value.
SEMA_STEP = 5
SEMA_STEP_NEG = (-SEMA_STEP) & SEMA_BM

# `MUTEX`/`SEMA` are declared regwidth/accesswidth = 64, but both live fields
# are inside the low 32 bits (mutex[0:0], sema[15:0]) and the SEP_IN AXI CSR
# path in this bench issues 4-byte beats.  A 4-byte access therefore covers the
# whole of each field under test; bits 63:32 hold no field in the RDL and are
# out of scope for this testcase.
ACCESS_BYTES = 4

# Stimulus floor, derived from the body below (loop integrity only -- the
# fail-capable reachability/value evidence is the scoreboard cross-check).
EXPECTED_ACCESSES = 14
# Reads carrying an `expected=`; the scoreboard books one only AFTER an exact
# rdata compare has passed, so a leg that lost its `expected=` fails here.
EXPECTED_VALUE_CHECKS = 9


class smc_mutex_semaphore_test_seq(SmcCsrSeq):
    """MUTEX[0] take/deny/release, MUTEX[1] independence, SEMA[0] accumulate."""

    def __init__(self, name: str = "smc_mutex_semaphore_test_seq") -> None:
        super().__init__(name)
        # Measured DUT reads, published for the testcase-level gate. `None`
        # means "never sampled" and fails that gate -- these are never
        # pre-seeded with the expected value.
        self.take = None
        self.deny = None
        self.free_after_release = None
        self.nbr_free_while_held = None
        self.nbr_held_after_release = None
        self.nbr_free_after_own_release = None
        self.sema_reset = None
        self.sema_inc = None
        self.sema_dec = None
        self.value_checks = 0

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        # ---- MUTEX[0]: acquire ----
        self.take = await self.csr_read(
            "MUTEX0_TAKE", MUTEX0, expected=MUTEX_FREE, length=ACCESS_BYTES
        )
        cocotb.log.info(
            "CHK-MUTEX-TAKE: MUTEX[0] read 0x%x == free 0x%x (now acquired)",
            self.take,
            MUTEX_FREE,
        )

        # ---- MUTEX[0]: deny while held ----
        self.deny = await self.csr_read(
            "MUTEX0_HELD", MUTEX0, expected=MUTEX_TAKEN, length=ACCESS_BYTES
        )
        cocotb.log.info(
            "CHK-MUTEX-HELD: MUTEX[0] read 0x%x == taken 0x%x while held",
            self.deny,
            MUTEX_TAKEN,
        )

        # ---- MUTEX[1]: the neighbouring lock is a *different* lock ----
        # If the four indices aliased onto one bit (address-decode or genvar
        # collapse) this read would return `taken` and fail here.
        self.nbr_free_while_held = await self.csr_read(
            "MUTEX1_TAKE", MUTEX1, expected=MUTEX_FREE, length=ACCESS_BYTES
        )
        cocotb.log.info(
            "CHK-MUTEX-NEIGHBOUR-FREE: MUTEX[1] read 0x%x == free 0x%x while "
            "MUTEX[0] is held (locks are independent, not aliased)",
            self.nbr_free_while_held,
            MUTEX_FREE,
        )

        # ---- release MUTEX[0]; MUTEX[1] must be untouched by it ----
        await self.csr_write("MUTEX0_RELEASE", MUTEX0, 1, length=ACCESS_BYTES)
        self.free_after_release = await self.csr_read(
            "MUTEX0_FREE", MUTEX0, expected=MUTEX_FREE, length=ACCESS_BYTES
        )
        cocotb.log.info(
            "CHK-MUTEX-REL: write released MUTEX[0]; read 0x%x == free 0x%x",
            self.free_after_release,
            MUTEX_FREE,
        )
        self.nbr_held_after_release = await self.csr_read(
            "MUTEX1_STILL_HELD", MUTEX1, expected=MUTEX_TAKEN, length=ACCESS_BYTES
        )
        cocotb.log.info(
            "CHK-MUTEX-NEIGHBOUR-HOLD: MUTEX[1] read 0x%x == taken 0x%x after "
            "the MUTEX[0] release (a release does not free its neighbours)",
            self.nbr_held_after_release,
            MUTEX_TAKEN,
        )

        # Restore both locks to their reset (available) state.
        await self.csr_write("MUTEX1_RELEASE", MUTEX1, 1, length=ACCESS_BYTES)
        self.nbr_free_after_own_release = await self.csr_read(
            "MUTEX1_FREE", MUTEX1, expected=MUTEX_FREE, length=ACCESS_BYTES
        )
        await self.csr_write("MUTEX0_RESTORE", MUTEX0, 1, length=ACCESS_BYTES)

        # ---- SEMA[0]: signed accumulate ----
        self.sema_reset = await self.csr_read(
            "SEMA0_RESET", SEMA0, expected=SEMA_RESET, length=ACCESS_BYTES
        )
        await self.csr_write("SEMA0_INC", SEMA0, SEMA_STEP, length=ACCESS_BYTES)
        self.sema_inc = await self.csr_read(
            "SEMA0_AFTER_INC",
            SEMA0,
            expected=SEMA_RESET + SEMA_STEP,
            length=ACCESS_BYTES,
        )
        await self.csr_write("SEMA0_DEC", SEMA0, SEMA_STEP_NEG, length=ACCESS_BYTES)
        self.sema_dec = await self.csr_read(
            "SEMA0_AFTER_DEC", SEMA0, expected=SEMA_RESET, length=ACCESS_BYTES
        )
        cocotb.log.info(
            "CHK-SEMA-ACCUMULATE: SEMA[0] 0x%x -(+%d)-> 0x%x -(-%d)-> 0x%x "
            "(signed 2s-complement inc/dec, rdl:283-293)",
            self.sema_reset,
            SEMA_STEP,
            self.sema_inc,
            SEMA_STEP,
            self.sema_dec,
        )

        # ---- Reconciliation: the compares must have reached a real checker ----
        # Loop integrity + scoreboard cross-check: `assert_all_reachable`
        # requires the scoreboard to have checked at least as many SYS AXI items
        # as this sequence issued, which the sequence's own counter cannot see
        # ([NO-ZERO-ACTIVITY-PASS]). A no-response raises in the AXI driver, so
        # no timeout count is asserted here.
        self.assert_all_reachable(EXPECTED_ACCESSES, "CPU_CTRL MUTEX/SEMA")
        sb = self.env.scoreboard
        # Fail-capable value floor: the scoreboard books a value check only
        # after an exact rdata compare has passed, so dropping one `expected=`
        # (which would silently delete that leg's compare) fails HERE.
        self.value_checks = sb.sys_axi_value_checks_seen
        assert self.value_checks >= EXPECTED_VALUE_CHECKS, (
            f"expected {EXPECTED_VALUE_CHECKS} value-checked SEP_IN AXI reads "
            f"(MUTEX[0] take/deny/free, MUTEX[1] free/held/free, SEMA[0] "
            f"reset/inc/dec), scoreboard saw {self.value_checks}"
        )
        cocotb.log.info(
            "CHK-MUTEX-BASIC: mutex0 take=0x%x deny=0x%x free=0x%x | "
            "mutex1 free_while_m0_held=0x%x held_after_m0_rel=0x%x free=0x%x | "
            "sema0 reset=0x%x inc=0x%x dec=0x%x | "
            "scoreboard value_checks=%d (>= %d)",
            self.take,
            self.deny,
            self.free_after_release,
            self.nbr_free_while_held,
            self.nbr_held_after_release,
            self.nbr_free_after_own_release,
            self.sema_reset,
            self.sema_inc,
            self.sema_dec,
            self.value_checks,
            EXPECTED_VALUE_CHECKS,
        )

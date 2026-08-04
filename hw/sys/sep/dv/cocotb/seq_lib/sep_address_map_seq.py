# SPDX-License-Identifier: Apache-2.0
"""Sequence for sep_address_map_test.

Full sweep of every sep_cpu_ctrl register (base 0x10A3_0000) over the CPU LSU bus:
  * READ_CHECK  — read each register, verify its reset value (decode + reset cov).
  * READ_ONLY   — read hw-driven / non-deterministic registers (resp-check only).
  * REF_COUNTER — read both REFERENCE_COUNTER words and log the observed value.
  * BASE_ADDR_RW — write/read/restore SEP base/size CSRs used by the local remap.
  * WRITE_READBACK — write a pattern to pure-RW scratch/threshold regs, read it
                     back masked to the register's implemented fields, then
                     restore the reset value (write-path coverage).
  * WRITE_ONLY  — write a benign value to write-only (sw=w) regs (decode + write
                  path); they cannot be read back.

followed by a SEP-local fabric walk that ports the OCAH sep_address_map_test
(which runs sep_reg_walk_seq) to the LSU-reachable, OSS-clean subset: one defined,
readable CSR per block — Secure DMA, WDT, cold/warm scratch, reset_ctrl, OTBN, AES,
HMAC, KMAC, CSRNG, EDN, entropy source, lifecycle ctrl, KM mailbox, eFuse shadow,
AXI-lite mailbox, alias-remap, output-remap, and the OpenTitan SPI host —
confirming every block decodes on the LSU bus.

Expected values are SOURCE-DERIVED, never hardcoded (AGENTS.md §7). Offsets,
reset values, and implemented-field masks all come from `env/sep_reg_meta.py`,
which reads the generated `hw/sys/sep/regs/gen/py/sep_reg.py` export of the
SystemRDL. Only the write PATTERNS and the fabric-walk block addresses are
literals here: the patterns are deliberately chosen stimulus, and the walk's
addresses encode a per-block editorial choice of "one safe, readable CSR" that no
generated symbol expresses. Blocks whose reset value IS exported
(reset_ctrl/OTBN/HMAC/KMAC) take it from the header.

Accepted scope delta — CLOCK_GATE_CTRL ungating:
    An earlier revision of this sequence ungated per-block CSR clocks
    (dma[1], mailbox[2], alias_remap[7], entropy_fifo[10]) before the fabric
    walk. Those fields do not exist in this repository's RDL: sep_cpu_ctrl.rdl
    declares CLOCK_GATE_CTRL as a placeholder with a single implemented bit
    (`pka_cg_enable[0:0]`, reset 0) and documents it as "not yet implemented".
    There is therefore nothing to ungate — every walked block is unconditionally
    clocked in this build, which the walk itself proves by responding. The
    write-path coverage that step provided is preserved: CLOCK_GATE_CTRL is still
    written with its full implemented mask, read back, and restored.

Most side-effecting registers are deliberately NOT written. The only address-aperture
exception is the SEP local/global base/size triplet: it is write/read/restored
immediately to close the CPU-control CSR write-path gap, before the fabric walk
runs. SMU base/size remain reset-checked only. woset LOCK regs are never written
because they would latch permanently. The scoreboard checks the AXI response on
every access and the value on every checked read.

This goes beyond OCAH's reg-walk: it runs on the external AXI master, which cannot
reach SW_RESET_N (so OCAH delegates the reset controller to a directed test). The
CPU LSU master reaches it, so we value-verify SW_RESET_N's reset value directly.
"""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from sep_reg_meta import HMAC, KMAC, OTBN, SEP_CPU_CTRL, SEP_RESET_CTRL

BASE = 0x10A3_0000

# Register names read and value-checked against their generated reset value.
# Never written.
READ_CHECK = [
    "CLOCK_GATE_CTRL",
    "TIMEOUT_INTERRUPT",
    "PKA_CTRL",
    # Remaining TIMEOUT_COUNT_* counters (DMA/SYS_IN are in WRITE_READBACK).
    "TIMEOUT_COUNT_MAILBOX_INBOUND",
    "TIMEOUT_COUNT_MAILBOX_OUTBOUND",
    "TIMEOUT_COUNT_ENTROPY_WRITE",
    "TIMEOUT_COUNT_ENTROPY_READ",
    "TIMEOUT_COUNT_FILTER_OUT",
    "TIMEOUT_COUNT_ALIAS_REMAP",
    "SEP_GLOBAL_BASE_ADDR",
    "SEP_LOCAL_BASE_ADDR",
    "SEP_REGION_SIZE",
    "SMU_GLOBAL_BASE_ADDR",
    "SMU_REGION_SIZE",
    "SMC_FUSE_SENSE_STATUS",
    "SEP_STRAPS",
    # Field-packed reset (0xC000_0100) — value-checked here rather than
    # resp-only, now that the reset comes from the generated header instead of a
    # hand-copied literal. Stronger than the previous resp-only check.
    "SEP_NMI_VEC",
    "SEP_NMI_VEC_LOCK",
    "EXT_TRNG_SRC_SEL",
    "EXT_TRNG_SRC_SEL_LOCK",
    "SEP_VERSION_ID",
]

# (name, why) — value is hw-driven / non-deterministic, so the RDL reset is not
# what the DUT presents. Check the AXI response (decode reachable) only.
READ_ONLY = [
    ("REFERENCE_COUNTER", "free-running counter on clk_ref_i"),
    ("SEP_TEST_CTRL", "hw-driven straps (e.g. sep_standalone)"),
    ("SEP_FUSE_SENSE_STATUS", "depends on the +skip_fuse_sense path"),
]

# (name, pattern) — write/read/restore the SEP base/size CSRs early, before the
# SEP-local fabric walk. Reset values come from the generated header. Patterns are
# chosen distinct from the reset so the R/W check stays non-vacuous. Do not include
# SMU_* here: those are system/outbound routing knobs and stay reset-value checks.
BASE_ADDR_RW = [
    ("SEP_GLOBAL_BASE_ADDR", 0x1234_0000),
    ("SEP_LOCAL_BASE_ADDR", 0xE000_0000),
    ("SEP_REGION_SIZE", 0x2000_0000),
]

# (name, pattern) — pure-RW, no side effects. The readback is compared against
# `pattern & mask` where mask is the register's implemented-field mask from the
# generated header, so a placeholder register that implements one bit today is
# checked honestly instead of against a full 32-bit pattern.
WRITE_READBACK = [
    ("SEP_SW_DEBUG", 0xDEAD_BEEF),
    ("TIMEOUT_COUNT_DMA", 0x0BAD_C0DE),
    ("TIMEOUT_COUNT_SYS_IN", 0xCAFE_F00D),
    ("TIMEOUT_ENABLE", 0x0000_00FF),
    ("RAS_BANK_INFO", 0x0000_00FF),
]

# (name, value) — write-only (sw=w) registers: reading them returns non-OKAY, so
# cover decode + write path with a benign value instead. Inert here because
# TIMEOUT_ENABLE is restored to its reset (the timeout subsystem is disabled), so
# TIMEOUT_CLEAR (write-1-to-clear) clears nothing and TIMEOUT_MODE is unused.
WRITE_ONLY = [
    ("TIMEOUT_CLEAR", 0x0000_0000),
    ("TIMEOUT_MODE", 0x0000_0000),
]

# SEP-local fabric walk (OCAH sep_reg_walk_seq parity): one defined, readable CSR
# per block. expected=None => accessibility only (response must be OKAY, value is
# hw-driven/state-dependent). The chosen offsets match the registers OCAH's
# reg-walk reads. Memory-backed ranges (SRAM/ROM/TCM, OTBN/KMAC mem, KM mem) and
# the OTP-triggering eFuse interface regs (0x1093_04xx+) are NOT probed — they
# would hang. Excluded for OSS hygiene: Cadence xSPI (0x2000_xxxx), the external
# SPI-mux port, and the TRNG wrapper (DWC core is externalized in bare sep).
#
# Blocks whose address AND reset value are exported by the generated header take
# both from it; the rest keep an explicit address because no generated symbol
# names the "one safe readable CSR" choice.
FABRIC_BLOCKS = [
    ("SECURE_DMA", 0x1080_0000, None),
    ("WDT_TIMER", 0x1080_1000, None),
    ("SEP_SCRATCH_COLD", 0x1080_2000, None),        # SCRATCH[0] (RW)
    ("SEP_SCRATCH_WARM", 0x1080_2080, None),        # SCRATCH[0] (RW)
    # SW_RESET_N reset: KM[0]=0 held in reset, OTBN/AES/HMAC/KMAC[4:1]=1 released.
    # OCAH's ext_axi reg-walk delegates this register (can't reach it); the CPU LSU
    # path reads it safely (a read has no side effect — only a write clears reset).
    (
        "SEP_RESET_CTRL",
        SEP_RESET_CTRL.addr("SW_RESET_N"),
        SEP_RESET_CTRL.reset32("SW_RESET_N"),
    ),
    ("OTBN", OTBN.addr("INTR_STATE"), OTBN.reset32("INTR_STATE")),
    ("AES", 0x1091_0000, None),
    ("HMAC", HMAC.addr("INTR_STATE"), HMAC.reset32("INTR_STATE")),
    ("KMAC", KMAC.addr("INTR_STATE"), KMAC.reset32("INTR_STATE")),
    # CSRNG/EDN are OpenTitan blocks not exported by the SEP RDL header; their
    # INTR_STATE-resets-to-0 is an OpenTitan-wide invariant.
    ("DRBG_CSRNG", 0x1091_5000, 0x0000_0000),       # INTR_STATE
    ("DRBG_EDN", 0x1091_5800, 0x0000_0000),         # INTR_STATE
    ("ENTROPY_SRC", 0x1091_6000, None),             # INTR_STATE hw-driven
    ("SEP_LIFECYCLE", 0x1091_8000, None),           # FEAT_CTRL (RO, hw-driven)
    ("KM_MAILBOX", 0x1092_000C, None),              # SEP_STATUS (offset 0 is write-only)
    ("SEP_EFUSE_SHADOW", 0x1093_0008, None),        # LC_STATE shadow (not the OTP path)
    ("AXIL_MAILBOX", 0x10A0_0000, None),
    ("ALIAS_REMAP", 0x10A1_0000, None),             # region_start
    ("AP_OUTPUT_REMAP", 0x10A1_0200, None),         # output-remap region
    ("OT_SPI_HOST", 0x10B0_0000, None),             # INTR_STATUS
]


class sep_address_map_seq(uvm_sequence):
    def __init__(self, name: str = "sep_address_map_seq") -> None:
        super().__init__(name)
        self.ref_counter_low = 0
        self.ref_counter_high = 0
        self.base_addr_rw_checks = 0
        self.write_readback_checks = 0

    async def _read(self, addr: int, expected: int | None, name: str) -> int:
        item = SepAxiItem(f"rd_{name}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def _write(self, addr: int, data: int, name: str) -> None:
        item = SepAxiItem(f"wr_{name}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def body(self) -> None:
        for name in READ_CHECK:
            await self._read(
                BASE + SEP_CPU_CTRL.offset(name),
                expected=SEP_CPU_CTRL.reset32(name),
                name=name,
            )

        for name, _why in READ_ONLY:
            await self._read(BASE + SEP_CPU_CTRL.offset(name), expected=None, name=name)

        # OCAH proves the 64-bit REFERENCE_COUNTER is frontdoor readable. It is a
        # free-running counter on clk_ref_i, CDC-synchronized into clk_i, so the
        # exact count is timing-dependent -- read it without a value check.
        ref_off = SEP_CPU_CTRL.offset("REFERENCE_COUNTER")
        self.ref_counter_low = await self._read(
            BASE + ref_off, expected=None, name="REFERENCE_COUNTER_lo"
        )
        self.ref_counter_high = await self._read(
            BASE + ref_off + 4, expected=None, name="REFERENCE_COUNTER_hi"
        )

        for name, pattern in BASE_ADDR_RW:
            addr = BASE + SEP_CPU_CTRL.offset(name)
            reset = SEP_CPU_CTRL.reset32(name)
            mask = SEP_CPU_CTRL.mask32(name)
            await self._write(addr, pattern, name=name)
            await self._read(addr, expected=pattern & mask, name=f"{name}_pattern")
            await self._write(addr, reset, name=f"{name}_restore")
            await self._read(addr, expected=reset, name=f"{name}_restored")
            self.base_addr_rw_checks += 1

        for name, pattern in WRITE_READBACK:
            addr = BASE + SEP_CPU_CTRL.offset(name)
            mask = SEP_CPU_CTRL.mask32(name)
            await self._write(addr, pattern, name=name)
            await self._read(addr, expected=pattern & mask, name=name)
            # Restore the generated reset value.
            await self._write(addr, SEP_CPU_CTRL.reset32(name), name=f"{name}_restore")
            self.write_readback_checks += 1

        for name, value in WRITE_ONLY:
            await self._write(BASE + SEP_CPU_CTRL.offset(name), value, name=name)

        # CLOCK_GATE_CTRL write path: drive every implemented bit, read it back,
        # restore the reset value. See the module docstring for why this no longer
        # ungates per-block clocks (those fields do not exist in this RDL).
        cg_addr = BASE + SEP_CPU_CTRL.offset("CLOCK_GATE_CTRL")
        cg_mask = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")
        cg_reset = SEP_CPU_CTRL.reset32("CLOCK_GATE_CTRL")
        await self._write(cg_addr, cg_mask, name="CLOCK_GATE_CTRL")
        await self._read(cg_addr, expected=cg_mask, name="CLOCK_GATE_CTRL")

        # Walk the SEP-local fabric: every block must decode on the LSU bus.
        for name, addr, expected in FABRIC_BLOCKS:
            await self._read(addr, expected=expected, name=name)

        # Restore CLOCK_GATE_CTRL to its reset value.
        await self._write(cg_addr, cg_reset, name="CLOCK_GATE_CTRL_restore")

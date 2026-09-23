# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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

The reserved span after the 64-bit ``SEP_FUSE_SENSE_STATUS`` and before
``SEP_SW_DEBUG`` is not a live register. ``CPU_CTRL_INTERIOR_HOLES`` names
three words in that span. ``memory_map.adoc`` states the contract for an
offset inside a unit's allocated extent that owns no register: the unit accepts
it, reads return zero and writes are discarded, both OKAY. The test grades that,
and that the offset does not alias a live register. Then a walk
of one readable CSR per LSU-reachable block — Secure DMA,
WDT, cold/warm scratch, reset_ctrl, OTBN, AES, HMAC, KMAC, CSRNG, EDN, entropy
source, Adams Bridge, entropy pool, lifecycle ctrl, KM mailbox, eFuse shadow,
AXI-lite mailbox, inbound filter, alias-remap, output-remap, and the
OpenTitan SPI host — confirming every block decodes.

Expected values are SOURCE-DERIVED, never hardcoded. Offsets,
reset values, and implemented-field masks all come from `env/sep_reg_meta.py`,
which reads the generated `hw/sys/sep/regs/gen/py/sep_reg.py` export of the
SystemRDL. Only the write PATTERNS and the fabric-walk block addresses are
literals here: the patterns are chosen stimulus, and the walk's
addresses encode a per-block editorial choice of "one safe, readable CSR" that no
generated symbol expresses. Blocks whose reset value IS exported
(reset_ctrl/OTBN/HMAC/KMAC) take it from the header.

CLOCK_GATE_CTRL has one implemented bit (`pka_cg_enable[0:0]`, reset 0).
This sequence writes that implemented mask, reads it back, and restores
reset. Per-block CSR clocks are not gated in this RDL, so every walked
block is unconditionally clocked.

Most side-effecting registers are NOT written. The only address-aperture
exception is the SEP local/global base/size triplet: it is write/read/restored
immediately to close the CPU-control CSR write-path gap, before the fabric walk
runs. SMU base/size remain reset-checked only. woset LOCK regs are never written
because they would latch permanently. The scoreboard checks the AXI response on
every access and the value on every checked read.

SW_RESET_N is reachable on the CPU LSU; this sequence value-checks its reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import (
    CSRNG,
    EDN,
    HMAC,
    KMAC,
    OTBN,
    SEP_CPU_CTRL,
    SEP_RESET_CTRL,
    iter_registers,
    sym,
)

from seq_lib.sep_abr_keygen_seq import ABR_NAME0, NAME0_EXP
from seq_lib.sep_entropy_pool_seq import POOL_STATUS

BASE = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")

# Interior reserved span in sep_cpu_ctrl. SEP_FUSE_SENSE_STATUS is 64-bit
# (sep_cpu_ctrl.rdl), so the hole starts at the next 8-byte offset and runs
# up to SEP_SW_DEBUG. The xbar still claims the window, and `memory_map.adoc`
# says a unit accepts an offset inside its extent that owns no register: reads
# return zero and writes are discarded, both OKAY.
_FUSE_OFF = SEP_CPU_CTRL.offset("SEP_FUSE_SENSE_STATUS")
_SW_DEBUG_OFF = SEP_CPU_CTRL.offset("SEP_SW_DEBUG")
_HOLE_LO = _FUSE_OFF + 8
_HOLE_NAMED = _HOLE_LO + 0x18
assert _HOLE_LO < _HOLE_NAMED < _SW_DEBUG_OFF, (
    "sep_cpu_ctrl reserved-span arithmetic no longer contains 0x170; "
    "re-derive CPU_CTRL_INTERIOR_HOLES from the generated map"
)
CPU_CTRL_INTERIOR_HOLES = (
    BASE + _HOLE_LO,
    BASE + _HOLE_NAMED,
    BASE + _SW_DEBUG_OFF - 4,
)

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
    # Field-packed reset (0xC000_0100) — value-checked against the generated header.
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
    ("SMC_FUSE_SENSE_STATUS", "hw-driven by the TB's SMC fuse-sense model"),
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
# generated header, so a placeholder register that implements one bit is
# checked honestly instead of against a full 32-bit pattern.
WRITE_READBACK = [
    ("SEP_SW_DEBUG", 0xDEAD_BEEF),
    # Odd literal: TIMEOUT_COUNT* implement only bit 0 (a placeholder
    # `reserved` field declared sw=rw), and its reset is 0. An even pattern would
    # mask to 0 == reset, so the readback could not tell a stored write from an
    # ignored one. 0x…DE would have been exactly that; 0x…DF is not.
    ("TIMEOUT_COUNT_DMA", 0x0BAD_C0DF),
    ("TIMEOUT_COUNT_SYS_IN", 0xCAFE_F00D),
    ("TIMEOUT_ENABLE", 0x0000_00FF),
]

# (name, value) — write-only (sw=w) registers: reading them returns non-OKAY, so
# cover decode + write path with a benign value instead. Inert here because
# TIMEOUT_ENABLE is restored to its reset (the timeout subsystem is disabled), so
# TIMEOUT_CLEAR (write-1-to-clear) clears nothing and TIMEOUT_MODE is unused.
WRITE_ONLY = [
    ("TIMEOUT_CLEAR", 0x0000_0000),
    ("TIMEOUT_MODE", 0x0000_0000),
]

# SEP-local fabric walk: one defined, readable CSR per LSU-reachable block.
# expected=None => accessibility only (OKAY; value hw-driven/state-dependent).
# Memory-backed ranges (SRAM/ROM/TCM, OTBN/KMAC mem, KM mem) and OTP-triggering
# eFuse interface regs (0x1093_04xx+) are NOT probed — they would hang.
# Pool pop (0x1095_0010) is destructive — only STATUS is walked.
#
# Blocks whose address AND reset value are exported take both from the header;
# ABR NAME and the entropy-pool STATUS come from their owning seq modules.
# ABR NAME0 comes from the owning seq (ASCII of ML-DSA-87).
_INFILT0 = sym("INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR")
_INFILT0_CFG_RESET = next(
    (
        info.reset
        for info in iter_registers()
        if info.block == "INBOUND_FILTER_CTRL_0_" and info.name == "FILTER_CONFIG"
    ),
    None,
)
if _INFILT0_CFG_RESET is None:
    # Fail at import rather than build a row with no expected value. A bare
    # next() raises StopIteration with no message; name what is missing.
    raise RuntimeError(
        "INBOUND_FILTER_CTRL_0_.FILTER_CONFIG is not in the generated register "
        "export, so the inbound-filter address-map row has no reset value to "
        "check; update FABRIC_BLOCKS if the block was renamed"
    )
FABRIC_BLOCKS = [
    ("SECURE_DMA", sym("SECURE_DMA_REG_MAP_BASE_ADDR"), None),
    ("WDT_TIMER", sym("WDT_TIMER_REG_MAP_BASE_ADDR"), None),
    ("SEP_SCRATCH_COLD", sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR"), None),
    ("SEP_SCRATCH_WARM", sym("SEP_SCRATCH_WARM_REG_MAP_BASE_ADDR"), None),
    # SW_RESET_N reset: KM[0]=0 held in reset, OTBN/AES/HMAC/KMAC/TRNG[5:1]=1
    # released. The reference suite's ext_axi reg-walk delegates this register
    # (it cannot reach it); the CPU LSU path reads it safely, since a read has no
    # side effect and only a write clears reset.
    (
        "SEP_RESET_CTRL",
        SEP_RESET_CTRL.addr("SW_RESET_N"),
        SEP_RESET_CTRL.reset32("SW_RESET_N"),
    ),
    ("OTBN", OTBN.addr("INTR_STATE"), OTBN.reset32("INTR_STATE")),
    ("AES", sym("AES_REG_MAP_BASE_ADDR"), None),
    ("HMAC", HMAC.addr("INTR_STATE"), HMAC.reset32("INTR_STATE")),
    ("KMAC", KMAC.addr("INTR_STATE"), KMAC.reset32("INTR_STATE")),
    ("DRBG_CSRNG", sym("CSRNG_INTR_STATE_REG_ADDR"), CSRNG.reset("INTR_STATE")),
    ("DRBG_EDN", sym("EDN_INTR_STATE_REG_ADDR"), EDN.reset("INTR_STATE")),
    ("ENTROPY_SRC", sym("ENTROPY_SOURCE_REG_MAP_BASE_ADDR"), None),
    ("ADAMS_BRIDGE", ABR_NAME0, NAME0_EXP),  # MLDSA_NAME[0]; no OSS RDL block
    ("ENTROPY_POOL", POOL_STATUS, None),  # adapter not in PeakRDL
    ("SEP_LIFECYCLE", sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR"), None),
    ("KM_MAILBOX", sym("KM_MAILBOX_SEP_SEP_STATUS_REG_ADDR"), None),
    ("SEP_EFUSE_SHADOW", sym("SEP_EFUSE_MAP_LC_STATE_REG_ADDR"), None),
    ("AXIL_MAILBOX", sym("AXIL_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR"), None),
    ("INBOUND_FILTER", _INFILT0, _INFILT0_CFG_RESET),
    ("ALIAS_REMAP", sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR"), None),
    ("AP_OUTPUT_REMAP", sym("AP_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR"), None),
    ("OT_SPI_HOST", sym("SPI_CONTROLLER_INTR_STATE_REG_ADDR"), None),
]


class sep_address_map_seq(uvm_sequence):
    def __init__(self, name: str = "sep_address_map_seq") -> None:
        super().__init__(name)
        self.ref_counter_low = 0
        self.ref_counter_high = 0
        self.base_addr_rw_checks = 0
        self.write_readback_checks = 0
        self.fabric_walk_checks = 0
        # Registers whose only fields are RDL `reserved` placeholders. They are
        # still fully checked above (real sw=rw storage), but what they prove is
        # storage rather than an implemented-field readback -- noted so the
        # evidence line can say so.
        self.write_readback_storage_only: list[str] = []

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

        # The 64-bit REFERENCE_COUNTER is frontdoor readable and LIVE: it counts
        # on clk_ref_i, which the testbench drives, so no pinned value can be
        # its expectation. Read the low half twice and require it to advance.
        # That is a stronger statement than a reset compare and it cannot be
        # satisfied by a dead decode: a neighbouring register's storage, a stuck
        # all-ones or a zero return all hold still between the two reads.
        #
        # expected=None on these two reads is deliberate and is not an unchecked
        # read -- the advance below is the check. Every other read in this sweep
        # keeps its pinned expectation.
        ref_off = SEP_CPU_CTRL.offset("REFERENCE_COUNTER")
        first_low = await self._read(BASE + ref_off, expected=None, name="REFERENCE_COUNTER_lo")
        self.ref_counter_high = await self._read(
            BASE + ref_off + 4, expected=None, name="REFERENCE_COUNTER_hi"
        )
        # Two AXI beats can finish inside one clk_ref_i period (40 ns vs a 4 ns
        # core). Wait two reference edges so a live counter must advance.
        await ClockCycles(cocotb.top.clk_ref_i, 2)
        self.ref_counter_low = await self._read(
            BASE + ref_off, expected=None, name="REFERENCE_COUNTER_lo_again"
        )
        # The low half wraps every 2**32 reference ticks. Two reads a few bus
        # accesses apart cannot span that, so a non-advance is a stopped counter.
        if self.ref_counter_low <= first_low:
            raise AssertionError(
                f"REFERENCE_COUNTER low half did not advance between two reads "
                f"(0x{first_low:08x} -> 0x{self.ref_counter_low:08x}). It counts on "
                f"clk_ref_i and resynchronises onto clk_i; a reference clock that is "
                f"not running and a crossing that never hands the value over both "
                f"read as a stable count"
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
            # Compare against the STORAGE mask, not the implemented-field mask.
            # Every register here is plain SW-write storage read straight back
            # (sep_cpu_ctrl_reg.sv:937-950 is the worked example: a `decoded_strb
            # && decoded_req_is_wr` load into field_storage, with no hw driver on
            # the field), so the readback is fully predictable even where the only
            # field is a `sw=rw` placeholder that RDL names `reserved`. Using
            # mask() here instead would silently drop TIMEOUT_* to expected==0 and
            # stop proving anything.
            store_mask = SEP_CPU_CTRL.mask32_all(name)
            expected = pattern & store_mask
            # Vacuity is a property of the PATTERN, not of the register: if the
            # masked pattern equals the masked reset, the readback cannot tell a
            # stored write from an ignored one. Fail loudly at authoring time
            # rather than reporting a check that proves nothing.
            assert expected != (SEP_CPU_CTRL.reset32(name) & store_mask), (
                f"{name}: WRITE_READBACK pattern 0x{pattern:08X} masks to the reset "
                f"value under storage mask 0x{store_mask:08X}; this check could not "
                f"distinguish a stored write from an ignored one. Choose a pattern "
                f"whose masked value differs from reset."
            )
            await self._write(addr, pattern, name=name)
            await self._read(addr, expected=expected, name=name)
            # Restore the generated reset value.
            await self._write(addr, SEP_CPU_CTRL.reset32(name), name=f"{name}_restore")
            self.write_readback_checks += 1
            # Informational only: these have no software-usable fields, so what was
            # proven is storage, not an implemented-field readback.
            if mask == 0:
                self.write_readback_storage_only.append(name)

        for name, value in WRITE_ONLY:
            await self._write(BASE + SEP_CPU_CTRL.offset(name), value, name=name)

        # CLOCK_GATE_CTRL write path: drive every implemented bit, read it back,
        # restore the reset value. See the module docstring for why this does not
        # ungate per-block clocks (those fields do not exist in this RDL).
        cg_addr = BASE + SEP_CPU_CTRL.offset("CLOCK_GATE_CTRL")
        cg_mask = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")
        cg_reset = SEP_CPU_CTRL.reset32("CLOCK_GATE_CTRL")
        await self._write(cg_addr, cg_mask, name="CLOCK_GATE_CTRL")
        await self._read(cg_addr, expected=cg_mask, name="CLOCK_GATE_CTRL")

        # Walk the SEP-local fabric: every block must decode on the LSU bus.
        for name, addr, expected in FABRIC_BLOCKS:
            await self._read(addr, expected=expected, name=name)
            self.fabric_walk_checks += 1

        # Restore CLOCK_GATE_CTRL to its reset value.
        await self._write(cg_addr, cg_reset, name="CLOCK_GATE_CTRL_restore")

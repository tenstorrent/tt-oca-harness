# SPDX-License-Identifier: Apache-2.0
"""Sequence for sep_address_map_test.

Full sweep of every sep_cpu_ctrl register (base 0x10A3_0000) over the CPU LSU bus:
  * READ_CHECK  — read each register, verify its reset value (decode + reset cov).
  * READ_ONLY   — read hw-driven / non-deterministic registers (resp-check only).
  * REF_COUNTER — read both REFERENCE_COUNTER words and log the observed value.
  * BASE_ADDR_RW — write/read/restore SEP base/size CSRs used by the local remap.
  * WRITE_READBACK — write a pattern to pure-RW scratch/threshold regs, read it
                     back, then restore the reset value (write-path coverage).
  * WRITE_ONLY  — write a benign value to write-only (sw=w) regs (decode + write
                  path); they cannot be read back.

followed by a SEP-local fabric walk that ports the OCAH sep_address_map_test
(which runs sep_reg_walk_seq) to the LSU-reachable, OSS-clean subset: one defined,
readable CSR per block — Secure DMA, WDT, cold/warm scratch, reset_ctrl, OTBN, AES,
HMAC, KMAC, CSRNG, EDN, entropy source, lifecycle ctrl, KM mailbox, eFuse shadow,
AXI-lite mailbox, alias-remap, output-remap, and the OpenTitan SPI host —
confirming every block decodes on the LSU bus. The DMA, mailbox, alias-remap, and
entropy-fifo clocks are ungated via CLOCK_GATE_CTRL first so those blocks respond.

This goes beyond OCAH's reg-walk: it runs on the external AXI master, which cannot
reach SW_RESET_N (so OCAH delegates the reset controller to a directed test). The
CPU LSU master reaches it, so we value-verify SW_RESET_N's reset value directly.

Most side-effecting registers are deliberately NOT written. The only address-aperture
exception is the SEP local/global base/size triplet: it is write/read/restored
immediately to close 's CPU-control CSR write-path gap, before the
fabric walk runs. SMU base/size remain reset-checked only. woset LOCK regs are
never written because they would latch permanently. Mirrors the internal
sep_cpuctrl_misc_regs test, scoped to the LSU-reachable CSRs. The scoreboard
checks the AXI response on every access and the value on every checked read.
"""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

BASE = 0x10A3_0000

# (name, offset, expected low-32 reset value) — read and verify, never written.
READ_CHECK = [
    ("CLOCK_GATE_CTRL",       0x008, 0x001F_0021),
    ("TIMEOUT_INTERRUPT",     0x018, 0x0000_0000),
    ("PKA_CTRL",              0x020, 0x0000_0001),
    # Remaining TIMEOUT_COUNT_* counters (DMA/SYS_IN are in WRITE_READBACK).
    ("TIMEOUT_COUNT_MAILBOX_INBOUND",  0x038, 0x0000_0000),
    ("TIMEOUT_COUNT_MAILBOX_OUTBOUND", 0x040, 0x0000_0000),
    ("TIMEOUT_COUNT_ENTROPY_WRITE",    0x048, 0x0000_0000),
    ("TIMEOUT_COUNT_ENTROPY_READ",     0x050, 0x0000_0000),
    ("TIMEOUT_COUNT_FILTER_OUT",       0x058, 0x0000_0000),
    ("TIMEOUT_COUNT_ALIAS_REMAP",      0x060, 0x0000_0000),
    ("SEP_GLOBAL_BASE_ADDR",  0x0C0, 0x0000_0000),
    # #3711: SEP_LOCAL_BASE_ADDR reset moved 0xC000_0000 -> 0xD000_0000 (fixed
    # 768 MiB CPU alias window base). SEP_REGION_SIZE (inbound/SMU) reset unchanged.
    ("SEP_LOCAL_BASE_ADDR",   0x0C8, 0xD000_0000),
    ("SEP_REGION_SIZE",       0x0D0, 0x0100_0000),
    ("SMU_GLOBAL_BASE_ADDR",  0x100, 0x8000_0000),
    ("SMU_REGION_SIZE",       0x110, 0x4000_0000),
    ("SMC_FUSE_SENSE_STATUS", 0x140, 0x0000_0000),
    ("SEP_STRAPS",            0x160, 0x0000_0000),
    ("SEP_NMI_VEC_LOCK",      0x188, 0x0000_0000),
    ("EXT_TRNG_SRC_SEL",      0x190, 0x0000_0003),
    ("EXT_TRNG_SRC_SEL_LOCK", 0x198, 0x0000_0000),
    ("SEP_VERSION_ID",        0x1000, 0xDEAD_BEEF),
]

# (name, offset) — value is hw-driven / non-deterministic; check the AXI response
# (decode reachable) without asserting a specific value.
READ_ONLY = [
    ("REFERENCE_COUNTER",     0x010),  # free-running counter
    ("SEP_TEST_CTRL",         0x0B0),  # hw-driven straps (e.g. sep_standalone)
    ("SEP_FUSE_SENSE_STATUS", 0x150),  # depends on +skip_fuse_sense path
    ("SEP_NMI_VEC",           0x180),  # field-packed reset; resp-check only
]

# (name, offset, pattern, reset_value) — write/read/restore the SEP base/size CSRs
# early, before the SEP-local fabric walk. These are the  remnants not
# covered by the original address-map sweep. Do not include SMU_* here: those are
# system/outbound routing knobs and stay reset-value checks in this test.
BASE_ADDR_RW = [
    ("SEP_GLOBAL_BASE_ADDR", 0x0C0, 0x1234_0000, 0x0000_0000),
    # Write a pattern distinct from the 0xD000_0000 reset so the R/W check stays
    # non-vacuous, then restore the true post-#3711 reset value.
    ("SEP_LOCAL_BASE_ADDR",  0x0C8, 0xE000_0000, 0xD000_0000),
    ("SEP_REGION_SIZE",      0x0D0, 0x2000_0000, 0x0100_0000),
]

# (name, offset, pattern, field_mask, reset_value) — pure-RW, no side effects.
WRITE_READBACK = [
    ("SEP_SW_DEBUG",          0x178, 0xDEAD_BEEF, 0xFFFF_FFFF, 0x0),
    ("TIMEOUT_COUNT_DMA",     0x028, 0x0BAD_C0DE, 0xFFFF_FFFF, 0x0),
    ("TIMEOUT_COUNT_SYS_IN",  0x030, 0xCAFE_F00D, 0xFFFF_FFFF, 0x0),
    ("TIMEOUT_ENABLE",        0x068, 0x0000_00FF, 0x0000_00FF, 0x0),
    ("RAS_BANK_INFO",         0x170, 0x0000_00FF, 0x0000_00FF, 0x0),
]

# (name, offset, value) — write-only (sw=w) registers: reading them returns
# non-OKAY, so cover decode + write path with a benign value instead. Inert here
# because TIMEOUT_ENABLE is restored to 0 (the timeout subsystem is disabled), so
# TIMEOUT_CLEAR (write-1-to-clear) clears nothing and TIMEOUT_MODE is unused.
WRITE_ONLY = [
    ("TIMEOUT_CLEAR", 0x070, 0x0000_0000),
    ("TIMEOUT_MODE",  0x078, 0x0000_0000),
]

# CLOCK_GATE_CTRL: ungate the blocks whose CSR clocks are off at reset so they
# respond, on top of the reset value (0x001F_0021). Bits (from sep_cpu_ctrl.rdl):
# dma[1], mailbox[2], alias_remap[7], entropy_fifo[10]. The crypto fabric
# (OTBN/AES/HMAC/KMAC/CSRNG/EDN/entropy CSRs) and sep_io are already clocked.
CLOCK_GATE_CTRL_ADDR = BASE + 0x008
CLOCK_GATE_CTRL_RESET = 0x001F_0021
CLOCK_GATE_CTRL_ENABLE = (
    CLOCK_GATE_CTRL_RESET | (1 << 1) | (1 << 2) | (1 << 7) | (1 << 10)
)

# SEP-local fabric walk (OCAH sep_reg_walk_seq parity): one defined, readable CSR
# per block. expected=None => accessibility only (response must be OKAY, value is
# hw-driven/state-dependent); a value means a known OpenTitan reset (INTR_STATE=0).
# The chosen offsets match the registers OCAH's reg-walk reads. Memory-backed
# ranges (SRAM/ROM/TCM, OTBN/KMAC mem, KM mem) and the OTP-triggering eFuse
# interface regs (0x1093_04xx+) are NOT probed — they would hang. Excluded for OSS
# hygiene: Cadence xSPI (0x2000_xxxx), the external SPI-mux port, and the TRNG
# wrapper (DWC core is externalized in bare sep, so it is not reachable here).
FABRIC_BLOCKS = [
    ("SECURE_DMA",      0x1080_0000, None),         # needs dma_cg
    ("WDT_TIMER",       0x1080_1000, None),
    ("SEP_SCRATCH_COLD", 0x1080_2000, None),        # SCRATCH[0] (RW)
    ("SEP_SCRATCH_WARM", 0x1080_2080, None),        # SCRATCH[0] (RW)
    # SW_RESET_N reset: KM[0]=0 held in reset, OTBN/AES/HMAC/KMAC[4:1]=1 released.
    # OCAH's ext_axi reg-walk delegates this register (can't reach it); the CPU LSU
    # path reads it safely (a read has no side effect — only a write clears reset).
    ("SEP_RESET_CTRL",  0x1080_3000, 0x0000_001E),
    ("OTBN",            0x1090_0000, 0x0000_0000),  # INTR_STATE
    ("AES",             0x1091_0000, None),
    ("HMAC",            0x1091_1000, 0x0000_0000),  # INTR_STATE
    ("KMAC",            0x1091_3000, 0x0000_0000),  # INTR_STATE
    ("DRBG_CSRNG",      0x1091_5000, 0x0000_0000),  # INTR_STATE
    ("DRBG_EDN",        0x1091_5800, 0x0000_0000),  # INTR_STATE
    ("ENTROPY_SRC",     0x1091_6000, None),         # INTR_STATE hw-driven (needs entropy_fifo_cg)
    ("SEP_LIFECYCLE",   0x1091_8000, None),         # FEAT_CTRL (RO, hw-driven)
    ("KM_MAILBOX",      0x1092_000C, None),         # SEP_STATUS (offset 0 is write-only)
    ("SEP_EFUSE_SHADOW", 0x1093_0008, None),        # LC_STATE shadow reg (not the OTP path)
    ("AXIL_MAILBOX",    0x10A0_0000, None),         # needs mailbox_cg
    ("ALIAS_REMAP",     0x10A1_0000, None),         # region_start (needs alias_remap_cg)
    ("AP_OUTPUT_REMAP", 0x10A1_0200, None),         # output-remap region (needs alias_remap_cg)
    ("OT_SPI_HOST",     0x10B0_0000, None),         # INTR_STATUS
]


class sep_address_map_seq(uvm_sequence):
    def __init__(self, name: str = "sep_address_map_seq") -> None:
        super().__init__(name)
        self.ref_counter_low = 0
        self.ref_counter_high = 0
        self.base_addr_rw_checks = 0

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
        for name, off, reset in READ_CHECK:
            await self._read(BASE + off, expected=reset, name=name)

        for name, off in READ_ONLY:
            await self._read(BASE + off, expected=None, name=name)

        # OCAH proves the 64-bit REFERENCE_COUNTER is frontdoor readable. It is a
        # free-running counter on clk_ref_i, CDC-synchronized into clk_i, so the
        # exact count is timing-dependent -- read it without a value check.
        self.ref_counter_low = await self._read(
            BASE + 0x010, expected=None, name="REFERENCE_COUNTER_lo"
        )
        self.ref_counter_high = await self._read(
            BASE + 0x014, expected=None, name="REFERENCE_COUNTER_hi"
        )

        for name, off, pattern, reset in BASE_ADDR_RW:
            await self._write(BASE + off, pattern, name=name)
            await self._read(BASE + off, expected=pattern, name=f"{name}_pattern")
            await self._write(BASE + off, reset, name=f"{name}_restore")
            await self._read(BASE + off, expected=reset, name=f"{name}_restored")
            self.base_addr_rw_checks += 1

        for name, off, pattern, mask, reset in WRITE_READBACK:
            await self._write(BASE + off, pattern, name=name)
            await self._read(BASE + off, expected=pattern & mask, name=name)
            await self._write(BASE + off, reset, name=name)  # restore reset value

        for name, off, value in WRITE_ONLY:
            await self._write(BASE + off, value, name=name)

        # Ungate the DMA/mailbox/alias-remap/entropy-fifo clocks before reaching
        # those blocks, then confirm the enable took (write-path on a known-RW reg).
        await self._write(CLOCK_GATE_CTRL_ADDR, CLOCK_GATE_CTRL_ENABLE, name="CLOCK_GATE_CTRL")
        await self._read(CLOCK_GATE_CTRL_ADDR, expected=CLOCK_GATE_CTRL_ENABLE, name="CLOCK_GATE_CTRL")

        # Walk the SEP-local fabric: every block must decode on the LSU bus.
        for name, addr, expected in FABRIC_BLOCKS:
            await self._read(addr, expected=expected, name=name)

        # Restore CLOCK_GATE_CTRL to its reset value.
        await self._write(CLOCK_GATE_CTRL_ADDR, CLOCK_GATE_CTRL_RESET, name="CLOCK_GATE_CTRL")

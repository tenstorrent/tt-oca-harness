// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

.option norvc
.option norelax

.equ CSR_MPMC,       0x7c0
.equ SRAM_CODE_ADDR, 0x10002000
.equ DCCM_TEST_ADDR, 0xC0041000
.equ ICCM_PROG_ADDR, 0xC0020000
.equ DCCM_PATTERN,   0xDCC0DE01
.equ STDOUT,         0x80000000
.equ TEST_MAGIC0,    0xA5A55A5A
.equ TEST_MAGIC_FAIL, 0xDEADBEEF
.equ PHASE3_CODE_BYTES, 36

.equ SECURE_DMA_SRC_ADDR_LO_REG_ADDR,                 0x10800010
.equ SECURE_DMA_SRC_ADDR_HI_REG_ADDR,                 0x10800014
.equ SECURE_DMA_DST_ADDR_LO_REG_ADDR,                 0x10800018
.equ SECURE_DMA_DST_ADDR_HI_REG_ADDR,                 0x1080001C
.equ SECURE_DMA_ADDR_SPACE_ID_REG_ADDR,               0x10800020
.equ SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_ADDR,   0x10800024
.equ SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_ADDR,  0x10800028
.equ SECURE_DMA_RANGE_VALID_REG_ADDR,                 0x1080002C
.equ SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR,             0x10800038
.equ SECURE_DMA_CHUNK_DATA_SIZE_REG_ADDR,             0x1080003C
.equ SECURE_DMA_TRANSFER_WIDTH_REG_ADDR,              0x10800040
.equ SECURE_DMA_CONTROL_REG_ADDR,                     0x10800044
.equ SECURE_DMA_SRC_CONFIG_REG_ADDR,                  0x10800048
.equ SECURE_DMA_DST_CONFIG_REG_ADDR,                  0x1080004C
.equ SECURE_DMA_STATUS_REG_ADDR,                      0x10800050
.equ SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR,           0x10A300D0

/* SEP outbound egress filter, entry 0. Offsets and the open-window encoding
 * match drivers/sep_outbound_filter.h: CONFIG @0x0, START @0x8, END @0x10;
 * CONFIG = read|write|entry_enabled|allow_burst plus the reserved bit 32. */
.equ OUTBOUND_FILTER_CTRL_BASE, 0x10A20000
.equ FILTER_CONFIG_OFF,         0x0
.equ FILTER_START_OFF,          0x8
.equ FILTER_END_OFF,            0x10
.equ FILTER_CFG_OPEN_LO,        0x01000013
.equ FILTER_CFG_OPEN_HI,        0x1

.section .text.init
.align 4
.global _start
_start:
    /* Match the normal SEP firmware PMA setup before touching TCM/peripherals. */
    li      t0, 0xAA2AAAAA
    csrw    CSR_MPMC, t0

    la      t0, trap_fail
    csrw    mtvec, t0

    /*
     * Open the outbound egress window over STDOUT before anything writes there.
     * The SEP outbound filter is BLOCK_BY_DEFAULT=1, so an unopened window does
     * not silently drop the store -- it isolates it and answers with an error,
     * which the EL2 takes as a store access fault. Both the PASS routine and
     * trap_fail report through STDOUT, so without this the image cannot report
     * at all: it faults on the first mailbox write and lands in fail_hang with
     * no verdict, whatever actually happened earlier.
     *
     * START/END before CONFIG so the entry enables over the final range.
     */
    li      t0, OUTBOUND_FILTER_CTRL_BASE
    li      t1, STDOUT
    sw      t1, FILTER_START_OFF(t0)
    sw      zero, FILTER_START_OFF+4(t0)
    li      t1, STDOUT
    addi    t1, t1, 0xFF
    sw      t1, FILTER_END_OFF(t0)
    sw      zero, FILTER_END_OFF+4(t0)
    li      t1, FILTER_CFG_OPEN_LO
    sw      t1, FILTER_CONFIG_OFF(t0)
    li      t1, FILTER_CFG_OPEN_HI
    sw      t1, FILTER_CONFIG_OFF+4(t0)
    fence

    /* Prove ROM-fetched code can access DCCM without DCCM firmware preload. */
    li      t0, DCCM_TEST_ADDR
    li      t1, DCCM_PATTERN
    sw      t1, 0(t0)
    lw      t2, 0(t0)
    bne     t1, t2, fail

    /*
     * CPU LSU cannot write ICCM directly on VeeR EL2.  Stage the ICCM PASS
     * routine in SEP SRAM, then use secure DMA to copy SRAM -> ICCM.
     */
    li      t0, SRAM_CODE_ADDR

    li      t1, 0x800002b7  /* lui  t0, 0x80000 */
    sw      t1, 0(t0)
    li      t1, 0x00028293  /* addi t0, t0, 0 */
    sw      t1, 4(t0)
    li      t1, 0xa5a56337  /* lui  t1, 0xa5a56 */
    sw      t1, 8(t0)
    li      t1, 0xa5a30313  /* addi t1, t1, -1446 => 0xA5A55A5A */
    sw      t1, 12(t0)
    li      t1, 0x0062a023  /* sw   t1, 0(t0) */
    sw      t1, 16(t0)
    li      t1, 0xcafec337  /* lui  t1, 0xcafec */
    sw      t1, 20(t0)
    li      t1, 0xabe30313  /* addi t1, t1, -1346 => 0xCAFEBABE */
    sw      t1, 24(t0)
    li      t1, 0x0062a023  /* sw   t1, 0(t0) */
    sw      t1, 28(t0)
    li      t1, 0x0000006f  /* self-loop after PASS */
    sw      t1, 32(t0)

    fence

    /* Allow DMA over the full address range. */
    li      t0, SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_ADDR
    sw      zero, 0(t0)
    li      t0, SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_ADDR
    li      t1, 0xffffffff
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_RANGE_VALID_REG_ADDR
    li      t1, 1
    sw      t1, 0(t0)

    /*
     * Disable the local-alias remap while DMA targets ICCM. Otherwise the DMA
     * path remaps the ICCM alias to the low address space before it reaches
     * the TCM port.
     */
    li      t0, SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR
    lw      s0, 0(t0)
    sw      zero, 0(t0)
    fence   ow, ow

    li      t0, SECURE_DMA_SRC_ADDR_LO_REG_ADDR
    li      t1, SRAM_CODE_ADDR
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_SRC_ADDR_HI_REG_ADDR
    sw      zero, 0(t0)
    li      t0, SECURE_DMA_DST_ADDR_LO_REG_ADDR
    li      t1, ICCM_PROG_ADDR
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_DST_ADDR_HI_REG_ADDR
    sw      zero, 0(t0)
    li      t0, SECURE_DMA_ADDR_SPACE_ID_REG_ADDR
    li      t1, 0x77
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_TRANSFER_WIDTH_REG_ADDR
    li      t1, 0x2
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_SRC_CONFIG_REG_ADDR
    li      t1, 0x1
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_DST_CONFIG_REG_ADDR
    li      t1, 0x1
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_CHUNK_DATA_SIZE_REG_ADDR
    li      t1, PHASE3_CODE_BYTES
    sw      t1, 0(t0)
    li      t0, SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR
    sw      t1, 0(t0)

    li      t0, SECURE_DMA_CONTROL_REG_ADDR
    li      t1, 0x80000100
    sw      t1, 0(t0)

    li      t0, SECURE_DMA_STATUS_REG_ADDR
    li      t3, 200000
dma_poll:
    lw      t1, 0(t0)
    andi    t2, t1, 0x8
    bnez    t2, fail
    andi    t2, t1, 0x2
    bnez    t2, dma_done
    addi    t3, t3, -1
    bnez    t3, dma_poll
    j       fail

dma_done:
    fence.i
    li      t0, ICCM_PROG_ADDR
    jalr    zero, 0(t0)

fail:
trap_fail:
    li      t0, STDOUT
    li      t1, TEST_MAGIC0
    sw      t1, 0(t0)
    fence
    li      t1, TEST_MAGIC_FAIL
    sw      t1, 0(t0)

fail_hang:
    wfi
    j       fail_hang

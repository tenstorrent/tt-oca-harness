// OCH SEP ROM - DMA copy implementation (secure_dma)
//
// References:
// - bootcode DMA API and behavior
// - `fw/sep/tests/dma_test/dma_test.c` (secure_dma programming sequence)
//
// This file is freestanding and uses absolute register addresses from
// `och_sep_top_reg.h`.

#include <stddef.h>
#include <stdint.h>

#include "rom_mmio.h"

// Generated absolute register map for OCH SEP.
#include "och_sep_top_reg.h"

#include "sep_dma.h"
#include "rom_virt_console.h"

// SMC interface (for dynamic SMC SRAM range checks).
#include "sep_smc_interface.h"

#ifndef BIT
#define BIT(n) (1u << (n))
#endif

// Cadence xSPI direct flash access / XIP window (OCH address map):
//   0x3000_0000 - 0x3FFF_FFFF (256 MiB).
#ifndef SEP_SPI_BASE
#define SEP_SPI_BASE ((uint32_t)SEP_AXI_EXTENSION_XIP_REGION_MEM_BASE_ADDR)
#endif
#ifndef SEP_SPI_MAX_SIZE
#define SEP_SPI_MAX_SIZE ((uint32_t)SEP_AXI_EXTENSION_XIP_REGION_MEM_SIZE)
#endif

// For OCH, the "SEP EXT SRAM" equivalent is `sep_sram` in the address map.
#define SEP_EXT_SRAM_BASE ((uint32_t)SEP_SRAM_MEM_BASE_ADDR)
#define SEP_SRAM_SIZE ((uint32_t)SEP_SRAM_MEM_SIZE)

// Minimal local error codes for the ROM DMA path.
enum {
    SEP_MSG_OUT_OF_RANGE_ERROR = 0x00020001u,
    SEP_MSG_DMA_ERROR = 0x00020002u,
};

static inline uint32_t dma_read(uint32_t addr) { return mmio_read32(addr); }
static inline void dma_write(uint32_t addr, uint32_t v) { mmio_write32(addr, v); }

static inline int contains_range_u32(uint32_t base, uint32_t size, uint32_t addr,
                                     uint32_t len) {
    // Reject wraparound.
    if (len == 0u) {
        return 1;
    }
    const uint32_t end = addr + len - 1u;
    if (end < addr) {
        return 0;
    }
    const uint32_t limit = base + size - 1u;
    if (limit < base) {
        return 0;
    }
    return (addr >= base) && (end <= limit);
}

void sep_dma_init(void) {
    // Secure DMA requires an enabled memory range before operation.
    dma_write(SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_ADDR, 0x00000000u);
    dma_write(SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_ADDR, 0xFFFFFFFFu);
    dma_write(SECURE_DMA_RANGE_VALID_REG_ADDR, 0x00000001u);
}

// Check if destination is in the ICCM region.
static inline int dest_is_iccm(uint32_t dest, uint32_t n) {
    return contains_range_u32(SEP_ICCM_MEM_BASE_ADDR, SEP_ICCM_MEM_SIZE, dest, n);
}

uint32_t sep_dma_copy(uint32_t dest, uint32_t src, size_t len) {
    const uint32_t n = (uint32_t)len;

    // Destination can be in SEP SRAM, SMC SRAM, or ICCM (for BL1 handoff).
    const uint32_t smc_sram = sep_get_smc_sram_base();
    if (!contains_range_u32(SEP_EXT_SRAM_BASE, SEP_SRAM_SIZE, dest, n) &&
        !contains_range_u32(smc_sram, SMC_SRAM_SIZE_BYTES, dest, n) &&
        !dest_is_iccm(dest, n)) {
        return SEP_MSG_OUT_OF_RANGE_ERROR;
    }

    // Source can be in SPI window, SMC SRAM, or SEP SRAM.
    if (!contains_range_u32(SEP_SPI_BASE, SEP_SPI_MAX_SIZE, src, n) &&
        !contains_range_u32(smc_sram, SMC_SRAM_SIZE_BYTES, src, n) &&
        !contains_range_u32(SEP_EXT_SRAM_BASE, SEP_SRAM_SIZE, src, n)) {
        return SEP_MSG_OUT_OF_RANGE_ERROR;
    }

    // The DMA master's AXI path includes an axi_local_alias_remap that
    // translates addresses in [SEP_LOCAL_BASE_ADDR, +SEP_REGION_SIZE) down
    // by subtracting SEP_LOCAL_BASE_ADDR.  Default: 0xC0000000 → 0x00000000.
    //
    // ICCM lives at 0xC0000000 on the crossbar (cpu_tcm port).  With the
    // remap active, a DMA write to 0xC0000000 becomes 0x00000000 which
    // routes to external_chiplet (DMA has no connectivity → BUS_ERROR).
    //
    // Workaround: temporarily set SEP_REGION_SIZE=0 to disable the remap,
    // so the DMA address passes through to the crossbar unchanged.
    const int iccm_dest = dest_is_iccm(dest, n);
    uint32_t saved_region_size = 0;
    if (iccm_dest) {
        saved_region_size = mmio_read32(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR);
        simputshex32("REMAP_OLD=", saved_region_size);

        // Disable remap: set region size to 0.
        mmio_write32(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR, 0u);

        // Fence to ensure register write is committed before DMA observes it.
        __asm__ volatile("fence ow, ow" ::: "memory");

        uint32_t readback = mmio_read32(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR);
        simputshex32("REMAP_NEW=", readback);
    }

    // Program transfer.
    dma_write(SECURE_DMA_SRC_ADDR_LO_REG_ADDR, src);
    dma_write(SECURE_DMA_SRC_ADDR_HI_REG_ADDR, 0u);
    dma_write(SECURE_DMA_DST_ADDR_LO_REG_ADDR, dest);
    dma_write(SECURE_DMA_DST_ADDR_HI_REG_ADDR, 0u);

    // Configure address space IDs: SRC_ASID=0x7 (OT internal), DST_ASID=0x7.
    // Required by secure_dma hardware (see dma_test.c).
    dma_write(SECURE_DMA_ADDR_SPACE_ID_REG_ADDR, 0x77u);

    // Configure for contiguous copy.
    // - transfer width: 4 bytes (FOUR_BYTE = 0x2) as used in dma_test.
    // - src/dst increment enabled.
    dma_write(SECURE_DMA_TRANSFER_WIDTH_REG_ADDR, 0x2u);
    dma_write(SECURE_DMA_SRC_CONFIG_REG_ADDR, 0x1u);
    dma_write(SECURE_DMA_DST_CONFIG_REG_ADDR, 0x1u);

    dma_write(SECURE_DMA_CHUNK_DATA_SIZE_REG_ADDR, n);
    dma_write(SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR, n);

    // Start: OPCODE=COPY (0), INITIAL_TRANSFER=1 (bit 8), GO=1 (bit 31).
    dma_write(SECURE_DMA_CONTROL_REG_ADDR, 0x80000100u);

    // Wait for completion (no timeout in the ROM DMA path).
    uint32_t result = 0;
    for (;;) {
        const uint32_t status = dma_read(SECURE_DMA_STATUS_REG_ADDR);
        if (status & BIT(1)) { // DONE
            break;
        }
        if (status & BIT(3)) { // ERROR
            uint32_t ecode = dma_read(SECURE_DMA_ERROR_CODE_REG_ADDR);
            simputshex32("DMA_STS=", status);
            simputshex32("DMA_EC=", ecode);
            simputshex32("DMA_DST=", dest);
            simputshex32("DMA_SRC=", src);
            simputshex32("DMA_LEN=", n);
            result = SEP_MSG_DMA_ERROR;
            break;
        }
    }

    // Restore remap if we disabled it.
    if (iccm_dest) {
        mmio_write32(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR, saved_region_size);
    }

    return result;
}

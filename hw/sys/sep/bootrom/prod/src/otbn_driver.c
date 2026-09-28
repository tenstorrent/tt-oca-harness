// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// OTBN hardware driver for OROM.
//
// Low-level driver for the OpenTitan OTBN coprocessor.
// Ported from fw/sep/tests/otbn_rsa_3072_verify_test with ROM adaptations:
//   - Uses mmio_read32/mmio_write32 (not WRITE_REG/READ_REG test macros)
//   - No printf; uses simputs/simputshex32 for debug output
//   - Bounded timeouts with error returns
//   - Freestanding (no libc)

#include "otbn_driver.h"

#include <stdbool.h>
#include <stddef.h>

#include "errors.h"
#include "rom_mmio.h"
#include "rsa_3072_app_otbn.h"
#include "sep.h"

// OTBN command register values.
#define OTBN_CMD_EXECUTE 0xD8u
#define OTBN_CMD_SEC_WIPE_DMEM 0xC3u

// OTBN status values.
#define OTBN_STATUS_IDLE 0x00u

// Timeout for OTBN operations (generous for RTL simulation).
#define OTBN_TIMEOUT 2000000

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

static int otbn_wait_idle(void) {
    for (int i = 0; i < OTBN_TIMEOUT; ++i) {
        if (mmio_read32(SEP_TOP_OTBN_STATUS_BASE_ADDR) == OTBN_STATUS_IDLE) return OTBN_OK;
    }
    simputs("OTBN_TIMEOUT\n");
    return OTBN_ERR_TIMEOUT;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int otbn_init(void) {
    // Entropy is a PREREQUISITE of this block, not something it brings up:
    // OTBN parks in UrndRefresh until EDN reseeds it. The caller establishes it
    // (see oca_platform.c) so this driver stays a hardware driver and does not
    // reach into another subsystem.
    // Release OTBN from SW reset.
    uint32_t rst = mmio_read32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    rst |= SEP_RESET_CTRL__SW_RESET_N__OTBN_SW_RST_N_bm;
    mmio_write32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, rst);
    __asm__ volatile("fence" ::: "memory");

    // Verify reset release stuck.
    if (!(mmio_read32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
          SEP_RESET_CTRL__SW_RESET_N__OTBN_SW_RST_N_bm)) {
        simputs("OTBN_RST_FAIL\n");
        return OTBN_ERR_NOT_IDLE;
    }

    // Wait for OTBN to be idle.
    int rc = otbn_wait_idle();
    if (rc != OTBN_OK) return rc;

    // Zero DMEM (768 visible 32-bit words = 3 KiB).
    for (uint32_t i = 0; i < 768u; ++i) {
        mmio_write32(SEP_TOP_OTBN_DMEM_BASE_ADDR + i * 4u, 0u);
    }

    // Reset load checksum.
    mmio_write32(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);

    return OTBN_OK;
}

int otbn_load_rsa_app(void) {
    // Load IMEM.
    for (uint32_t i = 0; i < otbn_rsa_3072_app_imem_words; ++i) {
        mmio_write32(SEP_TOP_OTBN_IMEM_BASE_ADDR + i * 4u, otbn_rsa_3072_app_imem[i]);
    }

    // Load DMEM (RSA constants: Montgomery parameters, etc.).
    for (uint32_t i = 0; i < otbn_rsa_3072_app_dmem_words; ++i) {
        mmio_write32(SEP_TOP_OTBN_DMEM_BASE_ADDR + i * 4u, otbn_rsa_3072_app_dmem[i]);
    }

    // Verify CRC if available.
    if (OTBN_RSA_3072_APP_EXPECTED_CRC != 0u) {
        uint32_t actual = mmio_read32(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR);
        if (actual != OTBN_RSA_3072_APP_EXPECTED_CRC) {
            simputshex32("OTBN_CRC_EXP=", OTBN_RSA_3072_APP_EXPECTED_CRC);
            simputshex32("OTBN_CRC_ACT=", actual);
            return OTBN_ERR_CRC;
        }
    }

    return OTBN_OK;
}

void otbn_dmem_write(uint32_t byte_offset, const uint32_t *data, uint32_t word_count) {
    for (uint32_t i = 0; i < word_count; ++i) {
        mmio_write32(SEP_TOP_OTBN_DMEM_BASE_ADDR + byte_offset + i * 4u, data[i]);
    }
}

void otbn_dmem_read(uint32_t byte_offset, uint32_t *data, uint32_t word_count) {
    for (uint32_t i = 0; i < word_count; ++i) {
        data[i] = mmio_read32(SEP_TOP_OTBN_DMEM_BASE_ADDR + byte_offset + i * 4u);
    }
}

int otbn_execute(void) {
    // Send execute command.
    mmio_write32(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);

    // Wait for completion.
    int rc = otbn_wait_idle();
    if (rc != OTBN_OK) return rc;

    // Check error bits.
    uint32_t err = mmio_read32(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    if (err != 0u) {
        simputshex32("OTBN_ERR=", err);
        return OTBN_ERR_EXEC;
    }

    return OTBN_OK;
}

/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Production ROM - Spec-Compliant Main Implementation
 *
 * Implementation following SMC ROM Boot Architecture Specification
 * for proper SMC initialization and boot flow.
 * SRAM initialization and protection status are handled in boot/sram_init.S
 */

#include <stdint.h>
#include "smc_prod_rom.h"
#include "smc_occp_error_codes.h"

/* picolibc exit() calls _exit(); provide a bare-metal stub that never returns. */
__attribute__((noreturn)) void _exit(int code) {
    (void)code;
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    /* Boot announcement */
    simputs("=== SMC Production ROM v1.0 ===\n");

    /* NOTE: MBIST and memory repair status validation has already been
     * performed in assembly startup code (__metal_mbist_early_check and
     * __metal_memory_repair_check) before any stack operations.
     * If we reach this point, memory integrity has been validated.
     * Scratchpad register 15 contains MBIST status (0x600DCAFE = passed). */

    /* Phase 0: Initialize POST codes and basic systems */
    smc_post_code_init();
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_INIT);
    smc_scratchpad_init();
    simputs("[MAIN] POST codes and scratchpad initialized\n");

    /* Initialize status reporting early */
    occp_status_init();
    smc_status_init();

    /* Set SEP safe SRAM offset for SEP scratchpad operations */
    smc_scratchpad_set_sep_safe_sram_offset(SEP_SAFE_SRAM_START, SEP_SAFE_SRAM_SIZE);
    simputs("[MAIN] SEP safe SRAM region information configured\n");
    /* Signal to SEP that SRAM initialization is complete (after status buffers are ready) */
    smc_scratchpad_signal_sram_init_complete();
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_SRAM_SETUP);
    smc_status_report(SMC_STATUS_TYPE_STATUS,
                      SMC_STATUS_COORDINATION_ACTIVE); // report smc-sep coordination active
    simputs("[MAIN] SRAM initialization status signaled to SEP\n");

    /* Report ROM startup */
    smc_status_report(SMC_STATUS_TYPE_STATUS, SMC_STATUS_ROM_STARTED); /* ROM started */

    /* Phase 1: Read straps and fuses */
    simputs("[MAIN] Reading hardware straps and fuses\n");

    smc_efuse_init();
    smc_strap_init();

    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_STRAP_FUSE);
    /* Check for invalid mode */
    if (smc_security_is_invalid_mode()) {
        simputs("[error] Device is in invalid mode\n");
        smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_ERROR);
        smc_post_code_set_error(POST_CODE_ERROR_INVALID_SEC_MODE);
        smc_status_report(SMC_STATUS_TYPE_ERROR,
                          SMC_STATUS_INVALID_SEC_MODE); /* Invalid security mode detected */
        while (true) {
            __asm__("wfi");
        }
    }

    uint8_t security_decisions = 0;
    if (smc_security_is_production_mode()) {
        security_decisions |=
            (uint8_t)(1U << (POST_CODE_SEC_PROD_MODE_BIT - POST_CODE_SECURITY_SHIFT));
        simputs("[MAIN] Device is in Production Mode\n");
    }
    if (smc_security_is_rma_sop_mode()) {
        security_decisions |=
            (uint8_t)(1U << (POST_CODE_SEC_RMA_SOP_BIT - POST_CODE_SECURITY_SHIFT));
        simputs("[MAIN] Device is in RMA SOP Mode\n");
    }

    if (smc_security_is_secure_mode()) {
        security_decisions |=
            (uint8_t)(1U << (POST_CODE_SEC_SECURE_MODE_BIT - POST_CODE_SECURITY_SHIFT));
        simputs("[MAIN] Device is in Secure Mode\n");
    } else {
        // if not post code secure mode bit set, its unsecure mode
        simputs("[MAIN] Device is in Non-Secure Mode\n");
    }
    smc_post_code_set_security_decisions(security_decisions);

    /* Optional PLL hook. The default weak implementation is a no-op. */
    if (smc_strap_is_bl0_pllclk_enabled()) {
        smc_pll_result_t pll_result = smc_pll_init();
        if (pll_result != SMC_PLL_SUCCESS) {
            simputs("[ERROR] PLL initialization failed: ");
            simputs(smc_pll_result_to_string(pll_result));
            simputs("\n");
            smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_ERROR);
            smc_post_code_set_error(POST_CODE_ERROR_INTERFACE);
            while (true) {
                __asm__("wfi");
            }
        }
    } else {
        simputs("[MAIN] BL0_PLLCLK strap deasserted - using reference clock\n");
    }

    /* Report boot sequence started after config/strap read */
    smc_status_report(SMC_STATUS_TYPE_STATUS,
                      SMC_STATUS_BOOT_START); /* Boot sequence started / Config read */

    /* Phase 2: SRAM Setup */
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_SRAM_SETUP);
    simputs("[MAIN] SRAM setup phase\n");

    /* Handle SRAM auto-zero based on straps */
    if (!smc_strap_is_sram_auto_zero_disabled()) {
        simputs("[MAIN] SRAM auto-zero enabled (strap controlled)\n");
        /* SRAM auto-zero would be handled by hardware/assembly startup */
    } else {
        simputs("[MAIN] SRAM auto-zero disabled by strap\n");
    }

    /* Phase 3: Interface Configuration */
    simputs("[MAIN] Interface configuration phase\n");

    smc_interface_map_init();
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_IFACE_CONFIG);

    /* Phase 4: OCCP Ready */
    simputs("[MAIN] Initializing OCCP interface\n");

    if (smc_occp_init() != 0) {
        simputs("[ERROR] OCCP initialization failed\n");
        smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_ERROR);
        smc_post_code_set_error(POST_CODE_ERROR_INTERFACE);
        smc_status_report(SMC_STATUS_TYPE_ERROR,
                          SMC_STATUS_OCCP_INIT_FAILED); /* OCCP init failed */
        while (true) {
            __asm__("wfi");
        }
    }
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_OCCP_READY);

    simputs("[MAIN] OCCP initialized successfully\n");
    smc_status_report(SMC_STATUS_TYPE_STATUS, SMC_STATUS_OCCP_READY); /* OCCP ready */

    /* Phase 5: OCCP Processing */
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_OCCP_PROC);
    simputs("[MAIN] Entering OCCP command processing loop\n");
    smc_status_report(SMC_STATUS_TYPE_STATUS, SMC_STATUS_BOOT_COMPLETE); /* Boot complete */

    /* Enter OCCP processing loop - this never returns */
    smc_occp_process();

    /* Should never reach here */
    smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_STATUS_UNEXPECTED_EXIT); /* Unexpected exit */
    while (true) {
        __asm__("wfi");
    }

    return 0;
}

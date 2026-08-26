/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// ROM main — SEP Boot ROM entry point.
//
// Freestanding (no libc). Machine-readable status reporting is always compiled
// in, while virtual-console debug text follows the ROM DEBUG build split:
// test builds enable DEBUG by default, release builds disable it by default.
// Runtime behavior is still controlled by strap bits and SMC registers.
//
// Debug text output uses virtual console (packed writes to SEP cold_scratch[2],
// decoded by cocotb monitor — same protocol when DEBUG is enabled).
// Machine-readable status codes are written to cold_scratch[1] using the status encoding.
// PASS/FAIL magic words use the mailbox (0x8000_0000) for SV testbench detection.
//
// Boot flow for the SEP BL0 sequence
// (see context/boot_flow/ocah_boot_flow.md for full task mapping):
//
//   [C0]    main() entry + runtime init check
//   [C2]    init_straps() → structured boot config
//   [C3]    status reporting init (strap-controlled)
//   [C1]    ROM version + hash print (hash filled at build time)
//   [C5]    PLL/clock init (strap-controlled)
//   [C6]    lifecycle policy
//   [C7]    chip ID identification (reads SMC CHIP_CONFIG_CHIP_ID)
//   [V3]    DFT / MEM_REPAIR gate (reads DFX_CTRL_STATUS_SMU)
//    —      peripheral/bus reset (reference suite-specific)
//   [C8]    crypto/security init
//   [C9a]   EXT SRAM clear
//   [C9b]   ICCM clear
//   [C9c]   init_bl0_state()
//   [C10b]  read sboot_dis fuse
//   [C16]   stack canary write
//   [C10c]  DMA init
//   [C11]   boot mode branch (SPI / recovery / secondary)
//    —      SMC scratch coordination
//   [C12–C14] manifest load / validate (retry loop)
//   [C13.10]  crypto validation (version/revocation/RSA-3072/decrypt/payload hash)
//   [C15]   demotion decisions + lock fuse secrets (KDF/measurement TODO)
//   [C17]   confirm fuse secrets locked
//   [C18]   BL1 handoff (copy → jump)
//   [C16]   stack canary check
//   [C19]   unified error convergence (rom_err_fail)

#include <stdbool.h>
#include <stdint.h>

#include "bl0_state.h"
#include "boot_straps.h"
#include "oca_boot.h"
#include "pll_init.h"
#include "errors.h"
#include "rom_mbx.h"
#include "rom_smc.h"
#include "fuse_lock.h"
#include "hmac_sha256.h"
#include "lifecycle.h"
#include "sep_dma.h"
#include "sep_spi.h"
#include "boot_flash.h"

extern const char g_rom_version[];
extern const char g_rom_sha256_str[];

// C trap handler called from vector.S trap_vector.
// Prints CSR values as hex for debug visibility, then signals FAIL.
__attribute__((noreturn)) void trap_handler_c(uint32_t mcause, uint32_t mepc, uint32_t mtval,
                                              uint32_t mstatus) {
    simputs("TRAP H0\n");
    simputshex32("MC=", mcause);
    simputshex32("PC=", mepc);
    simputshex32("MV=", mtval);
    simputshex32("MS=", mstatus);

    volatile uint32_t *mbx = (volatile uint32_t *)0x80000000;
    *mbx = 0xA5A55A5Au;
    *mbx = 0xDEADBEEFu;

    for (;;) {
        __asm__ volatile("wfi");
    }
}

// C runtime validation:
// - `g_data_init` lives in .data and must be initialized by vector.S copy loop.
// - `g_bss_zero` lives in .bss and must be zeroed by vector.S.
static volatile uint32_t g_data_init = 0x12345678u;
static volatile uint32_t g_bss_zero;

// Warm reset is handled in vector.S (V2):
// - vector.S reads sep_scratch_warm_scratch[0] (0x10A32080) early,
//   before touching DCCM (sp/scrub/.data/.bss), to preserve BL1 state.
// - If warm_scratch[0] contains a valid SRAM address, vector.S poisons
//   it (writes 0) and jumps directly to the warm handler.
// - If we reach rom_main(), it's always a cold boot (warm_scratch already
//   poisoned by vector.S on both warm and cold paths).
//
// The SEP scratch registers used:
//   warm_scratch[0] @ 0x10A32080: warm reset handler pointer (survives warm reset)
//   cold_scratch[0] @ 0x10A32000: ROM status (cleared on any reset)

#ifndef ROM_SPI_SYSCLK_MHZ
#define ROM_SPI_SYSCLK_MHZ 25u
#endif

// SPI init failure is no longer fatal.
// Kept as documentation of the previous approach.
// #define ROM_FAIL_ON_SPI_INIT_ERROR 0

// SEP scratch register addresses (from sep.h).
#include "sep.h"

// Placeholder addresses until DFT status window is finalized.
#ifndef ROM_DFT_STATUS_ADDR
#define ROM_DFT_STATUS_ADDR 0u
#endif

#ifndef ROM_DFT_POLICY_FUSE_ADDR
#define ROM_DFT_POLICY_FUSE_ADDR 0u
#endif

// ICCM/IRAM clear configuration.
#ifndef ROM_ICCM_BASE
#define ROM_ICCM_BASE 0u
#endif

#ifndef ROM_ICCM_SIZE_BYTES
#define ROM_ICCM_SIZE_BYTES 0u
#endif

// Stack canary for C16 stack health check.
// Written at __stack_bottom (lowest address of stack) after bl0_state init.
// Verified before PASS to detect stack overflow during boot.
#define STACK_CANARY_VALUE 0xDEAD5741u // 'STA\xDE' (stack guard)
extern uint8_t __stack_bottom[];       // defined in linker script

enum {
    ROM_ERR_RUNTIME_INIT_FAILED = 0x0000B001u,
    ROM_ERR_DFT_GATE_BLOCKED = 0x0000D001u,
    ROM_ERR_SMC_COORD_NOT_READY = 0x0000C001u,
    ROM_ERR_SPI_INIT_FAILED = 0x0000E001u,
    ROM_ERR_STACK_OVERFLOW = 0x0000F001u,
    ROM_ERR_CRYPTO_SELFTEST_FAILED = 0x0000F002u,
    ROM_ERR_FUSE_SECRETS_NOT_LOCKED = 0x0000F003u,
};

// ── [C19] Unified error convergence ──
// All ROM error paths converge here.  Records the error in:
// - BL0 state (error_code field, for BL1/debugger)
// - cold_scratch[1] (for debugger/DV visibility)
// - mailbox (FAIL + code, for DV monitor)
// Then hangs (wfi loop).
__attribute__((noreturn)) static void rom_err_fail(uint32_t error_code);

// Non-static wrapper for rom_err_fail(), callable from lifecycle.c.
__attribute__((noreturn)) void rom_err_fail_ext(uint32_t error_code) {
    rom_err_fail(error_code);
}

__attribute__((noreturn)) static void rom_err_fail(uint32_t error_code) {
    // Record in bl0_state if initialized.
    struct bl0_state *s = get_bl0_state();
    if (s->start_magic == BL0_STATE_MAGIC) {
        s->error_code = error_code;
    }

    // Record in cold_scratch[1] for debugger visibility (STATUS_ENCODE format).
    STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_ERROR, error_code & 0xFFFF));

    // Standard FAIL sequence via mailbox.
    rom_mbx_fail_and_hang(error_code);
}

static inline void rom_check_runtime_init_or_fail(void) {
    if (g_data_init != 0x12345678u || g_bss_zero != 0u) {
        rom_err_fail(ROM_ERR_RUNTIME_INIT_FAILED);
    }
}

// Quick sanity check: write a pattern to SMC scratch[7] (unused), read back,
// and verify the SVT slave memory round-trips correctly.
static void rom_smc_mem_sanity_check(void) {
    static const uint32_t patterns[] = {0xA5A55A5Au, 0x12345678u, 0x00000000u, 0xFFFFFFFFu};
    const int n = (int)(sizeof(patterns) / sizeof(patterns[0]));

    simputs("SMC_MEM_CHK\n");
    simputshex32("SMC_BASE=", sep_get_smc_base());
    for (int i = 0; i < n; i++) {
        smc_scratch_write(7, patterns[i]);
        uint32_t rb = smc_scratch_read(7);
        if (rb != patterns[i]) {
            simputshex32("SMC_MEM_EXP=", patterns[i]);
            simputshex32("SMC_MEM_GOT=", rb);
            simputs("SMC_MEM_FAIL\n");
            rom_err_fail(0x0000A001u);
        }
    }
    // Clean up
    smc_scratch_write(7, 0u);
    simputs("SMC_MEM_OK\n");
}

static void rom_smc_coordination_probe(void) {
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_SMC_COORD_CHECK);
    const uint32_t smc_status = smc_scratch_read(SMC_SCRATCH_STATUS_TO_SEP_IDX);
    const uint32_t manifest_off = smc_scratch_read(SMC_SCRATCH_MANIFEST_ADDR_IDX);
    const uint32_t status_buf_off = smc_scratch_read(SMC_SCRATCH_STATUS_BUFFER_ADDR_IDX);

    simputshex32("SMC_STATUS_TO_SEP=", smc_status);
    simputshex32("MANIFEST_OFF=", manifest_off);
    simputshex32("STATUS_BUF_OFF=", status_buf_off);

    if ((smc_status & SMC_SEP_STATUS_MANIFEST_READY) == 0u) {
        simputs("SMC_COORD_NOT_READY\n");
        return;
    }

    if (manifest_off == 0xFFFFFFFFu) {
        simputs("SMC_MANIFEST_OFF_INVALID\n");
        return;
    }

    const uint32_t manifest_addr = sep_get_smc_sram_base() + manifest_off;
    simputshex32("SMC_MANIFEST_ADDR=", manifest_addr);
}

// Write boot status to SEP cold_scratch[0] for debugger/DV visibility.
static inline void rom_write_cold_scratch_status(uint32_t value) {
    mmio_write32(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0), value);
}

static void rom_iccm_clear(void) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_ICCM_CLEAR_START);
    simputshex32("ICCM_BASE=", ROM_ICCM_BASE);
    simputshex32("ICCM_SIZE=", ROM_ICCM_SIZE_BYTES);
    volatile uint32_t *p = (volatile uint32_t *)ROM_ICCM_BASE;
    uint32_t words = ROM_ICCM_SIZE_BYTES / 4u;
    for (uint32_t i = 0; i < words; ++i) {
        p[i] = 0u;
        if ((i & 0x3FFF) == 0) {
            simputshex32("ICCM_CLR_PROG=", i * 4u);
        }
    }
    report_status(STATUS_TYPE_INFO, SEP_MSG_ICCM_CLEAR_DONE);
    simputs("ICCM_CLR_OK\n");
}

static void rom_peripheral_reset(void) {
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_PERIPH_BUS_RESET_CHECK);
    // TODO: implement peripheral/bus reset sequencing when hardware is ready.
    simputs("PERIPH_RST_TODO\n");
}

static void rom_crypto_init(void) {
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_CRYPTO_INIT_CHECK);
    // SHA-256 self-test: compute SHA-256("abc") and compare against NIST vector.
    // Same vector validated by fw/sep/tests/hmac_test/hmac_test.c.
    {
        static const uint8_t test_msg[] = {'a', 'b', 'c'};
        static const uint8_t expected[32] = {
            0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40,
            0xde, 0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17,
            0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad,
        };
        uint8_t digest[32];

        if (sha256(test_msg, sizeof(test_msg), digest) != 0) {
            simputs("CRYPTO_SELFTEST_TIMEOUT\n");
            rom_err_fail(ROM_ERR_CRYPTO_SELFTEST_FAILED);
        }

        for (int i = 0; i < 32; ++i) {
            if (digest[i] != expected[i]) {
                simputs("CRYPTO_SELFTEST_MISMATCH\n");
                rom_err_fail(ROM_ERR_CRYPTO_SELFTEST_FAILED);
            }
        }
        simputs("CRYPTO_SELFTEST_OK\n");
    }
}

static void rom_mem_clear(void) {
    // Status reports are inside rom_clear_ext_sram() itself.
    rom_clear_ext_sram();
}

static void rom_dma_init(void) {
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_DMA_INIT_CHECK);
    sep_dma_init();
    simputs("DMA_INIT_OK\n");
}

// SPI init — strap-aware: only called when boot_from_spi() is true.
// Returns SPI init status (0 = success, non-zero = failure).
// SPI init failure is NOT fatal — the manifest
// retry loop skips the primary manifest when spi_status != 0.
static uint32_t rom_spi_init(const struct boot_straps *straps, uint16_t sysclk_mhz) {
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_SPI_INIT_CHECK);
    simputsdec24("SPI_ROTATE=", straps->rotate_update);

    const uint32_t err = boot_flash_init(straps, sysclk_mhz);
    if (err != 0u) {
        simputshex32("SPI_INIT_ERR=", err);
        simputs("BL0: spi init failed\n");
        return err;
    }

#if !BOOT_SPI_CONTROLLER_OT
    // The Cadence path caches a PHY-tuning TLV whose primary slot may fail to
    // load; the OpenTitan controller has no TLV, so this only applies there.
    if (spi_primary_tlv_failed()) {
        simputs("SPI_PRIMARY_TLV_FAILED\n");
    }
#endif
    simputs("SPI_INIT_OK\n");
    return 0;
}

// Manifest load → validate → handoff sequence.
// Loads manifest via DMA from SPI/SMC SRAM, validates structure,
// locks fuse secrets, and hands off to BL1.
// spi_status: result of spi_init(); non-zero skips the primary manifest retry.
static void rom_manifest_validate_handoff(const struct boot_straps *straps, uint32_t spi_status) {
    // ── [C12–C14] manifest load ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_LOAD_START);
    uint32_t mfst_err = rom_manifest_boot(straps, spi_status);
    if (mfst_err != 0u) {
        simputshex32("MANIFEST_BOOT_FAIL=", mfst_err);
        rom_err_fail(mfst_err);
    }

    // ── [C13.10] crypto validation ──
    // No separate step under OCA: signature verification, key revocation,
    // anti-rollback, payload decryption and the payload hash chain are all part
    // of the staged sequence rom_manifest_boot() just completed, and a failure
    // in any of them has already been reported and returned above. Keeping the
    // SBOOT_OFF marker because DV asserts its absence on the secure-boot test.
    if (!get_bl0_state()->secure_boot) {
        simputs("SBOOT_OFF\n");
    }

    // ── [C15] Demotion decisions ──
    // Demotion decision flow:
    //   DEMOTE_1: BL1 demotion register
    //   DEMOTE_2: BL2 demotion register (written by BL1, not BL0)
    //
    // Logic:
    //   PROD_END: never demote, lock both registers.
    //   BL1 selector set: demotion_reg = usage_constraints flag, lock DEMOTE_1.
    //   BL2 deferred: store decision in bl0_state for BL1/KDF, do NOT write
    //     or lock DEMOTE_1 in the deferred BL2 case.
    //   DEMOTE_2 is never written by BL0 (except PROD_END lock).
    {
        uint32_t lc_st = get_bl0_state()->lc_state;

        if (lc_st == LC_STATE_PROD_END) {
            // PROD_END: never demote, always lock both registers.
            lc_write_demotion(false, true);
            lc_write_demotion_2(false, true);
            simputs("DEMOTE: PROD_END lock\n");
        } else {
            // OCA folds both halves of this decision into one 16-bit
            // demotion_control field, where the old format split them across
            // usage_constraints.selector_bits (is it specified) and
            // boot_arguments.flag_args (what is the value). The VALID bit is
            // the "specified" half; the ENABLE bit is the value.
            uint32_t dc = rom_oca_demotion_control();
            bool bl2_demote = (dc & OCA_DEMOTE_BL2_ENABLE) != 0u;

            if (dc & OCA_DEMOTE_BL1_VALID) {
                // BL1 manifest decides demotion: write DEMOTE_1 + lock.
                bool bl1_demote = (dc & OCA_DEMOTE_BL1_ENABLE) != 0u;
                lc_write_demotion(bl1_demote, true);
                simputsdec24("BL1_DEMOTE=", bl1_demote);
            } else {
                // BL2 deferred: do NOT write or lock DEMOTE_1.
                simputs("DEMOTE: BL2 deferred\n");
            }

            // Store BL2 demotion decision in bl0_state (for KDF/measurement).
            // DEMOTE_2 is NOT written by BL0; BL1 handles it.
            get_bl0_state()->bl2_demotion_decision = bl2_demote;
            simputsdec24("BL2_DEMOTE_DEC=", bl2_demote);
        }
    }

    // ── [C15] Lock fuse secrets ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SECRETS_LOCK);
    lock_fuse_secrets();

    // ── [C17] Confirm fuse secrets locked ──
    // Failure to confirm the lock state is fatal.
    if (!check_fuse_secrets_locked()) {
        report_status(STATUS_TYPE_ERROR, SEP_MSG_FUSE_SECRETS_NOT_LOCKED);
        rom_err_fail(ROM_ERR_FUSE_SECRETS_NOT_LOCKED);
    }
    report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SECRETS_LOCKED);

    // ── [C18] BL1 handoff ──
    {
        report_status(STATUS_TYPE_DEBUG, SEP_MSG_HANDOFF_CHECK);
        // Body and payload are staged in SEP EXT SRAM by rom_manifest_boot();
        // the handoff reaches them through the rom_oca_* accessors.
        uint32_t ho_err = rom_handoff_bl1();
        // rom_handoff_bl1 does not return on success; if we get here, it failed.
        rom_err_fail(ho_err);
    }
}

static void dft_mem_repair_gate(void) {
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_DFT_GATE_CHECK);
    /* Read DFX_CTRL_STATUS_SMU register. */
    const uint32_t dft_status = smc_read_dft_status();
    simputshex32("DFT_STATUS=", dft_status);

    /* Check mem_repair_success (bit 1). */
    if (dft_status & DFT_STATUS_MEM_REPAIR_SUCCESS_MASK) {
        /* Success — continue boot. */
        return;
    }

    /* MEM_REPAIR failure: dump raw value to scratch[10] for debugger. */
    smc_scratch_write(SMC_SCRATCH_MBIST_FAILURE_IDX, dft_status);

    /* Emit warning status. */
    report_status(STATUS_TYPE_WARN, SEP_MSG_MBIST_FAIL);
    simputs("MEM_REPAIR_FAIL\n");

    /* Check bypass strap (bit 13 of STRAPS_LO). */
    const uint32_t straps_lo = smc_read_straps_lo();
    if (straps_lo & SMC_STRAP_MEM_REPAIR_BYPASS_MASK) {
        simputs("MEM_REPAIR_BYPASS\n");
        return;
    }

    /* No bypass — halt. */
    rom_err_fail(ROM_ERR_DFT_GATE_BLOCKED);
}

// Report the ROM hash prefix via the status ring.
// Emits SEP_MSG_ROM_HASH followed by the first 4 hex chars (2 × uint16_t)
// of the hash for machine-readable consumption by DV/debugger.
static uint8_t char_to_int(char c) {
    if (c >= '0' && c <= '9')
        return (uint8_t)(c - '0');
    else if (c >= 'a' && c <= 'f')
        return (uint8_t)(c - 'a' + 10);
    else
        return 0;
}

static void report_rom_hash(void) {
    const uint8_t *p = (const uint8_t *)g_rom_sha256_str;

    report_status(STATUS_TYPE_INFO, SEP_MSG_ROM_HASH);

    // Skip "sha256:" prefix (7 chars).
    p += 7;

    // Report first 4 hex chars as two 16-bit status words.
    for (int i = 0; i < 2; i++, p += 4) {
        uint16_t val = 0;
        val = (uint16_t)(char_to_int((char)p[0]) << 12);
        val |= (uint16_t)(char_to_int((char)p[1]) << 8);
        val |= (uint16_t)(char_to_int((char)p[2]) << 4);
        val |= (uint16_t)(char_to_int((char)p[3]));
        report_status(STATUS_TYPE_INFO_EXT, val);
    }
}

// Status reporting init (strap-controlled).
// If the disable strap is set, skip reporting; otherwise initialize the ring buffer.
static void rom_status_reporting_init(const struct boot_straps *straps) {
    if (straps->status_report_disable) {
        STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_STATUS_REPORTING_DISABLED));
        simputs("STATUS_RPT_DISABLED\n");
        return;
    }

    STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_STATUS_REPORTING_ENABLED));
    simputs("STATUS_RPT_ENABLED\n");

    // Wait for the shared status path, then initialize status reporting.
    init_status_reporting();
}

void rom_main(void) {

    // ── [C0] main() entry ──
    STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_BOOTROM_START_MAIN));

    // ── [C0] runtime init check (g_data_init / g_bss_zero) ──
    rom_check_runtime_init_or_fail();
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_RUNTIME_INIT_OK);

    // ── SVT slave memory sanity check (write-read-back via SMC scratch[7]) ──
    rom_smc_mem_sanity_check();

    simputs("ROM\n");
    // ── [C1] ROM version + hash print (hash filled by build-time insert-rom-sha256.py) ──
    simputs(g_rom_version);
    simputs(g_rom_sha256_str);
    simputs("\n");
    report_rom_hash();

    // ── Cold boot (warm reset is handled in vector.S) ──
    // If we reach rom_main(), vector.S already determined this is a cold boot
    // (warm_scratch[0] was zero or out-of-range, and has been cleared).
    simputs("COLD\n");
    rom_write_cold_scratch_status(0x434F4C44u); // 'COLD' marker in cold_scratch[0]

    // Memory init checkpoint (DCCM scrub + .data/.bss init done in vector.S).
    simputs("MEM_INIT_OK\n");

    // ── [C2] init_straps → structured boot config ──
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_DEVICE_MODE_INPUTS_CHECK);
    struct boot_straps straps;
    init_straps(&straps);

    // ── [C3] Status reporting init (strap-controlled) ──
    rom_status_reporting_init(&straps);

    // ── [C5] PLL/Clock init (strap-controlled) ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_PLL_CLK_INIT);
    uint16_t smu_freq_mhz = pll_init(straps.bl0_pll_clk);
    report_status(STATUS_TYPE_INFO_EXT, smu_freq_mhz);
    simputshex32("SYS_CLK_MHZ=", (uint32_t)smu_freq_mhz);

    // ── [C6] Lifecycle policy ──
    // rom_lifecycle_policy() reads efuse, validates, and records in bl0_state.
    // Returns the decoded LC state (does not return on invalid).
    uint32_t lc_state = rom_lifecycle_policy();

    // ── [C7] Chip ID identification ──
    // Read CHIP_CONFIG_CHIP_ID from the SMC chip_config
    // block and report for DV/debugger visibility.
    {
        report_status(STATUS_TYPE_DEBUG, SEP_MSG_CHIP_ID_CHECK);
        const uint32_t chip_id = smc_read_chip_id();
        report_status(STATUS_TYPE_INFO_EXT, (uint16_t)(chip_id & 0xFFFFu));
        simputshex32("CHIP_ID=", chip_id);
    }

    // ── [V3] DFT / MBIST / MEM_REPAIR boot-gating (reads DFX_CTRL_STATUS register) ──
    dft_mem_repair_gate();

    // ── Peripheral/Bus reset sequencing (reference suite-specific) ──
    rom_peripheral_reset();

    // ── [C8] Crypto/security init ──
    rom_crypto_init();

    // ── [C9a] EXT SRAM clear ──
    simputs(">>C9a_SRAM_CLR\n");
    rom_mem_clear();
    simputs("<<C9a_SRAM_CLR\n");

    // ── [C9b] ICCM clear ──
    simputs(">>C9b_ICCM_CLR\n");
    rom_iccm_clear();
    simputs("<<C9b_ICCM_CLR\n");

    // ── [C9c] BL0 state init ──
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_BL0_STATE_INIT);
    init_bl0_state();
    simputs("BL0_STATE_OK\n");

    // ── [C10b] Read sboot_dis fuse ──
    // Read the SBOOT_DIS efuse shadow register.
    // Chicken bit to disable secure boot (bit 0 of SEP_EFUSE_MAP_SBOOT_DIS).
    {
        uint32_t sboot_dis_reg = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR);
        bool sboot_dis = (sboot_dis_reg & SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm) != 0u;
        get_bl0_state()->sboot_dis = sboot_dis;
        simputsdec24("FUSE: SBOOT_DIS: ", sboot_dis);
        report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SBOOT_DIS);
        report_status(STATUS_TYPE_INFO_EXT, sboot_dis);
    }

    // ── [C16] Stack canary write ──
    // Place canary at __stack_bottom (lowest stack address, just above .bss).
    // Checked before PASS to detect stack overflow during boot.
    *(volatile uint32_t *)__stack_bottom = STACK_CANARY_VALUE;

    // ── [C10c] DMA init ──
    rom_dma_init();

    // ── [C11] Boot mode branch (SPI / recovery / secondary) ──
    // spi_status tracks SPI init result (0 = OK); used by the manifest retry loop
    // to skip the primary manifest on SPI failure.
    uint32_t spi_status = 0;
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_BOOT_MODE);
    {
        struct bl0_state *bs = get_bl0_state();
        if (boot_from_spi(&straps)) {
            // Primary chiplet, normal mode: boot from SPI flash.
            report_status(STATUS_TYPE_INFO, SEP_MSG_PRIMARY_CHIPLET);
            bs->boot_mode = BOOT_MODE_SPI;
            simputs("BOOT_SPI\n");

            // Report the rotate_update strap value.
            report_status(STATUS_TYPE_INFO, SEP_MSG_ROTATE_UPDATE);
            report_status(STATUS_TYPE_INFO_EXT, straps.rotate_update);

            // SPI init (now uses strap-derived rotate and PLL-derived sysclk).
            simputs(">>SPI_INIT\n");
            spi_status = rom_spi_init(&straps, smu_freq_mhz);
            simputs("<<SPI_INIT\n");
        } else if (straps.primary_chiplet && straps.boot_recovery) {
            // Primary chiplet, recovery mode: wait for manifest from SMC SRAM.
            report_status(STATUS_TYPE_INFO, SEP_MSG_PRIMARY_CHIPLET);
            report_status(STATUS_TYPE_INFO, SEP_MSG_BOOT_RECOVERY);
            bs->boot_mode = BOOT_MODE_RECOVERY;
            simputs("BOOT_RECOVERY\n");
        } else {
            // Secondary chiplet: wait for manifest from SMC SRAM.
            report_status(STATUS_TYPE_INFO, SEP_MSG_SECONDARY_CHIPLET);
            bs->boot_mode = BOOT_MODE_SECONDARY;
            simputs("BOOT_SECONDARY\n");
        }
    }

    // SMC scratch coordination (manifest/status buffer handoff).
    rom_smc_coordination_probe();

    // ── [C12–C14] Manifest load / validate + [C15/C17] fuse lock + [C18] handoff ──
    rom_manifest_validate_handoff(&straps, spi_status);

    // ── [C16] Stack canary check ──
    // Verify the canary placed at __stack_bottom is still intact.
    // If corrupted, the stack overflowed into .bss — fatal error.
    if (*(volatile uint32_t *)__stack_bottom != STACK_CANARY_VALUE) {
        rom_err_fail(ROM_ERR_STACK_OVERFLOW);
    }

    // ── Done ──
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_ROM_MAIN_BEFORE_PASS);

    rom_mbx_putw(ROM_FW_MAGIC0);
    rom_mbx_putw(ROM_FW_PASS);

    // If DV doesn't stop CPU immediately on fw_done, park here.
    for (;;) {
        __asm__ volatile("wfi");
    }
}

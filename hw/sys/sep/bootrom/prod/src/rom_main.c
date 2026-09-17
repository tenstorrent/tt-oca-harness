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
// The terminal verdict is a single word in cold_scratch[0] (errors.h VERDICT_OUT);
// the ROM only ever reports FAIL there, since a successful boot ends in BL1.
//
// Boot flow for the SEP BL0 sequence
//
//   [S01]  reset entry + warm-reset detection      | vector.S
//   [S02]  PMP execution fences                    | vector.S
//   [S03]  DFT / MEM_REPAIR gate                   | vector.S, before the DCCM scrub
//   [S04]  main() entry + runtime init check
//   [S05]  ROM version + hash print (hash filled at build time)
//   [S06]  init_straps() → structured boot config
//   [S07]  status reporting init (strap-controlled)
//   [S08]  fuse-sense readiness (gates every fuse read)
//   [S09]  PLL/clock init (strap-controlled)
//   [S10]  init_bl0_state()   (must precede every bl0_state writer)
//   [S11]  lifecycle policy
//   [S12]  chip ID identification (reads SMC CHIP_CONFIG_CHIP_ID)
//   [S13]  peripheral/bus reset
//   [S14]  crypto/security init
//   [S15]  EXT SRAM clear
//   [S16]  ICCM clear
//   [S17]  ROM self-hash → measurement slot 0
//   [S18]  read sboot_dis fuse
//   [S19]  stack canary write
//   [S20]  DMA init
//   [S21]  boot mode branch (SPI / recovery / secondary)
//   [S22]  SMC scratch coordination
//   [S23]  manifest load / validate (retry loop)
//   [S24]  crypto validation (version/revocation/RSA-3072/decrypt/payload hash)
//   [S25]  demotion decisions + lock fuse secrets
//   [S26]  confirm fuse secrets locked
//   [S27]  boot-state record → measurement slot 1
//   [S28]  stack canary check -- before [S29], which does not return
//   [S29]  BL1 handoff (copy → jump); BL1 signals PASS, not BL0
//   [S30]  unified error convergence (rom_err_fail)

#include <stdbool.h>
#include <stdint.h>

#include "bl0_state.h"
#include "boot_straps.h"
#include "oca_boot.h"
#include "pll_init.h"
#include "errors.h"
#include "rom_smc.h"
#include "fuse_lock.h"
#include "hmac_sha256.h"
#include "lifecycle.h"
#include "measurement.h"
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

    // On the store / non-blocking-load error NMI, mcause and mtval say almost
    // nothing: the NMI vectors to SEP_NMI_VEC (0xC0000100) and mtval reads back
    // zero, so a bad store is indistinguishable from any other fault. VeeR latches
    // the offending D-bus address in mdseac (0xFC0) and refines the cause in
    // mscause (0x7FF); printing both turns "the ROM died somewhere" into an
    // address. MADDR= is the staged manifest pointer, the field most likely to be
    // the bad address.
    {
        uint32_t mdseac, mscause;
        __asm__ volatile("csrr %0, 0xFC0" : "=r"(mdseac));
        __asm__ volatile("csrr %0, 0x7FF" : "=r"(mscause));
        simputshex32("DSEAC=", mdseac);
        simputshex32("MSC=", mscause);
        simputshex32("MADDR=", get_bl0_state()->sep_sram_manifest_addr);
    }

    // Verdict on cold_scratch[0], matching what trap_vector_early in vector.S
    // already does -- a fault here and a fault there leave the same evidence.
    rom_test_fail();

    for (;;) {
        __asm__ volatile("wfi");
    }
}

// C runtime validation:
// - `g_data_init` lives in .data and must be initialized by vector.S copy loop.
// - `g_bss_zero` lives in .bss and must be zeroed by vector.S.
static volatile uint32_t g_data_init = 0x12345678u;
static volatile uint32_t g_bss_zero;

// Warm reset is handled in vector.S ([S01]):
// - vector.S reads cold_scratch[7] early,
//   before touching DCCM (sp/scrub/.data/.bss), to preserve BL1 state.
// - A valid ICCM address transfers directly to the warm handler and remains
//   intact for subsequent watchdog resets.
// - A zero slot selects cold boot; the cold path then poisons it with -1.
// - An invalid nonzero slot stops in vector.S.
//
// The SEP scratch registers used:
//   cold_scratch[7]: warm reset handler pointer (survives watchdog reset)
//   cold_scratch[0]: terminal ROM verdict

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
#define ROM_ICCM_BASE ((uint32_t)OCH_SEP_TOP_SEP_ICCM_BASE_ADDR)
#endif

#ifndef ROM_ICCM_SIZE_BYTES
#define ROM_ICCM_SIZE_BYTES ((uint32_t)OCH_SEP_TOP_SEP_ICCM_SIZE)
#endif

// MUST be 1 for release. Off here only because the clear costs ~1.84M cycles in
// simulation; the Makefile carries the full reasoning and the residual risk.
#ifndef ROM_ICCM_CLEAR_ENABLE
#define ROM_ICCM_CLEAR_ENABLE 0
#endif

// Stack canary for the [S28] stack health check.
// Written at __stack_bottom (lowest address of stack) after bl0_state init.
// Verified before PASS to detect stack overflow during boot.
#define STACK_CANARY_VALUE 0xDEAD5741u // 'STA\xDE' (stack guard)
extern uint8_t __stack_bottom[];       // defined in linker script
extern uint8_t __stack_top[];          // defined in linker script

enum {
    ROM_ERR_RUNTIME_INIT_FAILED = 0x0000B001u,
    // Retained for the error-code space only; the MEM_REPAIR gate moved to
    // vector.S and reports STATUS_ENCODE(ERROR, SEP_MSG_MBIST_FAIL) directly,
    // since rom_err_fail() needs a C stack that does not exist that early.
    ROM_ERR_DFT_GATE_BLOCKED = 0x0000D001u,
    ROM_ERR_SMC_COORD_NOT_READY = 0x0000C001u,
    ROM_ERR_SPI_INIT_FAILED = 0x0000E001u,
    ROM_ERR_STACK_OVERFLOW = 0x0000F001u,
    ROM_ERR_CRYPTO_SELFTEST_FAILED = 0x0000F002u,
    ROM_ERR_FUSE_SECRETS_NOT_LOCKED = 0x0000F003u,
    // 0x0000F004 is ROM_ERR_HANDOFF_SELFCHECK_FAILED in the spec's registry,
    // reserved here for the pre-hand-off self-check that has not landed yet.
    ROM_ERR_ROM_HASH_MISMATCH = 0x0000F005u,
    ROM_ERR_MEASUREMENT_FAILED = 0x0000F006u,
    ROM_ERR_BL0_STATE_OVERLAPS_STACK = 0x0000F007u,
};

// ── [S30] Unified error convergence ──
// All ROM error paths converge here.  Records the error in:
// - BL0 state (error_code field, for BL1/debugger)
// - cold_scratch[1] (the code, for debugger/DV visibility)
// - cold_scratch[0] (the FAIL verdict, which DV gates on)
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
    //
    // Only for codes that ARE status values. A subsystem error carries its
    // subsystem in the upper half (manifest errors are 0x0003xxxx), and
    // truncating one to 16 bits lands it in the SEP_MSG_* numbering space where
    // it decodes as an unrelated message: MANIFEST_ERR 0x00030012 came out as
    // "SEP_MSG_BL1_SIZE_INVALID" on a payload-hash failure. Every such path has
    // already reported its own specific ERROR status, so the truncated word adds
    // nothing and actively misleads. The full 32-bit code still reaches the
    // mailbox below, so DV loses no information.
    if ((error_code & 0xFFFF0000u) == 0u) {
        STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_ERROR, error_code & 0xFFFF));
    }

    // Verdict on cold_scratch[0] -- the channel DV gates on. The error code is
    // NOT repeated here; it is already on cold_scratch[1] above, which is what
    // lets the verdict register stay single-valued.
    rom_test_fail();

    // Terminal: a ROM error is not recoverable, so stop rather than return into
    // a caller that has no way to handle it.
    for (;;) {
        __asm__ volatile("wfi");
    }
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

static void rom_iccm_clear(void) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_ICCM_CLEAR_START);
    simputshex32("ICCM_BASE=", ROM_ICCM_BASE);
    simputshex32("ICCM_SIZE=", ROM_ICCM_SIZE_BYTES);

    // ICCM powers up with random contents and random ECC, and the IFU fetches
    // 64 bits at a time, so any word it reads must have been written first.
    // ROM_ICCM_CLEAR_FULL scrubs the whole region here; otherwise the hand-off
    // establishes ECC over BL1's image and a pad past its end.
    //
    // The fill goes through the DMA because the CPU cannot store to ICCM: ICCM
    // shares VeeR region 0xC with DCCM, so every ICCM address faults as
    // unmapped. sep_dma_zero() also handles the address remap ICCM needs.
#if ROM_ICCM_CLEAR_ENABLE && ROM_ICCM_CLEAR_FULL
    sep_dma_init();
    uint32_t err = sep_dma_zero(ROM_ICCM_BASE, ROM_ICCM_SIZE_BYTES);
    if (err) {
        simputs("ICCM_CLR_FAIL\n");
        rom_err_fail(err);
    }
    simputs("ICCM_CLR_FULL\n");
#elif ROM_ICCM_CLEAR_ENABLE
    simputs("ICCM_CLR_HANDOFF\n");
#else
    simputs("ICCM_CLR_SKIP\n");
#endif
    report_status(STATUS_TYPE_INFO, SEP_MSG_ICCM_CLEAR_DONE);
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
__attribute__((noreturn)) static void rom_manifest_validate_handoff(
    const struct boot_straps *straps, uint32_t spi_status, uint32_t lc_state) {
    // ── [S23] manifest load ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_LOAD_START);
    uint32_t mfst_err = rom_manifest_boot(straps, spi_status);
    if (mfst_err != 0u) {
        simputshex32("MANIFEST_BOOT_FAIL=", mfst_err);
        rom_err_fail(mfst_err);
    }

    // ── [S24] crypto validation ──
    // No separate step under OCA: signature verification, key revocation,
    // anti-rollback, payload decryption and the payload hash chain are all part
    // of the staged sequence rom_manifest_boot() just completed, and a failure
    // in any of them has already been reported and returned above. Keeping the
    // SBOOT_OFF marker because DV asserts its absence on the secure-boot test.
    if (!get_bl0_state()->secure_boot) {
        simputs("SBOOT_OFF\n");
    }

    // ── [S25] Demotion decisions ──
    //   DEMOTE_1: BL1 demotion register, BL0's to write.
    //   DEMOTE_2: BL2 demotion register, BL1's to write (except the PROD_END lock).
    //
    // Logic:
    //   PROD_END: never demote; DEMOTE_2 locked here, DEMOTE_1 by the defaults below.
    //   BL1 demotion valid: DEMOTE_1 takes the manifest's value and is locked.
    //   BL2 requested demotion: DEMOTE_1 left unlocked so BL2 can apply it. This
    //     is the ONLY case in which the register is left open.
    //   Otherwise: DEMOTE_1 written non-demoted and locked.
    //
    // The default is closed. Skipping the write whenever the BL1 valid bit was
    // clear left DEMOTE_1 unwritten and unlocked on any manifest that simply did
    // not assert it, so later software could set it at will -- it failed open.
    //
    // Only the decision is taken here; the register write is deferred until after
    // the fuse secrets are locked. See the deferred write below [S26].
    bool demotion_reg = false;
    bool lock_demotion = true;
    {
        if (lc_state == LC_STATE_PROD_END) {
            // PROD_END: never demote. DEMOTE_2 is locked here, the one case where
            // BL0 touches it at all; DEMOTE_1 takes the defaults above and is
            // written and locked by the deferred write.
            lc_write_demotion_2(false, true);
            simputs("DEMOTE: PROD_END lock\n");
        } else {
            // Both halves of this decision live in one 16-bit
            // demotion_control field: the VALID bit says whether demotion is
            // specified at all, the ENABLE bit says what the value is.
            uint32_t dc = rom_oca_demotion_control();
            // Both the VALID and the ENABLE bit, not ENABLE alone: a manifest
            // that never stated a BL2 pair has not asked for anything, and
            // treating a stray ENABLE as a request would leave DEMOTE_1 open on
            // the strength of a bit the producer never meant. The same predicate
            // has to drive the unlock decision below and the value recorded for
            // BL1, or the two disagree and BL1 tries to demote a locked register.
            bool bl2_demote = (dc & (OCA_DEMOTE_BL2_VALID | OCA_DEMOTE_BL2_ENABLE)) ==
                              (OCA_DEMOTE_BL2_VALID | OCA_DEMOTE_BL2_ENABLE);

            if (dc & OCA_DEMOTE_BL1_VALID) {
                // BL1 manifest decides demotion, and the register is always locked.
                demotion_reg = (dc & OCA_DEMOTE_BL1_ENABLE) != 0u;
                simputsdec24("BL1_DEMOTE=", demotion_reg);
            } else if (bl2_demote) {
                // The only case that leaves the register unlocked, so that BL2 can
                // still apply the demotion it asked for.
                lock_demotion = false;
                simputs("DEMOTE: BL2 deferred, unlocked\n");
            } else {
                // Nothing asked for demotion: close the register non-demoted
                // rather than leaving it open.
                simputs("DEMOTE: BL2 deferred, lock non-demoted\n");
            }

            // Stored for BL1/KDF/measurement. DEMOTE_2 is BL1's to write.
            get_bl0_state()->bl2_demotion_decision = bl2_demote;
            simputsdec24("BL2_DEMOTE_DEC=", bl2_demote);
        }
    }

    // ── [S27] Enroll the boot-state measurement (soft measurement slot 1) ──
    // Verified manifest hash plus device state (LC, secure boot, SBOOT_DIS,
    // demotion). Enrolled after the DEMOTE_1 write above so the record reflects
    // what BL0 actually applied, not what the manifest asked for.
    //
    // Ordered per SEP-ROM-ATT-030: after the demotion decision, before the
    // fuse-secret locks. The DEMOTE_1 write itself is deferred past those locks
    // by SEP-ROM-DEM-035, so this records the decision rather than reading the
    // register back -- demotion_reg and lock_demotion are exactly what will be
    // written, so the record cannot disagree with the register, and it still
    // reflects what BL0 applied rather than what the manifest asked for.
    {
        const uint8_t *mhash = rom_oca_manifest_hash();
        if (mhash == NULL) {
            rom_err_fail(ROM_ERR_MEASUREMENT_FAILED);
        }

        uint8_t demotion_bits = 0u;
        if (demotion_reg) {
            demotion_bits |= MEAS_DEMOTION_BL1_DEMOTE;
        }
        if (lock_demotion) {
            demotion_bits |= MEAS_DEMOTION_BL1_LOCKED;
        }
        if (get_bl0_state()->bl2_demotion_decision) {
            demotion_bits |= MEAS_DEMOTION_BL2_DECISION;
        }

        if (measurement_enroll_boot_state(mhash, demotion_bits) != 0u) {
            rom_err_fail(ROM_ERR_MEASUREMENT_FAILED);
        }
        simputs("MEAS_BOOT_STATE_OK\n");
    }

    // ── [S25] Lock fuse secrets ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SECRETS_LOCK);
    lock_fuse_secrets();

    // ── [S26] Confirm fuse secrets locked ──
    // Failure to confirm the lock state is fatal.
    if (!check_fuse_secrets_locked()) {
        report_status(STATUS_TYPE_ERROR, SEP_MSG_FUSE_SECRETS_NOT_LOCKED);
        rom_err_fail(ROM_ERR_FUSE_SECRETS_NOT_LOCKED);
    }
    report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SECRETS_LOCKED);

    // ── [S25] DEMOTE_1 write (deferred from the decision above) ──
    // Ordered after the secret lock deliberately: the demotion register is the
    // last fuse state BL0 changes, so a fault while writing it cannot leave the
    // secret fuses readable. The corollary is that anything needing to READ a
    // secret fuse must run before the lock, not here.
    if (lock_demotion) {
        lc_write_demotion(demotion_reg, true);
        simputs("DEMOTE_LOCKED\n");
    } else {
        simputs("DEMOTE_NOT_LOCKED\n");
    }



    // ── [S28] Stack canary check ──
    // Verify the canary placed at __stack_bottom is still intact; if corrupted,
    // the stack overflowed into .bss.
    //
    // Checked here for two reasons. It has to be after [S23], which is where
    // the stack actually peaks -- the RSA-3072 modexp, SHA-256 and AES all run
    // inside rom_manifest_boot() -- so checking before that call would measure
    // the canary ahead of the deepest frame and prove nothing. And it has to be
    // before [S29], because rom_handoff_bl1() jumps to BL1 and does not return:
    // this is the last instant at which the ROM can still refuse to hand off.
    if (*(volatile uint32_t *)__stack_bottom != STACK_CANARY_VALUE) {
        rom_err_fail(ROM_ERR_STACK_OVERFLOW);
    }

    // ── [S29] BL1 handoff ──
    {
        report_status(STATUS_TYPE_DEBUG, SEP_MSG_HANDOFF_CHECK);
        // Body and payload are staged in SEP EXT SRAM by rom_manifest_boot();
        // the handoff reaches them through the rom_oca_* accessors.
        uint32_t ho_err = rom_handoff_bl1();
        // rom_handoff_bl1 does not return on success; if we get here, it failed.
        rom_err_fail(ho_err);
    }
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

    // ── [S04] main() entry ──
    STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_BOOTROM_START_MAIN));

    // ── [S04] runtime init check (g_data_init / g_bss_zero) ──
    rom_check_runtime_init_or_fail();
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_RUNTIME_INIT_OK);

    // ── SVT slave memory sanity check (write-read-back via SMC scratch[7]) ──
    rom_smc_mem_sanity_check();

    simputs("ROM\n");
    // ── [S05] ROM version + hash print (hash filled by build-time insert-rom-sha256.py) ──
    simputs(g_rom_version);
    simputs(g_rom_sha256_str);
    simputs("\n");
    report_rom_hash();

    // ── Cold boot (warm reset is handled in vector.S) ──
    // If we reach rom_main(), vector.S already determined this is a cold boot
    // because cold_scratch[7] was zero, then poisoned the slot with -1.
    // Nothing is written to cold_scratch[0] here: it carries the terminal verdict
    // only (errors.h VERDICT_OUT), and a second writer with unrelated semantics
    // would make a single read ambiguous. The console line below reports the cold
    // boot instead.
    simputs("COLD\n");

    // Memory init checkpoint (DCCM scrub + .data/.bss init done in vector.S).
    simputs("MEM_INIT_OK\n");

    // ── [S06] init_straps → structured boot config ──
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_DEVICE_MODE_INPUTS_CHECK);
    struct boot_straps straps;
    init_straps(&straps);

    // ── [S07] Status reporting init (strap-controlled) ──
    rom_status_reporting_init(&straps);

    // ── [S08] Fuse-sense readiness ──
    // Gates every later fuse read, [S09]'s smu_pll_sysclk included.
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_FUSE_SENSE_WAIT);
    simputs("FUSE_SENSE_WAIT\n");
    smc_wait_fuse_sense();
    simputs("FUSE_SENSE_DONE\n");

    // ── [S09] PLL/Clock init (strap-controlled) ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_PLL_CLK_INIT);
    uint16_t smu_freq_mhz = pll_init(straps.bl0_pll_clk);
    report_status(STATUS_TYPE_INFO_EXT, smu_freq_mhz);
    simputshex32("SYS_CLK_MHZ=", (uint32_t)smu_freq_mhz);

    // ── [S10] BL0 state init ──
    // MUST precede every bl0_state writer: init_bl0_state() zeroes the whole
    // struct, so any field recorded before it is destroyed. The vector.S DCCM
    // scrub covers the bl0_state reserve as well, which makes the zeroing
    // redundant on the cold path -- keep it anyway, because the scrub length is a
    // build-time option and the struct's initial state must not depend on it.
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_BL0_STATE_INIT);
    init_bl0_state();

    // The DCCM reserve exists as TWO numbers -- __bl0_state_reserve in
    // link/rom.ld and BL0_STATE_RESERVE_BYTES in bl0_state.h -- and nothing at
    // build time compares them. The header's _Static_assert checks the struct
    // against the header's own copy, so a pair like "header 192, linker 128,
    // sizeof 160" passes it and still overlaps the stack. This is the check that
    // does not: __stack_top comes from the LINKER's number, so if the struct
    // starts below it the two numbers have drifted apart.
    if ((uintptr_t)BL0_STATE_ADDR < (uintptr_t)__stack_top) {
        simputshex32("BL0S_ADDR=", (uint32_t)BL0_STATE_ADDR);
        simputshex32("STACK_TOP=", (uint32_t)(uintptr_t)__stack_top);
        rom_err_fail(ROM_ERR_BL0_STATE_OVERLAPS_STACK);
    }
    simputs("BL0_STATE_OK\n");

    // ── [S11] Lifecycle policy ──
    // rom_lifecycle_policy() reads efuse, validates, and records in bl0_state.
    // Returns the decoded LC state (does not return on invalid).
    uint32_t lc_state = rom_lifecycle_policy();

    // ── [S12] Chip ID identification ──
    // Read CHIP_CONFIG_CHIP_ID from the SMC chip_config
    // block and report for DV/debugger visibility.
    {
        report_status(STATUS_TYPE_DEBUG, SEP_MSG_CHIP_ID_CHECK);
        const uint32_t chip_id = smc_read_chip_id();
        report_status(STATUS_TYPE_INFO_EXT, (uint16_t)(chip_id & 0xFFFFu));
        simputshex32("CHIP_ID=", chip_id);
    }

    // [S03] DFT / MBIST / MEM_REPAIR boot-gating now runs in vector.S, before the
    // DCCM scrub and before this C runtime existed. It has to: a repair failure
    // must not reach the lifecycle decision, and that decision is stored in DCCM.

    // ── Peripheral/Bus reset sequencing ──
    rom_peripheral_reset();

    // ── [S14] Crypto/security init ──
    rom_crypto_init();

    // ── [S17] Verify + enroll the ROM self-hash (soft measurement slot 0) ──
    // Recomputes SHA-256 over the hashed ROM region and compares it against the
    // build-time embedded hash before extending soft_pcr[MEAS_SLOT_ROM], so slot 0
    // measures what is executing rather than what the build claimed. Needs
    // the crypto self-test ([S14]) and bl0_state init ([S10]), both above.
    if (measurement_enroll_rom_hash() != 0u) {
        rom_err_fail(ROM_ERR_ROM_HASH_MISMATCH);
    }

    // ── [S15] EXT SRAM clear ──
    simputs(">>C9a_SRAM_CLR\n");
    rom_mem_clear();
    simputs("<<C9a_SRAM_CLR\n");

    // ── [S16] ICCM clear ──
    simputs(">>C9b_ICCM_CLR\n");
    rom_iccm_clear();
    simputs("<<C9b_ICCM_CLR\n");

    // ── [S18] Read sboot_dis fuse ──
    // Read the SBOOT_DIS efuse shadow register.
    // Chicken bit to disable secure boot (bit 0 of SEP_EFUSE_MAP_SBOOT_DIS).
    // Kept in a function-level local, not only in bl0_state: the secure-boot
    // decision takes it as an argument so the verdict cannot depend on mutable
    // shared state.
    bool sboot_dis;
    {
        uint32_t sboot_dis_reg = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR);
        sboot_dis = (sboot_dis_reg & SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm) != 0u;
        get_bl0_state()->sboot_dis = sboot_dis;
        simputsdec24("FUSE: SBOOT_DIS: ", sboot_dis);
        report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SBOOT_DIS);
        report_status(STATUS_TYPE_INFO_EXT, sboot_dis);
    }

    // ── [S19] Stack canary write ──
    // Place canary at __stack_bottom (lowest stack address, just above .bss).
    // Re-verified at [S28] just before the BL1 hand-off, which is after the
    // deepest frames the boot reaches (see the check site).
    *(volatile uint32_t *)__stack_bottom = STACK_CANARY_VALUE;

    // ── [S20] DMA init ──
    rom_dma_init();

    // ── [S21] Boot mode branch (SPI / recovery / secondary) ──
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

    // ── [S23] Manifest load / validate + [S25]/[S26] fuse lock + [S28] canary
    //    + [S29] handoff ──
    // Does not return: every path out of it either jumps to BL1 or converges
    // on rom_err_fail(). [S28] therefore lives inside the callee, where it is
    // reachable, and nothing may follow this call. The ROM has no PASS path of
    // its own -- in DV, bl1_pass_test writes MAGIC0 + PASS to the STDOUT
    // mailbox itself.
    rom_manifest_validate_handoff(&straps, spi_status, lc_state);
}

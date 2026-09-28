/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES Back-to-Back Stress Test (STRESS-001)
 *
 * Coverage:
 *  - Phase A: 40 blocks ECB AES-128 with incrementing data + variable delays
 *  - Phase B: 32 blocks CBC AES-128 with incrementing data (mode switch)
 *  - Phase C: 32 blocks CTR AES-128 with incrementing data (mode switch)
 *  - Phase D: 24 blocks ECB AES-256 with incrementing data (key rotation)
 *  - OUTPUT_LOST monitoring throughout all phases
 *  - Alert status monitoring
 *  - Variable inter-block delays via LFSR
 *
 * Total: 128 blocks across 4 phases exercising mode switching, key rotation,
 *        varying data patterns, and random back-pressure.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_aes_init.h"
#include "aes_test_util.h"

/* ------------------------------------------------------------------ */
/* Minimal trap handler - avoids printf to prevent recursive traps    */
/* ------------------------------------------------------------------ */

#define STDOUT_ADDR 0x80000000

static void raw_putc(char c) {
    *(volatile uint8_t *)STDOUT_ADDR = (uint8_t)c;
}

static void raw_puts(const char *s) {
    while (*s) raw_putc(*s++);
}

static void raw_hex32(uint32_t v) {
    const char hex[] = "0123456789abcdef";
    raw_puts("0x");
    for (int i = 28; i >= 0; i -= 4) raw_putc(hex[(v >> i) & 0xf]);
}

void trap_dump(uint32_t mcause, uint32_t mepc, uint32_t mtval) __attribute__((noreturn));

void trap_dump(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    raw_puts("\n*** TRAP ***\nmcause=");
    raw_hex32(mcause);
    raw_puts("\nmepc=");
    raw_hex32(mepc);
    raw_puts("\nmtval=");
    raw_hex32(mtval);
    raw_putc('\n');
    test_fail(1);
    while (1) __asm__ volatile("wfi");
}

static void trap_handler_c(void) __attribute__((naked));
static void trap_handler_c(void) {
    __asm__ volatile("addi  sp, sp, -16   \n"
                     "sw    ra, 12(sp)    \n"
                     "csrr  a0, mcause    \n"
                     "csrr  a1, mepc      \n"
                     "csrr  a2, mtval     \n"
                     "call  trap_dump     \n");
}

static void install_trap_handler(void) {
    uintptr_t addr = (uintptr_t)&trap_handler_c;
    __asm__ volatile("csrw mtvec, %0" ::"r"(addr));
}

/* ------------------------------------------------------------------ */
/* Test Vectors                                                       */
/* ------------------------------------------------------------------ */

/* AES-128 key (NIST SP 800-38A) */
static const uint32_t test_key_128[4] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09};

/* AES-256 key (NIST FIPS-197 Appendix C.3) */
static const uint32_t test_key_256[8] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                         0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c};

static const uint32_t zero_iv[4] = {0, 0, 0, 0};

static const uint32_t cbc_iv[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};

static const uint32_t ctr_iv[4] = {0xf3f2f1f0, 0xf7f6f5f4, 0xfbfaf9f8, 0xfffefdfc};

/* NIST F.1 ECB block #1 - for golden comparison on block 0 */
static const uint32_t ecb_pt_base[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};
static const uint32_t ecb_ct_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

/* AES-256 ECB: NIST FIPS-197 Appendix C.3 */
static const uint32_t pt_256[4] = {0x33221100, 0x77665544, 0xbbaa9988, 0xffeeddcc};
static const uint32_t ct_256_exp[4] = {0xcab7a28e, 0xbf456751, 0x9049fcea, 0x8960494b};

/* ------------------------------------------------------------------ */
/* LFSR for variable delays                                           */
/* ------------------------------------------------------------------ */

static uint32_t lfsr_state = 0xACE1u;

static uint32_t lfsr_next(void) {
    uint32_t bit =
        ((lfsr_state >> 0) ^ (lfsr_state >> 2) ^ (lfsr_state >> 3) ^ (lfsr_state >> 5)) & 1u;
    lfsr_state = (lfsr_state >> 1) | (bit << 15);
    return lfsr_state;
}

static void variable_delay(void) {
    uint32_t delay = lfsr_next() & 0xFF; /* 0-255 NOP iterations */
    for (volatile uint32_t i = 0; i < delay; i++) {
        __asm__("nop");
    }
}

/* ------------------------------------------------------------------ */
/* Generate incrementing plaintext pattern                            */
/* ------------------------------------------------------------------ */

static void gen_plaintext(uint32_t pt[4], int block_idx) {
    pt[0] = ecb_pt_base[0] ^ ((uint32_t)block_idx * 0x01010101u);
    pt[1] = ecb_pt_base[1] ^ ((uint32_t)block_idx * 0x10101010u);
    pt[2] = ecb_pt_base[2] ^ ((uint32_t)block_idx * 0x00110011u);
    pt[3] = ecb_pt_base[3] ^ ((uint32_t)block_idx * 0x11001100u);
}

/* ------------------------------------------------------------------ */
/* Common block check: OUTPUT_LOST + alert                            */
/* ------------------------------------------------------------------ */

static int check_block_status(int block, const char *phase) {
    aes__STATUS_t st = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
    if (st.f.OUTPUT_LOST) {
        printf("  ERROR: OUTPUT_LOST at %s block %d (STATUS=0x%08x)\n", phase, block, st.w);
        return -1;
    }
    if (st.f.STALL) {
        printf("  WARNING: STALL at %s block %d (STATUS=0x%08x)\n", phase, block, st.w);
    }
    return check_no_alert(phase);
}

/* ------------------------------------------------------------------ */
/* Phase A: ECB AES-128, 40 blocks, incrementing data + delays        */
/* ------------------------------------------------------------------ */

#define PHASE_A_BLOCKS 40

static int run_phase_a(void) {
    uint32_t pt[4], out[4];

    printf("\n--- Phase A: ECB-128, %d blocks, incrementing data + delays ---\n", PHASE_A_BLOCKS);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x1 /* ENC */, 0x1 /* ECB */, test_key_128, zero_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < PHASE_A_BLOCKS; block++) {
        /* Variable delay every 4 blocks */
        if ((block & 3) == 0 && block > 0) {
            variable_delay();
        }

        gen_plaintext(pt, block);
        write_data_in(pt);

        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(block, "PhaseA") != 0) return -1;
        read_data_out(out);

        /* Block 0 uses unmodified NIST vector - golden compare */
        if (block == 0) {
            if (compare_block(out, ecb_ct_exp, "PhaseA block 0 golden") != 0) return -1;
        }

        if ((block % 10) == 9) {
            printf("  Phase A: %d / %d blocks\n", block + 1, PHASE_A_BLOCKS);
        }

        if (block != (PHASE_A_BLOCKS - 1)) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    printf("  Phase A complete: %d blocks, no OUTPUT_LOST\n", PHASE_A_BLOCKS);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Phase B: CBC AES-128, 32 blocks, incrementing data (mode switch)   */
/* ------------------------------------------------------------------ */

#define PHASE_B_BLOCKS 32

static int run_phase_b(void) {
    uint32_t pt[4], out[4];

    printf("\n--- Phase B: CBC-128, %d blocks, incrementing data ---\n", PHASE_B_BLOCKS);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x1 /* ENC */, 0x2 /* CBC */, test_key_128, cbc_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < PHASE_B_BLOCKS; block++) {
        gen_plaintext(pt, PHASE_A_BLOCKS + block);
        write_data_in(pt);

        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(block, "PhaseB") != 0) return -1;
        read_data_out(out);

        if ((block % 8) == 7) {
            printf("  Phase B: %d / %d blocks\n", block + 1, PHASE_B_BLOCKS);
        }

        if (block != (PHASE_B_BLOCKS - 1)) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    printf("  Phase B complete: %d blocks CBC, no OUTPUT_LOST\n", PHASE_B_BLOCKS);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Phase C: CTR AES-128, 32 blocks, incrementing data (mode switch)   */
/* ------------------------------------------------------------------ */

#define PHASE_C_BLOCKS 32

static int run_phase_c(void) {
    uint32_t pt[4], out[4];

    printf("\n--- Phase C: CTR-128, %d blocks, incrementing data ---\n", PHASE_C_BLOCKS);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x1 /* ENC */, 0x10 /* CTR */, test_key_128, ctr_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < PHASE_C_BLOCKS; block++) {
        /* Variable delay every 6 blocks */
        if ((block % 6) == 0 && block > 0) {
            variable_delay();
        }

        gen_plaintext(pt, PHASE_A_BLOCKS + PHASE_B_BLOCKS + block);
        write_data_in(pt);

        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(block, "PhaseC") != 0) return -1;
        read_data_out(out);

        if ((block % 8) == 7) {
            printf("  Phase C: %d / %d blocks\n", block + 1, PHASE_C_BLOCKS);
        }

        if (block != (PHASE_C_BLOCKS - 1)) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    printf("  Phase C complete: %d blocks CTR, no OUTPUT_LOST\n", PHASE_C_BLOCKS);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Phase D: ECB AES-256, 24 blocks, incrementing data (key rotation)  */
/* ------------------------------------------------------------------ */

#define PHASE_D_BLOCKS 24

static int run_phase_d(void) {
    uint32_t pt[4], out[4];

    printf("\n--- Phase D: ECB-256, %d blocks, incrementing data ---\n", PHASE_D_BLOCKS);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x1 /* ENC */, 0x1 /* ECB */, 0x4 /* AES-256 */, test_key_256, 8, NULL,
                           zero_iv, 0x0) != 0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < PHASE_D_BLOCKS; block++) {
        if (block == 0) {
            /* Block 0: use NIST vector for golden compare */
            write_data_in(pt_256);
        } else {
            gen_plaintext(pt, PHASE_A_BLOCKS + PHASE_B_BLOCKS + PHASE_C_BLOCKS + block);
            write_data_in(pt);
        }

        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(block, "PhaseD") != 0) return -1;
        read_data_out(out);

        /* Block 0 uses NIST AES-256 vector */
        if (block == 0) {
            if (compare_block(out, ct_256_exp, "PhaseD block 0 AES-256 golden") != 0) return -1;
        }

        if ((block % 8) == 7) {
            printf("  Phase D: %d / %d blocks\n", block + 1, PHASE_D_BLOCKS);
        }

        if (block != (PHASE_D_BLOCKS - 1)) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    printf("  Phase D complete: %d blocks AES-256, no OUTPUT_LOST\n", PHASE_D_BLOCKS);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Main                                                               */
/* ------------------------------------------------------------------ */

int main(void) {
    int rc = 0;

    sep_outbound_filter_init();
    install_trap_handler();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_back_to_back_test (STRESS-001)\n");
    printf("========================================\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);
    printf("Total blocks: %d (A=%d + B=%d + C=%d + D=%d)\n",
           PHASE_A_BLOCKS + PHASE_B_BLOCKS + PHASE_C_BLOCKS + PHASE_D_BLOCKS, PHASE_A_BLOCKS,
           PHASE_B_BLOCKS, PHASE_C_BLOCKS, PHASE_D_BLOCKS);

    if (rc == 0) rc = run_phase_a(); /* ECB-128 + delays */
    if (rc == 0) rc = run_phase_b(); /* CBC-128 (mode switch) */
    if (rc == 0) rc = run_phase_c(); /* CTR-128 (mode switch) + delays */
    if (rc == 0) rc = run_phase_d(); /* ECB-256 (key rotation) */

    cleanup_aes();

    if (rc == 0) {
        printf("\n========================================\n");
        printf("=== sep_aes_back_to_back_test PASSED ===\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("\n=== sep_aes_back_to_back_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}

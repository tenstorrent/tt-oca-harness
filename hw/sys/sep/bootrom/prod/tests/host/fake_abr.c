/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "fake_abr.h"

#include <string.h>

#include "sep_addr.h"

#define ABR_BASE SEP_TOP_ABR_BASE_ADDR
#define ABR_EXTENT SEP_TOP_ABR_SIZE

#define ST_READY 0x1u
#define ST_VALID 0x2u
#define ST_STREAM 0x4u
#define ST_ERROR 0x8u

typedef enum {
    PH_IDLE,
    PH_ZEROIZING,
    PH_STALE, // zeroize finished but STATUS reads zeroize_status
    PH_BUSY,
    PH_STREAM,
    PH_COMPUTING,
    PH_VALID,
    PH_ERROR
} phase_e;

fake_abr_t g_fake;

static phase_e s_phase;
static int s_polls;
static uint32_t s_verify_res[16];
static uint32_t s_res_reads;
static uint32_t s_strobe;
static uint32_t s_done_sts;
static uint32_t s_done_count;
static uint32_t s_err_sts;
static uint32_t s_err_count;

void fake_abr_reset(void) {
    memset(&g_fake, 0, sizeof(g_fake));
    g_fake.zeroize_polls = 2;
    g_fake.stream_ready_polls = 2;
    g_fake.complete_polls = 2;
    g_fake.done_events = 1;
    g_fake.result = FAKE_RES_MATCH;
    s_phase = PH_IDLE;
    s_polls = 0;
    memset(s_verify_res, 0, sizeof(s_verify_res));
    s_res_reads = 0;
    s_strobe = 0xFu;
    // Stale events from earlier commands, which the RTL keeps through zeroize.
    s_done_sts = 1;
    s_done_count = 7;
    s_err_sts = 1;
    s_err_count = 3;
}

static int in_range(uint32_t addr, uint32_t base, uint32_t words) {
    return addr >= base && addr < base + words * 4u;
}

static void raise_valid(void) {
    s_phase = PH_VALID;
    s_res_reads = 0;
    switch (g_fake.result) {
    case FAKE_RES_MATCH:
        memcpy(s_verify_res, g_fake.signature, sizeof(s_verify_res));
        break;
    case FAKE_RES_MISMATCH:
        memcpy(s_verify_res, g_fake.signature, sizeof(s_verify_res));
        s_verify_res[g_fake.mismatch_word] ^= 0x10u;
        break;
    case FAKE_RES_ZERO:
        memset(s_verify_res, 0, sizeof(s_verify_res));
        break;
    case FAKE_RES_INVERSE:
        break;
    }
    s_done_sts = g_fake.done_sts_cleared ? 0u : 1u;
    s_done_count += (uint32_t)g_fake.done_events;
    if (g_fake.error_event || g_fake.error_sts_only) {
        s_err_sts = 1u;
    }
    if (g_fake.error_event || g_fake.error_count_only) {
        ++s_err_count;
    }
}

static uint32_t status_read(void) {
    ++s_polls;
    switch (s_phase) {
    case PH_IDLE:
        return ST_READY;
    case PH_ZEROIZING:
        if (g_fake.zeroize_never_ready ||
            (g_fake.trailing_zeroize_fails && g_fake.zeroize_count >= 2)) {
            return 0u;
        }
        if (s_polls < g_fake.zeroize_polls) {
            return 0u;
        }
        if (g_fake.zeroize_status != 0u) {
            s_phase = PH_STALE;
            return g_fake.zeroize_status;
        }
        s_phase = PH_IDLE;
        return ST_READY;
    case PH_STALE:
        return g_fake.zeroize_status;
    case PH_BUSY:
        if (g_fake.error_in_stream_wait) {
            s_phase = PH_ERROR;
            return ST_ERROR;
        }
        if (g_fake.never_stream_ready || s_polls < g_fake.stream_ready_polls) {
            return 0u;
        }
        if (g_fake.early_valid) {
            raise_valid();
            return ST_VALID;
        }
        s_phase = PH_STREAM;
        return ST_STREAM;
    case PH_STREAM:
        return ST_STREAM;
    case PH_COMPUTING:
        if (g_fake.error_in_complete_wait) {
            s_phase = PH_ERROR;
            return ST_ERROR;
        }
        if (g_fake.never_valid || s_polls < g_fake.complete_polls) {
            return 0u;
        }
        raise_valid();
        return ST_VALID;
    case PH_VALID:
        return ST_VALID;
    case PH_ERROR:
        return ST_ERROR;
    }
    return 0u;
}

uint32_t fake_mmio_read32(uint32_t addr) {
    if (addr < ABR_BASE || addr >= ABR_BASE + ABR_EXTENT || (addr & 3u) != 0u) {
        ++g_fake.out_of_window_accesses;
        return 0u;
    }
    if (addr == SEP_TOP_ABR_MLDSA_STATUS_BASE_ADDR) {
        return status_read();
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_NAME_BASE_ADDR(0), 2)) {
        return addr == SEP_TOP_ABR_MLDSA_NAME_BASE_ADDR(0) ? 0x44534D4Cu : 0x3837412Du;
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_VERSION_BASE_ADDR(0), 2)) {
        if (addr == SEP_TOP_ABR_MLDSA_VERSION_BASE_ADDR(0)) {
            return g_fake.identity_bad ? 0x00000001u : 0x302E322Eu;
        }
        return 0x00003100u;
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_VERIFY_RES_BASE_ADDR(0), 16)) {
        const uint32_t i = (addr - SEP_TOP_ABR_MLDSA_VERIFY_RES_BASE_ADDR(0)) / 4u;
        ++s_res_reads;
        // A second pass over the 16 words after VALID sees a different value.
        if (g_fake.second_res_differs && s_phase == PH_VALID && s_res_reads > 16u) {
            return s_verify_res[i] ^ 0x80000000u;
        }
        return s_verify_res[i];
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_PUBKEY_BASE_ADDR, 648)) {
        const uint32_t i = (addr - SEP_TOP_ABR_MLDSA_PUBKEY_BASE_ADDR) / 4u;
        if (s_phase != PH_VALID) return 0u;
        return g_fake.pubkey[i] ^ ((g_fake.pk_readback_corrupt && i == 300u) ? 1u : 0u);
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_SIGNATURE_BASE_ADDR, 1157)) {
        const uint32_t i = (addr - SEP_TOP_ABR_MLDSA_SIGNATURE_BASE_ADDR) / 4u;
        if (s_phase != PH_VALID) return 0u;
        return g_fake.signature[i] ^ ((g_fake.sig_readback_corrupt && i == 3u) ? 1u : 0u);
    }
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_NOTIF_INTERNAL_INTR_R_BASE_ADDR) return s_done_sts;
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_R_BASE_ADDR) return s_err_sts;
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_NOTIF_CMD_DONE_INTR_COUNT_R_BASE_ADDR)
        return s_done_count;
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_COUNT_R_BASE_ADDR) return s_err_count;
    return 0u;
}

static void zeroize(void) {
    ++g_fake.zeroize_count;
    s_phase = PH_ZEROIZING;
    s_polls = 0;
    memset(s_verify_res, 0, sizeof(s_verify_res));
    memset(g_fake.pubkey, 0, sizeof(g_fake.pubkey));
    memset(g_fake.signature, 0, sizeof(g_fake.signature));
    g_fake.ctx_config = 0u;
    s_strobe = 0u;
}

void fake_mmio_write32(uint32_t addr, uint32_t value) {
    if (addr < ABR_BASE || addr >= ABR_BASE + ABR_EXTENT || (addr & 3u) != 0u) {
        ++g_fake.out_of_window_accesses;
        return;
    }
    const int ready = s_phase == PH_IDLE || s_phase == PH_STALE;

    if (addr == SEP_TOP_ABR_MLDSA_CTRL_BASE_ADDR) {
        if ((value & 0x8u) != 0u) {
            zeroize();
            return;
        }
        if (ready && (value & 0x7u) == 0x3u) {
            ++g_fake.verify_commands;
            if (!g_fake.no_preload) {
                for (uint32_t i = 0; i < 16u; ++i) s_verify_res[i] = ~g_fake.signature[i];
            }
            s_phase = PH_BUSY;
            s_polls = 0;
        }
        return;
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_PUBKEY_BASE_ADDR, 648)) {
        if (ready) g_fake.pubkey[(addr - SEP_TOP_ABR_MLDSA_PUBKEY_BASE_ADDR) / 4u] = value;
        return;
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_SIGNATURE_BASE_ADDR, 1157)) {
        if (ready) g_fake.signature[(addr - SEP_TOP_ABR_MLDSA_SIGNATURE_BASE_ADDR) / 4u] = value;
        return;
    }
    if (addr == SEP_TOP_ABR_MLDSA_CTX_CONFIG_BASE_ADDR) {
        if (ready) g_fake.ctx_config = value;
        return;
    }
    if (addr == SEP_TOP_ABR_MLDSA_MSG_STROBE_BASE_ADDR) {
        if (s_phase == PH_STREAM) {
            s_strobe = value & 0xFu;
        } else {
            ++g_fake.strobe_outside_stream;
        }
        return;
    }
    if (in_range(addr, SEP_TOP_ABR_MLDSA_MSG_BASE_ADDR(0), 16)) {
        if (s_phase != PH_STREAM || addr != SEP_TOP_ABR_MLDSA_MSG_BASE_ADDR(0)) {
            ++g_fake.msg_outside_stream;
            return;
        }
        g_fake.strobes[g_fake.strobe_count++] = s_strobe;
        for (uint32_t b = 0; b < 4u; ++b) {
            if ((s_strobe & (1u << b)) != 0u && g_fake.stream_len < FAKE_ABR_MAX_STREAM) {
                g_fake.stream[g_fake.stream_len++] = (uint8_t)(value >> (8u * b));
            }
        }
        if (s_strobe != 0xFu) {
            s_phase = PH_COMPUTING;
            s_polls = 0;
        }
        return;
    }
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_NOTIF_INTERNAL_INTR_R_BASE_ADDR) {
        if ((value & 1u) != 0u && !g_fake.done_sts_sticks) s_done_sts = 0u;
        return;
    }
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_R_BASE_ADDR) {
        if ((value & 1u) != 0u) s_err_sts = 0u;
        return;
    }
    if (addr == SEP_TOP_ABR_INTR_BLOCK_RF_NOTIF_CMD_DONE_INTR_COUNT_R_BASE_ADDR) {
        if (!g_fake.done_count_sticks) s_done_count = value;
        return;
    }
}

void fake_mmio_bad_width(uint32_t addr) {
    (void)addr;
    ++g_fake.bad_width_accesses;
}

void fake_mmio_fence(void) {
    ++g_fake.fence_count;
}

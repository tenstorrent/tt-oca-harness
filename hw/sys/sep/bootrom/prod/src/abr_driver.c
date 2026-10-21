// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Adams Bridge ML-DSA-87 verify driver.
//
// A verify that never ran cannot pass: VERIFY_RES is written only by the
// command-accept preload (~c~), by the verify datapath (c~') and by zeroize (0), so
// with an all-zero c~ rejected up front, only a computed c~' can equal c~. A stale c~'
// from an earlier verify of the same signature is the remaining way to see c~ without
// computing it; the leading and trailing zeroize, the preload check and the single
// command-done event each rule that out independently.

#include <stddef.h>
#include <stdint.h>

#include "abr_driver.h"
#include "abr_driver_internal.h"
#include "harden.h"
#include "rom_mmio.h"
#include "sep_addr.h"

// Register fields, from the vendored abr_reg.rdl (MLDSA_CTRL, MLDSA_STATUS and the
// interrupt block's status registers).
#define ABR_CTRL_CMD_VERIFY 0x3u
#define ABR_CTRL_ZEROIZE (1u << 3)
#define ABR_CTRL_STREAM_MSG (1u << 6)
#define ABR_STATUS_READY (1u << 0)
#define ABR_STATUS_VALID (1u << 1)
#define ABR_STATUS_MSG_STREAM_READY (1u << 2)
#define ABR_STATUS_ERROR (1u << 3)
#define ABR_INTR_STS (1u << 0)

// "MLDSA-87" version "2.0.1", tied off in the RTL (abr_params_pkg.sv).
#define ABR_MLDSA_NAME0 0x44534D4Cu
#define ABR_MLDSA_NAME1 0x3837412Du
#define ABR_MLDSA_VERSION0 0x302E322Eu
#define ABR_MLDSA_VERSION1 0x00003100u

#define ABR_STATUS SEP_TOP_ABR_MLDSA_STATUS_BASE_ADDR
#define ABR_DONE_STS SEP_TOP_ABR_INTR_BLOCK_RF_NOTIF_INTERNAL_INTR_R_BASE_ADDR
#define ABR_ERR_STS SEP_TOP_ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_R_BASE_ADDR
#define ABR_DONE_COUNT SEP_TOP_ABR_INTR_BLOCK_RF_NOTIF_CMD_DONE_INTR_COUNT_R_BASE_ADDR
#define ABR_ERR_COUNT SEP_TOP_ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_COUNT_R_BASE_ADDR

#define PK_WORDS (ABR_MLDSA87_PK_BYTES / 4u)
#define SIG_WORDS ((ABR_MLDSA87_SIG_BYTES + 3u) / 4u)

// Poll budgets, in STATUS reads. Each read is a bus round trip, so these are far
// above the RTL's operation lengths: the zeroize sweep is about 1.5k ABR cycles and a
// verify a few hundred thousand.
#define ABR_POLL_ZEROIZE 100000u
#define ABR_POLL_PRELOAD 1000u
#define ABR_POLL_STREAM_READY 2000000u
#define ABR_POLL_COMPLETE 2000000u
#define ABR_POLL_DONE_COUNT 1000u

// Mixed into the verdict so that neither evaluation alone produces the pass token.
#define ABR_VERDICT_KEY 0xC3A5965Au

// The steps are static in the ROM, so nothing outside abr_mldsa87_verify() can call
// one alone; tests that stop the sequence part-way define ABR_DRV_EXPOSE_STEPS.
#ifdef ABR_DRV_EXPOSE_STEPS
#define ABR_DRV_STEP
#else
#define ABR_DRV_STEP static
#endif

static uint32_t le_word(const uint8_t *p, uint32_t len) {
    uint32_t w = 0u;
    for (uint32_t i = 0; i < len && i < 4u; ++i) {
        w |= (uint32_t)p[i] << (8u * i);
    }
    return w;
}

ABR_DRV_STEP void abr_drv_ctx_init(abr_drv_ctx_t *ctx) {
    for (uint32_t i = 0; i < ABR_DRV_CTILDE_WORDS; ++i) {
        ctx->ct[i] = 0u;
    }
    ctx->err_count = 0u;
    ctx->written = 0u;
    ctx->written_dup = 0u;
    ctx->streaming = 0u;
    ctx->diag.bytes_written = 0u;
    ctx->diag.early_valid = 0u;
    ctx->diag.res_inverse = 0u;
    ctx->diag.res_nonzero = 0u;
    ctx->diag.done_count = 0u;
    ctx->diag.stage = ABR_DRV_STAGE_ARGS;
}

int abr_drv_check_identity(void) {
    const uint32_t diff =
        (mmio_read32(SEP_TOP_ABR_MLDSA_NAME_BASE_ADDR(0)) ^ ABR_MLDSA_NAME0) |
        (mmio_read32(SEP_TOP_ABR_MLDSA_NAME_BASE_ADDR(1)) ^ ABR_MLDSA_NAME1) |
        (mmio_read32(SEP_TOP_ABR_MLDSA_VERSION_BASE_ADDR(0)) ^ ABR_MLDSA_VERSION0) |
        (mmio_read32(SEP_TOP_ABR_MLDSA_VERSION_BASE_ADDR(1)) ^ ABR_MLDSA_VERSION1);
    return diff == 0u ? ABR_DRV_OK : ABR_DRV_ERR_IDENTITY;
}

int abr_drv_zeroize(void) {
    mmio_write32(SEP_TOP_ABR_MLDSA_CTRL_BASE_ADDR, ABR_CTRL_ZEROIZE);
    mmio_fence();
    // READY alone: a VALID, ERROR or MSG_STREAM_READY left set means the zeroize did
    // not take, and a result from before it may still be readable.
    for (uint32_t i = 0; i < ABR_POLL_ZEROIZE; ++i) {
        if (mmio_read32(ABR_STATUS) == ABR_STATUS_READY) {
            return ABR_DRV_OK;
        }
    }
    return ABR_DRV_ERR_STATE;
}

ABR_DRV_STEP int abr_drv_load(abr_drv_ctx_t *ctx, const uint8_t *public_key,
                              const uint8_t *signature) {
    uint32_t any = 0u;
    for (uint32_t i = 0; i < ABR_DRV_CTILDE_WORDS; ++i) {
        ctx->ct[i] = le_word(signature + 4u * i, 4u);
        any |= ctx->ct[i];
    }
    if (any == 0u) {
        ctx->diag.stage = ABR_DRV_STAGE_ARGS;
        return ABR_DRV_ERR_SIG_INVALID;
    }

    ctx->diag.stage = ABR_DRV_STAGE_ZEROIZE;
    const int rc = abr_drv_zeroize();
    if (rc != ABR_DRV_OK) {
        return rc;
    }

    // A load cut short is caught after VALID, when PUBKEY and c~ are read back.
    ctx->diag.stage = ABR_DRV_STAGE_LOAD;
    for (uint32_t i = 0; i < PK_WORDS; ++i) {
        mmio_write32(SEP_TOP_ABR_MLDSA_PUBKEY_BASE_ADDR + 4u * i, le_word(public_key + 4u * i, 4u));
    }

    // The c~ the accelerator latches comes from ctx->ct, the copy every later check
    // compares against, never from the caller's buffer a second time.
    for (uint32_t i = 0; i < SIG_WORDS; ++i) {
        const uint32_t remaining = ABR_MLDSA87_SIG_BYTES - 4u * i;
        const uint32_t w =
            i < ABR_DRV_CTILDE_WORDS ? ctx->ct[i] : le_word(signature + 4u * i, remaining);
        mmio_write32(SEP_TOP_ABR_MLDSA_SIGNATURE_BASE_ADDR + 4u * i, w);
    }

    mmio_write32(SEP_TOP_ABR_MLDSA_CTX_CONFIG_BASE_ADDR, 0u);
    return ABR_DRV_OK;
}

ABR_DRV_STEP int abr_drv_start(abr_drv_ctx_t *ctx) {
    // The command-done status and counter are set only when VALID rises and survive
    // zeroize, so clearing them here makes the event checked at VALID this command's.
    ctx->diag.stage = ABR_DRV_STAGE_ARM;
    mmio_write32(ABR_DONE_STS, ABR_INTR_STS);
    mmio_write32(ABR_ERR_STS, ABR_INTR_STS);
    mmio_write32(ABR_DONE_COUNT, 0u);
    ctx->err_count = mmio_read32(ABR_ERR_COUNT);
    if (((mmio_read32(ABR_DONE_STS) | mmio_read32(ABR_ERR_STS)) & ABR_INTR_STS) != 0u ||
        mmio_read32(ABR_DONE_COUNT) != 0u) {
        return ABR_DRV_ERR_STATE;
    }

    ctx->diag.stage = ABR_DRV_STAGE_START;
    mmio_write32(SEP_TOP_ABR_MLDSA_CTRL_BASE_ADDR, ABR_CTRL_CMD_VERIFY | ABR_CTRL_STREAM_MSG);
    mmio_fence();

    // Accepting VERIFY preloads ~c~. Seeing it proves the command landed and latched
    // this c~.
    ctx->diag.stage = ABR_DRV_STAGE_PRELOAD;
    for (uint32_t poll = 0; poll < ABR_POLL_PRELOAD; ++poll) {
        uint32_t diff = 0u;
        for (uint32_t w = 0; w < ABR_DRV_CTILDE_WORDS; ++w) {
            diff |= mmio_read32(SEP_TOP_ABR_MLDSA_VERIFY_RES_BASE_ADDR(w)) ^ ~ctx->ct[w];
        }
        if (diff == 0u) {
            return ABR_DRV_OK;
        }
    }
    return ABR_DRV_ERR_STATE;
}

// The done counter updates a cycle after the status bit, so give it a few reads.
static uint32_t read_done_count(void) {
    uint32_t count = 0u;
    for (uint32_t i = 0; i < ABR_POLL_DONE_COUNT && count == 0u; ++i) {
        count = mmio_read32(ABR_DONE_COUNT);
    }
    return count;
}

// Reads VERIFY_RES once and returns how it differs from c~; also records whether it
// was ~c~ or zero, which tells a fail-closed rejection from a missing preload.
static uint32_t read_result(abr_drv_ctx_t *ctx) {
    uint32_t diff = 0u;
    uint32_t inv = 0u;
    uint32_t nonzero = 0u;
    for (uint32_t w = 0; w < ABR_DRV_CTILDE_WORDS; ++w) {
        const uint32_t r = mmio_read32(SEP_TOP_ABR_MLDSA_VERIFY_RES_BASE_ADDR(w));
        diff |= r ^ ctx->ct[w];
        inv |= r ^ ~ctx->ct[w];
        nonzero |= r;
    }
    ctx->diag.res_inverse = inv == 0u;
    ctx->diag.res_nonzero = nonzero != 0u;
    return diff;
}

static void stream_word(abr_drv_ctx_t *ctx, uint32_t strobe, uint32_t word, uint32_t bytes) {
    mmio_write32(SEP_TOP_ABR_MLDSA_MSG_STROBE_BASE_ADDR, strobe);
    mmio_write32(SEP_TOP_ABR_MLDSA_MSG_BASE_ADDR(0), word);
    ctx->written += bytes;
    ctx->written_dup += bytes;
}

ABR_DRV_STEP int abr_drv_stream_range(abr_drv_ctx_t *ctx, const uint8_t *message, uint32_t len,
                                      int final) {
    if (!final && (len & 3u) != 0u) {
        return ABR_DRV_ERR_PARAM;
    }

    if (!ctx->streaming) {
        // VALID first means the accelerator rejected the signature before asking for
        // the message; a pure streamed verify is only valid after the whole message.
        ctx->diag.stage = ABR_DRV_STAGE_STREAM_WAIT;
        for (uint32_t i = 0; i < ABR_POLL_STREAM_READY && !ctx->streaming; ++i) {
            const uint32_t st = mmio_read32(ABR_STATUS);
            if ((st & ABR_STATUS_ERROR) != 0u) {
                return ABR_DRV_ERR_HW;
            }
            if ((st & ABR_STATUS_MSG_STREAM_READY) != 0u) {
                ctx->streaming = 1u;
            } else if ((st & ABR_STATUS_VALID) != 0u) {
                ctx->diag.early_valid = 1u;
                ctx->diag.done_count = read_done_count();
                (void)read_result(ctx);
                return ABR_DRV_ERR_SIG_INVALID;
            }
        }
        if (!ctx->streaming) {
            return ABR_DRV_ERR_TIMEOUT;
        }
    }

    // MSG_STROBE goes before each MSG[0] write: the first strobe other than 0xF ends
    // the stream, and a whole-word message ends with strobe 0 and a dummy word.
    ctx->diag.stage = ABR_DRV_STAGE_STREAM;
    const uint32_t words = len / 4u;
    for (uint32_t w = 0; w < words; ++w) {
        stream_word(ctx, 0xFu, le_word(message + 4u * w, 4u), 4u);
    }
    if (final) {
        const uint32_t tail = len & 3u;
        stream_word(ctx, (1u << tail) - 1u, le_word(message + 4u * words, tail), tail);
    }
    ctx->diag.bytes_written = ctx->written;
    return ABR_DRV_OK;
}

static int wait_complete(abr_drv_ctx_t *ctx) {
    ctx->diag.stage = ABR_DRV_STAGE_COMPLETE;
    for (uint32_t i = 0; i < ABR_POLL_COMPLETE; ++i) {
        const uint32_t st = mmio_read32(ABR_STATUS);
        if ((st & ABR_STATUS_ERROR) != 0u) {
            return ABR_DRV_ERR_HW;
        }
        if ((st & ABR_STATUS_VALID) != 0u) {
            break;
        }
        if (i + 1u == ABR_POLL_COMPLETE) {
            return ABR_DRV_ERR_TIMEOUT;
        }
    }

    // Exactly one hardware completion since the events were cleared.
    const uint32_t count = read_done_count();
    ctx->diag.done_count = count;
    if ((mmio_read32(ABR_ERR_STS) & ABR_INTR_STS) != 0u ||
        mmio_read32(ABR_ERR_COUNT) != ctx->err_count) {
        return ABR_DRV_ERR_HW;
    }
    if (count != 1u || (mmio_read32(ABR_DONE_STS) & ABR_INTR_STS) == 0u) {
        return ABR_DRV_ERR_STATE;
    }
    return ABR_DRV_OK;
}

static int check_readback(abr_drv_ctx_t *ctx, const uint8_t *public_key) {
    // PUBKEY and SIGNATURE read back once VALID: the accelerator verified against
    // this key and this c~, not values a fault left behind.
    ctx->diag.stage = ABR_DRV_STAGE_READBACK;
    uint32_t diff = 0u;
    for (uint32_t i = 0; i < PK_WORDS; ++i) {
        diff |= mmio_read32(SEP_TOP_ABR_MLDSA_PUBKEY_BASE_ADDR + 4u * i) ^
                le_word(public_key + 4u * i, 4u);
    }
    for (uint32_t i = 0; i < ABR_DRV_CTILDE_WORDS; ++i) {
        diff |= mmio_read32(SEP_TOP_ABR_MLDSA_SIGNATURE_BASE_ADDR + 4u * i) ^ ctx->ct[i];
    }
    return harden_u32(diff) == 0u ? ABR_DRV_OK : ABR_DRV_ERR_FAULT;
}

static int decide(abr_drv_ctx_t *ctx, uint32_t message_len, uint32_t pass_token,
                  uint32_t *verdict) {
    ctx->diag.stage = ABR_DRV_STAGE_VERDICT;

    const uint32_t diff_a = read_result(ctx);

    // Evaluation B reads VERIFY_RES again and compares laundered operands, so one
    // fault cannot make both agree on a match.
    uint32_t diff_b = 0u;
    for (uint32_t w = 0; w < ABR_DRV_CTILDE_WORDS; ++w) {
        diff_b |= harden_u32(mmio_read32(SEP_TOP_ABR_MLDSA_VERIFY_RES_BASE_ADDR(w))) ^
                  harden_u32(ctx->ct[w]);
    }

    const int pass_a = diff_a == 0u;
    const int pass_b = harden_u32(diff_b) == 0u;
    if (pass_a != pass_b) {
        return ABR_DRV_ERR_FAULT;
    }
    if (!pass_a) {
        return ABR_DRV_ERR_SIG_INVALID;
    }

    // The whole message reached the accelerator, counted twice.
    if ((ctx->written ^ message_len) != 0u || (harden_u32(ctx->written_dup) ^ message_len) != 0u) {
        return ABR_DRV_ERR_SIG_INVALID;
    }

    *verdict = (harden_u32(diff_a) == 0u ? (pass_token ^ ABR_VERDICT_KEY) : 0u) ^
               (harden_u32(diff_b) == 0u ? ABR_VERDICT_KEY : 0u);
    return ABR_DRV_OK;
}

ABR_DRV_STEP int abr_drv_finish(abr_drv_ctx_t *ctx, const uint8_t *public_key, uint32_t message_len,
                                uint32_t pass_token, uint32_t *verdict) {
    *verdict = ~pass_token;

    int rc = wait_complete(ctx);
    if (rc == ABR_DRV_OK) {
        rc = check_readback(ctx, public_key);
    }
    if (rc == ABR_DRV_OK) {
        rc = decide(ctx, message_len, pass_token, verdict);
    }

    // A pass stands only if the accelerator is cleared afterwards.
    const int zrc = abr_drv_zeroize();
    if (rc == ABR_DRV_OK && zrc != ABR_DRV_OK) {
        rc = zrc;
        ctx->diag.stage = ABR_DRV_STAGE_ZEROIZE;
    }
    if (rc != ABR_DRV_OK) {
        *verdict = ~pass_token;
    } else {
        ctx->diag.stage = ABR_DRV_STAGE_DONE;
    }
    return rc;
}

int abr_mldsa87_verify(const uint8_t *public_key, const uint8_t *signature, const uint8_t *message,
                       uint32_t message_len, uint32_t pass_token, uint32_t *verdict,
                       abr_drv_diag_t *diag) {
    if (verdict == NULL) {
        return ABR_DRV_ERR_PARAM;
    }
    *verdict = ~pass_token;
    if (public_key == NULL || signature == NULL || message == NULL ||
        message_len > ABR_MLDSA87_MAX_MSG_BYTES || pass_token == 0u || pass_token == 0xFFFFFFFFu ||
        pass_token == ABR_VERDICT_KEY) {
        return ABR_DRV_ERR_PARAM;
    }

    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);

    int rc = abr_drv_load(&ctx, public_key, signature);
    if (rc == ABR_DRV_OK) {
        rc = abr_drv_start(&ctx);
    }
    if (rc == ABR_DRV_OK) {
        rc = abr_drv_stream_range(&ctx, message, message_len, 1);
    }
    if (rc == ABR_DRV_OK) {
        rc = abr_drv_finish(&ctx, public_key, message_len, pass_token, verdict);
    } else {
        (void)abr_drv_zeroize();
    }
    // rc follows the hardened verdict, so a skipped rejection branch cannot leave
    // ABR_DRV_OK beside a verdict that is not the pass token.
    if (rc == ABR_DRV_OK && harden_u32(*verdict) != pass_token) {
        rc = ABR_DRV_ERR_FAULT;
        *verdict = ~pass_token;
    }

    // Field by field: a struct copy may become a memcpy call, and the ROM has no libc.
    if (diag != NULL) {
        diag->bytes_written = ctx.diag.bytes_written;
        diag->early_valid = ctx.diag.early_valid;
        diag->res_inverse = ctx.diag.res_inverse;
        diag->res_nonzero = ctx.diag.res_nonzero;
        diag->done_count = ctx.diag.done_count;
        diag->stage = ctx.diag.stage;
    }
    return rc;
}

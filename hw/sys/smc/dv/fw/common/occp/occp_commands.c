/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* OCCP request builders, response checks and random command drivers for SMC OCCP tests. */

#include "occp_test_common.h"
#include "sep_ring_buffer_model.h"
#include <stdio.h>
#include <string.h>

/* ---------------------- Single shared TX/RX buffer ---------------------- */
#define OCCP_MAX_BODY_LEN 0x7FF
#define OCCP_MAX_HEADER_SIZE (sizeof(occp_req_header_t))
#define OCCP_OVERSIZE_PAD_MAX 64
#define OCCP_MAX_PACKET_SIZE (OCCP_MAX_HEADER_SIZE + OCCP_MAX_BODY_LEN + 4 + OCCP_OVERSIZE_PAD_MAX)
static uint8_t occp_tx_buf[OCCP_MAX_PACKET_SIZE];

/* ---------------------- CRC error injection helpers ---------------------- */
static void flip_n_random_bits(uint8_t *buf, size_t len, int n) {
    if (buf == NULL || len == 0 || n <= 0) return;
    size_t total_bits = len * 8u;
    if ((size_t)n > total_bits) n = (int)total_bits;

    /* Select n distinct bit indices without replacement */
    size_t selected_count = 0;
    /* Stack VLA: every call site keeps n at or below 32. */
    size_t selected_indices[n];

    while (selected_count < (size_t)n) {
        size_t bit_index = (size_t)(get_random_int() & 0x7fffffff) % total_bits;
        int duplicate = 0;
        for (size_t i = 0; i < selected_count; i++) {
            if (selected_indices[i] == bit_index) {
                duplicate = 1;
                break;
            }
        }
        if (duplicate) continue;
        selected_indices[selected_count++] = bit_index;
    }

    for (size_t i = 0; i < selected_count; i++) {
        size_t bit_index = selected_indices[i];
        size_t byte_index = bit_index >> 3;
        uint8_t bit_mask = (uint8_t)(1u << (bit_index & 7u));
        buf[byte_index] ^= bit_mask;
    }
}

static int choose_num_flips_crc8(bool detectable) {
    if (detectable) return 1 + (get_random_int() % 4);
    return 5 + (get_random_int() % 4);
}

static int choose_num_flips_crc32(bool detectable) {
    if (detectable) return 1 + (get_random_int() % 6);
    return 7 + (get_random_int() % 10);
}

static void inject_header_errors_if_enabled(test_context_t *ctx, uint8_t *hdr_bytes,
                                            size_t hdr_len) {
    if (ctx->header_crc_err_inject_mode == OCCP_CRC_INJECT_NONE) return;

    if (ctx->header_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
        /* Flip bits only in the header CRC byte */
        flip_n_random_bits(hdr_bytes, 1, (get_random_int() % 8 + 1));
        simputs("OCCP: Corrupted header CRC byte\n");
        return;
    }

    /* Flip bits after the CRC byte so the stored header CRC no longer matches. */
    if (hdr_len <= 1) return;
    uint8_t *fields = hdr_bytes + 1;
    size_t fields_len = hdr_len - 1;
    bool want_detectable = (ctx->header_crc_err_inject_mode == OCCP_CRC_INJECT_DETECTABLE);
    int flips = choose_num_flips_crc8(want_detectable);
    flip_n_random_bits(fields, fields_len, flips);
    simputshex16("OCCP: Injected header bit flips: ", (uint16_t)flips);
}

static void inject_body_errors_if_enabled(test_context_t *ctx, uint8_t *body_bytes, size_t body_len,
                                          bool use_crc32) {
    if ((ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_NONE) ||
        (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC))
        return;
    if (body_len == 0) return;
    bool want_detectable = (ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_DETECTABLE);
    int flips = use_crc32 ? choose_num_flips_crc32(want_detectable)
                          : choose_num_flips_crc8(want_detectable);
    flip_n_random_bits(body_bytes, body_len, flips);
    simputshex16("OCCP: Injected body bit flips: ", (uint16_t)flips);
}

/* Send a truncated header and expect an OCCP_INCOMPLETE_MSG error response. */
static int send_undersize_header_only(test_context_t *ctx, uint64_t i3c_addr, const uint8_t *hdr,
                                      size_t hdr_len) {
    ctx->exp_response_code = OCCP_INCOMPLETE_MSG;
    if (hdr_len < 2) return OCCP_INVALID_ARG;
    size_t short_len = (size_t)(1 + (get_random_int() % (hdr_len - 1)));

    if (ctx->type == DRIVER_TYPE_I3C) {
        if (ctx->drv.i3c_drv == NULL) return OCCP_INTERFACE_ERR;
        ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, (uint8_t *)hdr,
                                              short_len);
    } else {
        if (ctx->drv.i2c_drv == NULL) return OCCP_INTERFACE_ERR;
        ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, (uint8_t *)hdr, short_len,
                                                    ctx->timeout);
    }

    occp_resp_header_t resp_hdr;
    int rc = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    return (rc == OCCP_ERROR_NONE) ? OCCP_SUCCESS : rc;
}

static int verify_resp_header_crc(const occp_resp_header_t *resp_hdr) {
    const uint8_t *bytes = (const uint8_t *)resp_hdr;
    uint8_t calc = calculate_crc8((uint8_t *)(bytes + 1), sizeof(*resp_hdr) - 1);
    if (calc != resp_hdr->header_crc) {
        simputshex16("OCCP: Response header CRC mismatch calc:", calc);
        simputshex16("OCCP: Response header CRC mismatch recv:", resp_hdr->header_crc);
        return -1;
    }
    return 0;
}

/*
 * Read header_len body bytes and, when present, the trailing CRC that the length excludes.
 * On success, copies the body without CRC into out_buf and sets *out_len.
 */
static int read_body_and_verify_crc(test_context_t *ctx, uint64_t i3c_addr, bool body_crc_present,
                                    uint16_t header_len, uint8_t *out_buf, uint16_t out_buf_size,
                                    /*out*/ uint16_t *out_len) {
    simputs("OCCP: Reading body and verifying CRC\n");
    simputshex16("OCCP: Body CRC present: ", body_crc_present);
    simputshex16("OCCP: Header length: ", header_len);
    if (!body_crc_present) {
        if (header_len == 0) {
            *out_len = 0;
            return OCCP_SUCCESS;
        }
        if (header_len > out_buf_size) return OCCP_READ_UNDERFLOW;
        if (ctx->type == DRIVER_TYPE_I3C) {
            int status;
            bool timeout_enabled = ctx->timeout != 0;
            int count = timeout_enabled ? ctx->timeout : 1;
            do {
                status = ctx->drv.i3c_drv->read(ctx->drv.i3c_drv, i3c_addr, out_buf, header_len);
                if ((status != I3C_OK) && (status != I3C_ERR_CMD_FAILED)) return OCCP_INTERFACE_ERR;
                if (timeout_enabled) count--;
            } while ((count > 0) && (status != I3C_OK));
            if (count == 0) {
                return OCCP_TIMEOUT;
            }
        } else {
            size_t rx_num_bytes;
            int status = ctx->drv.i2c_drv->ctrlr_receive_data_w_timeout(
                ctx->drv.i2c_drv, out_buf, header_len, &rx_num_bytes, ctx->timeout);
            if (status != I2C_OK) return OCCP_INTERFACE_ERR;
        }
        *out_len = header_len;
        return OCCP_SUCCESS;
    }

    uint16_t expected_crc_size = (header_len > 14) ? 4 : 1;
    if (header_len > out_buf_size) return OCCP_READ_UNDERFLOW;

    uint8_t *temp_buf = occp_tx_buf;
    uint16_t body_size = header_len + expected_crc_size;
    if (body_size > OCCP_MAX_PACKET_SIZE) return OCCP_READ_UNDERFLOW;

    simputshex16("OCCP: Reading body size ", body_size);
    // Body and CRC arrive in one read.
    if (body_size) {
        if (ctx->type == DRIVER_TYPE_I3C) {
            int status;
            bool timeout_enabled = ctx->timeout != 0;
            int count = timeout_enabled ? ctx->timeout : 1;
            do {
                status = ctx->drv.i3c_drv->read(ctx->drv.i3c_drv, i3c_addr, temp_buf, body_size);
                if ((status != I3C_OK) && (status != I3C_ERR_CMD_FAILED)) return OCCP_INTERFACE_ERR;
                if (timeout_enabled) count--;
            } while ((count > 0) && (status != I3C_OK));
            if (count == 0) {
                return OCCP_TIMEOUT;
            }
        } else {
            size_t rx_num_bytes;
            int status = ctx->drv.i2c_drv->ctrlr_receive_data_w_timeout(
                ctx->drv.i2c_drv, temp_buf, body_size, &rx_num_bytes, ctx->timeout);
            if (status != I2C_OK) return OCCP_INTERFACE_ERR;
        }
    }

    // The CRC follows the header_len body bytes.
    uint8_t crc_tail[4] = {0};
    memcpy(crc_tail, temp_buf + header_len, expected_crc_size);

    int crc_ok = 0;
    if (expected_crc_size == 4) {
        uint32_t crc_recv;
        memcpy(&crc_recv, crc_tail, 4);
        uint32_t crc_calc = calculate_crc32(temp_buf, body_size - expected_crc_size);
        crc_ok = (crc_calc == crc_recv);
    } else {
        uint8_t crc_recv = crc_tail[0];
        uint8_t crc_calc = calculate_crc8(temp_buf, body_size - expected_crc_size);
        crc_ok = (crc_calc == crc_recv);
    }
    if (!crc_ok) {
        simputs("OCCP: Body CRC mismatch\n");
        return OCCP_ERR;
    }
    if ((body_size - expected_crc_size) > out_buf_size) return OCCP_READ_UNDERFLOW;
    memcpy(out_buf, temp_buf, body_size - expected_crc_size);
    *out_len = body_size - expected_crc_size;
    return OCCP_SUCCESS;
}

int occp_get_response_header(test_context_t *ctx, uint64_t i3c_addr,
                             /*out*/ occp_resp_header_t *resp_hdr) {
    bool timeout_enabled = ctx->timeout != 0;
    int count = timeout_enabled ? ctx->timeout : 1;
    uint8_t *resp_hdr_ptr = (uint8_t *)resp_hdr;
    if (ctx->type == DRIVER_TYPE_I3C) {
        int status;
        simputs("OCCP: Reading response header\n");
        do {
            status =
                ctx->drv.i3c_drv->read(ctx->drv.i3c_drv, i3c_addr, resp_hdr_ptr, sizeof(*resp_hdr));
            if ((status != I3C_OK) && (status != I3C_ERR_CMD_FAILED)) return OCCP_INTERFACE_ERR;

            if (timeout_enabled) count--;
        } while ((count > 0) && (status != I3C_OK));
        if (count == 0) {
            if (ctx->exp_timeout) {
                simputs("OCCP: Received expected timeout\n");
                return OCCP_SUCCESS;
            }
            return OCCP_TIMEOUT;
        }
    } else {
        size_t rx_num_bytes;
        int status = ctx->drv.i2c_drv->ctrlr_receive_data_w_timeout(
            ctx->drv.i2c_drv, resp_hdr_ptr, sizeof(*resp_hdr), &rx_num_bytes, ctx->timeout);
        if (ctx->exp_timeout && status == I2C_TIMEOUT) {
            simputs("OCCP: Received expected timeout\n");
            return OCCP_SUCCESS;
        }
        if (status != I2C_OK) return OCCP_INTERFACE_ERR;
    }

    if (ctx->exp_timeout) {
        simputs("Did not receive expected timeout\n");
        return OCCP_ERR;
    }

    if (verify_resp_header_crc(resp_hdr) != 0) {
        return OCCP_ERR;
    }

    if (resp_hdr->error) {
        uint32_t error_code = 0;
        simputs("OCCP response error\n");
        if (resp_hdr->length == sizeof(error_code)) {
            // Read error body and CRC (CRC8 expected)
            uint8_t body_buf[8] = {0};
            uint16_t body_len = 0;
            int rc =
                read_body_and_verify_crc(ctx, i3c_addr, resp_hdr->body_crc_present,
                                         resp_hdr->length, body_buf, sizeof(body_buf), &body_len);
            if (rc != OCCP_SUCCESS) return rc;
            if (body_len != sizeof(error_code)) return OCCP_ERR;
            memcpy(&error_code, body_buf, sizeof(error_code));
        } else {
            simputs("OCCP response error: length != sizeof(error_code)\n");
            return OCCP_ERR;
        }
        if (print_error_code(error_code) != 0) {
            return OCCP_ERR;
        }

        /* Under length injection, OCCP_INVALID_REQ_LEN is the expected outcome. */
        if (ctx->invalid_len_err_inject_enable && error_code == OCCP_INVALID_REQ_LEN) {
            simputs("OCCP: Expected invalid length error under injection\n");
            return OCCP_SUCCESS;
        }

        if (ctx->exp_response_code == OCCP_ERROR_NONE) {
            if (ctx->header_crc_err_inject_mode != OCCP_CRC_INJECT_NONE &&
                error_code == OCCP_CORRUPT_HEADER) {
                simputs("received expected error code: OCCP_CORRUPT_HEADER\n");
                return OCCP_SUCCESS;
            }
            if (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE &&
                error_code == OCCP_CORRUPT_DATA) {
                simputs("received expected error code: OCCP_CORRUPT_DATA\n");
                return OCCP_SUCCESS;
            }
            if (((ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_DETECTABLE) ||
                 (ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_UNDETECTABLE)) &&
                (error_code == OCCP_UNSUPPORTED_STATUS)) {
                simputs("received expected error code: OCCP_UNSUPPORTED_STATUS (body corruption "
                        "can cause this as well)\n");
                return OCCP_SUCCESS;
            }

            simputshex32("OCCP response error: expected none but got error: ", error_code);
            return OCCP_ERR;
        } else if (ctx->exp_response_code != error_code) {
            simputshex32("OCCP response error: expected error code: ", ctx->exp_response_code);
            simputshex32("but got: ", error_code);
            return OCCP_ERR;
        }
    } else {
        if (ctx->invalid_len_err_inject_enable) {
            simputs("OCCP: Non-error response under invalid length injection (FAIL)\n");
            ctx->overall_result = false;
            return OCCP_ERR;
        }
        if (ctx->header_crc_err_inject_mode == OCCP_CRC_INJECT_DETECTABLE ||
            ctx->header_crc_err_inject_mode == OCCP_CORRUPT_CRC ||
            ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_DETECTABLE ||
            ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
            simputs("OCCP response no error despite predicted corruption\n");
            return OCCP_ERR;
        }

        if (ctx->exp_response_code != OCCP_ERROR_NONE) {
            simputshex32("OCCP response error: expected error code but got none: ",
                         ctx->exp_response_code);
            return OCCP_ERR;
        }
    }
    simputshex16("OCCP response length: ", resp_hdr->length);
    return OCCP_SUCCESS;
}

/* ---------------- Invalid header injection (msg_id/app_id) ---------------- */
static uint16_t choose_random_body_len_like_rw(void) {
    /* Reuse write-size distribution for the dummy trailing bytes after invalid header */
    return get_random_occp_write_size();
}

int occp_send_invalid_header_command(test_context_t *ctx, uint64_t i3c_addr) {
    uint8_t app_id;
    uint8_t msg_id;
    static uint8_t buff[8 + 2048 + 4] = {0};

    switch (ctx->invalid_header_inject_mode) {
    case OCCP_INVALID_HDR_INVALID_MSGID: {
        app_id = (uint8_t)(get_random_int() % 2); /* valid app: 0 or 1 */
        if (app_id == 0) {
            msg_id = (uint8_t)(4 + (get_random_int() % 252));
        } else {
            msg_id = (uint8_t)(4 + (get_random_int() % 253));
        }
        break;
    }
    case OCCP_INVALID_HDR_INVALID_APPID: {
        app_id = (uint8_t)(2 + (get_random_int() % 254)); /* invalid app */
        msg_id = (uint8_t)(get_random_int() % 4);         /* valid msg for base/boot */
        break;
    }
    case OCCP_INVALID_HDR_INVALID_BOTH: {
        app_id = (uint8_t)(2 + (get_random_int() % 254));
        msg_id = (uint8_t)(4 + (get_random_int() % 252));
        break;
    }
    default: {
        /* With no mode set, send an invalid msg_id. */
        app_id = (uint8_t)(get_random_int() % 2);
        msg_id = (uint8_t)((app_id == 0) ? (4 + (get_random_int() % 252))
                                         : (3 + (get_random_int() % 253)));
        break;
    }
    }

    uint16_t body_len = choose_random_body_len_like_rw();
    bool has_body_crc = (get_random_int() % 2) == 0;

    occp_req_header_word_t hdr_word;
    hdr_word.app_id = app_id;
    hdr_word.msg_id = msg_id;
    hdr_word.flags = 0;
    hdr_word.length = (uint16_t)(body_len & 0x7FF);
    occp_req_header_t hdr;
    hdr.body_crc_present = has_body_crc;
    hdr.reserved = 0;
    hdr.header_word = hdr_word;
    hdr.header_crc = calculate_crc8(((uint8_t *)&hdr) + 1, sizeof(hdr) - 1);

    if (ctx->inject_undersize_header_err) {
        return send_undersize_header_only(ctx, i3c_addr, (const uint8_t *)&hdr, sizeof(hdr));
    }

    /* Frame: header, random body, optional body CRC (CRC-32 above 14 bytes). */
    for (int i = 0; i < sizeof(hdr); i++) {
        buff[i] = ((uint8_t *)&hdr)[i];
    }

    if (body_len > 0 || has_body_crc) {
        for (uint16_t i = 0; i < body_len; i++)
            buff[sizeof(hdr) + i] = (uint8_t)(get_random_int() & 0xFF);
        int tail = 0;
        if (has_body_crc) {
            if (body_len > 14) {
                uint32_t crc = calculate_crc32(buff + sizeof(hdr), body_len);
                memcpy(buff + sizeof(hdr) + body_len, &crc, sizeof(crc));
                tail = 4;
            } else {
                uint8_t crc = calculate_crc8(buff + sizeof(hdr), body_len);
                memcpy(buff + sizeof(hdr) + body_len, &crc, sizeof(crc));
                tail = 1;
            }
        }
        size_t total = sizeof(hdr) + body_len + tail;
        if (ctx->type == DRIVER_TYPE_I3C) {
            ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, buff, total);
        } else {
            ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, buff, total,
                                                        ctx->timeout);
        }
    }

    switch (ctx->invalid_header_inject_mode) {
    case OCCP_INVALID_HDR_INVALID_MSGID:
        ctx->exp_response_code = OCCP_INVALID_MSGID;
        break;
    case OCCP_INVALID_HDR_INVALID_APPID:
        ctx->exp_response_code = OCCP_INVALID_APPID;
        break;
    case OCCP_INVALID_HDR_INVALID_BOTH:
        ctx->exp_response_code = OCCP_INVALID_APPID;
        break; /* AppID precedence */
    default:
        ctx->exp_response_code = OCCP_INVALID_MSGID;
        break;
    }

    occp_resp_header_t resp_hdr;
    int retval = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    if (retval != OCCP_ERROR_NONE) return retval;

    ctx->exp_response_code = OCCP_ERROR_NONE;
    return OCCP_SUCCESS;
}

int occp_send_write_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr,
                            const uint8_t *data, uint16_t byte_length) {
    occp_write_header_t write_hdr;

    int data_start_idx = sizeof(write_hdr);
    int body_start = sizeof(write_hdr.header);
    int body_length = byte_length + (data_start_idx - body_start);
    /* Body CRC present: random unless forcing injection, in which case always present */
    bool has_body_crc = (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE)
                            ? true
                            : ((get_random_int() % 2) != 0);

    uint16_t body_len = (uint16_t)body_length;
    if (ctx->invalid_message_length_zero_inject_enable) {
        /* Keep header body length to metadata size (12); data omitted */
        body_len = (uint16_t)(sizeof(occp_write_header_t) - sizeof(occp_req_header_t));
        simputs("OCCP: WRITE inject: body=12, internal write_length=0\n");
    } else if (ctx->invalid_len_err_inject_enable) {
        body_len = (uint16_t)(get_random_int() % 12);
        if (body_len == 0) {
            has_body_crc = false; /* header-only: do not advertise body CRC */
        }
        simputshex16("OCCP: Random invalid WRITE length (0..11): ", body_len);
    }

    int crc_size = 0;
    if (has_body_crc) {
        crc_size = (body_len > 14) ? 4 : 1;
    }

    write_hdr.header = occp_encode_header_word(OCCP_WRITE, body_len, has_body_crc);
    write_hdr.addr = addr;
    write_hdr.write_length = byte_length;
    if (ctx->invalid_message_length_zero_inject_enable) {
        write_hdr.write_length = 0;
    }
    write_hdr.rwrite_attr = 0;
    write_hdr.reserved = 0;

    if (ctx->inject_undersize_header_err) {
        return send_undersize_header_only(ctx, i3c_addr, (const uint8_t *)&write_hdr,
                                          sizeof(write_hdr.header));
    }

    uint8_t *tx_buf = occp_tx_buf;
    size_t header_size = sizeof(write_hdr.header);
    memcpy(tx_buf, &write_hdr.header, header_size);

    size_t total_bytes;
    size_t meta_len = (size_t)(data_start_idx - (int)header_size);
    size_t meta_copy_len = (body_len <= meta_len) ? body_len : meta_len;
    if (meta_copy_len > 0) {
        memcpy(tx_buf + header_size, ((uint8_t *)&write_hdr) + header_size, meta_copy_len);
    }
    size_t curr_off = header_size + meta_copy_len;
    size_t remaining = (size_t)body_len - meta_copy_len;
    if (remaining > 0) {
        size_t data_copy_len = (remaining <= byte_length) ? remaining : byte_length;
        if (data_copy_len > 0) {
            memcpy(tx_buf + curr_off, data, data_copy_len);
            curr_off += data_copy_len;
            remaining -= data_copy_len;
        }
        /* Pad with random bytes if injected length exceeds available metadata + data */
        for (size_t i = 0; i < remaining; i++) {
            tx_buf[curr_off + i] = (uint8_t)(get_random_int() & 0xFF);
        }
        curr_off += remaining;
    }

    if (has_body_crc && body_len > 0) {
        const uint8_t *body_ptr = tx_buf + header_size;
        if (crc_size == 4) {
            uint32_t crc = calculate_crc32((uint8_t *)body_ptr, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 32 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
        } else {
            uint8_t crc = calculate_crc8((uint8_t *)body_ptr, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 8 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
        }
    }
    total_bytes = header_size + body_len + ((has_body_crc && body_len > 0) ? crc_size : 0);

    /* Undersize body injection: truncate the frame inside the body or CRC. */
    if (ctx->inject_undersize_body_err && body_len > 0) {
        uint16_t short_len = get_random_int() % (total_bytes - header_size);
        total_bytes = header_size + short_len;
    }

    /* Oversize body injection: append 1..OCCP_OVERSIZE_PAD_MAX random bytes. */
    if (ctx->inject_oversize_body_err) {
        uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
        for (uint16_t i = 0; i < extra_len; i++) {
            tx_buf[total_bytes + i] = (uint8_t)(get_random_int() & 0xFF);
        }
        total_bytes += extra_len;
    }

    inject_header_errors_if_enabled(ctx, tx_buf, header_size);
    if (has_body_crc && body_len > 0) {
        bool use_crc32 = (crc_size == 4);
        inject_body_errors_if_enabled(ctx, tx_buf + body_start, body_len, use_crc32);
    }

    if (ctx->type == DRIVER_TYPE_I3C) {
        if (ctx->drv.i3c_drv == NULL) {
            simputs("I3C driver not initialized\n");
            return OCCP_INTERFACE_ERR;
        }
        ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf, total_bytes);
    } else {
        if (ctx->drv.i2c_drv == NULL) {
            simputs("I2C driver not initialized\n");
            return OCCP_INTERFACE_ERR;
        }
        ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf, total_bytes,
                                                    ctx->timeout);
    }

    occp_resp_header_t resp_hdr;
    int retval = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    if (retval != OCCP_ERROR_NONE) {
        return retval;
    }

    return OCCP_SUCCESS;
}

int occp_send_read_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr, uint8_t *recv,
                           uint16_t byte_length) {
    occp_read_header_t read_hdr;
    /* Body CRC present: random unless forcing injection, in which case always present */
    bool has_body_crc = (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE)
                            ? true
                            : ((get_random_int() % 2) == 0);
    uint16_t body_len = (uint16_t)(sizeof(occp_read_header_t) - sizeof(occp_req_header_t));

    uint16_t injected_len = body_len;
    if (ctx->invalid_len_err_inject_enable) {
        uint16_t lower;
        if (body_len > 1) {
            uint16_t max_lower = (uint16_t)(body_len - 1);
            lower = (uint16_t)(1 + (get_random_int() % max_lower));
        } else {
            lower = 1;
        }
        uint16_t upper_min = (uint16_t)(body_len + 1);
        uint16_t upper_max = 0x100;
        uint16_t upper =
            (upper_min <= upper_max)
                ? (uint16_t)(upper_min + (get_random_int() % (upper_max - upper_min + 1)))
                : upper_max;
        const uint16_t candidates[3] = {0, lower, upper};
        injected_len = candidates[get_random_int() % 3];
        simputshex16("OCCP: Random invalid READ length: ", injected_len);
    }

    read_hdr.header = occp_encode_header_word(OCCP_READ, body_len, has_body_crc);
    read_hdr.addr = addr;
    read_hdr.read_length = byte_length;
    if (ctx->invalid_message_length_zero_inject_enable) {
        read_hdr.read_length = 0;
    }
    read_hdr.read_attr = 0;

    if (ctx->inject_undersize_header_err) {
        return send_undersize_header_only(ctx, i3c_addr, (const uint8_t *)&read_hdr,
                                          sizeof(read_hdr.header));
    }

    /* Override the length field after encoding */
    if (ctx->invalid_len_err_inject_enable) {
        read_hdr.header.header_word.length = injected_len & 0x7FF;
        /* Do not force body CRC presence based on length; honor header flag */
        /* Recalculate the header CRC over the new length. */
        read_hdr.header.header_crc =
            calculate_crc8(((uint8_t *)&read_hdr.header) + 1, sizeof(read_hdr.header) - 1);
        body_len = injected_len;
    }

    uint8_t *tx_buf = occp_tx_buf;
    int crc_size = 0;
    size_t tx_len;
    size_t header_size = sizeof(read_hdr.header);
    size_t available_body = sizeof(read_hdr) - header_size;
    size_t copy_len = (body_len <= available_body) ? body_len : available_body;

    memcpy(tx_buf, &read_hdr.header, header_size);

    /* Build body (truncate to available bytes) */
    if (copy_len > 0) {
        const uint8_t *body_ptr = ((const uint8_t *)&read_hdr) + header_size;
        memcpy(tx_buf + header_size, body_ptr, copy_len);
    }
    /* Pad with random data if injected length exceeds struct body */
    if (body_len > copy_len) {
        size_t pad_len = (size_t)body_len - copy_len;
        uint8_t *pad_ptr = tx_buf + header_size + copy_len;
        for (size_t i = 0; i < pad_len; i++) {
            pad_ptr[i] = (uint8_t)(get_random_int() & 0xFF);
        }
    }

    if (has_body_crc && body_len > 0) {
        const uint8_t *body_start = tx_buf + header_size;
        if (body_len > 14) {
            uint32_t crc = calculate_crc32((uint8_t *)body_start, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 32 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
            crc_size = 4;
        } else {
            uint8_t crc = calculate_crc8((uint8_t *)body_start, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 8 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
            crc_size = 1;
        }
    }

    /* Oversize body injection: append 1..OCCP_OVERSIZE_PAD_MAX random bytes. */
    if (ctx->inject_oversize_body_err) {
        size_t base_len = header_size + body_len + crc_size;
        uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
        for (uint16_t i = 0; i < extra_len; i++) {
            tx_buf[base_len + i] = (uint8_t)(get_random_int() & 0xFF);
        }
        tx_len = base_len + extra_len;
    } else if (ctx->inject_undersize_body_err && body_len > 0) {
        uint16_t short_len = get_random_int() % (body_len + crc_size);
        tx_len = header_size + short_len;
    } else {
        tx_len = header_size + body_len + crc_size;
    }

    inject_header_errors_if_enabled(ctx, tx_buf, header_size);
    if (has_body_crc && body_len > 0) {
        bool use_crc32 = (crc_size == 4);
        inject_body_errors_if_enabled(ctx, tx_buf + header_size, body_len, use_crc32);
    }

    if (ctx->type == DRIVER_TYPE_I3C) {
        if (ctx->drv.i3c_drv == NULL) {
            simputs("I3C driver not initialized\n");
            return OCCP_INTERFACE_ERR;
        }
        ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf, tx_len);
    } else {
        if (ctx->drv.i2c_drv == NULL) {
            simputs("I2C driver not initialized\n");
            return OCCP_INTERFACE_ERR;
        }
        ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf, tx_len, ctx->timeout);
    }

    occp_resp_header_t resp_hdr;
    int retval = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    if (retval != OCCP_ERROR_NONE) {
        return retval;
    }
    /* occp_get_response_header already checked the expected unsupported-status-ID error. */
    if (ctx->unsupported_status_id_inject_enable && resp_hdr.error) {
        ctx->exp_response_code = OCCP_ERROR_NONE;
        return OCCP_SUCCESS;
    }
    if (ctx->exp_timeout) {
        return OCCP_SUCCESS;
    }

    if (!resp_hdr.error) {
        static uint8_t recv_buff[MAX_OCCP_READ_SIZE + 4];
        uint16_t data_len = 0;
        int rc = read_body_and_verify_crc(ctx, i3c_addr, resp_hdr.body_crc_present, resp_hdr.length,
                                          recv_buff, sizeof(recv_buff), &data_len);
        if (rc != OCCP_SUCCESS) return rc;
        simputshex16("OCCP_READ verified data length: ", data_len);
        memcpy(recv, recv_buff, data_len);
    }
    return OCCP_SUCCESS;
}

static int occp_send_generic_get_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t cmd,
                                         uint32_t *statusBuff) {
    bool is_status_command = false;
    switch (cmd) {
    case OCCP_GET_VERSION:
        simputs("Sending GET_VERSION command\n");
        break;
    case OCCP_GET_VERSION_BOOT:
        simputs("Sending GET_VERSION_BOOT command\n");
        break;
    case OCCP_GET_OCCP_BOOT_STATUS:
        simputs("Sending GET_OCCP_BOOT_STATUS command\n");
        is_status_command = true;
        break;
    case OCCP_GET_OCCP_INTERFACE_STATUS:
        simputs("Sending GET_OCCP_INTERFACE_STATUS command\n");
        is_status_command = true;
        break;
    case OCCP_GET_OCCP_COMMAND_COUNT:
        simputs("Sending GET_OCCP_COMMAND_COUNT command\n");
        is_status_command = true;
        break;
    case OCCP_GET_OCCP_ERROR_CODE:
        simputs("Sending GET_OCCP_ERROR_CODE command\n");
        is_status_command = true;
        break;
    case OCCP_GET_SEP_STATUS:
        simputs("Sending GET_SEP_STATUS command\n");
        is_status_command = true;
        break;
    case OCCP_GET_SMC_STATUS:
        simputs("Sending GET_SMC_STATUS command\n");
        is_status_command = true;
        break;
    default:
        simputs("Unknown command for generic status\n");
        return OCCP_INVALID_CMD;
    }

    /* Version commands have no body; the others carry a 2-byte status ID. */
    uint16_t body_len = (cmd == OCCP_GET_VERSION || cmd == OCCP_GET_VERSION_BOOT) ? 0 : 2;
    bool has_body_crc = (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE)
                            ? (body_len > 0)
                            : (((get_random_int() % 2) == 0) && (body_len > 0));

    uint16_t injected_len = body_len;
    bool inject_len_err = ctx->invalid_len_err_inject_enable;
    if (inject_len_err) {
        if (body_len == 0) {
            /* Version commands expect length 0, so any non-zero length is invalid. */
            injected_len = (uint16_t)(1 + (get_random_int() % 0x100));
        } else {
            uint16_t lower;
            if (body_len > 1) {
                uint16_t max_lower = (uint16_t)(body_len - 1);
                lower = (uint16_t)(1 + (get_random_int() % max_lower));
            } else {
                lower = 1;
            }
            uint16_t upper_min = (uint16_t)(body_len + 1);
            uint16_t upper_max = 0x7FF;
            uint16_t upper =
                (upper_min <= upper_max)
                    ? (uint16_t)(upper_min + (get_random_int() % (upper_max - upper_min + 1)))
                    : upper_max;
            const uint16_t candidates[3] = {0, lower, upper};
            injected_len = candidates[get_random_int() % 3];
        }
        simputshex16("OCCP: Random invalid GET length: ", injected_len);
    }

    occp_req_header_t header_word = occp_encode_header_word(cmd, body_len, has_body_crc);

    if (ctx->inject_undersize_header_err) {
        return send_undersize_header_only(ctx, i3c_addr, (const uint8_t *)&header_word,
                                          sizeof(header_word));
    }

    /* Override the length field after encoding */
    if (inject_len_err) {
        header_word.header_word.length = injected_len & 0x7FF;
        /* Recalculate header CRC with the new length */
        header_word.header_crc =
            calculate_crc8(((uint8_t *)&header_word) + 1, sizeof(header_word) - 1);
        /* Do not force body CRC presence based on length; honor header flag */
        header_word.header_crc =
            calculate_crc8(((uint8_t *)&header_word) + 1, sizeof(header_word) - 1);
        body_len = injected_len;
    }

    inject_header_errors_if_enabled(ctx, (uint8_t *)&header_word, sizeof(header_word));
    uint8_t *tx_buf = occp_tx_buf;

    memcpy(tx_buf, &header_word, sizeof(header_word));

    // send status ID for non-version commands
    if (cmd != OCCP_GET_VERSION && cmd != OCCP_GET_VERSION_BOOT) {
        uint16_t status_id = 0;
        switch (cmd) {
        case OCCP_GET_OCCP_BOOT_STATUS:
            status_id = 0;
            break;
        case OCCP_GET_OCCP_INTERFACE_STATUS:
            status_id = 1;
            break;
        case OCCP_GET_OCCP_COMMAND_COUNT:
            status_id = 2;
            break;
        case OCCP_GET_OCCP_ERROR_CODE:
            status_id = 3;
            break;
        case OCCP_GET_SEP_STATUS:
            status_id = 0x8000;
            break;
        case OCCP_GET_SMC_STATUS:
            status_id = 0x8001;
            break;
        default:
            status_id = 0;
            break;
        }

        if (ctx->unsupported_status_id_inject_enable) {
            uint16_t candidate;
            do {
                candidate = (uint16_t)(get_random_int() & 0xFFFF);
            } while (candidate == 0u || candidate == 1u || candidate == 2u || candidate == 3u ||
                     candidate == 0x8000u || candidate == 0x8001u);
            status_id = candidate;
            simputshex16("OCCP: Injecting unsupported status_id 0x", status_id);
        }

        /* Status ID body, padded with random bytes when the injected length is longer. */
        memset(tx_buf + sizeof(header_word), 0, body_len + 4);
        size_t copy_size = (body_len < sizeof(status_id)) ? body_len : sizeof(status_id);
        if (copy_size > 0) memcpy(tx_buf + sizeof(header_word), &status_id, copy_size);
        if (body_len > copy_size) {
            size_t pad_len = (size_t)body_len - copy_size;
            uint8_t *pad_ptr = tx_buf + sizeof(header_word) + copy_size;
            for (size_t i = 0; i < pad_len; i++) pad_ptr[i] = (uint8_t)(get_random_int() & 0xFF);
        }
        int crc_size = 0;
        if (has_body_crc && body_len > 0) {
            if (body_len > 14) {
                uint32_t crc = calculate_crc32(tx_buf + sizeof(header_word), body_len);
                if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                    flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 32 + 1));
                    simputs("OCCP: Corrupted body CRC\n");
                }
                memcpy(tx_buf + sizeof(header_word) + body_len, &crc, sizeof(crc));
                crc_size = 4;
            } else {
                uint8_t crc = calculate_crc8(tx_buf + sizeof(header_word), body_len);
                if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                    flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 8 + 1));
                    simputs("OCCP: Corrupted body CRC\n");
                }
                memcpy(tx_buf + sizeof(header_word) + body_len, &crc, sizeof(crc));
                crc_size = 1;
            }
        }
        if (has_body_crc && body_len > 0) {
            bool use_crc32 = (crc_size == 4);
            inject_body_errors_if_enabled(ctx, tx_buf + sizeof(header_word), body_len, use_crc32);
        }
        size_t total = body_len + crc_size;

        if (ctx->inject_oversize_body_err) {
            /* Oversize body injection: append 1..OCCP_OVERSIZE_PAD_MAX random bytes. */
            uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
            for (uint16_t i = 0; i < extra_len; i++) {
                tx_buf[sizeof(header_word) + total + i] = (uint8_t)(get_random_int() & 0xFF);
            }
            total += extra_len;
        } else if (ctx->inject_undersize_body_err) {
            size_t short_len = get_random_int() % total;
            total = short_len;
        }

        if (ctx->type == DRIVER_TYPE_I3C) {
            ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf,
                                                  sizeof(header_word) + total);
        } else {
            ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf,
                                                        sizeof(header_word) + total, ctx->timeout);
        }
    } else if (inject_len_err && body_len > 0) {
        /* Version command with an injected non-zero length: random body bytes. */
        for (uint16_t i = 0; i < body_len; i++)
            tx_buf[sizeof(header_word) + i] = (uint8_t)(get_random_int() & 0xFF);
        int crc_size = 0;
        if (has_body_crc) {
            if (body_len > 14) {
                uint32_t crc = calculate_crc32(tx_buf + sizeof(header_word), body_len);
                memcpy(tx_buf + body_len, &crc, sizeof(crc));
                crc_size = 4;
            } else {
                uint8_t crc = calculate_crc8(tx_buf + sizeof(header_word), body_len);
                memcpy(tx_buf + body_len, &crc, sizeof(crc));
                crc_size = 1;
            }
        }
        size_t total = body_len + crc_size;

        if (ctx->inject_undersize_body_err) {
            uint16_t short_len = get_random_int() % total;
            total = short_len;
        } else if (ctx->inject_oversize_body_err) {
            uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
            for (uint16_t i = 0; i < extra_len; i++) {
                tx_buf[sizeof(header_word) + total + i] = (uint8_t)(get_random_int() & 0xFF);
            }
            total += extra_len;
        }

        if (ctx->type == DRIVER_TYPE_I3C) {
            ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf,
                                                  sizeof(header_word) + total);
        } else {
            ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf,
                                                        sizeof(header_word) + total, ctx->timeout);
        }
    } else {
        /* Version command: header only, plus random bytes under oversize injection. */
        if (ctx->inject_oversize_body_err) {
            size_t base_len = sizeof(header_word);
            uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
            for (uint16_t i = 0; i < extra_len; i++) {
                tx_buf[base_len + i] = (uint8_t)(get_random_int() & 0xFF);
            }
            if (ctx->type == DRIVER_TYPE_I3C) {
                ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf,
                                                      base_len + extra_len);
            } else {
                ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf,
                                                            base_len + extra_len, ctx->timeout);
            }
        } else {
            if (ctx->type == DRIVER_TYPE_I3C) {
                ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr,
                                                      (uint8_t *)&header_word, sizeof(header_word));
            } else {
                ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(
                    ctx->drv.i2c_drv, (uint8_t *)&header_word, sizeof(header_word), ctx->timeout);
            }
        }
    }

    bool expect_status_disabled = ctx->status_reporting_disabled && is_status_command;
    occp_error_code_t prev_expected_code = ctx->exp_response_code;
    if (expect_status_disabled) {
        ctx->exp_response_code = OCCP_UNSUPPORTED_STATUS;
    }

    occp_resp_header_t resp_hdr;
    int retval = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    if (expect_status_disabled) {
        ctx->exp_response_code = prev_expected_code;
    }
    if (retval != OCCP_ERROR_NONE) {
        return retval;
    }
    if (ctx->exp_timeout) {
        return OCCP_SUCCESS;
    }

    if (expect_status_disabled) {
        if (statusBuff != NULL) {
            *statusBuff = 0;
        }
        return OCCP_SUCCESS;
    }

    if (!resp_hdr.error) {
        if (cmd == OCCP_GET_VERSION || cmd == OCCP_GET_VERSION_BOOT) {
            /* Version response is 4 bytes */
            uint8_t body_buf[16] = {0};
            uint16_t body_len = 0;
            int rc =
                read_body_and_verify_crc(ctx, i3c_addr, resp_hdr.body_crc_present, resp_hdr.length,
                                         body_buf, sizeof(body_buf), &body_len);
            if (rc != OCCP_SUCCESS) return rc;
            if (body_len != 4) return OCCP_ERR;
            memcpy(statusBuff, body_buf, 4);
            return OCCP_SUCCESS;
        } else {
            /* GET_STATUS: 4 bytes BE */
            uint8_t body_buf[16] = {0};
            uint16_t body_len = 0;
            int rc =
                read_body_and_verify_crc(ctx, i3c_addr, resp_hdr.body_crc_present, resp_hdr.length,
                                         body_buf, sizeof(body_buf), &body_len);
            if (rc != OCCP_SUCCESS) return rc;
            if (body_len != 4) return OCCP_ERR;
            memcpy(statusBuff, body_buf, 4);
            return OCCP_SUCCESS;
        }
    }
}

int occp_send_get_version_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *version) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_VERSION, version);
}

int occp_send_get_version_boot_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *version) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_VERSION_BOOT, version);
}

int occp_send_get_status_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status) {
    bool status_disabled = ctx->status_reporting_disabled;
    if (status_disabled && status != NULL) {
        *status = 0;
    }

    // GET_STATUS packs the four GET_OCCP_* sub-status results into one word.
    uint32_t boot_status = 0;
    uint32_t interface_status = 0;
    uint32_t command_count = 0;
    uint32_t error_code = 0;
    int retval =
        occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_BOOT_STATUS, &boot_status);
    if (retval != OCCP_SUCCESS) {
        return retval;
    }
    if (!status_disabled) {
        increment_cmd_count(ctx);
    }
    retval = occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_INTERFACE_STATUS,
                                           &interface_status);
    if (retval != OCCP_SUCCESS) {
        return retval;
    }
    if (!status_disabled) {
        increment_cmd_count(ctx);
    }
    retval = occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_ERROR_CODE, &error_code);
    if (retval != OCCP_SUCCESS) {
        return retval;
    }
    if (!status_disabled) {
        increment_cmd_count(ctx);
    }
    // Read the command count last so it includes the three status commands above.
    retval =
        occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_COMMAND_COUNT, &command_count);
    if (retval != OCCP_SUCCESS) {
        return retval;
    }
    if (status_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; GET_STATUS family commands returned expected "
                "errors\n");
        return OCCP_SUCCESS;
    }

    *status = ((boot_status & 0xf)) | ((interface_status & 0xf) << 4) |
              ((command_count & 0xff) << 8) | ((error_code & 0xff) << 16);
    return retval;
}

static sep_ring_buffer_model_t sep_ring_buffer_model_ctx = {0};
static bool sep_ring_buffer_model_initialized = false;

static sep_ring_buffer_model_t *get_sep_ring_buffer_model(void) {
    if (!sep_ring_buffer_model_initialized) {
        sep_ring_buffer_model_init(&sep_ring_buffer_model_ctx);
        sep_ring_buffer_model_initialized = true;
    }

    return &sep_ring_buffer_model_ctx;
}

static bool occp_should_validate_sep_ring_buffer(const test_context_t *ctx) {
    if (ctx == NULL) {
        return true;
    }

    if (ctx->exp_timeout) {
        return false;
    }

    if (ctx->exp_response_code != OCCP_ERROR_NONE) {
        return false;
    }

    if (ctx->header_crc_err_inject_mode != OCCP_CRC_INJECT_NONE) {
        return false;
    }

    if (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE) {
        return false;
    }

    if (ctx->invalid_header_inject_mode != OCCP_INVALID_HDR_INJECT_NONE) {
        return false;
    }

    if (ctx->invalid_len_err_inject_enable || ctx->inject_undersize_header_err ||
        ctx->inject_undersize_body_err || ctx->inject_oversize_body_err ||
        ctx->invalid_message_length_zero_inject_enable) {
        return false;
    }

    if (ctx->unsupported_status_id_inject_enable) {
        return false;
    }

    if (ctx->status_reporting_disabled) {
        return false;
    }

    return true;
}

int occp_send_get_sep_status_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status) {
    sep_ring_buffer_model_t *model = get_sep_ring_buffer_model();
    bool validate = occp_should_validate_sep_ring_buffer(ctx);
    bool expect_empty;
    uint32_t expected_value = 0;

    sep_ring_buffer_guard_set();

    expect_empty = sep_ring_buffer_model_empty(model);
    if (validate && !expect_empty) {
        expected_value = sep_ring_buffer_model_peek(model);
    }

    int result = occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_SEP_STATUS, status);

    sep_ring_buffer_guard_clear();

    if (result != OCCP_SUCCESS) {
        return result;
    }

    if (!validate) {
        return OCCP_SUCCESS;
    }

    if (expect_empty) {
        if (*status != 0) {
            simputs("SEP ring buffer guard: expected empty entry but received data\n");
            simputshex32("  Unexpected value: 0x", *status);
            return OCCP_ERR;
        }
        return OCCP_SUCCESS;
    }

    if (*status != expected_value) {
        simputs("SEP ring buffer mismatch detected\n");
        simputshex32("  Expected: 0x", expected_value);
        simputshex32("  Actual:   0x", *status);
        return OCCP_ERR;
    } else {
        simputs("SEP ring buffer match\n");
    }

    sep_ring_buffer_model_pop(model);
    return OCCP_SUCCESS;
}

int occp_send_get_smc_status_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_SMC_STATUS, status);
}

int occp_send_get_occp_boot_status_command(test_context_t *ctx, uint64_t i3c_addr,
                                           uint32_t *status) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_BOOT_STATUS, status);
}

int occp_send_get_occp_interface_status_command(test_context_t *ctx, uint64_t i3c_addr,
                                                uint32_t *status) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_INTERFACE_STATUS, status);
}

int occp_send_get_occp_command_count_command(test_context_t *ctx, uint64_t i3c_addr,
                                             uint32_t *status) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_COMMAND_COUNT, status);
}

int occp_send_get_occp_error_code_command(test_context_t *ctx, uint64_t i3c_addr,
                                          uint32_t *status) {
    return occp_send_generic_get_command(ctx, i3c_addr, OCCP_GET_OCCP_ERROR_CODE, status);
}

int occp_send_jump_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr) {
    occp_exec_header_t exec_hdr;
    bool has_body_crc = (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE)
                            ? true
                            : ((get_random_int() % 2) == 0);
    uint16_t body_len = (uint16_t)(sizeof(occp_exec_header_t) - sizeof(occp_req_header_t));

    uint16_t injected_len = body_len;
    bool inject_len_err = ctx->invalid_len_err_inject_enable;
    if (inject_len_err) {
        uint16_t lower;
        if (body_len > 1) {
            uint16_t max_lower = (uint16_t)(body_len - 1);
            lower = (uint16_t)(1 + (get_random_int() % max_lower));
        } else {
            lower = 1;
        }
        uint16_t upper_min = (uint16_t)(body_len + 1);
        uint16_t upper_max = 0x100;
        uint16_t upper =
            (upper_min <= upper_max)
                ? (uint16_t)(upper_min + (get_random_int() % (upper_max - upper_min + 1)))
                : upper_max;
        const uint16_t candidates[3] = {0, lower, upper};
        injected_len = candidates[get_random_int() % 3];
        simputshex16("OCCP: Random invalid JUMP length: ", injected_len);
    }

    exec_hdr.header = occp_encode_header_word(OCCP_JUMP, body_len, has_body_crc);
    exec_hdr.start_addr = addr;
    exec_hdr.cpu_id = 0;
    exec_hdr.reserved = 0;
    exec_hdr.addr_attr = 0;

    if (ctx->inject_undersize_header_err) {
        return send_undersize_header_only(ctx, i3c_addr, (const uint8_t *)&exec_hdr,
                                          sizeof(exec_hdr.header));
    }

    /* Override the length field after encoding */
    if (inject_len_err) {
        exec_hdr.header.header_word.length = injected_len & 0x7FF;
        /* Recalculate header CRC with the new length */
        exec_hdr.header.header_crc =
            calculate_crc8(((uint8_t *)&exec_hdr.header) + 1, sizeof(exec_hdr.header) - 1);
        /* Do not force body CRC presence based on length; honor header flag */
        exec_hdr.header.header_crc =
            calculate_crc8(((uint8_t *)&exec_hdr.header) + 1, sizeof(exec_hdr.header) - 1);
        body_len = injected_len;
    }

    uint8_t *tx_buf = occp_tx_buf;
    int crc_size = 0;
    size_t tx_len;
    size_t header_size = sizeof(exec_hdr.header);
    size_t available_body = sizeof(exec_hdr) - header_size;
    size_t copy_len = (body_len <= available_body) ? body_len : available_body;

    memcpy(tx_buf, &exec_hdr.header, header_size);

    /* Build body (truncate to available bytes) */
    if (copy_len > 0) {
        const uint8_t *body_ptr = ((const uint8_t *)&exec_hdr) + header_size;
        memcpy(tx_buf + header_size, body_ptr, copy_len);
    }
    /* Pad with random data if injected length exceeds struct body */
    if (body_len > copy_len) {
        size_t pad_len = (size_t)body_len - copy_len;
        uint8_t *pad_ptr = tx_buf + header_size + copy_len;
        for (size_t i = 0; i < pad_len; i++) {
            pad_ptr[i] = (uint8_t)(get_random_int() & 0xFF);
        }
    }

    if (has_body_crc && body_len > 0) {
        const uint8_t *body_start = tx_buf + header_size;
        if (body_len > 14) {
            uint32_t crc = calculate_crc32((uint8_t *)body_start, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 32 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
            crc_size = 4;
        } else {
            uint8_t crc = calculate_crc8((uint8_t *)body_start, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 8 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
            crc_size = 1;
        }
    }

    inject_header_errors_if_enabled(ctx, tx_buf, header_size);
    if (has_body_crc && body_len > 0) {
        bool use_crc32 = (crc_size == 4);
        inject_body_errors_if_enabled(ctx, tx_buf + header_size, body_len, use_crc32);
    }

    if (ctx->inject_undersize_body_err && body_len > 0) {
        uint16_t short_len = get_random_int() % (body_len + crc_size);
        tx_len = header_size + short_len;
    } else {
        tx_len = header_size + body_len + crc_size;
    }

    /* Oversize body injection: append 1..OCCP_OVERSIZE_PAD_MAX random bytes. */
    if (ctx->inject_oversize_body_err) {
        uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
        for (uint16_t i = 0; i < extra_len; i++) {
            tx_buf[tx_len + i] = (uint8_t)(get_random_int() & 0xFF);
        }
        tx_len += extra_len;
    }
    if (ctx->type == DRIVER_TYPE_I3C) {
        ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf, tx_len);
    } else {
        ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf, tx_len, ctx->timeout);
    }

    occp_resp_header_t resp_hdr;
    int retval = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    if (retval != OCCP_ERROR_NONE) {
        return retval;
    }
    return OCCP_SUCCESS;
}

int occp_send_validate_boot_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr) {

    occp_exec_header_t exec_hdr;
    bool has_body_crc = (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE)
                            ? true
                            : ((get_random_int() % 2) == 0);
    uint16_t body_len = (uint16_t)(sizeof(occp_exec_header_t) - sizeof(occp_req_header_t));

    uint16_t injected_len = body_len;
    bool inject_len_err = ctx->invalid_len_err_inject_enable;
    if (inject_len_err) {
        uint16_t lower;
        if (body_len > 1) {
            uint16_t max_lower = (uint16_t)(body_len - 1);
            lower = (uint16_t)(1 + (get_random_int() % max_lower));
        } else {
            lower = 1;
        }
        uint16_t upper_min = (uint16_t)(body_len + 1);
        uint16_t upper_max = 0x100;
        uint16_t upper =
            (upper_min <= upper_max)
                ? (uint16_t)(upper_min + (get_random_int() % (upper_max - upper_min + 1)))
                : upper_max;
        const uint16_t candidates[3] = {0, lower, upper};
        injected_len = candidates[get_random_int() % 3];
        simputshex16("OCCP: Random invalid VALIDATE_BOOT length: ", injected_len);
    }

    exec_hdr.header = occp_encode_header_word(OCCP_VALIDATE_BOOT, body_len, has_body_crc);
    exec_hdr.start_addr = addr;
    exec_hdr.cpu_id = 0;
    exec_hdr.reserved = 0;
    exec_hdr.addr_attr = 0;

    if (ctx->inject_undersize_header_err) {
        return send_undersize_header_only(ctx, i3c_addr, (const uint8_t *)&exec_hdr,
                                          sizeof(exec_hdr.header));
    }

    /* Override the length field after encoding */
    if (inject_len_err) {
        exec_hdr.header.header_word.length = injected_len & 0x7FF;
        /* Recalculate header CRC with the new length */
        exec_hdr.header.header_crc =
            calculate_crc8(((uint8_t *)&exec_hdr.header) + 1, sizeof(exec_hdr.header) - 1);
        /* Do not force body CRC presence based on length; honor header flag */
        exec_hdr.header.header_crc =
            calculate_crc8(((uint8_t *)&exec_hdr.header) + 1, sizeof(exec_hdr.header) - 1);
        body_len = injected_len;
    }

    uint8_t *tx_buf = occp_tx_buf;
    int crc_size = 0;
    size_t tx_len;
    size_t header_size = sizeof(exec_hdr.header);
    size_t available_body = sizeof(exec_hdr) - header_size;
    size_t copy_len = (body_len <= available_body) ? body_len : available_body;

    memcpy(tx_buf, &exec_hdr.header, header_size);

    /* Build body (truncate to available bytes) */
    if (copy_len > 0) {
        const uint8_t *body_ptr = ((const uint8_t *)&exec_hdr) + header_size;
        memcpy(tx_buf + header_size, body_ptr, copy_len);
    }
    /* Pad with random data if injected length exceeds struct body */
    if (body_len > copy_len) {
        size_t pad_len = (size_t)body_len - copy_len;
        uint8_t *pad_ptr = tx_buf + header_size + copy_len;
        for (size_t i = 0; i < pad_len; i++) {
            pad_ptr[i] = (uint8_t)(get_random_int() & 0xFF);
        }
    }

    if (has_body_crc && body_len > 0) {
        const uint8_t *body_start = tx_buf + header_size;
        if (body_len > 14) {
            uint32_t crc = calculate_crc32((uint8_t *)body_start, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 32 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
            crc_size = 4;
        } else {
            uint8_t crc = calculate_crc8((uint8_t *)body_start, body_len);
            if (ctx->body_crc_err_inject_mode == OCCP_CORRUPT_CRC) {
                flip_n_random_bits((uint8_t *)&crc, sizeof(crc), (get_random_int() % 8 + 1));
                simputs("OCCP: Corrupted body CRC\n");
            }
            memcpy(tx_buf + header_size + body_len, &crc, sizeof(crc));
            crc_size = 1;
        }
    }

    inject_header_errors_if_enabled(ctx, tx_buf, header_size);
    if (has_body_crc && body_len > 0) {
        bool use_crc32 = (crc_size == 4);
        inject_body_errors_if_enabled(ctx, tx_buf + header_size, body_len, use_crc32);
    }

    /* Undersize body injection: truncate the frame inside the body or CRC. */
    if (ctx->inject_undersize_body_err && body_len > 0) {
        uint16_t short_len = get_random_int() % (body_len + crc_size);
        tx_len = header_size + short_len;
    } else {
        tx_len = header_size + body_len + crc_size;
    }

    /* Oversize body injection: append 1..OCCP_OVERSIZE_PAD_MAX random bytes. */
    if (ctx->inject_oversize_body_err) {
        uint16_t extra_len = (uint16_t)(1 + (get_random_int() % OCCP_OVERSIZE_PAD_MAX));
        for (uint16_t i = 0; i < extra_len; i++) {
            tx_buf[tx_len + i] = (uint8_t)(get_random_int() & 0xFF);
        }
        tx_len += extra_len;
    }

    if (ctx->type == DRIVER_TYPE_I3C) {
        ctx->drv.i3c_drv->send_payload_stream(ctx->drv.i3c_drv, i3c_addr, tx_buf, tx_len);
    } else {
        ctx->drv.i2c_drv->ctrlr_send_data_w_timeout(ctx->drv.i2c_drv, tx_buf, tx_len, ctx->timeout);
    }

    occp_resp_header_t resp_hdr;
    int retval = occp_get_response_header(ctx, i3c_addr, &resp_hdr);
    if (retval != OCCP_ERROR_NONE) {
        return retval;
    }
    return OCCP_SUCCESS;
}

void increment_cmd_count(test_context_t *ctx) {
    ctx->cmd_count++;
    ctx->cmd_count %= 256;
}

void check_occp_status_data(test_context_t *ctx, uint32_t status_data, int exp_interface_status,
                            int exp_boot_status) {
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping OCCP status verification\n");
        return;
    }

    /* simputs instead of snprintf keeps printf out of the ROM image. */
    uint16_t actual_error = (status_data >> 16) & 0xFF;
    int has_error = 0;
    simputshex32("Status Data: ", status_data);
    uint8_t actual_cmd_count = (status_data >> 8) & 0xFF;
    if (actual_cmd_count != ctx->cmd_count) {
        simputs("GET_STATUS: FAIL - Command count mismatch ");
        simputshex16("exp=0x", (uint16_t)ctx->cmd_count);
        simputshex16(" got=0x", (uint16_t)actual_cmd_count);
        simputs("\n");
        ctx->overall_result = false;
        has_error = 1;
    }
    uint8_t actual_interface_status = (status_data >> 4) & 0xF;
    if (actual_interface_status != exp_interface_status) {
        simputs("GET_STATUS: FAIL - Interface status mismatch ");
        simputshex16("exp=0x", (uint16_t)exp_interface_status);
        simputshex16(" got=0x", (uint16_t)actual_interface_status);
        simputs("\n");
        ctx->overall_result = false;
        has_error = 1;
    }
    uint8_t actual_boot_status = (status_data)&0xF;
    if (has_error == 0) {
        simputs("GET_STATUS: PASS\n");
    }
}

uint16_t get_random_occp_write_size(void) {
    uint32_t p = get_random_int() % 100;
    if (p < 10) { // 10% chance
        return 1;
    } else if (p < 80) { // 70% chance
        // Range: 2 to 32
        return (get_random_int() % 31) + 2;
    } else if (p < 95) { // 15% chance
        // Range: 33 to 255
        return (get_random_int() % (256 - 1 - 33 + 1)) + 33;
    } else if (p < 98) { // 3% chance
        // Range: 256 to 2033
        return (get_random_int() % (2034 - 1 - 256 + 1)) + 256;
    } else { // 2% chance
        return MAX_OCCP_WRITE_SIZE;
    }
}

uint16_t get_random_occp_read_size(void) {
    uint32_t p = get_random_int() % 100;
    if (p < 10) { // 10% chance
        return 1;
    } else if (p < 80) { // 70% chance
        // Range: 2 to 32
        return (get_random_int() % 31) + 2;
    } else if (p < 95) { // 15% chance
        // Range: 33 to 255
        return (get_random_int() % (256 - 1 - 33 + 1)) + 33;
    } else if (p < 98) { // 3% chance
        // Range: 256 to 2045
        return (get_random_int() % (2046 - 1 - 256 + 1)) + 256;
    } else { // 2% chance
        return MAX_OCCP_READ_SIZE;
    }
}

void send_random_occp_write(test_context_t *ctx, uint64_t addr_range) {
    uint16_t len = get_random_occp_write_size();
    // 4-byte-aligned addresses only
    uint64_t random_addr =
        ctx->test_base_addr + (get_random_int() % (addr_range - len + 1)) & 0xfffffffffffffffc;
    static uint8_t write_data[MAX_OCCP_WRITE_SIZE];
    for (int j = 0; j < len; j++) {
        write_data[j] = get_random_int() & 0xFF;
    }
    simputs("Writing ");
    simputshex16("", len);
    simputs(" bytes to address 0x");
    simputshex32("", random_addr);
    simputs("\n");

    int retval = occp_send_write_command(ctx, ctx->slave_addr, random_addr, write_data, len);
    if (retval == OCCP_SUCCESS) {
        simputs("WRITE command succeeded\n");
        bool store_in_scoreboard = (ctx->sram_scoreboard_idx < MAX_WRITES) &&
                                   (ctx->header_crc_err_inject_mode == OCCP_CRC_INJECT_NONE) &&
                                   (ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_NONE) &&
                                   (ctx->inject_undersize_header_err == false) &&
                                   (ctx->inject_undersize_body_err == false) &&
                                   (ctx->inject_oversize_body_err == false);
        if (store_in_scoreboard) {
            ctx->sram_scoreboard[ctx->sram_scoreboard_idx].address = random_addr;
            ctx->sram_scoreboard[ctx->sram_scoreboard_idx].len = len;
            memcpy(ctx->sram_scoreboard[ctx->sram_scoreboard_idx].data, write_data, len);
            ctx->sram_scoreboard_idx++;
        }
    } else {
        if (ctx->invalid_len_err_inject_enable) {
            simputs("WRITE command errored under length injection (expected)\n");
        } else {
            simputs("WRITE command failed\n");
            ctx->overall_result = false;
        }
    }
}

void send_random_occp_read(test_context_t *ctx, uint64_t addr_range) {
    bool read_from_scoreboard = (ctx->sram_scoreboard_idx > 0) && ((get_random_int() % 2) == 0);
    int retval;

    if (read_from_scoreboard) {
        int entry_idx = get_random_int() % ctx->sram_scoreboard_idx;
        scoreboard_entry_t *entry = &ctx->sram_scoreboard[entry_idx];

        // Pick a 4-byte-aligned offset and a length inside the entry.
        uint8_t read_offset =
            (entry->len > 1) ? ((get_random_int() % (entry->len - 1)) & 0xfffffffffffffffc) : 0;
        uint8_t max_read_len = entry->len - read_offset;
        uint8_t read_len = (max_read_len > 1) ? ((get_random_int() % (max_read_len - 1)) + 1) : 1;

        uint64_t read_addr = entry->address + read_offset;
        static uint8_t recv_data[MAX_OCCP_READ_SIZE] = {0};

        simputs("Scoreboard READ: len=");
        simputshex16("", read_len);
        simputs(" addr=0x");
        simputshex32("", read_addr);
        simputs(" offset=");
        simputshex16("", read_offset);
        simputs("\n");

        retval = occp_send_read_command(ctx, ctx->slave_addr, read_addr, recv_data, read_len);

        if (retval == OCCP_SUCCESS) {
            if (ctx->exp_timeout) {
                simputs("Scoreboard READ command timed out as expected\n");
                return;
            }

            bool check_scoreboard_data =
                (ctx->header_crc_err_inject_mode == OCCP_CRC_INJECT_NONE) &&
                (ctx->body_crc_err_inject_mode == OCCP_CRC_INJECT_NONE) &&
                (ctx->inject_undersize_header_err == false) &&
                (ctx->inject_undersize_body_err == false) &&
                (ctx->inject_oversize_body_err == false) &&
                (ctx->invalid_len_err_inject_enable == false);
            if (check_scoreboard_data) {
                if (memcmp(recv_data, entry->data + read_offset, read_len) == 0) {
                    simputs("Scoreboard READ data verification PASSED.\n");
                } else {
                    simputs("Scoreboard READ data verification FAILED.\n");
                    simputs("Expected: ");
                    for (int i = 0; i < read_len; i++) {
                        simputshex16("0x", entry->data[read_offset + i]);
                    }
                    simputs("\nActual: ");
                    for (int i = 0; i < read_len; i++) {
                        simputshex16("0x", recv_data[i]);
                    }
                    ctx->overall_result = false;
                }
            } else {
                simputs("Scoreboard READ data verification skipped due to body CRC injection.\n");
            }
        } else {
            if (ctx->invalid_len_err_inject_enable) {
                simputs("Scoreboard READ command errored under length injection (expected).\n");
            } else {
                simputs("Scoreboard READ command failed.\n");
                ctx->overall_result = false;
            }
        }
    } else {
        // Perform a read from a random address (no verification possible)
        uint16_t len = get_random_occp_read_size();
        uint64_t random_addr =
            ctx->test_base_addr + (get_random_int() % (addr_range - len + 1)) & 0xfffffffffffffffc;
        static uint8_t recv_data[MAX_OCCP_READ_SIZE];
        simputs("Random READ: len=");
        simputshex16("", len);
        simputs(" addr=0x");
        simputshex32("", random_addr);
        simputs("\n");

        retval = occp_send_read_command(ctx, ctx->slave_addr, random_addr, recv_data, len);
        if (retval == OCCP_SUCCESS) {
            simputs("Random READ command succeeded\n");
        } else {
            if (ctx->invalid_len_err_inject_enable) {
                simputs("Random READ command errored under length injection (expected)\n");
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("Random READ command errored under length injection (expected)\n");
                } else {
                    simputs("Random READ command failed\n");
                    ctx->overall_result = false;
                }
            }
        }
    }
}

void execute_random_commands(test_context_t *ctx, int num_commands) {

    uint64_t addr_range = ctx->test_upper_addr_bound - ctx->test_base_addr;
    int exp_interface_status = 0x1;
    int exp_boot_status = 0x5;
    int exp_occp_version_major = 1;
    int exp_occp_version_minor = 0;
    int exp_occp_version_patch = 0;
    int exp_occp_version =
        exp_occp_version_major | exp_occp_version_minor << 8 | exp_occp_version_patch << 16;

    for (int i = 0; i < num_commands; i++) {
        if (ctx->invalid_header_inject_mode != OCCP_INVALID_HDR_INJECT_NONE) {
            int rc_invalid = occp_send_invalid_header_command(ctx, ctx->slave_addr);
            if (rc_invalid != OCCP_SUCCESS) {
                simputs("Invalid header send failed\n");
                ctx->overall_result = false;
            }
            increment_cmd_count(ctx);
            continue;
        }
        // 30% status commands, 70% reads and writes.
        uint8_t is_status_cmd = get_random_int() % 10 < 3 ? 1 : 0;
        int retval;
        uint32_t status_data = 0;
        bool error_inject_enb = (ctx->exp_response_code != OCCP_ERROR_NONE) ||
                                (ctx->invalid_len_err_inject_enable) ||
                                (ctx->header_crc_err_inject_mode != OCCP_CRC_INJECT_NONE) ||
                                (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE) ||
                                (ctx->inject_undersize_header_err) ||
                                (ctx->inject_undersize_body_err) || (ctx->inject_oversize_body_err);

        occp_command_t command_selected = (is_status_cmd)
                                              ? (get_random_int() % 8)
                                              : ((get_random_int() % 2) ? OCCP_READ : OCCP_WRITE);

        // With status reporting disabled, 6% of picks are GET_VERSION* and 24% are rejected
        // status IDs.
        if (ctx->status_reporting_disabled && is_status_cmd)
            command_selected = ((get_random_int() % 10) < 2) ? (get_random_int() % 2)
                                                             : ((get_random_int() % 6) + 2);

        // Version commands have no body to corrupt or truncate.
        if (((ctx->inject_undersize_body_err) ||
             (ctx->body_crc_err_inject_mode != OCCP_CRC_INJECT_NONE)) &&
            is_status_cmd) {
            command_selected = get_random_int() % 6 + 2;
        }

        if (command_selected == OCCP_GET_VERSION || command_selected == OCCP_GET_VERSION_BOOT) {
            int version;
            if (command_selected == OCCP_GET_VERSION) {
                retval = occp_send_get_version_command(ctx, ctx->slave_addr, &version);
            } else {
                retval = occp_send_get_version_boot_command(ctx, ctx->slave_addr, &version);
            }
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_VERSION command timed out as expected\n");
                    return;
                }
                if (!error_inject_enb) {
                    simputshex32("OCCP Version: ", version);
                    if (version != exp_occp_version) {
                        simputs("OCCP Version mismatch\n");
                        simputshex32("Expected: ", exp_occp_version);
                        simputshex32("Actual: ", version);
                        ctx->overall_result = false;
                    }
                }
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_VERSION command errored under length injection (expected)\n");
                } else {
                    simputs("GET_VERSION command failed\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_STATUS) {
            retval = occp_send_get_status_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_STATUS command timed out as expected\n");
                    return;
                }
                if (!error_inject_enb && !ctx->status_reporting_disabled)
                    check_occp_status_data(ctx, status_data, exp_interface_status, exp_boot_status);
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_STATUS errored under length injection (expected)\n");
                } else {
                    simputs("GET_STATUS: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_SEP_STATUS) {
            retval = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_SEP_STATUS command timed out as expected\n");
                    return;
                }
                if (ctx->status_reporting_disabled) {
                    simputs("GET_SEP_STATUS: STATUS_RPT_DISABLE strap active (expected error "
                            "response)\n");
                } else {
                    simputshex32("SEP Status: ", status_data);
                    simputs("GET_SEP_STATUS: PASS\n");
                }
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_SEP_STATUS errored under length injection (expected)\n");
                } else {
                    simputs("GET_SEP_STATUS: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_SMC_STATUS) {
            retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_SMC_STATUS command timed out as expected\n");
                    return;
                }
                if (ctx->status_reporting_disabled) {
                    simputs("GET_SMC_STATUS: STATUS_RPT_DISABLE strap active (expected error "
                            "response)\n");
                } else {
                    simputshex32("SMC Status: ", status_data);
                    simputs("GET_SMC_STATUS: PASS\n");
                }
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_SMC_STATUS errored under length injection (expected)\n");
                } else {
                    simputs("GET_SMC_STATUS: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_OCCP_BOOT_STATUS) {
            retval = occp_send_get_occp_boot_status_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_OCCP_BOOT_STATUS command timed out as expected\n");
                    return;
                }
                // TODO: what is this expected to be?
                simputs("GET_OCCP_BOOT_STATUS: PASS\n");
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_OCCP_BOOT_STATUS errored under length injection (expected)\n");
                } else {
                    simputs("GET_OCCP_BOOT_STATUS: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_OCCP_COMMAND_COUNT) {
            retval = occp_send_get_occp_command_count_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_OCCP_COMMAND_COUNT command timed out as expected\n");
                    return;
                }
                if (!error_inject_enb && !ctx->status_reporting_disabled &&
                    ((status_data & 0xFF) != ctx->cmd_count)) {
                    simputs("GET_OCCP_COMMAND_COUNT: FAIL\n");
                    simputshex32("Expected: ", ctx->cmd_count);
                    simputshex32("Actual: ", status_data);
                    ctx->overall_result = false;
                } else {
                    simputs("GET_OCCP_COMMAND_COUNT: PASS\n");
                }
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_OCCP_COMMAND_COUNT errored under length injection (expected)\n");
                } else {
                    simputs("GET_OCCP_COMMAND_COUNT: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_OCCP_INTERFACE_STATUS) {
            bool error_inject_enb = (ctx->exp_response_code != OCCP_ERROR_NONE);
            retval =
                occp_send_get_occp_interface_status_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_OCCP_INTERFACE_STATUS command timed out as expected\n");
                    return;
                }
                simputs("GET_OCCP_INTERFACE_STATUS: PASS\n");
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs(
                        "GET_OCCP_INTERFACE_STATUS errored under length injection (expected)\n");
                } else {
                    simputs("GET_OCCP_INTERFACE_STATUS: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_GET_OCCP_ERROR_CODE) {
            bool error_inject_enb = (ctx->exp_response_code != OCCP_ERROR_NONE);
            retval = occp_send_get_occp_error_code_command(ctx, ctx->slave_addr, &status_data);
            if (retval == OCCP_SUCCESS) {
                if (ctx->exp_timeout) {
                    simputs("GET_OCCP_ERROR_CODE command timed out as expected\n");
                    return;
                }
                simputs("GET_OCCP_ERROR_CODE: PASS\n");
            } else {
                if (ctx->invalid_len_err_inject_enable) {
                    simputs("GET_OCCP_ERROR_CODE errored under length injection (expected)\n");
                } else {
                    simputs("GET_OCCP_ERROR_CODE: FAIL\n");
                    ctx->overall_result = false;
                }
            }
        } else if (command_selected == OCCP_READ) {
            send_random_occp_read(ctx, addr_range);
        } else if (command_selected == OCCP_WRITE) {
            send_random_occp_write(ctx, addr_range);
        }
        if (!ctx->inject_undersize_header_err) increment_cmd_count(ctx);
    }
}

void send_max_size_occp_write(test_context_t *ctx, uint64_t addr_range) {
    uint16_t len = MAX_OCCP_WRITE_SIZE;
    // Ensure the write does not go out of the specified memory range
    uint64_t random_addr =
        ctx->test_base_addr + (get_random_int() % (addr_range - len + 1)) & 0xfffffffffffffffc;
    static uint8_t write_data[MAX_OCCP_WRITE_SIZE];
    for (int j = 0; j < len; j++) {
        write_data[j] = get_random_int() & 0xFF;
    }
    simputs("Writing ");
    simputshex16("", len);
    simputs(" bytes to address 0x");
    simputshex32("", random_addr);
    simputs("\n");

    int retval = occp_send_write_command(ctx, ctx->slave_addr, random_addr, write_data, len);
    if (retval == OCCP_SUCCESS) {
        simputs("WRITE command succeeded\n");
        if (ctx->sram_scoreboard_idx < MAX_WRITES) {
            ctx->sram_scoreboard[ctx->sram_scoreboard_idx].address = random_addr;
            ctx->sram_scoreboard[ctx->sram_scoreboard_idx].len = len;
            memcpy(ctx->sram_scoreboard[ctx->sram_scoreboard_idx].data, write_data, len);
            ctx->sram_scoreboard_idx++;
        }
    } else {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    }
}

void send_max_size_occp_read(test_context_t *ctx, uint64_t addr_range) {
    bool read_from_scoreboard = (ctx->sram_scoreboard_idx > 0) && ((get_random_int() % 2) == 0);
    int retval;

    if (read_from_scoreboard) {
        int entry_idx = get_random_int() % ctx->sram_scoreboard_idx;
        scoreboard_entry_t *entry = &ctx->sram_scoreboard[entry_idx];

        uint16_t len = MAX_OCCP_READ_SIZE;
        // a scoreboard entry shorter than MAX_OCCP_READ_SIZE cannot serve a max-size read
        if (entry->len < len) {
            read_from_scoreboard = false;
        } else {
            uint64_t read_addr = entry->address;
            static uint8_t recv_data[MAX_OCCP_READ_SIZE] = {0};

            simputs("Scoreboard READ: len=");
            simputshex16("", len);
            simputs(" addr=0x");
            simputshex32("", read_addr);
            simputs("\n");

            retval = occp_send_read_command(ctx, ctx->slave_addr, read_addr, recv_data, len);

            if (retval == OCCP_SUCCESS) {
                if (memcmp(recv_data, entry->data, len) == 0) {
                    simputs("Scoreboard READ data verification PASSED.\n");
                } else {
                    simputs("Scoreboard READ data verification FAILED.\n");
                    simputs("Expected: ");
                    for (int i = 0; i < len; i++) {
                        simputshex16("0x", entry->data[i]);
                    }
                    simputs("\nActual: ");
                    for (int i = 0; i < len; i++) {
                        simputshex16("0x", recv_data[i]);
                    }
                    ctx->overall_result = false;
                }
            } else {
                simputs("Scoreboard READ command failed.\n");
                ctx->overall_result = false;
            }
        }
    }

    if (!read_from_scoreboard) {
        // Perform a read from a random address (no verification possible)
        uint16_t len = MAX_OCCP_READ_SIZE;
        uint64_t random_addr =
            ctx->test_base_addr + (get_random_int() % (addr_range - len + 1)) & 0xfffffffffffffffc;
        static uint8_t recv_data[MAX_OCCP_READ_SIZE];
        simputs("Random READ: len=");
        simputshex16("", len);
        simputs(" addr=0x");
        simputshex32("", random_addr);
        simputs("\n");

        retval = occp_send_read_command(ctx, ctx->slave_addr, random_addr, recv_data, len);
        if (retval == OCCP_SUCCESS) {
            simputs("Random READ command succeeded\n");
        } else {
            simputs("Random READ command failed\n");
            ctx->overall_result = false;
        }
    }
}

void execute_max_size_rw_commands(test_context_t *ctx, int num_commands) {
    uint64_t addr_range = ctx->test_upper_addr_bound - ctx->test_base_addr;
    for (int i = 0; i < num_commands; i++) {
        occp_command_t command_selected = (get_random_int() % 2 == 0) ? OCCP_READ : OCCP_WRITE;
        if (command_selected == OCCP_READ) {
            send_max_size_occp_read(ctx, addr_range);
        } else if (command_selected == OCCP_WRITE) {
            send_max_size_occp_write(ctx, addr_range);
        }
        increment_cmd_count(ctx);
    }
}

void send_min_size_occp_write(test_context_t *ctx, uint64_t addr_range) {
    uint16_t len = 1;
    // Ensure the write does not go out of the specified memory range
    uint64_t random_addr =
        ctx->test_base_addr + (get_random_int() % (addr_range - len + 1)) & 0xfffffffffffffffc;
    uint8_t write_data[1];
    for (int j = 0; j < len; j++) {
        write_data[j] = get_random_int() & 0xFF;
    }
    simputs("Writing ");
    simputshex16("", len);
    simputs(" bytes to address 0x");
    simputshex32("", random_addr);
    simputs("\n");

    int retval = occp_send_write_command(ctx, ctx->slave_addr, random_addr, write_data, len);
    if (retval == OCCP_SUCCESS) {
        simputs("WRITE command succeeded\n");
        if (ctx->sram_scoreboard_idx < MAX_WRITES) {
            ctx->sram_scoreboard[ctx->sram_scoreboard_idx].address = random_addr;
            ctx->sram_scoreboard[ctx->sram_scoreboard_idx].len = len;
            memcpy(ctx->sram_scoreboard[ctx->sram_scoreboard_idx].data, write_data, len);
            ctx->sram_scoreboard_idx++;
        }
    } else {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    }
}

void send_min_size_occp_read(test_context_t *ctx, uint64_t addr_range) {
    bool read_from_scoreboard = (ctx->sram_scoreboard_idx > 0) && ((get_random_int() % 2) == 0);
    int retval;

    if (read_from_scoreboard) {
        int entry_idx = get_random_int() % ctx->sram_scoreboard_idx;
        scoreboard_entry_t *entry = &ctx->sram_scoreboard[entry_idx];

        uint16_t len = 1;
        uint64_t read_addr = entry->address;
        uint8_t recv_data[1] = {0};

        simputs("Scoreboard READ: len=");
        simputshex16("", len);
        simputs(" addr=0x");
        simputshex32("", read_addr);
        simputs("\n");

        retval = occp_send_read_command(ctx, ctx->slave_addr, read_addr, recv_data, len);

        if (retval == OCCP_SUCCESS) {
            if (memcmp(recv_data, entry->data, len) == 0) {
                simputs("Scoreboard READ data verification PASSED.\n");
            } else {
                simputs("Scoreboard READ data verification FAILED.\n");
                simputs("Expected: ");
                for (int i = 0; i < len; i++) {
                    simputshex16("0x", entry->data[i]);
                }
                simputs("\nActual: ");
                for (int i = 0; i < len; i++) {
                    simputshex16("0x", recv_data[i]);
                }
                ctx->overall_result = false;
            }
        } else {
            simputs("Scoreboard READ command failed.\n");
            ctx->overall_result = false;
        }
    } else {
        // Perform a read from a random address (no verification possible)
        uint16_t len = 1;
        uint64_t random_addr =
            ctx->test_base_addr + (get_random_int() % (addr_range - len + 1)) & 0xfffffffffffffffc;
        uint8_t recv_data[1];
        simputs("Random READ: len=");
        simputshex16("", len);
        simputs(" addr=0x");
        simputshex32("", random_addr);
        simputs("\n");

        retval = occp_send_read_command(ctx, ctx->slave_addr, random_addr, recv_data, len);
        if (retval == OCCP_SUCCESS) {
            simputs("Random READ command succeeded\n");
        } else {
            simputs("Random READ command failed\n");
            ctx->overall_result = false;
        }
    }
}

void execute_min_size_rw_commands(test_context_t *ctx, int num_commands) {
    uint64_t addr_range = ctx->test_upper_addr_bound - ctx->test_base_addr;
    for (int i = 0; i < num_commands; i++) {
        occp_command_t command_selected = (get_random_int() % 2 == 0) ? OCCP_READ : OCCP_WRITE;
        if (command_selected == OCCP_READ) {
            send_min_size_occp_read(ctx, addr_range);
        } else if (command_selected == OCCP_WRITE) {
            send_min_size_occp_write(ctx, addr_range);
        }
        increment_cmd_count(ctx);
    }
}

/* Match a GET_*_STATUS word: [31:24] msg_type, [23:16] fw_id, [15:0] status_value. */
bool occp_status_matches_expected(uint32_t status_value, occp_fw_id_t expected_fw_id,
                                  occp_status_msg_type_t expected_msg_type,
                                  uint16_t expected_status_data, bool match_full_status_data) {
    uint8_t actual_msg_type = (uint8_t)((status_value >> 24) & 0xFF);
    uint8_t actual_fw_id = (uint8_t)((status_value >> 16) & 0xFF);
    uint16_t actual_value = (uint16_t)(status_value & 0xFFFF);

    if (actual_msg_type != (uint8_t)expected_msg_type) return false;
    if (actual_fw_id != (uint8_t)expected_fw_id) return false;

    /* Unless match_full_status_data is set, SMC BL0 error codes mask out their detail bits. */
    if (expected_fw_id == OCCP_FW_ID_SMC_BL0 && expected_msg_type == OCCP_STATUS_MSG_ERROR &&
        !match_full_status_data) {
        switch (expected_status_data) {
            uint16_t masked_expected, masked_actual;
        case OCCP_SPEC_ERROR_READ_ACCESS_DENIED:
        case OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED:
            masked_actual = (uint16_t)(actual_value & 0x1FF);
            masked_expected = (uint16_t)(expected_status_data & 0x1FF);
            return (masked_actual == masked_expected);
        case OCCP_SPEC_ERROR_CMD_FAILED:
            masked_actual = (uint16_t)(actual_value & 0xFF0);
            masked_expected = (uint16_t)(expected_status_data & 0xFF0);
            return (masked_actual == masked_expected);
        case OCCP_SPEC_ERROR_CMD_UNKNOWN:
            masked_actual = (uint16_t)(actual_value & 0xF01);
            masked_expected = (uint16_t)(expected_status_data & 0xF01);
            return (masked_actual == masked_expected);
        default:
            return (actual_value == expected_status_data);
        }
    }
    return (actual_value == expected_status_data);
}

bool occp_is_smc_error_code(uint32_t status_value) {
    uint8_t actual_msg_type = (uint8_t)((status_value >> 24) & 0xFF);
    uint8_t actual_fw_id = (uint8_t)((status_value >> 16) & 0xFF);
    uint16_t actual_value = (uint16_t)(status_value & 0xFFFF);

    return ((actual_msg_type == OCCP_STATUS_MSG_ERROR) && (actual_fw_id == OCCP_FW_ID_SMC_BL0) &&
            ((actual_value & 0xF00) != 0));
}

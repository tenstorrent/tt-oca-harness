// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP eFuse EL2 firmware MMIO test, CPU side.
//
// The EL2 CPU reads one OTP word through the eFuse read interface
// (doc/programmer/src/smc-programming.adoc, eFuse read sequence), then submits
// one RMA token on each RMA channel through the eFuse MMR
// (doc/programmer/src/sep-programming.adoc, sep-token-matching): the SiP token
// whose SHA-256 is the preloaded SiP digest, and on the chiplet channel a token
// whose SHA-256 is not the preloaded chiplet digest. Each channel is submitted
// once, and its TOKEN_MATCH is read once before its go, so the leaf can require
// that the polled result differs from the value the register held before.
//
// The firmware makes no verdict. It publishes the raw read flags, read data,
// both TOKEN_MATCH values before and after the go, the poll counts and
// TOKEN_MATCH_FAULT to the
// scratch-cold words, writes the done marker last, and returns 0. The cocotb
// leaf grades the published words against its own image and the token result
// table (hw/sys/sep/doc/token_processing.adoc). A poll that reaches its bound is
// published, not fatal.

#include <stdint.h>

#include "efuse_fw_test_common.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_scratch_drv.h"

// Scratch-cold layout and constants; the leaf sep_efuse_el2_fw_mmio_test.py
// holds the same values.
#define DONE_MARKER 0xE90500A5u
#define SCRATCH_DONE 0u
#define SCRATCH_READ_FLAGS 1u // bit 0 completed, bit 1 read_status, bit 2 req_error
#define SCRATCH_READ_DATA 2u
#define SCRATCH_SIP_MATCH 3u
#define SCRATCH_CHIP_MATCH 4u
#define SCRATCH_POLLS 5u // SiP reads in [15:0], chiplet reads in [31:16]
#define SCRATCH_FAULT 6u
// SCRATCH_SENSE: [0] 0 sense done seen, 1 bound reached; [15:8] SiP and
// [23:16] chiplet TOKEN_MATCH[7:0] read before the go.
#define SCRATCH_SENSE 7u
#define TOKEN_POLL_BOUND 4096u

#define TOKEN_WORDS SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_NUM

// Index 0 holds token[31:0] (token_processing.adoc, token submission
// registers). SiP: TOKEN_T1; chiplet: TOKEN_OTHER (cocotb/env/sep_efuse_plan.py).
static const uint32_t SIP_TOKEN[TOKEN_WORDS] = {
    0xC26B13C9u, 0x749405CFu, 0x5BFA2C0Fu, 0x1C72E4CEu,
    0xE658D4CDu, 0x81A301D4u, 0xB8D3F6E0u, 0xE8B28F4Au,
};
static const uint32_t CHIP_TOKEN[TOKEN_WORDS] = {
    0x969602D8u, 0xF89AB5E8u, 0xC776F81Bu, 0x924C457Bu,
    0x1873D45Au, 0x9939FFFBu, 0xAD42CF99u, 0x3C1C51DFu,
};

// Reads the result register once into *pre, writes the token array, writes the
// go bit, and polls the result register until it is non-zero or
// TOKEN_POLL_BOUND reads are done. Returns the last value read; *reads holds
// the number of polls.
static uint32_t token_submit(uint32_t array_base, uint32_t go_mask, uint32_t match_addr,
                             const uint32_t token[TOKEN_WORDS], uint32_t *pre, uint32_t *reads) {
    uint32_t value = 0;
    uint32_t n = 0;

    *pre = READ_REG(match_addr);
    efuse_write_8_words(array_base, token);
    WRITE_REG(SEP_TOP_EFUSE_MMR_TOKEN_EOP_BASE_ADDR, go_mask);
    while (n < TOKEN_POLL_BOUND) {
        value = READ_REG(match_addr);
        n++;
        if ((value & EFUSE_MMR__TOKEN_MATCH__TOKEN_MATCH_STATUS_bm) != 0) break;
    }
    *reads = n;
    return value;
}

int main(void) {
    efuse_fw_read_result_t rd;
    uint32_t sip_reads = 0;
    uint32_t chip_reads = 0;
    uint32_t sip_pre = 0;
    uint32_t chip_pre = 0;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP eFuse EL2 firmware MMIO test\n");
    sep_scratch_wr(SCRATCH_DONE, 0);

    // RMA results stay idle until fuse sensing completes.
    uint32_t sense = efuse_wait_sense_done() == 0 ? 0u : 1u;

    efuse_read_word_raw(EFUSE_FW_BIT0(SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR), &rd);
    // read_enable is cleared after the last word so a program can own the
    // command path.
    WRITE_REG(SEP_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR, 0);

    uint32_t sip = token_submit(
        SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0), EFUSE_MMR__TOKEN_EOP__RMA_SIP_TOKEN_GO_bm,
        SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_MATCH_BASE_ADDR, SIP_TOKEN, &sip_pre, &sip_reads);
    uint32_t chip = token_submit(SEP_TOP_EFUSE_MMR_RMA_CHIPLET_TOKEN_I_BASE_ADDR(0),
                                 EFUSE_MMR__TOKEN_EOP__RMA_CHIPLET_TOKEN_GO_bm,
                                 SEP_TOP_EFUSE_MMR_RMA_CHIPLET_TOKEN_MATCH_BASE_ADDR, CHIP_TOKEN,
                                 &chip_pre, &chip_reads);
    uint32_t fault = READ_REG(SEP_TOP_EFUSE_MMR_TOKEN_MATCH_FAULT_BASE_ADDR);

    sep_scratch_wr(SCRATCH_READ_FLAGS,
                   (rd.completed & 1u) | ((rd.read_status & 1u) << 1) | ((rd.req_error & 1u) << 2));
    sep_scratch_wr(SCRATCH_READ_DATA, rd.data_word);
    sep_scratch_wr(SCRATCH_SIP_MATCH, sip);
    sep_scratch_wr(SCRATCH_CHIP_MATCH, chip);
    sep_scratch_wr(SCRATCH_POLLS, (sip_reads & 0xFFFFu) | ((chip_reads & 0xFFFFu) << 16));
    sep_scratch_wr(SCRATCH_FAULT, fault);
    sep_scratch_wr(SCRATCH_SENSE, sense | ((sip_pre & 0xFFu) << 8) | ((chip_pre & 0xFFu) << 16));
    sep_scratch_wr(SCRATCH_DONE, DONE_MARKER);
    sep_mbx_puts("STEP published OTP read and token results\n");
    return 0;
}

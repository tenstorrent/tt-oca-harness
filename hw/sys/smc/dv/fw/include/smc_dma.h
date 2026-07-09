/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef __SMC_DMA_HEADER_DEFINED__
#define __SMC_DMA_HEADER_DEFINED__

#include <stdbool.h>
#include <stdint.h>

typedef enum { SMC_DMA_OK = 0x0, SMC_DMA_ERR = 0x1 } dma_err_e;

typedef struct {
    uint64_t decouple_aw : 1;
    uint64_t decouple_rw : 1;
    uint64_t src_reduce_len : 1;
    uint64_t dst_reduce_len : 1;
    uint64_t src_max_llen : 3;
    uint64_t dst_max_llen : 3;
    uint64_t enabled_nd : 1;
    uint64_t reserved : 53;
} dma_config_t;

typedef union {
    uint64_t val;
    dma_config_t config;
} dma_config_u;

typedef struct {
    uint64_t busy : 10;
    uint64_t reserved : 54;
} dma_status_t;

typedef struct {
    uint64_t src_addr;
    uint64_t src_stride;
    uint64_t dst_addr;
    uint64_t dst_stride;
    uint64_t length;
    uint64_t num_blocks;
    uint32_t id;
} dma_cmd_t;

void smc_dma_init();
void smc_dma_config(dma_config_u *config);
dma_err_e smc_dma_issue_cmd(dma_cmd_t *cmd);
void smc_dma_wait_idle();
bool smc_dma_is_idle();
void smc_dma_wait_cmd_done(dma_cmd_t *cmd);

#endif
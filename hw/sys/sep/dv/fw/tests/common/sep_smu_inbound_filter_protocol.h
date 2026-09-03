/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
#ifndef SEP_SMU_INBOUND_FILTER_PROTOCOL_H
#define SEP_SMU_INBOUND_FILTER_PROTOCOL_H

/*
 * smu_sep_inbound_filter_test firmware <-> cocotb contract.
 *
 * Cold scratch4 = published A_ext[31:0]
 * Cold scratch5 = written FILTER_CONFIG[31:0] (0x53113)
 * Cold scratch6 = IF024_PUBLISH / IF024_FAIL
 * Cold scratch7 = GLOBAL_BASE CSR readback
 *
 * A_ext is the pre-remap GLOBAL the inbound filter evaluates
 * (016-proven: GLOBAL_BASE + local 0x10802000 = 0x14802000).
 * The card formula GLOBAL + (0x10802000 - 0x10000000) is 0x04802000 and
 * misses the remap; do not use it.
 *
 * Keep values on the same line as #define (cocotb single-line regex).
 */
#define IF024_PUBLISH 0x024A0001u
#define IF024_FAIL 0x024FA11Eu
#define IF024_RULE_CONFIG 0x0000000000053113ULL
#define IF024_SEP_GLOBAL_BASE 0x04000000u
#define IF024_SEP_REGION_SIZE 0x11000000u
#define IF024_LOCAL_SCRATCH 0x10802000u
#define IF024_A_EXT 0x14802000u
#define IF024_SRC_ID 5u
#define IF024_ALLOW_NS 1u

#endif /* SEP_SMU_INBOUND_FILTER_PROTOCOL_H */

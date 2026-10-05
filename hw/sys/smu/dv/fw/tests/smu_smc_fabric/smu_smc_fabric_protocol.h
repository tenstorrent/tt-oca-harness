/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_smc_fabric_test protocol, shared by the SMC ROM image and the cocotb
 * sequence. Plain integer #defines only: the sequence parses this file.
 *
 * Scratch words are the SMC CPU scratch registers.
 */
#ifndef SMU_SMC_FABRIC_PROTOCOL_H
#define SMU_SMC_FABRIC_PROTOCOL_H

#define SMCFAB_SCRATCH_BASE 0xC0039080
#define SMCFAB_SCRATCH_STRIDE 8
#define SMCFAB_STATUS_IDX 0
#define SMCFAB_GO_IDX 1
#define SMCFAB_HART_IDX 4

#define SMCFAB_NUM_HARTS 4
#define SMCFAB_READY 0x5A1D0001
#define SMCFAB_GO 0x60F00001
#define SMCFAB_TEST_PASS 0xACAFACA1
#define SMCFAB_TEST_FAIL 0xFFFFFFFF
#define SMCFAB_HART_PASS 0x0DA00000
#define SMCFAB_HART_FAIL 0x0BAD0000

/* SEP SRAM at the global address the sequence opens the SEP aperture to, and
 * an address outside both that aperture and the SMC aperture at reset, which
 * leaves on ext_out. */
#define SMCFAB_SEP_TARGET 0x14002000
#define SMCFAB_EXT_TARGET 0x2A000000
#define SMCFAB_HART_STRIDE 0x40
#define SMCFAB_WORDS 4
#define SMCFAB_PATTERN 0x5EC0000000000000

#endif /* SMU_SMC_FABRIC_PROTOCOL_H */

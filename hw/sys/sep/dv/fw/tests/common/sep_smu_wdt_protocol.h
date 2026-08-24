/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * SEP_SMU_005  smu_sep_wdt_reset_to_smc_test  --  shared protocol contract.
 *
 * Included by SEP firmware and parsed by the cocotb checker. Plain integer/hex
 * #defines only. Thresholds match the VPLAN card (bark 0x200, bite 0x400).
 * SMC image is the existing smu_sep_boot shim (cookie/entry drift-checked).
 */
#ifndef SEP_SMU_WDT_PROTOCOL_H
#define SEP_SMU_WDT_PROTOCOL_H

#define WDT005_SMC_IMAGE_FIRST_WORD 0x41014081
#define WDT005_SMC_ENTRY 0x00000000C00601B2ULL
#define WDT005_FW_POLL_LIMIT 4000000

#define WDT005_BARK_THOLD 0x200
#define WDT005_BITE_THOLD 0x400

#define WDT005_S0_FAIL 0x00520FA1
#define WDT005_NMI_ARMED 0x00520001
#define WDT005_POST_NMI_ALIVE 0x00520002
#define WDT005_BRINGUP_OK 0x00520000

#endif /* SEP_SMU_WDT_PROTOCOL_H */

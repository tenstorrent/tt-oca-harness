/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * sep_smu_lc_handoff -- SEP/SMC firmware <-> SMU testbench protocol contract.
 *
 * Producer is real SEP eFuse/LCC (no Force). Demote CSRs are W1S. This image
 * holds a PROD window, then sets DEMOTE_1 and holds a second window. It does
 * not cover DEMOTE_2, a corrupt LC_STATE or SEC_DIS.
 *
 * The PVT consumer pad is BP_PVT_CLK_OBS.
 * Fallback hw2_ovrd on the dedicated obs GPIO_CTRL is forced inactive.
 *
 * SEP cannot frontdoor-program SMC PVT (0x4040_5C00 traps on the SEP->SMC
 * alias). Dedicated SMC firmware programs the CSRs at 0xC040_5Cxx and
 * publishes PVT_EN on scratch2. SEP only does LCC demote + scratch tokens.
 */
#ifndef SEP_SMU_LC_HANDOFF_PROTOCOL_H
#define SEP_SMU_LC_HANDOFF_PROTOCOL_H

#define LC_HANDOFF_SMC_IMAGE_FIRST_WORD 0x41014081
#define LC_HANDOFF_SMC_ENTRY 0x00000000C00601B2ULL
#define LC_HANDOFF_FW_POLL_LIMIT 4000000
#define LC_HANDOFF_WINDOW_MCYCLE 32768

#define LC_HANDOFF_LC_PROD_ENC 0xE1u
#define LC_HANDOFF_DEMOTE_RAW 0x1u
#define LC_HANDOFF_DEMOTE_ENC 0x1u
#define LC_HANDOFF_HW2_OVRD_BIT 24u

#define LC_HANDOFF_PVT_EN_ALIAS 0x40039090u
#define LC_HANDOFF_SMC_SCRATCH2 0xC0039090u
#define LC_HANDOFF_SMC_SCRATCH3 0xC0039098u
#define LC_HANDOFF_SMC_SCRATCH9 0xC00390C8u
#define LC_HANDOFF_SMC_SCRATCH10 0xC00390D0u

#define LC_HANDOFF_PVT_PROCESS_CTRL 0xC0405C00u
#define LC_HANDOFF_PVT_CLK_OBS_CTRL 0xC0405C04u
#define LC_HANDOFF_PVT_CLK_CNT_CTRL 0xC0405C60u
#define LC_HANDOFF_PVT_REFCLK_LO 0xC0405C64u
#define LC_HANDOFF_PVT_GPIO_CTRL 0xC040581Cu
#define LC_HANDOFF_PVT_OBS_DEFAULT 0x00001500u
#define LC_HANDOFF_PVT_OBS_UPDATE (1u << 16)
#define LC_HANDOFF_PVT_OBS_ENABLE 0x1u

#define LC_HANDOFF_S0_FAIL 0x00920FA1u
/* Shadow LC_STATE was not PROD, so the demote scenario could not run.
 * Distinct from S0_FAIL: nothing malfunctioned, the image was wrong. */
#define LC_HANDOFF_NOT_PROD_FAIL 0x00920FA2u
#define LC_HANDOFF_BRINGUP_OK 0x00920000u
#define LC_HANDOFF_PVT_EN 0x00920001u
#define LC_HANDOFF_ARMED 0x00920002u
#define LC_HANDOFF_DEMOTE1 0x00920003u
#define LC_HANDOFF_DEMOTE2 0x00920004u
#define LC_HANDOFF_PASS 0x0092000Fu
#define LC_HANDOFF_SMC_FAIL 0x009CFFEEu

#endif /* SEP_SMU_LC_HANDOFF_PROTOCOL_H */

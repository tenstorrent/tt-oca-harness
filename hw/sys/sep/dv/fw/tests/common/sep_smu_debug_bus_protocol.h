/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_sep_debug_bus_test -- shared protocol contract.
 *
 * Handshake (card S3): SMC clears scratch2/3 and publishes PH_CLEARED on
 * scratch4; SEP waits for PH_CLEARED, then publishes SEP_WAIT on scratch3 and
 * parks at debug_bus_wait_for_go polling scratch2 for GO. Dedicated SMC
 * DFD-arm firmware programs DFX/DFD/CLA (bogus negative then exact marker PC)
 * and writes GO only after that setup.
 * Closure is CLA EapStatus[0] + snapshot[63:48] == (marker_low16 << 2).
 * The RTL packs trace_rv_i_address_ip[15:0] that way: LOW16 << 2, not the
 * byte-PC and not (full_pc >> 2).
 *
 * Marker/wait PCs come from sep_debug_bus_symbols.h, generated from the
 * built SEP .sym when sep_smu_debug_bus links.
 */
#ifndef SEP_SMU_DEBUG_BUS_PROTOCOL_H
#define SEP_SMU_DEBUG_BUS_PROTOCOL_H

#define DEBUG_BUS_SMC_IMAGE_FIRST_WORD 0x41014081
#define DEBUG_BUS_SMC_ENTRY 0x00000000C00601B2ULL
#define DEBUG_BUS_HANDSHAKE_POLL_LIMIT 4000000

#define DEBUG_BUS_SEP_WAIT 0x017A0001u
#define DEBUG_BUS_GO 0x01760001u
#define DEBUG_BUS_GO_SEEN 0x017A0003u
#define DEBUG_BUS_S0_FAIL 0x01720FA1u

#define DEBUG_BUS_GO_ALIAS 0x40039090u
#define DEBUG_BUS_WAIT_ALIAS 0x40039098u
#define DEBUG_BUS_PHASE_ALIAS 0x400390A0u
#define DEBUG_BUS_SMC_SCRATCH2 0xC0039090u
#define DEBUG_BUS_SMC_SCRATCH3 0xC0039098u
#define DEBUG_BUS_SMC_SCRATCH4 0xC00390A0u
#define DEBUG_BUS_SMC_SCRATCH9 0xC00390C8u
#define DEBUG_BUS_SMC_SCRATCH10 0xC00390D0u
#define DEBUG_BUS_SMC_SCRATCH11 0xC00390D8u
#define DEBUG_BUS_SMC_SCRATCH12 0xC00390E0u
#define DEBUG_BUS_SMC_SCRATCH13 0xC00390E8u
#define DEBUG_BUS_SMC_SCRATCH14 0xC00390F0u
#define DEBUG_BUS_SMC_SCRATCH15 0xC00390F8u

#define DEBUG_BUS_PH_CLEARED 0x01740000u
#define DEBUG_BUS_PH_NEG_ARMED 0x01740001u
#define DEBUG_BUS_PH_NEG_OK 0x01740002u
#define DEBUG_BUS_PH_EXACT_ARMED 0x01740003u
#define DEBUG_BUS_PH_GO 0x01740004u
#define DEBUG_BUS_PH_CLEARED_EAP 0x01740005u
#define DEBUG_BUS_SMC_PASS 0x0174000Fu
#define DEBUG_BUS_SMC_FAIL 0x017CFFEEu

#define DEBUG_BUS_DFX_DBM_ID13 0x35u
#define DEBUG_BUS_DFX_DBM_ID6 0x19u
#define DEBUG_BUS_DFD_DBM_ID1 0x0000001000000005ULL
#define DEBUG_BUS_DFD_DBM_ID2 0x0000001000000009ULL
#define DEBUG_BUS_CLA_MASK0 0xFFFF000000000000ULL
#define DEBUG_BUS_CLA_EAP0 0x0000000000820000ULL
#define DEBUG_BUS_CLA_CTRL 0x60u
#define DEBUG_BUS_CLA_CTRL_CLK 0x40u
#define DEBUG_BUS_CLA_EAP_ALWAYS 0x0000000000010000ULL
#define DEBUG_BUS_CLA_W2C (1ULL << 32)
/* DEBUG_CTRL.force_clk_en=1 so L3/L2 DBM enable_mode can latch. */
#define DEBUG_BUS_DEBUG_CTRL_FORCE 0x10u
#define DEBUG_BUS_PH_PROBE 0x01740006u

#define DEBUG_BUS_NEG_HOLD_ITERS 8000
#define DEBUG_BUS_EXACT_HOLD_ITERS 8000
#define DEBUG_BUS_QUIET_HOLD_ITERS 8000

#endif /* SEP_SMU_DEBUG_BUS_PROTOCOL_H */

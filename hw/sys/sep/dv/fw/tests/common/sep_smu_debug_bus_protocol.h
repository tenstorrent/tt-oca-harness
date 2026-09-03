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
 * Closure is CLA EapStatus[0] + snapshot[63:48] == (marker_low16 << 2)
 * (kept-log CLA lane was 0x07d8 at marker 0xc00001f6, not byte-PC 0x01f6
 * and not (full_pc>>2)=0x007d).
 *
 * DFX DBM address: card text says 0xC000F810; generated map is
 * SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX = 0xC000B810. Implementation uses the
 * generated map (same class of drift as 008 PIC source 35→39).
 *
 * Marker/wait PCs come from generated sep_debug_bus_symbols.h (parsed from
 * the selected SEP ELF/.sym before the SMC image is compiled).
 */
#ifndef SEP_SMU_DEBUG_BUS_PROTOCOL_H
#define SEP_SMU_DEBUG_BUS_PROTOCOL_H

#define DBG017_SMC_IMAGE_FIRST_WORD 0x41014081
#define DBG017_SMC_ENTRY 0x00000000C00601B2ULL
/* Cross-CPU waits: SMC bring-up, PH_CLEARED, SEP_WAIT, GO_SEEN. These cross a
 * reset and a second CPU's startup, so they need the same budget every other
 * dual-firmware protocol here uses. The previous 512 could expire before the
 * peer had run at all -- the SMC image delays 1024 iterations before it
 * publishes PH_CLEARED, which SEP was waiting 512 polls for. A tight bound
 * belongs on a same-CPU sample, not on a handshake; give one its own constant
 * if a sample ever needs it. */
#define DBG017_HANDSHAKE_POLL_LIMIT 4000000

#define DBG017_SEP_WAIT 0x017A0001u
#define DBG017_GO 0x01760001u
#define DBG017_GO_SEEN 0x017A0003u
#define DBG017_S0_FAIL 0x01720FA1u

#define DBG017_GO_ALIAS 0x40039090u
#define DBG017_WAIT_ALIAS 0x40039098u
#define DBG017_PHASE_ALIAS 0x400390A0u
#define DBG017_SMC_SCRATCH2 0xC0039090u
#define DBG017_SMC_SCRATCH3 0xC0039098u
#define DBG017_SMC_SCRATCH4 0xC00390A0u
#define DBG017_SMC_SCRATCH9 0xC00390C8u
#define DBG017_SMC_SCRATCH10 0xC00390D0u
#define DBG017_SMC_SCRATCH11 0xC00390D8u
#define DBG017_SMC_SCRATCH12 0xC00390E0u
#define DBG017_SMC_SCRATCH13 0xC00390E8u
#define DBG017_SMC_SCRATCH14 0xC00390F0u
#define DBG017_SMC_SCRATCH15 0xC00390F8u

#define DBG017_PH_CLEARED 0x01740000u
#define DBG017_PH_NEG_ARMED 0x01740001u
#define DBG017_PH_NEG_OK 0x01740002u
#define DBG017_PH_EXACT_ARMED 0x01740003u
#define DBG017_PH_GO 0x01740004u
#define DBG017_PH_CLEARED_EAP 0x01740005u
#define DBG017_SMC_PASS 0x0174000Fu
#define DBG017_SMC_FAIL 0x017CFFEEu

#define DBG017_DFX_DBM_ID13 0x35u
#define DBG017_DFX_DBM_ID6 0x19u
#define DBG017_DFD_DBM_ID1 0x0000001000000005ULL
#define DBG017_DFD_DBM_ID2 0x0000001000000009ULL
#define DBG017_CLA_MASK0 0xFFFF000000000000ULL
#define DBG017_CLA_EAP0 0x0000000000820000ULL
#define DBG017_CLA_CTRL 0x60u
#define DBG017_CLA_CTRL_CLK 0x40u
#define DBG017_CLA_EAP_ALWAYS 0x0000000000010000ULL
#define DBG017_CLA_W2C (1ULL << 32)
#define DBG017_CDFDCSR_ARM (1ULL << 63)
/* DEBUG_CTRL.force_clk_en=1 so L3/L2 DBM enable_mode can latch. */
#define DBG017_DEBUG_CTRL_FORCE 0x10u
#define DBG017_PH_PROBE 0x01740006u

#define DBG017_NEG_HOLD_ITERS 8000
#define DBG017_EXACT_HOLD_ITERS 8000
#define DBG017_QUIET_HOLD_ITERS 8000

#endif /* SEP_SMU_DEBUG_BUS_PROTOCOL_H */

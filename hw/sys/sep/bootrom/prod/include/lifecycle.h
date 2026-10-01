/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Lifecycle controller interface for OROM.
//
// Reads LC_STATE from efuse shadow register, validates against the allowed
// set, and provides helpers for secure boot enforcement and manifest
// usage constraints validation.
//
// Also owns the SBOOT_DIS chicken bit, the device's other secure-boot posture
// input, so that both halves of that posture are read and decided in one place.
//
// RTL reference: hw/sys/sep/rtl/sep_lifecycle_ctrl.sv
// Registers:
//   FEAT_CTRL  @ 0x10918000 (64-bit, read-only)
//   DEMOTE_1   @ 0x10918008 (demote[0] + lock[1])
//   DEMOTE_2   @ 0x10918010 (demote[0] + lock[1])
// Efuse:
//   LC_STATE   @ 0x1093000C (8-bit field; low 4 bits = raw LC state)
//   SBOOT_DIS  @ 0x10930010 (disable_secure_boot[0] + rsvd[31:1])

#pragma once

#include <stdbool.h>
#include <stdint.h>

// ---------------------------------------------------------------------------
// LC state raw values (4-bit, from RTL sep_lifecycle_ctrl.sv case statements)
// ---------------------------------------------------------------------------

#define LC_STATE_TEST_DEV 0x0u
#define LC_STATE_PROD 0x1u
#define LC_STATE_RMA_SIP_LO 0x2u // RMA_SiP range: 0x2..0x3 (4'b001?)
#define LC_STATE_RMA_SIP_HI 0x3u
#define LC_STATE_RMA_CHIPLET_LO 0x4u // RMA_CHIPLET range: 0x4..0x7 (4'b01??)
#define LC_STATE_RMA_CHIPLET_HI 0x7u
#define LC_STATE_PROD_END 0x8u

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

// Read LC_STATE from efuse shadow register.
// Returns the 4-bit LC state (low nibble of the 8-bit efuse field).
// Differential decode and signal integrity check are handled by RTL
// (prim_diff_decode_multi).
uint32_t lc_read_state(void);

// Check if a decoded LC state value is valid (belongs to allowed set).
bool lc_state_is_valid(uint32_t lc_state);

// Check if the given LC state enforces secure boot.
// PROD and PROD_END enforce secure boot; TEST_DEV and RMA do not.
bool lc_state_enforces_secure_boot(uint32_t lc_state);

// Check if the given LC state is an RMA state (SiP or Chiplet).
bool lc_state_is_rma(uint32_t lc_state);

// Read FEAT_CTRL from the lifecycle controller (64-bit).
// Returns the low 32 bits; *hi receives the high 32 bits.
uint32_t lc_read_feat_ctrl(uint32_t *hi);

// Write BL1 demotion decision to lifecycle controller DEMOTE_1 register.
// Sets the demote bit.  If lock is true, also sets the lock bit
// (preventing further changes).
void lc_write_demotion(bool demote, bool lock);

// Write BL2 demotion decision to lifecycle controller DEMOTE_2 register.
void lc_write_demotion_2(bool demote, bool lock);

// Full lifecycle policy: read, decode, validate, report, record in bl0_state.
// Returns the decoded LC state on success.
// Calls rom_err_fail() on invalid state (does not return).
uint32_t rom_lifecycle_policy(void);

// ---------------------------------------------------------------------------
// Secure-boot chicken bit (SBOOT_DIS)
// ---------------------------------------------------------------------------

// Full SBOOT_DIS policy ([S18]): one read of the shadow, masked to
// disable_secure_boot, validated, reported, recorded in bl0_state, and latched
// for sboot_dis_disabled().
// Calls rom_err_fail() when a reserved bit is set (does not return).
void rom_sboot_dis_policy(void);

// The chicken-bit value latched by rom_sboot_dis_policy().
//
// Every consumer of the secure-boot posture reads this rather than the shadow,
// so the policy input, bl0_state and the boot measurement agree on both which
// bit matters and when it was sampled. Reads false until [S18] runs, and false
// enforces secure boot.
bool sboot_dis_disabled(void);

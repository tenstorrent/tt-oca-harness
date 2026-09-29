/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_state.h
 * @brief Global firmware state declarations for Key Manager
 *
 * Declares all mutable global firmware state as explicit standalone symbols.
 * This avoids hidden layout dependencies between C and assembly and keeps
 * hot scalars visible to the toolchain for small-data placement.
 */

#ifndef ROM_STATE_H
#define ROM_STATE_H

#include "rom_prng.h"
#include "rom_msgbuf.h"
#include "rom_keyreg.h"

/** @brief Firmware PRNG state (BSS, zero-initialized). */
extern rom_km_prng_state_t rom_prng_state;

/** @brief Inbound message buffer (BSS, zero-initialized). */
extern rom_km_msgbuf_t rom_rx_msgbuf;

/** @brief Outbound message buffer (BSS, zero-initialized). */
extern rom_km_msgbuf_t rom_tx_msgbuf;

/** @brief Key handle registry (BSS, zero-initialized). */
extern rom_km_keyreg_t rom_keyreg_state;

/** @brief Expected next command sequence number. */
extern uint8_t rom_cmd_seq_num;

/** @brief Next response sequence number. */
extern uint8_t rom_resp_seq_num;

#endif /* ROM_STATE_H */

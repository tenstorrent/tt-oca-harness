/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_state.c
 * @brief Single definition of global Key Manager state symbols.
 *
 * Defined in one translation unit so both production (rom_main) and test
 * builds (which omit rom_main.c and supply their own main()) can link all
 * firmware modules that reference mutable state.
 */

#include "rom_state.h"

rom_km_prng_state_t rom_prng_state;
rom_km_msgbuf_t rom_rx_msgbuf;
rom_km_msgbuf_t rom_tx_msgbuf;
rom_km_keyreg_t rom_keyreg_state;
uint8_t rom_cmd_seq_num;
uint8_t rom_resp_seq_num;

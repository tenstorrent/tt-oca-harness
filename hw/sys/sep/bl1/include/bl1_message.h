/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Challenge and confirmation messages exchanged with SMC BL1 over SEP mailbox 0.

#pragma once

#include <stdint.h>

#include "bl1_result.h"

#define BL1_MSG_WORDS 3u

// The challenge message: the SEP tag, then the challenge's low and high halves.
void bl1_challenge_message(uint64_t challenge, uint32_t out[BL1_MSG_WORDS]);

// Accepts exactly the SMC tag followed by this boot's challenge, in order, compared in constant
// time. Anything else is SEP_BL1_ERR_CONFIRM_BAD.
bl1_result_t bl1_check_confirmation(const uint32_t *words, uint32_t count, uint64_t challenge);

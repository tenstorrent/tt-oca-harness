/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Status ring buffer interface.
//
// The ring buffer lives in SMC SRAM and is shared between SEP (producer)
// and SMC (consumer).  SEP writes the head pointer; SMC writes the tail.

#ifndef STATUS_RING_H__
#define STATUS_RING_H__

#include <stdint.h>

void init_status_reporting(void);
void status_ring_buffer_insert(uint32_t value);

#endif // STATUS_RING_H__

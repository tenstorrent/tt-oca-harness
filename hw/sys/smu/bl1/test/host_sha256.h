/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#pragma once

#include <stdint.h>

int host_sha256(const uint8_t *data, uint32_t len, uint8_t *digest);

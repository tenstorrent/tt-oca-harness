/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef __VIRT_CONSOLE_H__
#define __VIRT_CONSOLE_H__

#include <stdint.h>

void simputs(const char *str);
void simputhex16(uint16_t val);
void simputhex32(uint32_t val);
void simputhex64(const uint64_t val);
void simputshex16(const char *msg, uint16_t val);
void simputshex32(const char *msg, uint32_t val);
void simputshex64(const char *msg, uint64_t val);
#endif

/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Virtual Console Functions
 * Debug output that automatically becomes no-op in production builds.
 */

#ifndef VIRT_CONSOLE_H
#define VIRT_CONSOLE_H

#include <stdint.h>

/* Virtual console functions - automatically no-op in production builds */
#ifdef DEBUG
/* Debug builds: Full console functionality */
void simputs(const char *str);
void simputhex16(uint16_t val);
void simputhex32(uint32_t val);
void simputhex64(const uint64_t val);
void simputshex16(const char *msg, uint16_t val);
void simputshex32(const char *msg, uint32_t val);
void simputshex64(const char *msg, uint64_t val);
#else
/* Production builds: No-op implementations */
static inline void simputs(const char *str) {
    (void)str;
}
static inline void simputhex16(uint16_t val) {
    (void)val;
}
static inline void simputhex32(uint32_t val) {
    (void)val;
}
static inline void simputhex64(const uint64_t val) {
    (void)val;
}
static inline void simputshex16(const char *msg, uint16_t val) {
    (void)msg;
    (void)val;
}
static inline void simputshex32(const char *msg, uint32_t val) {
    (void)msg;
    (void)val;
}
static inline void simputshex64(const char *msg, uint64_t val) {
    (void)msg;
    (void)val;
}
#endif

#endif /* VIRT_CONSOLE_H */

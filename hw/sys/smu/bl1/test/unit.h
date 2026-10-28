/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal host test framework: each CHECK records a failure and continues, so one run reports
// every broken case.

#pragma once

#include <stdint.h>
#include <stdio.h>

extern unsigned unit_checks;
extern unsigned unit_failures;

#define CHECK(cond) \
    do { \
        unit_checks++; \
        if (!(cond)) { \
            unit_failures++; \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        } \
    } while (0)

#define CHECK_EQ(actual, expected) \
    do { \
        unsigned long long unit_a_ = (unsigned long long)(actual); \
        unsigned long long unit_e_ = (unsigned long long)(expected); \
        unit_checks++; \
        if (unit_a_ != unit_e_) { \
            unit_failures++; \
            printf("FAIL %s:%d: %s == 0x%llx, expected 0x%llx\n", __FILE__, __LINE__, #actual, \
                   unit_a_, unit_e_); \
        } \
    } while (0)

// Reads a whole fixture file; returns its length, or 0 when it cannot be read.
size_t unit_read_file(const char *path, uint8_t *buf, size_t cap);

void test_zones(void);
void test_message(void);
void test_secure_state(void);
void test_record(void);
void test_handoff(void);

/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdio.h>

#include "unit.h"

unsigned unit_checks;
unsigned unit_failures;

size_t unit_read_file(const char *path, uint8_t *buf, size_t cap) {
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        printf("FAIL cannot open fixture %s\n", path);
        unit_failures++;
        return 0;
    }
    size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return n;
}

int main(void) {
    test_zones();
    test_message();
    test_secure_state();
    test_record();
    test_handoff();
    printf("%u/%u checks passed\n", unit_checks - unit_failures, unit_checks);
    return unit_failures == 0 ? 0 : 1;
}

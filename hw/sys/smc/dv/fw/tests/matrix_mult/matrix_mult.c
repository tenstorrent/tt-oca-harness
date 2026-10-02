/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"
#include "cpu_perf.h"

/* Number of power-of-two size classes; the arrays fit the largest class. */
#define MATRIX_SIZES 5
#define MAX_DIM (1 << (MATRIX_SIZES - 1))
#define N_ITER 5

static double A[MAX_DIM][MAX_DIM];
static double B[MAX_DIM][MAX_DIM];
static double C_standard[MAX_DIM][MAX_DIM];

void matrix_multiply_standard(int M, int K, int N) {
    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) {
            C_standard[i][j] = 0.0;
            for (int l = 0; l < K; l++) {
                C_standard[i][j] += A[i][l] * B[l][j];
            }
        }
    }
}

void initialize_matrix_random(double matrix[][MAX_DIM], int M, int N) {
    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) {
            matrix[i][j] = (double)get_random_int() / 32767.0 * 10.0;
        }
    }
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        init_test(hartid);

        for (int dim_log = 0; dim_log < MATRIX_SIZES; dim_log++) {
            int dim = (int)int_pow(2, dim_log);
            start_counter();
            for (int i = 0; i < N_ITER; i++) {
                initialize_matrix_random(A, dim, dim);
                initialize_matrix_random(B, dim, dim);
                simputs("Done initializing matrices.\n");

                start_subsequence();
                matrix_multiply_standard(dim, dim, dim);
                end_subsequence();
                simputs("Standard matrix multiplication completed.\n");
            }
            end_counter();
        }

        test_pass(hartid);
    }

    while (true) {
        __asm__("wfi");
    }
}

int other_main(int hartid) {
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}

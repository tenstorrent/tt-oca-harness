/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "cpu_perf.h"

// Number of array sizes to test (powers of 2, ie 1, 2, 4, 8, 16, 32, ...)
#define ARRAY_SIZES 12
// Number of iterations for each size
#define N_ITER 5
// Maximum size of the array (2^ARRAY_SIZES)
#define INT_POW (1 << ARRAY_SIZES)

static int arr[INT_POW];

/* Scratch for merge(), in .bss: the largest merges do not fit on the 4 KiB
 * stack. INT_POW, the length of arr[], bounds any span merge() handles. */
static int merge_lo[INT_POW];
static int merge_hi[INT_POW];

// Merge the sorted spans arr[l..m] and arr[m+1..r] back into arr[l..r]
void merge(int arr[], int l, int m, int r) {
    int i, j, k;
    int n1 = m - l + 1;
    int n2 = r - m;

    int *L = merge_lo;
    int *R = merge_hi;

    for (i = 0; i < n1; i++) L[i] = arr[l + i];
    for (j = 0; j < n2; j++) R[j] = arr[m + 1 + j];

    i = 0;
    j = 0;
    k = l;
    while (i < n1 && j < n2) {
        if (L[i] <= R[j]) {
            arr[k] = L[i];
            i++;
        } else {
            arr[k] = R[j];
            j++;
        }
        k++;
    }

    while (i < n1) {
        arr[k] = L[i];
        i++;
        k++;
    }

    while (j < n2) {
        arr[k] = R[j];
        j++;
        k++;
    }
}

void merge_sort(int arr[], int l, int r) {
    if (l < r) {
        int m = l + (r - l) / 2;

        merge_sort(arr, l, m);
        merge_sort(arr, m + 1, r);

        merge(arr, l, m, r);
    }
}

void fill_array(int arr[], int size) {
    for (int i = 0; i < size; i++) {
        arr[i] = get_random_int() % 1000;
    }
}

/* Require the array to be non-decreasing, and its element sum to be unchanged.
 * The sum check catches most sorts that drop or duplicate elements, which the
 * order check alone would accept. */
static void check_sorted(int arr[], int size, int expect_sum, int size_log, int iter) {
    int sum = 0;

    for (int i = 0; i < size; i++) {
        sum += arr[i];
        if (i > 0 && arr[i - 1] > arr[i]) {
            simputs("[ERROR] merge_sort left the array out of order\n");
            simputshex32("  size_log = ", (uint32_t)size_log);
            simputshex32("  iter     = ", (uint32_t)iter);
            simputshex32("  index    = ", (uint32_t)i);
            simputshex32("  prev     = ", (uint32_t)arr[i - 1]);
            simputshex32("  this     = ", (uint32_t)arr[i]);
            test_fail(0);
        }
    }
    if (sum != expect_sum) {
        simputs("[ERROR] merge_sort did not preserve the elements\n");
        simputshex32("  size_log = ", (uint32_t)size_log);
        simputshex32("  iter     = ", (uint32_t)iter);
        simputshex32("  sum before = ", (uint32_t)expect_sum);
        simputshex32("  sum after  = ", (uint32_t)sum);
        test_fail(0);
    }
}

int main() {

    if (metal_cpu_get_current_hartid() == 0) {
        init_test(0);

        for (int size_log = 0; size_log < ARRAY_SIZES; size_log++) {
            int size = (int)int_pow(2, size_log);
            start_counter();
            for (int i = 0; i < N_ITER; i++) {
                fill_array(arr, size);
                int expect_sum = 0;
                for (int j = 0; j < size; j++) {
                    expect_sum += arr[j];
                }
                start_subsequence();
                merge_sort(arr, 0, size - 1);
                end_subsequence();
                check_sorted(arr, size, expect_sum, size_log, i);
            }
            end_counter();
        }

        test_pass(0);
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

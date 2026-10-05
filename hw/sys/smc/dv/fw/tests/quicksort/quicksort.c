/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "cpu_perf.h"

#define ARRAY_SIZES 12
#define N_ITER 5
#define INT_POW (1 << ARRAY_SIZES)

static int arr[INT_POW];

void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

// Partition around the last element; returns the pivot's final index.
int partition(int arr[], int low, int high) {
    int pivot = arr[high];
    int i = (low - 1);

    for (int j = low; j <= high - 1; j++) {
        if (arr[j] <= pivot) {
            i++;
            swap(&arr[i], &arr[j]);
        }
    }
    swap(&arr[i + 1], &arr[high]);
    return (i + 1);
}

// Recursion depth is not bounded: an input whose pivot is always extremal,
// such as all-equal values (what the fill produces from a zero seed), recurses
// once per element and overflows the stack at the larger array sizes.
void quick_sort(int arr[], int low, int high) {
    if (low < high) {
        int pi = partition(arr, low, high);

        quick_sort(arr, low, pi - 1);
        quick_sort(arr, pi + 1, high);
    }
}

void fill_array(int arr[], int size) {
    for (int i = 0; i < size; i++) {
        arr[i] = get_random_int() % 1000;
    }
}

/* Require the array to be non-decreasing and its element sum to be unchanged.
 *
 * Ordering alone is satisfied by a sort that drops or duplicates elements; the
 * sum carried in from before the sort catches most such losses. */
static void check_sorted(int arr[], int size, int expect_sum, int size_log, int iter) {
    int sum = 0;

    for (int i = 0; i < size; i++) {
        sum += arr[i];
        if (i > 0 && arr[i - 1] > arr[i]) {
            simputs("[ERROR] quick_sort left the array out of order\n");
            simputshex32("  size_log = ", (uint32_t)size_log);
            simputshex32("  iter     = ", (uint32_t)iter);
            simputshex32("  index    = ", (uint32_t)i);
            simputshex32("  prev     = ", (uint32_t)arr[i - 1]);
            simputshex32("  this     = ", (uint32_t)arr[i]);
            test_fail(0);
        }
    }
    if (sum != expect_sum) {
        simputs("[ERROR] quick_sort did not preserve the elements\n");
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
                quick_sort(arr, 0, size - 1);
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

    return 0;
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

/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "cpu_perf.h"

#define ARRAY_SIZES 12
#define N_ITER 5
#define INT_POW (1 << ARRAY_SIZES)

static int arr[INT_POW];

// Function to swap two elements
void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

// This function takes last element as pivot, places
// the pivot element at its correct position in sorted
// array, and places all smaller (smaller than pivot)
// to left of pivot and all greater elements to right
// of pivot
int partition(int arr[], int low, int high) {
    int pivot = arr[high]; // pivot
    int i = (low - 1);     // Index of smaller element

    for (int j = low; j <= high - 1; j++) {
        // If current element is smaller than or
        // equal to pivot
        if (arr[j] <= pivot) {
            i++; // increment index of smaller element
            swap(&arr[i], &arr[j]);
        }
    }
    swap(&arr[i + 1], &arr[high]);
    return (i + 1);
}

// The main function that implements QuickSort
// arr[] --> Array to be sorted,
// low  --> Starting index,
// high  --> Ending index
//
// HAZARD, left as-is: recursion depth here is unbounded and can
// exceed the stack. Lomuto partition degrades to depth n when the pivot is
// always extremal, and the frame is 48 bytes (see the prologue in the built
// .dis), so ARRAY_SIZES-1 = 2048 elements needs ~98 KB against
// __stack_size = 4K (toolchain.mk) -- about 85 frames is all that fits. The
// all-equal input is one of the degenerate cases, and it is exactly what the
// fill path produces when the seed is zero.
//
// Not repaired here because the standard fix -- recurse into the smaller
// partition and loop on the larger, bounding depth to O(log n) -- changes the
// call structure of a routine whose purpose is to be *measured*. Doing that
// silently would alter the benchmark while its numbers are already unchecked
// (this test compares no result and calls test_pass unconditionally). It needs
// the perf owner to say whether the published figures may move.
void quick_sort(int arr[], int low, int high) {
    if (low < high) {
        // pi is partitioning index, arr[p] is now
        // at right place
        int pi = partition(arr, low, high);

        // Separately sort elements before
        // partition and after partition
        quick_sort(arr, low, pi - 1);
        quick_sort(arr, pi + 1, high);
    }
}

// Utility function to fill array with random numbers
void fill_array(int arr[], int size) {
    for (int i = 0; i < size; i++) {
        arr[i] = get_random_int() % 1000;
    }
}

/* Require the array to be non-decreasing and its element sum to be unchanged.
 *
 * Ordering alone is satisfied by a sort that drops or duplicates elements; the
 * sum carried in from before the sort makes this a permutation check. */
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

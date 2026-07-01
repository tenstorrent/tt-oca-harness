/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdio.h>
#include <stdlib.h>
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

// Merge function to merge two halves
void merge(int arr[], int l, int m, int r) {
    int i, j, k;
    int n1 = m - l + 1;
    int n2 = r - m;

    // Create temp arrays
    int L[n1], R[n2];

    // Copy data to temp arrays L[] and R[]
    for (i = 0; i < n1; i++)
        L[i] = arr[l + i];
    for (j = 0; j < n2; j++)
        R[j] = arr[m + 1 + j];

    // Merge the temp arrays back into arr[l..r]
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

    // Copy the remaining elements of L[], if there are any
    while (i < n1) {
        arr[k] = L[i];
        i++;
        k++;
    }

    // Copy the remaining elements of R[], if there are any
    while (j < n2) {
        arr[k] = R[j];
        j++;
        k++;
    }
}

// Merge sort function
void merge_sort(int arr[], int l, int r) {
    if (l < r) {
        int m = l + (r - l) / 2;

        // Sort first and second halves
        merge_sort(arr, l, m);
        merge_sort(arr, m + 1, r);

        // Merge the sorted halves
        merge(arr, l, m, r);
    }
}

// Utility function to fill array with random numbers
void fill_array(int arr[], int size) {
    for (int i = 0; i < size; i++) {
        arr[i] = get_random_int() % 1000;
    }
}

int main() {

	if (metal_cpu_get_current_hartid() == 0){
        init_test(0);

        for (int size_log = 0; size_log < ARRAY_SIZES; size_log++) {
            int size = (int)int_pow(2, size_log);
            start_counter(); 
            for (int i = 0; i < N_ITER; i++) {
                // Measure the time taken for merge sort
                fill_array(arr, size);
                start_subsequence();
                merge_sort(arr, 0, size - 1);
                end_subsequence();
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

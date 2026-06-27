/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

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
void swap(int* a, int* b) {
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
                quick_sort(arr, 0, size - 1);
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

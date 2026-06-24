/*
 * SMC Test Common Implementation
 * 
 * Global state definitions for test utilities
 */

#include "smc_test.h"

/* Global random state - single instance shared across all files */
uint32_t _RANDOM_LFSR = 0;
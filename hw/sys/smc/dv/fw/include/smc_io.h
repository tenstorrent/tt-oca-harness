/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_IO_H
#define SMC_IO_H

/* SMC firmware register-I/O umbrella.
 *
 * Aggregates the generic MMIO accessors and the per-peripheral register
 * helpers built on the native PeakRDL SMC_TOP_* map. Include this from drivers
 * and tests to get the full SMC helper surface. */

#include "virt_console.h"
#include "smc_reg_access.h"

#define NUM_EXTERNAL_INTERRUPTS (256)  /* 4-core: NUM_EXT_INTERRUPTS=256 */
#define MAILBOX_INTERUPT_ID_BASE (288) /* cpu_interrupts_o[288] */

#include "smc_strap.h"
#include "smc_cpu_ctrl.h"
#include "smc_mailbox.h"
#include "smc_mem.h"
#include "smc_dma_ctrl.h"
#include "smc_gpio.h"
#include "smc_avsbus.h"
#include "smc_uart.h"
#include "smc_cluster.h"

#endif /* SMC_IO_H */

/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Production ROM - Common Includes
 *
 * Common header that includes frequently used libraries for SMC production ROM development.
 */

#ifndef SMC_PROD_ROM_H
#define SMC_PROD_ROM_H

/* Standard C libraries */
#include <stdint.h>
#include <stdbool.h>

/* SMC ROM Core definitions */
#include "smc_defines.h"
#include "smc_rom_defs.h"

/* Hardware drivers */
#include "smc_strap.h"
#include "smc_efuse.h"
#include "smc_pll.h"

/* Libraries */
#include "smc_security.h"
#include "smc_interface_map.h"
#include "smc_status.h"
#include "smc_scratchpad.h"
#include "smc_post_code.h"
#include "occp.h"
#include "smc_occp_status.h"
/* Utilities */
#include "virt_console.h"

#endif /* SMC_PROD_ROM_H */

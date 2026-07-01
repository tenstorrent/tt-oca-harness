/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC firmware register umbrella.
 *
 * Hand-maintained collection of #includes (NOT generated). It pulls in the SMC
 * address header and the per-block register headers so firmware can include a
 * single header. Each include resolves from a generated location on the build's
 * search path:
 *   - smc_addr.h, the local sub-block headers: hw/sys/smc/regs/gen/c[/blocks]
 *   - hw/ip block headers: each hw/ip/<block>/regs/gen/c
 * Add a line here when a sub-block is added to smc.rdl.
 */
#ifndef SMC_H
#define SMC_H

#include "smc_addr.h"
#include "avsbus_controller.h"
#include "dma_ctrl.h"
#include "dfx_ctrl_status.h"
#include "axi_filter.h"
#include "gpio_wrap.h"
#include "gpio_poc_pbias_ctrl.h"
#include "pvt_wrap.h"
#include "reset_unit.h"
#include "axi_alias_remap.h"
#include "axil_mailbox_smc_wrap.h"
#include "output_remap.h"
#include "system_timer_octs.h"
#include "telemetry_receiver_wrap.h"
#include "uart_wrap.h"
#include "zeroer.h"
#include "misc_wrap.h"
#include "bus_error_unit.h"
#include "clint.h"
#include "efuse_interface_ctrl.h"
#include "efuse_shim_ctrl.h"
#include "oca_i3c_wrap.h"
#include "plic.h"
#include "cpu_ctrl.h"
#include "smc_base_config.h"
#include "smc_efuse_map.h"
#include "wdt.h"
#include "pll_wrap.h"
#include "i2c_wrap.h"
#include "debug_module.h"
#include "dfd.h"
#include "smc_axil_extension.h"

#endif /* SMC_H */

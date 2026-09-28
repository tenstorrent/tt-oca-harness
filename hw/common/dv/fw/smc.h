/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC firmware register umbrella.
 *
 * Hand-maintained list of #includes (not generated). Firmware includes this
 * one header to get smc_addr.h (SMC_TOP_* base addresses) and the PeakRDL
 * C headers for each SMC sub-block.
 *
 * Generated headers are on the compiler search path when FW_REG_SYS=smc
 * (see ocah_fw_reg_includes in hw/common/dv/fw/compile.mk):
 *   - hw/sys/smc/regs/gen/c[/blocks]
 *   - hw/ip/<block>/regs/gen/c
 *   - hw/common/axi/<block>/regs/gen/c
 *   - vendor/<org>/<ip>/overlay/rdl/gen/c
 *   - hw/sys/smc/dv/models/regs/gen/c and hw/ip/.../dv/models/regs/gen/c
 *
 * Each #include name is the generated addrmap name, which may differ from
 * the instance name in smc.rdl (e.g. filter_ctrl, alias_remap, smc_cla).
 * Add a line here when a new sub-block is wired into smc.rdl.
 */
#ifndef SMC_H
#define SMC_H

#include "smc_addr.h"
#include "avsbus_controller.h"
#include "gpio_ctrl_addr.h"
#include "dma_ctrl.h"
#include "dfx_ctrl_status.h"
#include "filter_ctrl.h"
#include "gpio_wrap.h"
#include "gpio_poc_pbias_ctrl.h"
#include "pvt_wrap.h"
#include "reset_unit.h"
#include "alias_remap.h"
#include "axil_mailbox_smc_wrap.h"
#include "output_remap.h"
#include "system_timer_octs.h"
#include "telemetry_receiver_wrap.h"
#include "uart_wrap.h"
#include "zeroer_ctrl.h"
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
#include "smc_cla.h"

/* Per-pad gpio_ctrl addresses in the smc_external window. */
#define SMC_TOP_GPIO_CTRL_COUNT SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_NUM
#define SMC_TOP_GPIO_CTRL_STRIDE SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_STRIDE

#define SMC_TOP_GPIO_CTRL_BASE_ADDR(i) SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(i)
#define SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(i) \
    (SMC_TOP_GPIO_CTRL_BASE_ADDR(i) + GPIO_CTRL_CONTROL_BASE_ADDR)

#endif /* SMC_H */

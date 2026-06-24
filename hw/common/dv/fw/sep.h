/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*
 * SEP firmware register umbrella.
 *
 * Hand-maintained collection of #includes (NOT generated). It pulls in the SEP
 * address header and the per-block register headers so firmware can include a
 * single header. Each include resolves from a generated location on the build's
 * search path:
 *   - sep_addr.h, the local sub-block headers: hw/sys/sep/regs/gen/c[/blocks]
 *   - hw/ip block headers: each hw/ip/<block>/regs/gen/c
 * Add a line here when a sub-block is added to sep.rdl.
 */
#ifndef SEP_H
#define SEP_H

#include "sep_addr.h"
#include "otbn.h"
#include "hmac.h"
#include "aes.h"
#include "kmac.h"
#include "secure_dma.h"
#include "aon_timer.h"
#include "sep_efuse_map.h"
#include "efuse_interface_ctrl.h"
#include "efuse_mmr.h"
#include "efuse_shim_ctrl.h"
#include "sep_lifecycle_ctrl.h"
#include "km_mailbox_sep.h"
#include "output_remap.h"
#include "axi_alias_remap.h"
#include "axi_filter.h"
#include "axil_mailbox_sep_wrap.h"
#include "sep_cpu_ctrl.h"
#include "sep_reset_ctrl.h"
#include "spi_controller.h"
#include "sep_axi_extension.h"
#include "sep_scratch.h"
#include "el2_pic.h"

#endif /* SEP_H */

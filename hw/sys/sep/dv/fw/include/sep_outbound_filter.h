/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Forwarding header: the outbound-filter driver lives in
 * hw/sys/sep/dv/fw/drivers/sep_outbound_filter.h. FW_INCLUDES puts include/
 * ahead of drivers/, so this file forwards there.
 */
#ifndef SEP_OUTBOUND_FILTER_INCLUDE_SHIM_H
#define SEP_OUTBOUND_FILTER_INCLUDE_SHIM_H

#include "../drivers/sep_outbound_filter.h"

#endif /* SEP_OUTBOUND_FILTER_INCLUDE_SHIM_H */

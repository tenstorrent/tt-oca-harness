/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "sep_fabric.h"

/* No-op stubs for the SEP fabric alias/remap setup helpers. They program no
 * hardware. */

int write_alias_csr_register() {
    return 0;
}
int read_alias_csr_register() {
    return 0;
}
int perform_alias_csr_soft_reset() {
    return 0;
}
int setup_alias_wrap_maximum_intensity() {
    return 0;
}
int setup_axi_filter_wrap_entry() {
    return 0;
}
int setup_local_alias_advanced_mapping() {
    return 0;
}
int test_axi_transaction_with_attributes() {
    return 0;
}
int setup_local_alias_deep_config() {
    return 0;
}
int setup_local_alias_complex_routing() {
    return 0;
}
int setup_local_alias_master_routing() {
    return 0;
}
int setup_local_alias_timing_critical() {
    return 0;
}
int setup_local_alias_remap_extended() {
    return 0;
}
int setup_local_alias_remap_master_specific() {
    return 0;
}
int setup_local_alias_remap_boundary() {
    return 0;
}
int setup_output_remap_region_multi_level() {
    return 0;
}
int setup_output_remap_region_priority() {
    return 0;
}

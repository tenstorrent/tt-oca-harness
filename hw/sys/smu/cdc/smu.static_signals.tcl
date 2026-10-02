# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
########################################################
# Quasi Static Signals (SMU top)
########################################################
#
# Only SMU top-PORT truth lives here. The subcomponent-internal stamps (u_smc boundary
# pins like boot_stall_jtag_*, lc_state_i, spi_enable_i, and every SMC-internal CSR/sync
# pin) come from the inherited smc_static_signals.tcl re-anchored via cdc_port_or_pin in
# hw/sys/smu/cdc/smu.cdc_rdc.tcl.

# will transition once to indicate status of POR DFX logic
create_static -name [get_ports {mem_repair_done_i}]
create_static -name [get_ports {mem_repair_success_i}]
create_static -name [get_ports {mem_repair_abort_i}]
create_static -name [get_ports {mbist_done_i}]
create_static -name [get_ports {mbist_pass_i}]
create_static -name [get_ports {mbist_abort_i}]

# Boot stall
create_static -name [get_ports {pad2core_i[60]}]

# will transition once as a strap (one time capture on cold reset de-assertion)
create_static -name [get_ports {smc_disable_sram_auto_init_i}]

# Primary chiplet / boot-master mode strap. Quasi-static after fuse sense.
create_static -name [get_ports {chiplet_is_primary_i}]

# SEP TEST_EN strap, captured once at boot.
create_static -name [get_ports {secure_tm_req_i}]

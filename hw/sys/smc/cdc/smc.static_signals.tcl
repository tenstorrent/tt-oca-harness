# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
########################################################
# Quasi Static Signals
########################################################
# Hierarchy-reusable: port references go through cdc_port_or_pin, anchored internal paths
# through cdc_inst, `-hier` globs are level-independent. See hier_reuse_procs.tcl.

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
}

# create_static on a block port (or the same-named instance pin at the parent), guarded.
proc _smc_static_port { pattern } {
    set obj [cdc_port_or_pin $pattern]
    if { [sizeof_collection $obj] > 0 } {
        create_static -name $obj
    } else {
        puts "WARNING: smc_static_signals: no object matches '$pattern' (prefix '$::cdc_hier_prefix') - skipped"
    }
}

# create_static on an anchored internal path, re-anchored by cdc_inst, guarded.
proc _smc_static_pin { path } {
    set obj [get_pins -quiet [cdc_inst $path]]
    if { [sizeof_collection $obj] > 0 } {
        create_static -name $obj
    } else {
        puts "WARNING: smc_static_signals: no pin matches '[cdc_inst $path]' - skipped"
    }
}

# The following can be marked as Quasi-static

# will transition once to indicate status of POR DFX logic
_smc_static_port {mem_repair_done_i}
_smc_static_port {mem_repair_success_i}
_smc_static_port {mem_repair_abort_i}
_smc_static_port {mbist_done_i}
_smc_static_port {mbist_pass_i}
_smc_static_port {mbist_abort_i}

# Boot Stall
_smc_static_port {pad2core_i[60]}
_smc_static_port {boot_stall_jtag_ovrd_i}
_smc_static_port {boot_stall_jtag_val_i}

# will transition infrequently, only if lifecycle state gets updated from the SEP
_smc_static_port {lc_state_i}

# will transition once as a strap (one time capture on cold reset de-assertion)
_smc_static_port {smc_disable_sram_auto_init_i}
_smc_static_port {chiplet_is_primary_i}

# controlled by internal register, expected to set once during boot and not expected to change frequently
_smc_static_port {smc_region_size_o*}

# GPIO mode / ownership controls
# These are expected to be programmed during setup, before the GPIOs are
# actively used by a live protocol.
_smc_static_port {lsio_interface_select_o*}
_smc_static_port {core2pad_en_o*}
_smc_static_port {pad2core_en_o*}

# GPIO interface register fields that choose interface ownership, direction,
# interrupt mode, and access filtering. These are treated as quasi-static
# control fields, not live GPIO data/status.
set gpio_qs_fields [get_nets -hier {
    *gpio_intf_hwif_out.DATA_CTRL.enable_rx_tx.value*
    *gpio_intf_hwif_out.DATA_CTRL.interface_enable.value*
    *gpio_intf_hwif_out.DATA_CTRL.lsio_select.value*
    *gpio_intf_hwif_out.DATA_CTRL.interrupt_enable.value*
    *gpio_intf_hwif_out.DATA_CTRL.lsio_disable.value*
    *gpio_intf_hwif_out.DATA_CTRL.interrupt_type.value*
    *gpio_intf_hwif_out.DATA_CTRL_ENABLE.use_reg_core2pad.value*
} -quiet]
if { [sizeof_collection $gpio_qs_fields] > 0 } {
    create_static -name $gpio_qs_fields
}

# field_storage flop Q pins for the same quasi-static control fields. The glitch
# engine reports its reconvergence sources at these pins
# (.../u_gpio_intf_reg/field_storage.DATA_CTRL.<field>.value/Q), so they must be
# stamped directly for the core2pad_o glitch path to be pruned.
set gpio_qs_field_storage_pins [get_pins -hier -quiet {
    *u_gpio_intf_reg/field_storage.DATA_CTRL.enable_rx_tx.value/Q
    *u_gpio_intf_reg/field_storage.DATA_CTRL.interface_enable.value/Q
    *u_gpio_intf_reg/field_storage.DATA_CTRL.lsio_select.value/Q
    *u_gpio_intf_reg/field_storage.DATA_CTRL.interrupt_enable.value/Q
    *u_gpio_intf_reg/field_storage.DATA_CTRL.lsio_disable.value/Q
    *u_gpio_intf_reg/field_storage.DATA_CTRL.interrupt_type.value/Q
    *u_gpio_intf_reg/field_storage.DATA_CTRL_ENABLE.use_reg_core2pad.value/Q
}]
if { [sizeof_collection $gpio_qs_field_storage_pins] > 0 } {
    create_static -name $gpio_qs_field_storage_pins
}

_smc_static_pin {u_smc_peripherals/u_avsbus_controller/u_avsbus_controller_reg_inst/field_storage.AVS_CONFIG.AVS_GPIO_ENABLE.value/Q}

_smc_static_port {spi_enable_i}

# -----------------------------------------------------------------------------
# UART / I2C / SMBus interface-enable CSRs — quasi-static during live traffic
# -----------------------------------------------------------------------------
# These CSR fields are the "is this protocol enabled on its LSIO pads?" master switches.
# Software programs them once during peripheral init and holds them stable while the protocol
# is actively running. They are NOT live traffic data.
#
# Without these `create_static` declarations, VC SpyGlass models the gating as a dynamic mux
# across two clock domains and reports a large cluster of `CDC_UNSYNC_CTRL` + `CDC_GLITCH_CTRL` violations.
# Functionally the glitch risk is zero: these enables only transition when the corresponding protocol is not
# actively receiving, so any brief gate transition can't be mistaken for a real protocol activity.

_smc_static_pin {u_smc_peripherals/u_uart_wrap/gen_uart_log_engine_wraps[0].u_uart_log_engine_wrap/u_uart_log_engine_ctrl_reg/field_storage.CTRL.UART_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_uart_wrap/gen_uart_log_engine_wraps[1].u_uart_log_engine_wrap/u_uart_log_engine_ctrl_reg/field_storage.CTRL.UART_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_uart_wrap/gen_uart_log_engine_wraps[2].u_uart_log_engine_wrap/u_uart_log_engine_ctrl_reg/field_storage.CTRL.UART_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_uart_wrap/gen_uart_log_engine_wraps[3].u_uart_log_engine_wrap/u_uart_log_engine_ctrl_reg/field_storage.CTRL.UART_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_uart_enable_sync/u_sync3[0]/q_ddd/Q}
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_uart_enable_sync/u_sync3[1]/q_ddd/Q}
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_uart_enable_sync/u_sync3[2]/q_ddd/Q}
# UART3 (`sync3[3]`): final-stage sync output quasi-static because upstream UART_EN CSR is.
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_uart_enable_sync/u_sync3[3]/q_ddd/Q}
_smc_static_pin {u_smc_peripherals/u_i2c_wrap/u_i2c_ctrl_reg/field_storage.I2C_CTRL[0].I2C_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_i2c_wrap/u_i2c_ctrl_reg/field_storage.I2C_CTRL[1].I2C_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_i2c_wrap/u_i2c_ctrl_reg/field_storage.I2C_CTRL[2].I2C_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_i2c_wrap/u_i2c_ctrl_reg/field_storage.I2C_CTRL[0].SMBUS_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_i2c_wrap/u_i2c_ctrl_reg/field_storage.I2C_CTRL[1].SMBUS_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_i2c_wrap/u_i2c_ctrl_reg/field_storage.I2C_CTRL[2].SMBUS_EN.value/Q}
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_i2c_enable_sync/u_sync3[0]/q_ddd/Q}
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_i2c_enable_sync/u_sync3[1]/q_ddd/Q}
_smc_static_pin {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_i2c_enable_sync/u_sync3[2]/q_ddd/Q}

# hartResetReg_[0-3] are JTAG-written quasi-static registers — they change only
# on explicit DMCONTROL.hartreset JTAG writes (10-50MHz TCK).
set hart_reset_pins [get_pins -quiet \
    [cdc_inst {u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/dmOuter/hartResetReg_*/Q}]]
if { [sizeof_collection $hart_reset_pins] > 0 } {
    create_static -name $hart_reset_pins
}

rename _smc_static_port {}
rename _smc_static_pin {}

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Elaborate the top with Vivado from the Bender file list or Bender's Vivado script.
set script_dir [file dirname [info script]]
source [file join $script_dir common.tcl]

create_project -in_memory -part $part
# Vivado's automatic compile order misses package references in parameter port
# lists, so keep the order Bender emits.
set_property source_mgmt_mode None [current_project]

if { $input eq "script" } {
    ocah_read_bender_script $vivado_script $sv_flist
} else {
    ocah_read_flist $sv_flist
}

# Some vendored .v sources are written in SystemVerilog.
set verilog [get_files -quiet -filter {FILE_TYPE == Verilog}]
if { [llength $verilog] } {
    set_property file_type SystemVerilog $verilog
}

set_property top $top_design [current_fileset]
report_compile_order -used_in synthesis -file "$rep_dir/${top_design}_compile_order.rpt"
synth_design -rtl -top $top_design -part $part
puts "VIVADO_ELABORATION_PASS: $top_design"

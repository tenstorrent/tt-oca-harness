# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Shared Vivado setup: env-driven inputs, reports dir, and the source loaders.
# Env vars are set by flows/fpga/vivado/vivado.mk.
proc ocah_env { name default } {
    if { [info exists ::env($name)] } { return $::env($name) }
    return $default
}

set sv_flist [ocah_env SV_FLIST "design.f"]
set vivado_script [ocah_env VIVADO_SCRIPT "design.tcl"]
set input [ocah_env VIVADO_INPUT "flist"]
set top_design [ocah_env TOP_DESIGN "design"]
set part [ocah_env PART "xczu15eg-ffvb1156-2-i"]
set out_dir [ocah_env OUT_DIR "."]
set rep_dir $out_dir/reports
file mkdir $rep_dir

puts "using: input      = '$input'"
puts "using: sv_flist   = '$sv_flist'"
puts "using: top_design = '$top_design'"
puts "using: part       = '$part'"

# Split a Bender flist-plus file into include dirs, defines and sources.
proc ocah_parse_flist { path } {
    set parsed [dict create incdirs {} defines {} files {}]
    set fh [open $path r]
    foreach line [split [read $fh] "\n"] {
        set line [string trim $line]
        if { $line eq "" || [string match "//*" $line] } { continue }
        if { [string match "+incdir+*" $line] } {
            dict lappend parsed incdirs [string range $line 8 end]
        } elseif { [string match "+define+*" $line] } {
            dict lappend parsed defines [string range $line 8 end]
        } else {
            dict lappend parsed files [file normalize $line]
        }
    }
    close $fh
    return $parsed
}

# Vivado treats a listed .vh or .svh file as an include-only header, but a Bender
# source list compiles every entry: some carry packages, others macros later
# sources use without including them.
proc ocah_compile_headers { files } {
    foreach f $files {
        if { [regexp {\.s?vh$} $f] } {
            set_property file_type SystemVerilog [get_files $f]
        }
    }
}

proc ocah_read_flist { path } {
    set parsed [ocah_parse_flist $path]
    add_files -norecurse [dict get $parsed files]
    ocah_compile_headers [dict get $parsed files]
    set_property include_dirs [dict get $parsed incdirs] [current_fileset]
    set_property verilog_define [dict get $parsed defines] [current_fileset]
}

# Bender's Vivado script leaves out .vh and .svh sources. Restore each one after
# the source that precedes it in the matching flist.
proc ocah_read_bender_script { script flist } {
    source $script
    set prev ""
    foreach f [dict get [ocah_parse_flist $flist] files] {
        if { [regexp {\.s?vh$} $f] } {
            add_files -norecurse $f
            ocah_compile_headers [list $f]
            set anchor [get_files -quiet $prev]
            if { $anchor eq "" } {
                reorder_files -front [get_files $f]
            } else {
                reorder_files -after $anchor [get_files $f]
            }
        }
        set prev $f
    }
}

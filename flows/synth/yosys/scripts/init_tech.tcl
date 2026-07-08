# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Tech-agnostic dispatcher: resolve the PDK from the environment (the same
# PDK= value hpretl/iic-osic-tools itself uses to pick /foss/pdks/<PDK>),
# source the matching tech/<pdk>.tcl - the only place PDK-specific data lives
# - then run the one step every PDK shares: load every liberty file into
# yosys. Nothing downstream (elab.tcl, synth.tcl) is tech-aware; they only
# ever consume the generic names this + tech/<pdk>.tcl define ($tech_cells,
# $tech_cells_args, $tech_cell_tiehi/tielo, $dont_use_args, $abc_constr, ...).
# Adding a PDK means adding a sibling tech/<pdk>.tcl; this file never changes.
if {![info exists ::env(PDK)] || $::env(PDK) eq ""} {
    error "init_tech: PDK environment variable is not set (e.g. PDK=ihp-sg13g2)"
}
set tech $::env(PDK)

set tech_dir  [file join [file dirname [info script]] .. tech]
set tech_file [file join $tech_dir "$tech.tcl"]

if {![file exists $tech_file]} {
    set known [glob -nocomplain -tails -directory $tech_dir "*.tcl"]
    error "init_tech: unknown PDK '$tech' (no $tech_file); known: $known"
}

puts "init_tech: loading technology '$tech' from $tech_file"
source $tech_file

# Pre-formatted for easier use in yosys commands: all liberty files, and just
# the standard-cell subset (used for dfflibmap + the final logic-only report).
set lib_list [concat [split $tech_cells] [split $tech_macros]]
set liberty_args [concat {*}[lmap lib $lib_list {concat "-liberty" $lib}]]
set tech_cells_args [concat {*}[lmap lib $tech_cells {concat "-liberty" $lib}]]

foreach file $lib_list {
    yosys read_liberty -lib "$file"
}

set dont_use_args [list]
foreach cell $dont_use_list {
    lappend dont_use_args [concat "-dont_use" $cell]
}
set dont_use_args [concat {*}$dont_use_args]

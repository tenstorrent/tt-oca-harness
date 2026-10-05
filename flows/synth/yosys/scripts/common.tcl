# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Shared synth setup: env-driven inputs + out/tmp/reports dirs. Env vars (set
# by flows/synth/yosys/yosys.mk's `env ...` invocation) replace any
# hardcoded in-repo path/name so the same scripts serve every hw/sys/<block>.
proc ocah_env { name default } {
    if { [info exists ::env($name)] } { return $::env($name) }
    return $default
}

set sv_flist [ocah_env SV_FLIST "build/synth/design.f"]
set proj_name [ocah_env PROJ_NAME "design"]
set top_design [ocah_env TOP_DESIGN $proj_name]
set build_dir [ocah_env OUT_DIR "build/synth"]
set timescale [ocah_env TIMESCALE "1ns/1ps"]
set out_dir $build_dir/out
set tmp_dir $build_dir/tmp
set rep_dir $build_dir/reports

file mkdir $out_dir
file mkdir $tmp_dir
file mkdir $rep_dir

puts "using: sv_flist   = '$sv_flist'"
puts "using: top_design = '$top_design'"
puts "using: proj_name  = '$proj_name'"
puts "using: out_dir    = '$out_dir'"
puts "using: tmp_dir    = '$tmp_dir'"
puts "using: rep_dir    = '$rep_dir'"

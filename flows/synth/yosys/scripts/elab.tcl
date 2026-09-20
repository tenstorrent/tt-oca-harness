# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Elaboration stage: load the yosys-slang plugin, elaborate the design from
# the bender-generated filelist, and report the as-elaborated design before
# any optimization runs. Assumes common.tcl and init_tech.tcl have already
# been sourced (see synth.tcl) for
# $sv_flist/$top_design/$proj_name/$tmp_dir/$rep_dir.
# --single-unit: slang defaults to one compilation unit per file in -f, so
# macros defined in one file (including ocah_vendor_defines.svh) are not
# visible in another.
yosys plugin -i slang.so
yosys read_slang --top $top_design -f $sv_flist \
    --compat-mode --keep-hierarchy --single-unit \
    --allow-use-before-declare --ignore-unknown-modules \
    --timescale=$timescale

# map the dont_touch attribute commonly applied to output nets of async regs
# to yosys's own `keep`, then propagate it back to the driving cell.
yosys attrmap -rename dont_touch keep
yosys attrmap -tocase keep -imap keep="true" keep=1
yosys attrmvcp -copy -attr keep

# A block wanting finer-grained `yosys flatten` granularity later (e.g. to
# keep specific submodules unflattened for debug, or blackbox a hard macro)
# can extend this file with the usual `setattr -set keep_hierarchy` /
# `blackbox` commands.

yosys hierarchy -top $top_design
yosys check
yosys proc
yosys tee -q -o "$rep_dir/${proj_name}_elaborated.rpt" stat
yosys write_verilog -norename -noexpr -attr2comment $tmp_dir/${proj_name}_yosys_elaborated.v

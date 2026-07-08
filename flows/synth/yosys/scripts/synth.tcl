# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Entry point: `yosys -c flows/synth/yosys/scripts/synth.tcl` (see
# flows/synth/yosys/yosys.mk), split by stage: common.tcl (env/dirs) ->
# init_tech.tcl (PDK liberty) -> elab.tcl (read_slang/check/proc) -> this
# file (coarse opt / techmap / flatten / ABC / final netlist+reports).
#
# ABC here uses a plain `-constr`/`-D <period>` pass against a single driving
# cell/load constraint rather than a full timing-driven synthesis script; see
# tech/<tech>.constr for the per-PDK driving-cell/load constraint.
set script_dir [file dirname [info script]]
source [file join $script_dir common.tcl]
source [file join $script_dir init_tech.tcl]
source [file join $script_dir elab.tcl]

# -----------------------------------------------------------------------------
# coarse: similar to `yosys synth -run coarse -noalumacc`
yosys opt_expr
yosys opt -noff
yosys fsm
yosys wreduce
yosys peepopt
yosys opt_clean
yosys opt -full
yosys booth
yosys share
yosys opt
yosys memory -nomap
yosys memory_map
yosys opt -fast

yosys opt_dff -sat -nodffe -nosdff
yosys share
yosys opt -full
yosys clean -purge

yosys write_verilog -norename -noexpr $tmp_dir/${proj_name}_yosys_abstract.v
yosys tee -q -o "$rep_dir/${proj_name}_abstract.rpt" stat -width -tech cmos

yosys techmap
yosys opt -fast
yosys clean -purge

yosys tee -q -o "$rep_dir/${proj_name}_generic.rpt" stat -tech cmos

# flatten all hierarchy except marked modules
yosys flatten
yosys write_verilog -norename $tmp_dir/${proj_name}_flatten.v
yosys clean -purge

# -----------------------------------------------------------------------------
# preserve flip-flop names as far as possible
yosys splitnets -format __v
yosys rename -wire -suffix _reg t:*DFF*
yosys write_verilog -norename $tmp_dir/${proj_name}_yosys_rename.v
yosys select -write $rep_dir/${proj_name}_registers.rpt t:*DFF*
yosys autoname t:*DFF* %n
yosys clean -purge

# report any hard macros / blackboxes selected for synthesis (none by default
# - see the elab.tcl hook comment for how a block would add its own)
yosys tee -q -o $rep_dir/${proj_name}_instances.rpt select -list "a:blackbox"

# -----------------------------------------------------------------------------
# technology mapping
yosys dfflibmap {*}$tech_cells_args

yosys abc {*}$tech_cells_args -D $abc_period_ps -constr $abc_constr {*}$dont_use_args -showtmp
yosys clean -purge

# -----------------------------------------------------------------------------
# prep for place & route
yosys write_verilog -norename -noexpr -attr2comment $out_dir/netlist_debug.v

yosys splitnets -ports -format __v
yosys setundef -zero
yosys clean -purge
yosys hilomap -singleton -hicell {*}$tech_cell_tiehi -locell {*}$tech_cell_tielo

# final reports
yosys tee -q -o "$rep_dir/${proj_name}_synth.rpt" check
yosys tee -q -o "$rep_dir/${proj_name}_area.rpt" stat -top $top_design {*}$liberty_args
yosys tee -q -o "$rep_dir/${proj_name}_area_logic.rpt" stat -top $top_design {*}$tech_cells_args

# final netlist - the deliverable
yosys write_verilog -noattr -noexpr -nohex -nodec $out_dir/${proj_name}_yosys.v

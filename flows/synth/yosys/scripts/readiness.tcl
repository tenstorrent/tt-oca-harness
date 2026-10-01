# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Structural synthesis evidence before technology mapping and ABC.
set script_dir [file dirname [info script]]
source [file join $script_dir common.tcl]

set slang_compat_args {}
if { [info exists ::env(OCAH_SLANG_COMPAT_FLAGS)] } {
    set slang_compat_args $::env(OCAH_SLANG_COMPAT_FLAGS)
}
yosys read_slang --top $top_design -f $sv_flist \
    --single-unit --keep-hierarchy \
    --allow-use-before-declare --ignore-assertions \
    {*}$slang_compat_args \
    --unroll-limit=100000 --error-limit=100 \
    --timescale=$timescale
yosys hierarchy -check -top $top_design
yosys proc
yosys tee -o "$rep_dir/${proj_name}_preopt_check.rpt" check
yosys tee -o "$rep_dir/${proj_name}_latches.rpt" select -list \
    {t:$dlatch} {t:$adlatch} {t:$dlatchsr} {t:$_DLATCH*}
yosys tee -o "$rep_dir/${proj_name}_blackboxes.rpt" select -list a:blackbox
yosys tee -o "$rep_dir/${proj_name}_elaborated.rpt" stat
yosys write_rtlil "$tmp_dir/${proj_name}_elaborated.il"

# Basic cleanup permits a second structural check without area/timing mapping.
yosys opt_expr
yosys opt_clean
# Modules whose latches are intentional. Elaboration uniquifies instances as
# <module>$<hierarchy>, so both spellings are matched. Latches in any other
# module fail the check.
set latch_allowed_modules {
    prim_clock_gating
    efuse_token_digest_sha256
}
set latch_select_expr {t:$dlatch t:$adlatch %u t:$dlatchsr %u t:$_DLATCH* %u}
set first_allowed 1
foreach mod $latch_allowed_modules {
    foreach pattern [list "${mod}/*" "${mod}\$*/*"] {
        append latch_select_expr " $pattern"
        if { !$first_allowed } {
            append latch_select_expr " %u"
        }
        set first_allowed 0
    }
}
append latch_select_expr " %d"
yosys select -assert-none {*}$latch_select_expr
yosys select -assert-none a:blackbox
yosys flatten
yosys opt_expr
yosys opt_clean
yosys tee -o "$rep_dir/${proj_name}_readiness.rpt" check -assert
yosys tee -o "$rep_dir/${proj_name}_readiness_stat.rpt" stat
yosys write_rtlil "$out_dir/${proj_name}_readiness.il"
puts "STRUCTURAL_READINESS_PASS: $top_design (frontend warnings require review)"

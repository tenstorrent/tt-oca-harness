# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# IHP SG13G2 (open 130nm PDK) technology data for the yosys synth flow.
# Ciel exposes the enabled PDK at $PDK_ROOT/$PDK/libs.ref/; these paths and
# cell names match that layout.
set pdk_root [ocah_env PDK_ROOT "/foss/pdks"]
set pdk_dir "$pdk_root/$tech"

set pdk_cells_lib "$pdk_dir/libs.ref/sg13g2_stdcell/lib"
set pdk_sram_lib "$pdk_dir/libs.ref/sg13g2_sram/lib"
set pdk_io_lib "$pdk_dir/libs.ref/sg13g2_io/lib"

set tech_cells [list "$pdk_cells_lib/sg13g2_stdcell_typ_1p20V_25C.lib"]
set tech_macros [glob -nocomplain -directory $pdk_sram_lib *_typ_1p20V_25C.lib]
lappend tech_macros "$pdk_io_lib/sg13g2_io_typ_1p2V_3p3V_25C.lib"

# tie-off cells, for `yosys hilomap`
set tech_cell_tiehi {sg13g2_tiehi L_HI}
set tech_cell_tielo {sg13g2_tielo L_LO}

# cells ABC should never select (none yet for this PDK)
set dont_use_list [list]

# ABC timing constraint: driving cell + external load seen by top-level ports
# (see tech/ihp-sg13g2/abc.constr) and target clock period for delay
# optimization.
set abc_constr [file join [file dirname [info script]] "abc.constr"]
set abc_period_ps 10000

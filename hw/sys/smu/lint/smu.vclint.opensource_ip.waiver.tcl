# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length

# For waiving violations on open-source 3rd party IP

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# PortTypeMismatch-ML: Port type differs from the type of the connected signal
#=======================================================================================================================

#=======================================================================================================================
# Module-name prefix support
#=======================================================================================================================

if { ![info exists PREFIX] } {
    set PREFIX ""
}
# Substitute the literal ${PREFIX} token in a -filter expression with $PREFIX's
# value. Uses string map rather than brace interpolation so that $clog2, bus
# indices like [i], and embedded quotes inside the filter are preserved verbatim.
proc apply_prefix { filter } {
    return [string map [list {${PREFIX}} $::PREFIX] $filter]
}

#=======================================================================================================================
# Ruleset: tt_lint_d0
#=======================================================================================================================

# PortTypeMismatch-ML: PULP axi type-parameter and ID-vector ports inside the smu AXI path.
waive_violation -add {SMU_PortTypeMismatch_axi_cut_spill_register_param} -comment {The port and the signal connected to it have different type names but are the same type: the instantiated module's type parameter is set to the signal's type. Third-party PULP IP shouldn't be modified. Created by gchang on 17-Nov-2026} -filter [apply_prefix {(Module == "${PREFIX}axi_cut") AND (HDLModName == "${PREFIX}spill_register") AND (((NodeType == "T") AND (NodeType1 == "axi_56_64_aw_chan_t")) OR ((NodeType == "T") AND (NodeType1 == "axi_56_64_w_chan_t")) OR ((NodeType == "T") AND (NodeType1 == "axi_56_64_b_chan_t")) OR ((NodeType == "T") AND (NodeType1 == "axi_56_64_ar_chan_t")) OR ((NodeType == "T") AND (NodeType1 == "axi_56_64_r_chan_t")))}] -app { lint } -tag { PortTypeMismatch-ML } -user { gchang } -timestamp { 17-11-2026 12:00:00 }
waive_violation -add {SMU_PortTypeMismatch_axi_id_remap_table_vectors} -comment {The port and the signal connected to it have different type names but are both plain logic vectors of the same width. Third-party PULP IP shouldn't be modified. Created by gchang on 17-Nov-2026} -filter [apply_prefix {(Module == "${PREFIX}axi_id_remap") AND (HDLModName == "${PREFIX}axi_id_remap_table") AND (((NodeType == "id_inp_t") AND (NodeType1 == "axi_out_id_t")) OR ((NodeType == "idx_t") AND (NodeType1 == "sep_56_64_6_12_axi_id_t")))}] -app { lint } -tag { PortTypeMismatch-ML } -user { gchang } -timestamp { 17-11-2026 12:00:00 }

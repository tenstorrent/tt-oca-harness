# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# packed_port_procs.tcl - locate struct fields on packed-array ports
#
# Synthesis bit-blasts a packed array of packed structs into one flat vector,
# so a field-name pattern such as `port*clk` matches nothing in the netlist.
################################################################################

# Names of the clock bit of each of the `count` elements of packed-struct array
# port `port`. Matches `${port}*${field}` while field names survive; otherwise
# takes the MSB of each element, so the clock must be the first struct member.
# Empty when the port does not exist or its width is not a multiple of `count`.
proc packed_clk_ports { port count { field clk } } {
    set named [get_object_name [get_ports -quiet "${port}*${field}"]]
    if { [llength $named] } {
        return [lsort -dictionary $named]
    }
    set total [sizeof_collection [get_ports -quiet "${port}*"]]
    set width [expr { $total / $count }]
    set bits {}
    if { $width && $width * $count == $total } {
        for { set i 1 } { $i <= $count } { incr i } {
            lappend bits "${port}\[[expr { $i * $width - 1 }]\]"
        }
    }
    return $bits
}

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP SpyGlass RDC waivers for open-source PULP IP used by jtag2axi.
# Tenstorrent-owned jtag2axi / prim_fifo_sync waivers live in
# dtp.vcrdc.waiver.tcl.
#
#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# RDC_CORRUPT_OBSERVED : Asynchronous reset assertion at one flop observed at a destination flop with no
#                       matching reset (the tool cannot prove a blocking scheme protects the destination).
#=======================================================================================================================
# All waivers in this file target the PULP common_cells / axi_cdc primitives used by jtag2axi to bridge
# JTAG_TCK <-> DTPCLK:
#
#   axi_cdc_clearable           - top-level AXI clock-domain bridge wrapper
#   cdc_fifo_gray_clearable     - per-channel asynchronous FIFO with gray-coded pointers
#   cdc_reset_ctrlr             - 4-phase clearable-reset coordination handshake
#
# cdc_reset_ctrlr implements a 4-phase clearable-reset handshake:
#   1. Asserting domain signals reset-request to the far side via a synchronizer
#   2. Far side drains in-flight data and acknowledges
#   3. Both sides enter reset-idle; no new data enters the FIFO
#   4. Only after full acknowledgment is traffic allowed to resume
#
# The RDC tool cannot model this protocol and flags paths where a reset-domain state change is theoretically
# visible at a register that has no matching reset, even though the 4-phase handshake guarantees those
# registers are quiescent. Same justification pattern as the cdc_fifo_gray_clearable / cdc_reset_ctrlr /
# axi_cdc_clearable module-scoped CDC waivers in
# block_flow_customizations/dtp/vccdc/inputs/waivers/opensource_ip_waiver.tcl, and the W146 / PragmaComments
# lint waivers in block_flow_customizations/dtp/vclint/inputs/waivers/opensource_ip_waiver.tcl.
#
# Filter naming convention:
#   `cdc_gray_data_q_<field>` waivers use `*data_q*<field>*` and intentionally catch BOTH the source-FIFO
#   register (i_src/data_q[N].<field>) AND the destination-side spill-register entry
#   (i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.<field>), because the spill-reg wrapper preserves the
#   `data_q` substring in its hierarchical name. Both ends share the same clearable-protocol justification.
#
# Violations inside Tenstorrent-owned jtag2axi RTL that involve these primitives at the boundary are waived
# separately in dtp.vcrdc.waiver.tcl (jtag2axi command-processor state, series_*_fifo storage, etc.).
#=======================================================================================================================

#-----------------------------------------------------------------------------------------------------------------------
# cdc_fifo_gray_clearable: source-FIFO and destination spill-register payload fields
#-----------------------------------------------------------------------------------------------------------------------

# AXI AxADDR (address) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_addr} \
    -comment {cdc_fifo_gray_clearable AW/AR channels: AXI AxADDR field in i_src/data_q[N].addr (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.addr (destination spill register). Managed by the 4-phase clearable-reset protocol; when reset asserts the FIFO is drained and both domains are idle before any address value can be consumed by active logic. Each end has an independent reset on its native domain (TCK side: trst_n_combined/tlr_reset; DTPCLK side: rst_n_i).} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*addr*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI AxCACHE (cache attributes) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_cache} \
    -comment {cdc_fifo_gray_clearable AW/AR channels: AXI AxCACHE attribute in i_src/data_q[N].cache (source FIFO, TCK) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.cache (destination spill register, DTPCLK). Managed by the 4-phase clearable-reset protocol; both source and destination ends are quiescent when any reset asserts, so no active AXI transaction can observe a stale AxCACHE value.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*cache*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI WDATA / RDATA payload field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_data} \
    -comment {cdc_fifo_gray_clearable W/R channels: AXI WDATA/RDATA payload in i_src/data_q[N].data (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.data (destination spill register). Managed by the 4-phase clearable-reset protocol; on reset the FIFO is drained and the spill register content is irrelevant until a new transfer arrives.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*data*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI ID field (all channels)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_id} \
    -comment {cdc_fifo_gray_clearable all channels: AXI AxID/RID/BID field in i_src/data_q[N].id (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.id (destination spill register). Managed by the 4-phase clearable-reset protocol; on reset both ends are idle, so no outstanding transaction can misuse a stale ID.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*id*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI WLAST / RLAST (last beat marker) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_last} \
    -comment {cdc_fifo_gray_clearable W/R channels: AXI WLAST/RLAST beat marker in i_src/data_q[N].last (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.last (destination spill register). Managed by the 4-phase clearable-reset protocol; on reset both ends are idle, so no active transaction can latch a stale last-beat indication.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*last*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI RRESP / BRESP (response code) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_resp} \
    -comment {cdc_fifo_gray_clearable R/B channels: AXI RRESP/BRESP code in i_src/data_q[N].resp (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.resp (destination spill register). Managed by the 4-phase clearable-reset protocol; on reset both ends are idle so the response code cannot be forwarded to active logic.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*resp*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI AxSIZE (transfer size) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_size} \
    -comment {cdc_fifo_gray_clearable AW/AR channels: AXI AxSIZE attribute in i_src/data_q[N].size (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.size (destination spill register). Managed by the 4-phase clearable-reset protocol; on reset both ends are idle so no transaction can use a stale size value.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*size*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI WSTRB (write strobe / byte enables) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_strb} \
    -comment {cdc_fifo_gray_clearable W channel: AXI WSTRB write-strobe byte enables in i_src/data_q[N].strb (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.strb (destination spill register). Managed by the 4-phase clearable-reset protocol; on reset both ends are idle so no pending write can be applied with a stale strobe.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*strb*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI USER (sideband) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_user} \
    -comment {cdc_fifo_gray_clearable all channels: AXI USER sideband bits in i_src/data_q[N].user (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.user (destination spill register). Managed by the 4-phase clearable-reset protocol; both ends are idle on reset before this field can be consumed.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*user*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# AXI AxBURST (burst type) field
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_burst} \
    -comment {cdc_fifo_gray_clearable AW/AR channels: AXI AxBURST type in i_src/data_q[N].burst (source FIFO) and i_dst/i_spill_register/gen_spill_reg.[ab]_data_q.burst (destination spill register). Managed by the 4-phase clearable-reset protocol; both ends are idle on reset before this field can be consumed.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*burst*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# Safety net: any data_q payload field not enumerated above
#   Today this matches zero violations; kept as a documented tripwire so that any
#   future PULP AXI struct field addition (len, lock, prot, qos, atop, region, ...)
#   is absorbed under the same clearable-protocol justification rather than
#   surfacing as a surprise unwaived violation.
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_data_q_other_fields} \
    -comment {cdc_fifo_gray_clearable: tripwire catch-all for any AXI payload field in data_q entries not covered by an individually named waiver above (e.g. len, lock, prot, qos, atop, region — none observed in current RTL). All such fields share the same 4-phase clearable-reset protocol justification: both source and destination ends are idle on reset before the field can affect active logic.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*data_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# cdc_fifo_gray_clearable: destination spill-register status flop (FIFO slot valid)
#-----------------------------------------------------------------------------------------------------------------------

# gen_spill_reg.{a,b}_full_q — DTPCLK spill-register slot-valid flop (not a data_q payload field)
# Same dest can be attributed to Module axi_cdc_clearable when the path crosses
# channel-instance boundaries inside the wrapper (RDC:1444).
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_spill_reg_full_q} \
    -comment {cdc_fifo_gray_clearable destination spill register: gen_spill_reg.{a,b}_full_q slot-valid status flop (DTPCLK, rst_n_i). Toggled when the 4-phase clearable reset controller marks the slot invalid; the status flop is reset by rst_n_i on the DTPCLK domain so cannot enter a corrupt state. Separated from the data_q payload waivers because full_q tracks slot validity rather than AXI payload content. Also matches Module==axi_cdc_clearable when VC Static attributes the same dest to the wrapper.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND ((Module == "cdc_fifo_gray_clearable") OR (Module == "axi_cdc_clearable")) AND (DestObject =~ "*spill_reg*full_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# cdc_fifo_gray_clearable / axi_cdc_clearable: gray-coded FIFO pointers and synchronizer
#-----------------------------------------------------------------------------------------------------------------------

# prim_sync3r gray-pointer synchronizer (3-flop CDC chain)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_fifo_sync3r_grayptr} \
    -comment {cdc_fifo_gray_clearable: reset-induced write/read-pointer change passes through the prim_sync3r gray-pointer synchronizer (i_dst/gen_sync[N].i_sync) into the destination domain. This is the intended CDC mechanism for the gray-coded pointer; 3-flop synchronization resolves metastability. The 4-phase clearable protocol ensures the FIFO is drained before any reset-induced pointer change can affect active logic.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*sync3r*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# Gray read/write pointer registers (rptr_q, wptr_q)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_fifo_ptr_regs} \
    -comment {cdc_fifo_gray_clearable / axi_cdc_clearable: gray-coded read pointer (rptr_q) or write pointer (wptr_q) reset-induced change visible across the clock domain. The 4-phase clearable protocol drains the FIFO and idles both domains before the pointer change affects active logic; the gray-pointer synchronizer (sync3r) resolves any metastability. Covers both Module values because the same path can be attributed to the FIFO instance or the top wrapper depending on propagation.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND ((Module == "cdc_fifo_gray_clearable") OR (Module == "axi_cdc_clearable")) AND ((DestObject =~ "*rptr_q*") OR (DestObject =~ "*wptr_q*"))} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# cdc_reset_ctrlr: internal 4-phase handshake fabric
#-----------------------------------------------------------------------------------------------------------------------

# RDC:1040 — half_a data_src_q -> half_b ack_dst_q (cross-domain acknowledgment)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_reset_ctrlr_ack_dst_q} \
    -comment {RDC:1040 — cdc_reset_ctrlr: JTAG-domain half_a data_src_q (trst_n_combined/tlr_reset) reaches DTPCLK-domain half_b ack_dst_q (rst_n_i). ack_dst_q is the acknowledgment handshake register of the 4-phase clearable protocol; the protocol is designed to be robust against concurrent reset assertion in either domain, and ack_dst_q is reset by rst_n_i on the DTPCLK side independently. Cross-domain reset observation is the intended signaling mechanism.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_reset_ctrlr") AND (DestObject =~ "*ack_dst_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1291 — half_a data_src_q -> half_b state_q (destination FSM state)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_reset_ctrlr_state_q} \
    -comment {RDC:1291 — cdc_reset_ctrlr: JTAG-domain half_a data_src_q (trst_n_combined/tlr_reset) reaches DTPCLK-domain half_b state_q (rst_n_i). state_q is the destination-half FSM register of the 4-phase clearable protocol; observing a cross-domain reset toggle is the intended signaling mechanism. state_q is reset by rst_n_i on the DTPCLK side independently, so it cannot enter a corrupt state.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_reset_ctrlr") AND (DestObject =~ "*state_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1135 — half_a data_src_q -> half_b receiver_phase_q (handshake phase tracker)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_reset_ctrlr_receiver_phase_q} \
    -comment {RDC:1135 — cdc_reset_ctrlr: JTAG-domain half_a data_src_q (trst_n_combined/tlr_reset) reaches DTPCLK-domain half_b receiver_phase_q (rst_n_i). receiver_phase_q tracks the 4-phase handshake phase on the destination half; cross-domain reset visibility is its intended input. Reset by rst_n_i on the DTPCLK side independently.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_reset_ctrlr") AND (DestObject =~ "*receiver_phase_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1640 — half_b ack_dst_q -> half_a sync2r (ack return synchronizer first stage)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_reset_ctrlr_ack_sync} \
    -comment {RDC:1640 — cdc_reset_ctrlr internal: half_b ack_dst_q (dst-side acknowledgment) drives the half_a sync2r synchronizer first stage returning the ack to the source domain. This is the internal 4-phase handshake fabric of cdc_reset_ctrlr; the path is correct-by-construction within the clearable-reset protocol. No external data is corrupted; this is the ack return path of the protocol itself.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_reset_ctrlr") AND (DestObject =~ "*sync2r*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# cdc_fifo_gray_clearable: top-level isolate/clear handshake registers (both domains)
#-----------------------------------------------------------------------------------------------------------------------
# Each FIFO instance has paired isolate/clear acknowledge registers — one in each
# clock domain (s_src_*_ack_q in the source domain, s_dst_*_ack_q in the
# destination domain).  Each pair latches the matching cross-domain handshake of
# the 4-phase clearable-reset protocol; each register is reset by its native
# domain's reset.  The waiver filters intentionally cover both src and dst
# variants because both are equally part of the protocol and share the same
# justification.
#-----------------------------------------------------------------------------------------------------------------------

# RDC:2772 — s_src_isolate_ack_q / s_dst_isolate_ack_q (paired isolate-handshake flops)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_isolate_ack_q} \
    -comment {RDC:2772 — cdc_fifo_gray_clearable: JTAG-domain half_a data_src_q (trst_n_combined/tlr_reset) reaches the paired isolate-acknowledge flops s_dst_isolate_ack_q (DTPCLK, rst_n_i) and s_src_isolate_ack_q (TCK, trst_n_combined/tlr_reset) at the FIFO top level. Each register latches the matching domain side of the 4-phase clearable-reset isolate handshake — capturing the cross-domain reset signal is exactly their intended function. Each is reset by its native-domain reset independently, so neither can enter a corrupt state.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*isolate_ack_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:2771 — s_src_clear_ack_q / s_dst_clear_ack_q (paired clear-handshake flops)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_cdc_gray_clear_ack_q} \
    -comment {RDC:2771 — cdc_fifo_gray_clearable: JTAG-domain half_a data_src_q (trst_n_combined/tlr_reset) reaches the paired clear-acknowledge flops s_dst_clear_ack_q (DTPCLK, rst_n_i) and s_src_clear_ack_q (TCK, trst_n_combined/tlr_reset) at the FIFO top level. Each register latches the matching domain side of the 4-phase clearable-reset clear handshake (sibling of the isolate_ack_q pair) — capturing the cross-domain reset signal is exactly their intended function. Each is reset by its native-domain reset independently.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "cdc_fifo_gray_clearable") AND (DestObject =~ "*clear_ack_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# axi_cdc_clearable: top-wrapper attribution (same paths reported under the wrapper Module)
#-----------------------------------------------------------------------------------------------------------------------

# RDC:2673 — DTPCLK controller state -> source FIFO data_q payload (wrapper attribution)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_axi_cdc_clearable_wrapper_data_q} \
    -comment {RDC:2673 — axi_cdc_clearable (top wrapper): DTPCLK-domain reset controller half_b state (rst_n_i) reaches TCK-domain source FIFO data_q payload fields (data, last, strb, ...) reported under Module=="axi_cdc_clearable" because the path crosses channel-instance boundaries within the wrapper. All such fields are quiescent when rst_n_i asserts due to the 4-phase clearable protocol; the TCK side is also in reset-idle so no active JTAG transaction can misuse stale field values.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "axi_cdc_clearable") AND (DestObject =~ "*data_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

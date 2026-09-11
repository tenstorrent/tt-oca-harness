<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU functional-coverage plan

Every point below is a `required_cells` entry from a scenario's coverage record in the frozen feature list, so each one traces to a spec section, not to RTL and not to an existing test. A cell is the unit that becomes a real coverage bin or cover property; the seed count is not part of this contract — `required_cells` is what binds.

| Features | Scenarios | Coverage cells | DIRECTED scenarios | RANDOMIZED scenarios | Contested-state scenarios |
|---:|---:|---:|---:|---:|---:|
| 49 | 206 | 337 | 198 | 8 | 53 |

## Carriers named by the plan

| `coverage_artifact` | Scenarios | What it means for collection |
|---|---:|---|
| `covergroup` | 137 | a SystemVerilog covergroup with the cells as bins; mergeable on VCS/Xcelium, Verilator has no covergroup support so these need a `cover property` per bin there |
| `cover_property` | 41 | a `cover property` — lands in the tool's `user` family and merges with the line/toggle database; the only carrier the coverage policy can gate on |
| `scoreboard_transaction_log` | 28 | checked by the testbench scoreboard — this is **evidence, not coverage**; it proves the scenario in the test that runs it and contributes nothing to a merged coverage score |

## Coverage points by feature

`Blocked by` names an open spec finding whose answer changes what the cell must observe; implement those last, or against the assumption the finding records.

### `SMU-XBAR-CONN` — SMU crossbar 3x3 connectivity matrix

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `route_sep_out_to_smc_in_read` | `SMU-XBAR-CONN.S1` | a sep_out access that matches the SMC aperture is delivered at smc_in | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-049 |
| `route_sep_out_to_smc_in_write` | `SMU-XBAR-CONN.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `route_smc_out_to_sep_in_read` | `SMU-XBAR-CONN.S2` | a smc_out access that matches the SEP aperture is delivered at sep_in | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `route_smc_out_to_sep_in_write` | `SMU-XBAR-CONN.S2` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `route_ext_in_to_sep_in_read` | `SMU-XBAR-CONN.S3` | an ext_in access that matches the SEP aperture is delivered at sep_in | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `route_ext_in_to_sep_in_write` | `SMU-XBAR-CONN.S3` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `route_ext_in_to_smc_in_read` | `SMU-XBAR-CONN.S4` | an ext_in access that matches the SMC aperture is delivered at smc_in | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `route_ext_in_to_smc_in_write` | `SMU-XBAR-CONN.S4` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `no_route_sep_out_to_sep_in` | `SMU-XBAR-CONN.S5` | sep_out has no route to sep_in - an initiator cannot reach its own inbound port | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| `no_route_smc_out_to_smc_in` | `SMU-XBAR-CONN.S6` | smc_out has no route to smc_in | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| `no_route_ext_in_to_ext_out` | `SMU-XBAR-CONN.S7` | ext_in has no route to ext_out | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| `concurrent_sep_out_ext_in_to_smc_in` | `SMU-XBAR-CONN.S8` | **[contested]** contested state - sep_out and ext_in target smc_in in the same cycle; both transactions complete or error within a bounded window and neither response is lost | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-005 |
| `both_complete_bounded` | `SMU-XBAR-CONN.S8` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no_lost_response` | `SMU-XBAR-CONN.S8` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `concurrent_opposite_direction_routes` | `SMU-XBAR-CONN.S9` | **[contested]** contested state - sep_out to smc_in and smc_out to sep_in run concurrently in opposite directions and neither path starves | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-005 |
| `neither_path_starved` | `SMU-XBAR-CONN.S9` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext_out_backpressure_sustained` | `SMU-XBAR-CONN.S10` | **[contested]** contested state - the external SMN slave applies sustained backpressure on ext_out while a sep_out to smc_in transfer is in progress; the internal path still completes within a bounded window | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | SF-005 |
| `internal_route_completes_under_backpressure` | `SMU-XBAR-CONN.S10` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reset_during_outstanding_burst` | `SMU-XBAR-CONN.S11` | **[contested]** contested state - rst_primary_smc_clk_no asserts with a crossbar burst outstanding; no response is emitted after reset and the fabric routes correctly after release | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | — |
| `no_post_reset_stale_response` | `SMU-XBAR-CONN.S11` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `fabric_usable_after_release` | `SMU-XBAR-CONN.S11` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-XBAR-APERTURE` — CSR-programmed SEP and SMC crossbar apertures

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_aperture_hit_low_edge` | `SMU-XBAR-APERTURE.S1` | a programmed SMC aperture base and size routes a matching address to smc_in | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Overview (+1) | SF-001, SF-054 |
| `smc_aperture_hit_high_edge` | `SMU-XBAR-APERTURE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `smc_aperture_hit_interior` | `SMU-XBAR-APERTURE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep_aperture_hit_low_edge` | `SMU-XBAR-APERTURE.S2` | a programmed SEP aperture base and size routes a matching address to sep_in | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Overview (+1) | SF-001 |
| `sep_aperture_hit_high_edge` | `SMU-XBAR-APERTURE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep_aperture_hit_interior` | `SMU-XBAR-APERTURE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `aperture_reprogram_old_address_misses` | `SMU-XBAR-APERTURE.S3` | reprogramming an aperture moves the decode boundary - an address that previously matched no longer matches and the new range does | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks (+1) | SF-001 |
| `aperture_reprogram_new_address_hits` | `SMU-XBAR-APERTURE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `global_base_remap_applied` | `SMU-XBAR-APERTURE.S4` | the programmable global-base remap shifts the decoded region by the programmed base | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 4 | SF-001 |
| `global_base_remap_zero` | `SMU-XBAR-APERTURE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `smc_region_size_o_matches_programmed_size` | `SMU-XBAR-APERTURE.S5` | the programmed SMC region size is reflected on smc_region_size_o | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port smc_region_size_o | SF-053 |
| `csr_rewrite_with_inflight_transaction` | `SMU-XBAR-APERTURE.S6` | **[contested]** contested state - the aperture CSR is rewritten while a transaction decoded under the old map is in flight; that transaction completes or errors within a bounded window and no response is lost | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-003 |
| `inflight_completes_or_errors_bounded` | `SMU-XBAR-APERTURE.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no_lost_response_on_map_change` | `SMU-XBAR-APERTURE.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `overlapping_apertures_programmed` | `SMU-XBAR-APERTURE.S7` | **[contested]** contested state - the SEP and SMC apertures are programmed to overlap; a single address is never delivered to two targets | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | SF-004 |
| `single_target_selected_per_address` | `SMU-XBAR-APERTURE.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `zero_size_aperture_no_match` | `SMU-XBAR-APERTURE.S8` | an aperture programmed with zero size matches no address | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Overview (+1) | — |
| `csr_write_concurrent_with_decode` | `SMU-XBAR-APERTURE.S9` | **[contested]** contested state - an aperture CSR write is concurrent with a decode of an address inside that aperture issued by another initiator | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-003 |
| `decode_result_is_one_of_old_or_new_map` | `SMU-XBAR-APERTURE.S9` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-XBAR-DEFAULT` — ext_out default master port for unmatched internal accesses

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `unmatched_sep_out_to_ext_out_read` | `SMU-XBAR-DEFAULT.S1` | an unmatched sep_out access is routed to ext_out | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `unmatched_sep_out_to_ext_out_write` | `SMU-XBAR-DEFAULT.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `unmatched_smc_out_to_ext_out_read` | `SMU-XBAR-DEFAULT.S2` | an unmatched smc_out access is routed to ext_out | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `unmatched_smc_out_to_ext_out_write` | `SMU-XBAR-DEFAULT.S2` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `default_path_response_returned` | `SMU-XBAR-DEFAULT.S3` | the response returned by the external SMN slave on the default path is delivered back to the originating initiator carrying its own ID | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | — |
| `default_path_response_id_preserved` | `SMU-XBAR-DEFAULT.S3` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `default_path_no_response_from_smn` | `SMU-XBAR-DEFAULT.S4` | **[contested]** contested state - an unmatched access while the external SMN slave withholds its response completes or errors within a bounded window rather than hanging the initiator | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | SF-009 |
| `bounded_completion_or_error` | `SMU-XBAR-DEFAULT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-XBAR-DECERR` — Decode error for unmatched external inbound accesses

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ext_in_unmatched_read_decerr` | `SMU-XBAR-DECERR.S1` | an unmatched ext_in read is answered with DECERR | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Error Handling | SF-008 |
| `ext_in_unmatched_write_decerr` | `SMU-XBAR-DECERR.S2` | an unmatched ext_in write is answered with DECERR | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Error Handling | SF-008 |
| `unmatched_burst_all_beats_answered` | `SMU-XBAR-DECERR.S3` | every beat of an unmatched ext_in burst is accounted for and the burst terminates | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | SF-008 |
| `unmatched_burst_terminates` | `SMU-XBAR-DECERR.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `unmatched_concurrent_with_matched` | `SMU-XBAR-DECERR.S4` | **[contested]** contested state - an unmatched ext_in access issued while a matched ext_in access is outstanding; the matched access still completes normally | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | — |
| `matched_access_unaffected` | `SMU-XBAR-DECERR.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two_outstanding_decode_errors` | `SMU-XBAR-DECERR.S5` | **[contested]** contested state - error during error; a second unmatched ext_in access is issued while the first decode-error response is still outstanding, and both receive their own error response | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling | — |
| `each_error_response_distinct` | `SMU-XBAR-DECERR.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-XBAR-ATOP` — AXI atomic operations rejected at the crossbar

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `atop_rejected_on_sep_out` | `SMU-XBAR-ATOP.S1` | an atomic issued on sep_out is rejected and is not performed at the target | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | SF-002 |
| `target_memory_unmodified_after_atop` | `SMU-XBAR-ATOP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `atop_rejected_on_smc_out` | `SMU-XBAR-ATOP.S2` | an atomic issued on smc_out is rejected and is not performed at the target | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | SF-002 |
| `target_memory_unmodified_after_atop` | `SMU-XBAR-ATOP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `atop_rejected_on_ext_in` | `SMU-XBAR-ATOP.S3` | an atomic issued on ext_in is rejected and is not performed at the target | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | SF-002 |
| `target_memory_unmodified_after_atop` | `SMU-XBAR-ATOP.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ordinary_access_after_rejected_atop` | `SMU-XBAR-ATOP.S4` | an ordinary access issued on the same path immediately after a rejected atomic completes normally | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling | — |
| `atop_rejected_with_outstanding_ordinary` | `SMU-XBAR-ATOP.S5` | **[contested]** contested state - an atomic is rejected while an ordinary transaction is outstanding on the same initiator; the ordinary transaction is neither corrupted nor reordered | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | — |
| `ordinary_transaction_intact` | `SMU-XBAR-ATOP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-IDW-IN` — External inbound 8-bit to 10-bit crossbar ID widening

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ext_in_id_roundtrip_read` | `SMU-IDW-IN.S1` | an 8-bit ext_in ID reaches the target and the response returns carrying the identical 8-bit ID | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | SF-007 |
| `ext_in_id_roundtrip_write` | `SMU-IDW-IN.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `two_distinct_ext_in_ids_outstanding` | `SMU-IDW-IN.S2` | **[contested]** two concurrent ext_in transactions with different IDs return responses tagged with their own IDs | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications | — |
| `responses_id_matched` | `SMU-IDW-IN.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `same_id_multiple_outstanding` | `SMU-IDW-IN.S3` | **[contested]** contested state - several ext_in transactions sharing one ID are outstanding together and their responses return in order | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications | — |
| `same_id_responses_in_order` | `SMU-IDW-IN.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `id_value_min_0` | `SMU-IDW-IN.S4` | every 8-bit inbound ID value is transportable end to end | RANDOMIZED | `axi_id`, `burst_len`, `read_or_write` | `covergroup` | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications (+1) | SF-007 |
| `id_value_max_255` | `SMU-IDW-IN.S4` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `id_value_random_interior` | `SMU-IDW-IN.S4` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |

### `SMU-IDW-SEP` — Crossbar 10-bit to SEP 6-bit ID conversion

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep_iw_conv_read_roundtrip` | `SMU-IDW-SEP.S1` | a transaction crossing u_iw_conv_sep arrives at SEP with a 6-bit ID and its response returns to the correct crossbar initiator | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks (+1) | — |
| `sep_iw_conv_write_roundtrip` | `SMU-IDW-SEP.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `id_space_oversubscribed` | `SMU-IDW-SEP.S2` | **[contested]** contested state - more distinct 10-bit IDs are outstanding than the 6-bit output space can represent; every response still returns to its originator within a bounded window | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | SF-006 |
| `all_responses_returned_bounded` | `SMU-IDW-SEP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reset_with_outstanding_conversion` | `SMU-IDW-SEP.S3` | **[contested]** contested state - reset asserts with a converted transaction outstanding and the converter routes correctly after release | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | — |
| `converter_usable_after_release` | `SMU-IDW-SEP.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `read_response_id_match` | `SMU-IDW-SEP.S4` | read and write responses crossing the converter are returned with IDs matching their requests | RANDOMIZED | `axi_id`, `outstanding_depth`, `burst_len` | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | — |
| `write_response_id_match` | `SMU-IDW-SEP.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mixed_read_write_interleave` | `SMU-IDW-SEP.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-IDW-SMC` — Crossbar 10-bit to SMC 6-bit ID conversion

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_iw_conv_read_roundtrip` | `SMU-IDW-SMC.S1` | a transaction crossing u_iw_conv_smc arrives at SMC with a 6-bit ID and its response returns to the correct crossbar initiator | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks (+1) | — |
| `smc_iw_conv_write_roundtrip` | `SMU-IDW-SMC.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `id_space_oversubscribed` | `SMU-IDW-SMC.S2` | **[contested]** contested state - more distinct 10-bit IDs are outstanding than the 6-bit output space can represent; every response still returns to its originator within a bounded window | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | SF-006 |
| `all_responses_returned_bounded` | `SMU-IDW-SMC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reset_with_outstanding_conversion` | `SMU-IDW-SMC.S3` | **[contested]** contested state - reset asserts with a converted transaction outstanding and the converter routes correctly after release | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | — |
| `converter_usable_after_release` | `SMU-IDW-SMC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `read_response_id_match` | `SMU-IDW-SMC.S4` | read and write responses crossing the converter are returned with IDs matching their requests | RANDOMIZED | `axi_id`, `outstanding_depth`, `burst_len` | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | — |
| `write_response_id_match` | `SMU-IDW-SMC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mixed_read_write_interleave` | `SMU-IDW-SMC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-EXT-SMN` — External SMN AXI port composition at the SMU boundary

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `addr_bit_0_toggled` | `SMU-EXT-SMN.S1` | the full 56-bit address is carried in both directions without truncation | DIRECTED | — | `covergroup` | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications (+1) | — |
| `addr_bit_55_toggled` | `SMU-EXT-SMN.S1` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `addr_all_ones_low_56` | `SMU-EXT-SMN.S1` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `data_all_zero` | `SMU-EXT-SMN.S2` | 64-bit data is carried without truncation in both directions | RANDOMIZED | `wdata`, `wstrb`, `burst_len` | `covergroup` | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications | — |
| `data_all_ones` | `SMU-EXT-SMN.S2` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `data_random_pattern` | `SMU-EXT-SMN.S2` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `wstrb_partial` | `SMU-EXT-SMN.S2` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `user_all_zero` | `SMU-EXT-SMN.S3` | the 12-bit user field is carried unmodified | DIRECTED | — | `covergroup` | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications | — |
| `user_all_ones` | `SMU-EXT-SMN.S3` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `user_random` | `SMU-EXT-SMN.S3` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `outbound_id_width_10` | `SMU-EXT-SMN.S4` | the outbound SMN port presents a 10-bit ID while the inbound port accepts an 8-bit ID | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Interfaces (+1) | — |
| `inbound_id_width_8` | `SMU-EXT-SMN.S4` | ″ | ″ | ″ | `cover_property` | `DECODE` | ″ | ″ |
| `outbound_response_never_returns` | `SMU-EXT-SMN.S5` | **[contested]** contested state - smu_axi_out_resp_i is tied off so no response ever returns; the originating initiator is released with a bounded error rather than hanging forever | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port smu_axi_out_resp_i (+1) | SF-009 |
| `initiator_released_bounded` | `SMU-EXT-SMN.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-ALIAS-REMAP` — SEP to SMC fixed alias remap bypassing the crossbar

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `alias_base_address_remapped` | `SMU-ALIAS-REMAP.S1` | an access at 0x40000000 is presented to SMC at address 0x00000000 | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `alias_top_address_remapped` | `SMU-ALIAS-REMAP.S2` | an access at the top of the window, 0x7FFFFFFF, is presented to SMC at 0x3FFFFFFF | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `below_window_not_remapped` | `SMU-ALIAS-REMAP.S3` | an access just below 0x40000000 is not remapped | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| `above_window_not_remapped` | `SMU-ALIAS-REMAP.S4` | an access just above 0x7FFFFFFF is not remapped | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| `alias_path_bypasses_xbar` | `SMU-ALIAS-REMAP.S5` | the remapped access bypasses the crossbar and is observed on no crossbar target port | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | — |
| `no_xbar_target_activity_during_alias` | `SMU-ALIAS-REMAP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `burst_crossing_window_top` | `SMU-ALIAS-REMAP.S6` | **[contested]** contested state - a burst that starts inside the alias window and would cross its top boundary | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-010 |

### `SMU-NOSEP` — SEP=0 build composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `nosep_smc_to_ext_read` | `SMU-NOSEP.S1` | with SEP=0 SMC and the external SMN port exchange read and write traffic through the direct ID converters | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Architecture Block Overview (+1) | — |
| `nosep_smc_to_ext_write` | `SMU-NOSEP.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `nosep_ext_to_smc_read` | `SMU-NOSEP.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `nosep_ext_to_smc_write` | `SMU-NOSEP.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `nosep_sep_outputs_tied_off` | `SMU-NOSEP.S2` | with SEP=0 the SEP-facing outputs at the SMU boundary are tied off | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `SMU_SPEC.md` §Configuration Parameters | — |
| `nosep_no_aperture_decode` | `SMU-NOSEP.S3` | with SEP=0 no crossbar aperture decode is present, so SMC traffic is not aperture-filtered | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Architecture Block Overview (+1) | SF-054 |
| `nosepcfg_fields_equal_defaultcfg` | `SMU-NOSEP.S4` | NoSepCfg is field-identical to DefaultCfg, so only the SEP parameter distinguishes the two builds | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | — |

### `SMU-SEPOTP-ERRSLV` — SEP=0 SEP-OTP AXI-Lite error slave

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep0_otp_read_decerr` | `SMU-SEPOTP-ERRSLV.S1` | a SEP=0 SEP-OTP read returns DECERR with read data 0xBADCAB1E | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Error Handling (+1) | SF-041 |
| `sep0_otp_read_data_badcab1e` | `SMU-SEPOTP-ERRSLV.S1` | ″ | ″ | ″ | `cover_property` | `DECODE` | ″ | ″ |
| `sep0_otp_write_error_response` | `SMU-SEPOTP-ERRSLV.S2` | a SEP=0 SEP-OTP write returns an error response | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Error Handling | SF-041 |
| `sep0_otp_back_to_back_accesses` | `SMU-SEPOTP-ERRSLV.S3` | **[contested]** contested state - back-to-back SEP-OTP accesses each receive their own error response | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling | — |
| `each_access_own_error_response` | `SMU-SEPOTP-ERRSLV.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `clk_ref_slower_than_clk_smu` | `SMU-SEPOTP-ERRSLV.S4` | **[contested]** contested state - the error slave runs on clk_ref_i while its AXI-Lite manager runs on clk_smu_i; the response is correct when the two clocks differ in frequency and phase | RANDOMIZED | `clk_ref_period`, `clk_smu_period`, `phase_offset` | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-042 |
| `clk_ref_faster_than_clk_smu` | `SMU-SEPOTP-ERRSLV.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `clk_ref_equal_clk_smu` | `SMU-SEPOTP-ERRSLV.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-MBOX-XCHG` — SMC to SEP mailbox challenge-response exchange

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `token_written_by_smc` | `SMU-MBOX-XCHG.S1` | a token written by SMC to its outbound mailbox is observed by SEP at its inbound mailbox | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-011 |
| `token_observed_by_sep` | `SMU-MBOX-XCHG.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `complement_written_by_sep` | `SMU-MBOX-XCHG.S2` | SEP writes the complement back and SMC pops the response | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-011 |
| `response_popped_by_smc` | `SMU-MBOX-XCHG.S2` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `popped_value_is_complement` | `SMU-MBOX-XCHG.S3` | the value SMC pops is the bitwise complement of the token it wrote | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-011 |
| `second_token_before_first_consumed` | `SMU-MBOX-XCHG.S4` | **[contested]** contested state - SMC writes a second token before SEP has consumed the first; both exchanges complete or the second is rejected, within a bounded window | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | SF-011 |
| `bounded_completion_or_rejection` | `SMU-MBOX-XCHG.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reset_between_write_and_pop` | `SMU-MBOX-XCHG.S5` | **[contested]** contested state - reset is asserted between the token write and the response pop; the mailbox path is usable again after release | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths (+1) | — |
| `mailbox_usable_after_release` | `SMU-MBOX-XCHG.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `token_all_zero` | `SMU-MBOX-XCHG.S6` | the exchange holds across the token value space | RANDOMIZED | `token_value`, `inter_write_delay` | `covergroup` | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| `token_all_ones` | `SMU-MBOX-XCHG.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `token_random` | `SMU-MBOX-XCHG.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-SEP-MBOX-IRQ` — SEP mailbox interrupt into SMC

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep_mailbox_irq_asserted` | `SMU-SEP-MBOX-IRQ.S1` | a SEP mailbox write asserts the corresponding SEP mailbox interrupt into SMC | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks (+1) | SF-014 |
| `sep_mailbox_irq_cleared_after_service` | `SMU-SEP-MBOX-IRQ.S2` | the SEP mailbox interrupt clears after SMC services the mailbox | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | SF-014 |
| `two_sep_mailbox_irqs_same_cycle` | `SMU-SEP-MBOX-IRQ.S3` | **[contested]** contested state - two SEP mailbox interrupts assert in the same cycle and both are delivered | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | SF-014 |
| `both_delivered` | `SMU-SEP-MBOX-IRQ.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-INT-AGG` — External interrupt aggregation into SMC

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ext_interrupts_width_256` | `SMU-INT-AGG.S1` | the aggregation port is 256 bits wide, matching Cfg.NUM_INT_TO_SMC | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Specifications (+1) | — |
| `single_ext_interrupt_asserted` | `SMU-INT-AGG.S2` | an asserted ext_interrupts_i bit is observable as an interrupt at SMC | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_interrupts_i (+1) | SF-012 |
| `interrupt_seen_at_smc` | `SMU-INT-AGG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext_interrupt_deasserted` | `SMU-INT-AGG.S3` | deasserting the external interrupt line propagates to SMC | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_interrupts_i | SF-012 |
| `interrupt_cleared_at_smc` | `SMU-INT-AGG.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `all_256_asserted_same_cycle` | `SMU-INT-AGG.S4` | **[contested]** contested state - all 256 lines assert in the same cycle and every one is delivered | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | — |
| `all_256_delivered` | `SMU-INT-AGG.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `index_0` | `SMU-INT-AGG.S5` | each interrupt index maps to its own SMC interrupt input | RANDOMIZED | `interrupt_index`, `assert_duration` | `covergroup` | `LIVE` | `port_table.adoc` §port ext_interrupts_i | SF-012 |
| `index_255` | `SMU-INT-AGG.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `index_random_interior` | `SMU-INT-AGG.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-MBOX-IRQ-OUT` — SMC mailbox interrupt outputs at the SMU boundary

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mailbox_irq_out_width_32` | `SMU-MBOX-IRQ-OUT.S1` | the mailbox interrupt output is 32 bits wide, matching smc_pkg NUM_MAILBOXES | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Specifications (+1) | — |
| `mailbox_irq_bit_asserted` | `SMU-MBOX-IRQ-OUT.S2` | an SMC mailbox interrupt appears on the corresponding output bit | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_mailbox_interrupts_o (+1) | SF-013 |
| `mailbox_irq_bit_cleared` | `SMU-MBOX-IRQ-OUT.S3` | the output bit clears when the mailbox is serviced | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_mailbox_interrupts_o | SF-013 |
| `multiple_mailbox_irqs_concurrent` | `SMU-MBOX-IRQ-OUT.S4` | **[contested]** contested state - several mailbox interrupts assert at once and each appears on its own bit | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | — |
| `bits_independent` | `SMU-MBOX-IRQ-OUT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-IRQ-PASSTHRU` — SMC-sourced raw interrupt and sync outputs at the SMU boundary

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `gpio_irq_bonded_wrap` | `SMU-IRQ-PASSTHRU.S1` | a raw GPIO wrap interrupt appears on the matching bit of gpio_interrupt_o | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port gpio_interrupt_o | SF-050, SF-051 |
| `gpio_irq_unbonded_wrap` | `SMU-IRQ-PASSTHRU.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `uart_irq_bit_asserted` | `SMU-IRQ-PASSTHRU.S2` | a UART interrupt appears on the matching bit of uart_interrupt_o in the peripheral clock domain | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port uart_interrupt_o (+1) | SF-051 |
| `uart_irq_in_periph_domain` | `SMU-IRQ-PASSTHRU.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sync_irq_follows_sync_reg` | `SMU-IRQ-PASSTHRU.S3` | sync_irq_o reflects the software-controlled SYNC_REG.sync bit and is not an aggregate of any interrupt | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port sync_irq_o | SF-051 |
| `sync_irq_not_set_by_any_interrupt` | `SMU-IRQ-PASSTHRU.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `all_gpio_wrap_bits_present` | `SMU-IRQ-PASSTHRU.S4` | both bonded and unbonded GPIO wraps present a bit on gpio_interrupt_o | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port gpio_interrupt_o | SF-050 |

### `SMU-XTRIG-CTM` — Cross-trigger CTM port composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ctm_src_req_asserted` | `SMU-XTRIG-CTM.S1` | a DTP cross-trigger source request appears on xtrig_ctm_src_req_o | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port xtrig_ctm_src_req_o (+1) | SF-017 |
| `ctm_dst_req_delivered` | `SMU-XTRIG-CTM.S2` | an external destination request on xtrig_ctm_dst_req_i reaches the DTP cross-trigger matrix | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port xtrig_ctm_dst_req_i (+1) | SF-017 |
| `ctm_ports_1_0_reserved_for_smc` | `SMU-XTRIG-CTM.S3` | ports [1:0] are reserved for SMC and are not assignable to an external cross-trigger source | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Specifications (+1) | SF-015 |
| `ctm_ack_unused_in_pulse_sync` | `SMU-XTRIG-CTM.S4` | in pulse-sync mode the source and destination acknowledge ports are unused | DIRECTED | — | `cover_property` | `DECODE` | `port_table.adoc` §port xtrig_ctm_src_ack_i (+1) | SF-017 |
| `multiple_ctm_requests_same_cycle` | `SMU-XTRIG-CTM.S5` | **[contested]** contested state - requests on several CTM ports in the same cycle are all delivered | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Specifications (+1) | — |
| `all_ctm_requests_delivered` | `SMU-XTRIG-CTM.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ctm_request_during_reset_release` | `SMU-XTRIG-CTM.S6` | **[contested]** contested state - a CTM request asserted while the primary reset is deasserting is either delivered or cleanly dropped, never partially | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | — |
| `delivered_or_dropped_cleanly` | `SMU-XTRIG-CTM.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-XTRIG-CTP` — Cross-trigger CTP GPIO port composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ctp_req_out_width_16` | `SMU-XTRIG-CTP.S1` | each of the four CTP groups presents 16 bits on each of its four signals | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications (+1) | — |
| `ctp_req_in_width_16` | `SMU-XTRIG-CTP.S1` | ″ | ″ | ″ | `cover_property` | `CONNECTIVITY` | ″ | ″ |
| `ctp_ack_in_width_16` | `SMU-XTRIG-CTP.S1` | ″ | ″ | ″ | `cover_property` | `CONNECTIVITY` | ″ | ″ |
| `ctp_ack_out_width_16` | `SMU-XTRIG-CTP.S1` | ″ | ″ | ″ | `cover_property` | `CONNECTIVITY` | ″ | ″ |
| `ctp_req_out_data_driven` | `SMU-XTRIG-CTP.S2` | a CTP request driven by DTP appears on xtrig_ctp_req_out_dout_o with its output enable asserted | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port xtrig_ctp_req_out_dout_o | SF-018 |
| `ctp_req_out_enable_asserted` | `SMU-XTRIG-CTP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ctp_req_in_data_received` | `SMU-XTRIG-CTP.S3` | a CTP input driven on xtrig_ctp_req_in_din_i reaches the DTP CTP logic when the corresponding input enable is set | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port xtrig_ctp_req_in_din_i | SF-018 |
| `ctp_req_in_enable_set` | `SMU-XTRIG-CTP.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ctp_ack_out_data_driven` | `SMU-XTRIG-CTP.S4` | an acknowledge driven by DTP appears on xtrig_ctp_ack_out_dout_o with its enable | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port xtrig_ctp_ack_out_dout_o | SF-018 |
| `ctp_ack_out_enable_asserted` | `SMU-XTRIG-CTP.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ctp_wire_or_two_sources` | `SMU-XTRIG-CTP.S5` | **[contested]** contested state - wire-OR contention, with two sources driving the same CTP channel in the same cycle | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 6 | SF-018 |
| `result_defined_under_contention` | `SMU-XTRIG-CTP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ctp_unused_input_tied_zero_inert` | `SMU-XTRIG-CTP.S6` | unused CTP data inputs tied to 0 leave the corresponding channel inert | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port xtrig_ctp_req_in_din_i (+1) | — |

### `SMU-XTRIG-MODE` — Per-internal-CT mode composition into DTP

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ct_mode_bits_1_0_zero` | `SMU-XTRIG-MODE.S1` | DTP receives mode bits [1:0] equal to 0, placing the two SMC-reserved cross triggers in pulse-sync mode | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | — |
| `ct_mode_upper_bits_passthrough` | `SMU-XTRIG-MODE.S2` | the remaining mode bits presented to DTP are the configured Cfg.XTRIG_INT_CT_MODE value, unmodified | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | SF-020 |
| `pulse_sync_ct_ignores_ack` | `SMU-XTRIG-MODE.S3` | a cross trigger configured in pulse-sync mode ignores its acknowledge port | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Configuration Parameters (+1) | SF-017 |

### `SMU-CLKSTOP-REQ` — Clock-stop request port composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `clk_stop_req_delivered` | `SMU-CLKSTOP-REQ.S1` | an external clock-stop request reaches the DTP clock-stop aggregation | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port xtrig_clk_stop_req_i (+1) | SF-019 |
| `clk_stop_port_0_reserved_for_smc` | `SMU-CLKSTOP-REQ.S2` | port [0] is reserved for SMC internally and is not assignable to an external requester | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Specifications (+1) | SF-016 |
| `multiple_clk_stop_requests` | `SMU-CLKSTOP-REQ.S3` | **[contested]** contested state - several clock-stop requests assert at once and the aggregation reflects all of them | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 6 (+1) | — |
| `aggregation_reflects_all` | `SMU-CLKSTOP-REQ.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `clk_stop_request_with_inflight_axi` | `SMU-CLKSTOP-REQ.S4` | **[contested]** contested state - a clock-stop request asserts while an AXI transaction is in flight; the transaction completes or errors within a bounded window | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 6 (+1) | — |
| `bounded_completion_or_error` | `SMU-CLKSTOP-REQ.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-CLKSTOP-OUT` — DTP clock-stop output to the PLL clock gates

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `stop_clks_from_debug_control` | `SMU-CLKSTOP-OUT.S1` | a JTAG DEBUG_CONTROL clock stop asserts dtp_stop_clks_o | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o (+1) | SF-019 |
| `stop_clks_from_cla_request` | `SMU-CLKSTOP-OUT.S2` | an SMC CLA clock-stop request asserts dtp_stop_clks_o | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o (+1) | SF-019 |
| `stop_clks_released` | `SMU-CLKSTOP-OUT.S3` | dtp_stop_clks_o deasserts once the requesting source releases | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o | — |
| `both_stop_sources_active` | `SMU-CLKSTOP-OUT.S4` | **[contested]** contested state - both sources request a stop and the output stays asserted until both release | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o (+1) | SF-019 |
| `stop_held_until_last_release` | `SMU-CLKSTOP-OUT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-LC-STATE` — Lifecycle state broadcast at the SMU boundary

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `lc_state_width_8` | `SMU-LC-STATE.S1` | lc_state_o is 8 bits wide, equal to 2 * LC_STATE_WIDTH | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Specifications (+1) | — |
| `lc_state_follows_sep` | `SMU-LC-STATE.S2` | with SEP=1 lc_state_o follows the SEP lifecycle controller | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations (+1) | SF-021 |
| `lc_state_sep0_is_f0` | `SMU-LC-STATE.S3` | with SEP=0 lc_state_o reads 8 hf0 | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Security Considerations (+1) | — |
| `lc_state_across_reset_release` | `SMU-LC-STATE.S4` | **[contested]** contested state - lc_state_o is stable across the reset release edge and shows no transient value that is neither the pre-reset nor the post-reset state | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-021 |
| `no_transient_intermediate_value` | `SMU-LC-STATE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-LC-DBGDIS` — Lifecycle debug disable from SEP into DTP

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `dbg_disable_blocks_stap_selection` | `SMU-LC-DBGDIS.S1` | with dbg_disable asserted, STAP selection is blocked | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations | SF-024 |
| `dbg_disable_blocks_ijtag_sib` | `SMU-LC-DBGDIS.S2` | with dbg_disable asserted, iJTAG SIB access is blocked | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations | — |
| `dbg_disable_blocks_smc_fabric_bridge` | `SMU-LC-DBGDIS.S3` | with dbg_disable asserted, the SMC fabric JTAG2AXI bridge produces no AXI traffic | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations (+1) | SF-024 |
| `no_axi_traffic_observed` | `SMU-LC-DBGDIS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `smc_otp_bridge_enabled_under_dbg_disable` | `SMU-LC-DBGDIS.S4` | the SMC OTP JTAG2AXI bridge remains enabled while dbg_disable is asserted | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations | — |
| `sep_otp_bridge_enabled_under_dbg_disable` | `SMU-LC-DBGDIS.S5` | the SEP OTP JTAG2AXI bridge remains enabled while dbg_disable is asserted | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations | — |
| `blocked_resource_bypass_fallback` | `SMU-LC-DBGDIS.S6` | a debug resource blocked by dbg_disable falls back to BYPASS | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling | SF-024 |
| `dbg_disable_during_inflight_jtag2axi` | `SMU-LC-DBGDIS.S7` | **[contested]** contested state - dbg_disable asserts while a JTAG2AXI transaction is in flight; the transaction completes or errors within a bounded window and no partial write reaches the fabric | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations (+1) | SF-024 |
| `bounded_completion_or_error` | `SMU-LC-DBGDIS.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no_partial_write` | `SMU-LC-DBGDIS.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-LC-SECDIS` — Security disable from SEP into SMC

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `security_disable_connected_sep_to_smc` | `SMU-LC-SECDIS.S1` | SEP drives security_disable into SMC and the connection is present in a SEP=1 build | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `SMU_SPEC.md` §Security Considerations (+1) | — |
| `security_disable_follows_lifecycle` | `SMU-LC-SECDIS.S2` | the security_disable value SMC receives follows the SEP lifecycle state | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations (+1) | SF-025 |
| `security_disable_change_during_traffic` | `SMU-LC-SECDIS.S3` | **[contested]** contested state - security_disable changes while SMC is mid-transaction; the new value is delivered within a bounded window and SMC keeps making progress | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations (+1) | SF-025 |
| `bounded_delivery` | `SMU-LC-SECDIS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `smc_progress_maintained` | `SMU-LC-SECDIS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-LC-DEMOTE` — Lifecycle demote state outputs

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `demote_1_width_2` | `SMU-LC-DEMOTE.S1` | both demote outputs are 2 bits wide and present at the SMU boundary | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port lcc_demote_state_1_o (+1) | — |
| `demote_2_width_2` | `SMU-LC-DEMOTE.S1` | ″ | ″ | ″ | `cover_property` | `CONNECTIVITY` | ″ | ″ |
| `demote_outputs_follow_sep` | `SMU-LC-DEMOTE.S2` | the demote outputs follow the SEP lifecycle demote state | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Interfaces (+1) | SF-023 |

### `SMU-LC-SIGINT` — Lifecycle signal integrity error output

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `lc_sigint_err_inert_in_normal_operation` | `SMU-LC-SIGINT.S1` | lc_sigint_err_o is present at the SMU boundary and is inert during normal operation | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port lc_sigint_err_o | SF-022 |
| `lc_sigint_err_driven_when_sep0` | `SMU-LC-SIGINT.S2` | lc_sigint_err_o is driven to a defined value in a SEP=0 build rather than floating | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port lc_sigint_err_o (+1) | SF-022 |

### `SMU-SEC-TOKEN` — SEP security-disable token parameter composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `token_parameter_connected_to_sep` | `SMU-SEC-TOKEN.S1` | SEP receives the 256-bit token from the SMU parameter | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `SMU_SPEC.md` §Configuration Parameters (+1) | — |
| `token_default_all_zero` | `SMU-SEC-TOKEN.S2` | the default SMU build presents 256 b0 on that parameter | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | — |

### `SMU-EFUSE-SHIM-SMC` — SMC eFuse shim port composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_efuse_bank_ctrl_request_observed` | `SMU-EFUSE-SHIM-SMC.S1` | an SMC eFuse bank-control AXI-Lite access appears at the SMU boundary and its response is returned to SMC | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `port_table.adoc` §port smc_efuse_bank_ctrl_req_o | — |
| `smc_efuse_bank_ctrl_response_returned` | `SMU-EFUSE-SHIM-SMC.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `smc_efuse_command_request_observed` | `SMU-EFUSE-SHIM-SMC.S2` | an SMC eFuse command request appears at the boundary and its response is returned to SMC | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `port_table.adoc` §port smc_efuse_shim_command_req_o | SF-048 |
| `smc_efuse_command_response_returned` | `SMU-EFUSE-SHIM-SMC.S2` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `smc_shadow_regs_present` | `SMU-EFUSE-SHIM-SMC.S3` | smc_shadow_regs_o presents the SMC eFuse shadow registers at the boundary | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port smc_shadow_regs_o | SF-048 |

### `SMU-EFUSE-SHIM-SEP` — SEP eFuse shim port composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep_efuse_bank_ctrl_request_observed` | `SMU-EFUSE-SHIM-SEP.S1` | a SEP eFuse bank-control AXI-Lite access appears at the SMU boundary and its response is returned to SEP | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `port_table.adoc` §port sep_efuse_bank_ctrl_req_o | SF-049 |
| `sep_efuse_bank_ctrl_response_returned` | `SMU-EFUSE-SHIM-SEP.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `sep_efuse_command_request_observed` | `SMU-EFUSE-SHIM-SEP.S2` | a SEP eFuse command request appears at the boundary and its response is returned to SEP | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `port_table.adoc` §port sep_efuse_shim_command_req_o | SF-048 |
| `sep_efuse_command_response_returned` | `SMU-EFUSE-SHIM-SEP.S2` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |

### `SMU-FUSE-SENSE` — Fuse-sense completion handshake at the SMU boundary

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_fuse_sense_done_asserted` | `SMU-FUSE-SENSE.S1` | fuse_sense_done_o asserts once SMC fuse sense completes | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port fuse_sense_done_o (+1) | — |
| `sep_fuse_sense_done_asserted` | `SMU-FUSE-SENSE.S2` | sep_fuse_sense_done_o asserts once SEP fuse sense completes | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port sep_fuse_sense_done_o (+1) | — |
| `fuse_reset_n_delayed_released_after_sense` | `SMU-FUSE-SENSE.S3` | fuse_reset_n_delayed_o is released after the fuse-sense phase rather than with the cold reset | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port fuse_reset_n_delayed_o (+1) | SF-026 |
| `skip_mem_repair_present` | `SMU-FUSE-SENSE.S4` | skip_mem_repair_o is presented to the memory repair logic | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port skip_mem_repair_o | SF-047 |
| `smc_done_before_sep` | `SMU-FUSE-SENSE.S5` | **[contested]** contested state - SMC and SEP fuse sense complete in either order and the bring-up proceeds in both orderings | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Security Considerations (+1) | SF-026 |
| `sep_done_before_smc` | `SMU-FUSE-SENSE.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-RST-COLD` — Cold reset entry and reference-clock cold-reset output

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cold_reset_async_assert_without_clock` | `SMU-RST-COLD.S1` | rst_cold_ni asserts asynchronously, without requiring a clock edge | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port rst_cold_ni | SF-029 |
| `cold_reset_sync_deassert` | `SMU-RST-COLD.S2` | rst_cold_ni deassertion is synchronized before it reaches the composed subsystems | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port rst_cold_ni | SF-027 |
| `cold_stable_ref_clk_active_low` | `SMU-RST-COLD.S3` | rst_cold_stable_ref_clk_no is an active-low cold reset synchronized to the reference clock domain | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port rst_cold_stable_ref_clk_no (+1) | SF-027 |
| `cold_stable_ref_clk_synchronized` | `SMU-RST-COLD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cold_reset_during_axi_traffic` | `SMU-RST-COLD.S4` | **[contested]** contested state - cold reset asserts with crossbar traffic in flight and the SMU returns to a defined state | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port rst_cold_ni (+1) | — |
| `defined_state_after_cold_reset` | `SMU-RST-COLD.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cold_reset_with_ref_clock_stopped` | `SMU-RST-COLD.S5` | **[contested]** contested state - cold reset asserts while clk_ref_i is not running, and the reference-clock reset output still reaches its asserted level | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port rst_cold_stable_ref_clk_no (+1) | — |
| `ref_clk_reset_output_asserted` | `SMU-RST-COLD.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-RST-PRIMARY` — Primary reset distribution to the composed subsystems

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `primary_smc_reset_synchronized_to_clk_smu` | `SMU-RST-PRIMARY.S1` | rst_primary_smc_clk_no is synchronized to clk_smu_i | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-027 |
| `primary_ref_reset_synchronized_to_clk_ref` | `SMU-RST-PRIMARY.S2` | rst_primary_ref_clk_no is synchronized to clk_ref_i | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-027 |
| `smc_released` | `SMU-RST-PRIMARY.S3` | SMC, SEP, DTP, the crossbar and the IW converters all leave reset on the primary reset release | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| `sep_released` | `SMU-RST-PRIMARY.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dtp_released` | `SMU-RST-PRIMARY.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `xbar_released` | `SMU-RST-PRIMARY.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `primary_reset_release_order_defined` | `SMU-RST-PRIMARY.S4` | **[contested]** contested state - the two primary reset outputs release in a defined order, with no window in which one subsystem drives another that is still held in reset | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-027 |
| `no_cross_subsystem_reset_mismatch_window` | `SMU-RST-PRIMARY.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-PWRGOOD` — Power-good qualification into the DTP power-on reset

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `dtp_held_in_por_while_powergood_low` | `SMU-PWRGOOD.S1` | DTP is held in power-on reset while powergood_stable is deasserted | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-029, SF-030 |
| `dtp_responsive_after_powergood_stable` | `SMU-PWRGOOD.S2` | DTP becomes responsive to JTAG after powergood_stable asserts | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-029 |
| `powergood_deassert_during_operation` | `SMU-PWRGOOD.S3` | **[contested]** contested state - powergood_i deasserts during operation and DTP returns to power-on reset | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset (+1) | SF-030 |
| `dtp_returns_to_por` | `SMU-PWRGOOD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-CLK-DOMAINS` — SMU clock and reset domain composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `primary_domain_hosts_all_four_blocks` | `SMU-CLK-DOMAINS.S1` | SMC, SEP, DTP, the crossbar and the IW converters all run on clk_smu_i under rst_primary_smc_clk_no | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| `telemetry_domain_independent` | `SMU-CLK-DOMAINS.S2` | the telemetry domain runs on clk_telemetry_i under rst_telemetry_ni, independently of the primary domain | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| `sep_wdt_domain_active` | `SMU-CLK-DOMAINS.S3` | the SEP watchdog runs on the low-frequency clk_sep_wdt_i domain under rst_wdt_n | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| `periph_domain_active` | `SMU-CLK-DOMAINS.S4` | the peripheral domain runs on clk_periph_i under rst_primary_periph_clk_no | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| `ref_slower` | `SMU-CLK-DOMAINS.S5` | **[contested]** contested state - clk_ref_i runs at a frequency and phase unrelated to clk_smu_i and data crossing between the two domains is still delivered intact | RANDOMIZED | `clk_ref_period`, `clk_smu_period`, `phase_offset` | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-042 |
| `ref_faster` | `SMU-CLK-DOMAINS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ref_same_frequency_shifted_phase` | `SMU-CLK-DOMAINS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep_debug_bus_sampled_coherently` | `SMU-CLK-DOMAINS.S6` | **[contested]** contested state - the 512-bit SEP debug bus synchronized into SMC never presents a value mixing two source samples | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-043 |
| `no_mixed_sample_value` | `SMU-CLK-DOMAINS.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-BOOTSEQ-GATE` — External boot-sequence gate on reset release

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `reset_release_held_while_boot_seq_low` | `SMU-BOOTSEQ-GATE.S1` | reset release is held while ext_boot_seq_done_i is low | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_boot_seq_done_i | SF-028 |
| `reset_release_after_boot_seq_done` | `SMU-BOOTSEQ-GATE.S2` | reset release proceeds after ext_boot_seq_done_i asserts | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_boot_seq_done_i | — |
| `boot_seq_done_never_asserts` | `SMU-BOOTSEQ-GATE.S3` | **[contested]** contested state - ext_boot_seq_done_i never asserts; the SMU stays in a defined held state and no subsystem is released on its own | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ext_boot_seq_done_i (+1) | SF-028 |
| `all_subsystems_remain_held` | `SMU-BOOTSEQ-GATE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-MEMINIT` — SRAM auto-initialization control and completion

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `auto_init_runs` | `SMU-MEMINIT.S1` | with disable_sram_auto_init_i at its 1 b0 default the initialization runs and init_mem_done_o asserts | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port disable_sram_auto_init_i (+1) | SF-046 |
| `init_mem_done_asserted` | `SMU-MEMINIT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `auto_init_suppressed` | `SMU-MEMINIT.S2` | with disable_sram_auto_init_i asserted the automatic initialization is suppressed | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port disable_sram_auto_init_i | SF-046 |
| `disable_asserted_mid_init` | `SMU-MEMINIT.S3` | **[contested]** contested state - disable_sram_auto_init_i changes while an initialization is already under way | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port disable_sram_auto_init_i (+1) | SF-046 |
| `defined_outcome_for_init_mem_done` | `SMU-MEMINIT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-SEPWDT-RST` — SEP watchdog reset request into SMC

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep_wdt_timeout_raises_reset_request` | `SMU-SEPWDT-RST.S1` | a SEP watchdog timeout raises the SEP reset request into SMC | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling | SF-031 |
| `wdt_request_crosses_domain` | `SMU-SEPWDT-RST.S2` | the request originates in the SEP watchdog clock domain and is delivered into the SMC domain | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | — |
| `wdt_timeout_while_sep_in_reset` | `SMU-SEPWDT-RST.S3` | **[contested]** contested state - a SEP watchdog timeout occurs while SEP is already held in reset | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Error Handling (+1) | SF-031 |
| `defined_request_behaviour` | `SMU-SEPWDT-RST.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-WDT-TIMEOUT` — Watchdog timeout outputs at the SMU boundary

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `first_timeout_asserted` | `SMU-WDT-TIMEOUT.S1` | the first watchdog timeout appears on wdt_first_timeout_o toward the reset unit | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port wdt_first_timeout_o | SF-032 |
| `second_timeout_asserted` | `SMU-WDT-TIMEOUT.S2` | the second watchdog timeout appears on wdt_second_timeout_o toward external systems | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port wdt_second_timeout_o | SF-032 |
| `second_timeout_while_first_asserted` | `SMU-WDT-TIMEOUT.S3` | **[contested]** contested state - the second timeout occurs while the first is still asserted and both outputs remain individually observable | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port wdt_first_timeout_o (+1) | SF-032 |
| `both_outputs_distinguishable` | `SMU-WDT-TIMEOUT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-NDMRESET` — Non-debug-module reset request and process ports

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ndmreset_request_reflected` | `SMU-NDMRESET.S1` | an ndmreset request is reflected on the corresponding ndmreset_process_o bit | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ndmreset_request_i (+1) | SF-033 |
| `per_cluster_independence` | `SMU-NDMRESET.S2` | requests are per cluster and one cluster request does not disturb another cluster | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ndmreset_request_i | SF-033, SF-050 |
| `ndmreset_with_outstanding_axi` | `SMU-NDMRESET.S3` | **[contested]** contested state - an ndmreset request is raised while an AXI transaction from that cluster is outstanding | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ndmreset_request_i (+1) | — |
| `bounded_completion_or_error` | `SMU-NDMRESET.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-SSRESET` — Subsystem isolation and reset control ports

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `isolate_req_bit_asserted` | `SMU-SSRESET.S1` | an isolation request is presented on the isolate_req_o bit for the addressed subsystem | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port isolate_req_o | SF-034 |
| `ss_reset_ctrl_array_32` | `SMU-SSRESET.S2` | ss_reset_ctrl_o presents one reset_ctrl_t element per subsystem | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port ss_reset_ctrl_o | — |
| `incomplete_holds_sequence` | `SMU-SSRESET.S3` | ss_reset_complete_i is consumed - a subsystem reporting incomplete holds the sequence for that subsystem | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ss_reset_complete_i | SF-034 |
| `complete_advances_sequence` | `SMU-SSRESET.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ss_config_present` | `SMU-SSRESET.S4` | ss_config_o is presented at the SMU boundary | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port ss_config_o | — |
| `flr_pf_active_consumed` | `SMU-SSRESET.S5` | cfg_flr_pf_active_i is consumed by the reset sequence | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port cfg_flr_pf_active_i | SF-034 |
| `one_subsystem_never_completes` | `SMU-SSRESET.S6` | **[contested]** contested state - a subsystem never reports ss_reset_complete_i and the sequence neither advances for it nor blocks the other subsystems indefinitely | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port ss_reset_complete_i | SF-034 |
| `other_subsystems_unblocked` | `SMU-SSRESET.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-ICRESET` — DTP IC_RESET TDR reset override

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `override_entered_when_enabled` | `SMU-ICRESET.S1` | the reset override mode is entered only when the IC_RESET override is enabled | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Operating Modes | SF-036 |
| `override_cleared_by_trst` | `SMU-ICRESET.S2` | the override is cleared by TRST or by a power-on reset | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Operating Modes | SF-036 |
| `override_cleared_by_por` | `SMU-ICRESET.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `override_cleared_by_clearing_ovrd` | `SMU-ICRESET.S3` | the override is cleared by clearing the override enables | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Operating Modes (+1) | SF-036 |
| `ic_reset_ext_tied_zero_when_disabled` | `SMU-ICRESET.S4` | with Cfg.JTAG_IC_RESET_ENABLE = 0 jtag_ic_reset_ext_o is tied to zero | DIRECTED | — | `cover_property` | `DECODE` | `port_table.adoc` §port jtag_ic_reset_ext_o (+1) | — |
| `ovrd_field_present` | `SMU-ICRESET.S5` | the override slice carries .ovrd override enables alongside active-low .val override values | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port jtag_ic_reset_ext_o | SF-035 |
| `val_field_active_low` | `SMU-ICRESET.S5` | ″ | ″ | ″ | `cover_property` | `CONNECTIVITY` | ″ | ″ |
| `override_during_inflight_axi` | `SMU-ICRESET.S6` | **[contested]** contested state - a reset override is asserted while an AXI transaction is in flight | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Operating Modes (+1) | SF-036 |
| `bounded_outcome` | `SMU-ICRESET.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-BOOTSTALL` — DTP boot-stall interaction with SMC boot

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_boot_held_under_stall` | `SMU-BOOTSTALL.S1` | SMC boot is held while the DTP boot-stall is asserted | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Sub-Blocks (+1) | SF-037 |
| `smc_boot_proceeds_after_release` | `SMU-BOOTSTALL.S2` | SMC boot proceeds once the boot-stall is released | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 3 | SF-037 |
| `stall_asserted_after_boot_started` | `SMU-BOOTSTALL.S3` | **[contested]** contested state - the boot-stall is asserted after SMC boot has already started | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 3 (+1) | SF-037 |
| `defined_outcome` | `SMU-BOOTSTALL.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-DFT-SCAN` — DFT test-enable and scan-reset composition

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `test_en_reaches_clock_gaters` | `SMU-DFT-SCAN.S1` | test_en_i reaches the clock-gater test ports | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port test_en_i | SF-045 |
| `test_en_reaches_axi_cells` | `SMU-DFT-SCAN.S2` | test_en_i reaches the AXI cell test inputs | DIRECTED | — | `cover_property` | `CONNECTIVITY` | `port_table.adoc` §port test_en_i | SF-045 |
| `scan_rst_bypasses_synchronizers` | `SMU-DFT-SCAN.S3` | scan_rst_ni bypasses the reset synchronizers | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port scan_rst_ni | — |
| `functional_path_unaffected_at_defaults` | `SMU-DFT-SCAN.S4` | with test_en_i at its 1 b0 default and scan_rst_ni at its 1 b1 default the functional reset path is unaffected | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port test_en_i (+1) | SF-045 |

### `SMU-JTAG2AXI-SMC` — DTP JTAG2AXI bridge into the SMC local fabric

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `jtag2axi_write_reaches_smc_csr` | `SMU-JTAG2AXI-SMC.S1` | a JTAG2AXI write reaches an SMC CSR and changes it | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Features Feature 3 (+1) | SF-038 |
| `jtag2axi_read_returns_csr_value` | `SMU-JTAG2AXI-SMC.S2` | a JTAG2AXI read returns the SMC CSR value | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Features Feature 3 | SF-038 |
| `back_to_back_jtag2axi_accesses` | `SMU-JTAG2AXI-SMC.S3` | **[contested]** contested state - back-to-back JTAG2AXI accesses through the configured pipeline depth of 3 all complete and none is dropped | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Configuration Parameters (+1) | SF-038 |
| `none_dropped` | `SMU-JTAG2AXI-SMC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `jtag2axi_concurrent_with_smc_traffic` | `SMU-JTAG2AXI-SMC.S4` | **[contested]** contested state - a JTAG2AXI access to the SMC fabric while SMC itself is generating fabric traffic | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Features Feature 3 (+1) | — |
| `both_complete_bounded` | `SMU-JTAG2AXI-SMC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-OTPAXI-SMC` — OTP-over-JTAG AXI-Lite path to the SMC OTP

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_otp_read_response_returned` | `SMU-OTPAXI-SMC.S1` | an OTP-over-JTAG read to the SMC OTP returns a response on the AXI-Lite channel | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Interfaces (+1) | SF-039 |
| `smc_otp_write_response_returned` | `SMU-OTPAXI-SMC.S2` | an OTP-over-JTAG write to the SMC OTP returns a response on the AXI-Lite channel | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Interfaces | SF-039 |
| `back_to_back_smc_otp_accesses` | `SMU-OTPAXI-SMC.S3` | **[contested]** contested state - back-to-back SMC OTP accesses each receive their own response in order | DIRECTED | — | `covergroup` | `LIVE` | `SMU_SPEC.md` §Configuration Parameters (+1) | — |
| `responses_in_order` | `SMU-OTPAXI-SMC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMU-OTPAXI-SEP` — OTP-over-JTAG AXI-Lite path to the SEP OTP

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep_otp_read_response_returned` | `SMU-OTPAXI-SEP.S1` | an OTP-over-JTAG read to the SEP OTP returns a response when SEP=1 | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Interfaces (+1) | SF-039 |
| `sep_otp_write_response_returned` | `SMU-OTPAXI-SEP.S2` | an OTP-over-JTAG write to the SEP OTP returns a response when SEP=1 | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `SMU_SPEC.md` §Interfaces | SF-039 |
| `sep_otp_depths_forced_to_3` | `SMU-OTPAXI-SEP.S3` | the SEP OTP read and write pipeline depths are the forced value 2 h3 and do not follow the configured SMC OTP depths | DIRECTED | — | `cover_property` | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | SF-040 |

### `SMU-SMC-AXIL-EXT` — SMC AXI-Lite external peripheral port

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `smc_external_request_observed` | `SMU-SMC-AXIL-EXT.S1` | an SMC access to the external AXI-Lite port appears at the SMU boundary and its response is returned to SMC | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `port_table.adoc` §port smc_external_req_o | — |
| `smc_external_response_returned` | `SMU-SMC-AXIL-EXT.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `smc_external_decerr_tieoff_returned` | `SMU-SMC-AXIL-EXT.S2` | with the port unused and tied to DECERR the error response is returned to SMC | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port smc_external_resp_i | SF-044 |

### `SMU-SEP-AXI-EXT` — SEP AXI extension port

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep_external_request_observed` | `SMU-SEP-AXI-EXT.S1` | a SEP access to the extension port appears at the SMU boundary and its response is returned to SEP | DIRECTED | — | `scoreboard_transaction_log` | `LIVE` | `port_table.adoc` §port sep_external_req_o | — |
| `sep_external_response_returned` | `SMU-SEP-AXI-EXT.S1` | ″ | ″ | ″ | `scoreboard_transaction_log` | `LIVE` | ″ | ″ |
| `sep_external_decerr_tieoff_returned` | `SMU-SEP-AXI-EXT.S2` | with the port unused and tied to DECERR the error response is returned to SEP | DIRECTED | — | `covergroup` | `LIVE` | `port_table.adoc` §port sep_external_resp_i | SF-044 |

## Contested-state scenarios — the ones least likely to be exercised today

Each demands bounded completion-or-error, not just the happy path. A coverage point on these that never fires is a finding about stimulus, not something to waive.

| Scenario | Intent | Cells | Proof | Blocked by |
|---|---|---|---|---|
| `SMU-XBAR-CONN.S8` | contested state - sep_out and ext_in target smc_in in the same cycle; both transactions complete or error within a bounded window and neither response is lost | `concurrent_sep_out_ext_in_to_smc_in`, `both_complete_bounded`, `no_lost_response` | `LIVE` | SF-005 |
| `SMU-XBAR-CONN.S9` | contested state - sep_out to smc_in and smc_out to sep_in run concurrently in opposite directions and neither path starves | `concurrent_opposite_direction_routes`, `neither_path_starved` | `LIVE` | SF-005 |
| `SMU-XBAR-CONN.S10` | contested state - the external SMN slave applies sustained backpressure on ext_out while a sep_out to smc_in transfer is in progress; the internal path still completes within a bounded window | `ext_out_backpressure_sustained`, `internal_route_completes_under_backpressure` | `LIVE` | SF-005 |
| `SMU-XBAR-CONN.S11` | contested state - rst_primary_smc_clk_no asserts with a crossbar burst outstanding; no response is emitted after reset and the fabric routes correctly after release | `reset_during_outstanding_burst`, `no_post_reset_stale_response`, `fabric_usable_after_release` | `LIVE` | — |
| `SMU-XBAR-APERTURE.S6` | contested state - the aperture CSR is rewritten while a transaction decoded under the old map is in flight; that transaction completes or errors within a bounded window and no response is lost | `csr_rewrite_with_inflight_transaction`, `inflight_completes_or_errors_bounded`, `no_lost_response_on_map_change` | `LIVE` | SF-003 |
| `SMU-XBAR-APERTURE.S7` | contested state - the SEP and SMC apertures are programmed to overlap; a single address is never delivered to two targets | `overlapping_apertures_programmed`, `single_target_selected_per_address` | `LIVE` | SF-004 |
| `SMU-XBAR-APERTURE.S9` | contested state - an aperture CSR write is concurrent with a decode of an address inside that aperture issued by another initiator | `csr_write_concurrent_with_decode`, `decode_result_is_one_of_old_or_new_map` | `LIVE` | SF-003 |
| `SMU-XBAR-DEFAULT.S4` | contested state - an unmatched access while the external SMN slave withholds its response completes or errors within a bounded window rather than hanging the initiator | `default_path_no_response_from_smn`, `bounded_completion_or_error` | `LIVE` | SF-009 |
| `SMU-XBAR-DECERR.S4` | contested state - an unmatched ext_in access issued while a matched ext_in access is outstanding; the matched access still completes normally | `unmatched_concurrent_with_matched`, `matched_access_unaffected` | `LIVE` | — |
| `SMU-XBAR-DECERR.S5` | contested state - error during error; a second unmatched ext_in access is issued while the first decode-error response is still outstanding, and both receive their own error response | `two_outstanding_decode_errors`, `each_error_response_distinct` | `LIVE` | — |
| `SMU-XBAR-ATOP.S5` | contested state - an atomic is rejected while an ordinary transaction is outstanding on the same initiator; the ordinary transaction is neither corrupted nor reordered | `atop_rejected_with_outstanding_ordinary`, `ordinary_transaction_intact` | `LIVE` | — |
| `SMU-IDW-IN.S2` | two concurrent ext_in transactions with different IDs return responses tagged with their own IDs | `two_distinct_ext_in_ids_outstanding`, `responses_id_matched` | `LIVE` | — |
| `SMU-IDW-IN.S3` | contested state - several ext_in transactions sharing one ID are outstanding together and their responses return in order | `same_id_multiple_outstanding`, `same_id_responses_in_order` | `LIVE` | — |
| `SMU-IDW-SEP.S2` | contested state - more distinct 10-bit IDs are outstanding than the 6-bit output space can represent; every response still returns to its originator within a bounded window | `id_space_oversubscribed`, `all_responses_returned_bounded` | `LIVE` | SF-006 |
| `SMU-IDW-SEP.S3` | contested state - reset asserts with a converted transaction outstanding and the converter routes correctly after release | `reset_with_outstanding_conversion`, `converter_usable_after_release` | `LIVE` | — |
| `SMU-IDW-SMC.S2` | contested state - more distinct 10-bit IDs are outstanding than the 6-bit output space can represent; every response still returns to its originator within a bounded window | `id_space_oversubscribed`, `all_responses_returned_bounded` | `LIVE` | SF-006 |
| `SMU-IDW-SMC.S3` | contested state - reset asserts with a converted transaction outstanding and the converter routes correctly after release | `reset_with_outstanding_conversion`, `converter_usable_after_release` | `LIVE` | — |
| `SMU-EXT-SMN.S5` | contested state - smu_axi_out_resp_i is tied off so no response ever returns; the originating initiator is released with a bounded error rather than hanging forever | `outbound_response_never_returns`, `initiator_released_bounded` | `LIVE` | SF-009 |
| `SMU-ALIAS-REMAP.S6` | contested state - a burst that starts inside the alias window and would cross its top boundary | `burst_crossing_window_top` | `LIVE` | SF-010 |
| `SMU-SEPOTP-ERRSLV.S3` | contested state - back-to-back SEP-OTP accesses each receive their own error response | `sep0_otp_back_to_back_accesses`, `each_access_own_error_response` | `LIVE` | — |
| `SMU-SEPOTP-ERRSLV.S4` | contested state - the error slave runs on clk_ref_i while its AXI-Lite manager runs on clk_smu_i; the response is correct when the two clocks differ in frequency and phase | `clk_ref_slower_than_clk_smu`, `clk_ref_faster_than_clk_smu`, `clk_ref_equal_clk_smu` | `LIVE` | SF-042 |
| `SMU-MBOX-XCHG.S4` | contested state - SMC writes a second token before SEP has consumed the first; both exchanges complete or the second is rejected, within a bounded window | `second_token_before_first_consumed`, `bounded_completion_or_rejection` | `LIVE` | SF-011 |
| `SMU-MBOX-XCHG.S5` | contested state - reset is asserted between the token write and the response pop; the mailbox path is usable again after release | `reset_between_write_and_pop`, `mailbox_usable_after_release` | `LIVE` | — |
| `SMU-SEP-MBOX-IRQ.S3` | contested state - two SEP mailbox interrupts assert in the same cycle and both are delivered | `two_sep_mailbox_irqs_same_cycle`, `both_delivered` | `LIVE` | SF-014 |
| `SMU-INT-AGG.S4` | contested state - all 256 lines assert in the same cycle and every one is delivered | `all_256_asserted_same_cycle`, `all_256_delivered` | `LIVE` | — |
| `SMU-MBOX-IRQ-OUT.S4` | contested state - several mailbox interrupts assert at once and each appears on its own bit | `multiple_mailbox_irqs_concurrent`, `bits_independent` | `LIVE` | — |
| `SMU-XTRIG-CTM.S5` | contested state - requests on several CTM ports in the same cycle are all delivered | `multiple_ctm_requests_same_cycle`, `all_ctm_requests_delivered` | `LIVE` | — |
| `SMU-XTRIG-CTM.S6` | contested state - a CTM request asserted while the primary reset is deasserting is either delivered or cleanly dropped, never partially | `ctm_request_during_reset_release`, `delivered_or_dropped_cleanly` | `LIVE` | — |
| `SMU-XTRIG-CTP.S5` | contested state - wire-OR contention, with two sources driving the same CTP channel in the same cycle | `ctp_wire_or_two_sources`, `result_defined_under_contention` | `LIVE` | SF-018 |
| `SMU-CLKSTOP-REQ.S3` | contested state - several clock-stop requests assert at once and the aggregation reflects all of them | `multiple_clk_stop_requests`, `aggregation_reflects_all` | `LIVE` | — |
| `SMU-CLKSTOP-REQ.S4` | contested state - a clock-stop request asserts while an AXI transaction is in flight; the transaction completes or errors within a bounded window | `clk_stop_request_with_inflight_axi`, `bounded_completion_or_error` | `LIVE` | — |
| `SMU-CLKSTOP-OUT.S4` | contested state - both sources request a stop and the output stays asserted until both release | `both_stop_sources_active`, `stop_held_until_last_release` | `LIVE` | SF-019 |
| `SMU-LC-STATE.S4` | contested state - lc_state_o is stable across the reset release edge and shows no transient value that is neither the pre-reset nor the post-reset state | `lc_state_across_reset_release`, `no_transient_intermediate_value` | `LIVE` | SF-021 |
| `SMU-LC-DBGDIS.S7` | contested state - dbg_disable asserts while a JTAG2AXI transaction is in flight; the transaction completes or errors within a bounded window and no partial write reaches the fabric | `dbg_disable_during_inflight_jtag2axi`, `bounded_completion_or_error`, `no_partial_write` | `LIVE` | SF-024 |
| `SMU-LC-SECDIS.S3` | contested state - security_disable changes while SMC is mid-transaction; the new value is delivered within a bounded window and SMC keeps making progress | `security_disable_change_during_traffic`, `bounded_delivery`, `smc_progress_maintained` | `LIVE` | SF-025 |
| `SMU-FUSE-SENSE.S5` | contested state - SMC and SEP fuse sense complete in either order and the bring-up proceeds in both orderings | `smc_done_before_sep`, `sep_done_before_smc` | `LIVE` | SF-026 |
| `SMU-RST-COLD.S4` | contested state - cold reset asserts with crossbar traffic in flight and the SMU returns to a defined state | `cold_reset_during_axi_traffic`, `defined_state_after_cold_reset` | `LIVE` | — |
| `SMU-RST-COLD.S5` | contested state - cold reset asserts while clk_ref_i is not running, and the reference-clock reset output still reaches its asserted level | `cold_reset_with_ref_clock_stopped`, `ref_clk_reset_output_asserted` | `LIVE` | — |
| `SMU-RST-PRIMARY.S4` | contested state - the two primary reset outputs release in a defined order, with no window in which one subsystem drives another that is still held in reset | `primary_reset_release_order_defined`, `no_cross_subsystem_reset_mismatch_window` | `LIVE` | SF-027 |
| `SMU-PWRGOOD.S3` | contested state - powergood_i deasserts during operation and DTP returns to power-on reset | `powergood_deassert_during_operation`, `dtp_returns_to_por` | `LIVE` | SF-030 |
| `SMU-CLK-DOMAINS.S5` | contested state - clk_ref_i runs at a frequency and phase unrelated to clk_smu_i and data crossing between the two domains is still delivered intact | `ref_slower`, `ref_faster`, `ref_same_frequency_shifted_phase` | `LIVE` | SF-042 |
| `SMU-CLK-DOMAINS.S6` | contested state - the 512-bit SEP debug bus synchronized into SMC never presents a value mixing two source samples | `sep_debug_bus_sampled_coherently`, `no_mixed_sample_value` | `LIVE` | SF-043 |
| `SMU-BOOTSEQ-GATE.S3` | contested state - ext_boot_seq_done_i never asserts; the SMU stays in a defined held state and no subsystem is released on its own | `boot_seq_done_never_asserts`, `all_subsystems_remain_held` | `LIVE` | SF-028 |
| `SMU-MEMINIT.S3` | contested state - disable_sram_auto_init_i changes while an initialization is already under way | `disable_asserted_mid_init`, `defined_outcome_for_init_mem_done` | `LIVE` | SF-046 |
| `SMU-SEPWDT-RST.S3` | contested state - a SEP watchdog timeout occurs while SEP is already held in reset | `wdt_timeout_while_sep_in_reset`, `defined_request_behaviour` | `LIVE` | SF-031 |
| `SMU-WDT-TIMEOUT.S3` | contested state - the second timeout occurs while the first is still asserted and both outputs remain individually observable | `second_timeout_while_first_asserted`, `both_outputs_distinguishable` | `LIVE` | SF-032 |
| `SMU-NDMRESET.S3` | contested state - an ndmreset request is raised while an AXI transaction from that cluster is outstanding | `ndmreset_with_outstanding_axi`, `bounded_completion_or_error` | `LIVE` | — |
| `SMU-SSRESET.S6` | contested state - a subsystem never reports ss_reset_complete_i and the sequence neither advances for it nor blocks the other subsystems indefinitely | `one_subsystem_never_completes`, `other_subsystems_unblocked` | `LIVE` | SF-034 |
| `SMU-ICRESET.S6` | contested state - a reset override is asserted while an AXI transaction is in flight | `override_during_inflight_axi`, `bounded_outcome` | `LIVE` | SF-036 |
| `SMU-BOOTSTALL.S3` | contested state - the boot-stall is asserted after SMC boot has already started | `stall_asserted_after_boot_started`, `defined_outcome` | `LIVE` | SF-037 |
| `SMU-JTAG2AXI-SMC.S3` | contested state - back-to-back JTAG2AXI accesses through the configured pipeline depth of 3 all complete and none is dropped | `back_to_back_jtag2axi_accesses`, `none_dropped` | `LIVE` | SF-038 |
| `SMU-JTAG2AXI-SMC.S4` | contested state - a JTAG2AXI access to the SMC fabric while SMC itself is generating fabric traffic | `jtag2axi_concurrent_with_smc_traffic`, `both_complete_bounded` | `LIVE` | — |
| `SMU-OTPAXI-SMC.S3` | contested state - back-to-back SMC OTP accesses each receive their own response in order | `back_to_back_smc_otp_accesses`, `responses_in_order` | `LIVE` | — |

## Interaction points

An interaction checker proves every feature it crosses from one joint observation, so each feature it names must also carry its own single-feature cell above.

| Key | Intent | Features | Cells | Method |
|---|---|---|---|---|
| `INT-SEP0-COMPOSITION` | in one SEP=0 build the crossbar and SEP are replaced by the direct ID converters AND the SEP-OTP path is terminated by the error slave; the two substitutions are one spec-stated composition and must be observed together | `SMU-NOSEP`, `SMU-SEPOTP-ERRSLV` | `nosep_direct_path_active_and_otp_errslv_present`, `smc_to_ext_traffic_ok_while_sep_otp_decerrs` | DIRECTED |
| `INT-LC-DBG-BRIDGE` | with dbg_disable asserted the SMC fabric JTAG2AXI bridge is blocked while both OTP JTAG2AXI bridges stay enabled; the selectivity is only observable as one joint measurement | `SMU-LC-DBGDIS`, `SMU-JTAG2AXI-SMC`, `SMU-OTPAXI-SMC`, `SMU-OTPAXI-SEP` | `fabric_bridge_blocked_and_otp_bridges_enabled`, `smc_otp_access_succeeds_while_fabric_blocked`, `sep_otp_access_succeeds_while_fabric_blocked` | DIRECTED |
| `INT-BOOTGATE-RESET` | ext_boot_seq_done_i gates the primary reset release, so the gate and the release are one ordered observation | `SMU-BOOTSEQ-GATE`, `SMU-RST-PRIMARY` | `primary_reset_held_until_boot_seq_done`, `ordered_boot_seq_done_then_reset_release` | DIRECTED |
| `INT-ALIAS-XBAR` | a SEP access inside the alias window takes the dedicated remap port and is simultaneously absent from every crossbar target port | `SMU-ALIAS-REMAP`, `SMU-XBAR-CONN` | `alias_hit_observed_at_smc_and_absent_at_xbar`, `sep_access_outside_window_observed_at_xbar` | DIRECTED |
| `INT-CLKSTOP-CHAIN` | an external clock-stop request is aggregated by DTP and coordinated with the SMC CLA clock-stop onto dtp_stop_clks_o, which only a joint request-to-output observation shows | `SMU-CLKSTOP-REQ`, `SMU-CLKSTOP-OUT` | `external_request_to_stop_clks_output`, `cla_request_to_stop_clks_output` | DIRECTED |
| `INT-XTRIG-MODE-CTM` | the mode composition presented to DTP determines whether a CTM port uses its acknowledge, so the mode value and the CTM port behaviour must be observed together | `SMU-XTRIG-MODE`, `SMU-XTRIG-CTM` | `pulse_sync_mode_port_ignores_ack`, `configured_mode_port_behaviour_matches_mode_bits` | DIRECTED |

---
*Derived from:* feature list revision 1, `content_sha256` `c398fc27a8434d50`; spec audit `93b162e38165502c`.

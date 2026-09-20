// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC SPM boundary scenario sequence (smc_spm_mem_boundary_test), carrying the
// cocotb smc_spm_mem_boundary_test_seq semantics on the SEP_IN AXI4 ingress:
// the first, second and last 64-bit words of the SPM window are three
// DISTINCT physical locations. Real-stall / multi-hart traffic is not claimed.
//
// CO-RESIDENCY, NOT PER-ADDRESS WRITE-THEN-READ. All three patterns are
// written first and read back afterwards. Writing and reading one address at a
// time cannot see aliasing: if all three "edge" addresses decoded onto ONE
// physical location, each write would be followed immediately by its own read
// and every pair would still match. With the writes batched, a collapsed
// decode returns the LAST pattern written and the first readback fails.
//
// The addresses and the window come from smc_top_addrmap_pkg
// (SMC_TOP_SPM_MEMORY_BASE_ADDR / _SIZE); the edges are the base, the base
// plus one word, and the last word of the window. Accesses are full-width
// 64-bit single beats: a 32-bit CSR-shaped access would leave half of each
// word untouched and could not discriminate the addresses.
//
// The patterns are pairwise distinct BY CONSTRUCTION and the sequence asserts
// it rather than trusting a comment: identical patterns would make a
// collapsed decode indistinguishable from a correct one. Each pass draws a
// fresh pattern set from the scenario seed, so the 16 passes of one
// simulation exercise different data (the cocotb twin uses fixed constants)
// and each pass also re-proves that the previous pass's words were replaced
// rather than merely re-read.
//
// +SMC_SPM_MEM_SCOREBOARD_NEGATIVE corrupts the reference model's prediction
// so the run must FAIL.

class smc_spm_mem_boundary_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_spm_mem_boundary_test_seq)

  localparam string ChkSpmEdge = "CHK-SPM-MEM-EDGE";
  localparam string ChkSpmCoResident = "CHK-SPM-CO-RESIDENT";
  localparam string ChkNonvac = "CHK-NONVAC";

  localparam int unsigned EdgeCount = 3;

  typedef struct {
    string     name;
    bit [63:0] addr;
    bit [63:0] pattern;
  } spm_edge_t;

  function new(string name = "smc_spm_mem_boundary_test_seq");
    super.new(name);
  endfunction

  // The three 64-bit-aligned edges of the PeakRDL SPM window, each with a
  // pass-specific pattern whose low half carries the edge identity so a
  // mismatch names the address that produced it.
  function void spm_edges(ref spm_edge_t edges[$]);
    bit [63:0] addrs[$] = '{SmcSpmBase, SmcSpmBase + SmcMemBytes,
                            SmcSpmBase + SmcSpmSize - SmcMemBytes};
    string     names[$] = '{"SPM_LO", "SPM_LO_NEXT", "SPM_HI"};
    edges.delete();
    // The low half is the low 32 bits of the edge's OWN address, so a
    // mismatch names the address that produced it. Derived rather than
    // written out: a hand-copied label drifts from the window it labels.
    foreach (addrs[i])
    edges.push_back('{names[i], addrs[i], {32'(random_pattern(32)), 32'(addrs[i])}});
  endfunction

  task body();
    spm_edge_t edges[$];
    bit [63:0] observed;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkMemResp, ChkSpmEdge, ChkSpmCoResident, ChkNonvac, ChkSbMinAct
                    });
    spm_edges(edges);
    if (edges.size() != EdgeCount)
      `uvm_fatal(get_type_name(), "spm_edges() did not build the expected edge set")
    assert_edges_discriminating(edges);
    // One readback per edge reaches the spm_mem predictor each pass.
    check_min_activity(SmcFeatureSpmMem, edges.size());
    `uvm_info(get_type_name(),
              $sformatf(
                  {"SMC SV-UVM SPM boundary (smc_spm_mem_boundary_test): window 0x%0h..0x%0h, %0d ",
                   "64-bit edges written co-resident then read back; scenario_seed=%0d"},
                    SmcSpmBase, SmcSpmBase + SmcSpmSize - 1, edges.size(), scenario_seed), UVM_LOW)

    wait_fuse_sense_done();

    // All writes first: this ordering is the discriminating part.
    foreach (edges[i]) mem_write(edges[i].addr, edges[i].pattern, {edges[i].name, ".write"});

    // Then every read back, with the other two patterns still resident.
    foreach (edges[i]) begin
      mem_read(edges[i].addr, observed, {edges[i].name, ".readback"});
      check_evidence(
          ChkSpmEdge, {edges[i].name, ".readback"}, observed, edges[i].pattern, $sformatf(
          "addr=0x%0h read while all %0d edge patterns are resident", edges[i].addr, edges.size()));
      // The same word must not equal any OTHER edge's pattern: that is the
      // shape a collapsed decode would produce.
      foreach (edges[j]) begin
        if (i == j) continue;
        void'(m_check.expect_true(
            ChkSpmCoResident,
            observed !== edges[j].pattern,
            $sformatf(
                "%s@0x%0h read 0x%016h, which is not %s's pattern 0x%016h",
                edges[i].name,
                edges[i].addr,
                observed,
                edges[j].name,
                edges[j].pattern)
        ));
      end
    end

    check_evidence(ChkNonvac, "sep_in_mem_accesses", 64'(mem_accesses), 64'(edges.size() * 2));
    finalize_evidence();
  endtask

  // Distinct addresses AND distinct patterns; without both, a readback could
  // not tell the edges apart.
  protected function void assert_edges_discriminating(ref spm_edge_t edges[$]);
    foreach (edges[i]) begin
      foreach (edges[j]) begin
        if (i >= j) continue;
        if (edges[i].addr == edges[j].addr)
          `uvm_fatal(
              get_type_name(), $sformatf(
              "SPM edges %s and %s share address 0x%0h", edges[i].name, edges[j].name, edges[i].addr
              ))
        if (edges[i].pattern == edges[j].pattern)
          `uvm_fatal(get_type_name(), $sformatf(
                     {
                       "SPM edges %s and %s drew the same pattern 0x%016h, so a co-resident ",
                       "readback could not discriminate them"
                     },
                     edges[i].name,
                     edges[j].name,
                     edges[i].pattern
                     ))
      end
    end
  endfunction

endclass : smc_spm_mem_boundary_test_seq

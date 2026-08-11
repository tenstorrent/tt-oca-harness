---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 3
content_sha256: 4b37c7ba88aa0234689282eec80604a4181b7fec42e255479eaa83bf8f58455c
ip: SMU_ALL
milestone: P2
status: approved
pin_revision: 1
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/index.adoc
  revision: 1e98bd45a59ae32ca1bb4715a963b721e26aaf3b
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/rom.adoc
  revision: df9e3efe4c8a68f95acb339d0aaf9c9f3f90ab4d
- path: hw/sys/sep/doc/index.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/introduction.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/crypto.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/periphs.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/memory_map.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/lifecycle_controller.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/security_disable.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/test_mode.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/token_processing.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/index.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/dtp/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/jtag.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/clock_stop.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
source_revision: e02d5a97ba46d97eb4469041e115efca949f0184
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
generated_by:
  human_id: minshaoho
  run_id: dv_vplan_gen-SMU_ALL-P2-20260805T074000+0800-amend-reverse-omission
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T07:42:58+08:00'
  amendment_of:
    supersedes_artifact_revision: 2
    reason: 'Skill 3 reverse_diff CONFIRMED-OMISSION: add SMC-BOOT, SEP-BOOT, SMC-AXI-LITE-SHIMS, DTP-IJTAG-SCAN,
      INT-FUSE-SENSE-BOOT, INT-XBAR-APERTURE-INTEROP'
approved_by: minshaoho
approved_at: '2026-08-05T07:45:45+08:00'
features:
- key: SMU-COMPOSE-BLOCKS
  title: SMU composes SMC, SEP, DTP, and AXI crossbar
  intent: At the SMU boundary the subsystem presents composed SMC, SEP (when SEP=1), DTP, and smu_axi_xbar
    with the documented block connectivity.
  triad:
    producer: chiplet integration instantiating SMU with DefaultCfg and SEP=1
    transport: SMU top composition wiring among u_smc, u_sep, u_dtp, and u_smu_axi_xbar
    consumer: external SMN/JTAG/reset/lifecycle observers that see the composed SMU port set
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Overview / §Architecture §Block Overview / §Sub-Blocks @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 743a4762aa81ee2794d0b9140fba775a585b571431d77c1b747c796c9bbc041e
  scenarios:
  - key: SMU-COMPOSE-BLOCKS.S1
    intent: With SEP=1 SMU exposes SMC, SEP, DTP, and the 3x3 crossbar as present instances.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Sub-Blocks (Present column) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep=1
      - blocks=smc+sep+dtp+xbar
      random_knobs: []
      coverage_artifact: null
  - key: SMU-COMPOSE-BLOCKS.S2
    intent: SMC, SEP, DTP, and crossbar share clk_smu_i / rst_primary_smc_clk_no.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (Primary domain) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - domain=clk_smu
      - rst=rst_primary_smc_clk_no
      random_knobs: []
      coverage_artifact: null
  - key: SMU-COMPOSE-BLOCKS.S3
    intent: SMU port table exposes JTAG, SMN AXI, cross-trigger, and lifecycle port groups.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (jtag/smu_axi/xtrig/lc groups) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - port_group=jtag
      - port_group=smu_axi
      - port_group=xtrig
      - port_group=lifecycle
      random_knobs: []
      coverage_artifact: null
- key: SMU-PORT-CLK-RST
  title: SMU multi-domain clocks and hierarchical resets
  intent: External clocks and cold/power-good resets enter SMU and produce documented primary/ref/periph/telemetry/SEP-WDT
    domain resets at the SMU boundary.
  triad:
    producer: chiplet PLL/power supervisor driving clk_* and rst_cold_ni/powergood_i
    transport: SMU clock/reset distribution into SMC/SEP/DTP/crossbar
    consumer: downstream subsystems observing rst_primary_*_clk_no and related reset outputs
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (clk_*/rst_*/powergood_i) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/clk_rst.adoc §Clock Architecture / §Reset Architecture @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: f09c87c1288b04c9f8d1e4348661add6b0dbe81c9e96fea4e8d4d39cd0183826
  scenarios:
  - key: SMU-PORT-CLK-RST.S1
    intent: Cold reset assert/deassert releases SMU primary resets in documented domains.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (rst_cold_ni) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/clk_rst.adoc §Primary Reset (rst_primary_no) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - rst=cold_assert
      - rst=cold_deassert
      - obs=rst_primary_smc
      random_knobs: []
      coverage_artifact: null
  - key: SMU-PORT-CLK-RST.S2
    intent: powergood_i qualification produces the stable POR path used by SMC/DTP bring-up.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Reset Architecture (BP_POWERGOOD / powergood_stable / pwr_on_rst_ni)
      @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (DTP pwr_on_rst_ni = powergood_stable) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - powergood=0
      - powergood=1
      random_knobs: []
      coverage_artifact: null
  - key: SMU-PORT-CLK-RST.S3
    intent: Telemetry and SEP-WDT clock domains remain separate from clk_smu_i.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (Telemetry / SEP WDT rows) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - clk=telemetry
      - clk=sep_wdt
      random_knobs: []
      coverage_artifact: null
- key: SMU-PORT-SMN-AXI
  title: External SMN AXI subordinate and manager ports
  intent: An external SMN master/subordinate pair at smu_axi_in/out exchanges AXI4 traffic with the SMU
    crossbar using documented 56/64/ID widths.
  triad:
    producer: external SMN AXI agent driving smu_axi_in_req_i or responding on smu_axi_out_resp_i
    transport: SMU axi_56_64 / axi_out port pair into/out of smu_axi_xbar
    consumer: SMC or SEP aperture targets (inbound) or SMN memory/IO (outbound)
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (External SMN AXI) / §Specifications (widths) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (smu_axi_in_*/out_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: c4e650a4d6b38958c016e3c1b763cec9fd7e1872e9507912e3f607621c40cd0d
  scenarios:
  - key: SMU-PORT-SMN-AXI.S1
    intent: A 56-bit/64-bit access on smu_axi_in reaches a programmed SMC aperture (SEP=0 direct IW converters
      or SEP=1 xbar→smc_in).
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Specifications (56-bit addr, 64-bit data) / §Data Paths (ext_in → smc_in)
      / §Architecture (When SEP=0 direct SMC↔external) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - dir=in
      - dest=smc_aperture
      random_knobs: []
      coverage_artifact: null
  - key: SMU-PORT-SMN-AXI.S2
    intent: SMC- or SEP-initiated unmatched/default traffic exits on smu_axi_out.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (ext_out default catch-all) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - dir=out
      - src=smc_out
      - src=sep_out
      random_knobs: []
      coverage_artifact: null
  - key: SMU-PORT-SMN-AXI.S3
    intent: Inbound ID width is 8-bit at the SMU external input per SMU crossbar spec.
    requires: DECODE
    spec_refs:
    - 'hw/sys/smu/doc/SMU_SPEC.md §Specifications (Crossbar ID widths: 8-bit max input) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9'
    coverage:
      method: DIRECTED
      required_cells:
      - id_width_in=8
      random_knobs: []
      coverage_artifact: null
  - key: SMU-PORT-SMN-AXI.S4
    intent: A 56-bit/64-bit access on smu_axi_in reaches a programmed SEP aperture via the SEP=1 3x3 crossbar
      (ext_in → sep_in).
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (ext_in → sep_in) / §Architecture (SEP=1 CSR-programmed apertures
      / u_smu_axi_xbar) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - dir=in
      - dest=sep_aperture
      random_knobs: []
      coverage_artifact: null
- key: SMU-SEP-PARAM
  title: SEP=0 versus SEP=1 configuration at the SMU boundary
  intent: Compile-time SEP selects real SEP+3x3 crossbar versus tied-off SEP paths with direct SMC↔external
    converters and an AXI-Lite error slave on the SEP-OTP path.
  triad:
    producer: build configuration selecting parameter SEP=0 or SEP=1
    transport: SMU generate blocks (gen_sep / no-SEP IW converters / sep_otp err slave)
    consumer: external SMN AXI, DTP SEP-OTP AXI-Lite, and lc_state_o observers
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Configuration Parameters (SEP) / §Architecture When SEP=0 / §Error Handling
    @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 9759b090133642772992987d478c11414a9e04f522d0ddaaa4d700c7e13ad33b
  scenarios:
  - key: SMU-SEP-PARAM.S1
    intent: With SEP=1, SEP participates in the 3x3 crossbar and drives lc_state_o.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Sub-Blocks (u_sep Present SEP=1) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (lc_state_o) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sep=1
      - xbar=present
      - lc_state=from_sep
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-PARAM.S2
    intent: With SEP=0, crossbar/SEP are replaced by direct SMC↔external ID converters.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Architecture (When SEP=0) / §Sub-Blocks (u_iw_conv_smc_*) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep=0
      - path=direct_smc_ext
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-PARAM.S3
    intent: With SEP=0, SEP-OTP returns DECERR/0xBADCAB1E and lc_state_o is 8'hf0.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP=0 SEP-OTP) / §Security Considerations (8'hf0) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep=0
      - otp_resp=DECERR
      - otp_rdata=0xBADCAB1E
      - lc_state=0xf0
      random_knobs: []
      coverage_artifact: null
- key: SMU-XBAR-CONNECT
  title: SMU AXI crossbar legal connectivity matrix
  intent: Each crossbar initiator may reach only its documented target set; a master cannot reach its
    own inbound port.
  triad:
    producer: SEP outbound, SMC outbound, or external SMN inbound AXI initiator
    transport: smu_axi_xbar 3x3 matrix with forbidden self-inbound edges
    consumer: sep_in, smc_in, or ext_out target returning the AXI response
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Crossbar routing connectivity) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 09ac1b5b2a1077503b28c3366936fb52b39d71786bb2ee0c8030827bcb5fbead
  scenarios:
  - key: SMU-XBAR-CONNECT.S1
    intent: sep_out reaches smc_in and ext_out only.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (sep_out→{smc_in, ext_out}) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=sep_out,dst=smc_in
      - src=sep_out,dst=ext_out
      random_knobs: []
      coverage_artifact: null
  - key: SMU-XBAR-CONNECT.S2
    intent: smc_out reaches sep_in and ext_out only.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (smc_out→{sep_in, ext_out}) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=smc_out,dst=sep_in
      - src=smc_out,dst=ext_out
      random_knobs: []
      coverage_artifact: null
  - key: SMU-XBAR-CONNECT.S3
    intent: ext_in reaches sep_in and smc_in only.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (ext_in→{sep_in, smc_in}) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=ext_in,dst=sep_in
      - src=ext_in,dst=smc_in
      random_knobs: []
      coverage_artifact: null
- key: SMU-XBAR-APERTURE
  title: CSR-programmed SEP/SMC apertures on the SMU crossbar
  intent: Firmware-programmed SEP/SMC aperture base/size CSRs determine which addresses decode to sep_in
    versus smc_in versus default/error paths.
  triad:
    producer: SMC firmware or debug agent programming SEP/SMC aperture CSRs
    transport: smu_axi_xbar addr_map built from CSR base/size
    consumer: transactions from sep_out/smc_out/ext_in decoding into programmed aperture targets
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Overview (CSR-programmed apertures) / §Feature 4 / §CDC notes (addr_map)
    @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access (GLOBAL_BASE/REGION_SIZE) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  - hw/sys/sep/doc/fabric.adoc §Transaction Routing (SEP_GLOBAL_BASE_ADDR/SEP_REGION_SIZE) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 8f86141eb209dc6e78c2444401f7ce24e434263a49b1638f2e5e207caf70d8d7
  scenarios:
  - key: SMU-XBAR-APERTURE.S1
    intent: After programming SMC aperture, ext_in inside SMC aperture delivers to smc_in.
    requires: DECODE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access (GLOBAL_BASE/REGION_SIZE used by SMU-level
      routing) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - aperture=smc
      - addr=inside
      - dest=smc_in
      random_knobs: []
      coverage_artifact: null
  - key: SMU-XBAR-APERTURE.S2
    intent: After programming SEP aperture, ext_in inside SEP aperture delivers to sep_in.
    requires: DECODE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc §Transaction Routing (SEP aperture used by SMU crossbar) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - aperture=sep
      - addr=inside
      - dest=sep_in
      random_knobs: []
      coverage_artifact: null
  - key: SMU-XBAR-APERTURE.S3
    intent: Reprogramming apertures during in-flight traffic is contested and requires bounded completion-or-error.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §CDC notes (addr_map not stability-checked against in-flight transactions)
      @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: RANDOMIZED
      required_cells:
      - overlap=reprogram_during_inflight
      - outcome=complete_or_error
      random_knobs:
      - aperture_base
      - aperture_size
      - inflight_count
      coverage_artifact: null
- key: SMU-XBAR-ATOP-REJECT
  title: SMU crossbar rejects AXI atomic operations
  intent: An AXI atomic (ATOP) request presented to the SMU crossbar is rejected because ATOPs=0.
  triad:
    producer: any crossbar initiator issuing an AXI transaction with ATOP asserted
    transport: smu_axi_xbar with ATOPs=1'b0
    consumer: initiator observing rejected/unsupported atomic outcome
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (ATOPs=1'b0) / §Error Handling (AXI atomic operation) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 37fd17637ee2025fe84838d5cb543dc099e2a995110f574a864ab2ce559f2b10
  scenarios:
  - key: SMU-XBAR-ATOP-REJECT.S1
    intent: ATOP on ext_in is rejected and does not complete as a successful atomic.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (AXI atomic operation) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=ext_in
      - atop=asserted
      - result=rejected
      random_knobs: []
      coverage_artifact: null
  - key: SMU-XBAR-ATOP-REJECT.S2
    intent: ATOP from smc_out or sep_out is likewise rejected.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Specifications (ATOPs unsupported) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=smc_out
      - src=sep_out
      - result=rejected
      random_knobs: []
      coverage_artifact: null
- key: SMU-XBAR-ID-CONV
  title: Crossbar-to-SMC/SEP AXI ID-width conversion
  intent: Transactions leaving the crossbar toward SEP/SMC pass 10-bit→6-bit ID converters so subordinate
    ports observe documented 6-bit IDs with correct response routing.
  triad:
    producer: crossbar master port emitting a 10-bit ID transaction toward SMC or SEP
    transport: u_iw_conv_sep / u_iw_conv_smc axi_iw_converter
    consumer: SMC sep_axi_in / SEP inbound port observing 6-bit ID responses
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (ID widths) / §Sub-Blocks (u_iw_conv_*) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/fabric.adoc §AXI ID Widths (SEP AXI input 6) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  record_sha256: b1c9736b53263c96495691d12f51ab7c32bcb2e49ff5615d66c78720e1d09cce
  scenarios:
  - key: SMU-XBAR-ID-CONV.S1
    intent: Multi-ID outstanding stream into SMC retains response association after 10→6 conversion.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Sub-Blocks (10-bit → 6-bit ID conversion) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: RANDOMIZED
      required_cells:
      - dest=smc
      - ids>=2
      - resp_match=1
      random_knobs:
      - axi_id
      - outstanding
      coverage_artifact: null
  - key: SMU-XBAR-ID-CONV.S2
    intent: Multi-ID outstanding stream into SEP retains response association after 10→6 conversion.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Sub-Blocks (u_iw_conv_sep) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: RANDOMIZED
      required_cells:
      - dest=sep
      - ids>=2
      - resp_match=1
      random_knobs:
      - axi_id
      - outstanding
      coverage_artifact: null
- key: SMU-XBAR-UNMAPPED
  title: Unmapped ext_in accesses decode-error
  intent: An external SMN access matching neither SEP nor SMC aperture receives DECERR because ext_in
    has no default master port.
  triad:
    producer: external SMN master addressing outside programmed SEP/SMC apertures
    transport: smu_axi_xbar address decode with no default for ext_in
    consumer: external master observing DECERR
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (ext_in has no default) / §Error Handling (Unmapped crossbar
    access) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: bf70354af42fd7faa9c46e9d03171cba332c398c4d79ab7768235ebc5df450df
  scenarios:
  - key: SMU-XBAR-UNMAPPED.S1
    intent: ext_in address outside both apertures returns DECERR.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (Unmapped crossbar access | DECERR) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=ext_in
      - addr=unmapped
      - resp=DECERR
      random_knobs: []
      coverage_artifact: null
  - key: SMU-XBAR-UNMAPPED.S2
    intent: Unmatched sep_out/smc_out take ext_out default rather than DECERR.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (ext_out default catch-all) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - src=sep_out
      - src=smc_out
      - dest=ext_out_default
      random_knobs: []
      coverage_artifact: null
- key: SMU-XBAR-BACKPRESSURE
  title: Crossbar backpressure and contested multi-initiator traffic
  intent: Concurrent SEP/SMC/external traffic under subordinate backpressure completes or errors in bounded
    time without silent deadlock.
  triad:
    producer: two or more of sep_out, smc_out, ext_in issuing concurrent AXI traffic
    transport: smu_axi_xbar shared target ports under ready/valid backpressure
    consumer: each initiator receiving a bounded response for every accepted request
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (performance/backpressure) / §Data Paths @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 899d309e5f8f1705a0f56b2162c02fd309210833a0c9a0bf4763296909c7d7a7
  scenarios:
  - key: SMU-XBAR-BACKPRESSURE.S1
    intent: Concurrent smc_out and sep_out to ext_out under SMN backpressure complete or error bounded.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (backpressure) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: RANDOMIZED
      required_cells:
      - pair=smc+sep
      - bp=ext_out
      - outcome=bounded
      random_knobs:
      - stall_cycles
      - outstanding
      coverage_artifact: null
  - key: SMU-XBAR-BACKPRESSURE.S2
    intent: Concurrent ext_in to smc_in and sep_in under local backpressure complete or error bounded.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (backpressure) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: RANDOMIZED
      required_cells:
      - src=ext_in
      - bp=local
      - outcome=bounded
      random_knobs:
      - stall_cycles
      - outstanding
      coverage_artifact: null
  - key: SMU-XBAR-BACKPRESSURE.S3
    intent: Saturated outstanding IDs still drain with completion-or-error.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (error handling / backpressure) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: RANDOMIZED
      required_cells:
      - state=saturated
      - outcome=bounded
      random_knobs:
      - id_count
      - outstanding
      coverage_artifact: null
- key: SMU-SEP-SMC-ALIAS
  title: Dedicated SEP→SMC alias remap bypassing the crossbar
  intent: SEP accesses in the fixed 0x4000_0000/1GB SMC region are remapped to 0x0 and delivered to SMC
    without traversing smu_axi_xbar.
  triad:
    producer: SEP master addressing SEP_SMC_REGION_BASE=0x4000_0000 size 0x4000_0000
    transport: sep_ext_to_smc_axi_local_alias_remap (axi_window_remap) bypass path
    consumer: SMC sep_axi_in / local resources observing remapped base 0x0000_0000
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (SEP→SMC alias remap) / §Sub-Blocks @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/memory_map.adoc §Memory Map (0x4000_0000 | 1 GB | SMC) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 5d4d851d48d1920ae0bd1703cb56db0ef489ab841c6159af98e441c9a94e86f3
  scenarios:
  - key: SMU-SEP-SMC-ALIAS.S1
    intent: SEP access to 0x4000_0000+offset is observed at SMC as offset from 0x0.
    requires: DECODE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (0x4000_0000/1GB → 0x0000_0000) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - addr=0x40000000
      - alias=0x0
      - bypass_xbar=1
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-SMC-ALIAS.S2
    intent: Access near the top of the 1 GB window still remaps to SMC.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (size 0x4000_0000) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - addr=near_top
      - alias_top=1
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-SMC-ALIAS.S3
    intent: Dedicated path does not require a matching smu_axi_xbar SMC aperture hit.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Sub-Blocks (bypasses the crossbar) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - path=alias_remap
      - xbar_required=0
      random_knobs: []
      coverage_artifact: null
- key: SMC-FAB-DUAL-NET
  title: SMC dual-network AXI4 vs AXI4-Lite delivery (SMU-visible)
  intent: Through SMU-integrated SMC fabric, manager transactions use AXI4 for high-performance subordinates
    and AXI4-Lite for low-performance subordinates.
  triad:
    producer: SMC fabric traffic manager (CPU cluster, DMA, JTAG2AXI, Log Engine)
    transport: SMC dual-network fabric (AXI4 HP / AXI4-Lite LP)
    consumer: addressed subordinate on the network class in Fabric Traffic Subordinates table
  spec_refs:
  - hw/sys/smc/doc/fabric.adoc §Dual-Network Architecture / §Traffic Subordinates @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  record_sha256: e25cd418423706e9753ecad1fc1363cff6d4acc3624244ded991610d513167d9
  scenarios:
  - key: SMC-FAB-DUAL-NET.S1
    intent: SRAM/PLIC/CLINT/WDT/external AXI use AXI4 HP network.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Traffic Subordinates (AXI4 High-Performance rows) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - dest=SRAM
      - dest=PLIC
      - dest=CLINT
      - dest=WDT
      - dest=external_axi
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FAB-DUAL-NET.S2
    intent: Local peripherals/config registers use AXI4-Lite LP network.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Traffic Subordinates (AXI4-Lite Low-Performance rows) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - dest=local_peripheral
      - dest=config_register
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FAB-DUAL-NET.S3
    intent: Both networks carry 64-bit data without truncation.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Dual-Network Architecture (64-bit data bus width) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - net=AXI4,data=64
      - net=AXI4-Lite,data=64
      random_knobs: []
      coverage_artifact: null
- key: SMC-FAB-IN-PORTS
  title: SMC fabric external input ports via SMU (sys / JTAG / SEP)
  intent: External masters entering SMC through sys_axi_in, jtag_axi_in, or sep_axi_in are admitted at
    documented widths and reach allowed resources subject to inbound filters.
  triad:
    producer: SMN/xbar (sys), DTP JTAG2AXI (jtag), or SEP path (sep) driving SMC input ports
    transport: SMC input fabric ports sys_axi_in / jtag_axi_in / sep_axi_in
    consumer: SMC local subordinates or error slave after inbound filter evaluation
  spec_refs:
  - hw/sys/smc/doc/fabric.adoc §Traffic Subordinates (External AXI Input Ports) / §Inbound Filtering @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sys/jtag/sep_axi_in) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 91ce811a5999f204c86e0719f4e0012a227b65e26931607de84dfd6959749ce6
  scenarios:
  - key: SMC-FAB-IN-PORTS.S1
    intent: sys_axi_in 6-bit ID / 56-bit addr / 12-bit user reaches an allowed SMC resource.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sys_axi_in 56/64/6/12) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/fabric.adoc §AXI ID Widths (System AXI input ID 6) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - port=sys_axi_in
      - id_w=6
      - user_w=12
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FAB-IN-PORTS.S2
    intent: jtag_axi_in 2-bit ID from DTP reaches an allowed SMC resource.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (jtag_axi_in) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axi_smc_dbg_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - port=jtag_axi_in
      - id_w=2
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FAB-IN-PORTS.S3
    intent: sep_axi_in is blocked by default inbound filter until programmed, then allowed.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_axi_in) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/fabric.adoc §Inbound Filtering (default blocking) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - port=sep_axi_in
      - filter=default_block
      - filter=allow_programmed
      random_knobs: []
      coverage_artifact: null
- key: SMC-FAB-OUT-SMN
  title: SMC outbound filtered/remapped traffic to SMN
  intent: SMC-initiated outbound transactions exit through output_axi after optional privilege remap and
    outbound filtering, carrying the documented Source ID.
  triad:
    producer: SMC CPU/DMA/other manager issuing outbound access
    transport: SMC output fabric (privilege remap optional → outbound filters → output_axi)
    consumer: SMN/system resources returning responses on output_axi_resp_i
  spec_refs:
  - hw/sys/smc/doc/fabric.adoc §Outbound Traffic Flow / §Source ID by Traffic Path / §Outbound Filtering
    @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (output_axi_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 7e3ebd990a78471310e1fb4bf76a2df015bf042c51a92e36f415663d938f5953
  scenarios:
  - key: SMC-FAB-OUT-SMN.S1
    intent: Direct-to-NoC outbound traffic uses Source ID SMC_ID.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Source ID by Traffic Path (Direct to NoC | SMC_ID) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - path=direct
      - sid=SMC_ID
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FAB-OUT-SMN.S2
    intent: Xvisor/M-mode remap paths use OTHER_ID / MMODE_ID.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Source ID by Traffic Path (Xvisor/M-mode rows) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - path=xvisor
      - sid=OTHER_ID
      - path=mmode
      - sid=MMODE_ID
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FAB-OUT-SMN.S3
    intent: Outbound filter deny yields an error response rather than SMN completion.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc §Outbound Filtering / §Non-Secure Bit Filtering (error slave) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - filter=deny
      - resp=error
      random_knobs: []
      coverage_artifact: null
- key: SMC-DECODE-APERTURE
  title: SMC local-alias and chiplet-global aperture decode
  intent: SMC resources are reachable identically via LOCAL_BASE 0xC000_0000 or programmable GLOBAL_BASE
    when inside the relevant aperture.
  triad:
    producer: any master addressing SMC using local alias or global aperture
    transport: SMC fabric local-alias window and GLOBAL_BASE/REGION_SIZE aperture decode
    consumer: addressed SMC component returning the same resource response for equivalent offsets
  spec_refs:
  - hw/sys/smc/doc/memmap.adoc §Memory Map (LOCAL_BASE / GLOBAL_BASE / REGION_SIZE) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  record_sha256: 7aba0f04f7732ed9defabe0d4560bd4ff3f57f89ab2aa30d2c12791496126532
  scenarios:
  - key: SMC-DECODE-APERTURE.S1
    intent: LOCAL_BASE+offset and GLOBAL_BASE+offset (same offset) reach the same component.
    requires: DECODE
    spec_refs:
    - hw/sys/smc/doc/memmap.adoc §Memory Map (identically regardless of which base) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - base=local
      - base=global
      - offset=mailbox
      random_knobs: []
      coverage_artifact: null
  - key: SMC-DECODE-APERTURE.S2
    intent: REGION_SIZE reset 16 MiB bounds the chiplet-global aperture until reprogrammed.
    requires: DECODE
    spec_refs:
    - hw/sys/smc/doc/memmap.adoc §Memory Map (REGION_SIZE CSR reset is 16 MiB) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - region_size_reset=16MiB
      - addr=inside
      - addr=outside
      random_knobs: []
      coverage_artifact: null
  - key: SMC-DECODE-APERTURE.S3
    intent: Mailbox at BASE+0x001_8000 and DTP control at BASE+0x000_F000 decode to those blocks.
    requires: DECODE
    spec_refs:
    - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (Mailbox / DTP Control Registers) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - dest=mailbox
      - dest=dtp_ctrl
      random_knobs: []
      coverage_artifact: null
- key: SMC-MBX-CHANNELS
  title: SMC mailbox MMIO channels for inter-processor communication
  intent: SMC presents 32 AXI4-Lite mailbox channels (16 inbound + 16 outbound) for inter-processor/inter-chiplet
    FIFO communication.
  triad:
    producer: SMC CPU or external agent writing/reading a mailbox channel FIFO
    transport: SMC mailbox MMIO region BASE+0x001_8000..BASE+0x003_7FFF
    consumer: peer agent (SEP or external) observing inbox/outbox data and interrupt side-effects
  spec_refs:
  - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (Mailbox | 32 channels) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/periphs.adoc §Peripherals (Mailbox | 32) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (NUM_MAILBOXES=32) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 3324a7bcea8c33ef649917ead714e2dd66c2a153068e14c6aabdbb66da09fab3
  scenarios:
  - key: SMC-MBX-CHANNELS.S1
    intent: Outbound mailbox write is readable on the peer inbox path used for SMC↔SEP exchange.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-response) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (Mailbox) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - ch=outbound0
      - peer=sep
      random_knobs: []
      coverage_artifact: null
  - key: SMC-MBX-CHANNELS.S2
    intent: Inbound mailbox write asserts corresponding mailbox interrupt in SMC interrupt assembly.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc §SMC CPU Interrupt Vector Map (mailbox_interrupts[31:0]) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - ch=inbound0
      - irq=mailbox_bit
      random_knobs: []
      coverage_artifact: null
  - key: SMC-MBX-CHANNELS.S3
    intent: Representative channels across the 32-channel map are independently addressable.
    requires: DECODE
    spec_refs:
    - hw/sys/smc/doc/memmap.adoc §Address Space Organization (Mailbox | 128KB | 32 channels) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - ch=0
      - ch=15
      - ch=16
      - ch=31
      random_knobs: []
      coverage_artifact: null
- key: SMU-MBX-CHALLENGE
  title: SMC↔SEP mailbox challenge-response interoperability
  intent: SMC writes a token outbound; SEP reads inbound, verifies, writes complement; SMC pops the response
    — primary real SMC↔SEP interoperability path.
  triad:
    producer: SMC CPU writing a challenge token into an outbound mailbox
    transport: SMC↔SEP mailbox pairing across the SMU integration
    consumer: SEP CPU consuming the token and SMC observing complement response/interrupts
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-response) / §Feature 5 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/fabric.adoc §Mailboxes @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_mailbox_interrupts_i) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: fe829a19d22a5eb0e156c86e0c306c22910138c8eee7aa2cddd47b90f2570468
  scenarios:
  - key: SMU-MBX-CHALLENGE.S1
    intent: End-to-end challenge then complement response completes with expected payloads.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-response) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - phase=challenge
      - phase=response
      - payload=complement
      random_knobs: []
      coverage_artifact: null
  - key: SMU-MBX-CHALLENGE.S2
    intent: SEP→SMC mailbox interrupts fire on SMC peripheral bits for channels 0–7.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc §Exact Indexed Map (SEP mailbox interrupt 0–7) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - irq=sep_mbx0
      - irq=sep_mbx7
      random_knobs: []
      coverage_artifact: null
  - key: SMU-MBX-CHALLENGE.S3
    intent: Exchange completes across SEP boot-stalled-then-released contested path.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 5 (SMC-executes-while-SEP-stalled) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_boot_stall_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sep=stalled_then_release
      - exchange=completes
      random_knobs: []
      coverage_artifact: null
- key: SEP-MBX-IRQ-SMC
  title: SEP mailbox interrupts cross into SMC PLIC vector
  intent: SEP mailbox interrupt outputs enter SMC as sep_mailbox_interrupts_i[7:0] at documented cpu_interrupts_o
    indices.
  triad:
    producer: SEP mailbox logic asserting smc_mailbox_interrupt_o
    transport: SMU SEP→SMC interrupt wiring (sep_mailbox_interrupts_i[7:0])
    consumer: SMC interrupt aggregator / PLIC seeing SEP mailbox peripheral bits
  spec_refs:
  - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (smc_mailbox_interrupt_o) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_mailbox_interrupts_i) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/interrupts.adoc §Exact Indexed Map (SEP mailbox interrupt 0–7) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: a1e276eb430ccab024fe4ca4147636ba6e8b4b13517fcebbf9d76b01450a8522
  scenarios:
  - key: SEP-MBX-IRQ-SMC.S1
    intent: 'SEP mailbox interrupt N sets cpu_interrupts_o bit NUM_EXT_INTERRUPTS+N (4-core: 256+N).'
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc §Exact Indexed Map (4-core bits 256–263) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - n=0
      - n=3
      - n=7
      - cfg=4core
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MBX-IRQ-SMC.S2
    intent: In 1-core configuration the same interrupts appear at bits 32–39.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc §Exact Indexed Map (1-core bits 32–39) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - n=0
      - n=7
      - cfg=1core
      random_knobs: []
      coverage_artifact: null
- key: SMC-MBX-IRQ-EXT
  title: SMC external mailbox interrupt outputs at SMU
  intent: SMC mailbox external interrupts are presented on SMU ext_mailbox_interrupts_o[NUM_MAILBOXES-1:0]
    for external targets.
  triad:
    producer: SMC mailbox channel event generating an external interrupt
    transport: SMU port ext_mailbox_interrupts_o
    consumer: external interrupt controller / chiplet target observing the corresponding bit
  spec_refs:
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (ext_mailbox_interrupts_o) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (ext_mailbox_interrupts_o) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (SMC mailbox interrupts) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 06f21af793852b88625b1b83fe02364ab0cce379109fff43c9d1f6b79507ed4b
  scenarios:
  - key: SMC-MBX-IRQ-EXT.S1
    intent: Mailbox external-interrupt event asserts matching bit on ext_mailbox_interrupts_o.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (ext_mailbox_interrupts_o | 32) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - bit=0
      - bit=31
      random_knobs: []
      coverage_artifact: null
  - key: SMC-MBX-IRQ-EXT.S2
    intent: Width equals NUM_MAILBOXES (32) at the SMU boundary.
    requires: DECODE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Specifications (SMC mailboxes = 32) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - width=32
      random_knobs: []
      coverage_artifact: null
- key: SMC-PWRGOOD-DTP-POR
  title: SMC powergood_stable qualifies DTP JTAG power-on reset
  intent: SMC debounced power-good is the DTP pwr_on_rst_ni source so loss of power-good forces TAP/TDR
    reset even when TRST is released.
  triad:
    producer: power supervisor / SMU powergood_i path through SMC powergood_stable
    transport: SMC→DTP pwr_on_rst_ni connection inside SMU
    consumer: DTP PTAP/TDR logic entering reset when power-good is lost
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (DTP pwr_on_rst_ni = powergood_stable) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/clk_rst.adoc §Reset Architecture (BP_POWERGOOD / TRST AND pwr_on_rst_ni) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/jtag.adoc §Reset Architecture (pwr_on_rst_ni) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 178c6a9dfc5678f02b7721d225f0a6ff0ed8d2e4ea5bc5d99396ac4e3462dbcd
  scenarios:
  - key: SMC-PWRGOOD-DTP-POR.S1
    intent: Deasserting power-good forces PTAP/TDR reset independent of TRST released.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Reset Architecture (loss of power-good forces TAP/TDR reset) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - powergood=0
      - trst=1
      - tap=reset
      random_knobs: []
      coverage_artifact: null
  - key: SMC-PWRGOOD-DTP-POR.S2
    intent: With power-good stable and TRST released, PTAP can leave Test-Logic-Reset.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc §Reset Architecture @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - powergood=1
      - trst=1
      - tap=exit_tlr
      random_knobs: []
      coverage_artifact: null
- key: SMC-RST-PRIMARY-EXPORT
  title: SMC primary resets exported at SMU boundary
  intent: SMC-generated primary resets synchronized to ref and SMC clocks are exported on SMU rst_primary_*
    ports for downstream subsystems.
  triad:
    producer: SMC reset unit responding to cold/cool/functional cold reset sources
    transport: SMU rst_primary_ref_clk_no / rst_primary_smc_clk_no
    consumer: downstream chiplet subsystems using those synchronized resets
  spec_refs:
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (rst_primary_*) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/clk_rst.adoc §Primary Reset (rst_primary_no) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 0a152a5fbc124e59d36e22333138f58da070bdf0b95f5118903232f49b097dbc
  scenarios:
  - key: SMC-RST-PRIMARY-EXPORT.S1
    intent: Functional cold reset asserts both exported primary reset outputs.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Primary Reset Activation Sources (Functional Cold Reset) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - src=cold
      - obs=rst_primary_smc
      - obs=rst_primary_ref
      random_knobs: []
      coverage_artifact: null
  - key: SMC-RST-PRIMARY-EXPORT.S2
    intent: JTAG/TDR state is not cleared by rst_primary alone.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Primary Reset (JTAG/TDR reset by POR, not rst_primary alone) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - rst_primary=assert
      - jtag_tdr=retained_unless_por
      random_knobs: []
      coverage_artifact: null
- key: SMC-DTP-CSR
  title: SMC programs DTP cross-trigger CSRs through local fabric
  intent: SMC (or JTAG2AXI via SMC map) accesses DTP control / cross-trigger CSR block at BASE+0x000_F000,
    carried on the SMC→DTP AXI-Lite CSR path.
  triad:
    producer: SMC CPU or debug agent issuing MMIO to DTP Control Registers
    transport: SMC fabric path to DTP axil_xtrig CSR interface (BASE+0x000_F000)
    consumer: DTP cross-trigger/CSR logic accepting configuration and returning responses
  spec_refs:
  - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (DTP Control Registers | BASE+0x000_F000) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axil_xtrig_req_i/resp_o) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: cc2131e65e3f601bf87bbcc5578005e7b58678c5785da38751dc8516cd60bd48
  scenarios:
  - key: SMC-DTP-CSR.S1
    intent: MMIO write/read to DTP control region completes on axil_xtrig path.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (DTP Control Registers) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axil_xtrig_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - op=write
      - op=read
      - dest=dtp_csr
      random_knobs: []
      coverage_artifact: null
  - key: SMC-DTP-CSR.S2
    intent: Programmed CTM/CTP configuration takes effect on subsequent trigger routing.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/overview.adoc §Cross Trigger Network (CTM flexible routing) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (DTP Control) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - cfg=ctm_route
      - effect=observed
      random_knobs: []
      coverage_artifact: null
- key: DTP-JTAG-PTAP
  title: DTP primary JTAG TAP access at SMU
  intent: An external JTAG host exercises the DTP PTAP through SMU jtag_ptap_client_* pins for IEEE 1149.1
    IDCODE/BYPASS/state transitions.
  triad:
    producer: external JTAG host driving TCK/TMS/TRST_N/TDI on SMU PTAP client ports
    transport: DTP JTAG Interface Unit / PTAP inside SMU u_dtp
    consumer: host observing TDO/TDO_OEN and jtag_ptap_state_o / inst_decoded_o
  spec_refs:
  - hw/sys/dtp/doc/overview.adoc §Key Features (JTAG Interface) / §Specifications @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/jtag.adoc §DTP JTAG Topology / §Reset Architecture @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (jtag_ptap_client_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: eceef877e862cb01aac312d3553d7fffb6f52ae299f623f31d73031133adef55
  scenarios:
  - key: DTP-JTAG-PTAP.S1
    intent: IDCODE instruction returns configured IDCODE fields.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/overview.adoc §Key Features (IDCODE) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 3 (IDCODE/BYPASS) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - inst=IDCODE
      random_knobs: []
      coverage_artifact: null
  - key: DTP-JTAG-PTAP.S2
    intent: BYPASS places a single-bit register between TDI and TDO.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/overview.adoc §Key Features (BYPASS) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - inst=BYPASS
      random_knobs: []
      coverage_artifact: null
  - key: DTP-JTAG-PTAP.S3
    intent: TRST or power-on returns TAP to Test-Logic-Reset.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc §Reset Architecture @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - rst=TRST
      - rst=POR
      - state=Test-Logic-Reset
      random_knobs: []
      coverage_artifact: null
- key: DTP-JTAG2AXI-SMC
  title: DTP JTAG2AXI bridge into SMC fabric
  intent: When enabled and lifecycle-permitted, DTP converts JTAG debug transactions into AXI on SMC jtag_axi_in
    for CSR/local-fabric access.
  triad:
    producer: JTAG host issuing memory/CSR access via DTP JTAG2AXI
    transport: DTP axi_smc_dbg_req_o → SMC jtag_axi_in_req_i
    consumer: addressed SMC fabric resource returning AXI response to the JTAG bridge
  spec_refs:
  - hw/sys/dtp/doc/jtag.adoc §DTP JTAG Topology (JTAG2AXI) / §Security Integration @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axi_smc_dbg_*) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 3 (JTAG2AXI local-fabric access) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: d5cfe46b1f4db41ef96ba57cf1a6454943dc27db8ba4b750fbe28271f4a1820e
  scenarios:
  - key: DTP-JTAG2AXI-SMC.S1
    intent: JTAG2AXI read/write to an allowed SMC CSR completes with matching data.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 3 (JTAG2AXI) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - op=read
      - op=write
      - dest=smc_csr
      random_knobs: []
      coverage_artifact: null
  - key: DTP-JTAG2AXI-SMC.S2
    intent: Lifecycle gating disables JTAG2AXI so no AXI traffic is issued.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc §Security Integration @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (Lifecycle-gated debug) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - feat_ctrl=debug_blocked
      - axi_traffic=0
      random_knobs: []
      coverage_artifact: null
- key: DTP-OTP-AXIL
  title: DTP OTP-over-JTAG AXI-Lite to SMC and SEP
  intent: DTP JTAG2AXIL masters drive SMC and SEP OTP debug AXI-Lite ports for fuse/OTP access over JTAG.
  triad:
    producer: JTAG host accessing OTP debug through DTP
    transport: DTP axil_smc_otp_jtag_* and axil_sep_otp_jtag_* AXI-Lite managers
    consumer: SMC or SEP OTP/eFuse controller (or SEP=0 error slave) responding
  spec_refs:
  - hw/sys/dtp/doc/jtag.adoc §DTP JTAG Topology (JTAG2AXIL OTP) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axil_*_otp_jtag_*) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (OTP debug) / §Error Handling (SEP=0 OTP) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 45609a5033f6f36b6f3d947dc377f561a7ae5e0322b8c70826c6ac1a46d311c8
  scenarios:
  - key: DTP-OTP-AXIL.S1
    intent: JTAG→SMC OTP AXI-Lite path completes a legal access.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axil_smc_otp_jtag_*) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (axil_smc_otp_jtag_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - target=smc_otp
      random_knobs: []
      coverage_artifact: null
  - key: DTP-OTP-AXIL.S2
    intent: With SEP=1, JTAG→SEP OTP AXI-Lite path completes a legal access.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (axil_sep_otp_jtag_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - target=sep_otp
      - sep=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-OTP-AXIL.S3
    intent: With SEP=0, SEP OTP path returns DECERR/0xBADCAB1E.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP=0 SEP-OTP) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep=0
      - resp=DECERR
      - rdata=0xBADCAB1E
      random_knobs: []
      coverage_artifact: null
- key: DTP-BOOT-STALL
  title: DTP JTAG boot-stall control of SMC bring-up
  intent: DTP boot-stall override/value outputs hold or release SMC boot sequencing under JTAG control.
  triad:
    producer: JTAG host programming DTP boot-stall override controls
    transport: DTP jtag_boot_stall_ovrd_o / jtag_boot_stall_o into SMC boot control
    consumer: SMC boot/reset release path observing stall versus run
  spec_refs:
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_boot_stall_*) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 3 (boot-stall) / §Operating Modes (Debug/test) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 5c6143717aeb4de54ac119d9039195ef48648d26469faad58c4d372339db6f47
  scenarios:
  - key: DTP-BOOT-STALL.S1
    intent: Override enabled with stall asserted holds SMC boot.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 3 (boot-stall/debug-control) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - ovrd=1
      - stall=1
      - boot=held
      random_knobs: []
      coverage_artifact: null
  - key: DTP-BOOT-STALL.S2
    intent: Clearing stall/override allows SMC boot progression.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Operating Modes (Debug/test) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - stall=0
      - boot=progresses
      random_knobs: []
      coverage_artifact: null
- key: DTP-IC-RESET
  title: DTP IC_RESET TDR override of SMC/SEP/external resets
  intent: When IC_RESET is enabled, DTP drives override enable/value structs to SMC, SEP, and external
    reset slices.
  triad:
    producer: JTAG host loading IC_RESET TDR override enables/values
    transport: DTP jtag_ic_reset_smc_o / sep_o / ext_o
    consumer: SMC/SEP/integrator reset controls observing forced active-low override values
  spec_refs:
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_ic_reset_*) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 3 (IC_RESET) / §Operating Modes (Reset override) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (jtag_ic_reset_ext_o) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 59df5722babcfeeef0fdc1b3c96973ba1654ef8739fff77b984b87d145001a11
  scenarios:
  - key: DTP-IC-RESET.S1
    intent: SMC IC_RESET override forces selected SMC reset slice to programmed value.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_ic_reset_smc_o) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - target=smc
      - ovrd=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-IC-RESET.S2
    intent: SEP IC_RESET override forces selected SEP reset slice when SEP=1.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_ic_reset_sep_o) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - target=sep
      - ovrd=1
      - sep=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-IC-RESET.S3
    intent: TRST/POR or clearing override removes the override effect.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Operating Modes (Reset override exit) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - exit=trst_por
      - exit=clear_ovrd
      random_knobs: []
      coverage_artifact: null
- key: DTP-FEAT-GATE
  title: SEP feat_ctrl gates DTP debug resources
  intent: SEP-driven lifecycle feature-control into DTP gates STAP selection, iJTAG SIB access, and JTAG2AXI
    bridges per lifecycle/debug policy.
  triad:
    producer: SEP LCC driving feat_ctrl_o into DTP feat_ctrl_i
    transport: SMU SEP→DTP feat_ctrl wiring
    consumer: DTP debug resources enabled or blocked per feat_ctrl bits
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Security Considerations / §Error Handling (Lifecycle-gated debug) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/dtp/doc/jtag.adoc §Security Integration @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (feat_ctrl_i) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/sep/doc/lifecycle_controller.adoc §Life Cycle Controller (feat_ctrl_o to TAP) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 881f51eec80010f1a533fd14e013079ab207d1fed45d885d86041ac58466ba74
  scenarios:
  - key: DTP-FEAT-GATE.S1
    intent: Debug-disable profile blocks STAP selection / JTAG2AXI traffic.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (feat_ctrl gating | blocked) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - policy=debug_disabled
      - jtag2axi=blocked
      random_knobs: []
      coverage_artifact: null
  - key: DTP-FEAT-GATE.S2
    intent: Debug-enable profile permits JTAG2AXI to SMC.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc §Security Integration @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - policy=debug_enabled
      - jtag2axi=allowed
      random_knobs: []
      coverage_artifact: null
  - key: DTP-FEAT-GATE.S3
    intent: lc_sigint_err fail-closed forces feat_ctrl=0 and blocks debug.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/lifecycle_controller.adoc §Life Cycle Controller (fail closed feat_ctrl_o=0) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sigint_err=1
      - feat_ctrl=0
      - debug=blocked
      random_knobs: []
      coverage_artifact: null
- key: DTP-CLKSTOP-AGG
  title: DTP clock-stop aggregation from JTAG and CLA requests
  intent: DTP OR-combines JTAG jtag_clock_stop with aggregated CLA xtrig_clk_stop_req_i to drive stop_clks_o,
    keeping CLA-only status separately observable.
  triad:
    producer: JTAG DEBUG_CONTROL jtag_clock_stop and/or CLA xtrig_clk_stop_req_i sources
    transport: DTP CTN clock-stop controller aggregation
    consumer: PLL/functional clock gates observing dtp_stop_clks_o and CLA status readback
  spec_refs:
  - hw/sys/dtp/doc/clock_stop.adoc §Clock Stop @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 6 / §Specifications (Clock-stop ports) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (dtp_stop_clks_o, xtrig_clk_stop_req_i) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 391aa756a9ab5568e4e45840a1d69fc0d40825f65e755061c302c95490f256e4
  scenarios:
  - key: DTP-CLKSTOP-AGG.S1
    intent: Only jtag_clock_stop asserts stop_clks_o.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/clock_stop.adoc §Clock Stop (jtag_clock_stop OR-combined) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - src=jtag
      - stop_clks=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-CLKSTOP-AGG.S2
    intent: Only CLA clk_stop_req asserts stop_clks_o and CLA-only status.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/clock_stop.adoc §Clock Stop (CLA indication excludes jtag_clock_stop) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - src=cla
      - stop_clks=1
      - cla_status=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-CLKSTOP-AGG.S3
    intent: Port [0] reserved for SMC participates in SMC CLA handshake.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Specifications (port [0] reserved for SMC) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (tdr_dbg_ctrl_clock_stop_en_i / clocks_stopped_by_cla_o)
      @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - port0=smc_reserved
      - smc_cla=handshake
      random_knobs: []
      coverage_artifact: null
- key: DTP-XTRIG-CTM
  title: DTP cross-trigger matrix external CTM ports
  intent: DTP CTM source/destination req/ack arrays route internal cross-triggers; DTP [1:0] reserved
    for SMC pulse-sync.
  triad:
    producer: SMC reserved CTM ports and/or external CTM agents
    transport: DTP Cross Trigger Matrix inside u_dtp
    consumer: configured CTM destinations observing req (and ack when not pulse-sync)
  spec_refs:
  - hw/sys/dtp/doc/overview.adoc §Cross Trigger Network / §Specifications (OCH CT v1.0) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (XTRIG_NUM_INT_CT; [1:0] reserved) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (xtrig_ctm_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: e55242bdd797c117562f66ac7ff9ff066521f0c2f2e27e0b612b0a7276097f45
  scenarios:
  - key: DTP-XTRIG-CTM.S1
    intent: Programmed CTM route delivers src_req to selected destination.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/overview.adoc §Cross Trigger Network (CTM flexible routing) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - route=programmed
      - pulse_seen=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-XTRIG-CTM.S2
    intent: Pulse-sync mode leaves ack ports unused as specified.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (ack unused in pulse-sync) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mode=pulse_sync
      - ack_unused=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-XTRIG-CTM.S3
    intent: Bits [1:0] remain reserved for SMC.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Specifications (DTP [1:0] reserved for SMC) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - bits=1:0
      - owner=smc
      random_knobs: []
      coverage_artifact: null
- key: DTP-XTRIG-CTP
  title: DTP CTP GPIO pad-facing cross-trigger ports
  intent: DTP CTP req/ack dout/din/en buses provide Wire-OR and Point-to-Point cross-trigger signaling
    through the GPIO pad ring (16 ports).
  triad:
    producer: DTP CTP logic or external pad-side CTP peer
    transport: SMU xtrig_ctp_* dout/din/en port group
    consumer: peer CTP endpoint observing Wire-OR or P2P protocol activity
  spec_refs:
  - hw/sys/dtp/doc/overview.adoc §Cross Trigger Network (Wire-OR and P2P) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (CTP ports 16) / §Feature 6 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (xtrig_ctp_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 392bd2964698eab0c52084874164d1dab16df84cfb1e5b6409463ff04f9f99b2
  scenarios:
  - key: DTP-XTRIG-CTP.S1
    intent: CTP request-out toggles dout/en for selected signaling mode.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/overview.adoc §Cross Trigger Network (Wire-OR and P2P) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mode=wire_or
      - mode=p2p
      - phase=req_out
      random_knobs: []
      coverage_artifact: null
  - key: DTP-XTRIG-CTP.S2
    intent: CTP ack path completes handshake in P2P mode.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 6 (CTP wire-OR/P2P) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - mode=p2p
      - phase=ack
      random_knobs: []
      coverage_artifact: null
- key: DTP-STAP-SMC-SEP
  title: DTP secondary TAPs to SMC and SEP debug
  intent: DTP STAP hosts provide secondary TAP connectivity to SMC and SEP CPU debug TAPs, gated by lifecycle/security
    disable policy.
  triad:
    producer: JTAG host selecting SMC or SEP STAP through DTP
    transport: DTP jtag_stap_smc_host_* / jtag_stap_sep_host_* STAP ports
    consumer: SMC or SEP debug TAP responding on TDO when selection and feat_ctrl allow
  spec_refs:
  - hw/sys/dtp/doc/overview.adoc §Secondary TAPs (SMC/SEP debug STAP) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/jtag.adoc §DTP JTAG Topology (STAPs) / §Security Integration @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_stap_smc/sep_host_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: f9d3ea40c85f7a0d6e6aaf23463ad6be794bbceee4148b988820a43cc77867a7
  scenarios:
  - key: DTP-STAP-SMC-SEP.S1
    intent: SMC STAP selection connects PTAP path to SMC debug TAP when enabled.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_stap_smc_host_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - stap=smc
      - selected=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-STAP-SMC-SEP.S2
    intent: SEP STAP selection connects PTAP path to SEP debug TAP when SEP=1 and enabled.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_stap_sep_host_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - stap=sep
      - sep=1
      - selected=1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-STAP-SMC-SEP.S3
    intent: Security/lifecycle disable blocks STAP selection for debug TAPs.
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc §Security Integration (Security disable gates STAP selection) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - stap=blocked
      - policy=disabled
      random_knobs: []
      coverage_artifact: null
- key: SEP-SYSIF-SMU-XBAR
  title: SEP System Interface traffic through SMU crossbar / SMN
  intent: SEP traffic leaving SEP-local decode routes via SMU crossbar apertures to SMC or external SMN
    per SEP outbound routing rules.
  triad:
    producer: SEP CPU/DMA/System I/F issuing external or SMC-bound transaction
    transport: SEP outbound path → SMU xbar (or alias remap for SMC region) → SMC/SMN
    consumer: SMC resources or SMN endpoints returning AXI responses into SEP
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc §Transaction Routing / §Local and External AXI4 Traffic Remapping @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/sep/doc/memory_map.adoc §Memory Map (External / SMC / SMU regions) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Crossbar routing) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: cdc8440efd6d76eddd5b1157d9525c8d4abb8fd099792dd2e30a80024fa4b99d
  scenarios:
  - key: SEP-SYSIF-SMU-XBAR.S1
    intent: SEP access to neighboring SMC via global SMC aperture reaches SMC.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc §Transaction Routing (Neighboring SMC resources) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - dest=smc_global
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SYSIF-SMU-XBAR.S2
    intent: Non-local non-SMC SEP access routes out to SMN via ext_out.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc §Transaction Routing (routed out to SMN) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - dest=smn
      - path=ext_out
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SYSIF-SMU-XBAR.S3
    intent: Inbound SMN→SEP through programmed SEP aperture is subject to default-block inbound filter
      until programmed.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc §Transaction Routing (inbound filter default block all) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - dir=inbound
      - filter=default_block
      - filter=allow
      random_knobs: []
      coverage_artifact: null
- key: SEP-LC-FEAT-EXPORT
  title: SEP lifecycle state and feat_ctrl export to SMC/DTP/SMU
  intent: SEP LCC exports lc_state and feat_ctrl to SMC and DTP; SMU presents lc_state_o and demote outputs
    at the chiplet boundary.
  triad:
    producer: SEP Life Cycle Controller after OTP shadow / demote inputs
    transport: SEP lc_state_o / feat_ctrl_o → SMC/DTP; SMU lc_state_o / lcc_demote_state_*
    consumer: SMC security policy and DTP debug gating observing exported vectors
  spec_refs:
  - hw/sys/sep/doc/lifecycle_controller.adoc §Life Cycle Controller (feat_ctrl_o destinations) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (lc_state_o, feat_ctrl_o) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (lc_state_o, lcc_demote_state_*) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (lc_state_i, feat_ctrl_i) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 0cecb2ce6c74e5561c2e0196914906f88f316e79894afcb754a59456870add33
  scenarios:
  - key: SEP-LC-FEAT-EXPORT.S1
    intent: Stable LC state is visible on SMU lc_state_o as 8-bit differentially encoded value.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Specifications (Lifecycle state width 8) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (lc_state_o) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - width=8
      - src=sep
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-FEAT-EXPORT.S2
    intent: feat_ctrl debug-disable bits are observed by DTP gating behavior.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/lifecycle_controller.adoc §Life Cycle Controller (feat_ctrl_o to TAP/DFT) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - bit=SEP_DBG
      - effect=dtp_gate
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-FEAT-EXPORT.S3
    intent: Demote CSR effects appear on SMU lcc_demote_state_* exports.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (lcc_demote_state_*) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/sep/doc/lifecycle_controller.adoc §DEMOTE_1 and DEMOTE_2 @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - demote=1
      - demote=2
      random_knobs: []
      coverage_artifact: null
- key: SEP-SEC-DIS
  title: SEP security-disable token path through SMU/JTAG
  intent: The 256-bit SEP_SEC_DISABLE_TOKEN / SEC_DIS path into SEP enables lifecycle override for debug/test
    when the hashed token matches, retaining JTAG token state across reset as specified.
  triad:
    producer: JTAG-hosted SEC_DIS_TOKEN_I (and related token inputs) into SEP via DTP/JTAG
    transport: SMU parameter SEP_SEC_DISABLE_TOKEN hierarchy into SEP fuse-controller comparator
    consumer: SEP security_disable_o / feat_ctrl override opening debug access per SEC_DIS rules
  spec_refs:
  - hw/sys/sep/doc/security_disable.adoc §Security Disable (SEC_DIS) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Configuration Parameters (SEP_SEC_DISABLE_TOKEN) / §Security Considerations
    @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (security_disable_o) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: e1d2b24dbb88384462d62aefa6dcecc7f9b0273c4cdeb71af4641387002e4819
  scenarios:
  - key: SEP-SEC-DIS.S1
    intent: Matching SEC_DIS token forces feature-control open for debug/test per SEC_DIS rules.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/security_disable.adoc §Security Disable (hash match overrides lifecycle) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - token=match
      - sec_dis=1
      - feat_ctrl=open
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SEC-DIS.S2
    intent: Mismatched/absent token leaves lifecycle feature-control unmodified by SEC_DIS.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/security_disable.adoc §Security Disable @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - token=mismatch
      - sec_dis=0
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SEC-DIS.S3
    intent: SEC_DIS token JTAG register retains value across reset (no reset) as specified.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/security_disable.adoc §Security Disable (shall not have a reset) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - reset=por_functional
      - token_reg=retained
      random_knobs: []
      coverage_artifact: null
- key: SEP-WDT-RST-SMC
  title: SEP watchdog reset request into SMC
  intent: SEP WDT timeout presents a reset request into SMC (active-low sep_wdt_reset_n_i / sep_wdt_timer_rst_req
    path) visible in the SMC interrupt/reset assembly.
  triad:
    producer: SEP watchdog timer expiring on clk_sep_wdt_i domain
    transport: SEP→SMC WDT reset/interrupt wiring at SMU
    consumer: SMC interrupt aggregator / reset handling observing the SEP WDT event
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP WDT timeout → SEP reset request into SMC) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_wdt_reset_n_i) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (clk_sep_wdt_i) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 8f5b557845a1ce9d0ba241798e51c94451c9f0af5f48701f9f5fe5b3b1d34bef
  scenarios:
  - key: SEP-WDT-RST-SMC.S1
    intent: SEP WDT timeout asserts the SMC-visible SEP WDT reset/interrupt indication.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_wdt_reset_n_i polarity/routing) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP WDT) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - wdt=timeout
      - smc_obs=1
      random_knobs: []
      coverage_artifact: null
  - key: SEP-WDT-RST-SMC.S2
    intent: Indication clears after SEP WDT/reset handling completes.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP WDT timeout) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - wdt=cleared
      random_knobs: []
      coverage_artifact: null
- key: SEP-FUSE-SENSE-HS
  title: SMC↔SEP fuse-sense handshake at SMU
  intent: SMC fuse_sense_done and SEP fuse_sense_done participate in the security bring-up handshake across
    the SMU boundary.
  triad:
    producer: SMC eFuse controller completing fuse sense / SEP fuse sense FSM
    transport: SMU fuse_sense_done_o / sep_fuse_sense_done_o and SEP smc_fuse_sense_done_i wiring
    consumer: peer side and external memory-repair/boot logic observing completion
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Security Considerations (fuse-sense handshake) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (fuse_sense_done_o, sep_fuse_sense_done_o) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (smc_fuse_sense_done_i, sep_fuse_sense_done_o)
    @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 210f1d760941c43948ae4f1b550c2a8258f724e1220f3eb8606093715c81d639
  scenarios:
  - key: SEP-FUSE-SENSE-HS.S1
    intent: SMC fuse_sense_done_o asserts after SMC fuse sense completes and is visible to SEP input.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (fuse_sense_done_o) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (smc_fuse_sense_done_i) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - smc_done=1
      - sep_sees=1
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FUSE-SENSE-HS.S2
    intent: SEP fuse_sense_done_o asserts after SEP fuse sense completes at SMU boundary.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_fuse_sense_done_o) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sep_done=1
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FUSE-SENSE-HS.S3
    intent: TEST_EN latch timing follows fuse-sense-done versus SEC_DIS as specified.
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/test_mode.adoc §Test Mode Entry (latched when fuse sensing done if SEC_DIS not asserted)
      @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sec_dis=0
      - latch=fuse_sense_done
      - sec_dis=1
      - latch=cold_reset_release
      random_knobs: []
      coverage_artifact: null
- key: SEP-MEM-BOUND-PASSTHROUGH
  title: SEP memory/crypto macro interfaces at SMU boundary
  intent: SMU passes through SEP TCM/ROM/SRAM and crypto/KM memory macro req/rsp ports so external macros
    service SEP CPU/crypto traffic.
  triad:
    producer: SEP CPU/DMA/crypto/KM issuing memory requests on SEP macro interfaces
    transport: SMU sep_*_req_o / rsp_i passthrough ports
    consumer: external SEP SRAM/ROM/TCM/OTBN/KM macros returning responses
  spec_refs:
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_sram/boot_rom/cpu_tcm/crypto/km mem ports)
    @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/sep/doc/memory_map.adoc §Memory Map (ICCM/DCCM/SRAM/ROM/OTBN/KM) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Sub-Blocks / §Interfaces (CPU memory / SEP passthrough) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 946f9f5ae5734f83587c6635d5709b59fa4d3c48bd348b9b8b79880d0cb7f127
  scenarios:
  - key: SEP-MEM-BOUND-PASSTHROUGH.S1
    intent: SEP TCM req/rsp passthrough completes an ITCM/DTCM access.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_cpu_tcm_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mem=tcm
      - op=read
      - op=write
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MEM-BOUND-PASSTHROUGH.S2
    intent: SEP boot ROM and scratch SRAM passthrough complete accesses.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_boot_rom_*, sep_sram_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mem=boot_rom
      - mem=scratch_sram
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MEM-BOUND-PASSTHROUGH.S3
    intent: OTBN/KM memory passthrough ports complete representative accesses.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_crypto_pka_* / sep_km_*) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mem=otbn_imem
      - mem=km_sram
      random_knobs: []
      coverage_artifact: null
- key: SMC-BOOT
  title: SMC boot and firmware execution under SMU
  intent: SMC boots from ROM, releases resets, runs firmware, and reports status via scratch/mailbox paths
    at the SMU integration boundary.
  triad:
    producer: SMC ROM/firmware after SMU/SMC reset release and fuse/repair gating
    transport: SMC CPU/ROM/scratch and SMU-exported control/status ports (ext_boot_seq_done_i, fuse_sense_done_o)
    consumer: observable SMC execution progress and downstream reset releases / pass-fail signaling
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 1 (SMC Boot and Firmware Execution) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/cpu.adoc §Boot Sequence Integration @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/rom.adoc @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: f5c8a8223c85f45271992adabbb06355850173af2fdc565e1efb207b8b0da5e3
  scenarios:
  - key: SMC-BOOT.S1
    intent: After reset/fuse/repair gating, SMC fetches from ROM and progresses execution with observable
      pass/fail via scratch or mailbox.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 1 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/smc/doc/cpu.adoc §Boot Sequence Integration @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - smc-rom-fetch-progress
      random_knobs: []
      coverage_artifact: null
  - key: SMC-BOOT.S2
    intent: ext_boot_seq_done_i and mem-repair/fuse status gate SMC reset release as specified at SMU
      ports.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (ext_boot_seq_done_i) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/cpu.adoc §Boot Sequence Integration @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - boot-seq-gate
      random_knobs: []
      coverage_artifact: null
  - key: SMC-BOOT.S3
    intent: SEP=0 no-SEP configuration still boots SMC per Feature 1 / Operating Modes.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 1 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/smu/doc/SMU_SPEC.md §Operating Modes (No-SEP configuration) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - smc-boot-sep0
      random_knobs: []
      coverage_artifact: null
- key: SEP-BOOT
  title: Real SEP boot and execution under SMU
  intent: With SEP=1, real SEP RTL boots from TCM/ROM under SMU with reset release and observable CPU
    progress.
  triad:
    producer: SEP TCM/ROM contents and SEP reset release under SMU
    transport: SMU-SEP reset and memory passthrough ports (sep_reset_n_o / sep_cpu_reset_n_o / TCM)
    consumer: SEP CPU execution progress observability at the SMU boundary
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 2 (Real SEP RTL Under the SMU) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_reset_n_o / sep_cpu_reset_n_o / sep memory)
    @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/sep/doc/cpu.adoc @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 555f3943404c8c593928d8238d91967b004c14f823a2653847f307e046e77fd1
  scenarios:
  - key: SEP-BOOT.S1
    intent: SEP TCM preload plus reset release yields observable CPU progress under SMU (SEP=1).
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Feature 2 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep-tcm-boot-progress
      random_knobs: []
      coverage_artifact: null
  - key: SEP-BOOT.S2
    intent: sep_reset_n_o and sep_cpu_reset_n_o reflect post fuse-sense / WDT combine at SMU boundary.
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_reset_n_o / sep_cpu_reset_n_o) @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sep-reset-exports
      random_knobs: []
      coverage_artifact: null
- key: SMC-AXI-LITE-SHIMS
  title: SMC AXI-Lite shim ports at SMU boundary
  intent: SMC AXI-Lite external shims (PLL/PVT/GPIO/eFuse/extension) are presented on SMU top ports for
    external peripheral control.
  triad:
    producer: SMC fabric AXI-Lite masters for shim/peripheral control
    transport: SMU top axil_pll/pvt/gpio/efuse and smc_external ports
    consumer: external PLL/PVT/GPIO/eFuse/adopter peripheral shims
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (SMC AXI-Lite shims) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (axil_pll/pvt / smc_external) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: f3262da0c1a95e86fbd0d4e62a4eba5ca51c407e66ef0f7bfe69c073ad2dbddd
  scenarios:
  - key: SMC-AXI-LITE-SHIMS.S1
    intent: SMC AXI-Lite shim request/response handshake completes on at least one SMU-exported shim port
      (e.g. axil_pll or axil_pvt).
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (axil_pll / axil_pvt) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (SMC AXI-Lite shims) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - axil-shim-handshake
      random_knobs: []
      coverage_artifact: null
  - key: SMC-AXI-LITE-SHIMS.S2
    intent: Unused smc_external port policy expects DECERR tie-off when unused.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (smc_external_resp_i — Tie to DECERR if unused)
      @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - smc-external-decerr-tieoff
      random_knobs: []
      coverage_artifact: null
- key: DTP-IJTAG-SCAN
  title: DTP iJTAG/BSR/DFT/DFD scan host ports
  intent: DTP exports BSR and iJTAG DFD/DFT secure/non-secure scan host controls at the SMU boundary (distinct
    from STAP SMC/SEP hosts).
  triad:
    producer: JTAG/iJTAG scan operations in DTP
    transport: jtag_bsr / jtag_dfd / jtag_dft host_scan SMU ports
    consumer: external scan chains loopback or scan model
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (BSR / STAP / iJTAG scan) / §Sub-Blocks (u_dtp) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/dtp/doc/overview.adoc §iJTAG Support / §Boundary Scan @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (jtag_bsr_host_scan_*) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: b628fb5bd6abc3b4f3a28a9a6ab096180b5bb49f75b8d9c9c3cc46b6d027da06
  scenarios:
  - key: DTP-IJTAG-SCAN.S1
    intent: BSR host scan path is electrically present under PTAP EXTEST/BSR enable family.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (jtag_bsr_host_scan_*) @2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/dtp/doc/overview.adoc §Boundary Scan @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - bsr-scan-port
      random_knobs: []
      coverage_artifact: null
  - key: DTP-IJTAG-SCAN.S2
    intent: DFD/DFT iJTAG host scan ports are present for secure and non-secure chains at SMU.
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (BSR / STAP / iJTAG scan) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    - hw/sys/dtp/doc/overview.adoc §iJTAG Support @2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - ijtag-dfd-dft-ports
      random_knobs: []
      coverage_artifact: null
interactions:
- key: INT-MBX-CHALLENGE-IRQ
  features:
  - SMU-MBX-CHALLENGE
  - SEP-MBX-IRQ-SMC
  - SMC-MBX-CHANNELS
  intent: Mailbox challenge-response must raise SEP→SMC mailbox interrupts on the documented vector bits
    during the exchange.
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-response) / §Feature 5 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/interrupts.adoc §Exact Indexed Map (SEP mailbox interrupt 0–7) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 16264e24c6bf7f8388e2891f6ac4bc24434910f8a30f4897b3722b4346052440
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - exchange=complete
    - irq=sep_mbx_seen
    random_knobs: []
    coverage_artifact: null
- key: INT-FEAT-CTRL-DTP-GATE
  features:
  - SEP-LC-FEAT-EXPORT
  - DTP-FEAT-GATE
  - DTP-JTAG2AXI-SMC
  intent: SEP feat_ctrl export must gate DTP JTAG2AXI/STAP debug resources per lifecycle policy.
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Security Considerations / §Error Handling (Lifecycle-gated debug) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/dtp/doc/jtag.adoc §Security Integration @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 47b16e5ed46a504e1e939437a1807c7621b398bb22bd9abce8796366acaf36a6
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - policy=disabled,jtag2axi=0
    - policy=enabled,jtag2axi=1
    random_knobs: []
    coverage_artifact: null
- key: INT-PWRGOOD-DTP-POR
  features:
  - SMC-PWRGOOD-DTP-POR
  - DTP-JTAG-PTAP
  - SMU-PORT-CLK-RST
  intent: SMC power-good stability must qualify DTP TAP POR so power-good loss resets JTAG/TDR independently
    of TRST.
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (pwr_on_rst_ni = powergood_stable) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/clk_rst.adoc §Reset Architecture @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 0bf82dbbb212143374ae7501b6be0f7b2f574ca53202e5a04f41bc86bc7aacbf
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - powergood=0,tap=reset
    - powergood=1,tap=runnable
    random_knobs: []
    coverage_artifact: null
- key: INT-CLKSTOP-SMC-CLA
  features:
  - DTP-CLKSTOP-AGG
  - SMC-DTP-CSR
  intent: DTP clock-stop aggregation must include the SMC-reserved CLA port and expose CLA-only status
    distinctly from JTAG stop.
  spec_refs:
  - hw/sys/dtp/doc/clock_stop.adoc §Clock Stop @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 6 / §Specifications (port [0] reserved) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 3a74600f728cb5ecb74d129ba4414efa71ad04343af94e5cfa9820c4cc552154
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - src=smc_cla,stop=1
    - src=jtag,cla_status=0
    random_knobs: []
    coverage_artifact: null
- key: INT-SEP0-OTP-ERR
  features:
  - SMU-SEP-PARAM
  - DTP-OTP-AXIL
  intent: In SEP=0 configuration, DTP SEP-OTP AXI-Lite accesses must hit the SMU error slave (DECERR/0xBADCAB1E).
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP=0 SEP-OTP) / §Sub-Blocks (u_sep_otp_axil_err_slv)
    @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 9846465f50bf3c56fc80e7a585c3324f34c99622237a5f7d33cc00a934eb0ca6
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - sep=0
    - resp=DECERR
    - rdata=0xBADCAB1E
    random_knobs: []
    coverage_artifact: null
- key: INT-ALIAS-VS-XBAR-SMC
  features:
  - SMU-SEP-SMC-ALIAS
  - SMU-XBAR-CONNECT
  - SEP-SYSIF-SMU-XBAR
  intent: SEP accesses to the fixed 0x4000_0000 SMC window must use the dedicated alias remap bypass,
    distinct from aperture-matched xbar routes.
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (SEP→SMC alias remap bypasses the crossbar) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/memory_map.adoc §Memory Map (SMC Resources 0x4000_0000) @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 5320819df32b5a2527d480abe8e17c4e386e88b3cf110f4bfffd8ade2c5ff070
  requires: CONNECTIVITY
  coverage:
    method: DIRECTED
    required_cells:
    - path=alias_bypass
    - path=xbar_aperture
    random_knobs: []
    coverage_artifact: null
- key: INT-BOOT-STALL-INTEROP
  features:
  - DTP-BOOT-STALL
  - SMU-MBX-CHALLENGE
  intent: DTP boot-stall must be able to hold SEP while SMC progresses, then release for mailbox interop
    completion.
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 5 (SMC-executes-while-SEP-stalled) / §Feature 3 (boot-stall) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: ad6291de3cb23b62efad867bb717b4dc313347c758c9ece167afb150ce5c6847
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - stall=hold_sep
    - stall=release
    - mbx=complete
    random_knobs: []
    coverage_artifact: null
- key: INT-FUSE-SENSE-BOOT
  features:
  - SEP-FUSE-SENSE-HS
  - SMC-BOOT
  - SEP-BOOT
  intent: Fuse-sense handshake participates in SMC/SEP security bring-up before/with boot progression.
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Security Considerations (fuse-sense handshake) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 1 / §Feature 2 @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/cpu.adoc §Boot Sequence Integration @2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 95a4529ac8fc6e1089981af000f3c9a62cf33bd3594b5a44010026b0c535d3df
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - fuse-sense-then-boot
    random_knobs: []
    coverage_artifact: null
- key: INT-XBAR-APERTURE-INTEROP
  features:
  - SMU-XBAR-APERTURE
  - SMU-MBX-CHALLENGE
  - SMU-XBAR-CONNECT
  intent: Mailbox interop depends on crossbar connectivity plus programmed SEP/SMC apertures (Feature
    5 x Feature 4).
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 5 (xbar programmability) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (CSR-programmed apertures) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 15981fd676efcba28542d2c76cdda111b8f6821f1e1877a62520ffc460488800
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - aperture-plus-mailbox-routing
    random_knobs: []
    coverage_artifact: null
---
# SMU_ALL Spec Feature List — amendment candidate (artifact_revision 3)

## Amendment (reverse_diff CONFIRMED-OMISSION)

Peer audit reverse inventory confirmed six in-scope keys absent from approved FL r2.
Option B honesty: all six are named by pinned SMU_SPEC / port_table at the SMU boundary — **ADD** (not OUT-OF-SCOPE-PERMANENT).

| Key | Disposition | Scenarios / notes |
|---|---|---|
| `SMC-BOOT` | **ADD** | S1 ROM fetch LIVE; S2 ext_boot_seq gate LIVE; S3 SEP=0 boot LIVE |
| `SEP-BOOT` | **ADD** | S1 TCM boot LIVE; S2 sep_reset exports LIVE |
| `SMC-AXI-LITE-SHIMS` | **ADD** | S1 axil shim handshake LIVE; S2 smc_external DECERR CONNECTIVITY |
| `DTP-IJTAG-SCAN` | **ADD** | S1 BSR host CONNECTIVITY; S2 DFD/DFT iJTAG CONNECTIVITY (STAP remains `DTP-STAP-SMC-SEP`) |
| `INT-FUSE-SENSE-BOOT` | **ADD** | cross `SEP-FUSE-SENSE-HS` × `SMC-BOOT` × `SEP-BOOT` |
| `INT-XBAR-APERTURE-INTEROP` | **ADD** | cross `SMU-XBAR-APERTURE` × `SMU-MBX-CHALLENGE` × `SMU-XBAR-CONNECT` |

Boundary-rejected this amend: **none**.

Draft never bless (`status: candidate`). Unaffected feature/interaction `record_sha256` values unchanged.

## Feature index (delta)

**SMC-BOOT — SMC boot and firmware execution under SMU:** SMC boots from ROM, releases resets, runs firmware, and reports status via scratch/mailbox paths.
  - Triad: producer SMC ROM/firmware after reset/fuse gating | transport SMC CPU/ROM/scratch + SMU ports | consumer observable progress / pass-fail
  - Scenarios:
    - SMC-BOOT.S1 [REQUIRES: LIVE]: ROM fetch + execution progress
    - SMC-BOOT.S2 [REQUIRES: LIVE]: ext_boot_seq_done_i gates reset release
    - SMC-BOOT.S3 [REQUIRES: LIVE]: SEP=0 still boots SMC

**SEP-BOOT — Real SEP boot under SMU:** With SEP=1, real SEP RTL boots from TCM/ROM with observable CPU progress.
  - Scenarios:
    - SEP-BOOT.S1 [REQUIRES: LIVE]: TCM preload + reset release → CPU progress
    - SEP-BOOT.S2 [REQUIRES: LIVE]: sep_reset_n_o / sep_cpu_reset_n_o exports

**SMC-AXI-LITE-SHIMS — SMC AXI-Lite shim ports:** PLL/PVT/GPIO/eFuse/extension shims on SMU top.
  - Scenarios:
    - SMC-AXI-LITE-SHIMS.S1 [REQUIRES: LIVE]: shim handshake
    - SMC-AXI-LITE-SHIMS.S2 [REQUIRES: CONNECTIVITY]: smc_external DECERR unused policy

**DTP-IJTAG-SCAN — BSR/iJTAG scan hosts:** BSR and DFD/DFT iJTAG host ports (not STAP).
  - Scenarios:
    - DTP-IJTAG-SCAN.S1 [REQUIRES: CONNECTIVITY]: BSR host present
    - DTP-IJTAG-SCAN.S2 [REQUIRES: CONNECTIVITY]: DFD/DFT iJTAG ports present

## Interactions (delta)

- INT-FUSE-SENSE-BOOT [FEATURES: [SEP-FUSE-SENSE-HS, SMC-BOOT, SEP-BOOT]] [REQUIRES: LIVE]: Fuse-sense then boot bring-up.
- INT-XBAR-APERTURE-INTEROP [FEATURES: [SMU-XBAR-APERTURE, SMU-MBX-CHALLENGE, SMU-XBAR-CONNECT]] [REQUIRES: LIVE]: Aperture + xbar + mailbox joint routing.

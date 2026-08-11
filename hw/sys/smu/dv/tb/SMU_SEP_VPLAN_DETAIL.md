---
schema: dv-quality/v1
artifact: checkbox-cards
artifact_revision: 1
content_sha256: fdcf847f63904b5803f7df0934eab903d4c6f5f860e84359e962456ce61cff19
ip: SMU_SEP
milestone: P2
status: candidate
pin_revision: 1
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/index.adoc
  revision: 06ed854b2f40c7a31468fdcd6e535d21378ede5e
- path: hw/sys/sep/doc/introduction.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/overview.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/crypto.adoc
  revision: 06ed854b2f40c7a31468fdcd6e535d21378ede5e
- path: hw/sys/sep/doc/periphs.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/memory_map.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/lifecycle_controller.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/security_disable.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/test_mode.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/token_processing.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/index.adoc
  revision: 06ed854b2f40c7a31468fdcd6e535d21378ede5e
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
source_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
generated_by:
  human_id: minshaoho
  run_id: smu-sep-skill1-20260807
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: false
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-07T17:45:00+08:00'
approved_by: null
approved_at: null
cards:
- id: SEP_SMU_001
  anchor: smu_sep_smoke_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 212310b25f9a0fc6ca1de428f5ec15ad2241822992601f896156f9a8fabb6217
  approved_by: null
  approved_at: null
  category: SEP boot/reset/fuse foundation
  owns: Boot/reset/fuse/ROM foundation only (no xbar/mailbox/filter)
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: cc12d2c296a455e20de80c7a0e6de9688d8eb749fe753ae7b300cd7fe070a927
    allocated_scenarios:
    - SEP-COMPOSE-ENABLE.S1
    - SEP-RESET-CONTROL.S1
    - SEP-RESET-CONTROL.S2
    - SEP-RESET-CONTROL.S3
    - SEP-FUSE-SENSE-HANDSHAKE.S1
    - SEP-ROM-BOOT-ENABLE.S1
    - SEP-ROM-BOOT-ENABLE.S2
    - INT-FUSE-AUTH-TO-ROM
  description:
    producer: powergood/cold-reset top pins into SMC reset unit; SEP=1 composition
    transport: rst_primary_smc_clk_no and fuse-sense authorization into SEP reset/boot path
    consumer: SEP EL2 retires BL0 Boot ROM after ordered fuse authorization
  steps:
  - id: S1
    text: Hold primary reset; sample SEP held (rst_ni=0, no retire) for bounded window
    derived_from:
    - SEP-RESET-CONTROL.S1
  - id: S2
    text: Confirm SEP instance composed under SEP=1 (not tied-off)
    derived_from:
    - SEP-COMPOSE-ENABLE.S1
  - id: S3
    text: Release primary reset; observe release edge and cpu-reset chain complete
    derived_from:
    - SEP-RESET-CONTROL.S2
    - SEP-RESET-CONTROL.S3
  - id: S4
    text: Observe SMC fuse_sense_done before SEP fuse completion
    derived_from:
    - SEP-FUSE-SENSE-HANDSHAKE.S1
  - id: S5
    text: ext_boot_seq_done gate satisfied; first BL0 ROM retire at Boot ROM base
    derived_from:
    - SEP-ROM-BOOT-ENABLE.S1
    - SEP-ROM-BOOT-ENABLE.S2
    - INT-FUSE-AUTH-TO-ROM
  - id: S6
    text: 'TIMEOUT: bounded waits for reset/fuse/ROM with last-state fail'
    derived_from: []
  randomization: DIRECTED rollup of allocated boot/reset/fuse scenarios + INT-FUSE-AUTH-TO-ROM
  observation: cycle-accurate smu_clk sampling for reset/order; retire events for Boot ROM PC
  checkers:
  - id: CHK-HELD-RESET
    checks_steps:
    - S1
    proves:
    - SEP-RESET-CONTROL
    covers:
    - SEP-RESET-CONTROL.S1
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
    proof: u_sep.rst_ni=0 across >=64 samples; retire_valid=0; inst_count=0
    fail_on: reset high, any retire, X, or wrong sample count
    lifecycle: null
  - id: CHK-COMPOSE-SEP1
    checks_steps:
    - S2
    proves:
    - SEP-COMPOSE-ENABLE
    covers:
    - SEP-COMPOSE-ENABLE.S1
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters SEP
    proof: SEP hierarchy present; SEP outputs not constant-tied as in SEP=0
    fail_on: SEP absent/tied-off under SEP=1
    lifecycle: null
  - id: CHK-RESET-RELEASE
    checks_steps:
    - S3
    proves:
    - SEP-RESET-CONTROL
    covers:
    - SEP-RESET-CONTROL.S2
    - SEP-RESET-CONTROL.S3
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
    proof: u_sep.rst_ni 0->1; sep_cpu_reset_n rises; no retire before cpu_reset release
    fail_on: missing release, retire-before-release, X
    lifecycle: null
  - id: CHK-SMC-FUSE-AUTH
    checks_steps:
    - S4
    proves:
    - SEP-FUSE-SENSE-HANDSHAKE
    covers:
    - SEP-FUSE-SENSE-HANDSHAKE.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/port_table.adoc smc_fuse_sense_done_i
    proof: smc fuse_sense_done observed =1 before SEP fuse_sense_done
    fail_on: SEP fuse done without prior SMC fuse done; X
    lifecycle: null
  - id: CHK-BL0-FETCH
    checks_steps:
    - S5
    proves:
    - SEP-ROM-BOOT-ENABLE
    covers:
    - SEP-ROM-BOOT-ENABLE.S1
    - SEP-ROM-BOOT-ENABLE.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/cpu.adoc Boot ROM
    proof: ext_boot_seq_done_i=1; first retired pc in Boot ROM window 0x1004_0000
    fail_on: wrong/missing PC, fetch before gate, timeout
    lifecycle: null
  - id: CHK-FUSE-ROM-ORDER
    checks_steps:
    - S5
    proves:
    - SEP-FUSE-SENSE-HANDSHAKE
    - SEP-ROM-BOOT-ENABLE
    covers:
    - INT-FUSE-AUTH-TO-ROM
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Security Considerations; hw/sys/sep/doc/periphs.adoc Fuse
      Controller
    proof: SMC_FUSE_DONE < SEP_FUSE_DONE < FIRST_BL0_ROM_RETIRE with timestamps
    fail_on: any pair out of order or missing term
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    - S5
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: HELD_RESET < COMPOSE_CHECK < RESET_RELEASE < SMC_FUSE < BL0_FETCH
    fail_on: PASS with any term missing/out of order
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S6
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: each wait logs finite bound + fail-on-expiry + last-state diagnostic
    fail_on: unbounded wait or expiry without failure
    lifecycle: null
  guardrails: passive hierarchical reads allowed; NO internal write/force/deposit; firmware-first stimulus
    per pinned policy
  blockers: []
- id: SEP_SMU_002
  anchor: smu_fuse_sense_handshake_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 020b9f0a623cd3c4899fb61a70c6a8cd9e8eed3b0ef775860171cb7119151371
  approved_by: null
  approved_at: null
  category: SEP fuse-sense export
  owns: sep_fuse_sense_done_o export only
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: d3cc7c418555098616072741cdd339a79550bcf4731fb7d86ae1fe39351c874a
    allocated_scenarios:
    - SEP-FUSE-SENSE-HANDSHAKE.S2
  description:
    producer: SEP fuse-sense completion
    transport: sep_fuse_sense_done_o at SMU
    consumer: system integration observes export
  steps:
  - id: S1
    text: After SMC/SEP fuse sequence, sample sep_fuse_sense_done_o=1
    derived_from:
    - SEP-FUSE-SENSE-HANDSHAKE.S2
  - id: S2
    text: TIMEOUT bounded wait for export
    derived_from: []
  randomization: DIRECTED rollup of SEP-FUSE-SENSE-HANDSHAKE.S2
  observation: SMU port sample of sep_fuse_sense_done_o
  checkers:
  - id: CHK-SEP-FUSE-EXPORT
    checks_steps:
    - S1
    proves:
    - SEP-FUSE-SENSE-HANDSHAKE
    covers:
    - SEP-FUSE-SENSE-HANDSHAKE.S2
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/port_table.adoc sep_fuse_sense_done_o
    proof: sep_fuse_sense_done_o=1 after SEP fuse completion
    fail_on: stuck-0, X, or export before SEP fuse done
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: SEP_FUSE_DONE before EXPORT_SAMPLE
    fail_on: PASS without ordered export
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry + last state
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_003
  anchor: smu_sep_smc_alias_remap_consistency_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 6cdbf2f24007e4dcaeadab378a93983ed1ae19f41d7c8c437b29193a47e1083e
  approved_by: null
  approved_at: null
  category: SEP→SMC alias remap
  owns: Alias remap path and SMC aperture bound only
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 8c9c8224a7a3f656f5d302c090f9985c9ebbca485f56982e3953d3f080decfcb
    allocated_scenarios:
    - SEP-SMC-ALIAS-REMAP.S1
    - SEP-SMC-ALIAS-REMAP.S2
    - SEP-SMC-ALIAS-REMAP.S3
  description:
    producer: SEP master access in 0x4000_0000 SMC window
    transport: sep_ext_to_smc_axi + axi_window_remap
    consumer: SMC sep_axi_in sees base+offset
  steps:
  - id: S1
    text: Issue SEP read/write at 0x4000_0000+offset; compare SMC target address
    derived_from:
    - SEP-SMC-ALIAS-REMAP.S1
  - id: S2
    text: Confirm traffic on dedicated sep_ext_to_smc (not xbar sep_out)
    derived_from:
    - SEP-SMC-ALIAS-REMAP.S2
  - id: S3
    text: Access outside SMC REGION_SIZE is not accepted as alias hit
    derived_from:
    - SEP-SMC-ALIAS-REMAP.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of SEP-SMC-ALIAS-REMAP scenarios
  observation: AXI monitor on sep_ext_to_smc and SMC target
  checkers:
  - id: CHK-ALIAS-HIT
    checks_steps:
    - S1
    proves:
    - SEP-SMC-ALIAS-REMAP
    covers:
    - SEP-SMC-ALIAS-REMAP.S1
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md SEP to SMC alias remap
    proof: addr 0x4000_0000+off maps to SMC 0x0+off with OKAY data match
    fail_on: wrong address, DECERR/SLVERR, data mismatch
    lifecycle: null
  - id: CHK-ALIAS-BYPASS
    checks_steps:
    - S2
    proves:
    - SEP-SMC-ALIAS-REMAP
    covers:
    - SEP-SMC-ALIAS-REMAP.S2
    proof_class: CONNECTIVITY
    expect_source: hw/sys/sep/doc/port_table.adoc sep_ext_to_smc_axi_req_o
    proof: sep_ext_to_smc_axi_req toggles; smu_axi_xbar sep_out idle for this access
    fail_on: traffic only on xbar sep_out
    lifecycle: null
  - id: CHK-SMC-APERTURE-BOUND
    checks_steps:
    - S3
    proves:
    - SEP-SMC-ALIAS-REMAP
    covers:
    - SEP-SMC-ALIAS-REMAP.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/fabric.adoc GLOBAL_BASE REGION_SIZE
    proof: out-of-REGION_SIZE alias attempt not decoded as valid SMC hit
    fail_on: out-of-bound accepted as hit
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: ALIAS_HIT observed with BYPASS evidence
    fail_on: PASS on xbar-only path
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_004
  anchor: smu_sep_alias_mailbox_interrupt_probe_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 400a957bbe790cbc373198347c1704ff4d116c12f06cf36f5ad0bebc83650839
  approved_by: null
  approved_at: null
  category: SEP mailbox interop
  owns: Mailbox data + IRQ crossing only (alias used as transport)
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 3a594b390d6cf26f85bf731c93727dd00d34a41e3630055e2dac4845b2ac5b27
    allocated_scenarios:
    - SEP-MAILBOX-IRQ-TO-SMC.S1
    - SEP-MAILBOX-IRQ-TO-SMC.S2
    - SEP-MAILBOX-IRQ-TO-SMC.S3
    - SEP-MAILBOX-DATA-EXCHANGE.S1
    - SEP-MAILBOX-DATA-EXCHANGE.S2
    - SEP-MAILBOX-DATA-EXCHANGE.S3
    - INT-ALIAS-MAILBOX
  description:
    producer: SMC/SEP mailbox writers
    transport: alias-reachable mailbox + smc_mailbox_interrupt_o
    consumer: peer mailbox payload + SMC IRQ bits
  steps:
  - id: S1
    text: SMC writes token to outbound mailbox; SEP reads inbound payload
    derived_from:
    - SEP-MAILBOX-DATA-EXCHANGE.S1
    - INT-ALIAS-MAILBOX
  - id: S2
    text: SEP writes response; SMC observes payload
    derived_from:
    - SEP-MAILBOX-DATA-EXCHANGE.S2
  - id: S3
    text: SEP accesses 64-bit mailbox word as two 32-bit halves
    derived_from:
    - SEP-MAILBOX-DATA-EXCHANGE.S3
  - id: S4
    text: Assert mailbox event; SMC IRQ bit set then cleared
    derived_from:
    - SEP-MAILBOX-IRQ-TO-SMC.S1
    - SEP-MAILBOX-IRQ-TO-SMC.S2
  - id: S5
    text: Exercise representative multi-channel IRQ fan-out
    derived_from:
    - SEP-MAILBOX-IRQ-TO-SMC.S3
  - id: S6
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of mailbox scenarios + INT-ALIAS-MAILBOX
  observation: mailbox payload scoreboard; SMC IRQ bit samples
  checkers:
  - id: CHK-MBX-SMC-TO-SEP
    checks_steps:
    - S1
    proves:
    - SEP-MAILBOX-DATA-EXCHANGE
    covers:
    - SEP-MAILBOX-DATA-EXCHANGE.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc Mailboxes
    proof: SEP inbound mailbox reads exact SMC-written token word(s)
    fail_on: wrong/missing payload
    lifecycle: null
  - id: CHK-MBX-SEP-TO-SMC
    checks_steps:
    - S2
    proves:
    - SEP-MAILBOX-DATA-EXCHANGE
    covers:
    - SEP-MAILBOX-DATA-EXCHANGE.S2
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Feature 5
    proof: SMC mailbox reads exact SEP response word(s)
    fail_on: wrong/missing response
    lifecycle: null
  - id: CHK-MBX-64B-HALVES
    checks_steps:
    - S3
    proves:
    - SEP-MAILBOX-DATA-EXCHANGE
    covers:
    - SEP-MAILBOX-DATA-EXCHANGE.S3
    proof_class: DECODE
    expect_source: hw/sys/sep/doc/fabric.adoc Mailboxes 64-bit data
    proof: low/high 32-bit halves reconstruct the 64-bit write
    fail_on: half mismatch
    lifecycle: null
  - id: CHK-MBX-IRQ-SET-CLR
    checks_steps:
    - S4
    proves:
    - SEP-MAILBOX-IRQ-TO-SMC
    covers:
    - SEP-MAILBOX-IRQ-TO-SMC.S1
    - SEP-MAILBOX-IRQ-TO-SMC.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt
    proof: lifecycle set→observed→cleared→checked_cleared on documented IRQ bit
    fail_on: missing assert/clear or wrong bit
    lifecycle:
      set: mailbox event drives smc_mailbox_interrupt_o[n]=1
      observed: SMC peripheral_interrupts maps bit n as documented
      cleared: after mailbox clear/ack, interrupt_o[n]=0
      checked_cleared: re-sample IRQ bit remains 0
  - id: CHK-MBX-IRQ-MULTI
    checks_steps:
    - S5
    proves:
    - SEP-MAILBOX-IRQ-TO-SMC
    covers:
    - SEP-MAILBOX-IRQ-TO-SMC.S3
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md SEP mailboxes=8
    proof: '>=2 distinct channels assert distinct SMC IRQ bits'
    fail_on: single-channel-only or bit collision
    lifecycle: null
  - id: CHK-ALIAS-MAILBOX-INT
    checks_steps:
    - S1
    proves:
    - SEP-SMC-ALIAS-REMAP
    - SEP-MAILBOX-DATA-EXCHANGE
    covers:
    - INT-ALIAS-MAILBOX
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md alias remap; Mailbox challenge-response
    proof: mailbox payload exchange uses alias-remap path (sep_ext_to_smc active)
    fail_on: exchange succeeds only via non-alias path
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    - S5
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: PAYLOAD_IN < PAYLOAD_OUT < IRQ_SET < IRQ_CLR
    fail_on: PASS without payload+IRQ evidence
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S6
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force; alias path required for INT checker
  blockers: []
- id: SEP_SMU_005
  anchor: smu_sep_smc_xbar_programmable_addr_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 3ea7a684f73617be84f51ef253db466277ca84bd380df42327e1a494394e0e24
  approved_by: null
  approved_at: null
  category: SEP SMU xbar sysif/aperture/connectivity
  owns: SMU xbar SEP ports only (not alias path)
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: bb862432d04234c6fe5f32cd20c8f5a1d95019b1ddfeeb1a59fa8be8390e7f66
    allocated_scenarios:
    - SEP-XBAR-SYSIF.S1
    - SEP-XBAR-SYSIF.S2
    - SEP-XBAR-SYSIF.S3
    - SEP-XBAR-APERTURE.S1
    - SEP-XBAR-APERTURE.S2
    - SEP-XBAR-CONNECTIVITY.S1
    - SEP-XBAR-CONNECTIVITY.S2
    - SEP-XBAR-CONNECTIVITY.S3
  description:
    producer: SEP/ext masters on SMU xbar
    transport: smu_axi_xbar apertures + connectivity
    consumer: legal targets OKAY; illegal DECERR/blocked
  steps:
  - id: S1
    text: SEP via xbar reaches SMC (sep_out→smc_in)
    derived_from:
    - SEP-XBAR-SYSIF.S1
  - id: S2
    text: ext_in reaches SEP (ext_in→sep_in)
    derived_from:
    - SEP-XBAR-SYSIF.S2
  - id: S3
    text: ID-width conversion preserves response routing
    derived_from:
    - SEP-XBAR-SYSIF.S3
  - id: S4
    text: Programmed SEP aperture hit
    derived_from:
    - SEP-XBAR-APERTURE.S1
  - id: S5
    text: Unmatched ext_in returns DECERR
    derived_from:
    - SEP-XBAR-APERTURE.S2
  - id: S6
    text: sep_out legal targets only; no self sep_in; ATOP rejected
    derived_from:
    - SEP-XBAR-CONNECTIVITY.S1
    - SEP-XBAR-CONNECTIVITY.S2
    - SEP-XBAR-CONNECTIVITY.S3
  - id: S7
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of xbar scenarios (SF-006 blocks exact CSR field constants — use SPEC-named
    apertures only)
  observation: AXI monitors on xbar ports; response codes
  checkers:
  - id: CHK-SEP-TO-SMC-XBAR
    checks_steps:
    - S1
    proves:
    - SEP-XBAR-SYSIF
    covers:
    - SEP-XBAR-SYSIF.S1
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing
    proof: SEP xbar access to SMC returns OKAY with expected data
    fail_on: DECERR/timeout/wrong data
    lifecycle: null
  - id: CHK-EXT-TO-SEP-XBAR
    checks_steps:
    - S2
    proves:
    - SEP-XBAR-SYSIF
    covers:
    - SEP-XBAR-SYSIF.S2
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing
    proof: ext_in access to SEP aperture returns OKAY
    fail_on: DECERR/timeout
    lifecycle: null
  - id: CHK-ID-WIDTH
    checks_steps:
    - S3
    proves:
    - SEP-XBAR-SYSIF
    covers:
    - SEP-XBAR-SYSIF.S3
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Crossbar ID widths
    proof: response ID routes to issuing SEP master after 10→6 conversion
    fail_on: orphaned/misrouted response
    lifecycle: null
  - id: CHK-APERTURE-HIT
    checks_steps:
    - S4
    proves:
    - SEP-XBAR-APERTURE
    covers:
    - SEP-XBAR-APERTURE.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc SEP_GLOBAL_BASE_ADDR
    proof: programmed aperture admits intended SEP region (OKAY)
    fail_on: hit becomes DECERR
    lifecycle: null
  - id: CHK-EXT-IN-DECERR
    checks_steps:
    - S5
    proves:
    - SEP-XBAR-APERTURE
    covers:
    - SEP-XBAR-APERTURE.S2
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Error Handling Unmapped crossbar
    proof: unmatched ext_in beat returns DECERR
    fail_on: OKAY on unmatched
    lifecycle: null
  - id: CHK-CONNECTIVITY
    checks_steps:
    - S6
    proves:
    - SEP-XBAR-CONNECTIVITY
    covers:
    - SEP-XBAR-CONNECTIVITY.S1
    - SEP-XBAR-CONNECTIVITY.S2
    - SEP-XBAR-CONNECTIVITY.S3
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing
    proof: sep_out→{smc_in,ext_out} only; sep_out→sep_in blocked; ATOP rejected
    fail_on: illegal path OKAY or ATOP accepted
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    - S5
    - S6
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: legal hit and illegal DECERR both observed
    fail_on: PASS with only happy-path OKAY
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S7
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force; exact aperture CSR addresses require SF-006 answer
  blockers:
  - SF-006
- id: SEP_SMU_006
  anchor: smu_lifecycle_security_handoff_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: f7fbc1d1459a49ea2f048b79757e09af7a97842a898edd8177f4a9b7affdd12d
  approved_by: null
  approved_at: null
  category: SEP lifecycle/security handoff
  owns: LC state + feat_ctrl profile + security_disable export
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 5521761a3b5df69c2fbeb0f2c6c82a584764c8c9c869f7ad36097a1caf58d41b
    allocated_scenarios:
    - SEP-FEAT-CTRL-EXPORT.S1
    - SEP-LC-STATE-EXPORT.S1
    - SEP-LC-STATE-EXPORT.S3
    - SEP-SECURITY-DISABLE-EXPORT.S1
    - INT-FEAT-LC-HANDOFF
  description:
    producer: SEP LCC outputs
    transport: lc_state_o / feat_ctrl_o / security_disable_o at SMU
    consumer: SMC/DTP observe handoff vector
  steps:
  - id: S1
    text: Sample feat_ctrl_o matches OTP-derived profile
    derived_from:
    - SEP-FEAT-CTRL-EXPORT.S1
  - id: S2
    text: Sample lc_state_o and demote exports
    derived_from:
    - SEP-LC-STATE-EXPORT.S1
    - SEP-LC-STATE-EXPORT.S3
  - id: S3
    text: Sample security_disable_o connectivity
    derived_from:
    - SEP-SECURITY-DISABLE-EXPORT.S1
  - id: S4
    text: Joint handoff observation
    derived_from:
    - INT-FEAT-LC-HANDOFF
  - id: S5
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of lifecycle/security export scenarios + INT-FEAT-LC-HANDOFF
  observation: SMU port samples of lc_state/feat_ctrl/security_disable
  checkers:
  - id: CHK-FEAT-PROFILE
    checks_steps:
    - S1
    proves:
    - SEP-FEAT-CTRL-EXPORT
    covers:
    - SEP-FEAT-CTRL-EXPORT.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/lifecycle_controller.adoc LCC
    proof: feat_ctrl_o equals SPEC LC profile for the loaded shadow state
    fail_on: mismatched/X feat_ctrl
    lifecycle: null
  - id: CHK-LC-EXPORT
    checks_steps:
    - S2
    proves:
    - SEP-LC-STATE-EXPORT
    covers:
    - SEP-LC-STATE-EXPORT.S1
    - SEP-LC-STATE-EXPORT.S3
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/port_table.adoc lc_state_o
    proof: lc_state_o tracks SEP encoding; lcc_demote_state_* visible
    fail_on: stuck/X exports
    lifecycle: null
  - id: CHK-SEC-DIS-EXPORT
    checks_steps:
    - S3
    proves:
    - SEP-SECURITY-DISABLE-EXPORT
    covers:
    - SEP-SECURITY-DISABLE-EXPORT.S1
    proof_class: CONNECTIVITY
    expect_source: hw/sys/sep/doc/port_table.adoc security_disable_o
    proof: security_disable_o readable at SMU/SMC boundary (0 or 1, non-X)
    fail_on: X/Z on security_disable_o
    lifecycle: null
  - id: CHK-LC-FEAT-HANDOFF
    checks_steps:
    - S4
    proves:
    - SEP-FEAT-CTRL-EXPORT
    - SEP-LC-STATE-EXPORT
    covers:
    - INT-FEAT-LC-HANDOFF
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Feature 7
    proof: same sample window captures consistent lc_state_o with feat_ctrl_o profile
    fail_on: inconsistent pair
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: all three exports sampled
    fail_on: PASS with any export missing
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S5
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_007
  anchor: smu_feat_ctrl_monitor_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 95142e1f953ac9036c50a69caabd99179019ddc331df25d7739490c7d0dcd08b
  approved_by: null
  approved_at: null
  category: SEP feat_ctrl profile variants
  owns: feat_ctrl fail-closed and demote profiles only
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 76bc4f3e7abdc38bd7977b42a9449dd2ef3d289c22712192752f6b03995d1b59
    allocated_scenarios:
    - SEP-FEAT-CTRL-EXPORT.S2
    - SEP-FEAT-CTRL-EXPORT.S3
  description:
    producer: LCC sigint/demote inputs
    transport: feat_ctrl_o
    consumer: fail-closed zero or demote profile at SMU
  steps:
  - id: S1
    text: Inject/observe signal-integrity fail-closed feat_ctrl_o=0
    derived_from:
    - SEP-FEAT-CTRL-EXPORT.S2
  - id: S2
    text: Program demote; observe altered feat_ctrl profile
    derived_from:
    - SEP-FEAT-CTRL-EXPORT.S3
  - id: S3
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of feat_ctrl variant scenarios
  observation: feat_ctrl_o samples under fault/demote
  checkers:
  - id: CHK-FEAT-FAIL-CLOSED
    checks_steps:
    - S1
    proves:
    - SEP-FEAT-CTRL-EXPORT
    covers:
    - SEP-FEAT-CTRL-EXPORT.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/lifecycle_controller.adoc signal-integrity errors
    proof: on sigint error feat_ctrl_o==0
    fail_on: non-zero feat_ctrl under sigint
    lifecycle: null
  - id: CHK-FEAT-DEMOTE
    checks_steps:
    - S2
    proves:
    - SEP-FEAT-CTRL-EXPORT
    covers:
    - SEP-FEAT-CTRL-EXPORT.S3
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/lifecycle_controller.adoc Demotion 1 and 2
    proof: DEMOTE asserted changes feat_ctrl_o per demote profile; OTP LC_STATE unchanged
    fail_on: no profile change or LC_STATE mutated
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: fail-closed and demote both observed
    fail_on: PASS with only one variant
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_008
  anchor: smu_sep_wdt_reset_to_smc_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 7d8859c1bd517ada1be571044e018ef8ad831142b70d4e0221dce0be68414b2c
  approved_by: null
  approved_at: null
  category: SEP WDT→SMC
  owns: WDT bark vs bite into SMC IRQ path only
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: a347f8f8c308fb394144aa494c1bae6e4a50794664b3bc46f1b5924ad697dd25
    allocated_scenarios:
    - SEP-WDT-RESET-TO-SMC.S1
    - SEP-WDT-RESET-TO-SMC.S2
    - SEP-WDT-RESET-TO-SMC.S3
  description:
    producer: SEP WDT bark/bite
    transport: wdt_timer_rst_req / sep_wdt_reset into SMC
    consumer: SMC SEP-watchdog IRQ indication
  steps:
  - id: S1
    text: Program WDT to bite; observe SMC SEP-watchdog IRQ path
    derived_from:
    - SEP-WDT-RESET-TO-SMC.S1
  - id: S2
    text: Distinguish bark interrupt from bite reset request
    derived_from:
    - SEP-WDT-RESET-TO-SMC.S2
  - id: S3
    text: Confirm clk_sep_wdt_i domain connectivity
    derived_from:
    - SEP-WDT-RESET-TO-SMC.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of WDT scenarios
  observation: SMC IRQ + SEP WDT outputs; SF-007 polarity TBD
  checkers:
  - id: CHK-WDT-BITE-IRQ
    checks_steps:
    - S1
    proves:
    - SEP-WDT-RESET-TO-SMC
    covers:
    - SEP-WDT-RESET-TO-SMC.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/interrupts.adoc SEP watchdog reset
    proof: 'lifecycle: bite sets SMC peripheral SEP-watchdog indication then observable then cleared after
      handling'
    fail_on: missing IRQ or wrong polarity (see SF-007)
    lifecycle:
      set: WDT bite asserts sep_wdt_reset indication into SMC
      observed: SMC peripheral_interrupts SEP-watchdog bit becomes 1 as documented
      cleared: after reset/ack path, indication returns to inactive
      checked_cleared: re-sample inactive
  - id: CHK-WDT-BARK-VS-BITE
    checks_steps:
    - S2
    proves:
    - SEP-WDT-RESET-TO-SMC
    covers:
    - SEP-WDT-RESET-TO-SMC.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/periphs.adoc Watchdog Timer
    proof: bark (first timeout) observable without bite; bite is second-stage request
    fail_on: bark==bite collapsed
    lifecycle: null
  - id: CHK-WDT-CLK
    checks_steps:
    - S3
    proves:
    - SEP-WDT-RESET-TO-SMC
    covers:
    - SEP-WDT-RESET-TO-SMC.S3
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset SEP WDT
    proof: clk_sep_wdt_i toggling while WDT counts
    fail_on: WDT clock stuck
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: bark and bite distinguished
    fail_on: PASS on bark-only
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers:
  - SF-007
- id: SEP_SMU_009
  anchor: smu_sep_outbound_demux_decode_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: a78e5e867d5db5da6a65e11d0eec751a262a07377813ff418c20d8be35bbcf29
  approved_by: null
  approved_at: null
  category: SEP outbound demux
  owns: Outbound demux decode only
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: f2f1e21dd382c07e45594b6fe0e404728bd86680bd4f83d5f6d5305d9ebe392f
    allocated_scenarios:
    - SEP-OUTBOUND-DEMUX.S1
    - SEP-OUTBOUND-DEMUX.S2
    - SEP-OUTBOUND-DEMUX.S3
  description:
    producer: SEP outbound addresses
    transport: system peripherals outbound demux
    consumer: sep_ext_to_smc vs smn_outbound vs local
  steps:
  - id: S1
    text: SMC-window address emerges on sep_ext_to_smc
    derived_from:
    - SEP-OUTBOUND-DEMUX.S1
  - id: S2
    text: Non-SMC external emerges on smn_outbound
    derived_from:
    - SEP-OUTBOUND-DEMUX.S2
  - id: S3
    text: Local SEP resource stays internal
    derived_from:
    - SEP-OUTBOUND-DEMUX.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of outbound demux scenarios
  observation: AXI monitors on sep_ext_to_smc and smn_outbound
  checkers:
  - id: CHK-DEMUX-SMC
    checks_steps:
    - S1
    proves:
    - SEP-OUTBOUND-DEMUX
    covers:
    - SEP-OUTBOUND-DEMUX.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc 0x4000_0000 SMC
    proof: SMC-window access toggles sep_ext_to_smc; smn_outbound idle
    fail_on: wrong egress port
    lifecycle: null
  - id: CHK-DEMUX-SMN
    checks_steps:
    - S2
    proves:
    - SEP-OUTBOUND-DEMUX
    covers:
    - SEP-OUTBOUND-DEMUX.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc routed out to the SMN
    proof: external non-SMC access toggles smn_outbound
    fail_on: wrong egress port
    lifecycle: null
  - id: CHK-DEMUX-LOCAL
    checks_steps:
    - S3
    proves:
    - SEP-OUTBOUND-DEMUX
    covers:
    - SEP-OUTBOUND-DEMUX.S3
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc SEP Local
    proof: local access completes without sep_ext_to_smc/smn_outbound
    fail_on: local leaks outbound
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: all three demux classes observed
    fail_on: PASS with one class only
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_010
  anchor: smu_sep_filter_rule_matrix_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 55859f746655375cea941c1dd750a53f35b05e6bda4f1a1bcd3e523adb2b69a7
  approved_by: null
  approved_at: null
  category: SEP inbound/outbound filters
  owns: Inbound+outbound filter rule matrix only
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: f93595830c2f5846a1b6bfc3095e1ecab24c93b1d49c9a3d7517aa498a237067
    allocated_scenarios:
    - SEP-INBOUND-FILTER.S1
    - SEP-INBOUND-FILTER.S2
    - SEP-INBOUND-FILTER.S3
    - SEP-OUTBOUND-FILTER.S1
    - SEP-OUTBOUND-FILTER.S2
  description:
    producer: external inbound / SEP outbound traffic
    transport: inbound+outbound filters
    consumer: allow OKAY / deny filtered response
  steps:
  - id: S1
    text: Post-POR inbound default deny
    derived_from:
    - SEP-INBOUND-FILTER.S1
  - id: S2
    text: Program allow; matching inbound admitted
    derived_from:
    - SEP-INBOUND-FILTER.S2
  - id: S3
    text: STEE-only rule on STEE remapper region
    derived_from:
    - SEP-INBOUND-FILTER.S3
  - id: S4
    text: Outbound deny rule blocks
    derived_from:
    - SEP-OUTBOUND-FILTER.S1
  - id: S5
    text: Outbound conforming passes
    derived_from:
    - SEP-OUTBOUND-FILTER.S2
  - id: S6
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of filter scenarios
  observation: AXI response codes on filtered paths
  checkers:
  - id: CHK-IN-DEFAULT-DENY
    checks_steps:
    - S1
    proves:
    - SEP-INBOUND-FILTER
    covers:
    - SEP-INBOUND-FILTER.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc block-by-default after POR
    proof: unprogrammed inbound address denied (non-OKAY filter response)
    fail_on: OKAY on default-deny address
    lifecycle: null
  - id: CHK-IN-ALLOW
    checks_steps:
    - S2
    proves:
    - SEP-INBOUND-FILTER
    covers:
    - SEP-INBOUND-FILTER.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc filters based on address NS source ID
    proof: programmed allow yields OKAY to SEP target
    fail_on: still denied after allow
    lifecycle: null
  - id: CHK-IN-STEE
    checks_steps:
    - S3
    proves:
    - SEP-INBOUND-FILTER
    covers:
    - SEP-INBOUND-FILTER.S3
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc STEE remapper
    proof: non-STEE denied to STEE remapper; STEE admitted
    fail_on: non-STEE admitted
    lifecycle: null
  - id: CHK-OUT-DENY
    checks_steps:
    - S4
    proves:
    - SEP-OUTBOUND-FILTER
    covers:
    - SEP-OUTBOUND-FILTER.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc outbound filter
    proof: programmed deny blocks matching outbound
    fail_on: deny rule passes
    lifecycle: null
  - id: CHK-OUT-ALLOW
    checks_steps:
    - S5
    proves:
    - SEP-OUTBOUND-FILTER
    covers:
    - SEP-OUTBOUND-FILTER.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc outbound filter
    proof: conforming outbound completes OKAY
    fail_on: conforming blocked
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    - S5
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: inbound deny+allow and outbound deny+allow all present
    fail_on: PASS without negative control
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S6
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force; negative checks require positive allow control in
    same card
  blockers: []
- id: SEP_SMU_011
  anchor: smu_sep_ap_stee_output_remap_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 5ae71c390d653226f641ceaf2bdfe767d7f985a8dcafd7f78c86fafd87441c8f
  approved_by: null
  approved_at: null
  category: SEP AP/STEE remap
  owns: AP/STEE remap regions only
  evidence_class: strict-e2e
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: a17d31d7b17ee107e9ffa0389633749a760fb4522aecf6350438ed0904544b6a
    allocated_scenarios:
    - SEP-AP-STEE-REMAP.S1
    - SEP-AP-STEE-REMAP.S2
    - SEP-AP-STEE-REMAP.S3
  description:
    producer: SEP writes to AP/STEE remap windows
    transport: AP/STEE remappers
    consumer: translated outbound attributes
  steps:
  - id: S1
    text: Invalid-reset remapper pass-through
    derived_from:
    - SEP-AP-STEE-REMAP.S1
  - id: S2
    text: Programmed AP remap translation
    derived_from:
    - SEP-AP-STEE-REMAP.S2
  - id: S3
    text: Programmed STEE remap translation
    derived_from:
    - SEP-AP-STEE-REMAP.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of AP/STEE remap scenarios
  observation: outbound address monitor
  checkers:
  - id: CHK-REMAP-PASSTHROUGH
    checks_steps:
    - S1
    proves:
    - SEP-AP-STEE-REMAP
    covers:
    - SEP-AP-STEE-REMAP.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc remap entries invalid out of reset
    proof: unprogrammed region behaves as transparent pass-through
    fail_on: spurious translate out of reset
    lifecycle: null
  - id: CHK-AP-REMAP
    checks_steps:
    - S2
    proves:
    - SEP-AP-STEE-REMAP
    covers:
    - SEP-AP-STEE-REMAP.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc AP Remap Region
    proof: programmed AP region output address = input+programmed offset
    fail_on: wrong output address
    lifecycle: null
  - id: CHK-STEE-REMAP
    checks_steps:
    - S3
    proves:
    - SEP-AP-STEE-REMAP
    covers:
    - SEP-AP-STEE-REMAP.S3
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc STEE Remap Region
    proof: STEE-qualified access translates; non-STEE denied/filtered
    fail_on: wrong translate or non-STEE admitted
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: passthrough and both remaps observed
    fail_on: PASS with only passthrough
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_012
  anchor: smu_sep_memory_integrity_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 82d788453504d4e84cd1900482657f0dc96e788e25eed5426479213283620237
  approved_by: null
  approved_at: null
  category: SEP memory ports
  owns: TCM/SRAM/ROM port observability only
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 6ae7087e32d132c45495110974396a95f27293f84a3ea2a6ce01acb1754dd799
    allocated_scenarios:
    - SEP-MEMORY-PORT-OBS.S1
    - SEP-MEMORY-PORT-OBS.S2
    - SEP-MEMORY-PORT-OBS.S3
  description:
    producer: SEP CPU memory accesses
    transport: SMU passthrough TCM/SRAM/ROM ports
    consumer: memory models respond
  steps:
  - id: S1
    text: TCM port activity during execution
    derived_from:
    - SEP-MEMORY-PORT-OBS.S1
  - id: S2
    text: Scratch SRAM port activity
    derived_from:
    - SEP-MEMORY-PORT-OBS.S2
  - id: S3
    text: Boot ROM port serves BL0 window
    derived_from:
    - SEP-MEMORY-PORT-OBS.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of memory port scenarios
  observation: SMU memory port monitors
  checkers:
  - id: CHK-TCM-PORT
    checks_steps:
    - S1
    proves:
    - SEP-MEMORY-PORT-OBS
    covers:
    - SEP-MEMORY-PORT-OBS.S1
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/port_table.adoc sep_cpu_tcm_req_o
    proof: sep_cpu_tcm_req/rsp handshake with data match to programmed pattern
    fail_on: no toggles or data mismatch
    lifecycle: null
  - id: CHK-SRAM-PORT
    checks_steps:
    - S2
    proves:
    - SEP-MEMORY-PORT-OBS
    covers:
    - SEP-MEMORY-PORT-OBS.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc Scratch SRAM
    proof: sep_sram_req/rsp activity with data match
    fail_on: no toggles or mismatch
    lifecycle: null
  - id: CHK-ROM-PORT
    checks_steps:
    - S3
    proves:
    - SEP-MEMORY-PORT-OBS
    covers:
    - SEP-MEMORY-PORT-OBS.S3
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc BL0 ROM
    proof: sep_boot_rom_req in BL0 window during fetch
    fail_on: no ROM port activity during BL0
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: TCM+SRAM+ROM all active
    fail_on: PASS with idle ports
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_013
  anchor: smu_sep_km_otbn_memory_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 060ec707b17edd12422ad00cade158974755b65ac2f3a35570aedb0f50969e07
  approved_by: null
  approved_at: null
  category: SEP crypto ports
  owns: AES/OTBN/KM SMU-visible ports only
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 1f673960a797b0de63b99a00ea399f2076d0c2edb3d443f7114119e0a27f2496
    allocated_scenarios:
    - SEP-CRYPTO-PORT-OBS.S1
    - SEP-CRYPTO-PORT-OBS.S2
    - SEP-CRYPTO-PORT-OBS.S3
  description:
    producer: SEP programmed crypto ops
    transport: crypto CSR/mem ports at SMU
    consumer: boundary-visible completion
  steps:
  - id: S1
    text: AES CSR op completes at boundary
    derived_from:
    - SEP-CRYPTO-PORT-OBS.S1
  - id: S2
    text: OTBN IMEM/DMEM ports toggle under execute
    derived_from:
    - SEP-CRYPTO-PORT-OBS.S2
  - id: S3
    text: KM ROM/SRAM ports observed
    derived_from:
    - SEP-CRYPTO-PORT-OBS.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of crypto port scenarios (not deep KAT)
  observation: SMU crypto/KM/OTBN port monitors
  checkers:
  - id: CHK-AES-PORT
    checks_steps:
    - S1
    proves:
    - SEP-CRYPTO-PORT-OBS
    covers:
    - SEP-CRYPTO-PORT-OBS.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc AES
    proof: AES CSR window access OKAY and status reaches done without requiring KAT digest proof
    fail_on: CSR DECERR or no completion
    lifecycle: null
  - id: CHK-OTBN-PORTS
    checks_steps:
    - S2
    proves:
    - SEP-CRYPTO-PORT-OBS
    covers:
    - SEP-CRYPTO-PORT-OBS.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/crypto.adoc OTBN PKA
    proof: OTBN IMEM/DMEM SMU ports toggle during execute flow
    fail_on: ports idle through execute
    lifecycle: null
  - id: CHK-KM-PORTS
    checks_steps:
    - S3
    proves:
    - SEP-CRYPTO-PORT-OBS
    covers:
    - SEP-CRYPTO-PORT-OBS.S3
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/port_table.adoc sep_km_rom_mem_req_o
    proof: KM ROM/SRAM req ports toggle under KM access
    fail_on: ports stuck
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: AES+OTBN+KM evidence present
    fail_on: PASS with CSR-only smoke
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force; deep crypto OUT of boundary
  blockers: []
- id: SEP_SMU_014
  anchor: smu_sep_dma_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: da1ecf5a985b0328c628cf50ce780083780031e967c44997c86002decd8de61f
  approved_by: null
  approved_at: null
  category: SEP DMA ports
  owns: DMA CSR and TCM preload only
  evidence_class: strict-e2e
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 50b88fd9439b417c2e6aa6ccafdd9ba0c4323d4d342b22bca7b220d7066219a4
    allocated_scenarios:
    - SEP-DMA-PORT-OBS.S1
    - SEP-DMA-PORT-OBS.S2
  description:
    producer: SEP DMA CSR programming
    transport: DMA master on SEP fabric
    consumer: destination memory updated
  steps:
  - id: S1
    text: DMA CSR kickoff
    derived_from:
    - SEP-DMA-PORT-OBS.S1
  - id: S2
    text: DMA TCM preload completes
    derived_from:
    - SEP-DMA-PORT-OBS.S2
  - id: S3
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of DMA scenarios
  observation: DMA CSR + destination memory compare
  checkers:
  - id: CHK-DMA-CSR
    checks_steps:
    - S1
    proves:
    - SEP-DMA-PORT-OBS
    covers:
    - SEP-DMA-PORT-OBS.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/memory_map.adoc DMA CSR
    proof: DMA CSR program OKAY; start bit accepted
    fail_on: CSR DECERR or start ignored
    lifecycle: null
  - id: CHK-DMA-TCM
    checks_steps:
    - S2
    proves:
    - SEP-DMA-PORT-OBS
    covers:
    - SEP-DMA-PORT-OBS.S2
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/fabric.adoc CPU TCM backdoor AXI path
    proof: destination TCM/SRAM contains DMA source pattern after completion
    fail_on: pattern missing/timeout
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: CSR kickoff precedes memory proof
    fail_on: PASS on CSR-only
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_015
  anchor: smu_sep_spi_bridge_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 20cbc67f373b47543649c17db523aea07e6b2316ed385fa5a0f983619251e3b4
  approved_by: null
  approved_at: null
  category: SEP SPI ports
  owns: SPI req/IRQ mux only
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 2a73799a95e8aed199f2bf925c822fd5fe6bb8ac353546ee561b6c5bc250d097
    allocated_scenarios:
    - SEP-SPI-PORT-OBS.S1
    - SEP-SPI-PORT-OBS.S2
  description:
    producer: SEP SPI programming
    transport: sep_io_spi + SPI IRQ mux at SMU
    consumer: pad-facing req / IRQ observed
  steps:
  - id: S1
    text: SPI host drives sep_io_spi_req_o
    derived_from:
    - SEP-SPI-PORT-OBS.S1
  - id: S2
    text: Muxed SPI IRQ observed on SMU path
    derived_from:
    - SEP-SPI-PORT-OBS.S2
  - id: S3
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of SPI port scenarios
  observation: SPI req + IRQ samples
  checkers:
  - id: CHK-SPI-REQ
    checks_steps:
    - S1
    proves:
    - SEP-SPI-PORT-OBS
    covers:
    - SEP-SPI-PORT-OBS.S1
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/port_table.adoc sep_io_spi_req_o
    proof: sep_io_spi_req_o toggles under host transaction
    fail_on: no SPI req activity
    lifecycle: null
  - id: CHK-SPI-IRQ-MUX
    checks_steps:
    - S2
    proves:
    - SEP-SPI-PORT-OBS
    covers:
    - SEP-SPI-PORT-OBS.S2
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smu/doc/port_table.adoc spi_irq_i
    proof: 'lifecycle: SPI IRQ set observed on mux path then cleared'
    fail_on: IRQ missing
    lifecycle:
      set: SPI event asserts IRQ into mux
      observed: SMU spi_irq path =1
      cleared: after clear =0
      checked_cleared: re-sample 0
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: SPI req and IRQ both observed
    fail_on: PASS with req-only
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
- id: SEP_SMU_016
  anchor: smu_sep_efuse_test
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 699c36cfa399ed6450f9aeb3ab28f235393cc52fa9bfb5292810d3724ce62475
  approved_by: null
  approved_at: null
  category: SEP eFuse ports
  owns: eFuse bank/command/JTAG-OTP only
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: e56863a99bd290691364975070aa20348248088cf008450face0d03a6cd8fdf5
    allocated_scenarios:
    - SEP-EFUSE-PORT-OBS.S1
    - SEP-EFUSE-PORT-OBS.S2
    - SEP-EFUSE-PORT-OBS.S3
  description:
    producer: SEP/DTP eFuse transactions
    transport: SMU eFuse passthrough ports
    consumer: eFuse shim completes
  steps:
  - id: S1
    text: eFuse bank-control AXI-Lite completes
    derived_from:
    - SEP-EFUSE-PORT-OBS.S1
  - id: S2
    text: eFuse command handshake completes
    derived_from:
    - SEP-EFUSE-PORT-OBS.S2
  - id: S3
    text: JTAG OTP debug path into SEP eFuse
    derived_from:
    - SEP-EFUSE-PORT-OBS.S3
  - id: S4
    text: TIMEOUT
    derived_from: []
  randomization: DIRECTED rollup of eFuse port scenarios
  observation: eFuse port monitors / AXI-Lite responses
  checkers:
  - id: CHK-EFUSE-BANK
    checks_steps:
    - S1
    proves:
    - SEP-EFUSE-PORT-OBS
    covers:
    - SEP-EFUSE-PORT-OBS.S1
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/port_table.adoc sep_efuse_bank_ctrl_req_o
    proof: bank-control transaction OKAY with expected readback
    fail_on: DECERR/timeout
    lifecycle: null
  - id: CHK-EFUSE-CMD
    checks_steps:
    - S2
    proves:
    - SEP-EFUSE-PORT-OBS
    covers:
    - SEP-EFUSE-PORT-OBS.S2
    proof_class: LIVE
    expect_source: hw/sys/smu/doc/port_table.adoc sep_efuse_shim_command_req_o
    proof: command req/resp handshake completes
    fail_on: handshake timeout
    lifecycle: null
  - id: CHK-EFUSE-JTAG
    checks_steps:
    - S3
    proves:
    - SEP-EFUSE-PORT-OBS
    covers:
    - SEP-EFUSE-PORT-OBS.S3
    proof_class: LIVE
    expect_source: hw/sys/sep/doc/port_table.adoc axil_sep_otp_jtag_req_i
    proof: JTAG-OTP AXI-Lite access completes with OKAY
    fail_on: DECERR/timeout
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: card ordering
    proof: bank+cmd+jtag evidence
    fail_on: PASS with single path only
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: timeout contract
    proof: finite bound + fail-on-expiry
    fail_on: unbounded wait
    lifecycle: null
  guardrails: passive hierarchical reads; no force
  blockers: []
---

# SMU_SEP — VPLAN Detail / Checkbox Cards (candidate)

- 16 cards · status candidate · empty boxes

## SEP_SMU_001 — `smu_sep_smoke_test`
- OWNS: Boot/reset/fuse/ROM foundation only (no xbar/mailbox/filter)
- Allocated: ['SEP-COMPOSE-ENABLE.S1', 'SEP-RESET-CONTROL.S1', 'SEP-RESET-CONTROL.S2', 'SEP-RESET-CONTROL.S3', 'SEP-FUSE-SENSE-HANDSHAKE.S1', 'SEP-ROM-BOOT-ENABLE.S1', 'SEP-ROM-BOOT-ENABLE.S2', 'INT-FUSE-AUTH-TO-ROM']
- Steps: 6 · Checkers: 8

## SEP_SMU_002 — `smu_fuse_sense_handshake_test`
- OWNS: sep_fuse_sense_done_o export only
- Allocated: ['SEP-FUSE-SENSE-HANDSHAKE.S2']
- Steps: 2 · Checkers: 3

## SEP_SMU_003 — `smu_sep_smc_alias_remap_consistency_test`
- OWNS: Alias remap path and SMC aperture bound only
- Allocated: ['SEP-SMC-ALIAS-REMAP.S1', 'SEP-SMC-ALIAS-REMAP.S2', 'SEP-SMC-ALIAS-REMAP.S3']
- Steps: 4 · Checkers: 5

## SEP_SMU_004 — `smu_sep_alias_mailbox_interrupt_probe_test`
- OWNS: Mailbox data + IRQ crossing only (alias used as transport)
- Allocated: ['SEP-MAILBOX-IRQ-TO-SMC.S1', 'SEP-MAILBOX-IRQ-TO-SMC.S2', 'SEP-MAILBOX-IRQ-TO-SMC.S3', 'SEP-MAILBOX-DATA-EXCHANGE.S1', 'SEP-MAILBOX-DATA-EXCHANGE.S2', 'SEP-MAILBOX-DATA-EXCHANGE.S3', 'INT-ALIAS-MAILBOX']
- Steps: 6 · Checkers: 8

## SEP_SMU_005 — `smu_sep_smc_xbar_programmable_addr_test`
- OWNS: SMU xbar SEP ports only (not alias path)
- Allocated: ['SEP-XBAR-SYSIF.S1', 'SEP-XBAR-SYSIF.S2', 'SEP-XBAR-SYSIF.S3', 'SEP-XBAR-APERTURE.S1', 'SEP-XBAR-APERTURE.S2', 'SEP-XBAR-CONNECTIVITY.S1', 'SEP-XBAR-CONNECTIVITY.S2', 'SEP-XBAR-CONNECTIVITY.S3']
- Steps: 7 · Checkers: 8

## SEP_SMU_006 — `smu_lifecycle_security_handoff_test`
- OWNS: LC state + feat_ctrl profile + security_disable export
- Allocated: ['SEP-FEAT-CTRL-EXPORT.S1', 'SEP-LC-STATE-EXPORT.S1', 'SEP-LC-STATE-EXPORT.S3', 'SEP-SECURITY-DISABLE-EXPORT.S1', 'INT-FEAT-LC-HANDOFF']
- Steps: 5 · Checkers: 6

## SEP_SMU_007 — `smu_feat_ctrl_monitor_test`
- OWNS: feat_ctrl fail-closed and demote profiles only
- Allocated: ['SEP-FEAT-CTRL-EXPORT.S2', 'SEP-FEAT-CTRL-EXPORT.S3']
- Steps: 3 · Checkers: 4

## SEP_SMU_008 — `smu_sep_wdt_reset_to_smc_test`
- OWNS: WDT bark vs bite into SMC IRQ path only
- Allocated: ['SEP-WDT-RESET-TO-SMC.S1', 'SEP-WDT-RESET-TO-SMC.S2', 'SEP-WDT-RESET-TO-SMC.S3']
- Steps: 4 · Checkers: 5

## SEP_SMU_009 — `smu_sep_outbound_demux_decode_test`
- OWNS: Outbound demux decode only
- Allocated: ['SEP-OUTBOUND-DEMUX.S1', 'SEP-OUTBOUND-DEMUX.S2', 'SEP-OUTBOUND-DEMUX.S3']
- Steps: 4 · Checkers: 5

## SEP_SMU_010 — `smu_sep_filter_rule_matrix_test`
- OWNS: Inbound+outbound filter rule matrix only
- Allocated: ['SEP-INBOUND-FILTER.S1', 'SEP-INBOUND-FILTER.S2', 'SEP-INBOUND-FILTER.S3', 'SEP-OUTBOUND-FILTER.S1', 'SEP-OUTBOUND-FILTER.S2']
- Steps: 6 · Checkers: 7

## SEP_SMU_011 — `smu_sep_ap_stee_output_remap_test`
- OWNS: AP/STEE remap regions only
- Allocated: ['SEP-AP-STEE-REMAP.S1', 'SEP-AP-STEE-REMAP.S2', 'SEP-AP-STEE-REMAP.S3']
- Steps: 4 · Checkers: 5

## SEP_SMU_012 — `smu_sep_memory_integrity_test`
- OWNS: TCM/SRAM/ROM port observability only
- Allocated: ['SEP-MEMORY-PORT-OBS.S1', 'SEP-MEMORY-PORT-OBS.S2', 'SEP-MEMORY-PORT-OBS.S3']
- Steps: 4 · Checkers: 5

## SEP_SMU_013 — `smu_sep_km_otbn_memory_test`
- OWNS: AES/OTBN/KM SMU-visible ports only
- Allocated: ['SEP-CRYPTO-PORT-OBS.S1', 'SEP-CRYPTO-PORT-OBS.S2', 'SEP-CRYPTO-PORT-OBS.S3']
- Steps: 4 · Checkers: 5

## SEP_SMU_014 — `smu_sep_dma_test`
- OWNS: DMA CSR and TCM preload only
- Allocated: ['SEP-DMA-PORT-OBS.S1', 'SEP-DMA-PORT-OBS.S2']
- Steps: 3 · Checkers: 4

## SEP_SMU_015 — `smu_sep_spi_bridge_test`
- OWNS: SPI req/IRQ mux only
- Allocated: ['SEP-SPI-PORT-OBS.S1', 'SEP-SPI-PORT-OBS.S2']
- Steps: 3 · Checkers: 4

## SEP_SMU_016 — `smu_sep_efuse_test`
- OWNS: eFuse bank/command/JTAG-OTP only
- Allocated: ['SEP-EFUSE-PORT-OBS.S1', 'SEP-EFUSE-PORT-OBS.S2', 'SEP-EFUSE-PORT-OBS.S3']
- Steps: 4 · Checkers: 5


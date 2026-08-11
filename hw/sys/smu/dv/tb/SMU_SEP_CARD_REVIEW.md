# SMU_SEP — Card Review Packet

## REVIEW-FOCUS

- First Skill 1 generation for SMU_SEP P2 (candidate).
- Exact aperture CSR constants blocked by SF-006 on SEP_SMU_005.
- WDT polarity blocked by SF-007 on SEP_SMU_008.
- Mailbox IRQ observation point blocked by SF-003 on SEP_SMU_004.
- SEC_DIS token match scenarios unallocated (SF-005); export-only on SEP_SMU_006.

## SEP_SMU_001 — `smu_sep_smoke_test`

- **OWNS:** Boot/reset/fuse/ROM foundation only (no xbar/mailbox/filter)
- **Triad:** producer powergood/cold-reset top pins into SMC reset unit; SEP=1 composition | transport rst_primary_smc_clk_no and fuse-sense authorization into SEP reset/boot path | consumer SEP EL2 retires BL0 Boot ROM after ordered fuse authorization
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-RESET-CONTROL.S1']: Hold primary reset; sample SEP held (rst_ni=0, no retire) for bounded window
- `S2` from ['SEP-COMPOSE-ENABLE.S1']: Confirm SEP instance composed under SEP=1 (not tied-off)
- `S3` from ['SEP-RESET-CONTROL.S2', 'SEP-RESET-CONTROL.S3']: Release primary reset; observe release edge and cpu-reset chain complete
- `S4` from ['SEP-FUSE-SENSE-HANDSHAKE.S1']: Observe SMC fuse_sense_done before SEP fuse completion
- `S5` from ['SEP-ROM-BOOT-ENABLE.S1', 'SEP-ROM-BOOT-ENABLE.S2', 'INT-FUSE-AUTH-TO-ROM']: ext_boot_seq_done gate satisfied; first BL0 ROM retire at Boot ROM base
- `S6` from ['scaffolding']: TIMEOUT: bounded waits for reset/fuse/ROM with last-state fail

### Checkers (what it proves / how it fails)

- `CHK-HELD-RESET` proves ['SEP-RESET-CONTROL'] / covers ['SEP-RESET-CONTROL.S1']
  - PROOF: u_sep.rst_ni=0 across >=64 samples; retire_valid=0; inst_count=0
  - FAIL-ON: reset high, any retire, X, or wrong sample count
- `CHK-COMPOSE-SEP1` proves ['SEP-COMPOSE-ENABLE'] / covers ['SEP-COMPOSE-ENABLE.S1']
  - PROOF: SEP hierarchy present; SEP outputs not constant-tied as in SEP=0
  - FAIL-ON: SEP absent/tied-off under SEP=1
- `CHK-RESET-RELEASE` proves ['SEP-RESET-CONTROL'] / covers ['SEP-RESET-CONTROL.S2', 'SEP-RESET-CONTROL.S3']
  - PROOF: u_sep.rst_ni 0->1; sep_cpu_reset_n rises; no retire before cpu_reset release
  - FAIL-ON: missing release, retire-before-release, X
- `CHK-SMC-FUSE-AUTH` proves ['SEP-FUSE-SENSE-HANDSHAKE'] / covers ['SEP-FUSE-SENSE-HANDSHAKE.S1']
  - PROOF: smc fuse_sense_done observed =1 before SEP fuse_sense_done
  - FAIL-ON: SEP fuse done without prior SMC fuse done; X
- `CHK-BL0-FETCH` proves ['SEP-ROM-BOOT-ENABLE'] / covers ['SEP-ROM-BOOT-ENABLE.S1', 'SEP-ROM-BOOT-ENABLE.S2']
  - PROOF: ext_boot_seq_done_i=1; first retired pc in Boot ROM window 0x1004_0000
  - FAIL-ON: wrong/missing PC, fetch before gate, timeout
- `CHK-FUSE-ROM-ORDER` proves ['SEP-FUSE-SENSE-HANDSHAKE', 'SEP-ROM-BOOT-ENABLE'] / covers ['INT-FUSE-AUTH-TO-ROM']
  - PROOF: SMC_FUSE_DONE < SEP_FUSE_DONE < FIRST_BL0_ROM_RETIRE with timestamps
  - FAIL-ON: any pair out of order or missing term
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: HELD_RESET < COMPOSE_CHECK < RESET_RELEASE < SMC_FUSE < BL0_FETCH
  - FAIL-ON: PASS with any term missing/out of order
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: each wait logs finite bound + fail-on-expiry + last-state diagnostic
  - FAIL-ON: unbounded wait or expiry without failure

Approve mechanics [ ]

## SEP_SMU_002 — `smu_fuse_sense_handshake_test`

- **OWNS:** sep_fuse_sense_done_o export only
- **Triad:** producer SEP fuse-sense completion | transport sep_fuse_sense_done_o at SMU | consumer system integration observes export
- **Evidence/Tier:** frontdoor-func / A

### Steps

- `S1` from ['SEP-FUSE-SENSE-HANDSHAKE.S2']: After SMC/SEP fuse sequence, sample sep_fuse_sense_done_o=1
- `S2` from ['scaffolding']: TIMEOUT bounded wait for export

### Checkers (what it proves / how it fails)

- `CHK-SEP-FUSE-EXPORT` proves ['SEP-FUSE-SENSE-HANDSHAKE'] / covers ['SEP-FUSE-SENSE-HANDSHAKE.S2']
  - PROOF: sep_fuse_sense_done_o=1 after SEP fuse completion
  - FAIL-ON: stuck-0, X, or export before SEP fuse done
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: SEP_FUSE_DONE before EXPORT_SAMPLE
  - FAIL-ON: PASS without ordered export
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry + last state
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_003 — `smu_sep_smc_alias_remap_consistency_test`

- **OWNS:** Alias remap path and SMC aperture bound only
- **Triad:** producer SEP master access in 0x4000_0000 SMC window | transport sep_ext_to_smc_axi + axi_window_remap | consumer SMC sep_axi_in sees base+offset
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-SMC-ALIAS-REMAP.S1']: Issue SEP read/write at 0x4000_0000+offset; compare SMC target address
- `S2` from ['SEP-SMC-ALIAS-REMAP.S2']: Confirm traffic on dedicated sep_ext_to_smc (not xbar sep_out)
- `S3` from ['SEP-SMC-ALIAS-REMAP.S3']: Access outside SMC REGION_SIZE is not accepted as alias hit
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-ALIAS-HIT` proves ['SEP-SMC-ALIAS-REMAP'] / covers ['SEP-SMC-ALIAS-REMAP.S1']
  - PROOF: addr 0x4000_0000+off maps to SMC 0x0+off with OKAY data match
  - FAIL-ON: wrong address, DECERR/SLVERR, data mismatch
- `CHK-ALIAS-BYPASS` proves ['SEP-SMC-ALIAS-REMAP'] / covers ['SEP-SMC-ALIAS-REMAP.S2']
  - PROOF: sep_ext_to_smc_axi_req toggles; smu_axi_xbar sep_out idle for this access
  - FAIL-ON: traffic only on xbar sep_out
- `CHK-SMC-APERTURE-BOUND` proves ['SEP-SMC-ALIAS-REMAP'] / covers ['SEP-SMC-ALIAS-REMAP.S3']
  - PROOF: out-of-REGION_SIZE alias attempt not decoded as valid SMC hit
  - FAIL-ON: out-of-bound accepted as hit
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: ALIAS_HIT observed with BYPASS evidence
  - FAIL-ON: PASS on xbar-only path
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_004 — `smu_sep_alias_mailbox_interrupt_probe_test`

- **OWNS:** Mailbox data + IRQ crossing only (alias used as transport)
- **Triad:** producer SMC/SEP mailbox writers | transport alias-reachable mailbox + smc_mailbox_interrupt_o | consumer peer mailbox payload + SMC IRQ bits
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-MAILBOX-DATA-EXCHANGE.S1', 'INT-ALIAS-MAILBOX']: SMC writes token to outbound mailbox; SEP reads inbound payload
- `S2` from ['SEP-MAILBOX-DATA-EXCHANGE.S2']: SEP writes response; SMC observes payload
- `S3` from ['SEP-MAILBOX-DATA-EXCHANGE.S3']: SEP accesses 64-bit mailbox word as two 32-bit halves
- `S4` from ['SEP-MAILBOX-IRQ-TO-SMC.S1', 'SEP-MAILBOX-IRQ-TO-SMC.S2']: Assert mailbox event; SMC IRQ bit set then cleared
- `S5` from ['SEP-MAILBOX-IRQ-TO-SMC.S3']: Exercise representative multi-channel IRQ fan-out
- `S6` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-MBX-SMC-TO-SEP` proves ['SEP-MAILBOX-DATA-EXCHANGE'] / covers ['SEP-MAILBOX-DATA-EXCHANGE.S1']
  - PROOF: SEP inbound mailbox reads exact SMC-written token word(s)
  - FAIL-ON: wrong/missing payload
- `CHK-MBX-SEP-TO-SMC` proves ['SEP-MAILBOX-DATA-EXCHANGE'] / covers ['SEP-MAILBOX-DATA-EXCHANGE.S2']
  - PROOF: SMC mailbox reads exact SEP response word(s)
  - FAIL-ON: wrong/missing response
- `CHK-MBX-64B-HALVES` proves ['SEP-MAILBOX-DATA-EXCHANGE'] / covers ['SEP-MAILBOX-DATA-EXCHANGE.S3']
  - PROOF: low/high 32-bit halves reconstruct the 64-bit write
  - FAIL-ON: half mismatch
- `CHK-MBX-IRQ-SET-CLR` proves ['SEP-MAILBOX-IRQ-TO-SMC'] / covers ['SEP-MAILBOX-IRQ-TO-SMC.S1', 'SEP-MAILBOX-IRQ-TO-SMC.S2']
  - PROOF: lifecycle set→observed→cleared→checked_cleared on documented IRQ bit
  - FAIL-ON: missing assert/clear or wrong bit
- `CHK-MBX-IRQ-MULTI` proves ['SEP-MAILBOX-IRQ-TO-SMC'] / covers ['SEP-MAILBOX-IRQ-TO-SMC.S3']
  - PROOF: >=2 distinct channels assert distinct SMC IRQ bits
  - FAIL-ON: single-channel-only or bit collision
- `CHK-ALIAS-MAILBOX-INT` proves ['SEP-SMC-ALIAS-REMAP', 'SEP-MAILBOX-DATA-EXCHANGE'] / covers ['INT-ALIAS-MAILBOX']
  - PROOF: mailbox payload exchange uses alias-remap path (sep_ext_to_smc active)
  - FAIL-ON: exchange succeeds only via non-alias path
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: PAYLOAD_IN < PAYLOAD_OUT < IRQ_SET < IRQ_CLR
  - FAIL-ON: PASS without payload+IRQ evidence
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_005 — `smu_sep_smc_xbar_programmable_addr_test`

- **OWNS:** SMU xbar SEP ports only (not alias path)
- **Triad:** producer SEP/ext masters on SMU xbar | transport smu_axi_xbar apertures + connectivity | consumer legal targets OKAY; illegal DECERR/blocked
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-XBAR-SYSIF.S1']: SEP via xbar reaches SMC (sep_out→smc_in)
- `S2` from ['SEP-XBAR-SYSIF.S2']: ext_in reaches SEP (ext_in→sep_in)
- `S3` from ['SEP-XBAR-SYSIF.S3']: ID-width conversion preserves response routing
- `S4` from ['SEP-XBAR-APERTURE.S1']: Programmed SEP aperture hit
- `S5` from ['SEP-XBAR-APERTURE.S2']: Unmatched ext_in returns DECERR
- `S6` from ['SEP-XBAR-CONNECTIVITY.S1', 'SEP-XBAR-CONNECTIVITY.S2', 'SEP-XBAR-CONNECTIVITY.S3']: sep_out legal targets only; no self sep_in; ATOP rejected
- `S7` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-SEP-TO-SMC-XBAR` proves ['SEP-XBAR-SYSIF'] / covers ['SEP-XBAR-SYSIF.S1']
  - PROOF: SEP xbar access to SMC returns OKAY with expected data
  - FAIL-ON: DECERR/timeout/wrong data
- `CHK-EXT-TO-SEP-XBAR` proves ['SEP-XBAR-SYSIF'] / covers ['SEP-XBAR-SYSIF.S2']
  - PROOF: ext_in access to SEP aperture returns OKAY
  - FAIL-ON: DECERR/timeout
- `CHK-ID-WIDTH` proves ['SEP-XBAR-SYSIF'] / covers ['SEP-XBAR-SYSIF.S3']
  - PROOF: response ID routes to issuing SEP master after 10→6 conversion
  - FAIL-ON: orphaned/misrouted response
- `CHK-APERTURE-HIT` proves ['SEP-XBAR-APERTURE'] / covers ['SEP-XBAR-APERTURE.S1']
  - PROOF: programmed aperture admits intended SEP region (OKAY)
  - FAIL-ON: hit becomes DECERR
- `CHK-EXT-IN-DECERR` proves ['SEP-XBAR-APERTURE'] / covers ['SEP-XBAR-APERTURE.S2']
  - PROOF: unmatched ext_in beat returns DECERR
  - FAIL-ON: OKAY on unmatched
- `CHK-CONNECTIVITY` proves ['SEP-XBAR-CONNECTIVITY'] / covers ['SEP-XBAR-CONNECTIVITY.S1', 'SEP-XBAR-CONNECTIVITY.S2', 'SEP-XBAR-CONNECTIVITY.S3']
  - PROOF: sep_out→{smc_in,ext_out} only; sep_out→sep_in blocked; ATOP rejected
  - FAIL-ON: illegal path OKAY or ATOP accepted
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: legal hit and illegal DECERR both observed
  - FAIL-ON: PASS with only happy-path OKAY
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_006 — `smu_lifecycle_security_handoff_test`

- **OWNS:** LC state + feat_ctrl profile + security_disable export
- **Triad:** producer SEP LCC outputs | transport lc_state_o / feat_ctrl_o / security_disable_o at SMU | consumer SMC/DTP observe handoff vector
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-FEAT-CTRL-EXPORT.S1']: Sample feat_ctrl_o matches OTP-derived profile
- `S2` from ['SEP-LC-STATE-EXPORT.S1', 'SEP-LC-STATE-EXPORT.S3']: Sample lc_state_o and demote exports
- `S3` from ['SEP-SECURITY-DISABLE-EXPORT.S1']: Sample security_disable_o connectivity
- `S4` from ['INT-FEAT-LC-HANDOFF']: Joint handoff observation
- `S5` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-FEAT-PROFILE` proves ['SEP-FEAT-CTRL-EXPORT'] / covers ['SEP-FEAT-CTRL-EXPORT.S1']
  - PROOF: feat_ctrl_o equals SPEC LC profile for the loaded shadow state
  - FAIL-ON: mismatched/X feat_ctrl
- `CHK-LC-EXPORT` proves ['SEP-LC-STATE-EXPORT'] / covers ['SEP-LC-STATE-EXPORT.S1', 'SEP-LC-STATE-EXPORT.S3']
  - PROOF: lc_state_o tracks SEP encoding; lcc_demote_state_* visible
  - FAIL-ON: stuck/X exports
- `CHK-SEC-DIS-EXPORT` proves ['SEP-SECURITY-DISABLE-EXPORT'] / covers ['SEP-SECURITY-DISABLE-EXPORT.S1']
  - PROOF: security_disable_o readable at SMU/SMC boundary (0 or 1, non-X)
  - FAIL-ON: X/Z on security_disable_o
- `CHK-LC-FEAT-HANDOFF` proves ['SEP-FEAT-CTRL-EXPORT', 'SEP-LC-STATE-EXPORT'] / covers ['INT-FEAT-LC-HANDOFF']
  - PROOF: same sample window captures consistent lc_state_o with feat_ctrl_o profile
  - FAIL-ON: inconsistent pair
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: all three exports sampled
  - FAIL-ON: PASS with any export missing
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_007 — `smu_feat_ctrl_monitor_test`

- **OWNS:** feat_ctrl fail-closed and demote profiles only
- **Triad:** producer LCC sigint/demote inputs | transport feat_ctrl_o | consumer fail-closed zero or demote profile at SMU
- **Evidence/Tier:** frontdoor-func / B

### Steps

- `S1` from ['SEP-FEAT-CTRL-EXPORT.S2']: Inject/observe signal-integrity fail-closed feat_ctrl_o=0
- `S2` from ['SEP-FEAT-CTRL-EXPORT.S3']: Program demote; observe altered feat_ctrl profile
- `S3` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-FEAT-FAIL-CLOSED` proves ['SEP-FEAT-CTRL-EXPORT'] / covers ['SEP-FEAT-CTRL-EXPORT.S2']
  - PROOF: on sigint error feat_ctrl_o==0
  - FAIL-ON: non-zero feat_ctrl under sigint
- `CHK-FEAT-DEMOTE` proves ['SEP-FEAT-CTRL-EXPORT'] / covers ['SEP-FEAT-CTRL-EXPORT.S3']
  - PROOF: DEMOTE asserted changes feat_ctrl_o per demote profile; OTP LC_STATE unchanged
  - FAIL-ON: no profile change or LC_STATE mutated
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: fail-closed and demote both observed
  - FAIL-ON: PASS with only one variant
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_008 — `smu_sep_wdt_reset_to_smc_test`

- **OWNS:** WDT bark vs bite into SMC IRQ path only
- **Triad:** producer SEP WDT bark/bite | transport wdt_timer_rst_req / sep_wdt_reset into SMC | consumer SMC SEP-watchdog IRQ indication
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-WDT-RESET-TO-SMC.S1']: Program WDT to bite; observe SMC SEP-watchdog IRQ path
- `S2` from ['SEP-WDT-RESET-TO-SMC.S2']: Distinguish bark interrupt from bite reset request
- `S3` from ['SEP-WDT-RESET-TO-SMC.S3']: Confirm clk_sep_wdt_i domain connectivity
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-WDT-BITE-IRQ` proves ['SEP-WDT-RESET-TO-SMC'] / covers ['SEP-WDT-RESET-TO-SMC.S1']
  - PROOF: lifecycle: bite sets SMC peripheral SEP-watchdog indication then observable then cleared after handling
  - FAIL-ON: missing IRQ or wrong polarity (see SF-007)
- `CHK-WDT-BARK-VS-BITE` proves ['SEP-WDT-RESET-TO-SMC'] / covers ['SEP-WDT-RESET-TO-SMC.S2']
  - PROOF: bark (first timeout) observable without bite; bite is second-stage request
  - FAIL-ON: bark==bite collapsed
- `CHK-WDT-CLK` proves ['SEP-WDT-RESET-TO-SMC'] / covers ['SEP-WDT-RESET-TO-SMC.S3']
  - PROOF: clk_sep_wdt_i toggling while WDT counts
  - FAIL-ON: WDT clock stuck
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: bark and bite distinguished
  - FAIL-ON: PASS on bark-only
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_009 — `smu_sep_outbound_demux_decode_test`

- **OWNS:** Outbound demux decode only
- **Triad:** producer SEP outbound addresses | transport system peripherals outbound demux | consumer sep_ext_to_smc vs smn_outbound vs local
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-OUTBOUND-DEMUX.S1']: SMC-window address emerges on sep_ext_to_smc
- `S2` from ['SEP-OUTBOUND-DEMUX.S2']: Non-SMC external emerges on smn_outbound
- `S3` from ['SEP-OUTBOUND-DEMUX.S3']: Local SEP resource stays internal
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-DEMUX-SMC` proves ['SEP-OUTBOUND-DEMUX'] / covers ['SEP-OUTBOUND-DEMUX.S1']
  - PROOF: SMC-window access toggles sep_ext_to_smc; smn_outbound idle
  - FAIL-ON: wrong egress port
- `CHK-DEMUX-SMN` proves ['SEP-OUTBOUND-DEMUX'] / covers ['SEP-OUTBOUND-DEMUX.S2']
  - PROOF: external non-SMC access toggles smn_outbound
  - FAIL-ON: wrong egress port
- `CHK-DEMUX-LOCAL` proves ['SEP-OUTBOUND-DEMUX'] / covers ['SEP-OUTBOUND-DEMUX.S3']
  - PROOF: local access completes without sep_ext_to_smc/smn_outbound
  - FAIL-ON: local leaks outbound
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: all three demux classes observed
  - FAIL-ON: PASS with one class only
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_010 — `smu_sep_filter_rule_matrix_test`

- **OWNS:** Inbound+outbound filter rule matrix only
- **Triad:** producer external inbound / SEP outbound traffic | transport inbound+outbound filters | consumer allow OKAY / deny filtered response
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-INBOUND-FILTER.S1']: Post-POR inbound default deny
- `S2` from ['SEP-INBOUND-FILTER.S2']: Program allow; matching inbound admitted
- `S3` from ['SEP-INBOUND-FILTER.S3']: STEE-only rule on STEE remapper region
- `S4` from ['SEP-OUTBOUND-FILTER.S1']: Outbound deny rule blocks
- `S5` from ['SEP-OUTBOUND-FILTER.S2']: Outbound conforming passes
- `S6` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-IN-DEFAULT-DENY` proves ['SEP-INBOUND-FILTER'] / covers ['SEP-INBOUND-FILTER.S1']
  - PROOF: unprogrammed inbound address denied (non-OKAY filter response)
  - FAIL-ON: OKAY on default-deny address
- `CHK-IN-ALLOW` proves ['SEP-INBOUND-FILTER'] / covers ['SEP-INBOUND-FILTER.S2']
  - PROOF: programmed allow yields OKAY to SEP target
  - FAIL-ON: still denied after allow
- `CHK-IN-STEE` proves ['SEP-INBOUND-FILTER'] / covers ['SEP-INBOUND-FILTER.S3']
  - PROOF: non-STEE denied to STEE remapper; STEE admitted
  - FAIL-ON: non-STEE admitted
- `CHK-OUT-DENY` proves ['SEP-OUTBOUND-FILTER'] / covers ['SEP-OUTBOUND-FILTER.S1']
  - PROOF: programmed deny blocks matching outbound
  - FAIL-ON: deny rule passes
- `CHK-OUT-ALLOW` proves ['SEP-OUTBOUND-FILTER'] / covers ['SEP-OUTBOUND-FILTER.S2']
  - PROOF: conforming outbound completes OKAY
  - FAIL-ON: conforming blocked
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: inbound deny+allow and outbound deny+allow all present
  - FAIL-ON: PASS without negative control
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_011 — `smu_sep_ap_stee_output_remap_test`

- **OWNS:** AP/STEE remap regions only
- **Triad:** producer SEP writes to AP/STEE remap windows | transport AP/STEE remappers | consumer translated outbound attributes
- **Evidence/Tier:** strict-e2e / B

### Steps

- `S1` from ['SEP-AP-STEE-REMAP.S1']: Invalid-reset remapper pass-through
- `S2` from ['SEP-AP-STEE-REMAP.S2']: Programmed AP remap translation
- `S3` from ['SEP-AP-STEE-REMAP.S3']: Programmed STEE remap translation
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-REMAP-PASSTHROUGH` proves ['SEP-AP-STEE-REMAP'] / covers ['SEP-AP-STEE-REMAP.S1']
  - PROOF: unprogrammed region behaves as transparent pass-through
  - FAIL-ON: spurious translate out of reset
- `CHK-AP-REMAP` proves ['SEP-AP-STEE-REMAP'] / covers ['SEP-AP-STEE-REMAP.S2']
  - PROOF: programmed AP region output address = input+programmed offset
  - FAIL-ON: wrong output address
- `CHK-STEE-REMAP` proves ['SEP-AP-STEE-REMAP'] / covers ['SEP-AP-STEE-REMAP.S3']
  - PROOF: STEE-qualified access translates; non-STEE denied/filtered
  - FAIL-ON: wrong translate or non-STEE admitted
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: passthrough and both remaps observed
  - FAIL-ON: PASS with only passthrough
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_012 — `smu_sep_memory_integrity_test`

- **OWNS:** TCM/SRAM/ROM port observability only
- **Triad:** producer SEP CPU memory accesses | transport SMU passthrough TCM/SRAM/ROM ports | consumer memory models respond
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-MEMORY-PORT-OBS.S1']: TCM port activity during execution
- `S2` from ['SEP-MEMORY-PORT-OBS.S2']: Scratch SRAM port activity
- `S3` from ['SEP-MEMORY-PORT-OBS.S3']: Boot ROM port serves BL0 window
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-TCM-PORT` proves ['SEP-MEMORY-PORT-OBS'] / covers ['SEP-MEMORY-PORT-OBS.S1']
  - PROOF: sep_cpu_tcm_req/rsp handshake with data match to programmed pattern
  - FAIL-ON: no toggles or data mismatch
- `CHK-SRAM-PORT` proves ['SEP-MEMORY-PORT-OBS'] / covers ['SEP-MEMORY-PORT-OBS.S2']
  - PROOF: sep_sram_req/rsp activity with data match
  - FAIL-ON: no toggles or mismatch
- `CHK-ROM-PORT` proves ['SEP-MEMORY-PORT-OBS'] / covers ['SEP-MEMORY-PORT-OBS.S3']
  - PROOF: sep_boot_rom_req in BL0 window during fetch
  - FAIL-ON: no ROM port activity during BL0
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: TCM+SRAM+ROM all active
  - FAIL-ON: PASS with idle ports
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_013 — `smu_sep_km_otbn_memory_test`

- **OWNS:** AES/OTBN/KM SMU-visible ports only
- **Triad:** producer SEP programmed crypto ops | transport crypto CSR/mem ports at SMU | consumer boundary-visible completion
- **Evidence/Tier:** frontdoor-func / B

### Steps

- `S1` from ['SEP-CRYPTO-PORT-OBS.S1']: AES CSR op completes at boundary
- `S2` from ['SEP-CRYPTO-PORT-OBS.S2']: OTBN IMEM/DMEM ports toggle under execute
- `S3` from ['SEP-CRYPTO-PORT-OBS.S3']: KM ROM/SRAM ports observed
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-AES-PORT` proves ['SEP-CRYPTO-PORT-OBS'] / covers ['SEP-CRYPTO-PORT-OBS.S1']
  - PROOF: AES CSR window access OKAY and status reaches done without requiring KAT digest proof
  - FAIL-ON: CSR DECERR or no completion
- `CHK-OTBN-PORTS` proves ['SEP-CRYPTO-PORT-OBS'] / covers ['SEP-CRYPTO-PORT-OBS.S2']
  - PROOF: OTBN IMEM/DMEM SMU ports toggle during execute flow
  - FAIL-ON: ports idle through execute
- `CHK-KM-PORTS` proves ['SEP-CRYPTO-PORT-OBS'] / covers ['SEP-CRYPTO-PORT-OBS.S3']
  - PROOF: KM ROM/SRAM req ports toggle under KM access
  - FAIL-ON: ports stuck
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: AES+OTBN+KM evidence present
  - FAIL-ON: PASS with CSR-only smoke
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_014 — `smu_sep_dma_test`

- **OWNS:** DMA CSR and TCM preload only
- **Triad:** producer SEP DMA CSR programming | transport DMA master on SEP fabric | consumer destination memory updated
- **Evidence/Tier:** strict-e2e / B

### Steps

- `S1` from ['SEP-DMA-PORT-OBS.S1']: DMA CSR kickoff
- `S2` from ['SEP-DMA-PORT-OBS.S2']: DMA TCM preload completes
- `S3` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-DMA-CSR` proves ['SEP-DMA-PORT-OBS'] / covers ['SEP-DMA-PORT-OBS.S1']
  - PROOF: DMA CSR program OKAY; start bit accepted
  - FAIL-ON: CSR DECERR or start ignored
- `CHK-DMA-TCM` proves ['SEP-DMA-PORT-OBS'] / covers ['SEP-DMA-PORT-OBS.S2']
  - PROOF: destination TCM/SRAM contains DMA source pattern after completion
  - FAIL-ON: pattern missing/timeout
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: CSR kickoff precedes memory proof
  - FAIL-ON: PASS on CSR-only
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_015 — `smu_sep_spi_bridge_test`

- **OWNS:** SPI req/IRQ mux only
- **Triad:** producer SEP SPI programming | transport sep_io_spi + SPI IRQ mux at SMU | consumer pad-facing req / IRQ observed
- **Evidence/Tier:** frontdoor-func / B

### Steps

- `S1` from ['SEP-SPI-PORT-OBS.S1']: SPI host drives sep_io_spi_req_o
- `S2` from ['SEP-SPI-PORT-OBS.S2']: Muxed SPI IRQ observed on SMU path
- `S3` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-SPI-REQ` proves ['SEP-SPI-PORT-OBS'] / covers ['SEP-SPI-PORT-OBS.S1']
  - PROOF: sep_io_spi_req_o toggles under host transaction
  - FAIL-ON: no SPI req activity
- `CHK-SPI-IRQ-MUX` proves ['SEP-SPI-PORT-OBS'] / covers ['SEP-SPI-PORT-OBS.S2']
  - PROOF: lifecycle: SPI IRQ set observed on mux path then cleared
  - FAIL-ON: IRQ missing
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: SPI req and IRQ both observed
  - FAIL-ON: PASS with req-only
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## SEP_SMU_016 — `smu_sep_efuse_test`

- **OWNS:** eFuse bank/command/JTAG-OTP only
- **Triad:** producer SEP/DTP eFuse transactions | transport SMU eFuse passthrough ports | consumer eFuse shim completes
- **Evidence/Tier:** strict-e2e / A

### Steps

- `S1` from ['SEP-EFUSE-PORT-OBS.S1']: eFuse bank-control AXI-Lite completes
- `S2` from ['SEP-EFUSE-PORT-OBS.S2']: eFuse command handshake completes
- `S3` from ['SEP-EFUSE-PORT-OBS.S3']: JTAG OTP debug path into SEP eFuse
- `S4` from ['scaffolding']: TIMEOUT

### Checkers (what it proves / how it fails)

- `CHK-EFUSE-BANK` proves ['SEP-EFUSE-PORT-OBS'] / covers ['SEP-EFUSE-PORT-OBS.S1']
  - PROOF: bank-control transaction OKAY with expected readback
  - FAIL-ON: DECERR/timeout
- `CHK-EFUSE-CMD` proves ['SEP-EFUSE-PORT-OBS'] / covers ['SEP-EFUSE-PORT-OBS.S2']
  - PROOF: command req/resp handshake completes
  - FAIL-ON: handshake timeout
- `CHK-EFUSE-JTAG` proves ['SEP-EFUSE-PORT-OBS'] / covers ['SEP-EFUSE-PORT-OBS.S3']
  - PROOF: JTAG-OTP AXI-Lite access completes with OKAY
  - FAIL-ON: DECERR/timeout
- `CHK-NONVAC` proves (integrity) / covers -
  - PROOF: bank+cmd+jtag evidence
  - FAIL-ON: PASS with single path only
- `CHK-TIMEOUT-PATHS` proves (integrity) / covers -
  - PROOF: finite bound + fail-on-expiry
  - FAIL-ON: unbounded wait

Approve mechanics [ ]

## Appendix

- cards content_sha256: `fdcf847f63904b5803f7df0934eab903d4c6f5f860e84359e962456ce61cff19`
- artifact_revision: 1
- n_cards: 16

# SEP `rom_fw` Full Group Regression — results

**Run directory:** `20260915_151207__vcs__rom_fw_full`  
**Generated:** 2026-09-16 from `result.json` and `regress.log`  
**Simulator:** VCS `V-2023.12-SP2-9` · `--sim-jobs 6` · `--build-jobs 12`  
**Branch:** `inmcm/sep_rom_oca_manifest` @ `dd628c751`  
**Verdict:** `PASS` · exit `0` · **67/67 passing**, 0 failing · pass rate 1.00 · **19.3 h** wall

| # | Test | Status | Seed | Elapsed |
|---:|---|:---:|---:|---:|
| 1 | `sep_rom_non_secure_boot_test` | PASS | 257866640 | 1787 s |
| 2 | `sep_rom_ot_dma_boot_test` | PASS | 801894756 | 2214 s |
| 3 | `sep_rom_ot_pio_boot_test` | PASS | 857373916 | 2398 s |
| 4 | `sep_rom_ot_secure_boot_test` | PASS | 289606286 | 8775 s |
| 5 | `sep_firmware_mbist_fail_test` | PASS | 64633886 | 7 s |
| 6 | `sep_scratch_7_test` | PASS | 777928448 | 4 s |
| 7 | `sep_firmware_device_cntl_non_secure_boot_flow_test` | PASS | 740452082 | 8773 s |
| 8 | `sep_firmware_enforced_secure_boot_flow_test` | PASS | 1185145682 | 8833 s |
| 9 | `sep_firmware_cntl_secure_boot_flow_test` | PASS | 2094935796 | 3372 s |
| 10 | `sep_firmware_backup_invalid_signature_test` | PASS | 1513569783 | 9323 s |
| 11 | `sep_firmware_backup_invalid_security_version_test` | PASS | 2040345461 | 3117 s |
| 12 | `sep_firmware_backup_invalid_public_key_selection_test` | PASS | 173745874 | 3061 s |
| 13 | `sep_firmware_backup_unpopulated_rom_key_slot_test` | PASS | 948318263 | 2924 s |
| 14 | `sep_spi_detect_success_test` | PASS | 508511379 | 2247 s |
| 15 | `sep_spi_primary_fail_backup_test` | PASS | 1465407224 | 3104 s |
| 16 | `sep_failover_sram_clear_assertion_test` | **SKIPPED** | — | — |
| 17 | `sep_spi_not_detected_terminal_test` | PASS | 931234192 | 2709 s |
| 18 | `sep_firmware_mbist_pass_test` | PASS | 969364870 | 2020 s |
| 19 | `sep_firmware_mbist_only_fail_test` | PASS | 2111284566 | 7 s |
| 20 | `sep_boot_recovery_test` | PASS | 1608362555 | 1864 s |
| 21 | `sep_rotate_update_set_test` | PASS | 217629065 | 2109 s |
| 22 | `sep_firmware_primary_invalid_key_hash_test` | PASS | 1872237117 | 9600 s |
| 23 | `sep_firmware_backup_invalid_key_hash_test` | PASS | 345626666 | 3168 s |
| 24 | `sep_firmware_backup_pubkey_rom_0_revoked_key_test` | PASS | 1437680659 | 2916 s |
| 25 | `sep_firmware_backup_pubkey_rom_1_revoked_key_test` | PASS | 1514489970 | 3011 s |
| 26 | `sep_firmware_backup_pubkey_rom_2_revoked_key_test` | PASS | 2131376721 | 2685 s |
| 27 | `sep_firmware_backup_pubkey_rom_3_revoked_key_test` | PASS | 812523313 | 2883 s |
| 28 | `sep_firmware_backup_pubkey_rom_4_revoked_key_test` | PASS | 685298488 | 2878 s |
| 29 | `sep_firmware_backup_pubkey_rom_5_revoked_key_test` | PASS | 1282314399 | 2798 s |
| 30 | `sep_firmware_backup_invalid_signature_type_test` | PASS | 1269190956 | 2722 s |
| 31 | `sep_firmware_backup_rom_key_index_invalid_test` | PASS | 14451094 | 3005 s |
| 32 | `sep_firmware_backup_rom_key_valid_test` | PASS | 976058840 | 9283 s |
| 33 | `sep_firmware_primary_invalid_public_key_selection_test` | PASS | 387606052 | 9555 s |
| 34 | `sep_firmware_primary_invalid_security_version_test` | PASS | 1451113971 | 9803 s |
| 35 | `sep_firmware_primary_pubkey_rom_0_revoked_key_test` | PASS | 346733731 | 3139 s |
| 36 | `sep_firmware_primary_pubkey_rom_1_revoked_key_test` | PASS | 1843845853 | 9322 s |
| 37 | `sep_firmware_primary_pubkey_rom_2_revoked_key_test` | PASS | 1622439253 | 9383 s |
| 38 | `sep_firmware_primary_pubkey_rom_3_revoked_key_test` | PASS | 1555857881 | 9480 s |
| 39 | `sep_firmware_primary_pubkey_rom_4_revoked_key_test` | PASS | 349630364 | 9418 s |
| 40 | `sep_firmware_primary_pubkey_rom_5_revoked_key_test` | PASS | 1253499274 | 9760 s |
| 41 | `sep_firmware_primary_invalid_signature_test` | PASS | 464318134 | 16204 s |
| 42 | `sep_firmware_primary_invalid_signature_type_test` | PASS | 936844044 | 9530 s |
| 43 | `sep_firmware_primary_rom_key_index_invalid_test` | PASS | 453002041 | 9756 s |
| 44 | `sep_firmware_primary_rom_key_valid_test` | PASS | 936979317 | 8284 s |
| 45 | `sep_firmware_bl1_ver_test` | PASS | 151651801 | 8646 s |
| 46 | `sep_firmware_chiplet_pubkey_0_test` | PASS | 1531544398 | 8867 s |
| 47 | `sep_firmware_chiplet_pubkey_0_revoke_test` | PASS | 920587372 | 3202 s |
| 48 | `sep_firmware_chiplet_pubkey_1_test` | PASS | 1983574939 | 8877 s |
| 49 | `sep_firmware_chiplet_pubkey_1_revoke_test` | PASS | 1570338079 | 3254 s |
| 50 | `sep_firmware_chiplet_pubkey_0_wrong_digest_test` | PASS | 1395137576 | 3564 s |
| 51 | `sep_firmware_demotion_decision_auth_flag_0_prod_end_test` | PASS | 752222666 | 9659 s |
| 52 | `sep_firmware_demotion_decision_no_flag_prod_end_test` | PASS | 2142764903 | 9453 s |
| 53 | `sep_firmware_demotion_decision_no_flag_prod_end_sel_bit_set_test` | PASS | 218975949 | 9614 s |
| 54 | `sep_firmware_demotion_decision_auth_flag_0_prod_test` | PASS | 988733605 | 2440 s |
| 55 | `sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_test` | PASS | 1863537437 | 2302 s |
| 56 | `sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test` | PASS | 2114794993 | 2545 s |
| 57 | `sep_firmware_demotion_decision_no_flag_prod_sel_bit_set_test` | PASS | 1782745718 | 2318 s |
| 58 | `sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_sel_bit_set_test` | PASS | 1776642823 | 2262 s |
| 59 | `sep_bl1_size_invalid_test` | PASS | 1055146202 | 16399 s |
| 60 | `sep_bl1_entry_invalid_test` | PASS | 1175619666 | 16562 s |
| 61 | `sep_decryption_failure_terminal_test` | PASS | 284602345 | 16614 s |
| 62 | `sep_decryption_failure_failover_test` | PASS | 1303874807 | 16192 s |
| 63 | `sep_mbist_fail_continue_test` | PASS | 226001399 | 2177 s |
| 64 | `sep_warm_reset_invalid_hang_test` | PASS | 1225677805 | 6 s |
| 65 | `sep_warm_reset_below_range_hang_test` | PASS | 1498460537 | 6 s |
| 66 | `sep_warm_reset_unarmed_cold_boot_test` | PASS | 1163744640 | 4 s |
| 67 | `sep_warm_reset_bad_target_exception_test` | PASS | 988749779 | 205 s |
| 68 | `sep_otbn_rsa_verify_failure_test` | PASS | 1410357742 | 15885 s |

## Notes

Rows follow the `rom_fw` group order in `all.toml`, so test families stay together. Seeds are recorded because they are what make a result reproducible.

**Row 16 is skipped, not failed.** `sep_failover_sram_clear_assertion_test` is verilator-only; the per-test `tools` key filtered it out of a VCS run and `result.json` records it under `selection.skipped_wrong_tool`. That is the per-test `tools` feature behaving as designed, and it is why the group has 68 members but 67 runnable leaves.

**Not in this table:** `sep_rom_oca_encrypted_boot_test`, `sep_rom_oca_otp_key_boot_test` and `sep_rom_oca_tamper_test` are in `rom_fw.toml` but not in the `all.toml` group, so a group run does not select them. All three are separately verified; see the "Open: three tests in the testlist but not in the `rom_fw` group" section of `ROM_FW_REGRESSION_TRIAGE.md`.

**Timing.** Longest item 16614 s against a 21600 s cap; median 3139 s; total serial work ~108 h compressed into 19.3 h by the 6-way fan-out. For contrast the 2026-09-11 baseline was 56/66 with four members truncated at the then-`timeout_sec = 14400`.

**Full `selection` payload:**

```json
{
  "skipped_excluded": [],
  "skipped_unimplemented": [],
  "skipped_wrong_tool": [
    "sep_failover_sram_clear_assertion_test"
  ]
}
```

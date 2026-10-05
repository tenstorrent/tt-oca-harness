<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

These tables list the OCA ROM's console tokens, result codes, status words and constants for lookup only and are not a source of expected values: derive every testcase expectation from the ROM source.

# SEP OCA boot ROM tokens and codes

`test_oca_token_map.py` checks that every token in table 1 is printed by the ROM or BL1
(`sep_oca_console.ROM_MARKERS` or `src/*.S`), and that every `oca_result_t` /
`OCA_BOOT_ERR_*` name in table 2 equals the listed code.

Global rules:

- `MANIFEST_OK` prints after `oca_validate_manifest` and before the payload checks; `PAYLOAD_OK` is what shows a slot was accepted.
- Output from the VP and the warm stubs (the `[VP]` verdict line, `WARM_JUMP_OK`, `PST`) is not a ROM token and is not in table 1.

## 1. Token

| OCA token | ROM symbol | Notes |
|---|---|---|
| `COLD` `MEM_INIT_OK` | `rom_main` | |
| `TRAP H0` | `trap_handler_c` | |
| `BOOT_SPI` `BOOT_RECOVERY` `BOOT_SECONDARY` | `rom_main` | |
| `>>SPI_INIT` `<<SPI_INIT` | `rom_main` | |
| `SPI_INIT_OK` `SPI_ROTATE=` | `rom_spi_init` | |
| `OT_SPI: init ok` | `ot_spi_init` | |
| `STRAPS_LO=` `STRAPS_HI=` `STRAP primary=` `rotate=` | `init_straps` | |
| `SRAM_SCRUB_CFG=` `SRAM_CLR_SKIP` `SRAM_CLR_OK` | `rom_clear_ext_sram` | |
| `LC_STATE=` `LC_STATE_INVALID=` `LC=TEST_DEV` `LC=PROD` `LC=PROD_END` `LC=RMA_CHIPLET` `LC=RMA_SIP` | `rom_lifecycle_policy` | |
| `FUSE: SBOOT_DIS:` | `rom_sboot_dis_policy` | |
| `SMC_STATUS_TO_SEP=` `MANIFEST_OFF=` `SMC_MANIFEST_ADDR=` `SMC_COORD_NOT_READY` `SMC_MANIFEST_OFF_INVALID` | `rom_smc_coordination_probe` | |
| `WAIT_SMC_MANIFEST` | `rom_manifest_boot` | |
| `MANIFEST_SRC=` | `rom_manifest_boot` | Starts every slot attempt; with rotate, `MANIFEST_BACKUP` and `MANIFEST_SRC=0x00041000` print first |
| `MANIFEST_PRIMARY` `MANIFEST_BACKUP` | `rom_manifest_boot` | Printed per slot, not per attempt order |
| `MANIFEST_ALL_FAILED` | `rom_manifest_boot` | |
| `MANIFEST_ERR=` | `rom_manifest_boot` | Codes in table 2 |
| `MANIFEST_BOOT_FAIL=` | `rom_manifest_validate_handoff` | Codes in table 2 |
| `OCA_BODY=` `MFST_VER=` | `try_manifest_slot` | `MFST_VER=` is the low 32 bits of the 16 B flag field, printed for every slot |
| `MANIFEST_OK` `PAYLOAD_OK` | `try_manifest_slot` | See the global rules |
| `PAYLOAD_LOC_FAIL` `FLASH_READ_OOB` | `try_manifest_slot`, `manifest_src_read` | `PAYLOAD_LOC_FAIL` with `0x0003001b`, or `FLASH_READ_OOB` with `0x00030106` |
| `DEMOTE: PROD_END lock` `DEMOTE: BL2 deferred, unlocked` `DEMOTE: BL2 deferred, lock non-demoted` | `rom_manifest_validate_handoff` | |
| `BL1_DEMOTE=` `BL2_DEMOTE_DEC=` `DEMOTE_LOCKED` `DEMOTE_NOT_LOCKED` | `rom_manifest_validate_handoff` | |
| `SBOOT_OFF` | `rom_manifest_validate_handoff` | Printed once, after a slot succeeds |
| `FUSE_SECRETS_LOCKED` `FUSE_SECRETS_NOT_LOCKED` `LOCKS_LO=` | `check_fuse_secrets_locked` | The fuse lock runs after the measurement |
| `MEAS_BOOT_STATE_OK` `ROM_HASH_VERIFIED` | `rom_manifest_validate_handoff`, `measurement_enroll_rom_hash` | The measurement uses two soft-PCR slots |
| `PUBK_SEL=` | `plat_is_key_authorized` | One bitmap slot number; `0x06` prints before `PUBK_SLOT_RESERVED` |
| `PUBK_AUTHORIZED` `PUBK_UNAUTHORIZED` | `plat_is_key_authorized` | `PUBK_AUTHORIZED` prints before `RSA_EXEC`; `PUBK_UNAUTHORIZED` with `0x00030023` |
| `PUBK_SLOT_RESERVED` `PUBK_SLOT_PQC_UNSUPPORTED` `PUBK_SLOT_UNPROVISIONED` | `plat_is_key_authorized` | |
| `PUBK_SEL_AMBIGUOUS` `PUBK_SEL_EMPTY` `PUBK_OTP_EMPTY` | `plat_is_key_authorized` | |
| `PUBK_HASH_TIMEOUT` | `plat_is_key_authorized` | |
| `PUBK_REVOKE=` | `plat_get_root_key_revocation` | Printed after `PUBK_AUTHORIZED` |
| `FUSE_VER=` | `plat_get_security_version` | The raw low 32 bits, printed after revocation |
| `RSA_EXEC` `RSA_EXEC_FAIL` `RSA_CMP1` `RSA_CMP2` | `rsa_3072_verify` | |
| `RSA_PKCS1_FAIL` `RSA_INOUT_UNCHANGED` `RSA_VERIFY_OK` | `rsa_3072_verify` | A failed verify reports `0x0003000e` |
| `RSA_OTBN_INIT_FAIL` `RSA_OTBN_LOAD_FAIL` | `rsa_3072_verify` | |
| `OTBN_ERR=` | `otbn_execute` | |
| `OTBN_RST_FAIL` | `otbn_init` | |
| `AES_DEC_FAIL` `AES_PAD_BAD` `AES_RST_FAIL` `AES_BAD_KEYLEN` `AES_CTRL_REJECTED` `AES_INIT_BUSY` `AES_IDLE_TIMEOUT=` `AES_ALERT_STATUS=` `AES_ALERT_AFTER_DEC` | `aes_cbc_decrypt`, `aes_pkcs7_strip`, `aes_init`, `wait_idle`, `check_no_alert`, `plat_decrypt_payload` | A failed AES init prints nothing and reports `0x00030013` |
| `KDF_FAIL` | `plat_decrypt_payload` | |
| `KDF_HMAC_FAIL` | `oca_derive_payload_key` | |
| `DECRYPT_OK` | `plat_decrypt_payload` | Printed only after the PKCS#7 check passes |
| `HMAC_FIFO_TIMEOUT` `HMAC_OP_REJECTED` `HMAC_START_REJECTED` `HMAC_ERR_CODE=` | `hmac_sha256`, `check_no_error` | A hash timeout reports `0x0003000f` |
| `SHA_FIFO_TIMEOUT` `SHA_OP_REJECTED` `SHA_START_REJECTED` | `sha256` | A hash timeout reports `0x0003000f` |
| `PRE_JUMP` | `jump_to_bl1` | |
| `BL1_COPIED` `BL1_JUMP=` `COPY_SRC=` `COPY_DST=` `COPY_LEN=` | `rom_handoff_bl1` | Values follow the OCA TOC |
| `LOAD=` `LEN=` `ENTRY=` | `bl1_locate` | Values follow the OCA TOC; `rom_handoff_bl1`, `rom_clear_ext_sram` and `dma_transfer` also print `LEN=` |
| `NO_BL1_IMAGE` | `bl1_locate` | After `PAYLOAD_OK`; code `0x00030102` |
| `BL1_ADDR_RANGE` `BL1_ENTRY_RANGE` | `bl1_locate` | After `PAYLOAD_OK`; code `0x00030103` |
| `BL1` `BL0S_CHK` `BL0S_OK` `BL0S_VERIFY_FAIL` | `_start` (bl1_pass_test) | BL1 token |
| `BL0S_MFST=` | `bl1_verify_bl0_state` (bl1_pass_test) | BL1 token |
| `BL0S_BOOT_PCR=` | `bl1_verify_bl0_state` (bl1_pass_test) | SHA256(0^32 ‖ SHA256(40 B record)); see `boot_measurement_golden.py` |
| `FAIL:BL0S` `FAIL:BL0S_MFST` `FAIL:LOCKS` `FAIL:CLASS_KEY=` `FAIL:RMA_CHIP=` `FAIL:RMA_SIP=` | `bl1_verify_bl0_state`, `bl1_verify_fuse_locks`, `bl1_test_locked_field_reads` (bl1_pass_test) | BL1 token |
| `FUSE_CHK` `FUSE_OK` `FUSE_LOCK_VERIFY_FAIL` | `_start` (bl1_pass_test) | BL1 token |
| `LOCKS=` | `bl1_verify_fuse_locks` (bl1_pass_test) | BL1 token |
| `LOCK_RD` `LOCK_RD_OK` `LOCK_RD_FAIL` | `_start` (bl1_pass_test) | BL1 token |
| `GO!` | `_start` (bl1_pass_test) | BL1 token |

Several refusals print no token and show only as a `MANIFEST_ERR=` code: manifest hash
(`0x0003000d`), payload hash (`0x00030012`), revoked key (`0x00030016`), security version
(`0x00030017`), chiplet, package and system ID (`0x00030007` to `0x00030009`), lifecycle
(`0x0003000a`), encryption without secure boot (`0x0003001d`), and every TOC rule
(`0x00030015`, with no image index).

## 2. Error codes

OCA code = `OCA_BOOT_ERR_BASE (0x00030000) | oca_result_t`; `0x000301xx` are the ROM's own `OCA_BOOT_ERR_*`.

| OCA code | Name | Notes |
|---|---|---|
| `0x00030001` | `OCA_FAIL_TRUNCATED` | Also an encrypted payload whose `payload_hashed_length` is wrong |
| `0x00030002` | `OCA_FAIL_MAGIC` | |
| `0x00030004` | `OCA_FAIL_FORMAT_VERSION_MISMATCH` | Manifest major version > 1 |
| `0x00030007` | `OCA_FAIL_CHIPLET_ID` | |
| `0x00030008` | `OCA_FAIL_PACKAGE_ID` | |
| `0x00030009` | `OCA_FAIL_SYSTEM_ID` | |
| `0x0003000a` | `OCA_FAIL_LIFECYCLE` | |
| `0x0003000d` | `OCA_FAIL_MANIFEST_HASH` | |
| `0x0003000e` | `OCA_FAIL_SIGNATURE` | |
| `0x0003000f` | `OCA_FAIL_CALLBACK_UNAVAILABLE` | A hash engine timeout |
| `0x00030012` | `OCA_FAIL_PAYLOAD_HASH` | |
| `0x00030013` | `OCA_FAIL_DECRYPT` | Bad PKCS#7 pad or AES failure |
| `0x00030014` | `OCA_FAIL_PAYLOAD_HASH_CHAIN` | The image content changes |
| `0x00030015` | `OCA_FAIL_PAYLOAD_TOC` | Any TOC rule, including TOC major version > 1; status ERROR `0x000f` |
| `0x00030016` | `OCA_FAIL_ROOT_KEY_REVOKED` | |
| `0x00030017` | `OCA_FAIL_SECURITY_VERSION` | |
| `0x00030019` | `OCA_FAIL_PAYLOAD_ENTRY_HASH` | Only the entry hash field changes |
| `0x0003001a` | `OCA_FAIL_PAYLOAD_TOO_MANY_IMAGES` | |
| `0x0003001b` | `OCA_FAIL_PAYLOAD_LOCATION` | Payload outside the slot window |
| `0x0003001c` | `OCA_FAIL_MANIFEST_LENGTH` | `manifest_length` is not the variant body size |
| `0x0003001d` | `OCA_FAIL_ENCRYPTION_REQUIRES_SECURE_BOOT` | |
| `0x0003001e` | `OCA_FAIL_NO_PROVISIONED_SECRET` | |
| `0x00030022` | `OCA_FAIL_CRYPTO_FIELD_SIZE` | Unsupported signature type |
| `0x00030023` | `OCA_FAIL_ROOT_KEY_UNAUTHORIZED` | |
| `0x00030100` | `OCA_BOOT_ERR_DMA` | |
| `0x00030101` | `OCA_BOOT_ERR_STAGE_OVERFLOW` | `PAYLOAD_TOO_LARGE` |
| `0x00030102` | `OCA_BOOT_ERR_NO_BL1` | |
| `0x00030103` | `OCA_BOOT_ERR_BL1_BAD_ADDR` | |
| `0x00030104` | `OCA_BOOT_ERR_BL1_TOO_LARGE` | |
| `0x00030106` | `OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` | `FLASH_READ_OOB` |
| `0x00030107` | `OCA_BOOT_ERR_FLASH_READ` | |

## 3. Status

- ERROR `0x000e` is INVALID_SIGNATURE; ERROR `0x000f` is TOC_ID_INVALID for any TOC rejection (`0x00030015`).
- A failed slot sends one WARN `status_for_result`; ERROR `0x0013` is sent only when the last slot also fails.
- A key revocation sends WARN or ERROR `0x007a`.
- ERROR `0x0213` follows ERROR `status_for_result(last)`; slot failover sends ERROR `0x0217`.
- INFO `0x004c` is sent for every slot that passes the magic peek, before version, length and hash; slot acceptance is INFO `0x0055`; INFO `0x0053` follows authentication.
- INFO `0x0051` is sent twice, plus INFO_EXT. INFO_EXT carries more words, which shifts positions and counts.
- `0x0003xxxx` codes send no status in `rom_err_fail`.

## 4. Constants

| Item | Value |
|---|---|
| manifest slot | 0x1000 / 0x41000 |
| payload | 0x2000 / 0x42000 |
| Read window per slot | 0x3F000 (ends at 0x40000 / 0x80000) |
| manifest body | 4096 B (PQC 36864 B) |
| Image end | Follows the OCA TOC (32 + 280·n + images); `total_size` 0x50000, pad 0xFF; SPI reads are a 20 B peek, the 4096 B body, then the payload |
| Manifest field offsets | magic @0, length @16, selector @24, ID @40/72/104, LC @136, demotion @172, secure_boot_control @182, secver @2042, enc type @2058, sig type @2092, pubk select @2104, key @2120, revoke @2655, payload_hash @2775, chain @2847, hashed_len @2911, payload_len @2960 (`oca_layout.C`) |
| cold scratch | 0x10802000 stride 8 (0 verdict, 1 status 0x10802008, 2 console 0x10802010, 7 warm 0x10802038; scratch 7 is cleared at dispatch) |
| SMC scratch | 0x40039080 (8/9/10/11 = C0/C8/D0/D8); 13/14 not read; 7 read back after the write |
| MBIST/DFX | 0x4000B800 (0x112 / 0x13) |
| straps | 0x40405800 / 0x40405804 (LO 13/19/20/21/25, HI 22/26) |
| SMC SRAM | 0x40060000, 1 MiB |
| BL1_JUMP | 0xC0000000; may also be in SRAM when `BL1_SRAM_EXEC_ENABLE=1` (default) |
| SEP SRAM staging | body 0x10000000, payload 0x10001000, BL1 source 0x10001000 + TOC offset, 0x3FFF8 available |
| fuse sense | Always waited for (0x10A30140 bit 0) |
| eFuse lc_state | 0x0C (RMA_CHIPLET is 0x6–0x7 only) |
| eFuse sboot_dis | 0x10 (a reserved bit is terminal and ranks after the signed bit) |
| eFuse class_key | 0x68 (OCA KDF; all zero = not provisioned; secret_select=1) |
| eFuse chiplet_pubk_revoke | 0x88 (ORed with the manifest bitmap) |
| eFuse bl1_version | 0x8C (128-bit superset across 4 words) |
| eFuse SYSCLK_FREQ_MHZ | 0x174 |
| eFuse chiplet_pubk_hash0 / hash1 | 0x178 / 0x198 |
| eFuse sip_pubk_hash1 | 0x240 |
| eFuse sep_chiplet / sip / sys_id | 0x280 / 0x2A0 / 0x2C0 (identity source) |
| key selection | 128-bit bitmap |
| secure boot flag | signed `secure_boot_control` @182 |
| demotion | signed `demotion_control` @172 |

<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

This table maps legacy ROM tokens to the OCA ROM for lookup only and is not a source of expected values: derive every testcase expectation from the ROM source.

# SEP boot ROM token map: legacy ROM to OCA

`test_oca_token_map.py` checks that every OCA token in table 1 is printed by the ROM or BL1
(`sep_oca_console.ROM_MARKERS` or `src/*.S`), and that every `oca_result_t` / `OCA_BOOT_ERR_*`
name in table 2 equals the listed code. The mapping itself (legacy verdict to OCA verdict) comes
from comparing the two ROM sources; the test does not check that the semantics are equivalent.

Global rules:

- `MANIFEST_OK` prints after `oca_validate_manifest` and before the payload checks; `PAYLOAD_OK` is what shows a slot was accepted.
- Every `MANIFEST_ERR=` / `MANIFEST_BOOT_FAIL=` code is renumbered and collides with an old number (table 2); never reuse an old literal.
- `MANIFEST_HASH_OK`, `SIG_VALID`, `CRYPTO_VALIDATE_OK`, `PLD_HASH_OK` and `RSA_VERIFY_START` no longer exist and must not appear in `expect`.
- Output from the VP and the warm stubs (the `[VP]` verdict line, `WARM_JUMP_OK`, `PST`) is not a ROM token and is not in table 1.

## 1. Token

| OLD token | OCA token | ROM symbol | Notes |
|---|---|---|---|
| `COLD` | `COLD` | `rom_main` | Unchanged |
| `MEM_INIT_OK` | `MEM_INIT_OK` | `rom_main` | Unchanged |
| `TRAP H0` | `TRAP H0` | `trap_handler_c` | Unchanged |
| `BOOT_SPI` / `BOOT_RECOVERY` / `BOOT_SECONDARY` | `BOOT_SPI` `BOOT_RECOVERY` `BOOT_SECONDARY` | `rom_main` | Unchanged |
| `>>SPI_INIT` / `<<SPI_INIT` | `>>SPI_INIT` `<<SPI_INIT` | `rom_main` | Unchanged |
| `SPI_INIT_OK` | `SPI_INIT_OK` | `rom_spi_init` | Unchanged |
| `OT_SPI: init ok` | `OT_SPI: init ok` | `ot_spi_init` | Unchanged |
| `SPI_ROTATE=` | `SPI_ROTATE=` | `rom_spi_init` | Unchanged |
| `STRAPS_LO=` / `STRAPS_HI=` | `STRAPS_LO=` `STRAPS_HI=` | `init_straps` | Unchanged |
| `STRAP primary=` / `rotate=` | `STRAP primary=` `rotate=` | `init_straps` | Unchanged |
| `SRAM_SCRUB_CFG=` | `SRAM_SCRUB_CFG=` | `rom_clear_ext_sram` | Unchanged |
| `SRAM_CLR_SKIP` / `SRAM_CLR_OK` | `SRAM_CLR_SKIP` `SRAM_CLR_OK` | `rom_clear_ext_sram` | Unchanged |
| `LC_STATE=` / `LC_STATE_INVALID=` | `LC_STATE=` `LC_STATE_INVALID=` | `rom_lifecycle_policy` | Unchanged |
| `LC=*` | `LC=TEST_DEV` `LC=PROD` `LC=PROD_END` `LC=RMA_CHIPLET` `LC=RMA_SIP` | `rom_lifecycle_policy` | Unchanged |
| `FUSE: SBOOT_DIS:` | `FUSE: SBOOT_DIS:` | `rom_sboot_dis_policy` | Unchanged |
| `SMC_STATUS_TO_SEP=` / `MANIFEST_OFF=` / `SMC_MANIFEST_ADDR=` | `SMC_STATUS_TO_SEP=` `MANIFEST_OFF=` `SMC_MANIFEST_ADDR=` | `rom_smc_coordination_probe` | Unchanged |
| `SMC_COORD_NOT_READY` / `SMC_MANIFEST_OFF_INVALID` | `SMC_COORD_NOT_READY` `SMC_MANIFEST_OFF_INVALID` | `rom_smc_coordination_probe` | Unchanged |
| `WAIT_SMC_MANIFEST` | `WAIT_SMC_MANIFEST` | `rom_manifest_boot` | Unchanged |
| `MANIFEST_SRC=` | `MANIFEST_SRC=` | `rom_manifest_boot` | Starts every slot attempt; with rotate, `MANIFEST_BACKUP` and `MANIFEST_SRC=0x00041000` print first |
| `MANIFEST_PRIMARY` / `MANIFEST_BACKUP` | `MANIFEST_PRIMARY` `MANIFEST_BACKUP` | `rom_manifest_boot` | Printed per slot, not per attempt order |
| `MANIFEST_ALL_FAILED` | `MANIFEST_ALL_FAILED` | `rom_manifest_boot` | Unchanged |
| `MANIFEST_ERR=` | `MANIFEST_ERR=` | `rom_manifest_boot` | Token unchanged, codes renumbered (table 2) |
| `MANIFEST_BOOT_FAIL=` | `MANIFEST_BOOT_FAIL=` | `rom_manifest_validate_handoff` | Token unchanged, codes renumbered (table 2) |
| `DEMOTE: *` | `DEMOTE: PROD_END lock` `DEMOTE: BL2 deferred, unlocked` `DEMOTE: BL2 deferred, lock non-demoted` | `rom_manifest_validate_handoff` | Unchanged |
| `BL1_DEMOTE=` / `BL2_DEMOTE_DEC=` | `BL1_DEMOTE=` `BL2_DEMOTE_DEC=` | `rom_manifest_validate_handoff` | Unchanged |
| `DEMOTE_LOCKED` / `DEMOTE_NOT_LOCKED` | `DEMOTE_LOCKED` `DEMOTE_NOT_LOCKED` | `rom_manifest_validate_handoff` | Unchanged |
| `FUSE_SECRETS_LOCKED` / `FUSE_SECRETS_NOT_LOCKED` / `LOCKS_LO=` | `FUSE_SECRETS_LOCKED` `FUSE_SECRETS_NOT_LOCKED` `LOCKS_LO=` | `check_fuse_secrets_locked` | Unchanged; the fuse lock runs after the measurement |
| `RSA_EXEC` / `RSA_EXEC_FAIL` / `RSA_CMP1` / `RSA_CMP2` | `RSA_EXEC` `RSA_EXEC_FAIL` `RSA_CMP1` `RSA_CMP2` | `rsa_3072_verify` | Unchanged |
| `RSA_PKCS1_FAIL` / `RSA_VERIFY_OK` | `RSA_PKCS1_FAIL` `RSA_VERIFY_OK` | `rsa_3072_verify` | Unchanged |
| `RSA_OTBN_INIT_FAIL` / `RSA_OTBN_LOAD_FAIL` | `RSA_OTBN_INIT_FAIL` `RSA_OTBN_LOAD_FAIL` | `rsa_3072_verify` | Unchanged |
| `OTBN_ERR=` | `OTBN_ERR=` | `otbn_execute` | Unchanged |
| `OTBN_RST_FAIL` | `OTBN_RST_FAIL` | `otbn_init` | Unchanged |
| `AES_*` | `AES_DEC_FAIL` `AES_PAD_BAD` `AES_RST_FAIL` `AES_BAD_KEYLEN` `AES_CTRL_REJECTED` `AES_INIT_BUSY` `AES_IDLE_TIMEOUT=` `AES_ALERT_STATUS=` `AES_ALERT_AFTER_DEC` | `aes_cbc_decrypt`, `aes_pkcs7_strip`, `aes_init`, `wait_idle`, `check_no_alert`, `plat_decrypt_payload` | Unchanged |
| `KDF_FAIL` | `KDF_FAIL` | `plat_decrypt_payload` | Unchanged |
| `KDF_HMAC_FAIL` | `KDF_HMAC_FAIL` | `oca_derive_payload_key` | Unchanged |
| `DECRYPT_OK` | `DECRYPT_OK` | `plat_decrypt_payload` | Printed only after the PKCS#7 check passes |
| `HMAC_*` | `HMAC_FIFO_TIMEOUT` `HMAC_OP_REJECTED` `HMAC_START_REJECTED` `HMAC_ERR_CODE=` | `hmac_sha256`, `check_no_error` | Unchanged |
| `SHA_*` | `SHA_FIFO_TIMEOUT` `SHA_OP_REJECTED` `SHA_START_REJECTED` | `sha256` | Unchanged |
| `PUBK_HASH_TIMEOUT` | `PUBK_HASH_TIMEOUT` | `plat_is_key_authorized` | Unchanged |
| `PRE_JUMP` | `PRE_JUMP` | `jump_to_bl1` | Unchanged |
| `BL1_COPIED` / `BL1_JUMP=` | `BL1_COPIED` `BL1_JUMP=` | `rom_handoff_bl1` | Unchanged |
| `COPY_SRC=` / `COPY_DST=` / `COPY_LEN=` | `COPY_SRC=` `COPY_DST=` `COPY_LEN=` | `rom_handoff_bl1` | Values follow the OCA TOC |
| `LOAD=` / `LEN=` / `ENTRY=` | `LOAD=` `LEN=` `ENTRY=` | `bl1_locate` | Values follow the OCA TOC; `rom_handoff_bl1`, `rom_clear_ext_sram` and `dma_transfer` also print `LEN=` |
| `NO_BL1_IMAGE` | `NO_BL1_IMAGE` | `bl1_locate` | After `PAYLOAD_OK`; code `0x00030102` |
| `BL1_ADDR_RANGE` / `BL1_ENTRY_RANGE` | `BL1_ADDR_RANGE` `BL1_ENTRY_RANGE` | `bl1_locate` | After `PAYLOAD_OK`; code `0x00030103` |
| `PUBK_SEL=` | `PUBK_SEL=` | `plat_is_key_authorized` | New meaning: one bitmap slot number; old `0x20` is `0x11`, `0x30` does not print, `0x06` prints before `PUBK_SLOT_RESERVED` |
| `PUBK_REVOKE=` | `PUBK_REVOKE=` | `plat_get_root_key_revocation` | New meaning: printed after `PUBK_AUTHORIZED` |
| `FUSE_VER=` | `FUSE_VER=` | `plat_get_security_version` | New meaning: the raw low 32 bits, printed after revocation |
| `MFST_VER=` | `MFST_VER=` | `try_manifest_slot` | New meaning: low 32 bits of the 16 B flag field, printed for every slot |
| `SBOOT_OFF` | `SBOOT_OFF` | `rom_manifest_validate_handoff` | Printed once, after a slot succeeds |
| `MANIFEST_HASH_OK` | none | — | Removed; `PAYLOAD_OK` shows the slot was accepted |
| `MANIFEST_HASH_MISMATCH` | none | — | `MANIFEST_ERR=0x0003000d`; WARN/ERROR `0x0013` |
| `*_HASH_TIMEOUT` | `HMAC_FIFO_TIMEOUT` `SHA_FIFO_TIMEOUT` | `hmac_sha256`, `sha256` | Code `0x0003000f` |
| `SIG_VALID` | `RSA_VERIFY_OK` | `rsa_3072_verify` | Removed |
| `RSA_VERIFY_START` | `PUBK_AUTHORIZED` `RSA_EXEC` | `plat_is_key_authorized`, `rsa_3072_verify` | Removed; order is `PUBK_AUTHORIZED` then `RSA_EXEC` |
| `RSA_VERIFY_FAIL` | `RSA_PKCS1_FAIL` `RSA_EXEC_FAIL` `RSA_INOUT_UNCHANGED` | `rsa_3072_verify` | Code `0x0003000e` |
| `CRYPTO_VALIDATE_OK` | `MANIFEST_OK` `PAYLOAD_OK` | `try_manifest_slot` | Removed |
| `CRYPTO_FAIL=` | `MANIFEST_ERR=` | `rom_manifest_boot` | Codes in table 2 |
| `PLD_HASH_OK` | `PAYLOAD_OK` | `try_manifest_slot` | Removed |
| `PLD_HASH_MISMATCH` / `PLD_HASH_FAIL` | none | — | Code `0x00030012` |
| `DECRYPT_START` | none | — | Status INFO `0x0040` |
| `DECRYPT_TERMINAL=` | none | — | A decrypt failure now fails over |
| `DECRYPT_FAIL` | none | — | The legacy ROM does not print it either |
| `AES_INIT_FAIL` | none | — | No console output; code `0x00030013` |
| `BAD_SIG_TYPE=` | none | — | Code `0x00030022` / `0x00030023` |
| `BAD_KEY_IDX` | `PUBK_SLOT_RESERVED` `PUBK_SLOT_PQC_UNSUPPORTED` | `plat_is_key_authorized` | |
| `BAD_KEY_SEL` | `PUBK_SEL_AMBIGUOUS` `PUBK_SEL_EMPTY` | `plat_is_key_authorized` | |
| `ROM_KEY_EMPTY` | `PUBK_SLOT_UNPROVISIONED` | `plat_is_key_authorized` | |
| `FUSE_KEY_EMPTY` | `PUBK_OTP_EMPTY` | `plat_is_key_authorized` | |
| `PUBK_HASH_MISMATCH` | `PUBK_UNAUTHORIZED` | `plat_is_key_authorized` | Code `0x00030023` |
| `KEY_REVOKED idx=` | none | — | Code `0x00030016` |
| `VERSION_ROLLBACK` | none | — | Code `0x00030017` |
| `CID_*` / `CHIPLET_ID_MISMATCH` | none | — | Code `0x00030007` |
| `PID_*` | none | — | Code `0x00030008`; system ID `0x00030009` |
| `LC_USAGE_*` / `LC_ALLOWED=` / `LC_BIT=` | none | — | Code `0x0003000a` |
| `ENC_WITHOUT_SBOOT` | none | — | Code `0x0003001d` |
| `ENC_HASHED_LEN_PARTIAL` | none | — | Code `0x00030015` |
| `PAYLOAD_OFF_RANGE` / `PAYLOAD_LEN_RANGE` / `PAYLOAD_OVERLAPS_MANIFEST` / `PAYLOAD_LOC_*` | `PAYLOAD_LOC_FAIL` `FLASH_READ_OOB` | `try_manifest_slot`, `manifest_src_read` | `PAYLOAD_LOC_FAIL` with `0x0003001b`, or `FLASH_READ_OOB` with `0x00030106` |
| `PAYLOAD_OFF_ALIGN` | none | — | No matching verdict |
| `PAYLOAD_HASHED_LEN_BAD=` | none | — | Code `0x00030015`; `0x00030001` when encrypted |
| `TOC_REGION_OOB=` / `TOC_PLEN_MISMATCH=` | none | — | Code `0x00030015` |
| `IMAGE_*` | none | — | Code `0x00030015`, without an index |
| `IMAGE_LEN_ALIGN` / `IMAGE_ORDER_BAD idx=0` | none | — | No matching verdict |
| `IMAGE_HASH_MISMATCH` | none | — | Code `0x00030014` or `0x00030019` |
| `IMAGES=` / `PAYLOAD=` / `BL1_TYPE=` | none | — | The closest is `OCA_BODY=` (`try_manifest_slot`) |
| `PAYLOAD_DST=` | none | — | |
| `USING_*_SRAM` / `EXT_SRAM_INIT_WAIT` / `SMC_WIN_*` / `PAYLOAD_NO_ROOM=` / `STAGED_WIPE=` | none | — | External SRAM selection is removed; the closest is `PAYLOAD_TOO_LARGE` with `0x00030101` |
| `FLASH_REINIT_FAIL=` | none | — | |
| `MEAS_*` / `MEASUREMENT_OK` / `MEASUREMENT_FAIL` | `MEAS_BOOT_STATE_OK` `ROM_HASH_VERIFIED` | `rom_manifest_validate_handoff`, `measurement_enroll_rom_hash` | The measurement uses two soft-PCR slots |
| `BL1` | `BL1` | `_start` (bl1_pass_test) | BL1 token |
| `BL0S_CHK` / `BL0S_OK` / `BL0S_VERIFY_FAIL` | `BL0S_CHK` `BL0S_OK` `BL0S_VERIFY_FAIL` | `_start` (bl1_pass_test) | BL1 token |
| `BL0S_MFST=0x10000000` | `BL0S_MFST=` | `bl1_verify_bl0_state` (bl1_pass_test) | Value unchanged |
| `FAIL:*` | `FAIL:BL0S` `FAIL:BL0S_MFST` `FAIL:LOCKS` `FAIL:CLASS_KEY=` `FAIL:RMA_CHIP=` `FAIL:RMA_SIP=` | `bl1_verify_bl0_state`, `bl1_verify_fuse_locks`, `bl1_test_locked_field_reads` (bl1_pass_test) | BL1 token |
| `FUSE_CHK` / `FUSE_OK` / `FUSE_LOCK_VERIFY_FAIL` | `FUSE_CHK` `FUSE_OK` `FUSE_LOCK_VERIFY_FAIL` | `_start` (bl1_pass_test) | BL1 token |
| `LOCKS=0x8880A800` | `LOCKS=` | `bl1_verify_fuse_locks` (bl1_pass_test) | BL1 token |
| `LOCK_RD*` | `LOCK_RD` `LOCK_RD_OK` `LOCK_RD_FAIL` | `_start` (bl1_pass_test) | BL1 token |
| `GO!` | `GO!` | `_start` (bl1_pass_test) | BL1 token |
| `BL0S_MEAS=` | `BL0S_BOOT_PCR=` | `bl1_verify_bl0_state` (bl1_pass_test) | The value is SHA256(0^32 ‖ SHA256(40 B record)); see `boot_measurement_golden.py` |

## 2. Error codes

OCA code = `OCA_BOOT_ERR_BASE (0x00030000) | oca_result_t`; `0x000301xx` are the ROM's own `OCA_BOOT_ERR_*`.
"Same number, new meaning" names the verdict that the old number stands for under OCA, so an old literal is not reused by mistake.

| OLD code | OCA code | oca_result_t name | Notes |
|---|---|---|---|
| `01` DMA_FAILED | `0x00030100` `0x00030107` `0x00030106` | `OCA_BOOT_ERR_DMA` `OCA_BOOT_ERR_FLASH_READ` `OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` | Same number, new meaning: TRUNCATED |
| `02` BAD_MAGIC | `0x00030002` | `OCA_FAIL_MAGIC` | Same number, same meaning |
| `03` BAD_VERSION | `0x00030004` | `OCA_FAIL_FORMAT_VERSION_MISMATCH` | major > 1; same number, new meaning: TRAILER |
| `04` BAD_LENGTH | `0x0003001c` `0x0003001b` `0x00030015` `0x00030001` | `OCA_FAIL_MANIFEST_LENGTH` `OCA_FAIL_PAYLOAD_LOCATION` `OCA_FAIL_PAYLOAD_TOC` `OCA_FAIL_TRUNCATED` | Depends on the length field; same number, new meaning: FORMAT_VERSION |
| `05` BAD_TOC_ID | `0x00030102` `0x00030013` `0x00030014` `0x00030015` | `OCA_BOOT_ERR_NO_BL1` `OCA_FAIL_DECRYPT` `OCA_FAIL_PAYLOAD_HASH_CHAIN` `OCA_FAIL_PAYLOAD_TOC` | No direct match; NO_BL1 at hand-off, the other three for garbage after decryption; same number, new meaning: RESERVED_BITS |
| `06` BAD_TOC_VERSION | `0x00030015` | `OCA_FAIL_PAYLOAD_TOC` | TOC major > 1; same number, new meaning: SECURE_BOOT_INVARIANT |
| `07` PAYLOAD_TOO_LARGE | `0x0003001b` `0x00030101` | `OCA_FAIL_PAYLOAD_LOCATION` `OCA_BOOT_ERR_STAGE_OVERFLOW` | Same number, new meaning: CHIPLET_ID |
| `08` NO_BL1 | `0x00030102` | `OCA_BOOT_ERR_NO_BL1` | Same number, new meaning: PACKAGE_ID |
| `09` BL1_TOO_LARGE | `0x00030104` | `OCA_BOOT_ERR_BL1_TOO_LARGE` | Same number, new meaning: SYSTEM_ID |
| `0a` BL1_BAD_ADDR | `0x00030103` | `OCA_BOOT_ERR_BL1_BAD_ADDR` | Same number, new meaning: LIFECYCLE |
| `0b` manifest HASH_MISMATCH | `0x0003000d` | `OCA_FAIL_MANIFEST_HASH` | Same number, new meaning: VERSION_RANGE |
| `0c` SIG_FAILED | `0x0003000e` `0x00030022` `0x00030023` `0x0003000f` | `OCA_FAIL_SIGNATURE` `OCA_FAIL_CRYPTO_FIELD_SIZE` `OCA_FAIL_ROOT_KEY_UNAUTHORIZED` `OCA_FAIL_CALLBACK_UNAVAILABLE` | Same number, new meaning: DEMOTION_CONTROL |
| `0d` BAD_IMAGE_TYPE | none | none | No matching verdict; same number, new meaning: MANIFEST_HASH |
| `0e` IMAGE_OOB | `0x00030015` | `OCA_FAIL_PAYLOAD_TOC` | Same number, new meaning: SIGNATURE |
| `0f` IMAGE_OVERLAP | `0x00030015` | `OCA_FAIL_PAYLOAD_TOC` | Same number, new meaning: CALLBACK_UNAVAILABLE |
| `10` TOC_COUNT | `0x00030015` `0x0003001a` | `OCA_FAIL_PAYLOAD_TOC` `OCA_FAIL_PAYLOAD_TOO_MANY_IMAGES` | Same number, new meaning: INVALID_ARG |
| `11` PAYLOAD_OVERLAP | `0x0003001b` | `OCA_FAIL_PAYLOAD_LOCATION` | Same number, new meaning: UNSUPPORTED_VARIANT |
| `12` PAYLOAD_BAD_LOC | `0x0003001b` `0x00030106` | `OCA_FAIL_PAYLOAD_LOCATION` `OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` | Same number, new meaning: PAYLOAD_HASH |
| `13` LC_USAGE | `0x0003000a` `0x00030007` `0x00030008` `0x0003001d` | `OCA_FAIL_LIFECYCLE` `OCA_FAIL_CHIPLET_ID` `OCA_FAIL_PACKAGE_ID` `OCA_FAIL_ENCRYPTION_REQUIRES_SECURE_BOOT` | Depends on the constraint; same number, new meaning: DECRYPT |
| `14` VERSION_ROLLBACK | `0x00030017` | `OCA_FAIL_SECURITY_VERSION` | Same number, new meaning: PAYLOAD_HASH_CHAIN |
| `15` KEY_REVOKED | `0x00030016` | `OCA_FAIL_ROOT_KEY_REVOKED` | Same number, new meaning: PAYLOAD_TOC |
| `16` KEY_HASH_MISMATCH | `0x00030023` | `OCA_FAIL_ROOT_KEY_UNAUTHORIZED` | Same number, new meaning: ROOT_KEY_REVOKED |
| `17` PAYLOAD_HASH | `0x00030012` | `OCA_FAIL_PAYLOAD_HASH` | Same number, new meaning: SECURITY_VERSION |
| `18` DECRYPT_FAILED | `0x00030013` `0x0003001e` | `OCA_FAIL_DECRYPT` `OCA_FAIL_NO_PROVISIONED_SECRET` | Same number, new meaning: SECURITY_STATE_UPDATE |
| `19` IMAGE_HASH | `0x00030014` `0x00030019` | `OCA_FAIL_PAYLOAD_HASH_CHAIN` `OCA_FAIL_PAYLOAD_ENTRY_HASH` | 0x14 when the image content changes, 0x19 when only the entry hash field changes; same number, new meaning: PAYLOAD_ENTRY_HASH |
| `1a` PAYLOAD_NO_ROOM | `0x00030101` | `OCA_BOOT_ERR_STAGE_OVERFLOW` | Usually no matching verdict; same number, new meaning: TOO_MANY_IMAGES |
| `1b` IMAGE_ALIGN | `0x00030015` | `OCA_FAIL_PAYLOAD_TOC` | Same number, new meaning: PAYLOAD_LOCATION |

## 3. Status

| OLD status | OCA status |
|---|---|
| DEBUG 0x0044 | Unchanged |
| DEBUG 0x0207 | None |
| ERROR 0x0004 / 0x0005 / 0x000e / 0x000f / 0x0010 / 0x0015 (truncated codes) | Removed; OCA ERROR 0x000e is INVALID_SIGNATURE and ERROR 0x000f is TOC_ID_INVALID for any TOC rejection (0x15), so an old `forbid` would trip on them |
| ERROR 0x0013 | One WARN per failed slot; ERROR only when the last slot also fails |
| ERROR 0x0016 | WARN / ERROR 0x007a |
| ERROR 0x0028 / 0x0069 | Unchanged |
| ERROR 0x0213 | Unchanged, preceded by ERROR `status_for_result(last)` |
| ERROR 0x0067 / 0x008b | Removed |
| ERROR 0x0224 | WARN 0x0215 or an OT SPI code |
| INFO 0x0020 / 0x0023 / 0x002a / 0x002c / 0x004a / 0x0054 / 0x0058 / 0x007d / 0x0090 / 0x0212 / 0x021b / 0x021c | Unchanged |
| INFO 0x004c | Earlier: sent for every slot that passes the magic peek, before version / length / hash |
| INFO 0x004f / 0x0039 / 0x0098 / 0x0099 / 0x009b / 0x009c | None |
| INFO 0x0051 | Twice, plus INFO_EXT |
| INFO 0x0053 | Only after authentication; slot acceptance is now INFO 0x0055 |
| (new) | Per-slot WARN `status_for_result`; INFO 0x0040 / 0x0042 / 0x0055; DEBUG 0x0052 / 0x009e; ERROR 0x0012 / 0x0014 / 0x012b / 0x0217 (also on slot failover); INFO 0x0225 / 0x0228; ERROR 0x0226 / 0x0227; WARN 0x0229 / 0x022a / 0x022b / 0x0215 |

INFO_EXT carries more words, which shifts positions and counts; `0x0003xxxx` codes send no status in `rom_err_fail`.

## 4. Constants

| Item | OLD | OCA |
|---|---|---|
| manifest slot | 0x1000 / 0x41000 | Unchanged |
| payload | 0x2000 / 0x42000 | Unchanged |
| Read window per slot | ends at 0x41000 / 0x81000 | 0x3F000 (ends at 0x40000 / 0x80000) |
| manifest body | 1184 B | 4096 B (PQC 36864 B) |
| Image end | Fixed | Follows the OCA TOC (32 + 280·n + images); `total_size` 0x50000, pad 0xFF; every `spi_reads` range and count is recomputed (peek 20 B, body 4096 B, then the payload) |
| Manifest field offsets | legacy layout | magic @0, length @16, selector @24, ID @40/72/104, LC @136, demotion @172, secure_boot_control @182, secver @2042, enc type @2058, sig type @2092, pubk select @2104, key @2120, revoke @2655, payload_hash @2775, chain @2847, hashed_len @2911, payload_len @2960 (`oca_layout.C`) |
| cold scratch | 0x10802000 stride 8 | Unchanged (0 verdict, 1 status 0x10802008, 2 console 0x10802010, 7 warm 0x10802038; scratch 7 is cleared at dispatch) |
| SMC scratch | 0x40039080 | Unchanged (8/9/10/11 = C0/C8/D0/D8); 13/14 not read; 7 read back after the write |
| MBIST/DFX | 0x4000B800 | Unchanged (0x112 / 0x13) |
| straps | 0x40405800 / 0x40405804 | Unchanged (LO 13/19/20/21/25, HI 22/26) |
| SMC SRAM | 0x40060000, 1 MiB | Unchanged |
| BL1_JUMP | 0xC0000000 | Unchanged; may also be in SRAM when `BL1_SRAM_EXEC_ENABLE=1` (default) |
| SEP SRAM staging | — | body 0x10000000, payload 0x10001000, BL1 source 0x10001000 + TOC offset, 0x3FFF8 available |
| fuse sense | — | Always waited for (0x10A30140 bit 0) |
| eFuse lc_state | — | 0x0C (RMA_CHIPLET is 0x6–0x7 only) |
| eFuse sboot_dis | — | 0x10 (a reserved bit is terminal and ranks after the signed bit) |
| eFuse class_key | — | 0x68 (OCA KDF; all zero = not provisioned; secret_select=1) |
| eFuse chiplet_pubk_revoke | — | 0x88 (ORed with the manifest bitmap) |
| eFuse bl1_version | — | 0x8C (128-bit superset across 4 words) |
| eFuse chiplet_pubk_hash0 / hash1 | 0x198 / 0x1B8 | 0x178 / 0x198 |
| eFuse sip_pubk_hash1 | 0x260 | 0x240 |
| eFuse sep_chiplet / sip / sys_id | 0x2A0 / 0x2C0 / 0x2E0 | 0x280 / 0x2A0 / 0x2C0 (identity source) |
| eFuse SPI fields | Present | Removed; SYSCLK_FREQ_MHZ at 0x174 |
| key selection | index | 128-bit bitmap |
| secure boot flag | fuse / manifest flag | signed `secure_boot_control` @182 |
| demotion | — | signed `demotion_control` @172 |
| use_ext_sram (bit 29) / skip_sha256 (bit 31) | Present | Removed |

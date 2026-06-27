# OpenTitan package stubs (`ot_pkg`)

This directory holds **local copies** of selected OpenTitan SystemVerilog packages. They are trimmed or customized for Tenstorrent (TT) silicon and are **not** wired from `vendor/opentitan/upstream/hw/ip/...` at compile time, even though matching files exist upstream (see `vendor_package` in the repo-root `Bender.yml`).

RTL lives under `rtl/`. Packages are compiled early in the global file list so vendored OT blocks (OTBN, KMAC, AES, CSRNG/EDN) and TT wrappers share common typedefs and parameters.

## Why keep local copies?

Upstream OpenTitan evolves independently of TT. Several files here intentionally differ from vendor:

| Concern | Local choice |
|--------|----------------|
| Lifecycle | `lc_ctrl_state_pkg` uses a **fixed sparse-encoding seed** tied to OTP typedefs in `otp_ctrl_pkg` |
| Naming | `flash_*` / `FlashRmaSt` vs upstream `nvm_*` / `NvmRmaSt` |
| Key manager | `keymgr_pkg` uses **TT-specific** `RndCnst*SeedDefault` constants |
| Entropy | `entropy_src_pkg` adds `cs_aes_halt_*` types; omits vendor `ht_watermark_num_e` |
| LC control | `lc_ctrl_pkg` is a **subset** (no `lc_to_mubi8` / `lc_to_mubi4_inv`) |

Do not replace these files with vendor copies without a full interface and regression review.

## Build integration

**Bender** (`Bender.yml`, “Packages needed by OTBN”):

| Compiled from `ot_pkg` | Compiled elsewhere (same package name) |
|------------------------|--------------------------------------|
| `entropy_src_pkg.sv` | — |
| `lc_ctrl_state_pkg.sv` | — |
| `lc_ctrl_reg_pkg.sv` | — |
| `lc_ctrl_pkg.sv` | — |
| `keymgr_reg_pkg.sv` | — |
| `keymgr_pkg.sv` | — |
| `otp_ctrl_pkg.sv` | — |
| — | `csrng_pkg.sv` → `hw/comp/csrng/rtl/` |
| — | `edn_pkg.sv` → `hw/comp/edn/rtl/` |

Legacy filelists (`dv/smu/tb/tb_uvm/tt_smu.f`, `fv/smu/synopsys_vcf/filelist/smu_fv.fl`) still list **`ot_pkg` copies** of `csrng_pkg.sv` and `edn_pkg.sv`. SMC paths (`tt_smc.f`) already use `hw/comp` for CSRNG/EDN. The `ot_pkg` `csrng_pkg.sv` file is an **obsolete stub**; do not use it in new flows.

**OTBN** (`vendor/opentitan/upstream/hw/ip/otbn`) depends on `otp_ctrl_pkg` and is built on SEP after `sep_crypto_pkg` imports the OT packages.

## Package dependency graph

```
lc_ctrl_state_pkg
       │
       ├──► lc_ctrl_reg_pkg (width constants only)
       │
       ├──► lc_ctrl_pkg ──► used by crypto IPs + wrappers
       │
       └──► otp_ctrl_pkg ──► OTBN scramble / LC OTP structs

keymgr_reg_pkg ──► keymgr_pkg ──► AES / KMAC / HMAC / OTBN sideload

entropy_src_pkg ──► CSRNG / EDN / DRBG entropy bus widths
       ▲
       │ (ot_pkg copy required in filelist before hw/comp/csrng)

csrng_pkg (hw/comp) ──► edn_pkg (hw/comp)
```

## TT lifecycle vs OpenTitan lifecycle

TT product lifecycle (manufacturing states on SEP/SMC/efuse) uses **`sep_pkg::lc_state`** and related TT registers. That is **separate** from OpenTitan’s `lc_ctrl_state_pkg` sparse state encodings.

`lc_ctrl_pkg::lc_tx_t` (`On` / `Off` and test helpers) is what TT RTL uses for **OpenTitan-style** lifecycle *signals* on crypto blocks (escalate, hardware debug, RMA). Today most SEP wrappers tie these inputs to **`lc_ctrl_pkg::Off`** because there is no full OT `lc_ctrl` block in the SoC—only the typedefs and port compatibility.

---

## Per-package usage

### `lc_ctrl_pkg.sv`

**Role:** Life-cycle **signal** types and helpers (`lc_tx_t`, `lc_to_mubi4`, `lc_tx_test_*`, token indices, CSR width typedefs in `lc_hw_rev_t`).

**TT usage:**

| Area | How it is used |
|------|----------------|
| `hw/ip/kmac`, `hw/ip/aes` | `lc_escalate_en_i` ports; FSMs gate operation on `lc_tx_test_*` |
| `hw/comp/csrng` | `lc_hw_debug_en_i` for DRBG debug policy |
| `hw/comp/drbg` | `lc_hw_debug_en_i` on the integrated DRBG top |
| `hw/sep/*_wrapper.sv`, `sep_crypto.sv` | Ports tied to **`lc_ctrl_pkg::Off`** (escalate / debug / RMA not driven from TT LC yet) |
| `hw/sep/sep_crypto_otbn_wrapper.sv` | `lc_escalate_en_i`, `lc_rma_req_i` → `Off`; `lc_rma_ack_o` typed as `lc_tx_t` |

**Not instantiated:** No `lc_ctrl` RTL module in TT. Only the package API is reused.

---

### `lc_ctrl_state_pkg.sv`

**Role:** Sparse-encoded LC **state** and **counter** types (`lc_state_t`, `lc_cnt_t`, `lc_token_t`, enums `lc_state_e`, `lc_cnt_e`) and decode helpers.

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `otp_ctrl_pkg.sv` | `otp_lc_data_t`, `lc_otp_program_req_t`, and `OTP_LC_DATA_DEFAULT` reference `LcStTestUnlocked0`, `LcCnt1`, tokens |
| `lc_ctrl_pkg.sv` | `import lc_ctrl_state_pkg::*` |
| *(no other direct RTL imports in `hw/`)* | Compiled for OTP/OTBN consistency; **not** the same as `sep_pkg` lifecycle |

Changing the generation seed in this file breaks OTP partition / LC data layout expectations.

---

### `lc_ctrl_reg_pkg.sv`

**Role:** Register-parameter widths for a full OT `lc_ctrl` block (`SiliconCreatorIdWidth`, `ProductIdWidth`, OTP/vendor error struct field names).

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `lc_ctrl_pkg.sv` | `lc_hw_rev_t` field widths |
| *(otherwise)* | Pulled into filelists for compile closure; **no** `lc_ctrl` reg top in TT |

Local rename example: `flash_rma_error` vs upstream `nvm_rma_error`.

---

### `otp_ctrl_pkg.sv`

**Role:** OTP/LC **interface typedefs** without importing top-specific `otp_ctrl_reg_pkg` (suitable for generic IPs).

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `vendor/.../otbn` | `otbn_otp_key_req_t` / `otbn_otp_key_rsp_t`, scramble key/nonce types, `RndCnstOtbnKeyDefault` |
| `hw/sep/sep_crypto_otbn_wrapper.sv` | **Mock** OTP key response (fixed key/nonce) on `otbn_otp_key_*` ports |
| `hw/sep/sep_crypto_pkg.sv` | `import otp_ctrl_pkg::*` for OTBN integration |
| `otp_ctrl_pkg` internally | Imports `lc_ctrl_state_pkg` + `lc_ctrl_pkg` for LC/OTP structs |

TT does not instantiate OpenTitan `otp_ctrl` RTL; the package satisfies OTBN’s port types and default parameters.

---

### `keymgr_reg_pkg.sv`

**Role:** Register layout constants for OT key manager (`NumSwBindingReg`, `NumSaltReg`, etc.).

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `keymgr_pkg.sv` | `SwBindingWidth`, `SaltWidth` derived from reg counts |
| *(no direct RTL import elsewhere)* | Required whenever `keymgr_pkg` is compiled |

**Not instantiated:** TT **`hw/comp/key_manager`** is a separate design; it does not include the OT `keymgr` reg block. It drives **`keymgr_pkg`** sideload structs from its own CSRs.

---

### `keymgr_pkg.sv`

**Role:** Key-manager **sideload** and OTBN key interface types (`hw_key_req_t`, `otbn_key_req_t`, widths, TT `RndCnst*SeedDefault`).

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `hw/ip/aes`, `hw/ip/kmac`, `hw/ip/hmac` | `keymgr_key_i` / `hw_key_req_t` sideload ports (OpenTitan-compatible) |
| `hw/sep/aes_wrapper.sv`, `kmac_wrapper.sv`, `hmac_wrapper.sv` | Build `hw_key_req_t` from **key_manager** CSRs |
| `hw/sep/sep_crypto_otbn_wrapper.sv` | `otbn_key_req_t` from `otbn_wrapper_key` CSRs → OTBN `keymgr_key_i` |
| `hw/sep/sep_crypto_pkg.sv` | Imports package for SEP crypto subsystem |
| DV (`kmac_env_pkg`, `aes` UVM) | Sideload agents typed with `hw_key_req_t` |

The OT **keymgr FSM** is not in the netlist; only the **package-level wire types** connect TT key_manager to OT crypto accelerators.

---

### `entropy_src_pkg.sv`

**Role:** Entropy **hardware interface** widths and structs between entropy source and CSRNG (`entropy_src_hw_if_*`, `CSRNG_BUS_WIDTH`, `FIPS_BUS_WIDTH`, `cs_aes_halt_*`).

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `hw/comp/drbg` | `drbg_csrng_seed_adapter` — entropy bus to CSRNG seed path |
| `hw/comp/csrng` | `entropy_src_hw_if_o/i` on `csrng` / `csrng_core` |
| `hw/comp/edn` | `FIPS_BUS_WIDTH` in `edn_pkg` endpoint width math |
| `hw/comp/csrng/rtl/csrng_pkg.sv` | `FIPS_GENBITS_BUS_WIDTH` uses `entropy_src_pkg::FIPS_BUS_WIDTH` |

**Related but separate:** `hw/ip/entropy_source` is the TT entropy-source block (PeakRDL registers, `watermark_test_e` in block RTL). It does **not** import this package for HT watermark enums; the DRBG/CSRNG chain uses the **bus typedefs** from `entropy_src_pkg` only.

---

### `csrng_pkg.sv` (in `ot_pkg` — legacy only)

**Role:** CSRNG application command/status types.

**TT usage:** **None** for current SMC/Bender builds. Active RTL uses **`hw/comp/csrng/rtl/csrng_pkg.sv`** (matches vendor). The file here is an old stub kept for SMU/FV filelists; prefer `hw/comp` paths for new work.

---

### `edn_pkg.sv` (in `ot_pkg` — legacy duplicate)

**Role:** EDN endpoint request/response types (`edn_req_t`, `edn_rsp_t`).

**TT usage:**

| Consumer | Usage |
|----------|--------|
| `hw/comp/edn`, `hw/comp/drbg` | Primary copies from **`hw/comp/edn/rtl/edn_pkg.sv`** (byte-identical to vendor) |
| `hw/sep/sep_crypto.sv` | AXI-stream DRBG ↔ crypto client `edn_req_t` / `edn_rsp_t` arrays |
| `hw/sep/*_wrapper.sv`, `sep_crypto_otbn_wrapper.sv` | Per-IP EDN randomness ports |

The `ot_pkg` copy exists for legacy SMU filelists; Bender already compiles `hw/comp/edn/rtl/edn_pkg.sv`.

---

## Related directories (not in `ot_pkg`)

| Path | Relationship |
|------|----------------|
| `vendor/opentitan/upstream/hw/ip/<ip>/rtl/*_pkg.sv` | Upstream originals; compare before any merge |
| `hw/comp/csrng`, `hw/comp/edn`, `hw/comp/drbg` | TT DRBG stack; uses `entropy_src_pkg` from here + local `csrng`/`edn` packages |
| `hw/comp/key_manager` | TT key delivery; drives `keymgr_pkg` interfaces |
| `hw/ip/entropy_source` | TT physical entropy block (registers + RTL) |
| `hw/sep/sep_pkg.sv` | TT lifecycle / fuse map — **not** `lc_ctrl_state_pkg` |

## Maintenance notes

1. When updating from OpenTitan, diff each file against `vendor/opentitan/upstream/hw/ip/<ip>/rtl/<same_name>.sv` and preserve TT-specific seeds, renames, and added types.
2. Keep **`entropy_src_pkg` → `lc_ctrl_*` → `otp_ctrl_pkg` → `keymgr_*`** compile order in filelists (as in `Bender.yml`).
3. Prefer aligning SMU/FV filelists with SMC (`hw/comp` for CSRNG/EDN) to avoid compiling the obsolete `ot_pkg/csrng_pkg.sv` stub.

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SEP DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw-libs TARGET=sep
FW_NAME := sep
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
# The SEP boot ROM sits outside the DV tree (hw/sys/sep/bootrom/prod, mirroring
# hw/sys/smc/bootrom/); this engine borrows its headers and elf-to-vmem tool.
SEP_BOOTROM_DIR := $(abspath $(FW_DIR)/../../bootrom/prod)
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# Runtime sources. Tests supply their own main() and link against libsep.a.
# fw_build_id.c is outside drivers/. The nonfree SEP firmware build compiles
# every drivers/*.c and does not generate fw_build_id.h.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c) $(FW_DIR)/fw_build_id.c
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)
FW_INCLUDES := -I$(FW_DIR)/include

# Register headers via the shared engine helper (umbrella sep.h under
# hw/common/dv/fw + this sys's generated headers).
FW_REG_SYS := sep

# Test discovery is unified in compile.mk; declare only the SEP deltas.
FW_TEST_EXCLUDE_NAMES := bl1_pass_test sep_smu_spi_mux
# drivers/ carries runtime headers (sep_mailbox.h etc.) that tests include directly.
# The boot ROM's include/ holds the rom_*/boot_* headers that the sep_smc_* and
# sep_smu_* tests include directly. The register headers are not here:
# compile.mk already puts the generated regs/gen/c dirs on the path.
FW_TEST_INCLUDES := -I$(FW_DIR)/tests/common -I$(FW_DIR)/drivers \
                    -I$(SEP_BOOTROM_DIR)/include
FW_TEST_COMMON_SRCS := $(FW_DIR)/tests/common/sha256.c

# OTBN applications.
#
# The OTBN tests load an image into OTBN's IMEM/DMEM and check the CRC the
# hardware reports against the one computed at build time, so the image has to
# be assembled here rather than checked in. Each app becomes a generated
# <app>_otbn.c (memory arrays + CRC) and <app>_otbn.h (DMEM symbol addresses)
# that the test links against. Upstream drives this from one Makefile per test;
# this tree builds every test from the shared engine, so the app inventory
# lives here and each app is produced by a recursive make on common_otbn's
# otbn_app.mk - the same entry point upstream uses for its own multi-app test.
FW_BUILD_DIR    ?= $(FW_DIR)/build

# Build identity. fw_src_digest.py hashes every source directory the images can
# draw from and writes the digest to fw_build_id.h, touching the header only
# when the digest changes. fw_build_id.c compiles it into each image as
# "FW-BUILD-ID:<digest>"; sep_base_test reads it back out of the loaded TCM
# image and compares it with the digest of the committed tree
# (CHK-FW-IDENTITY), so an image built from other source fails a logged check.
FW_BUILD_ID_H := $(FW_BUILD_DIR)/fw_build_id.h
FW_SRC_DIGEST := $(shell python3 "$(FW_DIR)/fw_src_digest.py" --write-header "$(FW_BUILD_ID_H)" "$(OCAH_ROOT)")
ifeq ($(strip $(FW_SRC_DIGEST)),)
$(error fw_src_digest.py produced no digest; the firmware build identity is required)
endif
FW_INCLUDES += -I$(FW_BUILD_DIR)

OTBN_APP_MK     := $(FW_DIR)/tests/common_otbn/otbn_app.mk
OTBN_BUILD_ROOT := $(FW_BUILD_DIR)/otbn

# Per app: the test directory whose otbn_src/ holds the sources, and the
# sources themselves. Sources present in otbn_src/ but absent here are not
# linked (the p256 SCA variants, the RSA keygen entry points).
OTBN_APP_DIR_otbn_smoke            := otbn_smoke_test
OTBN_APP_SRCS_otbn_smoke           := otbn_smoke.s
OTBN_APP_DIR_otbn_loops            := otbn_loops_test
OTBN_APP_SRCS_otbn_loops           := otbn_loops.s
OTBN_APP_DIR_otbn_sep_integration  := otbn_sep_integration_test
OTBN_APP_SRCS_otbn_sep_integration := otbn_sep_integration.s
OTBN_APP_DIR_p256_ecdsa            := otbn_p256_verify_test
OTBN_APP_SRCS_p256_ecdsa           := p256_base.s p256_isoncurve.s p256_shared_key.s \
                                      p256_sign.s p256_verify.s run_p256.s
OTBN_APP_DIR_rsa_3072_app          := otbn_rsa_3072_verify_test
OTBN_APP_SRCS_rsa_3072_app         := gcd.s modexp.s montmul.s mul.s rsa_keygen.s \
                                      rsa_modinv_f4.s rsa_primality.s run_rsa_mem.s run_rsa.s
# The software-error test needs one app per error class, each a single source.
OTBN_ERROR_APPS := bad_data_addr bad_insn_addr call_stack illegal_insn loop_error
$(foreach a,$(OTBN_ERROR_APPS),$(eval OTBN_APP_DIR_$(a) := otbn_sw_error_test))
$(foreach a,$(OTBN_ERROR_APPS),$(eval OTBN_APP_SRCS_$(a) := $(a).s))

OTBN_APPS := otbn_smoke otbn_loops otbn_sep_integration p256_ecdsa rsa_3072_app \
             $(OTBN_ERROR_APPS)

# Which apps each test links. otbn_fw_control_test drives the same smoke image
# as otbn_smoke_test; otbn_plic_test uses none.
OTBN_TEST_APPS_otbn_smoke_test           := otbn_smoke
OTBN_TEST_APPS_otbn_fw_control_test      := otbn_smoke
OTBN_TEST_APPS_otbn_loops_test           := otbn_loops
OTBN_TEST_APPS_otbn_sep_integration_test := otbn_sep_integration
OTBN_TEST_APPS_otbn_p256_verify_test     := p256_ecdsa
OTBN_TEST_APPS_otbn_rsa_3072_verify_test := rsa_3072_app
OTBN_TEST_APPS_otbn_sw_error_test        := $(OTBN_ERROR_APPS)

OTBN_TESTS := otbn_smoke_test otbn_fw_control_test otbn_loops_test \
              otbn_sep_integration_test otbn_p256_verify_test \
              otbn_rsa_3072_verify_test otbn_sw_error_test

ocah_otbn_app_c   = $(OTBN_BUILD_ROOT)/$(1)/$(1)_otbn.c
ocah_otbn_app_h   = $(OTBN_BUILD_ROOT)/$(1)/$(1)_otbn.h
ocah_otbn_app_src = $(addprefix $(FW_DIR)/tests/$(OTBN_APP_DIR_$(1))/otbn_src/,$(OTBN_APP_SRCS_$(1)))

# Must be set before compile.mk, which folds the extras into each test's sources.
$(foreach t,$(OTBN_TESTS), \
  $(eval FW_TEST_EXTRA_SRCS_$(t) := $(foreach a,$(OTBN_TEST_APPS_$(t)),$(call ocah_otbn_app_c,$(a)))))
FW_TEST_INCLUDES += $(foreach a,$(OTBN_APPS),-I$(OTBN_BUILD_ROOT)/$(a))
# Test sources call unprototyped functions and mix register pointer types;
# these relaxations let them compile.
FW_TEST_EXTRA_CFLAGS += \
  -Wno-implicit-function-declaration \
  -Wno-incompatible-pointer-types \
  -Wno-strict-prototypes
# Tests built with the Zb* bit-manip extensions. Everything else takes the
# Zb*-free FW_ARCH default, because GCC emits sh2add/rev8 from plain C and those
# trap as illegal instructions on this EL2 config.
FW_TEST_BITMANIP := \
  ap_stee_output_remap_test bl1_pass_test hello_world \
  nmi_sanity_test \
  otbn_fw_control_test otbn_loops_test otbn_p256_verify_test otbn_plic_test \
  otbn_rsa_3072_verify_test otbn_sep_integration_test otbn_smoke_test \
  otbn_sw_error_test rom_no_tcm_preload_mem_init sep_aes_back_to_back_test \
  sep_inbound_filter_decerr sep_smc_notify \
  sram_perf_test uart \
  wdt_bark_bite_order_test wdt_bite_before_bark_test wdt_cdc_sync_test \
  wdt_cfg_lock_test wdt_count_overflow_test wdt_intr_clear_test wdt_intr_test \
  wdt_lc_escalate_test wdt_pause_sleep_test wdt_pet_reset_test \
  wdt_poll_consistency_test wdt_sanity_test wdt_stress_all_test \
  wdt_threshold_jump_test wdt_wkup_timer_test
# Deferred: toolchain.mk, which defines FW_ARCH_BITMANIP, is included later.
$(foreach t,$(FW_TEST_BITMANIP), \
  $(eval FW_TEST_IMAGE_CFLAGS_$(t) += -march=$$(FW_ARCH_BITMANIP)))

# Default link mode: link/modes/tcm.ld, auto-discovered by compile.mk.
FW_DEFAULT_TEST_MODE := tcm
FW_TEST_LDFLAGS = $(FW_LDFLAGS)

# rom_no_tcm_preload_mem_init is the one image that runs from Boot ROM with no
# TCM preload at all: pure assembly, linked freestanding against its own ROM
# linker script, and consumed by the testbench as a VMEM rather than a TCM hex.
# It has no .c, so discovery does not see it.
FW_TEST_EXTRA_NAMES := rom_no_tcm_preload_mem_init
FW_TEST_SRCS_rom_no_tcm_preload_mem_init := \
  $(FW_DIR)/tests/rom_no_tcm_preload_mem_init/rom_no_tcm_preload_mem_init.S
# No sha256 helper, and no libsep.a: -nostdlib means anything the linker pulled
# in would want a libc that is not there.
FW_TEST_COMMON_SRCS_rom_no_tcm_preload_mem_init :=
FW_TEST_MODE_rom_no_tcm_preload_mem_init := rom_only
# Relaxation would turn absolute accesses into gp-relative ones, and this image
# runs before any gp is established.
FW_TEST_IMAGE_CFLAGS_rom_no_tcm_preload_mem_init += -mno-relax

FW_EXTRA_LINK_MODES := rom_only
FW_LINK_SCRIPT_rom_only := $(FW_DIR)/tests/rom_no_tcm_preload_mem_init/rom_only.ld
FW_TEST_LDFLAGS_rom_only := -march=rv32im_zicsr_zifencei -mabi=ilp32 \
                            -nostdlib -Wl,--gc-sections -Wl,--no-relax
FW_TEST_ARCHIVE_LINK_rom_only :=

# Boot ROM base; the VMEM is emitted as one 64-bit word per line from here.
SEP_ROM_BASE := 0x10040000

define FW_TEST_POSTPROCESS
$(if $(filter rom_only,$(3)),
	$(PYTHON) "$(SEP_BOOTROM_DIR)/tools/elf-to-vmem.py" \
	  --base $(SEP_ROM_BASE) --gcc-prefix $(patsubst %-,%,$(OCAH_FW_TOOL_PREFIX)) \
	  -o "$(4).vmem" "$(1)"
,
	$(OBJCOPY) -O verilog $(1) --only-section=.text --only-section=.nmi_handler \
	  --change-addresses "-0xC0000000" "$(4).itcm.hex"
	$(OBJCOPY) -O verilog $(1) \
	  --only-section=.data --only-section=.sdata --only-section=.rodata --only-section=.srodata \
	  --only-section=.tdata --only-section=.bss --only-section=.sbss \
	  --change-addresses "-0xC0040000" "$(4).dtcm.hex"
	$(if $(filter sep_smu_debug_bus,$(2)),$(PYTHON) \
	  "$(OCAH_ROOT)/tools/dv/generate_fw_symbol_pins.py" \
	  --sym "$(4).tcm.sym" --output "$(dir $(4))sep_debug_bus_symbols.h")
)
endef

# `all` builds libsep.a; the test images are built through compile.mk.

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk

# OTBN app rules, after compile.mk so FW_TEST_BUILD_DIR and the toolchain
# prefix are resolved. Grouped targets (&:) because one sub-make run produces
# both the .c and the .h.
define ocah_otbn_app_rule
$(call ocah_otbn_app_c,$(1)) $(call ocah_otbn_app_h,$(1)) &: \
    $(call ocah_otbn_app_src,$(1)) $(OTBN_APP_MK) $(FW_BUILD_ID_H) \
    $(FW_DIR)/tests/common_otbn/generate_otbn_c.py \
    $(FW_DIR)/tests/common_otbn/otbn_app.ld
	+$$(MAKE) -f $(OTBN_APP_MK) \
	  OCAH_ROOT="$(OCAH_ROOT)" \
	  OTBN_APP_NAME=$(1) \
	  OTBN_SRC_DIR="$(FW_DIR)/tests/$(OTBN_APP_DIR_$(1))/otbn_src" \
	  OTBN_APP_SRCS="$(call ocah_otbn_app_src,$(1))" \
	  OTBN_BUILD_DIR="$(OTBN_BUILD_ROOT)/$(1)" \
	  RV32_PREFIX="$$(OCAH_FW_TOOL_PREFIX)" \
	  otbn-app
endef
$(foreach a,$(OTBN_APPS),$(eval $(call ocah_otbn_app_rule,$(a))))

# Every object depends on the identity header, which changes exactly when the
# source digest does. A source change therefore rebuilds all of them -- also an
# edit whose timestamp make cannot see -- so the digest in an image never sits
# beside an object compiled from other source.
$(FW_LIB_OBJS) $(FW_ENTRY_OBJS) \
$(foreach t,$(FW_TEST_NAMES),$(foreach i,$(call ocah_fw_test_images,$(t)),$(FW_TEST_OBJS_$(i)))): \
    $(FW_BUILD_ID_H)

# The test's own translation unit includes the generated header, and on a clean
# build there is no depfile yet to say so; without this a parallel build can
# compile the test before the app exists.
define ocah_otbn_test_header_dep
$(FW_TEST_BUILD_DIR)/$(1)/$(1).o: \
    $(foreach a,$(OTBN_TEST_APPS_$(1)),$(call ocah_otbn_app_h,$(a)))
endef
$(foreach t,$(OTBN_TESTS),$(eval $(call ocah_otbn_test_header_dep,$(t))))

# The boot ROM links the RSA-3072 app too (secure-boot signature verification),
# and it builds from its own Makefile rather than through this engine, so give
# it a target to ask for the apps by name.
.PHONY: dv-fw-otbn-apps
dv-fw-otbn-apps: $(foreach a,$(OTBN_APPS),$(call ocah_otbn_app_c,$(a)))

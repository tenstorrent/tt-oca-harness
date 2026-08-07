# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMC DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw-libs TARGET=smc
FW_NAME := smc
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# SMC runtime driver library. DV tests supply main() and link against it. Layout
# follows the SiFive Metal include convention rooted at include/metal.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)
FW_INCLUDES := \
  -I$(FW_DIR)/include \
  -I$(FW_DIR)/include/metal \
  -I$(FW_DIR)/include/metal/drivers \
  -I$(FW_DIR)/include/metal/smc

# OCCP master BFM library sources.  Compiled into libsmc.a so that
# occp_sanity and occp_master (rom-mode) tests link without a real I3C
# driver.  Sram tests link against the archive too but never call these
# functions; --gc-sections removes them from sram ELFs at link time.
FW_C_SRCS += \
  $(FW_DIR)/common/occp/occp_commands.c \
  $(FW_DIR)/common/occp/occp_interfaces.c \
  $(FW_DIR)/common/occp/status_decode.c \
  $(FW_DIR)/common/occp/sep_ring_buffer_model.c \
  $(FW_DIR)/common/occp/i2c_controller_driver.c \
  $(FW_DIR)/common/occp/i3c_controller_driver_stub.c

# exit_stub.c provides _exit() for rom-mode tests (crt0 → exit() → _exit();
# ROM tests never return so it just spins in WFI).
FW_C_SRCS += $(FW_DIR)/startup/exit_stub.c

FW_INCLUDES += \
  -I$(FW_DIR)/common/occp \
  -I$(OCAH_ROOT)/hw/sys/smc/bootrom/prod/include

# Register headers via the shared engine helper (umbrella smc.h under
# hw/common/dv/fw + this sys's generated headers).
FW_REG_SYS := smc

# Test discovery is unified in compile.mk; declare only the SMC deltas. coremark
# pulls in the shared core_portme.c harness alongside its own source.
FW_TEST_EXTRA_SRCS_coremark := $(FW_DIR)/tests/core_portme.c
# The boot ROM's registers dir is test-only: a few OCCP master-BFM tests include
# smc_top_regs.h directly. It stays out of FW_INCLUDES because the nonfree dv_rom
# build force-includes vendor I3C shims whose types collide with it.
FW_TEST_INCLUDES := \
  -I$(FW_DIR)/tests \
  -I$(OCAH_ROOT)/hw/sys/smc/bootrom/prod/registers
# Test sources predate strict prototypes / native register headers; keep these
# relaxations so they compile unchanged.
FW_TEST_EXTRA_CFLAGS += \
  -Wno-incompatible-pointer-types \
  -Wno-implicit-function-declaration \
  -Wno-implicit-int \
  -Wno-int-conversion \
  -Wno-strict-prototypes
# Tests default to sram; opt into another mode with FW_TEST_MODE_<name> := rom.
FW_DEFAULT_TEST_MODE := sram
# Both sram and rom use FW_LDFLAGS and --whole-archive (compile.mk defaults).
# sram.ld declares ENTRY(_enter); the linker script is the only difference
# between modes.  --whole-archive ensures entry.S/crt0.S are always pulled
# from the archive so _enter and _start resolve before picolibc's exit().

# OCCP tests run as rom-mode images (crt0 + _enter, text at ROM address).
# These are the master-BFM images the BL0 regression loads via +MASTER_BFM_ROM;
# the BFM half drives the OCCP protocol against the DUT running the prod ROM.
FW_TEST_MODE_occp_sanity := rom
FW_TEST_MODE_occp_master := rom
FW_TEST_MODE_i3c_raw_master := rom
FW_TEST_MODE_occp_boot_sequence_status_test := rom
FW_TEST_MODE_occp_comprehensive_error_verification_test := rom
FW_TEST_MODE_occp_crc_err_injection_test := rom
FW_TEST_MODE_occp_interface_latch_test := rom
FW_TEST_MODE_occp_interface_unlatch_test := rom
FW_TEST_MODE_occp_invalid_cmd_test := rom
FW_TEST_MODE_occp_invalid_length_field_test := rom
FW_TEST_MODE_occp_jump := rom
FW_TEST_MODE_occp_jump_invalid_region_test := rom
FW_TEST_MODE_occp_jump_reject := rom
FW_TEST_MODE_occp_max_size_transfer_test := rom
FW_TEST_MODE_occp_mem_boundary_access_test := rom
FW_TEST_MODE_occp_min_size_transfer_test := rom
FW_TEST_MODE_occp_oversize_body_test := rom
FW_TEST_MODE_occp_random_test := rom
FW_TEST_MODE_occp_register_access_test := rom
FW_TEST_MODE_occp_ring_buffer_advanced_test := rom
FW_TEST_MODE_occp_ring_buffer_overflow_test := rom
FW_TEST_MODE_occp_ring_buffer_stress_test := rom
FW_TEST_MODE_occp_ring_buffer_test := rom
FW_TEST_MODE_occp_secure_access_test := rom
FW_TEST_MODE_occp_secure_boot_test := rom
FW_TEST_MODE_occp_unaligned_access_test := rom
FW_TEST_MODE_occp_undersize_body_test := rom
FW_TEST_MODE_occp_undersize_header_test := rom
FW_TEST_MODE_occp_unsecure_boot_test := rom
FW_TEST_MODE_occp_unsupported_status_id_test := rom
FW_TEST_MODE_occp_validate_boot_invalid_region_test := rom
FW_TEST_MODE_occp_validate_boot_reject_test := rom
FW_TEST_MODE_occp_validate_boot_test := rom
FW_TEST_MODE_occp_zero_length_rw_test := rom
FW_TEST_MODE_occp_zero_length_test := rom

# Make the simulator-consumed ECC image the primary postprocess target. The
# shared engine then rebuilds sidecars when the ELF or either converter changes
# without forcing the C objects and archive to rebuild.
FW_TEST_POSTPROCESS_PRIMARY_SUFFIX := .ecc.hex
FW_TEST_POSTPROCESS_DEPS := \
  $(FW_DIR)/fw.mk \
  $(FW_DIR)/postprocess.mk \
  $(FW_DIR)/scripts/bin_to_verilog.py \
  $(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py

# Shared with hw/sys/smc/bootrom/dummy/Makefile.
include $(FW_DIR)/postprocess.mk

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk

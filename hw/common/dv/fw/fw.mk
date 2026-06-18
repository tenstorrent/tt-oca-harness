# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_fw_mk
ocah_fw_mk := 1

# DV firmware dispatcher.
#
# Each subsystem owns a self-contained firmware build at
# hw/{ip,sys}/<name>/dv/fw/fw.mk plus its own toolchain.mk. The three target
# CPUs differ in ISA / ABI / libc, so a subsystem build is dispatched as an
# INDEPENDENT recursive sub-make: per-subsystem toolchain flags never share
# global state, and separate subsystems can build in any order (or in parallel
# across invocations) without colliding. Shared toolchain resolution and build
# rules live in hw/common/dv/fw/common.mk.
#
# Discovery mirrors the register flow: any block exposing a dv/fw/fw.mk is
# picked up automatically, so new subsystems need no edits here.
OCAH_DV_FW_MKS := $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/fw/fw.mk $(OCAH_ROOT)/hw/sys/*/dv/fw/fw.mk)
ocah_dv_fw_name = $(notdir $(patsubst %/dv/fw/fw.mk,%,$(1)))
OCAH_DV_FW_SUBSYSTEMS := $(sort $(foreach m,$(OCAH_DV_FW_MKS),$(call ocah_dv_fw_name,$(m))))
ocah_dv_fw_dir_for = $(patsubst %/fw.mk,%,$(filter %/$(1)/dv/fw/fw.mk,$(OCAH_DV_FW_MKS)))

## @section DV Firmware

## Build DV firmware for one or all subsystems.
## Each subsystem builds via an independent recursive sub-make using its own
## toolchain.mk (distinct ISA/ABI/libc), so builds do not share flag state.
## @param TARGET=km Optional subsystem to build (km, sep, smc); omit to build all
.PHONY: ocah-dv-fw
ocah-dv-fw: $(if $(strip $(TARGET)),ocah-dv-fw-$(strip $(TARGET)),$(addprefix ocah-dv-fw-,$(OCAH_DV_FW_SUBSYSTEMS)))

## Build DV firmware for a single subsystem by name.
.PHONY: ocah-dv-fw-%
ocah-dv-fw-%:
	@dir="$(call ocah_dv_fw_dir_for,$*)"; \
	if [ -z "$$dir" ]; then \
		echo "error: unknown DV firmware subsystem '$*'"; \
		echo "known subsystems: $(OCAH_DV_FW_SUBSYSTEMS)"; \
		exit 1; \
	fi; \
	echo "==> Building DV firmware: $* ($$dir)"; \
	$(MAKE) -C "$$dir" -f fw.mk OCAH_ROOT="$(OCAH_ROOT)" all

## Remove built DV firmware for one or all subsystems.
## @param TARGET=km Optional subsystem to clean; omit to clean all
.PHONY: ocah-dv-fw-clean
ocah-dv-fw-clean:
	@$(foreach s,$(if $(strip $(TARGET)),$(strip $(TARGET)),$(OCAH_DV_FW_SUBSYSTEMS)), \
		$(MAKE) -C "$(call ocah_dv_fw_dir_for,$(s))" -f fw.mk OCAH_ROOT="$(OCAH_ROOT)" clean &&) true

## List the DV firmware subsystems discovered under hw/{ip,sys}/*/dv/fw.
.PHONY: ocah-dv-fw-list
ocah-dv-fw-list:
	@echo "DV firmware subsystems: $(OCAH_DV_FW_SUBSYSTEMS)"

OCAH_PHONY += \
  ocah-dv-fw \
  ocah-dv-fw-% \
  ocah-dv-fw-clean \
  ocah-dv-fw-list

endif

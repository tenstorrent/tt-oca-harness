# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_fw_mk
ocah_fw_mk := 1

# DV firmware dispatcher: discover each subsystem's dv/fw/fw.mk and run it as its
# own recursive sub-make (distinct ISA/ABI/libc toolchains; engine is compile.mk).
OCAH_DV_FW_MKS := $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/fw/fw.mk $(OCAH_ROOT)/hw/sys/*/dv/fw/fw.mk)
ocah_dv_fw_name = $(notdir $(patsubst %/dv/fw/fw.mk,%,$(1)))
OCAH_DV_FW_SUBSYSTEMS := $(sort $(foreach m,$(OCAH_DV_FW_MKS),$(call ocah_dv_fw_name,$(m))))
ocah_dv_fw_dir_for = $(patsubst %/fw.mk,%,$(filter %/$(1)/dv/fw/fw.mk,$(OCAH_DV_FW_MKS)))

# Subsystems a goal applies to: TARGET=<sub> for one, else all discovered.
ocah_dv_fw_selected = $(if $(strip $(TARGET)),$(strip $(TARGET)),$(OCAH_DV_FW_SUBSYSTEMS))

# Fan one engine goal out to each selected subsystem as an isolated sub-make.
# TEST selects a single FW test; an unknown TARGET errors at run time.
ocah_dv_fw_run = @$(foreach s,$(ocah_dv_fw_selected), \
	{ dir="$(call ocah_dv_fw_dir_for,$(s))"; \
	  [ -n "$$dir" ] || { echo "error: unknown DV firmware subsystem '$(s)' (known: $(OCAH_DV_FW_SUBSYSTEMS))" >&2; exit 1; }; \
	  echo "==> $(s): $(1)"; \
	  $(MAKE) -C "$$dir" -f fw.mk OCAH_ROOT="$(OCAH_ROOT)" $(1) TEST="$(TEST)"; } &&) true

## @section DV Firmware

## Build DV firmware for one or all subsystems.
## @param TARGET=km Optional subsystem to build (km, sep, smc); omit to build all
.PHONY: ocah-dv-fw
ocah-dv-fw:
	$(call ocah_dv_fw_run,all)

## Build DV firmware C tests for one or all subsystems.
## @param TARGET=km Optional subsystem to build (km, sep, smc); omit to build all
## @param TEST=<test> Optional FW C testcase name to build within the subsystem
.PHONY: ocah-dv-fw-tests
ocah-dv-fw-tests:
	$(call ocah_dv_fw_run,dv-fw-tests)

## Remove built DV firmware for one or all subsystems.
## @param TARGET=km Optional subsystem to clean; omit to clean all
.PHONY: ocah-dv-fw-clean
ocah-dv-fw-clean:
	$(call ocah_dv_fw_run,clean)

## List the DV firmware subsystems discovered under hw/{ip,sys}/*/dv/fw.
.PHONY: ocah-dv-fw-list
ocah-dv-fw-list:
	@echo "DV firmware subsystems: $(OCAH_DV_FW_SUBSYSTEMS)"

## List DV firmware C tests for one or all subsystems.
## @param TARGET=km Optional subsystem to list (km, sep, smc); omit to list all
.PHONY: ocah-dv-fw-test-list
ocah-dv-fw-test-list:
	$(call ocah_dv_fw_run,dv-fw-test-list)

OCAH_PHONY += \
  ocah-dv-fw \
  ocah-dv-fw-tests \
  ocah-dv-fw-clean \
  ocah-dv-fw-list \
  ocah-dv-fw-test-list

endif

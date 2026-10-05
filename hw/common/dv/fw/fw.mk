# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_fw_mk
ocah_fw_mk := 1

# DV firmware dispatcher. Shared fan-out lives in dispatch.mk; only
# the literal target list below is tree-specific (kept literal for `make help`).
include $(OCAH_ROOT)/hw/common/dv/fw/dispatch.mk

OCAH_DV_FW_MKS := $(call ocah_dv_fw_mks_in,$(OCAH_ROOT))
OCAH_DV_FW_SUBSYSTEMS := $(call ocah_dv_fw_subsystems,$(OCAH_DV_FW_MKS))

# Bind the fan-out: empty label, OCAH_ROOT forwarded.
ocah_dv_fw = $(call ocah_dv_fw_run,$(1),,$(OCAH_DV_FW_MKS),$(OCAH_DV_FW_SUBSYSTEMS),OCAH_ROOT="$(OCAH_ROOT)")

## @section DV Firmware

## Build DV firmware libraries for one or all subsystems.
## @param TARGET=smc Optional subsystem to build (sep, smc); omit to build all
.PHONY: ocah-dv-fw-libs
ocah-dv-fw-libs:
	$(call ocah_dv_fw,all)

## Build DV firmware C tests for one or all subsystems.
## @param TARGET=smc Optional subsystem to build (sep, smc); omit to build all
## @param TEST=<test> Optional FW C testcase name to build within the subsystem
.PHONY: ocah-dv-fw-tests
ocah-dv-fw-tests:
	$(call ocah_dv_fw,dv-fw-tests)

## Remove built DV firmware for one or all subsystems.
## @param TARGET=smc Optional subsystem to clean; omit to clean all
.PHONY: ocah-dv-fw-clean
ocah-dv-fw-clean:
	$(call ocah_dv_fw,clean)

## List the DV firmware subsystems discovered under hw/{ip,sys}/*/dv/fw.
.PHONY: ocah-dv-fw-list
ocah-dv-fw-list:
	@echo "DV firmware subsystems: $(OCAH_DV_FW_SUBSYSTEMS)"

## List DV firmware C tests for one or all subsystems.
## @param TARGET=smc Optional subsystem to list (sep, smc); omit to list all
.PHONY: ocah-dv-fw-test-list
ocah-dv-fw-test-list:
	$(call ocah_dv_fw,dv-fw-test-list)

OCAH_PHONY += \
  ocah-dv-fw-libs \
  ocah-dv-fw-tests \
  ocah-dv-fw-clean \
  ocah-dv-fw-list \
  ocah-dv-fw-test-list

endif

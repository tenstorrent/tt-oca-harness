# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_dv_fw_dispatch_mk
ocah_dv_fw_dispatch_mk := 1

# Shared DV firmware dispatch helpers. A tree's fw.mk includes
# this, computes its mks/subsystem lists from its own root, and keeps literal
# ##/.PHONY targets (for `make help`) whose recipes call ocah_dv_fw_run. The
# prefix label and search root are parameters, so no tree-specific literals here.

# Discover subsystem dv/fw/fw.mk under a tree root. $(1) = tree root
ocah_dv_fw_mks_in = $(wildcard $(1)/hw/ip/*/dv/fw/fw.mk $(1)/hw/ip/*/*/dv/fw/fw.mk $(1)/hw/sys/*/dv/fw/fw.mk)

# Subsystem name from a fw.mk path.
ocah_dv_fw_name = $(notdir $(patsubst %/dv/fw/fw.mk,%,$(1)))

# Sorted unique subsystem names from a mks list.
ocah_dv_fw_subsystems = $(sort $(foreach m,$(1),$(call ocah_dv_fw_name,$(m))))

# Subsystem dv/fw dir from a mks list. $(1) = mks list   $(2) = subsystem name
ocah_dv_fw_dir_for = $(patsubst %/fw.mk,%,$(filter %/$(2)/dv/fw/fw.mk,$(1)))

# Fan an engine goal out to each selected subsystem as an isolated sub-make
# (distinct toolchains; the per-subsystem engine is compile.mk). TARGET picks one
# (else all), TEST picks one test, unknown TARGET errors at run time.
#   $(1) = goal   $(2) = label prefix   $(3) = mks   $(4) = all names
#   $(5) = extra make-var assignments forwarded to each sub-make
ocah_dv_fw_run = @$(foreach s,$(if $(strip $(TARGET)),$(strip $(TARGET)),$(4)), \
	{ dir="$(call ocah_dv_fw_dir_for,$(3),$(s))"; \
	  [ -n "$$dir" ] || { echo "error: unknown $(2)DV firmware subsystem '$(s)' (known: $(4))" >&2; exit 1; }; \
	  echo "==> $(2)$(s): $(1)"; \
	  $(MAKE) -C "$$dir" -f fw.mk $(5) $(1) TEST="$(TEST)"; } &&) true

endif

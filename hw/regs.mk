ifndef ocah_regs_mk
ocah_regs_mk := 1

OCAH_HJSON_REG_BLOCKS ?= \
  vendor/lowRISC/opentitan/upstream/hw/ip/otbn

OCAH_REG_BLOCKS ?= \
  hw/ip/system_timer_octs \
  hw/ip/gpio \
  hw/ip/km \
  $(OCAH_HJSON_REG_BLOCKS)

OCAH_REGBLOCK_UDP ?= $(OCAH_ROOT)/hw/common/regs/regblock_udps.rdl
OCAH_REG_CPU_IF ?= axi4-lite-flat
OCAH_REG_DEFAULT_RESET ?= arst_n
OCAH_PANDOC ?= pandoc
OCAH_REGGEN_WRAPPER ?= $(OCAH_ROOT)/tools/regs/reggen_wrapper.py

ocah_reg_block_by_name = $(strip $(foreach block,$(OCAH_REG_BLOCKS),$(if $(filter $(1),$(notdir $(block))),$(block))))
OCAH_SELECTED_REG_BLOCKS := $(if $(TARGET),$(call ocah_reg_block_by_name,$(TARGET)),$(OCAH_REG_BLOCKS))

ifeq ($(strip $(OCAH_SELECTED_REG_BLOCKS)),)
  $(error Unknown OCAH register block '$(TARGET)'; known blocks: $(foreach block,$(OCAH_REG_BLOCKS),$(notdir $(block))))
endif

ocah_reg_name = $(notdir $(1))
ocah_reg_root = $(OCAH_ROOT)/$(1)
ocah_reg_rdl = $(call ocah_reg_root,$(1))/regs/$(call ocah_reg_name,$(1)).rdl
ocah_reg_hjson = $(call ocah_reg_root,$(1))/data/$(call ocah_reg_name,$(1)).hjson
ocah_reg_gen = $(call ocah_reg_root,$(1))/regs/gen
ocah_reg_build = $(call ocah_reg_root,$(1))/build/regs

ocah_reg_sv_stamp = $(call ocah_reg_build,$(1))/sv.generated
ocah_reg_sv_outputs = \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_reg.sv \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_reg_pkg.sv
ocah_reg_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1)).h
ocah_reg_c_addr_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1))_addr.h
ocah_reg_svpkg_output = $(call ocah_reg_gen,$(1))/svh/$(call ocah_reg_name,$(1))_reg.svh
ocah_reg_raw_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1))_addr.h
ocah_reg_py_output = $(call ocah_reg_gen,$(1))/py/$(call ocah_reg_name,$(1))_addr.py
ocah_reg_md_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).md
ocah_reg_adoc_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).adoc
ocah_reg_html_output = $(call ocah_reg_gen,$(1))/html/index.html

OCAH_REGEN_REG_SV := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_sv_outputs,$(block)))
OCAH_REGEN_REG_H := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_c_output,$(block)) $(call ocah_reg_raw_c_output,$(block)))
OCAH_REGEN_REG_SVH := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_svpkg_output,$(block)))
OCAH_REGEN_REG_PY := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_py_output,$(block)))
OCAH_REGEN_REG_ADOC := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_adoc_output,$(block)))
OCAH_REGEN_REG_HTML := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_html_output,$(block)))
OCAH_REGEN_REG_STAMPS := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_build,$(block))/.generated)
OCAH_REGEN_ALL := \
  $(OCAH_REGEN_REG_SV) \
  $(OCAH_REGEN_REG_H) \
  $(OCAH_REGEN_REG_SVH) \
  $(OCAH_REGEN_REG_PY) \
  $(OCAH_REGEN_REG_ADOC) \
  $(OCAH_REGEN_REG_HTML)

define ocah_hjson_reg_block_rules
$(call ocah_reg_rdl,$(1)): $(call ocah_reg_hjson,$(1)) $(OCAH_REGGEN_WRAPPER) | uv-sync
	@mkdir -p "$(call ocah_reg_root,$(1))/regs" "$(call ocah_reg_build,$(1))"
	@echo "Exporting OpenTitan HJSON register description to RDL for $(1)"
	@cd "$(OCAH_ROOT)" && "$(UV)" run python tools/regs/reggen_wrapper.py \
		--systemrdl \
		-o "$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(1)/data/$(call ocah_reg_name,$(1)).hjson"
endef

define ocah_reg_block_rules
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/sv" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1)"
	@cd "$(OCAH_ROOT)" && bash -o pipefail -c '"$(UV)" run peakrdl regblock "$$$$1" "$$$$2" -o "$$$$3" --cpuif "$$$$4" --default-reset "$$$$5" --module-name "$$$$6" --package-name "$$$$7" 2>&1 | tee "$$$$8"' _ \
		"$(OCAH_REGBLOCK_UDP)" \
		"$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(1)/regs/gen/sv" \
		"$(OCAH_REG_CPU_IF)" \
		"$(OCAH_REG_DEFAULT_RESET)" \
		"$(call ocah_reg_name,$(1))_reg" \
		"$(call ocah_reg_name,$(1))_reg_pkg" \
		"$(1)/build/regs/peakrdl_sv.log"
	@touch "$$@"

$(call ocah_reg_sv_outputs,$(1)): $(call ocah_reg_sv_stamp,$(1))
	@test -f "$$@" || { echo "error: expected generated file missing: $$@"; exit 1; }

$(call ocah_reg_c_output,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1)"
	@cd "$(OCAH_ROOT)" && bash -o pipefail -c '"$(UV)" run peakrdl c-header "$$$$1" -o "$$$$2" --bitfields ltoh --type-style lexical 2>&1 | tee "$$$$3"' _ \
		"$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(1)/regs/gen/c/$(call ocah_reg_name,$(1)).h" \
		"$(1)/build/regs/c_header.log"

$(call ocah_reg_raw_c_output,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating raw C address header for $(1)"
	@cd "$(OCAH_ROOT)" && bash -o pipefail -c '"$(UV)" run peakrdl raw-header "$$$$1" --format c --base-name "$$$$2" -o "$$$$3" 2>&1 | tee "$$$$4"' _ \
		"$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(shell echo $(call ocah_reg_name,$(1))_addr | tr a-z A-Z)" \
		"$(1)/regs/gen/c/$(call ocah_reg_name,$(1))_addr.h" \
		"$(1)/build/regs/raw_c_header.log"

$(call ocah_reg_svpkg_output,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/svh" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating SystemVerilog address package include for $(1)"
	@cd "$(OCAH_ROOT)" && bash -o pipefail -c '"$(UV)" run peakrdl raw-header "$$$$1" --format svpkg -o "$$$$2" 2>&1 | tee "$$$$3"' _ \
		"$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(1)/regs/gen/svh/$(call ocah_reg_name,$(1))_reg.svh" \
		"$(1)/build/regs/raw_svpkg.log"

$(call ocah_reg_py_output,$(1)): $(call ocah_reg_raw_c_output,$(1)) $(OCAH_ROOT)/tools/regs/pyhdr.py
	@mkdir -p "$(call ocah_reg_gen,$(1))/py" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Python address constants for $(1)"
	@cd "$(OCAH_ROOT)" && "$(UV)" run python tools/regs/pyhdr.py \
		"$(1)/regs/gen/c/$(call ocah_reg_name,$(1))_addr.h" \
		"$(1)/regs/gen/py/$(call ocah_reg_name,$(1))_addr.py"

$(call ocah_reg_md_output,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/adoc" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Markdown register docs for $(1)"
	@cd "$(OCAH_ROOT)" && bash -o pipefail -c '"$(UV)" run peakrdl markdown "$$$$1" -o "$$$$2" 2>&1 | tee "$$$$3"' _ \
		"$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(1)/regs/gen/adoc/$(call ocah_reg_name,$(1)).md" \
		"$(1)/build/regs/markdown.log"

$(call ocah_reg_adoc_output,$(1)): $(call ocah_reg_md_output,$(1))
	@command -v "$(OCAH_PANDOC)" >/dev/null 2>&1 || { \
		echo "error: pandoc is required to convert Markdown register docs to AsciiDoc"; \
		exit 1; \
	}
	@echo "Converting Markdown register docs to AsciiDoc for $(1)"
	@cd "$(OCAH_ROOT)" && "$(OCAH_PANDOC)" -f markdown -t asciidoc \
		"$(1)/regs/gen/adoc/$(call ocah_reg_name,$(1)).md" \
		-o "$(1)/regs/gen/adoc/$(call ocah_reg_name,$(1)).adoc"

$(call ocah_reg_html_output,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/html" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1)"
	@cd "$(OCAH_ROOT)" && bash -o pipefail -c '"$(UV)" run peakrdl html "$$$$1" -o "$$$$2" 2>&1 | tee "$$$$3"' _ \
		"$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(1)/regs/gen/html" \
		"$(1)/build/regs/html.log"

$(call ocah_reg_build,$(1))/.generated: $(call ocah_reg_sv_outputs,$(1)) $(call ocah_reg_c_output,$(1)) $(call ocah_reg_raw_c_output,$(1)) $(call ocah_reg_svpkg_output,$(1)) $(call ocah_reg_py_output,$(1)) $(call ocah_reg_adoc_output,$(1)) $(call ocah_reg_html_output,$(1))
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@touch "$$@"
endef

$(foreach block,$(OCAH_HJSON_REG_BLOCKS),$(eval $(call ocah_hjson_reg_block_rules,$(block))))
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_block_rules,$(block))))

## @section Register Regeneration

## Regenerate all register collateral for all OCAH register blocks.
## @param OCAH_REG_BLOCKS Registered block roots to regenerate
## @param OCAH_HJSON_REG_BLOCKS HJSON-backed block roots that are converted to RDL first
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs
ocah-regen-regs: $(OCAH_REGEN_ALL) $(OCAH_REGEN_REG_STAMPS)

## Regenerate SystemVerilog register RTL for OCAH register blocks.
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs-sv
ocah-regen-regs-sv: $(OCAH_REGEN_REG_SV)

## Regenerate firmware C headers and raw C address headers for OCAH register blocks.
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs-h
ocah-regen-regs-h: $(OCAH_REGEN_REG_H)

## Regenerate SystemVerilog address headers/packages for OCAH register blocks.
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs-svh
ocah-regen-regs-svh: $(OCAH_REGEN_REG_SVH)

## Regenerate flat Python address constants for OCAH register blocks.
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs-py
ocah-regen-regs-py: $(OCAH_REGEN_REG_PY)

## Regenerate AsciiDoc register documentation for OCAH register blocks.
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs-adoc
ocah-regen-regs-adoc: $(OCAH_REGEN_REG_ADOC)

## Regenerate HTML register documentation for OCAH register blocks.
## @param TARGET=gpio Optional register block basename to regenerate
.PHONY: ocah-regen-regs-html
ocah-regen-regs-html: $(OCAH_REGEN_REG_HTML)

## Remove generated register collateral and transient register-generation stamps.
## @param TARGET=gpio Optional register block basename to clean
.PHONY: ocah-regen-regs-clean
ocah-regen-regs-clean:
	@for block in $(OCAH_SELECTED_REG_BLOCKS); do \
		rm -rf "$(OCAH_ROOT)/$${block}/regs/gen"; \
		rm -rf "$(OCAH_ROOT)/$${block}/build/regs"; \
	done

## Regenerate all register collateral for one block by basename.
## @param BLOCK=gpio Block basename from OCAH_REG_BLOCKS
.PHONY: ocah-regen-regs-%
ocah-regen-regs-%:
	@block="$(call ocah_reg_block_by_name,$*)"; \
	if [ -z "$${block}" ]; then \
		echo "error: unknown OCAH register block '$*'"; \
		echo "known blocks: $(foreach block,$(OCAH_REG_BLOCKS),$(notdir $(block)))"; \
		exit 1; \
	fi; \
	$(MAKE) ocah-regen-regs TARGET="$*"

## Remove generated register collateral for one block by basename.
## @param BLOCK=gpio Block basename from OCAH_REG_BLOCKS
.PHONY: ocah-regen-regs-%-clean
ocah-regen-regs-%-clean:
	@block="$(call ocah_reg_block_by_name,$*)"; \
	if [ -z "$${block}" ]; then \
		echo "error: unknown OCAH register block '$*'"; \
		echo "known blocks: $(foreach block,$(OCAH_REG_BLOCKS),$(notdir $(block)))"; \
		exit 1; \
	fi; \
	rm -rf "$(OCAH_ROOT)/$${block}/regs/gen"; \
	rm -rf "$(OCAH_ROOT)/$${block}/build/regs"

OCAH_PHONY += \
  ocah-regen-regs \
  ocah-regen-regs-sv \
  ocah-regen-regs-h \
  ocah-regen-regs-svh \
  ocah-regen-regs-py \
  ocah-regen-regs-adoc \
  ocah-regen-regs-html \
  ocah-regen-regs-clean \
  ocah-regen-regs-% \
  ocah-regen-regs-%-clean

endif

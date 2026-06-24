# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_help_mk
ocah_help_mk := 1

.PHONY: help
help:
ifdef HELP_TITLE
	@echo $(HELP_TITLE)
endif
ifdef HELP_DESCRIPTION
	@echo $(HELP_DESCRIPTION)
endif
	@echo ""
	@MAKEFILES="$(MAKEFILE_LIST)" bash "$(OCAH_ROOT)/scripts/generate-makefile-help.sh"

.PHONY: list-all-targets
list-all-targets:
	@LC_ALL=C $(MAKE) -pRrq : 2>/dev/null | awk -v RS= -F: '/(^|\n)# Files(\n|$$)/,/(^|\n)# Finished Make data base/ {if ($$1 !~ "^[#.]") {print $$1}}' | sort | grep -v -e '^[^[:alnum:]]' -e '^$@$$'

endif

#include <stdio.h>
#include "test_completion.h"
#include "sep_outbound_filter.h"

int main(void)
{
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    printf("Hello World from OCH SEP!\n");
    // Require FW to explicitly signal PASS to the testbench/cocotb.
    test_pass(0);
    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}

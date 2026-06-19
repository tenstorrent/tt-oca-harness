
#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"


int main(void) {

  test_pass(0);

  while (true) {
    __asm__("wfi");
  }

  return 0;
}

int secondary_main(void) {

  return main();

}

/* Parser fixture, not a loadable kernel module or production driver. */
__attribute__((used, section(".modinfo")))
static const char metadata[] =
    "vermagic=6.18.38 SMP mod_unload aarch64\0name=module0\0depends=\0";
__attribute__((used, section(".gnu.linkonce.this_module")))
const unsigned char __this_module[8] = {0};
extern int fixture_external;
int fixture_symbol(void) { return fixture_external; }

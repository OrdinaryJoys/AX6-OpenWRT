/* Only the actual IRQ acquisition/free and NAPI registration bodies are executed.
 * Kernel APIs below model ownership; they do not model IRQ service or real RCU. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define __rcu
#define __iomem
#define IRQF_SHARED 1
#define pr_warn(...) ((void)0)
#define pr_debug(...) ((void)0)
#define pr_info(...) ((void)0)
#define netdev_dbg(...) ((void)0)
typedef uint64_t dma_addr_t;
typedef int irqreturn_t;
typedef int spinlock_t;
struct net_device { const char *name; bool dummy; };
struct napi_struct { struct net_device *owner; bool added; };
struct platform_device { int cookie; };
struct sk_buff;
struct device_node;
struct nss_dp_data_plane_ctx;
/* HEADERS */
struct edma_hw edma_hw;
static struct net_device dummy = {"dummy", true}, devices[EDMA_MAX_GMACS], foreign;
static struct platform_device platform;
static int lookup_fail, request_fail, lookups, requests, live[64], live_count;
static unsigned adds, dels, warnings, cases;
static bool rtnl_held;
static void check(bool ok, const char *why) {
    if (!ok) { fprintf(stderr, "EDMA_IRQ_CONTRACT %s\n", why); exit(86); }
}
#define ASSERT_RTNL() check(rtnl_held, "rtnl-held")
#define WARN_ON(x) ((x) ? (++warnings, true) : false)
#define rcu_access_pointer(p) (p)
static void publish(struct net_device **slot, struct net_device *dev) {
    check(edma_hw.napi.added && edma_hw.napi.owner == &dummy &&
          edma_hw.misc_irq_owned && live_count ==
          (int)(edma_hw.txcmpl_rings + edma_hw.rxfill_rings + edma_hw.rxdesc_rings + 1),
          "publish-after-registration");
    *slot = dev;
}
#define rcu_assign_pointer(p, v) publish(&(p), (v))
static int irq_callback(int irq, void *data) {
    (void)irq; (void)data; check(false, "irq-service-outside-model"); return 0;
}
static int misc_callback(int irq, void *data) {
    (void)irq; (void)data; check(false, "irq-service-outside-model"); return 0;
}
int edma_napi(struct napi_struct *napi, int budget) {
    (void)napi; (void)budget; check(false, "poll-outside-model"); return 0;
}
#define edma_handle_irq irq_callback
#define edma_handle_misc_irq misc_callback
static int platform_get_irq(struct platform_device *dev, unsigned index) {
    check(dev == &platform && index == (unsigned)lookups++, "irq-lookup-owner");
    return lookups == lookup_fail ? -ENXIO : 100 + (int)index;
}
static int request_irq(int irq, int (*callback)(int, void *), unsigned flags,
                       const char *name, void *owner) {
    int index = requests++;
    unsigned t = edma_hw.txcmpl_rings, f = edma_hw.rxfill_rings;
    unsigned d = edma_hw.rxdesc_rings;
    check(owner == &platform && flags == IRQF_SHARED && irq == 100 + index,
          "irq-request-owner");
    const char *expected = (unsigned)index < t ? "edma_txcmpl" :
        (unsigned)index < t + f ? "edma_rxfill" :
        (unsigned)index < t + f + d ? "edma_rxdesc" : "edma_misc";
    check(!strcmp(name, expected) && callback ==
          ((unsigned)index == t + f + d ? misc_callback : irq_callback),
          "irq-request-callback");
    for (int i = 0; i < live_count; ++i)
        check(live[i] != irq, "irq-not-already-owned");
    if (requests == request_fail) return -EBUSY;
    live[live_count++] = irq;
    return 0;
}
static void free_irq(int irq, void *owner) {
    check(owner == &platform && live_count > 0, "irq-free-owner");
    check(live[live_count - 1] == irq, "irq-free-order");
    --live_count;
}
static void netif_napi_add(struct net_device *dev, struct napi_struct *napi,
                           int (*poll)(struct napi_struct *, int)) {
    check(dev == &dummy && dev->dummy && napi == &edma_hw.napi && poll == edma_napi,
          "napi-dummy-owner");
    check(!napi->added, "napi-single-owner");
    napi->owner = dev; napi->added = true; ++adds;
}
static void netif_napi_del(struct napi_struct *napi) {
    check(napi == &edma_hw.napi && napi->added && napi->owner == &dummy,
          "napi-delete-owner");
    napi->added = false; napi->owner = NULL; ++dels;
}
/* FUNCTIONS */
static void empty_ownership(void) {
    check(!live_count && !edma_hw.tx_irqs_owned && !edma_hw.rxfill_irqs_owned &&
          !edma_hw.rxdesc_irqs_owned && !edma_hw.misc_irq_owned, "irq-live-ledger");
}
static void reset(unsigned rings) {
    check(!live_count && !edma_hw.napi.added, "previous-case-clean");
    memset(&edma_hw, 0, sizeof(edma_hw));
    edma_hw.pdev = &platform; edma_hw.napi_dev = &dummy;
    edma_hw.edma_initialized = true;
    edma_hw.txcmpl_rings = edma_hw.rxfill_rings = edma_hw.rxdesc_rings = rings;
    lookups = requests = lookup_fail = request_fail = 0;
    adds = dels = warnings = 0; rtnl_held = true;
}
static void retire(void) {
    edma_free_irqs(); empty_ownership();
    edma_free_irqs(); empty_ownership();
    if (edma_hw.napi.added) netif_napi_del(&edma_hw.napi);
    check(adds == dels, "napi-balanced");
}
static void no_publication(void) {
    for (unsigned i = 0; i < EDMA_MAX_GMACS; ++i)
        check(edma_hw.netdev_arr[i] == NULL, "registration-rollback");
    check(!edma_hw.napi_added && !edma_hw.napi.added && adds == dels,
          "registration-rollback");
}
static void passed(const char *name, unsigned rings, unsigned index) {
    ++cases; printf("PASS %s:%u:%u\n", name, rings, index);
}
static void refused_without_effects(struct net_device *dev, uint32_t port, int expected) {
    unsigned char before[sizeof(edma_hw)];
    memcpy(before, &edma_hw, sizeof(edma_hw));
    int old_requests = requests, old_lookups = lookups, old_live = live_count;
    unsigned old_adds = adds, old_dels = dels, old_warnings = warnings;
    check(edma_register_netdevice(dev, port) == expected, "refusal-result");
    check(!memcmp(before, &edma_hw, sizeof(edma_hw)) && requests == old_requests &&
          lookups == old_lookups && live_count == old_live && adds == old_adds &&
          dels == old_dels && warnings == old_warnings, "refusal-state");
}
int main(void) {
    for (unsigned rings = 1; rings <= 2; ++rings) {
        unsigned total = rings * 3 + 1;
        for (unsigned fault = 1; fault <= total; ++fault) {
            reset(rings); lookup_fail = (int)fault;
            check(edma_register_netdevice(&devices[0], 1) < 0, "lookup-failure-return");
            check(lookups == (int)fault && !requests, "lookup-no-acquisition");
            empty_ownership(); no_publication();
            lookup_fail = lookups = 0;
            check(!edma_register_netdevice(&devices[0], 1), "lookup-retry");
            retire(); passed("lookup-failure-retry", rings, fault);
            reset(rings); request_fail = (int)fault;
            check(edma_register_netdevice(&devices[0], 1) < 0, "request-failure-return");
            check(requests == (int)fault, "request-first-failure");
            empty_ownership(); no_publication();
            request_fail = lookups = requests = 0;
            check(!edma_register_netdevice(&devices[0], 1), "request-retry");
            retire(); passed("request-failure-retry", rings, fault);
        }
        reset(rings);
        for (unsigned port = 1; port <= EDMA_MAX_GMACS; ++port) {
            check(!edma_register_netdevice(&devices[port - 1], port), "register-port");
            int old_requests = requests;
            check(!edma_register_netdevice(&devices[port - 1], port) &&
                  requests == old_requests && adds == 1, "register-idempotent");
            refused_without_effects(&foreign, port, -EBUSY);
            passed("shared-single-napi", rings, port);
        }
        check(edma_irq_init() == -EINVAL && warnings == 1, "owned-reentry-refused");
        retire(); passed("owned-reentry-and-retire-twice", rings, 0);
    }
    unsigned invalid[] = {0, EDMA_MAX_GMACS + 1, UINT32_MAX};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        reset(1);
        refused_without_effects(&devices[0], invalid[i], -EINVAL);
        empty_ownership(); no_publication(); passed("invalid-port", 1, i);
    }
    reset(1); refused_without_effects(NULL, 1, -EINVAL);
    empty_ownership(); no_publication(); passed("null-device", 1, 0);
    reset(1); edma_hw.edma_initialized = false;
    refused_without_effects(&devices[0], 1, -ENODEV);
    empty_ownership(); no_publication(); passed("not-initialized", 1, 0);
    reset(1); edma_hw.napi_dev = NULL;
    refused_without_effects(&devices[0], 1, -ENODEV);
    empty_ownership(); no_publication(); passed("missing-dummy", 1, 0);
    reset(1); edma_hw.override_accounted[0] = true;
    refused_without_effects(&devices[0], 1, -EBUSY);
    empty_ownership(); no_publication(); passed("overridden-id", 1, 0);
    check(cases == 2 * (4 + 7) + 2 * EDMA_MAX_GMACS + 2 + 7,
          "case-inventory");
    return 0;
}

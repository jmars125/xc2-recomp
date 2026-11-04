// Run through tests/vk_pipeline_lock_test.py. The includes contain current runtime/vk_pipeline.c declarations and
// function bodies, not a second implementation. Fake compiles block on a gate; lookups use the real platform locks.
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>

#include "pipeline_types.inc"

struct GfxShader { int stage, id; atomic_int builds, failures; };
static struct { int loading; uint32_t left; } K;
static Layout test_layout = {.layout = (VkPipelineLayout)1, .set = (VkDescriptorSetLayout)2};
static int start_workers, noted;
static atomic_int fail_alloc, fail_job, waiters, wait_entries, upgrade_entered, upgrade_release;
static _Thread_local int pause_upgrade;
static pthread_mutex_t gate_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_cv = PTHREAD_COND_INITIALIZER;
static const GfxShader *gated;
static int entered, released;

static void *checked_calloc(size_t n, size_t size) {
    if (atomic_exchange(&fail_alloc, 0)) return NULL;
    if (size == sizeof(Job) && atomic_exchange(&fail_job, 0)) return NULL;
    return calloc(n, size);
}

static void checked_wait(PlatCond *c, PlatMutex *m) {
    atomic_fetch_add(&waiters, 1);
    atomic_fetch_add(&wait_entries, 1);
    plat_cond_wait(c, m);
    atomic_fetch_sub(&waiters, 1);
}

static void wait_for(atomic_int *value, int minimum) {
    uint64_t end = plat_now_ns() + 2000000000ull;
    while (atomic_load(value) < minimum && plat_now_ns() < end) {
        struct timespec t = {0, 1000000};
        nanosleep(&t, NULL);
    }
    assert(atomic_load(value) >= minimum);
}

static void checked_unlock_shared(PlatMutex *m) {
    plat_mutex_unlock_shared(m);
    if (pause_upgrade) {
        pause_upgrade = 0;
        atomic_store(&upgrade_entered, 1);
        wait_for(&upgrade_release, 1);
    }
}

static VkPipeline fake_create(const GfxShader *cs) {
    // No other test thread is started until the first build reaches its gate. Taking the lock here verifies that
    // runtime/vk_pipeline.c pipe_miss and compute_get released it and reserved exactly one building entry first.
    assert(plat_mutex_trylock(&P.lock));
    int owners = 0;
    for (int i = 0; i < PIPE_BUCKETS; i++)
        for (Pipe *p = pipes[i]; p; p = p->next) owners += p->building;
    assert(owners == 1 && P.sync_builds == 1);
    plat_mutex_unlock(&P.lock);
    GfxShader *s = (GfxShader *)cs;
    atomic_fetch_add(&s->builds, 1);
    pthread_mutex_lock(&gate_lock);
    if (cs == gated) {
        entered = 1;
        pthread_cond_broadcast(&gate_cv);
        while (!released) pthread_cond_wait(&gate_cv, &gate_lock);
    }
    pthread_mutex_unlock(&gate_lock);
    if (atomic_load(&s->failures)) {
        atomic_fetch_sub(&s->failures, 1);
        return VK_NULL_HANDLE;
    }
    return (VkPipeline)(uintptr_t)(100 + s->id);
}

static int ensure_init(void) { return 1; }
static int workers_start(void) { return start_workers; }
static uint32_t binding_span(const GfxShader *s) { return 1; }
static int add_stage(Bindings *b, const GfxShader *s, uint32_t off) { return 1; }
static Layout *layout_get(Bindings *b) { return &test_layout; }
static Layout *layout_pair(Bindings *b, Bindings *f) { return &test_layout; }
static int layout_covers(const VkPipeState *s, const Layout *l, uint32_t off, char *why, size_t n) { return 1; }
static void gkey_fill(const VkPipeState *s, GKey *k) { memset(k, 0, sizeof *k); k->vs = s->vs; }
static VkPipeline create_graphics(const VkPipeState *s, const GKey *k, const Layout *l, uint32_t off) { return fake_create(s->vs); }
static VkPipeline compute_create(const GfxShader *s, const Layout *l) { return fake_create(s); }
static void keys_note(const VkPipeState *s) { noted++; }
static void promote(Pipe *p) {}
static void job_lower(Job *j) {}
static void lib_wait(const VkPipeState *s, const GKey *k, Layout *l, double end) { assert(0); }
static VkPipeline gpl_link(const VkPipeState *s, const GKey *k, const Layout *l, int build, int *final) { assert(0); return 0; }
const char *cfg_get(const char *name) { return NULL; }
int gfx_shader_stage(const GfxShader *s) { return s->stage; }
uint32_t gfx_shader_inputs(const GfxShader *s, GfxShaderIo io[32]) { return 0; }
void rt_log(const char *fmt, ...) {}
uint64_t perf_begin(void) { return 0; }
void perf_end(int kind, uint64_t t0) {}
void perf_count(int kind) {}
VKAPI_ATTR void VKAPI_CALL vkDestroyPipeline(VkDevice d, VkPipeline p, const VkAllocationCallbacks *a) { assert(0); }

#define calloc checked_calloc
#define plat_cond_wait checked_wait
#define plat_mutex_unlock_shared checked_unlock_shared
#include "pipeline_functions.inc"
#undef calloc
#undef plat_cond_wait
#undef plat_mutex_unlock_shared

typedef struct Call {
    const GfxShader *shader;
    int prebuild, mode, upgrade;
    VkPipeline pipeline;
    const VkPipeInfo *info;
    int pending;
    atomic_int done;
} Call;

static void *lookup(void *arg) {
    Call *c = arg;
    pause_upgrade = c->upgrade;
    if (c->prebuild) lb_compute(c->shader);
    else if (c->shader->stage == GFX_STAGE_CS) c->pipeline = vk_pipeline_compute(c->shader, &c->info);
    else {
        VkPipeState s = {.vs = c->shader};
        c->pipeline = graphics(&s, &c->info, c->mode, &c->pending, 0);
    }
    atomic_store(&c->done, 1);
    return NULL;
}

static pthread_t launch(Call *c) {
    pthread_t t;
    assert(!pthread_create(&t, NULL, lookup, c));
    return t;
}

static void gate_on(const GfxShader *s) {
    pthread_mutex_lock(&gate_lock);
    gated = s, entered = released = 0;
    pthread_mutex_unlock(&gate_lock);
}

static void gate_entered(void) {
    pthread_mutex_lock(&gate_lock);
    while (!entered) pthread_cond_wait(&gate_cv, &gate_lock);
    pthread_mutex_unlock(&gate_lock);
}

static void gate_open(void) {
    pthread_mutex_lock(&gate_lock);
    released = 1;
    pthread_cond_broadcast(&gate_cv);
    pthread_mutex_unlock(&gate_lock);
}

static void reset(void) {
    assert(!P.sync_builds && !atomic_load(&waiters));
    for (int i = 0; i < PIPE_BUCKETS; i++) {
        while (pipes[i]) {
            Pipe *p = pipes[i];
            pipes[i] = p->next;
            free(p->bindings), free(p);
        }
    }
    memset(&P.stats, 0, sizeof P.stats);
    memset(&LB.built, 0, sizeof LB.built);
    memset(&LB.have, 0, sizeof LB.have);
    memset(&LB.fail, 0, sizeof LB.fail);
    LB.cs_draw = 0;
    start_workers = noted = 0;
    gated = NULL;
}

// A cache hit, statistics snapshot and worker-style publication all finish while an unrelated compile is held.
static void unrelated_work(Call *hot) {
    Call hit = {.shader = hot->shader};
    pthread_t t = launch(&hit);
    wait_for(&hit.done, 1);
    pthread_join(t, NULL);
    assert(hit.pipeline == hot->pipeline && hit.info == hot->info);
    VkPipeStats stats;
    vk_pipeline_stats(&stats);
    assert(stats.hits > 0);
    int waits = atomic_load(&wait_entries);
    plat_mutex_lock(&P.lock);
    GKey k;
    VkPipeState s = {.vs = hot->shader};
    gkey_fill(&s, &k);
    Pipe *p = pipe_find(&k, sizeof k, key_hash(&k, sizeof k));
    pipe_publish(p, (VkPipeline)999);
    plat_cond_broadcast(&done_cv);   // unrelated/spurious wake must not release the same-key waiter
    plat_mutex_unlock(&P.lock);
    wait_for(&wait_entries, waits + 1);
    assert(__atomic_load_n(&hot->info->pipeline, __ATOMIC_ACQUIRE) == (VkPipeline)999);
}

static void same_key(int stage, int fail, int prebuild, int mode) {
    reset();
    GfxShader hot_shader = {.stage = GFX_STAGE_VS, .id = 1};
    Call hot = {.shader = &hot_shader};
    lookup(&hot);
    if (mode == 3) start_workers = 1, atomic_store(&fail_job, 1), mode = 1;
    GfxShader shader = {.stage = stage, .id = 2, .failures = fail};
    gate_on(&shader);
    Call a = {.shader = &shader, .prebuild = prebuild, .mode = mode};
    Call b = {.shader = &shader, .mode = mode};
    pthread_t ta = launch(&a);
    gate_entered();
    pthread_t tb = launch(&b);
    wait_for(&waiters, 1);
    unrelated_work(&hot);
    assert(!atomic_load(&a.done) && !atomic_load(&b.done));
    gate_open();
    pthread_join(ta, NULL), pthread_join(tb, NULL);
    int retry = prebuild && fail;
    assert(atomic_load(&shader.builds) == 1 + retry);
    assert(!b.pending && b.info);
    assert(b.pipeline == (fail && !retry ? VK_NULL_HANDLE : (VkPipeline)102));
    if (!prebuild) assert(a.pipeline == b.pipeline && a.info == b.info);
    Call again = {.shader = &shader};
    lookup(&again);
    assert(again.info == b.info && again.pipeline == b.pipeline);
    assert(atomic_load(&shader.builds) == 1 + retry);
    assert(P.stats.failures == (fail && !prebuild));
    assert(P.stats.compute == (stage == GFX_STAGE_CS && (!fail || retry)));
    assert(P.stats.graphics == 1 + (stage == GFX_STAGE_VS && !fail));
    assert(noted == 1 + (stage == GFX_STAGE_VS && !fail && mode != 2));
    assert(!P.stats.pending_skips);
    if (prebuild) assert(fail ? LB.fail[2] == 1 : LB.built[2] == 1);
}

static void shared_hits_and_upgrade(void) {
    reset();
    GfxShader shader = {.stage = GFX_STAGE_VS, .id = 3};
    Call first = {.shader = &shader, .upgrade = 1};
    atomic_store(&upgrade_entered, 0), atomic_store(&upgrade_release, 0);
    pthread_t t = launch(&first);
    wait_for(&upgrade_entered, 1);
    Call other = {.shader = &shader};
    lookup(&other);   // populate between the first caller's shared and exclusive lock
    atomic_store(&upgrade_release, 1);
    pthread_join(t, NULL);
    assert(first.info == other.info && atomic_load(&shader.builds) == 1);
    plat_mutex_lock_shared(&P.lock);
    Call hits[8] = {0};
    pthread_t threads[8];
    for (int i = 0; i < 8; i++) hits[i].shader = &shader, threads[i] = launch(&hits[i]);
    for (int i = 0; i < 8; i++) wait_for(&hits[i].done, 1), pthread_join(threads[i], NULL);
    plat_mutex_unlock_shared(&P.lock);
    VkPipeStats stats;
    vk_pipeline_stats(&stats);
    assert(stats.hits == 9 && stats.graphics == 1);
}

static void async_and_allocation(void) {
    reset();
    GfxShader shader = {.stage = GFX_STAGE_VS, .id = 4};
    start_workers = 1;
    Call queued = {.shader = &shader, .mode = 1};
    lookup(&queued);
    assert(queued.pending && !queued.pipeline && !queued.info && !atomic_load(&shader.builds));
    assert(A.inflight == 1 && A.head);
    // A published fast link remains usable while the optimised job owns the entry.
    Pipe *p = A.head->p;
    plat_mutex_lock(&P.lock);
    p->fast = (VkPipeline)104;
    pipe_publish(p, p->fast);
    plat_mutex_unlock(&P.lock);
    Call fast = {.shader = &shader, .mode = 1};
    lookup(&fast);
    assert(!fast.pending && fast.pipeline == p->fast && fast.info == &p->info);
    assert(P.stats.hits == 0);
    plat_mutex_lock(&P.lock);
    pipe_publish(p, (VkPipeline)204);
    p->building = 0, p->job = NULL;
    free(A.head);
    A.head = A.tail = NULL, A.inflight = 0;
    plat_mutex_unlock(&P.lock);
    assert(__atomic_load_n(&fast.info->pipeline, __ATOMIC_ACQUIRE) == (VkPipeline)204);
    reset();
    for (int cs = 0; cs < 2; cs++) {
        shader.stage = cs ? GFX_STAGE_CS : GFX_STAGE_VS;
        atomic_store(&fail_alloc, 1);
        Call oom = {.shader = &shader};
        lookup(&oom);
        assert(!oom.pipeline && !oom.info && !atomic_load(&shader.builds) && !P.sync_builds);
    }
}

static void *drain(void *arg) { workers_drain(); atomic_store((atomic_int *)arg, 1); return NULL; }

static void drain_build(void) {
    reset();
    GfxShader shader = {.stage = GFX_STAGE_CS, .id = 5};
    gate_on(&shader);
    Call c = {.shader = &shader};
    pthread_t tc = launch(&c), td;
    gate_entered();
    atomic_int done = 0;
    assert(!pthread_create(&td, NULL, drain, &done));
    wait_for(&waiters, 1);
    assert(!atomic_load(&done));
    gate_open();
    pthread_join(tc, NULL), pthread_join(td, NULL);
    assert(atomic_load(&done) && !P.sync_builds);
}

static void bad_stage(void) {
    reset();
    GfxShader shader = {.stage = GFX_STAGE_FS, .id = 6};
    const VkPipeInfo *first, *again;
    assert(!vk_pipeline_compute(&shader, &first));
    assert(!vk_pipeline_compute(&shader, &again));
    assert(first && first == again && !atomic_load(&shader.builds));
    VkPipeState s = {.vs = &shader};
    assert(!vk_pipeline_graphics(&s, &first));
    assert(!vk_pipeline_graphics(&s, &again));
    assert(first && first == again && !atomic_load(&shader.builds));
    assert(P.stats.failures == 2 && !P.sync_builds);
}

static void prebuild_follows_draw(int fail) {
    reset();
    GfxShader shader = {.stage = GFX_STAGE_CS, .id = 7, .failures = fail};
    gate_on(&shader);
    Call draw = {.shader = &shader}, prebuild = {.shader = &shader, .prebuild = 1};
    pthread_t td = launch(&draw);
    gate_entered();
    pthread_t tp = launch(&prebuild);
    wait_for(&waiters, 1);
    gate_open();
    pthread_join(td, NULL), pthread_join(tp, NULL);
    assert(atomic_load(&shader.builds) == 1 && LB.have[2] == 1);
    assert(P.stats.failures == fail && LB.cs_draw == !fail);
}

int main(void) {
    for (int fail = 0; fail < 2; fail++) {
        same_key(GFX_STAGE_CS, fail, 0, 0);
        same_key(GFX_STAGE_CS, fail, 1, 0);
        same_key(GFX_STAGE_VS, fail, 0, 0);
        same_key(GFX_STAGE_VS, fail, 0, 1);   // worker-start failure falls back to the same synchronous owner
        same_key(GFX_STAGE_VS, fail, 0, 2);   // prewarm fallback preserves its key-recording policy
        same_key(GFX_STAGE_VS, fail, 0, 3);   // job-allocation failure also falls back
        prebuild_follows_draw(fail);
    }
    shared_hits_and_upgrade();
    async_and_allocation();
    drain_build();
    bad_stage();
    reset();
    puts("pipeline locking: duplicate owners, failures/retry, unrelated progress, shared hits, upgrade, memo, async, OOM, drain passed");
    return 0;
}

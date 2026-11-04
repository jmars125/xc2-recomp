// Synthetic mount roots and guest paths: rejected names and long joins; no game files or storage roots are opened.
#include <assert.h>
#include "../runtime/host.h"
#undef HOST_OVERRIDE
#define HOST_OVERRIDE(sym, fn)
#include "../runtime/fs_host.c"
#define need romfs_need
#define lock romfs_lock
#include "../runtime/romfs.c"
#undef lock
#undef need

void rt_log(const char *fmt, ...) { (void)fmt; }
void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
void plat_mutex_lock(PlatMutex *m) { (void)m; }
void plat_mutex_unlock(PlatMutex *m) { (void)m; }
void plat_mutex_lock_shared(PlatMutex *m) { (void)m; }
void plat_mutex_unlock_shared(PlatMutex *m) { (void)m; }
int plat_fs_kind(const char *p) { (void)p; return PLAT_FS_MISSING; }
int plat_fs_list(const char *p, int (*cb)(const char *, int, uint64_t, void *), void *ctx) {
    (void)p; (void)cb; (void)ctx; abort();
}

static void test_paths(void) {
    const char *bad[] = {"CON", "nul.txt", "Aux", "pRn.dat", "com1", "LPT9.sav", "CON .sav", "CONIN$", "conout$.txt",
                         "COM\xc2\xb9", "lpt\xc2\xb2.dat", "COM\xc2\xb3", ".", "..", "a.", "a ", "a:b"};
    const char *good[] = {"save.bin", "console", "null", "COM0", "LPT10", "com1extra", "x.CON", "COM", "LPT"};
    for (size_t i = 0; i < sizeof bad / sizeof *bad; i++) assert(!component_ok(bad[i], strlen(bad[i])));
    for (size_t i = 0; i < sizeof good / sizeof *good; i++) assert(component_ok(good[i], strlen(good[i])));
    char root[1100], guest[800], out[PATH_CAP];
    memset(root, 'r', 1050); root[1050] = 0;
    assert(!mount_add("test", M_TEMP, root));
    strcpy(guest, "test:/");
    memset(guest + 6, 'a', 768); guest[774] = 0;
    assert(!host_path(guest, out, sizeof out));
    assert(strlen(out) == 1050 + 1 + 768);
    assert(host_path("test:/NUL.txt", out, sizeof out) == FS_R_INVALID_PATH);
}

int main(void) {
    test_paths();
    puts("runtime paths: names and long joins passed");
    return 0;
}

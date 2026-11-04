// Injected host read and write failures on save files; no game files or storage roots are opened.
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

static int64_t results[64];
static int calls, sleeps, id_ok = 1, sync_ok = 1;
static uint64_t offsets[64], host_size = 64;
void rt_log(const char *fmt, ...) { (void)fmt; }
void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
void mem_thaw(uint64_t addr, uint64_t size) { (void)addr; (void)size; }
void plat_mutex_lock(PlatMutex *m) { (void)m; }
void plat_mutex_unlock(PlatMutex *m) { (void)m; }
void plat_mutex_lock_shared(PlatMutex *m) { (void)m; }
void plat_mutex_unlock_shared(PlatMutex *m) { (void)m; }
void plat_sleep_ms(uint32_t ms) { assert(ms == 50); sleeps++; }
int plat_file_id(PlatFile *f, PlatFileId *id) { (void)f; id->size = host_size; return id_ok; }
int plat_file_fsync(PlatFile *f) { (void)f; return sync_ok; }
int64_t plat_file_pread(PlatFile *f, void *buf, uint32_t n, uint64_t off) {
    (void)f;
    assert(calls < 64);
    offsets[calls] = off;
    int64_t r = results[calls++];
    assert(r <= n);
    if (r > 0) memset(buf, 0x5a, (size_t)r);
    return r;
}
int64_t plat_file_pwrite(PlatFile *f, const void *buf, uint32_t n, uint64_t off) {
    (void)f; (void)buf;
    assert(calls < 64);
    offsets[calls] = off;
    int64_t r = results[calls++];
    assert(r <= n);
    return r;
}

static void io_reset(void) {
    calls = sleeps = 0;
    memset(results, 0, sizeof results);
    files[0] = (File){(PlatFile *)1, FS_OPEN_READ | FS_OPEN_WRITE, 0};
    id_ok = sync_ok = 1;
}
static void test_io(void) {
    uint8_t buf[8];
    uint64_t got;
    int32_t flush = 1;
    io_reset();
    results[0] = -PLAT_FS_BUSY; results[1] = 2; results[2] = 3;
    assert(!read_file(&got, FILE_BASE, 7, buf, 8) && got == 5);
    assert(calls == 4 && sleeps == 1 && offsets[0] == 7 && offsets[1] == 7 && offsets[2] == 9);
    io_reset(); results[0] = 2; results[1] = -1;
    assert(read_file(&got, FILE_BASE, 0, buf, 8) == FS_R_INVALID_ARGUMENT && got == 2 && !sleeps);
    io_reset(); results[0] = -2;
    assert(read_file(&got, FILE_BASE, 0, buf, 8) == FS_R_INVALID_ARGUMENT && got == 0 && calls == 1);
    for (int writing = 0; writing < 2; writing++) {
        io_reset();
        for (int i = 0; i < 64; i++) results[i] = -PLAT_FS_BUSY;
        uint32_t r = writing ? write_file(FILE_BASE, 0, buf, 8, NULL) : read_file(&got, FILE_BASE, 0, buf, 8);
        assert(r == FS_R_INVALID_ARGUMENT && calls == 41 && sleeps == 40);
    }
    io_reset(); results[0] = 2; results[1] = -PLAT_FS_BUSY; results[2] = 6;
    assert(!write_file(FILE_BASE, 7, buf, 8, &flush));
    assert(calls == 3 && sleeps == 1 && offsets[1] == 9 && offsets[2] == 9);
    io_reset(); results[0] = -1;
    assert(write_file(FILE_BASE, 0, buf, 8, NULL) == FS_R_INVALID_ARGUMENT && calls == 1 && !sleeps);
    io_reset();
    assert(write_file(FILE_BASE, 0, buf, 8, NULL) == FS_R_INVALID_ARGUMENT && calls == 1);
    io_reset(); id_ok = 0;
    assert(write_file(FILE_BASE, 0, buf, 8, NULL) == FS_R_INVALID_ARGUMENT && !calls);
    io_reset(); results[0] = 8; sync_ok = 0;
    assert(write_file(FILE_BASE, 0, buf, 8, &flush) == FS_R_INVALID_ARGUMENT);
    io_reset();
    assert(write_file(FILE_BASE, 63, buf, 8, NULL) == FS_R_APPEND_REQUIRED && !calls);
    files[0].mode |= FS_OPEN_APPEND; results[0] = 8;
    assert(!write_file(FILE_BASE, 63, buf, 8, NULL));
    io_reset();
    assert(read_file(&got, FILE_BASE, INT64_MAX, buf, 8) == FS_R_INVALID_ARGUMENT && !calls);
    assert(write_file(FILE_BASE, 0, buf, UINT64_MAX, NULL) == FS_R_INVALID_ARGUMENT && !calls);
    files[0].mode = FS_OPEN_READ;
    assert(write_file(FILE_BASE, 0, buf, 8, NULL) == FS_R_OPEN_MODE);
    files[0].mode = FS_OPEN_WRITE;
    assert(read_file(&got, FILE_BASE, 0, buf, 8) == FS_R_OPEN_MODE);
}

int main(void) {
    test_io();
    puts("runtime save I/O: failures and retries on busy files passed");
    return 0;
}

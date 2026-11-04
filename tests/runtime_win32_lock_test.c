// Windows integration check: actual byte-range lock conflicts, using only a new temporary file.
#include <assert.h>
#include "../runtime/platform/win32.c"

int main(void) {
    char temp[1100], file[1200];
    assert(plat_temp_dir(temp, sizeof temp));
    snprintf(file, sizeof file, "%s/xc2-lock-test-%lu.bin", temp, (unsigned long)GetCurrentProcessId());
    int err = 0;
    PlatFile *f = plat_fs_create(file, &err);
    assert(f && plat_file_pwrite(f, "save", 4, 0) == 4 && plat_file_fsync(f));
    plat_file_close(f);
    f = plat_fs_open(file, 1, &err);
    PlatFile *other = plat_fs_open(file, 1, &err);
    assert(f && other);
    char data[4];
    assert(plat_file_pread(f, data, 4, 0) == 4 && !memcmp(data, "save", 4));
    OVERLAPPED ov = {0};
    assert(LockFileEx((HANDLE)other, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 4, 0, &ov));
    assert(plat_file_pread(f, data, 4, 0) == -PLAT_FS_BUSY);
    assert(plat_file_pwrite(f, "next", 4, 0) == -PLAT_FS_BUSY);
    assert(UnlockFileEx((HANDLE)other, 0, 4, 0, &ov));
    assert(plat_file_pwrite(f, "next", 4, 0) == 4);
    plat_file_close(other); plat_file_close(f);
    assert(!plat_fs_unlink(file));
    puts("Windows filesystem: lock conflicts passed");
    return 0;
}

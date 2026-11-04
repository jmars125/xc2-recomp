// Windows integration check: long paths, using only a new temporary tree.
#include <assert.h>
#include "../runtime/platform/win32.c"

static int listed(const char *name, int kind, uint64_t size, void *ctx) {
    assert(!strcmp(name, "save-\xc3\xa9.bin") && kind == PLAT_FS_FILE && size == 4);
    ++*(int *)ctx;
    return 1;
}

int main(void) {
    wchar_t w[WPATH];
    assert(widen_path("C:/base/../save.bin", w, WPATH) && !wcscmp(w, L"\\\\?\\C:\\save.bin"));
    assert(widen_path("//server/share/folder/save.bin", w, WPATH) &&
           !wcscmp(w, L"\\\\?\\UNC\\server\\share\\folder\\save.bin"));
    assert(widen_path("\\\\?\\C:\\save.bin", w, WPATH) && !wcscmp(w, L"\\\\?\\C:\\save.bin"));
    assert(widen_path("\\\\?\\UNC\\server\\share\\save.bin", w, WPATH) &&
           !wcscmp(w, L"\\\\?\\UNC\\server\\share\\save.bin"));
    assert(widen_path("relative/../save.bin", w, WPATH) && !wcsncmp(w, L"\\\\?\\", 4) && !wcsstr(w, L".."));
    assert(!widen_path("C:/save.bin", w, 4) && !w[0]);
    char huge[WPATH + 20];
    memset(huge, 'x', sizeof huge - 1); huge[sizeof huge - 1] = 0;
    assert(!widen_path(huge, w, WPATH));

    char temp[1100], dirs[9][1100], file[1200], renamed[1200], linked[1200];
    assert(plat_temp_dir(temp, sizeof temp));
    snprintf(dirs[0], sizeof dirs[0], "%s/xc2-fs-test-%lu", temp, (unsigned long)GetCurrentProcessId());
    assert(!plat_fs_mkdir(dirs[0]));
    for (int i = 1; i < 9; i++) {
        snprintf(dirs[i], sizeof dirs[i], "%s/abcdefghijklmnopqrstuvwxyz-abcdefghijklmnopqrstuvwxyz-%d", dirs[i - 1], i);
        assert(!plat_fs_mkdir(dirs[i]));
    }
    assert(strlen(dirs[8]) > 260 && plat_fs_kind(dirs[8]) == PLAT_FS_DIR);
    snprintf(file, sizeof file, "%s/save-\xc3\xa9.bin", dirs[8]);
    snprintf(renamed, sizeof renamed, "%s/renamed.bin", dirs[8]);
    snprintf(linked, sizeof linked, "%s/linked.bin", dirs[8]);
    int err = 0;
    PlatFile *f = plat_fs_create(file, &err);
    assert(f && plat_file_pwrite(f, "save", 4, 0) == 4 && plat_file_fsync(f));
    plat_file_close(f);
    assert(plat_fs_kind(file) == PLAT_FS_FILE);
    int count = 0;
    assert(!plat_fs_list(dirs[8], listed, &count) && count == 1);
    f = plat_fs_open(file, 1, &err);
    assert(f);
    char data[4];
    assert(plat_file_pread(f, data, 4, 0) == 4 && !memcmp(data, "save", 4));
    plat_file_close(f);
    assert(!plat_fs_rename(file, renamed, 1));
    assert(!plat_fs_link(renamed, linked) && plat_fs_links(linked) == 2);
    plat_fs_sync_dir(dirs[8]);
    assert(!plat_fs_unlink(linked) && !plat_fs_unlink(renamed));
    for (int i = 8; i >= 0; i--) assert(!plat_fs_rmdir(dirs[i]));
    puts("Windows filesystem: path conversion, deep Unicode save and rename/link passed");
    return 0;
}

"""Compile and run every tests/runtime_*_test.c synthetic regression check without game files.

Linux: python tests/runtime_errors_test.py --scratch /tmp/xc2-runtime-check
Windows (UCRT64 clang first on PATH): python tests/runtime_errors_test.py --scratch C:/temp/xc2-runtime-check
The movie check needs libvpx headers; nothing links libvpx or SDL. The runtime_win32_* checks run on Windows only.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ROMFS_STUB = '''#define ROMFS_MISSING 1
#define ROMFS_IMAGE_SHA256 "synthetic fixture"
#define ROMFS_INDEX_SHA256 "synthetic fixture"
#define ROMFS_FILE_COUNT 0
#define ROMFS_IMAGE_SIZE 0
'''


def run(scratch, cc):
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-errors-", dir=scratch) as tmp:
        work = Path(tmp)
        (work / "romfs_config.h").write_text(ROMFS_STUB)
        tests = sorted(p.stem for p in (ROOT / "tests").glob("runtime_*_test.c"))
        if os.name != "nt":
            tests = [name for name in tests if not name.startswith("runtime_win32_")]
        for name in tests:
            exe = work / (name + (".exe" if os.name == "nt" else ""))
            command = [cc, "-std=gnu11", "-O1", "-ffunction-sections", "-fdata-sections", "-I" + str(work),
                       "-I" + str(ROOT / "runtime"), str(ROOT / "tests" / (name + ".c")),
                       "-Wl,--gc-sections", "-o", str(exe)]
            if os.name == "nt":
                # GNU ld and lld for PE keep unreferenced functions that --gc-sections drops on ELF; those call runtime parts the test leaves out.
                command += ["-fuse-ld=lld", "-Wl,-Xlink=-force:unresolved"]
            if name.startswith("runtime_win32_"):
                command += ["-lbcrypt", "-lpsapi", "-lwinmm", "-lshell32", "-lole32", "-luuid"]
            subprocess.run(command, check=True)
            subprocess.run([str(exe)], check=True, timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    run(args.scratch.resolve(), args.cc)

"""Exercise pipeline ownership with fake builds and the real Linux platform locks.

Run on Linux: python tests/vk_pipeline_lock_test.py --scratch /tmp/pipeline-check
Needs clang and Vulkan headers, but no SDL, Vulkan device, game files or runtime build.
The harness compiles the current cache/lookup functions verbatim; shader/layout creation
is stubbed so a test can hold a build open. The full source also gets a syntax check.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = re.search(r"^(?:static )?[^\n;{}]*\b" + name + r"\([^;]*?\) \{", source, re.M)
    if not start:
        raise ValueError(f"function not found: {name}")
    # These functions use column-zero closing braces; one-line helpers end on their first line.
    line_end = source.index("\n", start.end())
    end = line_end if source[start.end():line_end].rstrip().endswith("}") else source.index("\n}", start.end()) + 2
    return source[start.start():end] + "\n"


def section(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def run(scratch):
    source = (ROOT / "runtime/vk_pipeline.c").read_text()
    (scratch / "SDL3").mkdir()
    (scratch / "SDL3/SDL_clipboard.h").write_text("int SDL_SetClipboardText(const char *);\n")
    (scratch / "vk_mem_alloc.h").write_text(
        "typedef struct VmaAllocator_T *VmaAllocator;\n"
        "typedef struct VmaAllocation_T *VmaAllocation;\n"
        "typedef struct VmaDeviceMemoryCallbacks VmaDeviceMemoryCallbacks;\n")
    types = source[:source.index("static uint64_t fnv(")]
    types += section(source, "typedef struct {\n    uint32_t n;\n    VkDescriptorSetLayoutBinding", "static VkDescriptorType descriptor_type")
    types += section(source, "typedef struct {                       // normalized:", "static int blendable")
    types += section(source, "static PlatCond work_cv", "static Lib *libs")
    types += section(source, "typedef struct LibJob", "// A building entry for key")
    types += section(source, "typedef struct Job", "// ---- pipeline keys")
    types += section(source, "#define LB_MAX_THREADS", "static void lb_lock")
    (scratch / "pipeline_types.inc").write_text(types)
    names = ["key_hash", "pipe_find", "pipe_add", "pipe_publish", "now_ms", "qpc", "ms_since",
             "workers_drain", "pipe_miss", "graphics", "vk_pipeline_graphics", "vk_pipeline_graphics_async",
             "compute_layout", "lb_lock", "lb_unlock", "compute_get", "vk_pipeline_compute",
             "lb_count", "lb_compute", "vk_pipeline_stats"]
    (scratch / "pipeline_functions.inc").write_text("\n".join(function(source, name) for name in names))
    cc = os.environ.get("CC", "clang")
    flags = [cc, "-std=gnu11", "-I" + str(ROOT / "runtime"), "-I" + str(scratch)]
    subprocess.run(flags + ["-fsyntax-only", str(ROOT / "runtime/vk_pipeline.c")], check=True)
    exe = scratch / "pipeline_check"
    subprocess.run(flags + ["-O1", "-g", "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                           str(ROOT / "tests/vk_pipeline_lock_check.c"), str(ROOT / "runtime/platform/linux.c"),
                           "-pthread", "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, help="parent for temporary compiler output")
    args = parser.parse_args()
    if args.scratch:
        args.scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pipeline-", dir=args.scratch) as tmp:
        run(Path(tmp))

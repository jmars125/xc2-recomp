# Building from source

Windows 10 or later, an x86-64 CPU with AVX2, and a GPU with Vulkan 1.3 and `VK_EXT_external_memory_host`. Allow about
60 GB for the work folder. Extraction wants about 55 GB free while it runs and keeps about 35 GB afterwards.

Players who only want to play can use the [installer](installer.md) instead: it builds the game on their machine
without this toolchain.

## Toolchain

Versions are the ones the build was verified with; newer patch releases are fine.

| Tool | Version | Install | Used for |
|---|---|---|---|
| MSYS2 UCRT64 | clang/lld 23.1.3 | msys2.org installer to `C:\msys64`, packages below | compiling the generated C and the runtime |
| Visual Studio Build Tools | 2026, C++ workload, Windows SDK 10.0.26100 | winget `Microsoft.VisualStudio.BuildTools` with `--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended` | the linker .NET NativeAOT calls |
| .NET SDK | 10.0 | winget `Microsoft.DotNet.SDK.10` | the shader translator (`xc2_xlate.exe`) |
| Vulkan SDK | 1.4.363 | winget `KhronosGroup.VulkanSDK` | validation layers, `vulkaninfo` |
| uv | 0.13 | standalone installer from astral.sh | the two Python environments |
| hactool | 1.4.0 @ `1d64a83` | `.venv\Scripts\python tools\build_hactool.py`, see below | NCA and update extraction |
| llvm-mingw + libraries | clang 23.1.4, SDL3 3.4.18, Opus 1.6.1, libvpx 1.17.0, zstd 1.5.7, Vulkan 1.4.363, VMA 3.4.0 | `.venv\Scripts\python tools\fetch_toolchain.py`, see below | `tools\build_xc2.ps1` (3.0.1) |

MSYS2 packages, after `pacman -Syuu` (run it twice; the first pass updates the core and exits):

```sh
pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-{clang,lld,ninja,gcc,make,pkgconf,sdl3,opus,libvpx,zstd,vulkan-devel,\
vulkan-memory-allocator,vulkan-validation-layers,shaderc,spirv-tools} base-devel git unzip
```

`ffmpeg` from MSYS2 is a GPLv3 build and is never linked; the movies go through libvpx.

PATH:

- Add `C:\Program Files (x86)\Microsoft Visual Studio\Installer` to the user PATH: NativeAOT needs `vswhere.exe`, or
  the publish fails at the link step (MSB3073).
- Another `cmake` or `ninja` earlier on PATH (a 32-bit winlibs MinGW, for example) is picked up by accident. The build
  scripts call Ninja from `C:\msys64\ucrt64\bin` themselves; from a shell, put `C:\msys64\ucrt64\bin` first.

### hactool

`tools/build_hactool.py` fetches SciresM/hactool at `1d64a83` into `toolchain\src\hactool`, applies the two patches in
`tools/hactool/` and builds a static `toolchain\hactool\hactool.exe` with MSYS2 UCRT64 gcc (a few seconds):

- `portable.patch`: the parts of MacNativeGames' `build_hactool()` that run on Windows, the `MNG_TITLE_KEYS` variable and
  the two BKTR fixes in `nca.c` for the subsection table padding and the subsection layout of newer cumulative updates;
- `unicode.patch`: a manifest with `<activeCodePage>UTF-8</activeCodePage>`, so paths under a non-ASCII user profile
  reach it intact.

hactool reads `-k <prod.keys>`; MSYS2 shells set `HOME`, which hides its default key location, so pass `-k` there.

### llvm-mingw and libraries

`tools\build_xc2.ps1` builds 3.0.1 with llvm-mingw and the libraries the Windows release ships, not with MSYS2 clang.
`tools/fetch_toolchain.py` downloads them (once, after the Python environments of step 1) into the ignored `toolchain\`,
from the pinned URLs and sha256 of `tools/make_release.py` (`PINS`), cached in `toolchain\release-dl`:

```powershell
.venv\Scripts\python tools\fetch_toolchain.py
```

- `toolchain\llvm-mingw-23.1.4\llvm-mingw-23.1.4\`: llvm-mingw 20261020 (clang 23.1.4), x86_64 only;
- `toolchain\deps-mingw\include`, `lib`: SDL3, Opus, libvpx, Vulkan headers and loader import library, zstd, VMA;
- `toolchain\deps-mingw\bin`: `SDL3.dll` and `libopus-0.dll`, which `build_xc2.ps1` copies next to `xc2.exe`.

A folder that is already there is kept; `--force` downloads and rebuilds it. Ninja still comes from MSYS2 UCRT64.

## Build

From the repository root, in PowerShell. Every step that depends on the game version takes it as `<ver>`: `v143` for
1.4.3 or `v121` for 1.2.1. The tools default to `v121` when `--version` is left out. Saves load on either version.

1. Python environments (once). `.venv` runs the lifter and the build; `.venv-py314` runs the extraction scripts, which
   need the stdlib `compression.zstd` of Python 3.14:

   ```powershell
   uv venv --python 3.12 .venv
   uv pip install --python .venv/Scripts/python.exe -r tools/requirements.txt
   uv venv --python 3.14 .venv-py314
   uv pip install --python .venv-py314/Scripts/python.exe -r tools/requirements-py314.txt
   ```

2. Copy `config.example.toml` to `config.local.toml` and set the paths to your base game, the update and your console's
   keys file. `config.local.toml` is ignored by git. The tools read the keys file themselves.

3. Extract and verify. This writes `build\extracted\v0` (1.0.0) and `build\extracted\<ver>` for each update in
   `updates`, identified by its hash; a hash mismatch stops the run:

   ```powershell
   .venv-py314\Scripts\python tools\extract.py
   ```

4. Shader translator (once; no game files). This publishes `build\xlate\xc2_xlate.exe`:

   ```powershell
   .venv\Scripts\python tools\build_xlate.py
   ```

5. Lift the modules to C, write the RomFS half of the frame-rate patches, then compile and link `build\<ver>\xc2.exe`:

   ```powershell
   .venv\Scripts\python recomp\gen.py --exefs build\extracted\<ver>\exefs --out generated\<ver> --patches recomp\patches-<ver>.txt
   .venv-py314\Scripts\python tools\make_romfs_patches.py --version <ver>
   .venv\Scripts\python tools\build_game.py --version <ver>
   ```

   Lifting takes about 15 s, a clean compile about 200 s on 24 threads; later builds recompile only what changed.
   `--patches` builds in the frame-rate, resolution and other patch sets, switchable at run time. The link copies
   `SDL3.dll`, `libiconv-2.dll` and `libopus-0.dll` next to the exe.

6. Prepare the shaders (once per build folder and translator). It needs `refs\MacNativeGames` (`tools\fetch_refs.sh`)
   for the shared shader list:

   ```powershell
   .venv-py314\Scripts\python tools\prepare_shaders.py build\<ver> --version <ver>
   ```

   Without this step the first launch compiles shaders and pipelines during play and stutters until the caches fill.
   The AMD driver keeps its pipeline cache per exe path and holds a limited amount: preparing another build folder can
   evict this one's. `xc2.exe --warm-shaders` rebuilds it from the shader cache.

7. Run. Keep the window in the foreground; an unfocused window stalls the game.

   ```powershell
   build\<ver>\xc2.exe
   ```

Settings live in `xc2.ini` next to `xc2.exe` ([xc2.ini.example](../xc2.ini.example) lists them). Saves go to
`build\profile` for `v121` and `build\profile-<ver>` for other versions (`build_game.py --profile` changes it).

### Portable folder

`.venv\Scripts\python tools\package_build.py --version <ver>` writes `build\<ver>-portable`, which runs on another of
your machines without MSYS2, Python or .NET. `romfs.bin` stays out unless you pass `--with-romfs`; otherwise put it in
`romfs\` next to the exe or point `XC2_ROMFS` at its folder. Run `xc2.exe --prepare-shaders` once in the copied
folder. The folder holds code and data derived from your game: for your own machines only.

## Linux (in progress)

The runtime builds and runs on x86-64 Linux with a window, input and menu on SDL3 (`*_sdl.c`) in place of the Win32
files (`*_win.c`); `runtime/platform/linux.c` implements `platform.h`. Status: the selftest and the probes pass; 1.2.1
plays at 60 fps on RADV (RX 7800 XT) and NVIDIA (RTX 3060); 1.4.3 builds, probes and plays on RADV (RX 6600, and the
Vega 7 of a Ryzen 5 4600G at about 34 fps). Long play sessions and the Steam Deck itself are not verified yet.

Requirements:

- Linux 6.7 or later: the write watch uses userfaultfd write protection with `PAGEMAP_SCAN`. SteamOS 3.8 qualifies.
- A Vulkan 1.3 driver with `VK_EXT_external_memory_host` (RADV, NVIDIA).
- Packages on Arch:

  ```sh
  pacman -S --needed clang lld ninja make sdl3 opus libvpx zstd vulkan-headers vulkan-icd-loader \
      vulkan-validation-layers shaderc spirv-tools dotnet-sdk uv git
  ```

  Vulkan Memory Allocator is a single header (AUR `vulkan-memory-allocator`). Without it, `build_game.py` fetches the
  version the Windows release pins (3.4.0) into `toolchain/vma/` on first use and checks its hash.

The steps are the Windows ones with POSIX paths: `.venv/bin/python` in place of `.venv\Scripts\python`, and `xc2` in
place of `xc2.exe`. `build_game.py` takes clang, lld and Ninja from PATH (or the ones in `<dir>/bin` with
`--toolchain <dir>`) and links against the system libraries, with `libstdc++` static and an `$ORIGIN` rpath;
`build_hactool.py` builds `hactool` with make. `tools/prepare_shaders.py` reads the shader list from
`refs/MacNativeGames` at `origin/HEAD`, which must be the pinned commit with its history (the list format changed later).

Memory: on Windows the GPU imports guest memory and `GetWriteWatch` tracks the CPU's writes to it. On Linux,
re-protecting imported memory invalidates the driver's userptr buffer on every submit (about 1.3 ms per 16 MiB on
amdgpu), and importing pins the pages, which drops their write protection. Each CPU-visible pool therefore gets a
host-visible copy (shadow storage, `runtime/vk_memory.c`): the pages the CPU wrote go in before each submit, and the GPU's
writes come back at its fence. In play that costs about 0.2 ms a frame and doubles the memory of those pools (about
1.1 GB). `XC2_SHADOW=1` turns it on under Windows too. The Steam Deck's RADV has `VK_EXT_external_memory_host` as
well: the shadow copies are chosen for the measured cost above, not for a missing extension.

The Deck's GPU (Van Gogh) has no native ASTC, so its textures go through the compute decoder (`runtime/vk_astc.c`,
`XC2_ASTC`) as on desktop AMD GPUs without it; frame times measured there include it.

### Windows build from Linux

A Linux host builds `xc2.exe` with the Linux-hosted tarball of the llvm-mingw release the Windows release pins
(`tools/make_release.py`, `PINS`): the same clang, lld, `llvm-windres`, mingw-w64 headers and libc++ as a
`--toolchain` build on Windows, with the Windows libraries from `toolchain/deps-mingw` as there. Once, with the 3.14
environment (it reads the MSYS2 packages):

```sh
.venv-py314/bin/python tools/make_release.py --cross-tools
```

downloads and checks them into `toolchain/`: `llvm-mingw-<version>/llvm-mingw-<version>-ucrt-ubuntu-22.04-x86_64/`,
`ninja-linux/ninja` and `deps-mingw/` (`include/`, `lib/`, `bin/` with `SDL3.dll` and `libopus-0.dll`). Then:

```sh
.venv/bin/python tools/build_game.py --version <ver> --target windows \
    --toolchain toolchain/llvm-mingw-<version>/llvm-mingw-<version>-ucrt-ubuntu-22.04-x86_64 \
    --ninja toolchain/ninja-linux/ninja --out build/<ver>-cross
```

writes `build/<ver>-cross/xc2.exe` with the DLLs beside it: the Windows runtime files (`*_win.c`,
`platform/win32.c`, `xc2.rc`), flags and libraries of the Windows `--toolchain` build, so the folder is what that build
makes and runs on a Windows machine with the game files (the host cannot run it; `--selftest` and the probes run
there). `--target` defaults to the host's OS, so no other invocation changes. Memory is measured per process only (no
job objects), and the generated objects are never shared with another build directory, as with `--toolchain` on
Windows. A clean 3.0.1 build took 12 s on a 256-thread host (66 compile jobs under the 50 GiB budget; 256 jobs gained
nothing, the largest chunk sets the time); 1.0.0 took 62 s on 32 threads.

## Checks

Before a commit:

- `python tools/check_content.py --staged`: nothing game-derived is staged. CI runs the same check;
  `git config core.hooksPath .githooks` runs it before each local commit and refuses pushes to `master` or `main`.
- `build\<ver>\xc2.exe --selftest`: layout, dispatch table and host-function registry, without game files.

`python tests\run.py` runs every check that needs no game files and prints one line per check (`--list` names them,
`--skip-native` leaves out the ones that compile C); CI runs it on Linux and Windows on every push and pull request
(`.github/workflows/tests.yml`). `tools\check_platform.py` runs there without blocking: it still finds Win32 calls in
`runtime/kernel.c` and `runtime/main.c`.

The lifter (`recomp/`) and the CPU headers (`runtime/cpu.h`, `runtime/simd.h`) are checked against Unicorn. Every lifter
change passes these, all run with `.venv`, with one known gap in `excl_mt.py` (below the table):

| Test | Checks | Game files |
|---|---|---|
| `tests\diff\lift.py` | instructions sampled from the extracted modules; `--coverage` lists every word the lifter rejects or traps | yes |
| `tests\diff\simd.py` | the whole FP/SIMD encoding space | no |
| `tests\diff\atomic.py` | exclusive load/store sequences and ARMv8.1 atomics | no |
| `tests\diff\func.py` | whole functions as the generator emits them, loops, jump tables and calls included (calls go to a stub that checks the registers at the call) | yes |
| `tests\flags_check.py` | the function-local flag helpers of `runtime\cpu.h` against its packed ones | no |
| `tests\excl_mt.py` | the exclusive monitor helpers on several threads: the contention cases must pass; the ABA cases are a known gap, printed but not counted (`--strict` counts them) | no |
| `tests\jumptables_check.py` | `recomp/jumptables.py` against a Unicorn oracle; must report 0 disagreements, on 1.4.3 too | yes |

Known gap: `runtime/cpu.h` `stx##N` and `stxp128` emulate the monitor with a compare-and-swap against the value
remembered at the load, so a store-exclusive succeeds after another thread wrote X, Y, X in between, where ARM's monitor
fails it; a monitor that every store clears would cost on every store. `tests\excl_mt.py` runs its three ABA cases,
prints them as `known gap` and leaves them out of the exit code; `--strict` counts them again, which makes them mandatory
once a real monitor replaces the compare-and-swap. An ABA case that passes without `--strict` is printed loudly: the
emulation changed and this note is stale.

Runtime probes, each a mode of `xc2.exe` (the list is at the top of `runtime/main.c`): `--probe-kernel`,
`--probe-vkexec`, `--probe-nvn-tex` and `--probe-shader` cover most runtime changes.

`tests\feedback_check.py` runs the attachment feedback decisions of `runtime\vk_exec.c` and `runtime\vk_exec_draw.c`
against a fake Vulkan device, without a GPU or game files; run it after changing `feedback_prepare` or `feedback_scan`.

Shaders: `.venv-py314\Scripts\python tools\shader_census.py --version <ver> --translate` extracts every Maxwell shader
to `build\<ver>\shaders\` and runs it through the translator and `spirv-val`; failure groups go to `failures.txt`.
`tools\xlate_smoke.py` checks the translator alone, without game files.

## Reverse engineering (optional)

- Ghidra 12.1.2 with Adubbz's Ghidra-Switch-Loader in `toolchain\ghidra\` (JDK 21) opens the game modules (NSO).
- `tools\fetch_refs.sh` clones the upstream projects this port builds on into `refs\`, read-only.

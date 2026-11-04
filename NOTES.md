# XC2 Recomp: bring-up notes

Fork of the XC3 bring-up (`xc3` remote: the uncommitted XC3 work on top of XCX master 1025eac; `xcx` remote: XCX Recomp).
Game data stays out of the repository.

## Inputs

| File | Title id | Notes |
|---|---|---|
| base | `0100E95004038000` | v0 NSP |
| update 3.0.1 (v1114112) | `0100E95004038800` | RomFS through BKTR; the supported version (`tools/data/expected-xc2-3.0.1.json`) |
| add-on content 1-6, 99 | `0100E95004039001`-`6`, `...9063` | 1 Torna, 2 New Quests, 3 Rare Blades, 4 Challenge Mode, 5 Helpful Items, 6 My Nintendo bonus, 99 Japanese voices; mounted from `build/extracted/upd/aoc/<index>` |
| update 2.1.0 (v983040) | `0100E95004038800` | `tools/data/expected-xc2-2.1.0.json`; `extract_xc2.py --name v210`, `build_game.py --version v210`. Boots and plays the new-game script (title to Argentum) with no unimplemented call; no add-on content extracted for it yet |
| XCI | `0100E95004038000` | base + v2.1.0 update + 7 DLC in one cartridge image; the 2.1.0 build uses the NSP update instead |

## Survey

- Older NintendoSDK (2017). Modules `main`, `sdk`, `subsdk0`, `rtld`. Init arrays: main 200, subsdk0 46, sdk 103.
- Start-up is `nn::init::Start(ulong, ulong, void (*)(), void (*)())`: two callbacks, no finalizer (`boot.c guest_main`).
- First `nvnBootstrapLoader` returns to main+0x708b44 (2.1.0: +0x7082c4; `boot.c nvn_rets`, keyed by `rt_game_name`).
- 2.1.0 and 3.0.1 bind the same 59 overrides (`--probe-services`); the same SDK symbols, so no older-SDK gap shows for 2.1.0.
- Lifted: 76,639 functions (main 35,908), 277 MB of C, 0 unsupported instructions, 21 s.
- Audio goes through AudioRenderer at revision 3 (`audren.c`), not AudioOut as in XCX and XC3.
- NVN pool and texture setup lends the virtual core (`kernel.c kern_core_lend`, `nvn_api.h NVN_BLOCKING`): taking it back
  counts one priority step better. Without that, XC2's main thread (p44, polling the clock with no SVC) kept the core the
  render thread (p44) gave up in `nvnMemoryPoolInitialize`, and presents stopped on the first loading screen.
- Older SDK names the runtime now also answers: `account::OpenPreselectedUser` (Result), `fs::CommitSaveData`,
  `vi::SetLayerScalingMode`, `oe::Enable/DisableScreenShot`. `fs::QueryMountRomCacheSize` answers one page: XC2 mallocs it and
  asserts on null.

## Build and run

```powershell
.venv-py314\Scripts\python tools\extract_xc2.py --base game\base.nsp --update game\update-3.0.1.nsp --keys <prod.keys> --dlc (ls game\dlc-*.nsp) --hactool toolchain\hactool\hactool.exe
.venv\Scripts\python recomp\gen.py --exefs build\extracted\upd\exefs --out generated\upd
tools\build_xc2.ps1
build\upd\xc2.exe
```

`build\xlate\xc2_xlate.exe` is XC3's translator build copied over (same sources) with `tools\build_xlate.py --id-only`.

`tools\build_xc2.ps1` builds with the repository's own toolchain in the ignored `toolchain\`, the dev-mode layout of
`installer/layout.py`: `toolchain\llvm-mingw-<ver>\llvm-mingw-<ver>\` (llvm-mingw, clang 23.1.4 now), `toolchain\deps-mingw`
with `include\`, `lib\` and `bin\` (SDL3.dll, libopus-0.dll), and MSYS2 UCRT64 ninja. `tools\fetch_toolchain.py` recreates
both folders from the release's pinned downloads (`tools/make_release.py` `PINS`, sha256-checked); `-Setup <folder>`
still builds from an unpacked TotK or XC2 Recomp release folder. The build used to borrow `..\..\totk-pc-recomp` and broke when that folder was reset.

Test runs: `XC2_ASSUME_FOCUS=1 XC2_BACKGROUND_WINDOW=1`, `--boot`, `XC2_INPUT_SCRIPT=<file>`, `--seconds N --shot x.png`,
`XC2_SHOTS=<from>-<to>:<step>`, `XC2_DUMP=<frame>`.

## Known gaps

- Transform feedback is not replayed (`nvn_api_cmd.c xfb_skipped`).
- Resolution and ultrawide (2026-11-03). The game keeps its own picture size: neither 3.0.1 nor 2.1.0 holds the
  `{1920, 1080, 1280, 720}` table XC3's `resolution.c` wrote, and the XCX-address interface fit of `nvn_api_cmd.c` is
  gone with it (in the history). What `output_res` does now is shape the 3D view. XC2 keeps no 16:9 constant for its
  camera: the aspect is computed at run time as render width / height (`ml::DevGraph::getAspect` =
  `getRenderW() / getRenderH()`, DevGraph +0x230 / +0x234, inlined at its users; the names are from Glitxhhh's
  xc2-decomp, https://github.com/Glitxhhh/xc2-decomp, whose 1.0.0 `main` keeps its symbols; every update is stripped).
  Both community 21:9 patches for 2.1.0 (build id `F77F1559371C0EC6D50E78774AC59D95`) overwrite that quotient in `s0`:
  Fl4sh_'s "21:9 Ultrawide v2.1.0" pchtxt (https://github.com/Fl4sh9174/Switch-Emulator-Ultrawide-FPS-Mods) rewrites
  three slots at each of three sites, text 0x7e3080/+8/+c (the slot between kept), 0x6cbfcc/+4/+8 and
  0x6c2390/+4/+8, with `mov w30 ; movk w30 ; fmov s0, w30` (3440/1440), and theboy181's "21'9" pchtxt
  (https://github.com/theboy181/switch-ptchtxt-mods) rewrites 0x7e308c alone with `fmov s0, #2.375`; so the code
  there is `scvtf s0, w ; (one) ; scvtf s1, w ; fdiv s0, s0, s1`. `tools/aspect_sites_xc2.py` scans `main` for that
  shape (two integers loaded from memory, converted and divided) and emits the set `aspect`: each `fdiv` alone
  becomes `adrp x30, <page> ; ldr s<d>, [x30, #0x60]` (+0x64 for a division the other way round, emitted only when
  one is found), x30 being dead where the function saved it in its prologue, which the mods assume as well; the
  loads of an f32 16/9 or 9/16 constant are a secondary form. `resolution.c res_init` stores the output's aspect and
  its inverse there and switches the set on for a shape other than 16:9, as `frame_rate.c xc2_rate_store` does for
  the 1/30 loads of `xc360`. The 16:9 frame then holds the wider view, and the present fits the frame at the output's
  shape (`gfx_present.c present_image`, `res_aspect_shape`), so `picture_fit = keep` shows a 21:9 output whole on a
  21:9 window. The interface is laid out on the 16:9 canvas and stretches with the picture, as with the mods under
  the emulators' "stretch to window". On a 2.1.0 `main` the finder checks its result against the mods' sites (agree
  or disagree per site) and against the size pairs Fl4sh_ turns into 2580x1080 (0x6caff8, 0x6cb060, 0x70a634); on
  1.0.0 it verifies the pattern inside `getAspect` itself and names its callers.
  Run on 1.0.0 (2026-11-03, `build/extracted/v0`): eight sites, all camera code. `ml::DevGraphNx::getPersSys`+0x60
  divides DevGraph's render size (+0x230 / +0x234) inline for a matrix of its own (it neither calls `getAspect`, which
  has no caller at all, nor reads a cached field). The camera's own projection and frustum come from RENDER_INFO
  +0x1f0 (its 26 `ldr s` readers cluster in `ScnObjCam` and `ScnCamMan`), and every writer of that field divides a
  size: `ml::ScnObjCam::apply`+0x30 (the viewport, +8 / +0xc), `ml::ScnObjCam::setSize`+0x4c (its argument),
  `ml::ScnCamMan::update`+0x188 (the size it stores to +0x1e0 / +0x1e4 first), and the constructor
  `ml::ScnObjCam::ScnObjCam`+0x130 / +0x198 and `ml::ScnObjCam::infoInit`+0x68, which call `getRootWidth()` and
  `getRootHeight()` (1280x720, 16:9 as well) after setting fov 40, near 0.1, far 80000; `getAspect`+0x28 is the eighth.
  `getAspect` and `setSize` are leaves, patched through x8 and x9 (their converted width dies at the `ret` or the tail
  call); the others through x30. The 15 other divisions of converted integers are HP rates, menu buttons, the minimap,
  the layout and `gf::PlayerCamera`'s root-size aspect, left alone. 1.0.0 has no 1920/1080 pair; its 1280/720 pairs are
  `ml::WorkRoot::getWidth`, `grlib::CGLibDisplay::setup`, `ui::UILayoutObject::updateSize`, the movie player and the
  title loader.
  Run on 3.0.1 (stripped): five sites, read in the disassembly by their shape: main+0x6aac00 (`getPersSys`, the same
  prologue and GOT load of DevGraph), +0x6c2c18 (`ScnCamMan::update`, stores +0x1e0 / +0x1e4 then +0x1f0),
  +0x6cb88c and +0x6cb8f4 (two constructor / `infoInit` copies: fov 40 to +0x1e8, near 0.1, far 80000, then
  `bl main+0x6a2edc` / `bl main+0x6a2efc`, the root getters, divided and stored to +0x1f0), +0x6cc854 (`apply`, the
  viewport with the 1.0 guard). `getAspect` and `setSize` have no copy of their own in 3.0.1. The first 3.0.1 set had
  only the first, second and fifth: the game ran, the log said the set was on, and the title screen and the opening
  cutscene were byte-identical with `XC2_ASPECT=1` and `=0`, because their cameras take the aspect from the
  constructors. The two nnMain matches the finder lists as weak (main+0x68574c, +0x685818) divide
  `(x - min) / (max - min)` from `ldp w8, w9, [x20, #0x80]`, progress fractions, not aspects; main+0x725c7c stores +0x1f0
  from a lerp of two cameras' +0x1e8 .. +0x1f4 (a camera blend, derived); main+0x51288c writes another struct. 3.0.1
  holds 112 `str` to `[x?, #0x1f0]` (98 w, 14 s), 14 of them `str s`, the five above plus the blend, two to the stack
  and the rest other structs. Both results are `KNOWN_SITES` and `gen.py --patches` accepts both sets (no mismatched
  word, five and eight gated sites in the C).
  Not done yet: the five-site 3.0.1 set has not been run in the game (the three-site one has, see above). Its
  `--selftest` covers the forms on a synthetic image. To finish: `fps_sites_xc2.py main > patches-upd.txt`, `aspect_sites_xc2.py main --sizes >> patches-upd.txt`
  (stderr names each site's function, the sites it left unpatched and why), `gen.py --patches`, build, and a run at
  3440x1440 with `XC2_OUTPUT_RES=3440x1440`: the 3D view must show more at the sides, not a stretched 16:9. Which of
  the three sites is the field camera and which the menus or the map is not known; run 2.1.0 first, where the mods'
  sites are the check. Then the interface: the `--sizes` INFO lines list where 1280/720 (the canvas, `ml::WorkRoot`)
  and 1920/1080 are used together. `render_scale` has no effect (the scene sites are not found); the menu row says so.
- 60 fps, 3.0.1 (2026-11-02; on by default, `XC2_FPS_LIMIT=30` or `XC2_FPS60=0` for the shipping 30):
  - Frame pacing is a spin in the main thread, main+0x6aafd8: it reads the system tick until the time since the frame
    began exceeds period * interval * 0.997 (constant main+0x9b558c). The period comes from virtual +0xd0 of the object
    at GOT main+0xb8caa8.
  - The interval is an int at main+0xb75c40: −1 in the image, 2 throughout play. Setter main+0x6a4078 keeps the old
    value at GOT main+0xb8cba0. Its other readers are main+0x6a36bc (frame time = period * interval, 3 callers) and the
    load meter main+0x6aaa5c.
  - Writing 1 there gives a steady 60 fps (59.7 mean). The game then runs at double speed: the title screen changes as
    much in 30 frames at 60 fps as in 30 frames at 30 fps. Logic steps a fixed 1/30 s per frame: the f32 constant at
    main+0x9b5148 has 78 loads (adrp page 0x9b5000 + `ldr s, #0x148`), the frame step a patch set has to send to the patch page.
  - Patch set xc360 (`tools/fps_sites_xc2.py` -> `recomp/patches-upd.txt`): the 79 1/30 loads read patch page
    +0x50, the frame wait +0x48, the frame-time getter +0x50. The interval is set to 1 by
    `frame_rate.c xc2_interval_store`. Result: 59.9 fps at a 60 limit and 114 fps at 120. Alone it left play at
    double speed (the new-game script reached the Arts tutorial at 40 s instead of about 60 s).
  - The step most logic advances by is two f32, 1/30 each, at +0x78 and +0x7c of the object main+0xb900d0 points to;
    the game does not recompute them. The 2.0.2 "60 FPS + Cutscenes Speed Fix" cheat (GBAtemp, "Xenoblade Chronicles 2
    Graphics Settings" thread) writes 1/60 there at 2.0.2 main+0xb8f0d0 with the interval 1; found in 3.0.1 by
    scanning main's data for a pointer to two 1/30 at +0x78. `frame_rate.c xc2_delta_store` writes the measured frame
    time there every frame. New-game script at a 60 limit (45-60 fps): the first fight lasts 43 s against 47 s at 30
    fps, and the script reaches Goldmouth as at 30.
  - Still faster than real time: the title screen and 2D interface (cloud motion per second 9.3 against 5.6 at 30; the
    cheat's users report the same). The cheat also writes 60 (30 in its other branch) to +0xbd4 of the object at
    2.0.2 main+0xf82ed8, and picks its branch on 2.0.2 main+0xbd7e2c == 1.0f and main+0xbd4380 == 0 (its cutscene
    test). The cheat's text (OldManKain, thread post #502) reads `[main+0xbd4380] != 0` as "cutscene": interval 2,
    step 1/30, +0xbd4 = 30. The 2.1.0 cheat uses the same two addresses, and 2.1.0 lays bss out as 2.0.2; 3.0.1 moved
    it by +0x1000 (the same 17 sites write +0x10 of main+0xbd5370 in both). `frame_rate.c xc2_cutscene` reads
    main+0xbd5380 (2026-11-03): 1 on the title screen and through the opening cutscene, 0 after PLUS skips to play,
    1 again at the next event scene; play holds 59-60 fps, cutscenes 30. Not used: the cheat's +0xbd4 / 2.1.0
    [main+0x15e8750]+0x264 write (3.0.1 [main+0x15e9750]+0x264 reads 30 in play and in cutscenes; its use is unknown)
    and its `main+0xbd7e2c != 1.0f` test (3.0.1 +0xbd8e2c stays 0 through the opening).
  - The vsync thread (main+0x89bb08, a 60 Hz WaitSystemEvent loop) counts vsyncs at +0x278 of its object. The frame
    wait does not use it.
  - Not frame pacing: the periodic timer at main+0xec7540 is nn::hid's vibration sampler.
  - Leads for the two values not found in 3.0.1 (the cutscene test and the interface speed), from masagrator's
    FPSLocker-Warehouse (https://github.com/masagrator/FPSLocker-Warehouse, branch `v4`,
    `SaltySD/plugins/FPSLocker/patches/0100E95004038000/4F5C96E2D97F45AC.yaml` for 3.0.1): the cutscene flag is a
    uint8 at main+0xbd8f40 (2.1.0 main+0xbd7f40), == 1 forces 30 fps, and the interface struct is at main+0xc232c8
    (2.1.0 main+0xc222c8), +0x80 the interface speed. He re-finds each per version by a byte pattern (`# REF:` lines),
    as `fps_sites_xc2.py` finds its sites. Not applied to `frame_rate.c` yet.
- XC2 builds its window with present interval 1 and never changes it (`XC2_TRACE=gfx`: `nvnWindowSetPresentInterval` is
  not called through the new-game script). Its 30 fps cap is the game's own vsync waits, so 60 fps needs a patch at that
  site, not at the NVN interval.
- `docs/` and `tests/` still describe XC3 2.2.1 / XCX behaviour under the renamed names; the installer and release text say
  XC2 3.0.1.
- A release folder's deps directory (`-Setup`) has no `bin/`, so `build_game.py --deps` copies no DLLs there; a new build
  directory takes them from `build\upd`. `toolchain\deps-mingw\bin` has them.

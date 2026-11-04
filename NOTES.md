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
`XC2_SHOTS=<from>-<to>:<step>`, `XC2_DUMP=<frame>` (`XC2_DUMP=t<tick>`: the frame where a scripted run reaches that
game tick).

## Known gaps

- Transform feedback is not replayed (`nvn_api_cmd.c xfb_skipped`).
- The patch table holds only the 60 fps set (below); the game keeps its own resolution. Comments that say XC2 in `frame_rate.c`,
  `resolution.c` and the `UI_*` sites of `nvn_api_cmd.c` describe XCX addresses (the rename went XCX -> XC3 -> XC2); those
  paths are inert until the sites are found in XC2's `main`: neither 3.0.1 nor 2.1.0 holds the `{1920, 1080, 1280, 720}`
  table, and the `xc360` set that gates every XCX address write in `frame_rate.c` does not exist for XC2.
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
  - Patch set xc360 (`tools/fps_sites_xc2.py` -> `recomp/patches-upd.txt`): the 1/30 loads read patch page
    +0x50 (79, 16 of them returned to the constant below), the frame wait +0x48, the frame-time getter +0x50. The interval is set to 1 by
    `frame_rate.c xc2_interval_store`. Result: 59.9 fps at a 60 limit and 114 fps at 120. Alone it left play at
    double speed (the new-game script reached the Arts tutorial at 40 s instead of about 60 s).
  - The step most logic advances by is two f32, 1/30 each, at +0x78 and +0x7c of the object main+0xb900d0 points to;
    the game does not recompute them. The 2.0.2 "60 FPS + Cutscenes Speed Fix" cheat (GBAtemp, "Xenoblade Chronicles 2
    Graphics Settings" thread) writes 1/60 there at 2.0.2 main+0xb8f0d0 with the interval 1; found in 3.0.1 by
    scanning main's data for a pointer to two 1/30 at +0x78. `frame_rate.c xc2_delta_store` writes the measured frame
    time there every frame. New-game script at a 60 limit (45-60 fps): the first fight lasts 43 s against 47 s at 30
    fps, and the script reaches Goldmouth as at 30.
  - The title screen and 2D interface were faster than real time (cloud motion per second 9.3 against 5.6 at 30; the
    cheat's users report the same). `frame_rate.c xc2_cutscene` runs the title at 30 fps, which hides that there; play
    has event state 0, so its menus stayed fast. Four separate per-frame assumptions, found with the base game's symbols
    and the `# REF:` lines of masagrator's FPSLocker-Warehouse (`0100E95004038000/4F5C96E2D97F45AC.yaml`):
    - layer animations: [main+0xc232c8]+0x80 is `layer::LayerManager`'s seconds per frame, 1/30, and +0x7c is 30
      (constructor; `setFrameRate` has no caller). Now the measured step: `frame_rate.c xc2_layer_step_store`.
    - ui motions and event delays: `ui::UIMotionData` and the menus' `requestObjectEvent` turn authored frames into
      seconds with the 1/30 constant, and those seconds run out against the frame step. The set xc360 had replaced
      that constant with the step, so N frames took N rendered frames. Those 16 loads keep 1/30
      (`tools/fps_sites_xc2.py UI_FRAME_LENGTH`). `btl` and `event` loads were not classified; some look like the same
      conversion.
    - menu waits: all 27 instances of `gf::GfMenuSequence<T, N>::wait` count rendered frames; the set scales the count
      by patch page +0x4c (FPSLocker scales only the two of `GfMenuObjQuestLog`).
    - button challenge: `btl::ButtonChallenge::Update` sends delta * 30 as a `ui::UICtrl` speed that `ui::UICtrl::update`
      multiplies by the delta again, which only came out right while the motion lengths were halved too. Now 1, the
      shipping value at 30 fps.
    FPSLocker's effect speed (main+0x17794c) is not applied: it is not 2D interface.
    Measured at the title with `XC2_CUTSCENE_30=0`: the dialog's arrows pulse every 0.25 s at 60 fps before and 0.50 s at both rates
    after, and the title's clouds, which are 3D and not this, still change faster at 60 than at 30, the same with and without it.
    Measure the title with `XC2_CUTSCENE_30=0`, or it runs at 30 fps. The cheat also writes 60 (30 in its other branch) to +0xbd4 of the object at
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
- Game fixes, 3.0.1 (`recomp/fixes-upd.txt`, included by `patches-upd.txt`; sites from Aegis, checked against our
  modules): set `wind` (`XC2_WIND_GUARD`) sends main+0x1ab7c0, which can remove a wind object twice and stop the game,
  to `xc2_fixes.c wind_remove`; set `hipcwake` (`XC2_HIPC_BROADCAST`) makes the HIPC session pool broadcast instead of
  signal one waiter (a lost wakeup Aegis saw as a boot hang). Neither crash nor hang has been seen in this port yet.
- Per-frame steps the 60 fps step does not cover, 3.0.1 (measured with probes at the sites, 2026-11-04):
  - The stick camera turned 0.0524 rad a frame at any rate (3.14 rad/s at 60 fps against 1.57 at 30); set `camrate`
    (`XC2_CAM_RATE`) scales its yaw and pitch steps by the frame time: 1.571, 1.591 and 1.577 rad/s at 30, 60, 120.
  - Already right, so not patched: the frame time the per-frame managers get (main+0x32a978 hands them +0x78 of the
    step object, the measured step), and the time of day (its step is 1.6 / fps, built from the xc360 frame time).
    Aegis scales both (its sites +0x35a8f4, +0x35ac28, +0x27e994) because its runtime has no measured step.
- XC2 builds its window with present interval 1 and never changes it (`XC2_TRACE=gfx`: `nvnWindowSetPresentInterval` is
  not called through the new-game script). Its 30 fps cap is the game's own vsync waits, so 60 fps needs a patch at that
  site, not at the NVN interval.
- `docs/` and `tests/` still describe XC3 2.2.1 / XCX behaviour under the renamed names; the installer and release text say
  XC2 3.0.1.
- A release folder's deps directory (`-Setup`) has no `bin/`, so `build_game.py --deps` copies no DLLs there; a new build
  directory takes them from `build\upd`. `toolchain\deps-mingw\bin` has them.

## Cloud Sea

- Issue 5: a flat blue-grey band over the lower screen, flickering, when the camera pitches up at Goldmouth Return Port
  (Argentum). The Cloud Sea shaders (vs `4091bdf5b0df81bb`, fs `595a926b53b7aa34`) place the cloud plane at c3[8].w
  and draw the inside-the-clouds fog when it is above the camera height c3[10].y. main+0x70fd18 fills both, from +0x194
  and +0x154 of the view object at `[[GOT main+0xb8daa0]+0x50]+0x38`.
- The top is −8 there: written once, early in boot, by the environment blender main+0x724ff0 (two presets of the
  area's environment data mixed by a weight). Rex's floor is −8.5, and pitching up lowers the camera to about 0.36 m
  above it, so it sits 0.14 m under the top and crosses it as it bobs. The same at 30 and 60 fps; no translation
  error found on the way, so this reads as the game's own behaviour (no Switch capture to compare yet).
- `XC2_CLOUD_TOP_FIX` (patch set cloudtop, on by default, `=0` turns it off, `recomp/fixes-upd.txt`): a camera less
  than 1 m under the top sees a top 0.125 m below itself, so the clouds stay drawn from above. Diving deeper keeps the fog.
  Tried live at Goldmouth: no band or fog at any camera angle with it on; both come back with it off.

r"""Find the 60 fps sites in XC2's main and print them as the xc360 set of a patch table (recomp/patches.py).

    .venv\Scripts\python tools\fps_sites_xc2.py build\extracted\upd\exefs\main > recomp\patches-upd.txt

XC2 steps its logic by a fixed 1/30 s each frame and paces frames itself (NOTES.md, "60 fps"). The set has these parts:
  - every load of the 1/30 constant (`ldr s<t>, [x<n>, #lo]` after `adrp x<n>, <its page>`) reads patch page +0x50, the
    frame step runtime/frame_rate.c stores; x<n> is pointed back at the constant's page afterwards, so code after the
    site sees the registers it had. The interface's loads (UI_FRAME_LENGTH) keep the constant;
  - the menu sequences' frame-counted waits (wait_sites) count frames of the frame limit;
  - the button challenge's speed factor (SPEED_FACTOR) stays 1;
  - the frame wait's target (the spin in the frame loop, `fmul s0, s0, s10` = period * interval * 0.997) reads +0x48,
    the frame time of the limit;
  - the frame-time getter (period * interval) returns +0x50.
The interval itself (1 instead of 2) and the step most logic advances by (two floats of a game object) are data writes
in runtime/frame_rate.c (xc2_interval_store, xc2_delta_store). The two single sites are found by their
instruction words near a known address, and the script stops when the code there is not what it expects.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recomp'))
from nso import Nso  # noqa: E402

STEP = 1.0 / 30
PAGE_STEP, PAGE_WAIT, PAGE_TICKS = 0x50, 0x48, 0x4c

# Loads of 1/30 in the interface, where it is the length of one authored frame and no frame step: a count of 30 fps
# frames turns into seconds, and the base game's symbols name the callers. ui::UIMotionData
# getMotionLength and getMotionParamDelta (main+0x67de44, 0x67e378), the delays given to ui::UIManager
# requestObjectEvent by the gf::GfMenuObj* listeners, and GfMenuObjFade's loading screens. Those seconds run out against
# fw::UpdateInfo's delta (ui::UICtrl update, ui::UIEventManager update), the measured frame time. With the step here a
# count of N frames took N rendered frames: double speed at 60 fps.
UI_FRAME_LENGTH = frozenset((
    0x3b9728, 0x3ba1cc, 0x3c2654, 0x3dee68, 0x3dfb64, 0x3e2510, 0x407b30, 0x407b74, 0x42977c, 0x42ad98, 0x42addc,
    0x45831c, 0x458624, 0x49c8f0, 0x67de44, 0x67e378,
))

# btl::ButtonChallenge::Update, 3.0.1 main+0x1d0c4: `fmul s8, s0, s1` is delta * 30, sent to
# gf::GfMenuObjButtonChallenge2 setSpeedFactor as the rings' ui::UICtrl speed. ui::UICtrl update already multiplies
# its speed by the delta, so above 30 fps the rings would run slower by the same ratio. fmov s8, #1.0: the 30 fps value.
SPEED_FACTOR = (0x1d0c4, 0x1E210808, 0x1E2E1008)
WAITS = 27


def adrp(pc, target, rd):
    imm = (target >> 12) - (pc >> 12)
    imm &= 0x1FFFFF
    return 0x90000000 | (imm & 3) << 29 | (imm >> 2) << 5 | rd


def ldr_s(rt, rn, off):
    return 0xBD400000 | (off // 4) << 10 | rn << 5 | rt


def adrp_target(pc, w):
    imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    return ((pc >> 12) + imm) << 12


def writes_reg(w, rd):
    """A conservative test: an instruction whose low five bits name rd and that is not a store or a compare."""
    if (w & 31) != rd:
        return False
    store = (w & 0x3B400000) == 0x39000000 or (w & 0x3A400000) == 0x28000000   # STR (imm) / STP
    compare = (w & 0x7F20001F) == 0x6B00001F or (w & 0x7F00001F) == 0x7100001F
    return not store and not compare


def step_sites(img, text_end, const_at):
    page, lo = const_at & ~0xFFF, const_at & 0xFFF
    sites = []
    for a in range(0, text_end, 4):
        w = struct.unpack_from('<I', img, a)[0]
        if (w & 0xFFC00000) != 0xBD400000 or ((w >> 10) & 0xFFF) * 4 != lo:
            continue
        rn, rt = (w >> 5) & 31, w & 31
        for b in range(a - 4, max(a - 0x400, 0), -4):
            v = struct.unpack_from('<I', img, b)[0]
            if (v & 0x9F000000) == 0x90000000 and (v & 31) == rn:
                if adrp_target(b, v) == page:
                    sites.append((a, w, [('page', rn), ldr_s(rt, rn, PAGE_STEP), adrp(a, page, rn)]))
                break
            if writes_reg(v, rn):
                break
    return sites


def wait_sites(img, text_end):
    """gf::GfMenuSequence<T, N>::wait, one instance per menu class: the first call copies the wait in frames to a
    counter (`ldr w8, [x19, #from]; str w8, [x19, #to]; mov w8, #1; mov w0, wzr; strb w8, [x19, #flag]`, then to the
    epilogue) and later calls count it down once a frame. The store becomes frames / (30 / frame rate), rounded: patch
    page +0x4c is 1 at 30 fps and in cutscenes. Only w8, x9 and s0-s2 change, all dead until the function returns."""
    sites = []
    for a in range(0, text_end - 20, 4):
        w = struct.unpack_from('<5I', img, a)
        if ((w[0] & 0xFFC003FF) != 0xB9400268 or (w[1] & 0xFFC003FF) != 0xB9000268 or w[2] != 0x320003E8
                or w[3] != 0x2A1F03E0 or (w[4] & 0xFFC003FF) != 0x39000268):
            continue
        sites.append((a + 4, w[1], [
            ('page', 9), ldr_s(0, 9, PAGE_TICKS),
            0x1E230101,   # ucvtf s1, w8
            0x1E201821,   # fdiv s1, s1, s0
            0x1E2C1002,   # fmov s2, #0.5
            0x1E222821,   # fadd s1, s1, s2
            0x1E390028,   # fcvtzu w8, s1
            w[1],
        ]))
    return sites


def expect(img, a, words, what):
    have = struct.unpack_from(f'<{len(words)}I', img, a)
    if list(have) != words:
        sys.exit(f'fps_sites_xc2: {what} at main+{a:#x} is not the expected code; another game version?')


def main():
    n = Nso(sys.argv[1])
    img, text_end = n.image, n.text[0] + n.text[1]
    hits = [i for i in range(n.rodata[0], n.rodata[0] + n.rodata[1], 4) if struct.unpack_from('<f', img, i)[0] ==
            struct.unpack('<f', struct.pack('<f', STEP))[0]]
    sites = []
    for c in hits:
        sites += step_sites(img, text_end, c)
    if not sites:
        sys.exit('fps_sites_xc2: no loads of 1/30')
    missing = UI_FRAME_LENGTH - {a for a, _, _ in sites}
    if missing:
        sys.exit(f'fps_sites_xc2: {sorted(map(hex, missing))} are not loads of 1/30; another game version?')
    sites = [site for site in sites if site[0] not in UI_FRAME_LENGTH]
    waits = wait_sites(img, text_end)
    if len(waits) != WAITS:
        sys.exit(f'fps_sites_xc2: {len(waits)} menu sequence waits, expected {WAITS}; another game version?')
    expect(img, SPEED_FACTOR[0], [SPEED_FACTOR[1]], 'the button challenge speed factor')
    # The frame wait, 3.0.1 main+0x6ab168: fmul s0, s0, s10 ; fcmp s0, s8 ; b.pl (the loop); x8 is dead there
    wait = 0x6ab168
    expect(img, wait, [0x1E2A0800, 0x1E282000], 'the frame wait')
    # The frame-time getter, 3.0.1 main+0x6a3710: ldp x29, x30, [sp, #0x10] ; ldp x20, x19, [sp], #0x20 ; ret
    getter = 0x6a3710
    expect(img, getter, [0xA9417BFD, 0xA8C24FF4, 0xD65F03C0], 'the frame-time getter')
    print('# XC2 3.0.1 60 fps (tools/fps_sites_xc2.py; NOTES.md "60 fps"). Generated from the game\'s main.')
    print('set xc360 XC2_FPS60 1')
    for a, w, repl in sites + waits:
        words = ' '.join(f'@page:x{r[1]}' if isinstance(r, tuple) else f'{r:08x}' for r in repl)
        print(f'site xc360 main {a:x} {w:08x} {words}')
    print(f'site xc360 main {wait:x} 1e2a0800 @page:x8 {ldr_s(0, 8, PAGE_WAIT):08x}')
    print(f'site xc360 main {getter:x} a9417bfd @page:x8 {ldr_s(0, 8, PAGE_STEP):08x} a9417bfd')
    print(f'site xc360 main {SPEED_FACTOR[0]:x} {SPEED_FACTOR[1]:08x} {SPEED_FACTOR[2]:08x}')
    print('include fixes-upd.txt   # the game fixes, kept by hand')
    print(f'# {len(sites)} step loads, {len(waits)} menu waits', file=sys.stderr)


if __name__ == '__main__':
    main()

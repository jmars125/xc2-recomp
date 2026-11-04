r"""Find the sites where XC2's main sets its render size and applies its render scale, and print them as the sets
size and scale of a patch table (recomp/patches.py).

    .venv\Scripts\python tools\fps_sites_xc2.py build\extracted\upd\exefs\main > recomp\patches-upd.txt
    .venv\Scripts\python tools\aspect_sites_xc2.py build\extracted\upd\exefs\main >> recomp\patches-upd.txt
    .venv\Scripts\python tools\size_sites_xc2.py build\extracted\upd\exefs\main [--no-gate] >> recomp\patches-upd.txt
    python3 tools\size_sites_xc2.py --selftest

The render size. XC2 draws its picture into the two window textures (colour and depth) that
grlib::CGLibDisplay::setup builds at 1280x720, docked and handheld alike (the dynamic resolution scales the scene
below that, never above): `movz w21, #1280 ; movz w22, #720` into two callee-saved registers (1.0.0 main+0x7a81c0,
setup+0x118; 3.0.1 main+0x700640), each passed as w1 / w2 to the texture builder's size call through a GOT-loaded NVN
proc (`mov x0, sp ; mov w1, w21 ; mov w2, w22 ; blr x8`), once per texture. The viewport and DevGraph's render size
(+0x230 / +0x234, which the aspect sites divide) follow the textures. The names are from Glitxhhh's xc2-decomp
(https://github.com/Glitxhhh/xc2-decomp), whose 1.0.0 main keeps its symbols; every update is stripped. The community
resolution mods overwrite the two immediates: emoose's 2.0.2 1080p patch (2.0.2 main+0x6ffcac / +0x6ffcb0,
https://gist.github.com/emoose/93a81ff4944933cafe64160a91f2acbe) and Fl4sh_'s "2560x1440 v2.1.0" (2.1.0 main+0x6ffdc0 /
+0x6ffdc4, https://github.com/Fl4sh9174/Switch-Emulator-Ultrawide-FPS-Mods). emoose notes that of the six or so
places that use 1280x720 only this one has an effect, and that a larger size breaks the map and some cutscene
effects in the emulators. The set size replaces each movz with `adrp x<d>, <patch page> ; ldr w<d>, [x<d>, #slot]`
(+0x68 the width, +0x6c the height, u32): the destination register is free to hold the page address, and the load
zero-extends as the movz did. runtime/resolution.c res_init stores XC2_OUTPUT_RES there and switches the set on when
it is not 1280x720. The other 1280 / 720 pairs (the interface canvas ml::WorkRoot::getWidth / getHeight and
DevGraph's root getters, the layout, the movie player, the title loader) are listed as INFO and left alone.

The pixel memory budget. grlib::CGLibManager::deviceInit (1.0.0 main+0x790bec, 3.0.1 main+0x6f4ee4) fills a
CGLibMemHandle::ArgMemInfo with constants and calls CGLibMemHandle::setup, which carves the region GLIBTOP out of the
game's heap and the regions GLIBCNT, GLIBDEF and GLIBPXL out of it; GLIBPXL, the render targets' memory, takes the
second u32 of the struct, 0x16a00000 (362 MiB) in 3.0.1 and 0x15600000 in 1.0.0, written as the top half of one
`movz x9, #0x16a0, lsl #48 ; movk x9, #0x280, lsl #16 ; str x9, [sp, #8]` (3.0.1 main+0x6f4f74, 1.0.0 main+0x790c84,
x8 there). The display's targets at 1280x720 take about 80 MiB of it, so 3840x1080 (4.5x) still fits and 5120x1440
(8x) does not: the game then has no GLIBPXL (its creation prints mlStackTrace and the first allocation from it fails).
The set size replaces that movz with `adrp x<r>, <patch page> ; ldr x<r>, [x<r>, #0x78]`: the movk after it still
puts the first u32 in place, and the page's u64 holds the budget in its top half, which res_init grows with the pixel
count and adds to the application pool as well (res_heap_extra_bytes, runtime/memory.c mem_init).

The graphic region. CGLibMemHandle::setup does not carve GLIBTOP out of the heap directly: its parent is
ml::MlMem::getGraphicMem(), a region of its own that ml::WorkRootMem::initialize mallocs at the size nnMain writes into
ml::WorkRootParam, a constant 512 MiB in every version read (`orr w8, wzr, #0x20000000 ; ... ; stp xzr, x8, [sp, #a]`,
1.0.0 main+0x6a0474, 3.0.1 main+0x6421c4, after the product region's 0x8c400000 and the debug region's 0xd800000). So a
GLIBPXL past about 400 MiB has no room whatever the pool and the budget say, and GLIBTOP's creation fails. The set size
replaces that orr with `adrp x<r>, <patch page> ; ldr w<r>, [x<r>, #0x80]`, where res_init stores 512 MiB plus what the
budget grew by; the load zero-extends as the orr did and the register is free to hold the page address.

The render scale. The game's dynamic resolution (lib_nx.ini: red_sclX / red_sclY the docked scale, red_hdsclX / Y
the handheld one, red_Auto the automatic stepping; the file lives inside bf2.ard, not loose in the RomFS, its path
string is 3.0.1 main+0x9ab4d5) ends in ml::DrPixlPostParm::isReductionBuffer(const DrCalcGpuCost *, bool, int width,
int height) (1.0.0 main+0x85c970, 3.0.1 main+0x7a13ec): the scale pair, the ini's values times the automatic factors
or the GPU-cost controller's pair, is multiplied by 100.0 (an f32 constant loaded by adrp + ldr), truncated to a
whole percent, and the scene is width * percent / 100 rounded up to a multiple of 8. The set scale replaces each of
the two fmul by that constant (1.0.0 main+0x85ca94 / +0x85ca9c, 3.0.1 main+0x7a1510 / +0x7a1518) with
`adrp x8, <patch page> ; ldr s<d>, [x8, #0x70] ; adrp x8, <the constant's page>`, the form of fps_sites_xc2.py: both
percents come from the page (+0x70, f32) and x8 holds what it held. res_init stores 100 there when the set size is on
(the picture is drawn at its size) and XC2_RENDER_SCALE's percentage when one is given; otherwise the set stays off
and the game keeps its own dynamic resolution. rsc-pl's 3.0.0 "All-in-One Graphics Pack" (GBAtemp, "Xenoblade
Chronicles 2 Graphics Settings" thread, post #742) rewrites the ldr of that constant at 3.0.0 main+0x7a150c to a 200.0
one for its supersampling and redirects the lib_nx.ini path string (3.0.0 main+0x9ab4d6) to a loose file for its
"Disable Resolution Scaling"; 3.0.1 holds the same code at the same address.

Patch page slot map (the page is the first 4 KiB after main's image; the runtime owns its contents):
  +0x40 .. +0x53  xc360 (frame_rate.c): vsync period, rate, frame wait, ticks, step
  +0x60, +0x64    aspect (resolution.c res_init): f32 output width / height and height / width
  +0x68           size: u32 render width (resolution.c res_init)
  +0x6c           size: u32 render height
  +0x70           scale: f32 render scale in percent (100 = the render size)
  +0x78           size: u64, the pixel memory budget (GLIBPXL) in the top 32 bits, the low 32 zero
  +0x80           size: u32, the graphic region (ml::WorkRootParam, the parent of GLIBTOP)
  +0x84 .. +0x9f  reserved for the sets of this file (+0xa0 and up: the interface sets)

How the sites are found. The size site: `movz w<a>, #1280` right before `movz w<b>, #720`, a and b callee-saved
(x19 .. x28) and distinct, followed within 8 instructions by `mov w1, w<a> ; mov w2, w<b>` and a blr, and once more
by the same three within 0x100 bytes (the second texture); a main with two such places stops the script. The budget
site: `movz x<r>, #imm, lsl #48` with the immediate between 0x1000 and 0x4000 (256 MiB to 1 GiB), right before
`movk x<r>, #imm, lsl #16`, with `str x<r>, [sp, #8]`, the struct's first constant (movz w, #0x280, lsl #16) and a
call within 40 instructions; one such place at most. The graphic region site: `movz w<r>, #0x8c40, lsl #16 ; stp xzr,
x<r>, [sp, #a] ; movz w<r>, #0xd80, lsl #16 ; stp xzr, x<r>, [sp, #a + 0x10] ; orr w<r>, wzr, #0x20000000` with
`stp xzr, x<r>, [sp, #a + 0x20]` within 3 instructions; one such place at most. The scale
sites: a load of the f32 100.0 (adrp x<n> ; ldr s<p>, [x<n>, #lo]) followed within 4 instructions by
`fmul s<x>, s<x>, s<p>` and `fmul s<y>, s<y>, s<p>` with x and y distinct, each converted by fcvtzu within the next 8
instructions, and the f32 0.01 loaded within 24; a main with other than one such place stops the script. A 100.0
load with two such fmul that fails a later test is listed as INFO (the game's many percent computations are not). KNOWN
holds the mods' sites and the ones this script found and that were read in the disassembly; when the scanned main is
one of those versions the result is checked against them. When main keeps its symbols (1.0.0) the size site is
checked to lie in grlib::CGLibDisplay::setup, the budget site in grlib::CGLibManager::deviceInit and the scale sites
in ml::DrPixlPostParm::isReductionBuffer, whose callers are named.

The version gate is aspect_sites_xc2.py's: the build id names 1.0.0, 2.0.2, 2.1.0, 3.0.0 or 3.0.1, or main holds
the 3.0.1 constants NOTES.md "60 fps" names; another main stops the script unless --no-gate. --selftest runs the
scanner over a synthetic image that holds the size site, the budget site, the scale sites, a pair into argument
registers (a size pair), a pair without the texture calls (INFO) and a 100.0 load with one fmul (no site), and checks
the sites, the words, the
KNOWN comparison and the symbol check, with recomp/patches.py parsing and checking the result as gen.py would.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recomp'))
from aspect_sites_xc2 import (BUILD_IDS, Image, adrp, adrp_target, bl, f32, gate, is_adrp, is_branch, is_ldr_s_imm,  # noqa: E402
                              is_movz, ldr_s, ldr_w, movz_w, writes_reg)

SIZE_SET, SIZE_ENV = 'size', 'XC2_RENDER_RES'
SCALE_SET, SCALE_ENV = 'scale', 'XC2_FIXED_SCALE'
SLOT_W, SLOT_H, SLOT_SCALE, SLOT_BUDGET, SLOT_GRAPHIC = 0x68, 0x6c, 0x70, 0x78, 0x80
BUDGET_MIN, BUDGET_MAX = 0x1000, 0x4000   # the movz immediate (lsl #48): a budget of 256 MiB to 1 GiB
BUDGET_NEAR = 40                          # instructions around the movz for the struct's other constants
WIDTH, HEIGHT = 1280, 720
PERCENT = f32(100.0)          # 0x42c80000
HUNDREDTH = f32(0.01)         # 0x3c23d70a
BACK_LIMIT = 0x400            # how far back an adrp is looked for (bytes), as in fps_sites_xc2.py
CALL_LIMIT = 8                # instructions from the movz pair to its first use as w1 / w2
SECOND_LIMIT = 0x100          # bytes to the second use (the second texture)
PAIR_NEAR = 0x80              # bytes: a 1280 and a 720 this close are one INFO pair
SETUP = '_ZN5grlib12CGLibDisplay5setupEP9NVNdevice'
DEVICE_INIT = '_ZN5grlib12CGLibManager10deviceInitEv'
NN_MAIN = 'nnMain'
ORR_GRAPHIC = 0x320303E0      # orr w0, wzr, #0x20000000; | the register
REDUCTION = '_ZN2ml14DrPixlPostParm17isReductionBufferEPKNS_13DrCalcGpuCostEbii'
# (width movz, height movz), the budget movz and (fmul of the width scale, fmul of the height scale) per version,
# text offsets
KNOWN = {'2.0.2': {'size': (0x6ffcac, 0x6ffcb0), 'budget': None, 'scale': None, 'graphic': None},     # emoose's 1080p patch
         '2.1.0': {'size': (0x6ffdc0, 0x6ffdc4), 'budget': None, 'scale': None, 'graphic': None},     # Fl4sh_'s "2560x1440 v2.1.0"
         # 1.0.0: this script's result (2026-11-03), read in the disassembly: grlib::CGLibDisplay::setup+0x118,
         # grlib::CGLibManager::deviceInit+0x98 and ml::DrPixlPostParm::isReductionBuffer+0x124 / +0x12c
         '1.0.0': {'size': (0x7a81c0, 0x7a81c4), 'budget': 0x790c84, 'scale': (0x85ca94, 0x85ca9c), 'graphic': 0x6a0474},
         '3.0.0': {'size': None, 'budget': None, 'scale': (0x7a1510, 0x7a1518), 'graphic': None},     # the fmul after rsc-pl's ldr at 0x7a150c
         # 3.0.1 (stripped): the same shapes, the size site being the 2.1.0 one plus the +0x880 drift
         '3.0.1': {'size': (0x700640, 0x700644), 'budget': 0x6f4f74, 'scale': (0x7a1510, 0x7a1518), 'graphic': 0x6421c4}}


# ---- encoders and decoders the aspect finder lacks
def mov_w(rd, rm):              # mov w<rd>, w<rm> = orr w<rd>, wzr, w<rm>
    return 0x2A0003E0 | rm << 16 | rd


def blr(rn):
    return 0xD63F0000 | rn << 5


def fmul_s(rd, rn, rm):
    return 0x1E200800 | rm << 16 | rn << 5 | rd


def fcvtzu_w(rd, rn):
    return 0x1E390000 | rn << 5 | rd


def movz_x(rd, imm16, hw):
    return 0xD2800000 | hw << 21 | imm16 << 5 | rd


def movk_x(rd, imm16, hw):
    return 0xF2800000 | hw << 21 | imm16 << 5 | rd


def ldr_x(rt, rn, off):
    return 0xF9400000 | (off // 8) << 10 | rn << 5 | rt


def str_x_sp8(rt):              # str x<rt>, [sp, #8]
    return 0xF90007E0 | rt


def is_mov_w(w):
    return (w & 0xFFE0FFE0) == 0x2A0003E0


def is_movz_x_hw(w, hw):        # movz x<d>, #imm16, lsl #(16 * hw)
    return (w & 0xFFE00000) == 0xD2800000 | hw << 21


def is_movk_x_hw(w, hw):
    return (w & 0xFFE00000) == 0xF2800000 | hw << 21


def is_movz_w_hw1(w, imm16):    # movz w<d>, #imm16, lsl #16
    return (w & 0xFFFFFFE0) == 0x52A00000 | imm16 << 5


def is_blr(w):
    return (w & 0xFFFFFC1F) == 0xD63F0000


def is_fmul_s(w):
    return (w & 0xFFE0FC00) == 0x1E200800


def is_fcvtzu_w(w):
    return (w & 0xFFFFFC00) == 0x1E390000


def movz_imm(w):
    """The 16-bit immediate of a 32-bit movz without a shift, else None."""
    return (w >> 5) & 0xFFFF if is_movz(w) and (w >> 21) & 3 == 0 and not w & 0x80000000 else None


def constant_load(img, a):
    """(register, page) when a is `ldr s, [x<n>, #lo]` whose x<n> an adrp set within BACK_LIMIT: the loaded word's
    address is page + lo; None otherwise."""
    w = img.word(a)
    if not is_ldr_s_imm(w):
        return None
    rn = (w >> 5) & 31
    for b in range(a - 4, max(a - BACK_LIMIT, img.text[0]) - 4, -4):
        v = img.word(b)
        if is_adrp(v) and (v & 31) == rn:
            return rn, adrp_target(b, v)
        if writes_reg(v, rn):
            return None
    return None


# ---- the size site
def uses_pair(img, a, ra, rb, limit):
    """The address of the blr that `mov w1, w<ra> ; mov w2, w<rb>` feed, the moves within limit instructions after
    a and the blr within 4 after them, else None."""
    end = min(a + 4 * limit, img.text[0] + img.text[1])
    for b in img.text_range(a, end):
        if img.word(b) == mov_w(1, ra) and b + 4 < end and img.word(b + 4) == mov_w(2, rb):
            for c in img.text_range(b + 8, min(b + 8 + 16, img.text[0] + img.text[1])):
                if is_blr(img.word(c)):
                    return c
                if is_branch(img.word(c)):
                    break
            return None
    return None


def size_site(img):
    """([(address, word, replacement)] of the width and height movz, the blr addresses) of the display setup, and the
    INFO lines: the pairs that are not it."""
    sites, info = [], []
    for a in img.text_range():
        w, v = img.word(a), img.word(a + 4) if a + 4 < img.text[0] + img.text[1] else 0
        if movz_imm(w) != WIDTH or movz_imm(v) != HEIGHT:
            continue
        ra, rb = w & 31, v & 31
        if not (19 <= ra <= 28 and 19 <= rb <= 28) or ra == rb:   # arguments of a call: listed among the size pairs
            continue
        first = uses_pair(img, a + 8, ra, rb, CALL_LIMIT)
        second = uses_pair(img, first + 4, ra, rb, SECOND_LIMIT // 4) if first else None
        if not first or not second:
            info.append((a, f'movz w{ra}, #1280 ; movz w{rb}, #720: {"no" if not first else "one"} texture size call '
                            '(mov w1 / w2 and blr) follows, not the display'))
            continue
        sites.append(([(a, w, [('page', ra), ldr_w(ra, ra, SLOT_W)]), (a + 4, v, [('page', rb), ldr_w(rb, rb, SLOT_H)])],
                      (first, second)))
    return sites, info


def size_pairs(img):
    """[(address, what)]: every place a movz of 1280 and one of 720 lie within PAIR_NEAR bytes, the start of the
    interface fit, as INFO."""
    found = [(a, movz_imm(img.word(a))) for a in img.text_range() if movz_imm(img.word(a)) in (WIDTH, HEIGHT)]
    out = []
    for i, (a, v) in enumerate(found):
        if v != WIDTH:
            continue
        near = [(abs(b - a), b) for b, u in found[max(0, i - 8):i + 9] if u == HEIGHT and abs(b - a) <= PAIR_NEAR]
        if near:
            _, b = min(near)
            out.append((min(a, b), f'1280 (movz w{img.word(a) & 31}) at main+{a:#x} and 720 (movz w{img.word(b) & 31}) '
                                   f'at main+{b:#x}'))
    return sorted(set(out))


# ---- the budget site
def budget_site(img):
    """[(address, word, replacement, budget bytes)] for the movz that holds the pixel memory budget (one at most), and
    the INFO lines for the lsl #48 movz that fail the other tests."""
    sites, info = [], []
    end = img.text[0] + img.text[1]
    for a in img.text_range():
        w = img.word(a)
        if not is_movz_x_hw(w, 3):
            continue
        imm, r = (w >> 5) & 0xFFFF, w & 31
        if not BUDGET_MIN <= imm <= BUDGET_MAX or a + 4 >= end:
            continue
        v = img.word(a + 4)
        if not (is_movk_x_hw(v, 1) and v & 31 == r):
            continue
        near = [img.word(b) for b in img.text_range(max(a - 4 * BUDGET_NEAR, img.text[0]), min(a + 4 * BUDGET_NEAR, end))]
        have = {'store': any(u == str_x_sp8(r) for u in near), 'def': any(is_movz_w_hw1(u, 0x280) for u in near),
                'call': any(u >> 26 == 0x25 for u in near)}
        if all(have.values()):
            sites.append((a, w, [('page', r), ldr_x(r, r, SLOT_BUDGET)], imm << 16))
        else:
            info.append((a, f'movz x{r}, #{imm:#x}, lsl #48 ; movk: missing ' + ', '.join(k for k, ok in have.items() if not ok)
                            + ' of the memory struct fill, not the budget'))
    return sites, info


# ---- the graphic region site
def stp_xzr_sp(rt2, off):       # stp xzr, x<rt2>, [sp, #off]
    return 0xA90003FF | (off // 8) << 15 | rt2 << 10


def graphic_site(img):
    """[(address, word, replacement, bytes)] for the orr of the graphic region's size in nnMain's ml::WorkRootParam
    fill (one at most)."""
    sites = []
    end = img.text[0] + img.text[1]
    for a in img.text_range(img.text[0], end - 0x20):
        w = img.word(a)
        r = w & 31
        if w != 0x52A00000 | 0x8c40 << 5 | r:   # movz w<r>, #0x8c40, lsl #16: the product region
            continue
        v = img.word(a + 4)
        if v & 0xFFC003FF != 0xA90003FF or (v >> 10) & 31 != r:
            continue
        off = ((v >> 15) & 0x7F) * 8
        if img.word(a + 8) != 0x52A00000 | 0xd80 << 5 | r or img.word(a + 12) != stp_xzr_sp(r, off + 0x10):
            continue
        g = a + 16
        if img.word(g) != ORR_GRAPHIC | r:
            continue
        if any(img.word(b) == stp_xzr_sp(r, off + 0x20) for b in img.text_range(g + 4, g + 16)):
            sites.append((g, img.word(g), [('page', r), ldr_w(r, r, SLOT_GRAPHIC)], 0x2000 << 16))
    return sites


# ---- the scale sites
def scale_sites(img):
    """[(fmul address, word, replacement)] for the two fmul by the f32 100.0 that make the whole percents, and the
    INFO lines for the 100.0 loads that are not followed by them."""
    sites, info = [], []
    end = img.text[0] + img.text[1]
    for a in img.text_range():
        c = constant_load(img, a)
        if not c:
            continue
        rn, page = c
        at = page + ((img.word(a) >> 10) & 0xFFF) * 4
        if not img.in_image(at) or img.word(at) != PERCENT:
            continue
        p = img.word(a) & 31
        muls = [(b, img.word(b)) for b in img.text_range(a + 4, min(a + 4 * 5, end))
                if is_fmul_s(img.word(b)) and (img.word(b) >> 16) & 31 == p and (img.word(b) >> 5) & 31 == img.word(b) & 31]
        if len(muls) != 2 or muls[0][1] & 31 == muls[1][1] & 31:   # the game's many percent computations: not listed
            continue
        regs = {m[1] & 31 for m in muls}
        conv = {img.word(b) >> 5 & 31 for b in img.text_range(muls[1][0] + 4, min(muls[1][0] + 4 * 9, end))
                if is_fcvtzu_w(img.word(b))}
        if not regs <= conv:
            info.append((a, f'load of 100.0 into s{p}: the products are not converted to integers, not the scale'))
            continue
        hundredth = any(constant_load(img, b) and img.in_image(constant_load(img, b)[1] + ((img.word(b) >> 10) & 0xFFF) * 4)
                        and img.word(constant_load(img, b)[1] + ((img.word(b) >> 10) & 0xFFF) * 4) == HUNDREDTH
                        for b in img.text_range(a + 4, min(a + 4 * 25, end)))
        if not hundredth:
            info.append((a, f'load of 100.0 into s{p}: no 0.01 within 24 instructions, not the scale'))
            continue
        for b, w in muls:
            sites.append((b, w, [('page', rn), ldr_s(w & 31, rn, SLOT_SCALE), adrp(b, page, rn)]))
    return sites, info


# ---- the known sites and the symbols
def check_known(version, size, budget, scale, graphic=(), known=KNOWN):
    """[(text, ok)] comparing the scan with the sites recorded for this version."""
    k = known.get(version)
    if not k:
        return []
    out = []
    have = tuple(s[0] for s in size[0][0]) if size else None
    if k['size']:
        ok = have == k['size']
        out.append((f'{"agree" if ok else "disagree"} size main+{k["size"][0]:#x}'
                    + ('' if ok else f': the list has it, the scanner has {"none" if not have else f"main+{have[0]:#x}"}'), ok))
    have = budget[0][0] if budget else None
    if k['budget']:
        ok = have == k['budget']
        out.append((f'{"agree" if ok else "disagree"} budget main+{k["budget"]:#x}'
                    + ('' if ok else f': the scanner has {"none" if have is None else f"main+{have:#x}"}'), ok))
    have = tuple(s[0] for s in scale)
    if k['scale']:
        ok = have == k['scale']
        out.append((f'{"agree" if ok else "disagree"} scale main+{k["scale"][0]:#x} / main+{k["scale"][1]:#x}'
                    + ('' if ok else f': the scanner has {", ".join(f"main+{a:#x}" for a in have) or "none"}'), ok))
    have = graphic[0][0] if graphic else None
    if k.get('graphic'):
        ok = have == k['graphic']
        out.append((f'{"agree" if ok else "disagree"} graphic main+{k["graphic"]:#x}'
                    + ('' if ok else f': the scanner has {"none" if have is None else f"main+{have:#x}"}'), ok))
    return out


def check_symbols(img, size, budget, scale, graphic=()):
    """When main keeps its symbols: whether the sites lie in the functions the names say, and who calls the scale's."""
    if not img.symbolic:
        return []
    lines = []
    if size:
        a = size[0][0][0][0]
        lines.append(f'size site main+{a:#x} lies in {img.name_of(a)}'
                     + ('' if img.name_of(a).startswith(SETUP + '+') else f', NOT in {SETUP}'))
    for a, _, _, _ in budget:
        lines.append(f'budget site main+{a:#x} lies in {img.name_of(a)}'
                     + ('' if img.name_of(a).startswith(DEVICE_INIT + '+') else f', NOT in {DEVICE_INIT}'))
    for a, _, _ in scale:
        lines.append(f'scale site main+{a:#x} lies in {img.name_of(a)}'
                     + ('' if img.name_of(a).startswith(REDUCTION + '+') else f', NOT in {REDUCTION}'))
    for a, _, _, _ in graphic:
        lines.append(f'graphic site main+{a:#x} lies in {img.name_of(a)}'
                     + ('' if img.name_of(a).startswith(NN_MAIN + '+') else f', NOT in {NN_MAIN}'))
    if REDUCTION in img.syms:
        f = img.syms[REDUCTION][0]
        callers = sorted({img.name_of(b) for b in img.text_range()
                          if img.word(b) >> 26 == 0x25 and b + ((((img.word(b) & 0x3FFFFFF) ^ 0x2000000) - 0x2000000) << 2) == f})
        lines.append(f'{REDUCTION} is called from {", ".join(callers) or "nowhere (inlined)"}')
    return lines


# ---- output
def emit(size, budget, scale, version, out=sys.stdout, graphic=()):
    print(f'# XC2 {version} render size and scale (tools/size_sites_xc2.py; NOTES.md "Known gaps"). Generated from the '
          'game\'s main.', file=out)
    if size or budget or graphic:
        print(f'set {SIZE_SET} {SIZE_ENV} 1', file=out)
        for a, w, repl in (size[0][0] if size else []) + [(a, w, repl) for a, w, repl, _ in list(budget) + list(graphic)]:
            print(f'site {SIZE_SET} main {a:x} {w:08x} ' + ' '.join(word(r) for r in repl), file=out)
    if scale:
        print(f'set {SCALE_SET} {SCALE_ENV} 1', file=out)
        for a, w, repl in sorted(scale):
            print(f'site {SCALE_SET} main {a:x} {w:08x} ' + ' '.join(word(r) for r in repl), file=out)


def word(r):
    return f'@page:x{r[1]}' if isinstance(r, tuple) else f'{r:08x}'


def report(img, size, size_info, budget, budget_info, scale, scale_info, pairs, known, symbols, out=sys.stderr, graphic=()):
    if size:
        (w, h), (first, second) = size[0]
        print(f'site main+{w[0]:#x} {img.name_of(w[0])}: render width, movz w{w[1] & 31} -> +{SLOT_W:#x}; height at '
              f'main+{h[0]:#x}, movz w{h[1] & 31} -> +{SLOT_H:#x}; the texture size calls at main+{first:#x} and '
              f'main+{second:#x}', file=out)
    for a, w, repl, bytes_ in budget:
        print(f'site main+{a:#x} {img.name_of(a)}: pixel memory budget {bytes_ >> 20} MiB ({bytes_:#x}), movz x{w & 31} -> '
              f'+{SLOT_BUDGET:#x}', file=out)
    for a, w, repl, bytes_ in graphic:
        print(f'site main+{a:#x} {img.name_of(a)}: graphic region {bytes_ >> 20} MiB, orr w{w & 31} -> +{SLOT_GRAPHIC:#x}', file=out)
    for a, w, repl in sorted(scale):
        print(f'site main+{a:#x} {img.name_of(a)}: render scale, fmul s{w & 31} by 100.0 -> +{SLOT_SCALE:#x} through '
              f'x{repl[0][1]}', file=out)
    for a, what in sorted(size_info + budget_info + scale_info):
        print(f'INFO main+{a:#x} {img.name_of(a)}: {what}', file=out)
    patched = {s[0][0][0] for s in size}
    for a, what in pairs:
        if a not in patched:
            print(f'INFO size pair main+{a:#x} {img.name_of(a)}: {what}', file=out)
    for text, _ in known:
        print(f'known: {text}', file=out)
    for text in symbols:
        print(f'symbols: {text}', file=out)
    print(f'# {"1 size site" if size else "no size site"}, {len(budget)} budget site, {len(graphic)} graphic site, {len(scale)} scale sites, '
          f'{len(size_info) + len(budget_info) + len(scale_info)} left unpatched, {len(pairs)} size pairs', file=out)


# ---- self test
def selftest():
    import tempfile
    import patches
    NOP, RET = 0xD503201F, 0xD65F03C0
    STP, LDP = 0xA9BE7BFD, 0xA8C27BFD   # stp / ldp x29, x30, [sp, #-0x20]! / [sp], #0x20
    rodata_base = 0x4000
    rod = bytearray(0x100)
    struct.pack_into('<III', rod, 0x10, PERCENT, HUNDREDTH, f32(0.1))
    code = [NOP] * 0x10
    # the display setup: GOT loads, the pair, the two texture size calls
    f1 = len(code) * 4
    code += [STP, 0x910003FD, 0xF9400108, movz_w(21, WIDTH, 0), movz_w(22, HEIGHT, 0), 0x910003E0, mov_w(1, 21),
             mov_w(2, 22), blr(8)]
    p1 = f1 + 12
    c1 = len(code) * 4 - 4
    code += [0xF9400388, 0x910003E0, blr(8), 0xB900FC00, 0xF9400368, 0x910003E0, mov_w(1, 21), mov_w(2, 22), blr(8)]
    c2 = len(code) * 4 - 4
    code += [LDP, RET]
    # the root getters: 1280 and 720 into w0, INFO only
    g1 = len(code) * 4
    code += [movz_w(0, WIDTH, 0), RET, movz_w(0, HEIGHT, 0), RET]
    # an adjacent pair into callee-saved registers with no texture calls: INFO
    g2 = len(code) * 4
    code += [STP, movz_w(19, WIDTH, 0), movz_w(20, HEIGHT, 0), 0x0B140260, LDP, RET]   # add w0, w19, w20
    # the reduction: ldr s2 / s1 from the object, the 100.0 load, two fmul, fcvtzu, the 0.01 load
    f3 = len(code) * 4
    code += [STP, ldr_s(2, 19, 0xfb8), ldr_s(1, 19, 0xfbc), adrp(len(code) * 4 + 12, rodata_base, 8), ldr_s(0, 8, 0x10),
             fmul_s(2, 2, 0), 0x1E220284, fmul_s(1, 1, 0), fcvtzu_w(8, 2), fcvtzu_w(9, 1), 0x1E220102]   # scvtf s4, w20 ; scvtf s2, w8
    s1, s2 = f3 + 20, f3 + 28
    code += [adrp(len(code) * 4, rodata_base, 8), 0x1E220123, ldr_s(1, 8, 0x14), fmul_s(2, 2, 1), LDP, RET]
    # a 100.0 load with one fmul: no site
    f4 = len(code) * 4
    code += [STP, adrp(len(code) * 4 + 4, rodata_base, 9), ldr_s(0, 9, 0x10), fmul_s(3, 3, 0), LDP, RET]
    # the device init filling the memory struct: the budget movz, the movk, the store, the other constants, the call
    f6 = len(code) * 4
    code += [STP, 0x52A05008, 0xB9001BE8, 0x52A03808, 0xB90017E8, movz_x(9, 0x16a0, 3), movk_x(9, 0x280, 1), str_x_sp8(9),
             0x910023E0, bl(len(code) * 4 + 36, f1), LDP, RET]   # mov w8, #0x2800000 ; str w8, [sp, #0x18] ; mov w8, #0x1c00000 ; ...
    b1 = f6 + 20
    # a lsl #48 movz + movk without the struct fill, beyond the window around the fill: INFO
    code += [NOP] * BUDGET_NEAR
    code += [STP, movz_x(10, 0x2000, 3), movk_x(10, 0x100, 1), str_x_sp8(10), LDP, RET]
    b2 = len(code) * 4 - 20
    # nnMain's ml::WorkRootParam fill: the three region sizes, the third being the graphic region
    f7 = len(code) * 4
    code += [STP, 0x52A00000 | 0x8c40 << 5 | 8, stp_xzr_sp(8, 0x20), 0x52A00000 | 0xd80 << 5 | 8, stp_xzr_sp(8, 0x30),
             ORR_GRAPHIC | 8, 0x910063E0, stp_xzr_sp(8, 0x40), LDP, RET]   # add x0, sp, #0x18
    g1g = f7 + 20
    # the same orr without the two region sizes before it: no site
    code += [ORR_GRAPHIC | 8, stp_xzr_sp(8, 0x40), RET]
    text = b''.join(struct.pack('<I', w) for w in code)
    image = bytearray(rodata_base + len(rod))
    image[:len(text)] = text
    image[rodata_base:rodata_base + len(rod)] = rod
    syms = [(SETUP, 0, 1, f1, g1 - f1), ('getters', 0, 1, g1, g2 - g1), ('decoy', 0, 1, g2, f3 - g2),
            (REDUCTION, 0, 1, f3, f4 - f3), ('one_mul', 0, 1, f4, f6 - f4), (DEVICE_INIT, 0, 1, f6, b2 - 4 - f6),
            ('decoy_budget', 0, 1, b2 - 4, f7 - b2 + 4), (NN_MAIN, 0, 1, f7, g1g + 20 - f7)]
    syms += [(f'pad_{i}', 0, 1, 0x3000 + 4 * i, 4) for i in range(1000)]   # a table large enough to count as kept
    img = Image(image, (0, len(text)), (rodata_base, len(rod)), (rodata_base + len(rod), 0), syms=syms,
                build_id=BUILD_IDS['3.0.1'].upper() + '0' * 48)
    assert gate(img) == '3.0.1'
    assert is_mov_w(mov_w(1, 21)) and mov_w(1, 21) == 0x2A1503E1 and blr(8) == 0xD63F0100
    assert fmul_s(2, 2, 0) == 0x1E200842 and fmul_s(1, 1, 0) == 0x1E200821 and is_fcvtzu_w(0x1E390048)
    assert ldr_w(21, 21, SLOT_W) == 0xB9406AB5 and ldr_w(22, 22, SLOT_H) == 0xB9406ED6 and ldr_s(2, 8, SLOT_SCALE) == 0xBD407102
    size, size_info = size_site(img)
    assert len(size) == 1 and [s[0] for s in size[0][0]] == [p1, p1 + 4] and size[0][1] == (c1, c2), (size, size_info)
    assert size[0][0][0][2] == [('page', 21), ldr_w(21, 21, SLOT_W)] and size[0][0][1][2] == [('page', 22), ldr_w(22, 22, SLOT_H)]
    assert [a for a, _ in size_info] == [g2 + 4] and 'no texture' in size_info[0][1], size_info
    pairs = size_pairs(img)
    assert [a for a, _ in pairs] == [p1, g1, g2 + 4], pairs
    budget, budget_info = budget_site(img)
    assert [(b[0], b[1], b[2], b[3]) for b in budget] == [(b1, movz_x(9, 0x16a0, 3), [('page', 9), ldr_x(9, 9, SLOT_BUDGET)], 0x16a00000)], (budget, budget_info)
    assert ldr_x(9, 9, SLOT_BUDGET) == 0xF9403D29 and [a for a, _ in budget_info] == [b2] and 'missing def, call' in budget_info[0][1], budget_info
    graphic = graphic_site(img)
    assert graphic == [(g1g, ORR_GRAPHIC | 8, [('page', 8), ldr_w(8, 8, SLOT_GRAPHIC)], 0x20000000)], graphic
    assert ldr_w(8, 8, SLOT_GRAPHIC) == 0xB9408108
    scale, scale_info = scale_sites(img)
    assert [s[0] for s in scale] == [s1, s2], ([hex(s[0]) for s in scale], scale_info)
    assert scale[0][1:] == (fmul_s(2, 2, 0), [('page', 8), ldr_s(2, 8, SLOT_SCALE), adrp(s1, rodata_base, 8)]), scale[0]
    assert scale[1][1:] == (fmul_s(1, 1, 0), [('page', 8), ldr_s(1, 8, SLOT_SCALE), adrp(s2, rodata_base, 8)]), scale[1]
    assert adrp_target(s1, scale[0][2][2]) == rodata_base, 'x8 is pointed back at the constant page'
    assert scale_info == [], scale_info
    symbols = check_symbols(img, size, budget, scale, graphic)
    assert len(symbols) == 6 and all('NOT' not in s for s in symbols) and symbols[5].endswith('nowhere (inlined)'), symbols
    stripped = Image(image, img.text, img.rodata, img.data)
    assert not stripped.symbolic and check_symbols(stripped, size, budget, scale) == []
    assert size_site(stripped)[0] == size and scale_sites(stripped)[0] == scale and budget_site(stripped)[0] == budget
    assert graphic_site(stripped) == graphic
    known = {'3.0.1': {'size': (p1, p1 + 4), 'budget': b1, 'scale': (s1, s2 + 4), 'graphic': g1g},
             '1.0.0': {'size': None, 'budget': b2, 'scale': (s1, s2), 'graphic': None}}
    result = check_known('3.0.1', size, budget, scale, graphic, known)
    assert [ok for _, ok in result] == [True, True, False, True] and result[2][0].startswith('disagree scale'), result
    assert check_known('1.0.0', size, budget, scale, graphic, known) == [(f'disagree budget main+{b2:#x}: the scanner has main+{b1:#x}', False),
                                                                        (f'agree scale main+{s1:#x} / main+{s2:#x}', True)]
    assert check_known('2.1.0', [], [], [], (), known) == [] and check_known('3.0.1', [], [], [], (), known)[0][0].endswith('has none')
    # The emitted table parses, resolves @page and passes the original-word check, as gen.py --patches runs it.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'patches.txt'
        with open(path, 'w') as f:
            emit(size, budget, scale, 'selftest', f, graphic)
        mods = [('main', 0x10000000, len(image)), ('sdk', 0x10400000, 0x1000)]
        table = patches.load(path, mods)
        assert table.sets == [(SIZE_SET, SIZE_ENV, 1), (SCALE_SET, SCALE_ENV, 1)]
        assert sorted(table.sites['main']) == sorted([p1, p1 + 4, b1, g1g, s1, s2])

        class Mod:
            base = 0x10000000
            def in_text(self, a): return img.in_text(a - self.base)
            def word(self, a): return img.word(a - self.base)
        patches.check(table, Mod(), 'main')
        resolved = table.for_module('main', 0x10000000)
        assert all(adrp_target(a, words[0]) == table.page for a, (_, words) in resolved.items()), 'adrp to the page'
        assert resolved[0x10000000 + p1][1] == [adrp(0x10000000 + p1, table.page, 21), ldr_w(21, 21, SLOT_W)]
        assert resolved[0x10000000 + s1][1][2] == adrp(s1, rodata_base, 8), 'the restore adrp is the site\'s own'
        assert resolved[0x10000000 + b1][1] == [adrp(0x10000000 + b1, table.page, 9), ldr_x(9, 9, SLOT_BUDGET)]
        bad = Image(bytes(image[:p1]) + b'\0\0\0\0' + bytes(image[p1 + 4:]), img.text, img.rodata, img.data)
        try:
            class BadMod(Mod):
                def word(self, a): return bad.word(a - self.base)
            patches.check(table, BadMod(), 'main')
        except patches.PatchError:
            pass
        else:
            raise AssertionError('a changed original word must fail the check')
    print('size_sites_xc2: selftest ok (the size site with its two texture calls, the budget site, the graphic region site, 2 scale sites, 2 '
          'unpatched, 3 size pairs, known-site and symbol checks)')


def main():
    args = sys.argv[1:]
    if args == ['--selftest']:
        return selftest()
    no_gate = '--no-gate' in args
    args = [a for a in args if a != '--no-gate']
    if len(args) != 1:
        sys.exit('usage: size_sites_xc2.py <main NSO> [--no-gate] | --selftest')
    img = Image.from_nso(args[0])
    version = gate(img)
    if not version and not no_gate:
        sys.exit(f'size_sites_xc2: main (build id {img.build_id[:16]}) is none of {", ".join(BUILD_IDS)} and holds none '
                 'of the 3.0.1 constants NOTES.md names; another game version? --no-gate scans it anyway')
    size, size_info = size_site(img)
    budget, budget_info = budget_site(img)
    scale, scale_info = scale_sites(img)
    graphic = graphic_site(img)
    if len(graphic) > 1:
        sys.exit('size_sites_xc2: more than one graphic region in main: ' + ', '.join(f'main+{g[0]:#x}' for g in graphic))
    if len(size) > 1:
        sys.exit('size_sites_xc2: more than one display setup in main: ' + ', '.join(f'main+{s[0][0][0]:#x}' for s in size))
    if len(budget) > 1:
        sys.exit('size_sites_xc2: more than one pixel memory budget in main: ' + ', '.join(f'main+{b[0]:#x}' for b in budget))
    if len(scale) not in (0, 2):
        sys.exit(f'size_sites_xc2: {len(scale)} scale sites in main, not the two of one isReductionBuffer')
    if not size and not scale:
        sys.exit('size_sites_xc2: neither the render size nor the render scale site in main')
    pairs = size_pairs(img)
    known = check_known(version, size, budget, scale, graphic)
    symbols = check_symbols(img, size, budget, scale, graphic)
    emit(size, budget, scale, version or f'unknown version, build id {img.build_id[:16]} (--no-gate)', graphic=graphic)
    report(img, size, size_info, budget, budget_info, scale, scale_info, pairs, known, symbols, graphic=graphic)


if __name__ == '__main__':
    main()

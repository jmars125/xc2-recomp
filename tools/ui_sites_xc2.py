r"""Find the sites that place XC2's interface in its picture and print them as the set ui of a patch table
(recomp/patches.py).

    .venv\Scripts\python tools\fps_sites_xc2.py build\extracted\upd\exefs\main > recomp\patches-upd.txt
    .venv\Scripts\python tools\aspect_sites_xc2.py build\extracted\upd\exefs\main >> recomp\patches-upd.txt
    .venv\Scripts\python tools\size_sites_xc2.py build\extracted\upd\exefs\main >> recomp\patches-upd.txt
    .venv\Scripts\python tools\ui_sites_xc2.py build\extracted\upd\exefs\main [--no-gate] >> recomp\patches-upd.txt
    python3 tools\ui_sites_xc2.py --selftest

How the interface reaches the picture. layer::LayerShdManager holds the canvas (+0x550 / +0x554, f32, 1280 x 720: the
constructor's constants) and, per frame, layer::LayerShdManager::beginShader reads the render size from the draw info
(+0x550 / +0x554, u32) and derives everything else from it: the screen size (+0x530 / +0x534, what
layer::LayerManager::getScreenWidth returns), one scale per axis (+0x55c = width / 1280, +0x560 = height / 720) and
their minimum (+0x558), the one scale the interface is drawn at, so it keeps its proportions. Positions are kept as
canvas x / screen width; a transform uniform maps them with x_ndc = x * 2 * (+0x558) - 1 (+0x564; for example
layer::LayerObj::updateDefUniformBlock), and the viewport covers the whole target from its origin. At 3840x1080 the
scale is 1.5 and the canvas pixel x lands at x_ndc = x / 1280 - 1, that is on pixel 1.5 * x: the canvas fills x 0..1920
of 3840, at its own proportions, with nothing to centre it. The title screen matches: the canvas centre (640) falls
on 25% of the picture.

The fix makes the interface's whole view of the picture the 16:9 rectangle inside it, which is how the same code
runs at 1920x1080 in the emoose and Fl4sh_ resolution mods (tools/size_sites_xc2.py):

- beginShader reads the rectangle's size from the patch page instead of the render size (+0xa0 / +0xa4), so every
  value above, the mesh, font and filter uniforms built from them and the layer's own perspective (+0x4a0) are those
  of a 16:9 screen.
- Each viewport the manager sets on the main target starts at the rectangle's origin (+0xa8 / +0xac): beginShader and
  resetViewPort (the whole rectangle, x and y stored as one u64), setViewPort and setShaderMaskMode (a canvas rect
  scaled by +0x558, then the origin added; the mask only when no layout render target is bound, its +0x360 being
  zero, since a render target's own origin is its corner). layer::LayerShdManager::selectViewPort takes no patch: no
  code calls it in 1.0.0 and 3.0.1 has no copy of it.
- grlib::CGLibRenderTarget::setRenderTarget sets a viewport over its whole target, and at 16:9 the rectangle is that
  same viewport, so resetViewPort returns early unless its flag +0x528 says a viewport was changed. A filter or a
  memory object rebinds the main target between objects (layer::LayerObjTopFilter::finalRender,
  layer::LayerObjTopMemObj::setupRender), so resetViewPort loads 1 for the flag and sets the rectangle every time.
  Setting it again is harmless: with the flag clear the fields it writes already hold those values.
- endShader restores the whole picture for whatever draws next, and does so even when the flag is clear, since the
  rectangle is no longer the whole picture (+0xc0 / +0xc4 for the sizes it would have computed).
- What this leaves: a filter object (layer::LayerObjTopFilter) still samples the main target through UV uniforms that
  take the rectangle for the whole target (layer::LayerFilterObj::calcMatDef), so a blurred backdrop shows the picture
  squeezed into the rectangle; the shader that reads them was not read, so no fix is guessed here.
- Positions projected from the 3D world are scaled to land where the wider view shows them. gf::util::getScreenPos
  (damage numbers through btl::BattleCharacter::NotifyDamage, name plates through gf::GfMenuFieldPosAdapter and
  gf::GfMenuPosAdapter) maps the camera's x_ndc to the 1280 canvas; on a wide picture that x_ndc spans the picture,
  not the rectangle, so x_ndc and y_ndc are multiplied by render size / rectangle size (+0xb0 / +0xb4). Layer objects
  placed in world space (layer::LayerObjUtil::createWorldMatrixUniform) use the product beginShader computes of the
  draw info's view and projection; the same factors go into the projection's first two columns before that product
  (+0xb0 .. +0xbc, a 4-float vector).

The patch page, f32 unless said otherwise (the page's lower slots belong to the other sets; +0x80 .. +0x9f are held
for the effects work):
  +0xa0 u32 rectangle width    +0xa4 u32 rectangle height
  +0xa8 rectangle x            +0xac rectangle y
  +0xb0 render w / rect w      +0xb4 render h / rect h     +0xb8 1.0     +0xbc 1.0
  +0xc0 render width           +0xc4 render height
runtime/resolution.c res_init stores them and switches the set on when the render size's shape differs from 16:9.

Registers. x30 is the scratch register wherever the function has saved it (the aspect set's rule); getScreenPos is a
leaf, and x9 and s7 are dead at both its sites (their last reads lie before the first site). s5 and s6 are unused in
setViewPort and setShaderMaskMode; v0 and v1 are overwritten right after the projection site.

How the sites are found: fixed words around each site, listed in the find_* functions; the functions are the same
instruction for instruction in 1.0.0 and 3.0.1 (compared in the disassembly, the adrp and bl targets and one GOT and
constant offset per function aside). A shape that matches no place or two places stops the script. When main keeps
its symbols (1.0.0) each site is checked to lie in the function its name says. KNOWN holds the 1.0.0 and 3.0.1
results and is compared when one of those versions is scanned. --selftest runs the finders over a synthetic image and
parses and checks the emitted table as gen.py does.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recomp'))
from aspect_sites_xc2 import BUILD_IDS, Image, adrp, adrp_target, bl, gate, ldr_s, movz_w  # noqa: E402

SET, ENV = 'ui', 'XC2_UI_CENTER'
SLOT_SIZE_W, SLOT_SIZE_H = 0xa0, 0xa4
SLOT_ORIGIN_X, SLOT_ORIGIN_Y = 0xa8, 0xac
SLOT_FACTOR_X, SLOT_FACTOR_Y = 0xb0, 0xb4
SLOT_RENDER_W, SLOT_RENDER_H = 0xc0, 0xc4
XZR, SP = 31, 31
SUB_SP_30 = 0xD100C3FF               # sub sp, sp, #0x30
NEAR_BEGIN = 0x700                 # bytes from beginShader's size load past its last site, short of endShader
NEAR_RESET = 0x70                  # bytes from resetViewPort's flag to its origin
NEAR_END = 0x40                    # bytes from endShader's flag to its sizes
PROJECTION = (0x420, 0x430, 0x440, 0x450)   # the rows of the manager's copy of the projection
BEGIN = '_ZN5layer15LayerShdManager11beginShaderEPKN2ml15IDrDrawWorkInfoE'
RESET = '_ZN5layer15LayerShdManager13resetViewPortEv'
END = '_ZN5layer15LayerShdManager9endShaderEPKN2ml15IDrDrawWorkInfoE'
VIEW = '_ZN5layer15LayerShdManager11setViewPortEPNS_20LayerResViewPortInfoE'
MASK = '_ZN5layer15LayerShdManager17setShaderMaskModeEPKNS_18LayerObjTopMaskObjE'
SCREEN_POS = '_ZN2gf4util12getScreenPosERN2mm4Vec3ERKS2_'
# The sites per version, text offsets: this script's result, read in the disassembly (2026-11-04). 1.0.0 keeps its
# symbols, so its addresses also carry the names checked by check_symbols.
KNOWN = {'1.0.0': (0x5d8410, 0x5d8428, 0x910278, 0x910284, 0x9103ac, 0x910924, 0x910948, 0x9109a0, 0x9109d4, 0x910a08,
                   0x910a10, 0x910c24, 0x910c28, 0x910d04, 0x910d08),
         '3.0.1': (0x571118, 0x571130, 0x8391f4, 0x839200, 0x839328, 0x8398a0, 0x8398c4, 0x83991c, 0x839950, 0x839984,
                   0x83998c, 0x839ae8, 0x839aec, 0x839bc8, 0x839bcc)}


# ---- encoders the aspect finder lacks
def str_s(rt, rn, off):
    return 0xBD000000 | (off // 4) << 10 | rn << 5 | rt


def ldr_x(rt, rn, off):
    return 0xF9400000 | (off // 8) << 10 | rn << 5 | rt


def str_x(rt, rn, off):
    return 0xF9000000 | (off // 8) << 10 | rn << 5 | rt


def ldr_q(rt, rn, off):
    return 0x3DC00000 | (off // 16) << 10 | rn << 5 | rt


def str_q(rt, rn, off):
    return 0x3D800000 | (off // 16) << 10 | rn << 5 | rt


def ldrb_w(rt, rn, off):
    return 0x39400000 | off << 10 | rn << 5 | rt


def ldp_s(rt, rt2, rn, off):
    return 0x2D400000 | ((off // 4) & 0x7F) << 15 | rt2 << 10 | rn << 5 | rt


def stp_s(rt, rt2, rn, off):
    return 0x2D000000 | ((off // 4) & 0x7F) << 15 | rt2 << 10 | rn << 5 | rt


def fmul_s(rd, rn, rm):
    return 0x1E200800 | rm << 16 | rn << 5 | rd


def fadd_s(rd, rn, rm):
    return 0x1E202800 | rm << 16 | rn << 5 | rd


def fsub_s(rd, rn, rm):
    return 0x1E203800 | rm << 16 | rn << 5 | rd


def fmul_4s(rd, rn, rm):
    return 0x6E20DC00 | rm << 16 | rn << 5 | rd


def ucvtf_s(rd, rn):            # the scalar form: the source is a float register holding an integer
    return 0x7E21D800 | rn << 5 | rd


def scvtf_s(rd, rn):
    return 0x5E21D800 | rn << 5 | rd


def fmov_w_s(rd, rn):           # fmov s<rd>, w<rn>
    return 0x1E270000 | rn << 5 | rd


def ldr_d(rt, rn, off):
    return 0xFD400000 | (off // 8) << 10 | rn << 5 | rt


def cmeq_d_zero(rd, rn):        # all ones when the register is zero, no flags (a patched site may not write them)
    return 0x5EE09800 | rn << 5 | rd


def and_8b(rd, rn, rm):
    return 0x0E201C00 | rm << 16 | rn << 5 | rd


def mov_x(rd, rm):              # mov x<rd>, x<rm> = orr x<rd>, xzr, x<rm>
    return 0xAA0003E0 | rm << 16 | rd


def add_x(rd, rn, imm):
    return 0x91000000 | imm << 10 | rn << 5 | rd


def is_cbz_w8(w):
    return w & 0xFF00001F == 0x34000008


def is_bl(w):
    return w >> 26 == 0x25


# ---- the shapes
def matches(img, a, words):
    return a >= img.text[0] and a + 4 * len(words) <= img.text[0] + img.text[1] and \
        all(img.word(a + 4 * i) == w for i, w in enumerate(words))


def scan(img, words, start=None, end=None):
    """The addresses in [start, end) where the words stand in a row. Only the text words equal to the first are tried,
    so a scan of the whole text is one pass."""
    return [a for a in img.text_range(start, end) if img.word(a) == words[0] and matches(img, a, words)]


def one(found, what):
    if len(found) != 1:
        sys.exit(f'ui_sites_xc2: {what}: {len(found)} matches in main, not one')
    return found[0]


def page_load(load):
    return [('page', 30), load]


def origin_store():
    """x and y of the rectangle's origin, stored over the `str xzr, [sp, #8]` of a viewport struct."""
    return page_load(ldr_x(30, 30, SLOT_ORIGIN_X)) + [str_x(30, SP, 8)]


def find_begin(img):
    """beginShader: its two loads of the render size, the end of the second copy into the manager's matrices, and the
    origin of its viewport."""
    a = one(scan(img, [ldr_s(0, 20, 0x550), ucvtf_s(2, 0), str_s(2, 19, 0x530), ldr_s(0, 20, 0x554)]), 'beginShader')
    h = a + 0xc
    # add x0, x19, #0x420 ; add x1, x20, #0x150 ; mov w2, #0x40 ; bl memcpy ; ldr s0, [x19, #0x3e0] ; ldr s1, [x19, #0x420]:
    # the copy of the projection, then the first reads of the view * projection product
    p = one(scan(img, [ldr_s(0, 19, 0x3e0), ldr_s(1, 19, 0x420)], a, a + NEAR_BEGIN), 'beginShader projection')
    if not is_bl(img.word(p - 4)) or img.word(p - 0x10) != add_x(0, 19, 0x420) or img.word(p - 0xc) != add_x(1, 20, 0x150):
        sys.exit(f'ui_sites_xc2: main+{p:#x} does not follow the copy of the projection')
    o = one(scan(img, [str_x(XZR, SP, 8), stp_s(0, 1, SP, 0x10), str_x(8, SP, 0x18)], a, a + NEAR_BEGIN), 'beginShader viewport')
    proj = page_load(ldr_q(1, 30, SLOT_FACTOR_X))
    for row in PROJECTION:
        proj += [ldr_q(0, 19, row), fmul_4s(0, 0, 1), str_q(0, 19, row)]
    proj.append(img.word(p))
    return [(a, img.word(a), page_load(ldr_s(0, 30, SLOT_SIZE_W)), 'render width -> rectangle width'),
            (h, img.word(h), page_load(ldr_s(0, 30, SLOT_SIZE_H)), 'render height -> rectangle height'),
            (p, img.word(p), proj, 'the projection\'s x and y scaled to the rectangle'),
            (o, img.word(o), origin_store(), 'whole-rectangle viewport: origin')]


def find_reset(img):
    # ldrb w8, [x0, #0x528] ; cbz w8 ; sub sp, sp, #0x30: the flag test before the frame
    a = one([f for f in scan(img, [ldrb_w(8, 0, 0x528)]) if is_cbz_w8(img.word(f + 4)) and img.word(f + 8) == SUB_SP_30], 'resetViewPort')
    o = one(scan(img, [str_x(XZR, SP, 8)], a, a + NEAR_RESET), 'resetViewPort viewport')
    return [(a, img.word(a), [movz_w(8, 1, 0)], 'always set the rectangle (a rebind leaves the whole target)'),
            (o, img.word(o), origin_store(), 'whole-rectangle viewport: origin')]


def find_end(img):
    # mov x19, x0 ; bl setMainFrameBuffer ; ldrb w8, [x19, #0x528] ; cbz w8: beginShader's tail has the same flag test
    # after a run of mov w<n>, #imm
    a = one([f for f in scan(img, [ldrb_w(8, 19, 0x528)]) if is_cbz_w8(img.word(f + 4)) and is_bl(img.word(f - 4))
             and img.word(f - 8) == mov_x(19, 0)], 'endShader')
    h = one(scan(img, [fmul_s(1, 2, 1), fmov_w_s(2, 9), fmul_s(0, 2, 0)], a, a + NEAR_END), 'endShader sizes')
    w = h + 8
    return [(a, img.word(a), [movz_w(8, 1, 0)], 'always restore the whole picture'),
            (h, img.word(h), page_load(ldr_s(1, 30, SLOT_RENDER_H)), 'restored viewport: render height'),
            (w, img.word(w), page_load(ldr_s(0, 30, SLOT_RENDER_W)), 'restored viewport: render width')]


def add_origin(mul, axis_reg, slot):
    return [mul] + page_load(ldr_s(5, 30, slot)) + [fadd_s(axis_reg, axis_reg, 5)]


def find_view(img):
    a = one(scan(img, [fmul_s(1, 0, 1), ldp_s(3, 4, 20, 0), fmul_s(3, 0, 3), fmul_s(4, 0, 4)]), 'setViewPort')
    x, y = a + 8, a + 12
    return [(x, img.word(x), add_origin(img.word(x), 3, SLOT_ORIGIN_X), 'canvas rect: x + origin'),
            (y, img.word(y), add_origin(img.word(y), 4, SLOT_ORIGIN_Y), 'canvas rect: y + origin')]


def add_origin_unless_target(mul, axis_reg, slot):
    """The mask may be drawn while a layout's render target (the manager's +0x360) is bound, whose origin is its corner."""
    return [mul] + page_load(ldr_s(5, 30, slot)) + [ldr_d(6, 0, 0x360), cmeq_d_zero(6, 6), and_8b(5, 5, 6),
                                                    fadd_s(axis_reg, axis_reg, 5)]


def find_mask(img):
    a = one(scan(img, [ldr_s(0, 0, 0x558), ldr_s(1, 1, 0x260), ldr_s(2, 1, 0x264), ldr_s(3, 1, 0x258), ldr_s(4, 1, 0x25c),
                       fmul_s(1, 0, 1), fmul_s(3, 0, 3), fmul_s(4, 0, 4)]), 'setShaderMaskMode')
    x, y = a + 0x18, a + 0x1c
    return [(x, img.word(x), add_origin_unless_target(img.word(x), 3, SLOT_ORIGIN_X), 'mask rect: x + origin'),
            (y, img.word(y), add_origin_unless_target(img.word(y), 4, SLOT_ORIGIN_Y), 'mask rect: y + origin')]


def find_screen_pos(img):
    a = one([f for f in scan(img, [fmul_s(4, 5, 3), ldr_s(5, 8, 0), fadd_s(4, 4, 2), scvtf_s(5, 5)])
             if matches(img, f + 0x18, [fmul_s(1, 1, 3), fsub_s(1, 2, 1)])], 'gf::util::getScreenPos')
    y = a + 0x18
    return [(a, img.word(a), [img.word(a), ('page', 9), ldr_s(7, 9, SLOT_FACTOR_X), fmul_s(4, 4, 7)], 'world position: x_ndc * factor'),
            (y, img.word(y), [img.word(y), ('page', 9), ldr_s(7, 9, SLOT_FACTOR_Y), fmul_s(1, 1, 7)], 'world position: y_ndc * factor')]


def find_all(img):
    return sorted(find_screen_pos(img) + find_begin(img) + find_reset(img) + find_end(img) + find_view(img) + find_mask(img))


# ---- checks and output
def check_known(version, sites, known=KNOWN):
    k = known.get(version)
    if k is None:
        return []
    have = tuple(s[0] for s in sites)
    if have == k:
        return [(f'agree: the {len(k)} sites of {version}', True)]
    return [(f'disagree {version}: only the scan has ' + ' '.join(f'main+{a:#x}' for a in have if a not in k) + '; only the list has '
             + ' '.join(f'main+{a:#x}' for a in k if a not in have), False)]


def check_symbols(img, sites, by=None):
    """When main keeps its symbols: whether each site lies in the function the names say."""
    if not img.symbolic:
        return []
    want = by or [SCREEN_POS, SCREEN_POS, BEGIN, BEGIN, BEGIN, BEGIN, RESET, RESET, END, END, END, VIEW, VIEW, MASK, MASK]
    return [f'site main+{s[0]:#x} lies in {img.name_of(s[0])}' + ('' if img.name_of(s[0]).startswith(n + '+') else f', NOT in {n}')
            for s, n in zip(sites, want)]


def word(r):
    return f'@page:x{r[1]}' if isinstance(r, tuple) else f'{r:08x}'


def emit(sites, version, out=sys.stdout):
    print(f'# XC2 {version} interface placement (tools/ui_sites_xc2.py; NOTES.md "Resolution and ultrawide"). Generated '
          'from the game\'s main.', file=out)
    print(f'set {SET} {ENV} 1', file=out)
    for a, w, repl, _ in sites:
        print(f'site {SET} main {a:x} {w:08x} ' + ' '.join(word(r) for r in repl), file=out)


def report(img, sites, known, symbols, out=sys.stderr):
    for a, _, repl, what in sites:
        print(f'site main+{a:#x} {img.name_of(a)}: {what} ({len(repl)} words)', file=out)
    for text, _ in known:
        print(f'known: {text}', file=out)
    for text in symbols:
        print(f'symbols: {text}', file=out)
    print(f'# {len(sites)} ui sites', file=out)


# ---- self test
def selftest():
    import tempfile
    import patches
    NOP, RET = 0xD503201F, 0xD65F03C0
    SAVE, BL0 = 0xA9BE7BFD, bl(0, 0)
    code = [NOP] * 8

    def add(words):
        at = len(code) * 4
        code.extend(words)
        return at

    screen = add([fmul_s(4, 5, 3), ldr_s(5, 8, 0), fadd_s(4, 4, 2), scvtf_s(5, 5), fmul_s(5, 5, 6), NOP, fmul_s(1, 1, 3),
                  fsub_s(1, 2, 1), RET])
    add([fmul_s(4, 5, 3), ldr_s(5, 8, 0x550), fadd_s(4, 4, 2), RET])   # the manager's own unused copy of getScreenPos
    begin = add([SAVE, ldr_s(0, 20, 0x550), ucvtf_s(2, 0), str_s(2, 19, 0x530), ldr_s(0, 20, 0x554)])
    add([add_x(0, 19, 0x420), add_x(1, 20, 0x150), NOP, BL0])
    proj = add([ldr_s(0, 19, 0x3e0), ldr_s(1, 19, 0x420), NOP])
    add([str_x(9, SP, 0x20)])
    origin1 = add([str_x(XZR, SP, 8), stp_s(0, 1, SP, 0x10), str_x(8, SP, 0x18), BL0, RET])
    # beginShader's tail tests the flag the way endShader does, after other calls
    add([movz_w(6, 3, 0), BL0, ldrb_w(8, 19, 0x528), 0x34000048, RET])
    reset = add([ldrb_w(8, 0, 0x528), 0x340000E8, SUB_SP_30, SAVE, NOP])
    origin2 = add([str_x(XZR, SP, 8), str_x(8, SP, 0x18), stp_s(0, 1, SP, 0x10), BL0, RET])
    end = add([SAVE, mov_x(19, 0), BL0, ldrb_w(8, 19, 0x528), 0x34000128, NOP])
    end_h = add([fmul_s(1, 2, 1), fmov_w_s(2, 9), fmul_s(0, 2, 0), BL0, RET])
    view = add([SAVE, ldr_s(0, 19, 0x558), fmul_s(1, 0, 1), ldp_s(3, 4, 20, 0), fmul_s(3, 0, 3), fmul_s(4, 0, 4), RET])
    add([fmul_s(1, 0, 1), ldp_s(3, 4, 1, 0), fmul_s(3, 0, 3), fmul_s(4, 0, 4), RET])   # selectViewPort: x1, not x20
    mask = add([SAVE, ldr_s(0, 0, 0x558), ldr_s(1, 1, 0x260), ldr_s(2, 1, 0x264), ldr_s(3, 1, 0x258), ldr_s(4, 1, 0x25c),
                fmul_s(1, 0, 1), fmul_s(3, 0, 3), fmul_s(4, 0, 4), RET])
    tail = len(code) * 4
    image = bytearray(0x4000)
    image[:tail] = b''.join(struct.pack('<I', w) for w in code)
    syms = [(SCREEN_POS, 0, 1, screen, 0x24), (BEGIN, 0, 1, begin, reset - begin), (RESET, 0, 1, reset, end - reset),
            (END, 0, 1, end, view - end), (VIEW, 0, 1, view, mask - view), (MASK, 0, 1, mask, tail - mask)]
    syms += [(f'pad_{i}', 0, 1, 0x3000 + 4 * i, 4) for i in range(1000)]
    img = Image(image, (0, tail), (tail, 0), (tail, 0), syms=syms, build_id=BUILD_IDS['3.0.1'].upper() + '0' * 48)
    assert gate(img) == '3.0.1'
    # encoders against the game's words read in the disassembly
    assert ldr_s(0, 20, 0x550) == 0xBD455280 and ldr_s(0, 20, 0x554) == 0xBD455680 and str_x(XZR, SP, 8) == 0xF90007FF
    assert ldr_s(0, 19, 0x3e0) == 0xBD43E260
    sites = find_all(img)
    want = (screen, screen + 0x18, begin + 4, begin + 0x10, proj, origin1, reset, origin2, end + 0xc, end_h, end_h + 8,
            view + 0x10, view + 0x14, mask + 0x1c, mask + 0x20)
    assert tuple(s[0] for s in sites) == want, [hex(s[0]) for s in sites]
    by = dict((s[0], s) for s in sites)
    assert by[begin + 4][2] == [('page', 30), ldr_s(0, 30, SLOT_SIZE_W)] and by[reset][2] == [movz_w(8, 1, 0)]
    assert by[origin1][2] == by[origin2][2] == [('page', 30), ldr_x(30, 30, SLOT_ORIGIN_X), str_x(30, SP, 8)]
    assert by[proj][2][-1] == ldr_s(0, 19, 0x3e0) and len(by[proj][2]) == 2 + 3 * len(PROJECTION) + 1, 'the original load comes last'
    assert by[view + 0x10][2][0] == fmul_s(3, 0, 3) and by[view + 0x10][2][-1] == fadd_s(3, 3, 5)
    assert ldr_d(6, 0, 0x360) in by[mask + 0x1c][2] and by[mask + 0x20][2][2] == ldr_s(5, 30, SLOT_ORIGIN_Y)
    assert check_known('3.0.1', sites, {'3.0.1': want}) == [(f'agree: the {len(want)} sites of 3.0.1', True)]
    assert check_known('3.0.1', sites, {'3.0.1': want[:-1]})[0][1] is False and check_known('2.1.0', sites) == []
    symbols = check_symbols(img, sites)
    assert len(symbols) == len(sites) and all('NOT' not in s for s in symbols), symbols
    assert not Image(image, img.text, img.rodata, img.data).symbolic
    # a shape that appears twice stops the script
    try:
        one(scan(img, [fmul_s(1, 0, 1)]), 'twice')
    except SystemExit:
        pass
    else:
        raise AssertionError('an ambiguous shape must stop the script')
    # The emitted table parses, resolves @page and passes the original-word check, as gen.py --patches runs it.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'patches.txt'
        with open(path, 'w') as f:
            emit(sites, 'selftest', f)
        mods = [('main', 0x10000000, len(image)), ('sdk', 0x10400000, 0x1000)]
        table = patches.load(path, mods)
        assert table.sets == [(SET, ENV, 1)] and sorted(table.sites['main']) == sorted(want)

        class Mod:
            base = 0x10000000
            def in_text(self, a): return img.in_text(a - self.base)
            def word(self, a): return img.word(a - self.base)
        patches.check(table, Mod(), 'main')
        resolved = table.for_module('main', 0x10000000)
        assert adrp_target(0x10000000 + screen, resolved[0x10000000 + screen][1][1]) == table.page, 'the page after the first word'
        assert resolved[0x10000000 + origin1][1][0] == adrp(0x10000000 + origin1, table.page, 30)
    print(f'ui_sites_xc2: selftest ok ({len(sites)} sites, known-site and symbol checks, the table parsed and checked)')


def main():
    args = sys.argv[1:]
    if args == ['--selftest']:
        return selftest()
    no_gate = '--no-gate' in args
    args = [a for a in args if a != '--no-gate']
    if len(args) != 1:
        sys.exit('usage: ui_sites_xc2.py <main NSO> [--no-gate] | --selftest')
    img = Image.from_nso(args[0])
    version = gate(img)
    if not version and not no_gate:
        sys.exit(f'ui_sites_xc2: main (build id {img.build_id[:16]}) is none of {", ".join(BUILD_IDS)}; another game '
                 'version? --no-gate scans it anyway')
    sites = find_all(img)
    known = check_known(version, sites)
    if any(not ok for _, ok in known):
        sys.exit('ui_sites_xc2: ' + known[0][0])
    emit(sites, version or f'unknown version, build id {img.build_id[:16]} (--no-gate)')
    report(img, sites, known, check_symbols(img, sites))


if __name__ == '__main__':
    main()

r"""Find the sites where XC2's main computes its 16:9 aspect ratio and print them as the aspect set of a patch table
(recomp/patches.py).

    .venv\Scripts\python tools\fps_sites_xc2.py build\extracted\upd\exefs\main > recomp\patches-upd.txt
    .venv\Scripts\python tools\aspect_sites_xc2.py build\extracted\upd\exefs\main [--sizes] [--no-gate] >> recomp\patches-upd.txt
    python3 tools\aspect_sites_xc2.py --selftest

XC2 keeps no 16:9 constant for its camera: the aspect is computed at run time as render width / height
(ml::DevGraph::getAspect = getRenderW() / getRenderH(), DevGraph +0x230 and +0x234, inlined at its users). The names
come from Glitxhhh's xc2-decomp (https://github.com/Glitxhhh/xc2-decomp), whose 1.0.0 main keeps its symbols; every
update is stripped. The two community 21:9 patches for 2.1.0 both overwrite that quotient in s0: Fl4sh_'s
"21:9 Ultrawide v2.1.0" pchtxt (Fl4sh9174, https://github.com/Fl4sh9174/Switch-Emulator-Ultrawide-FPS-Mods) rewrites
three instruction slots at each of three sites (text offsets 0x7e3080, +8, +c with the slot between kept; 0x6cbfcc,
+4, +8; 0x6c2390, +4, +8) with mov w30, #lo ; movk w30, #hi, lsl #16 ; fmov s0, w30, and theboy181's "21'9" pchtxt
(https://github.com/theboy181/switch-ptchtxt-mods) rewrites 0x7e308c alone with fmov s0, #2.375. Both leave the
interface to the emulator's "stretch to window". Nothing is copied from them: the sites say what the code there is,
and the scanner looks for that shape in any version. Ghidra's names for the enclosing 2.1.0 functions are from
masterofshadow90/xenoblade2-decomp (symbols.txt, address = text offset + 0x100000).

The primary form (p):

    ldr w<a>, [x<b>, #off] ; ldr w<c>, [x<b>, #off + 4] ; scvtf s<x>, w<a> ; (an instruction) ; scvtf s<y>, w<c> ;
    fdiv s<d>, s<x>, s<y>

the division of two integers just loaded from memory (ldr, ldur or ldp w), the width at the lower offset. The patch
replaces the fdiv alone with adrp x30, <patch page> ; ldr s<d>, [x30, #slot]: a patch site replaces one instruction
with any number (recomp/patches.py), so the two scvtf stay in place and only the quotient comes from the page
(+0x60 width / height; +0x64 height / width, for a division the other way round, emitted only when one is found).
The mods' third slot needs no nop here for the same reason. x30 is the scratch register the mods use as well: a site
is patched only when the enclosing function saved x30 in its prologue (stp x29, x30, [sp, ...] or str x30, [sp, ...],
found walking back from the site without passing a ret) and restores it after the site (ldp or ldr x30 from sp before
the next ret, without passing another prologue). The compiler never allocates x30 otherwise, so x30 is dead at such a
site; a site that fails the rule is listed as INFO with the reason. The INFO list also names a division of two
converted integers that are not loaded from memory (a weaker match, for the reader).

The secondary forms, the loads of the f32 constants 16/9 (0x3fe38e39) and 9/16 (0x3f100000), in case a version holds
one for a default or a fallback:
  (a) adrp x<n>, <page> ; ... ; ldr s<t>, [x<n>, #lo]   patched as in fps_sites_xc2.py: adrp x<n>, <patch page> ;
      ldr s<t>, [x<n>, #slot] ; adrp x<n>, <page>, so x<n> holds what it held;
  (b) movz w<n>, #lo16 ; movk w<n>, #hi16, lsl #16 ; fmov s<t>, w<n>   patched at the fmov: adrp x<n>, <patch page> ;
      ldr s<t>, [x<n>, #slot] ; then the moves again, so w<n> ends as it did;
  (c) ldr s<t>, <literal> and (d) fmov s<t>, #0.5625   INFO only: no address register at the site.

Patch page slot map (the page is the first 4 KiB after main's image; the runtime owns its contents):
  +0x40 .. +0x53  xc360 (frame_rate.c xc2_rate_store, xc2_wait_store): vsync period, rate, frame wait, ticks, step
  +0x60           aspect: f32 output width / height (resolution.c res_init)
  +0x64           aspect: f32 output height / width
XC3's sets used +0 .. +0xb and +0x50 .. +0x6b; none of them exists in XC2's table, so the slots are free here.

KNOWN_SITES holds the 2.1.0 sites of the two mods, the fdiv being the last slot of each of Fl4sh_'s triples (the one
theboy181 rewrites), with the function each lies in. When the scanned main is 2.1.0 (its build id) the result is
checked against them, agree or disagree per site, and sites the mods do not have are listed as new. When main keeps
its symbols (1.0.0), the pattern is verified inside ml::DevGraph::getAspect itself and its callers are named.

--sizes: INFO only, the pairs of 1920 and 1080 (the docked render targets, which Fl4sh_ makes 2580x1080 at
2.1.0 text 0x6caff8, 0x6cb060 and 0x70a634) and of 1280 and 720 (the interface's logical size, ml::WorkRoot) used
together, as movz immediates, as f32 constants or as literals; not patched, the start of the interface fit.

The version gate: the build id names 2.0.2, 2.1.0, 3.0.0 and 3.0.1 (the ids the community patches and masagrator's
FPSLocker files carry), and 3.0.1 is also known by the constants NOTES.md "60 fps" names (the 1/30 at main+0x9b5148,
the 0.997 at main+0x9b558c); another main stops the script unless --no-gate. --selftest runs the scanner over a
synthetic image that holds each form, a function that saves x30 and one that does not, and checks the sites, the
patch words, the x30 rule and the KNOWN_SITES comparison, with recomp/patches.py parsing and checking the result as
gen.py would.
"""
import bisect
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recomp'))

ASPECT = struct.unpack('<I', struct.pack('<f', 16 / 9))[0]     # 0x3fe38e39
INVERSE = struct.unpack('<I', struct.pack('<f', 9 / 16))[0]    # 0x3f100000
SLOT_ASPECT, SLOT_INVERSE = 0x60, 0x64
SLOT = {ASPECT: SLOT_ASPECT, INVERSE: SLOT_INVERSE}
SET_NAME, SET_ENV = 'aspect', 'XC2_ASPECT'
BUILD_IDS = {'2.0.2': 'd007651bc7c6a51ed7e8f463e02ac2ef', '2.1.0': 'f77f1559371c0ec6d50e78774ac59d95',
             '3.0.0': '12a2634f01346f2156b959703c47c146', '3.0.1': '4f5c96e2d97f45ac'}   # prefixes of main's build id
LANDMARKS = {'3.0.1': [(0x9b5148, 1 / 30), (0x9b558c, 0.997)]}   # NOTES.md "60 fps": main's f32 constants
# (fdiv site, first slot of the mod's triple, enclosing function) per version, text offsets; Ghidra's FUN_ names are
# the function offsets + 0x100000.
KNOWN_SITES = {'2.1.0': {'fdiv': [(0x7e308c, 0x7e3080, 0x7e2f88), (0x6cbfd4, 0x6cbfcc, 0x6cbfa4),
                                  (0x6c2398, 0x6c2390, 0x6c2210)],
                         'sizes': [(0x6caff8, 0x6cb000), (0x6cb060, 0x6cb068), (0x70a634, 0x70a640)]}}
GET_ASPECT = '_ZN2ml8DevGraph9getAspectEv'
BACK_LIMIT = 0x400      # how far back an adrp is looked for (bytes), as in fps_sites_xc2.py
MOV_LIMIT = 16          # how many instructions back a movz / movk chain is followed
CVT_LIMIT = 6           # how many instructions back from the fdiv its scvtf are looked for
LOAD_LIMIT = 8          # how many instructions back from a scvtf its load is looked for
FUNC_LIMIT = 0x2000     # bytes walked each way for the prologue and the epilogue of the site's function
UI_SIZES = {1280: 'w', 720: 'h', 1920: 'w', 1080: 'h'}
UI_NEAR = 0x80          # bytes: a width and a height this close are one candidate


def f32(v):
    return struct.unpack('<I', struct.pack('<f', v))[0]


# ---- encoders
def adrp(pc, target, rd):
    imm = (target >> 12) - (pc >> 12)
    imm &= 0x1FFFFF
    return 0x90000000 | (imm & 3) << 29 | (imm >> 2) << 5 | rd


def ldr_s(rt, rn, off):
    return 0xBD400000 | (off // 4) << 10 | rn << 5 | rt


def ldr_w(rt, rn, off):
    return 0xB9400000 | (off // 4) << 10 | rn << 5 | rt


def ldp_w(rt1, rt2, rn, off):
    return 0x29400000 | ((off // 4) & 0x7F) << 15 | rt2 << 10 | rn << 5 | rt1


def scvtf_s(rd, rn):
    return 0x1E220000 | rn << 5 | rd


def fdiv_s(rd, rn, rm):
    return 0x1E201800 | rm << 16 | rn << 5 | rd


def movz_w(rd, imm16, hw):
    return 0x52800000 | hw << 21 | imm16 << 5 | rd


def movk_w(rd, imm16, hw):
    return 0x72800000 | hw << 21 | imm16 << 5 | rd


def fmov_s_imm(rd, imm8):
    return 0x1E201000 | imm8 << 13 | rd


def ldr_s_lit(rt, pc, target):
    return 0x1C000000 | (((target - pc) >> 2) & 0x7FFFF) << 5 | rt


def bl(pc, target):
    return 0x94000000 | ((target - pc) >> 2) & 0x3FFFFFF


STP_X29_X30_PRE_20 = 0xA9BE7BFD   # stp x29, x30, [sp, #-0x20]!
LDP_X29_X30_POST_20 = 0xA8C27BFD  # ldp x29, x30, [sp], #0x20
MOV_X29_SP = 0x910003FD
RET = 0xD65F03C0
NOP = 0xD503201F


def mov_words(rd, value):
    """The movz / movk pair (or single movz) that puts the 32-bit value into w<rd>."""
    lo, hi = value & 0xFFFF, value >> 16
    if not lo:
        return [movz_w(rd, hi, 1)]
    if not hi:
        return [movz_w(rd, lo, 0)]
    return [movz_w(rd, lo, 0), movk_w(rd, hi, 1)]


# ---- decoders
def adrp_target(pc, w):
    imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    return ((pc >> 12) + imm) << 12


def is_adrp(w):
    return (w & 0x9F000000) == 0x90000000


def is_ldr_s_imm(w):
    return (w & 0xFFC00000) == 0xBD400000


def is_ldr_s_lit(w):
    return (w & 0xFF000000) == 0x1C000000


def lit_target(pc, w):
    imm = (w >> 5) & 0x7FFFF
    if imm & (1 << 18):
        imm -= 1 << 19
    return pc + imm * 4


def is_fmov_s_w(w):
    return (w & 0xFFFFFC00) == 0x1E270000


def is_fmov_s_imm(w):
    return (w & 0xFFE01FE0) == 0x1E201000


def fmov_imm_word(imm8):
    """The f32 word an 8-bit FMOV immediate expands to (Arm ARM VFPExpandImm, single precision)."""
    b6 = (imm8 >> 6) & 1
    return (imm8 >> 7) << 31 | (b6 ^ 1) << 30 | (0x1F if b6 else 0) << 25 | ((imm8 >> 4) & 3) << 23 | (imm8 & 0xF) << 19


def is_movz(w):
    return (w & 0x7F800000) == 0x52800000


def is_movk(w):
    return (w & 0x7F800000) == 0x72800000


def is_scvtf_s(w):   # scvtf s<d>, w<n> or x<n>
    return (w & 0x7FFFFC00) == 0x1E220000


def is_fdiv_s(w):
    return (w & 0xFFE0FC00) == 0x1E201800


def is_fp_op(w):   # SIMD / FP data processing or an FP load: a possible writer of an s register
    return (w & 0x0E000000) == 0x0E000000 or (w & 0x3F400000) == 0x3D400000 or (w & 0x3F600000) == 0x3C400000


def int_load(w):
    """(rt registers, base, offset of each) of a 32-bit load from memory, or None: ldr w (imm), ldur w, ldr w (reg),
    ldp w (post, signed, pre)."""
    rt, rn = w & 31, (w >> 5) & 31
    if (w & 0xFFC00000) == 0xB9400000:
        return {rt: (rn, ((w >> 10) & 0xFFF) * 4)}
    if (w & 0xFFE00C00) == 0xB8400000:
        off = (w >> 12) & 0x1FF
        return {rt: (rn, off - 0x200 if off & 0x100 else off)}
    if (w & 0xFFE00C00) == 0xB8600800:
        return {rt: (rn, None)}
    if (w & 0xFFC00000) in (0x28C00000, 0x29400000, 0x29C00000):
        off = (w >> 15) & 0x7F
        off = (off - 0x80 if off & 0x40 else off) * 4
        return {rt: (rn, off), (w >> 10) & 31: (rn, off + 4)}
    return None


def is_ret(w):
    return (w & 0xFFFFFC1F) == 0xD65F0000


def is_branch(w):
    if w >> 26 in (0x05, 0x25):                                  # b, bl
        return True
    if (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000 or (w & 0x7E000000) == 0x36000000:
        return True                                              # b.cond, cbz / cbnz, tbz / tbnz
    return (w & 0xFFFFFC1F) in (0xD65F0000, 0xD61F0000, 0xD63F0000)   # ret, br, blr


def saves_x30(w):
    """stp x<n>, x<m>, [sp, ...] with x30 among them, or str x30, [sp, #imm]: a prologue save of the link register."""
    if (w & 0xFE400000) == 0xA8000000 and (w >> 23) & 7 and (w >> 5) & 31 == 31:
        return (w & 31) == 30 or (w >> 10) & 31 == 30
    return (w & 0xFFC003FF) == 0xF90003FE


def restores_x30(w):
    """ldp x<n>, x<m>, [sp, ...] with x30 among them, or ldr x30, [sp, #imm]."""
    if (w & 0xFE400000) == 0xA8400000 and (w >> 23) & 7 and (w >> 5) & 31 == 31:
        return (w & 31) == 30 or (w >> 10) & 31 == 30
    return (w & 0xFFC003FF) == 0xF94003FE


def writes_reg(w, rd):
    """A conservative test: an instruction whose low five bits name rd and that is not a store or a compare."""
    if (w & 31) != rd:
        return False
    store = (w & 0x3B400000) == 0x39000000 or (w & 0x3A400000) == 0x28000000   # STR (imm) / STP
    compare = (w & 0x7F20001F) == 0x6B00001F or (w & 0x7F00001F) == 0x7100001F
    return not store and not compare


# ---- the image
class Image:
    """main's bytes as 32-bit words (little-endian, as the module is), with the segment bounds, the build id and the
    symbols."""

    def __init__(self, image, text, rodata, data, syms=(), build_id=''):
        self.image = bytes(image)
        self.text, self.rodata, self.data = text, rodata, data
        self.build_id = build_id.lower()
        self.words = struct.unpack_from(f'<{len(self.image) // 4}I', self.image)
        self.syms = {s[0]: (s[3], s[4]) for s in syms if s[3] and s[2]}   # (name, info, shndx, value, size)
        funcs = sorted((a, n) for n, (a, _) in self.syms.items())
        self.func_addrs = [a for a, _ in funcs]
        self.func_names = [s for _, s in funcs]

    @classmethod
    def from_nso(cls, path):
        from nso import Nso
        n = Nso(path)
        return cls(n.image, n.text, n.rodata, n.data, n.syms, n.build_id)

    def word(self, a):
        return self.words[a >> 2]

    def in_text(self, a):
        return self.text[0] <= a < self.text[0] + self.text[1]

    def in_image(self, a):
        return 0 <= a <= len(self.image) - 4

    def name_of(self, off):
        i = bisect.bisect_right(self.func_addrs, off) - 1
        return f'{self.func_names[i]}+{off - self.func_addrs[i]:#x}' if i >= 0 else '?'

    def text_range(self, start=None, end=None):
        lo = self.text[0] if start is None else start
        hi = self.text[0] + self.text[1] if end is None else end
        return range(lo, hi, 4)


# ---- the primary form: the computed aspect
def x30_dead(img, a):
    """None when the function around a saved x30 in its prologue and restores it after a; else why not."""
    saved = False
    for b in range(a - 4, max(a - FUNC_LIMIT, img.text[0]) - 4, -4):
        w = img.word(b)
        if saves_x30(w):
            saved = True
            break
        if is_ret(w):
            return 'no save of x30 before the site (a ret comes first): x30 is live'
    if not saved:
        return f'no save of x30 within {FUNC_LIMIT:#x} bytes before the site'
    for b in img.text_range(a + 4, min(a + FUNC_LIMIT, img.text[0] + img.text[1])):
        w = img.word(b)
        if restores_x30(w):
            return None
        if is_ret(w) or saves_x30(w):
            return 'no restore of x30 between the site and the next ret or prologue: x30 is live'
    return f'no restore of x30 within {FUNC_LIMIT:#x} bytes after the site'


def scvtf_source(img, a, s):
    """(scvtf address, integer register) of the last writer of s<s> before a, when it is a scvtf; else None."""
    for b in range(a - 4, max(a - 4 * CVT_LIMIT, img.text[0]) - 4, -4):
        w = img.word(b)
        if is_branch(w):
            return None
        if (w & 31) == s and is_fp_op(w):
            return (b, (w >> 5) & 31) if is_scvtf_s(w) else None
    return None


def load_source(img, a, r):
    """(base register, offset) of the load that wrote w<r> last before a, or None (offset None: register offset)."""
    for b in range(a - 4, max(a - 4 * LOAD_LIMIT, img.text[0]) - 4, -4):
        w = img.word(b)
        if is_branch(w):
            return None
        loads = int_load(w)
        if loads and r in loads:
            return loads[r]
        if writes_reg(w, r) and not (loads and r in loads):
            return None
    return None


def computed_sites(img, lo=None, hi=None):
    """(sites, info) of the form (p) in text[lo:hi]: sites [(fdiv address, word, replacement, slot, window start,
    order)], info [(address, what)]. order: 'w/h', 'h/w', or None when the loads do not say which is which."""
    sites, info = [], []
    for a in img.text_range(lo, hi):
        w = img.word(a)
        if not is_fdiv_s(w):
            continue
        d, x, y = w & 31, (w >> 5) & 31, (w >> 16) & 31
        cx, cy = scvtf_source(img, a, x), scvtf_source(img, a, y)
        if not cx or not cy or cx[0] == cy[0]:
            continue
        lx, ly = load_source(img, cx[0], cx[1]), load_source(img, cy[0], cy[1])
        start = min(cx[0], cy[0])
        if not lx or not ly:
            info.append((a, f'fdiv s{d}, s{x}, s{y} of two converted integers (window main+{start:#x}) that are not '
                            'loaded from memory just before: a weak match, not patched'))
            continue
        order = None
        if lx[0] == ly[0] and lx[1] is not None and ly[1] is not None and lx[1] != ly[1]:
            order = 'w/h' if lx[1] < ly[1] else 'h/w'
        why = x30_dead(img, a)
        if why:
            info.append((a, f'computed aspect (fdiv s{d}, s{x}, s{y}; window main+{start:#x}; loads at x{lx[0]}+'
                            f'{lx[1]}, x{ly[0]}+{ly[1]}): not patched, {why}'))
            continue
        slot = SLOT_INVERSE if order == 'h/w' else SLOT_ASPECT
        sites.append((a, w, [('page', 30), ldr_s(d, 30, slot)], slot, start, order))
    return sites, info


# ---- the secondary forms: constant loads
def value_in_reg(img, a, rn):
    """The 32-bit value w<rn> holds at a, built by movz / movk just before, or None when it is not known."""
    parts, base = {}, None
    for b in range(a - 4, max(a - 4 * MOV_LIMIT, img.text[0]) - 4, -4):
        v = img.word(b)
        if is_branch(v):
            return None
        if (v & 31) == rn and (is_movz(v) or is_movk(v)):
            hw, imm = (v >> 21) & 3, (v >> 5) & 0xFFFF
            if hw > 1:
                return None
            parts.setdefault(hw, imm)
            if is_movz(v):
                base = hw
                break
        elif writes_reg(v, rn):
            return None
    if base is None:
        return None
    value = 0
    for hw in (0, 1):
        value |= parts.get(hw, 0) << 16 * hw
    return value


def constant_sites(img):
    """(sites, info): sites [(address, original word, replacement words, slot)] of the forms (a) and (b); info
    [(address, what)] for the unpatched forms (c) and (d)."""
    hits = {}   # address of a constant word anywhere in the image -> its value
    for a in range(0, len(img.image) - 3, 4):
        w = img.word(a)
        if w in SLOT:
            hits[a] = w
    by_lo = {}   # (a) grouped by the ldr's offset, so each constant costs one dictionary lookup
    for a in img.text_range():
        w = img.word(a)
        if is_ldr_s_imm(w):
            by_lo.setdefault(((w >> 10) & 0xFFF) * 4, []).append(a)
    sites, info = [], []
    for const_at, value in sorted(hits.items()):
        page, lo = const_at & ~0xFFF, const_at & 0xFFF
        for a in by_lo.get(lo, ()):
            w = img.word(a)
            rn, rt = (w >> 5) & 31, w & 31
            for b in range(a - 4, max(a - BACK_LIMIT, img.text[0]) - 4, -4):
                v = img.word(b)
                if is_adrp(v) and (v & 31) == rn:
                    if adrp_target(b, v) == page:
                        sites.append((a, w, [('page', rn), ldr_s(rt, rn, SLOT[value]), adrp(a, page, rn)], SLOT[value]))
                    break
                if writes_reg(v, rn):
                    break
    for a in img.text_range():
        w = img.word(a)
        if is_fmov_s_w(w):
            rd, rn = w & 31, (w >> 5) & 31
            value = value_in_reg(img, a, rn)
            if value in SLOT:
                sites.append((a, w, [('page', rn), ldr_s(rd, rn, SLOT[value])] + mov_words(rn, value), SLOT[value]))
        elif is_ldr_s_lit(w):
            t = lit_target(a, w)
            if img.in_image(t) and img.word(t) in SLOT:
                info.append((a, f'ldr s{w & 31}, =main+{t:#x} ({"16/9" if img.word(t) == ASPECT else "9/16"} literal): '
                                'not patched, no address register at the site'))
        elif is_fmov_s_imm(w) and fmov_imm_word((w >> 13) & 0xFF) in SLOT:
            info.append((a, f'fmov s{w & 31}, #0.5625 (9/16 immediate): not patched, no address register at the site'))
    sites.sort()
    return sites, info


# ---- INFO: the size pairs
def size_sites(img):
    """[(address, width, height, what)] where a logical width and height are used together: 1920/1080 (the docked
    render targets) and 1280/720 (the interface's canvas)."""
    size_words = {f32(float(v)): v for v in UI_SIZES}
    found = []   # (address, value, how)
    adrp_of = {}   # register -> (adrp address, page), the last adrp seen walking forward; a cheap stand-in for (a)
    for a in img.text_range():
        w = img.word(a)
        if is_adrp(w):
            adrp_of[w & 31] = (a, adrp_target(a, w))
        elif is_branch(w):
            adrp_of.clear()
        elif is_movz(w) and (w >> 21) & 3 == 0 and (w >> 5) & 0xFFFF in UI_SIZES:
            found.append((a, (w >> 5) & 0xFFFF, f'movz w{w & 31}'))
        elif is_ldr_s_imm(w):
            rn = (w >> 5) & 31
            if rn in adrp_of:
                t = adrp_of[rn][1] + ((w >> 10) & 0xFFF) * 4
                if img.in_image(t) and img.word(t) in size_words:
                    found.append((a, size_words[img.word(t)], 'ldr s (f32)'))
        elif is_ldr_s_lit(w):
            t = lit_target(a, w)
            if img.in_image(t) and img.word(t) in size_words:
                found.append((a, size_words[img.word(t)], 'ldr s (f32 literal)'))
    out = []
    for i, (a, v, how) in enumerate(found):   # each width with the nearest matching height, one candidate per width
        if UI_SIZES[v] != 'w':
            continue
        near = [(abs(b - a), b, u, how2) for b, u, how2 in found[max(0, i - 8):i + 9]
                if (v, u) in ((1280, 720), (1920, 1080)) and abs(b - a) <= UI_NEAR]
        if near:
            _, b, u, how2 = min(near)
            out.append((min(a, b), v, u, f'{v} ({how}) at main+{a:#x} and {u} ({how2}) at main+{b:#x}'))
    return sorted(set(out))


# ---- the gate and the known sites
def gate(img):
    """The game version main's build id or landmark constants name, or None."""
    for version, prefix in BUILD_IDS.items():
        if img.build_id.startswith(prefix):
            return version
    for version, marks in LANDMARKS.items():
        if all(img.in_image(a) and img.word(a) == f32(v) for a, v in marks):
            return version
    return None


def check_known(version, sites, sizes, known=KNOWN_SITES):
    """[(text, ok)] comparing the scan with the mods' sites of this version: agree / disagree per known fdiv site and
    size pair, and the scanner's sites the mods do not have as new."""
    k = known.get(version)
    if not k:
        return []
    out = []
    found = {a: s for a, _, _, _, s, _ in sites}
    for fdiv, start, func in k['fdiv']:
        if fdiv in found:
            note = '' if found[fdiv] == start else f' (window starts at main+{found[fdiv]:#x}, the mod at main+{start:#x})'
            out.append((f'agree main+{fdiv:#x} (function main+{func:#x}){note}', True))
        else:
            out.append((f'disagree main+{fdiv:#x} (function main+{func:#x}): the mod patches it, the scanner has no site there',
                        False))
    for a in sorted(found):
        if a not in {f for f, _, _ in k['fdiv']}:
            out.append((f'new main+{a:#x}: a site the mods do not have', True))
    pairs = {(a, b) for a, _, _, what in sizes for a, b in [tuple(int(x, 16) for x in
             __import__('re').findall(r'main\+(0x[0-9a-f]+)', what))]}
    for a, b in k['sizes']:
        ok = (a, b) in pairs or (b, a) in pairs
        out.append((f'{"agree" if ok else "disagree"} size pair main+{a:#x} / main+{b:#x}', ok))
    return out


def check_symbols(img):
    """When main keeps its symbols: (text lines) on ml::DevGraph::getAspect, the pattern inside it and its callers."""
    if GET_ASPECT not in img.syms:
        return []
    a, size = img.syms[GET_ASPECT]
    sites, info = computed_sites(img, a, a + size)
    lines = [f'{GET_ASPECT} at main+{a:#x} ({size:#x} bytes): the computed-aspect pattern is '
             f'{"found" if sites or info else "NOT found"} inside it']
    callers = [b for b in img.text_range() if img.word(b) >> 26 == 0x25 and
               b + ((((img.word(b) & 0x3FFFFFF) ^ 0x2000000) - 0x2000000) << 2) == a]
    for b in callers:
        lines.append(f'  called from main+{b:#x} {img.name_of(b)}')
    if not callers:
        lines.append('  no bl to it: inlined at every user')
    return lines


# ---- output
def emit(sites, version, out=sys.stdout):
    print(f'# XC2 {version} ultrawide aspect (tools/aspect_sites_xc2.py; NOTES.md "Known gaps"). Generated from the '
          'game\'s main.', file=out)
    print(f'set {SET_NAME} {SET_ENV} 1', file=out)
    for a, w, repl in sorted((s[0], s[1], s[2]) for s in sites):
        words = ' '.join(f'@page:x{r[1]}' if isinstance(r, tuple) else f'{r:08x}' for r in repl)
        print(f'site {SET_NAME} main {a:x} {w:08x} {words}', file=out)


def report(img, computed, constants, info, sizes, known, symbols, out=sys.stderr):
    for a, w, _, slot, start, order in computed:
        how = {'w/h': 'width / height', 'h/w': 'height / width', None: 'order assumed width / height'}[order]
        print(f'site main+{a:#x} {img.name_of(a)}: computed aspect, window main+{start:#x}, {how} -> +{slot:#x}', file=out)
    for a, w, _, slot in constants:
        form = 'adrp+ldr' if is_ldr_s_imm(w) else 'movz/movk+fmov'
        print(f'site main+{a:#x} {img.name_of(a)}: constant {form} -> +{slot:#x}', file=out)
    for a, what in sorted(info):
        print(f'INFO main+{a:#x} {img.name_of(a)}: {what}', file=out)
    for a, v, u, what in sizes:
        print(f'INFO size pair main+{a:#x} {img.name_of(a)}: {what}', file=out)
    for text, _ in known:
        print(f'known: {text}', file=out)
    for text in symbols:
        print(f'symbols: {text}', file=out)
    inverse = any(s[3] == SLOT_INVERSE for s in computed) or any(s[3] == SLOT_INVERSE for s in constants)
    print(f'# {len(computed)} computed-aspect sites, {len(constants)} constant loads, {len(info)} left unpatched, '
          f'{len(sizes)} size pairs; the inverse slot +0x64 is {"used" if inverse else "not used"}', file=out)


# ---- self test
def selftest():
    import tempfile
    import patches
    rodata_base = 0x2000
    rod = bytearray(0x100)
    struct.pack_into('<IIII', rod, 0x10, ASPECT, INVERSE, f32(1280.0), f32(720.0))
    pad = lambda n: [0x8B030041] * n                  # add x1, x2, x3: writes x1 only
    code = [NOP] * 0x10
    # (p) in a function that saves x30: the loads by ldr, one instruction between the scvtf, as at the mod's first site
    f1 = len(code) * 4
    code += [STP_X29_X30_PRE_20, MOV_X29_SP, ldr_w(8, 19, 0x230), ldr_w(9, 19, 0x234), scvtf_s(0, 8)] + pad(1)
    code += [scvtf_s(1, 9), fdiv_s(0, 0, 1)]
    p1 = len(code) * 4 - 4
    code += [bl(len(code) * 4, 0x40), LDP_X29_X30_POST_20, RET]
    # (p) the other way round (height / width), the loads by ldp, the scvtf adjacent
    f2 = len(code) * 4
    code += [STP_X29_X30_PRE_20, MOV_X29_SP, ldp_w(8, 9, 19, 0x30), scvtf_s(0, 8), scvtf_s(1, 9), fdiv_s(2, 1, 0)]
    p2 = len(code) * 4 - 4
    code += [LDP_X29_X30_POST_20, RET]
    # (p) in a leaf that never saves x30: INFO
    f3 = len(code) * 4
    code += [ldr_w(8, 0, 0x230), ldr_w(9, 0, 0x234), scvtf_s(0, 8), scvtf_s(1, 9), fdiv_s(0, 0, 1)]
    p3 = len(code) * 4 - 4
    code += [RET]
    # a division of two converted integers that came from arithmetic, not a load: the weak INFO
    code += [STP_X29_X30_PRE_20, 0x0B090108, 0x0B080129, scvtf_s(0, 8), scvtf_s(1, 9), fdiv_s(0, 0, 1)]   # add w8, w8, w9 ; add w9, w9, w8
    p4 = len(code) * 4 - 4
    code += [LDP_X29_X30_POST_20, RET]
    # the constant forms
    code += [adrp(len(code) * 4, rodata_base, 8), ldr_s(0, 8, 0x10)]                       # (a) 16/9, A1
    a1 = len(code) * 4 - 4
    code += [adrp(len(code) * 4, rodata_base, 9)] + pad(3) + [ldr_s(3, 9, 0x14)]           # (a) 9/16, A2
    a2 = len(code) * 4 - 4
    code += [adrp(len(code) * 4, rodata_base, 10), 0xAA0B03EA, ldr_s(1, 10, 0x10)]        # x10 rewritten: no site
    code += [movz_w(8, 0x8E39, 0), movk_w(8, 0x3FE3, 1), 0x1E270100]                       # (b) 16/9 -> s0, B1
    b1 = len(code) * 4 - 4
    code += [movz_w(11, 0x3F10, 1), 0x1E270164]                                            # (b) 9/16 -> s4, B2
    b2 = len(code) * 4 - 4
    code += [movz_w(8, 0x8E39, 0), movk_w(8, 0x3FE3, 1), 0x14000002, 0x1E270100]           # branch between: no site
    lit = len(code) * 4 + 0x40
    code += [ldr_s_lit(5, len(code) * 4, lit)]                                              # (c) literal: INFO
    c1 = len(code) * 4 - 4
    code += [fmov_s_imm(6, 0x62)]                                                           # (d) 0.5625: INFO
    d1 = len(code) * 4 - 4
    code += [movz_w(0, 1280, 0), NOP, movz_w(1, 720, 0)]                                   # size pair: INFO
    e1 = len(code) * 4 - 12
    code += [adrp(len(code) * 4, rodata_base, 12), ldr_s(7, 12, 0x18), ldr_s(8, 12, 0x1C)]  # size pair as f32: INFO
    e2 = len(code) * 4 - 8
    code += [movz_w(0, 0x780, 0), NOP, movz_w(0, 0x438, 0)]                                # 1920 / 1080 as the mod's
    e3 = len(code) * 4 - 12
    while len(code) * 4 < lit:
        code.append(NOP)
    code += [ASPECT, RET]                                                                   # the literal, ret
    text = b''.join(struct.pack('<I', w) for w in code)
    image = bytearray(rodata_base + len(rod))
    image[:len(text)] = text
    image[rodata_base:rodata_base + len(rod)] = rod
    syms = [('fn_a', 0, 1, f1, f2 - f1), (GET_ASPECT, 0, 1, f2, f3 - f2), ('fn_c', 0, 1, f3, 0x100)]
    img = Image(image, (0, len(text)), (rodata_base, len(rod)), (rodata_base + len(rod), 0), syms=syms,
                build_id=BUILD_IDS['2.1.0'].upper() + '0' * 32)
    assert gate(img) == '2.1.0'
    assert fmov_imm_word(0x62) == INVERSE, hex(fmov_imm_word(0x62))
    assert fmov_imm_word(0x70) == f32(1.0) and fmov_imm_word(0x00) == f32(2.0), 'fmov immediate decoding'
    assert saves_x30(STP_X29_X30_PRE_20) and restores_x30(LDP_X29_X30_POST_20)
    assert saves_x30(0xA9017BFD) and restores_x30(0xA9417BFD), 'stp / ldp x29, x30, [sp, #0x10]'
    assert saves_x30(0xF9000FFE) and restores_x30(0xF9400FFE), 'str / ldr x30, [sp, #0x18]'
    assert saves_x30(0xA9017BF3), 'stp x19, x30, [sp, #0x10]'
    assert int_load(ldr_w(8, 19, 0x230)) == {8: (19, 0x230)} and int_load(ldp_w(8, 9, 19, 0x30)) == {8: (19, 0x30), 9: (19, 0x34)}
    assert int_load(0xB85F0268) == {8: (19, -16)}, 'ldur w8, [x19, #-16]'
    # the primary form
    computed, info = computed_sites(img)
    assert [s[0] for s in computed] == [p1, p2], [hex(s[0]) for s in computed]
    assert computed[0][1:] == (fdiv_s(0, 0, 1), [('page', 30), ldr_s(0, 30, SLOT_ASPECT)], SLOT_ASPECT, p1 - 12, 'w/h'), computed[0]
    assert computed[1][1:] == (fdiv_s(2, 1, 0), [('page', 30), ldr_s(2, 30, SLOT_INVERSE)], SLOT_INVERSE, p2 - 8, 'h/w'), computed[1]
    assert [a for a, _ in info] == [p3, p4], [hex(a) for a, _ in info]
    assert 'x30 is live' in info[0][1] and 'not loaded from memory' in info[1][1], info
    assert x30_dead(img, p1) is None and x30_dead(img, p3)
    # the secondary forms
    constants, cinfo = constant_sites(img)
    assert [s[0] for s in constants] == [a1, a2, b1, b2], [hex(s[0]) for s in constants]
    by = {a: (w, repl) for a, w, repl, _ in constants}
    assert by[a1] == (ldr_s(0, 8, 0x10), [('page', 8), ldr_s(0, 8, 0x60), adrp(a1, rodata_base, 8)])
    assert by[a2] == (ldr_s(3, 9, 0x14), [('page', 9), ldr_s(3, 9, 0x64), adrp(a2, rodata_base, 9)])
    assert adrp_target(a1, by[a1][1][2]) == rodata_base, 'x8 is pointed back at the constant page'
    assert by[b1] == (0x1E270100, [('page', 8), ldr_s(0, 8, 0x60), movz_w(8, 0x8E39, 0), movk_w(8, 0x3FE3, 1)])
    assert by[b2] == (0x1E270164, [('page', 11), ldr_s(4, 11, 0x64), movz_w(11, 0x3F10, 1)])
    for a in (b1, b2):   # the regenerated moves rebuild the word the original built
        fake = Image(b''.join(struct.pack('<I', w) for w in [NOP] * 4 + by[a][1][2:] + [by[a][0]]),
                     (0, 4 * (5 + len(by[a][1]) - 2)), (0x1000, 0), (0x1000, 0))
        assert value_in_reg(fake, 4 * (4 + len(by[a][1]) - 2), by[a][1][0][1]) in SLOT
    assert [a for a, _ in cinfo] == [c1, d1], [hex(a) for a, _ in cinfo]
    assert 'literal' in cinfo[0][1] and '0.5625' in cinfo[1][1]
    # the size pairs, the symbols, the known-site comparison
    sizes = size_sites(img)
    assert [(a, v, u) for a, v, u, _ in sizes] == [(e1, 1280, 720), (e2, 1280, 720), (e3, 1920, 1080)], sizes
    assert img.name_of(p1) == f'fn_a+{p1 - f1:#x}' and img.name_of(0x10) == '?'
    symbols = check_symbols(img)
    assert symbols and 'is found' in symbols[0] and symbols[1] == '  no bl to it: inlined at every user', symbols
    known = {'2.1.0': {'fdiv': [(p1, p1 - 12, f1), (p3, p3 - 8, f3)], 'sizes': [(e3, e3 + 8), (0x40, 0x48)]}}
    result = check_known('2.1.0', computed, sizes, known)
    assert [ok for _, ok in result] == [True, False, True, True, False], result
    assert result[0][0].startswith(f'agree main+{p1:#x}') and ' (window' not in result[0][0], result[0]
    assert result[1][0].startswith(f'disagree main+{p3:#x}') and result[2][0].startswith(f'new main+{p2:#x}'), result
    assert result[3][0].startswith('agree size pair') and result[4][0].startswith('disagree size pair'), result
    assert check_known('3.0.1', computed, sizes, known) == []
    # The emitted table parses, resolves @page and passes the original-word check, as gen.py --patches runs it.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'patches.txt'
        with open(path, 'w') as f:
            emit(computed + constants, 'selftest', f)
        mods = [('main', 0x10000000, len(image)), ('sdk', 0x10400000, 0x1000)]
        table = patches.load(path, mods)
        assert table.sets == [(SET_NAME, SET_ENV, 1)]
        assert sorted(table.sites['main']) == sorted([p1, p2, a1, a2, b1, b2])

        class Mod:
            base = 0x10000000
            def in_text(self, a): return img.in_text(a - self.base)
            def word(self, a): return img.word(a - self.base)
        patches.check(table, Mod(), 'main')
        resolved = table.for_module('main', 0x10000000)
        assert all(adrp_target(a, words[0]) == table.page for a, (_, words) in resolved.items()), 'adrp to the page'
        assert resolved[0x10000000 + p1][1][0] & 31 == 30, 'the computed site uses x30'
        bad = Image(bytes(image[:p1]) + b'\0\0\0\0' + bytes(image[p1 + 4:]), img.text, img.rodata, img.data)
        try:
            class BadMod(Mod):
                def word(self, a): return bad.word(a - self.base)
            patches.check(table, BadMod(), 'main')
        except patches.PatchError:
            pass
        else:
            raise AssertionError('a changed original word must fail the check')
    print('aspect_sites_xc2: selftest ok (2 computed-aspect sites, 4 constant loads, 4 unpatched, 3 size pairs, '
          'known-site and symbol checks)')


def main():
    args = sys.argv[1:]
    if args == ['--selftest']:
        return selftest()
    no_gate, sizes_wanted = '--no-gate' in args, '--sizes' in args
    args = [a for a in args if a not in ('--no-gate', '--sizes')]
    if len(args) != 1:
        sys.exit('usage: aspect_sites_xc2.py <main NSO> [--sizes] [--no-gate] | --selftest')
    img = Image.from_nso(args[0])
    version = gate(img)
    if not version and not no_gate:
        sys.exit(f'aspect_sites_xc2: main (build id {img.build_id[:16]}) is none of {", ".join(BUILD_IDS)} and holds '
                 'none of the 3.0.1 constants NOTES.md names; another game version? --no-gate scans it anyway')
    computed, info = computed_sites(img)
    constants, cinfo = constant_sites(img)
    sizes = size_sites(img) if sizes_wanted or version in KNOWN_SITES else []
    known = check_known(version, computed, sizes)
    symbols = check_symbols(img)
    if not computed and not constants:
        sys.exit('aspect_sites_xc2: no patchable aspect site in main')
    emit(computed + constants, version or f'unknown version, build id {img.build_id[:16]} (--no-gate)')
    report(img, computed, constants, info + cinfo, sizes if sizes_wanted else [], known, symbols)


if __name__ == '__main__':
    main()

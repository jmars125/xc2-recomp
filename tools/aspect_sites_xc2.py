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

the division of two integers that live in memory just before, loaded (ldr, ldur or ldp w) or stored (str, stur or
stp w, as ml::ScnCamMan::update stores the size to RENDER_INFO +0x1e0 / +0x1e4 before dividing it), the width at the
lower offset. The patch
replaces the fdiv alone with adrp x30, <patch page> ; ldr s<d>, [x30, #slot]: a patch site replaces one instruction
with any number (recomp/patches.py), so the two scvtf stay in place and only the quotient comes from the page
(+0x60 width / height; +0x64 height / width, for a division the other way round, emitted only when one is found).
The mods' third slot needs no nop here for the same reason. x30 is the scratch register the mods use as well: a site
is patched only when the enclosing function saved x30 in its prologue (stp x29, x30, [sp, ...] or str x30, [sp, ...],
found walking back from the site without passing a ret) and restores it after the site (ldp or ldr x30 from sp before
the next ret, without passing another prologue). The compiler never allocates x30 otherwise, so x30 is dead at such a
site. A leaf has no such save: ml::DevGraph::getAspect itself (1.0.0 main+0x713698: the two loads, a zero guard
cbz each, fmov s0, #1.0 for the guarded path, scvtf, scvtf, fdiv, ret) ends in ret right after the fdiv, so there the
scratch register is the x-form of one of the scvtf sources (x8 or x9, caller-saved temporaries that die at the ret),
when no instruction between the fdiv and the ret reads it; the zero guards stay, so a zero size still yields 1.0. A
leaf that ends in a tail call (ml::ScnObjCam::setSize: b updateViewMatrix) counts the same when main's symbols say
the branch goes to a function's start, with x8..x17 only, as x0..x7 carry the call's arguments.
A site that fails both rules is listed as INFO with the reason. The walks from the fdiv back to the scvtf and from a
scvtf back to its load pass through conditional branches (the zero guards) and stop at an unconditional branch, a
call, a ret or a write to the register traced. The INFO list also names a division of two converted integers that
are not loaded from memory (a weaker match, for the reader). Each site's line names where the quotient is stored when
an instruction right after stores it: on 1.0.0 ml::DevGraphNx::getPersSys, the projection builder, divides DevGraph's
render size for its own matrix, and ml::ScnObjCam::apply, ml::ScnObjCam::setSize and ml::ScnCamMan::update store
their quotient to RENDER_INFO +0x1f0, the aspect the frustum (updateFovNearFar) is derived from, so both kinds need
the patch: a widened projection with a 16:9 frustum culls at the sides.

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
theboy181 rewrites), with the function each lies in, and the five 1.0.0 sites this script found and that were read
in the disassembly. When the scanned main is one of those versions (its build id) the result is checked against
them, agree or disagree per site, and sites the list does not have are listed as new. When main keeps
its symbols (1.0.0), the pattern is verified inside ml::DevGraph::getAspect itself, its callers (b and bl) are named,
and ml::DevGraphNx::getPersSys, the projection builder, is described: whether it calls getAspect, inlines it, or
reads s registers from an object (a cached aspect), with its calls named.

--sizes: INFO only, the pairs of 1920 and 1080 (the docked render targets, which Fl4sh_ makes 2580x1080 at
2.1.0 text 0x6caff8, 0x6cb060 and 0x70a634) and of 1280 and 720 (the interface's logical size, ml::WorkRoot) used
together, as movz immediates, as f32 constants or as literals; not patched, the start of the interface fit.

The version gate: the build id names 1.0.0, 2.0.2, 2.1.0, 3.0.0 and 3.0.1 (the ids the community patches and
masagrator's FPSLocker files carry), and 3.0.1 is also known by the constants NOTES.md "60 fps" names (the 1/30 at main+0x9b5148,
the 0.997 at main+0x9b558c); another main stops the script unless --no-gate. --selftest runs the scanner over a
synthetic image that holds each form, a function that saves x30, a leaf shaped like getAspect and a leaf that reads
its registers after the division, and checks the sites, the patch words, the x30 and leaf rules and the KNOWN_SITES
comparison, with recomp/patches.py parsing and checking the result as
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
BUILD_IDS = {'1.0.0': '5087af2917d85858a0fd49cb4d6eed67', '2.0.2': 'd007651bc7c6a51ed7e8f463e02ac2ef',
             '2.1.0': 'f77f1559371c0ec6d50e78774ac59d95', '3.0.0': '12a2634f01346f2156b959703c47c146',
             '3.0.1': '4f5c96e2d97f45ac'}   # prefixes of main's build id
LANDMARKS = {'3.0.1': [(0x9b5148, 1 / 30), (0x9b558c, 0.997)]}   # NOTES.md "60 fps": main's f32 constants
# (fdiv site, first slot of the mod's triple, enclosing function) per version, text offsets; Ghidra's FUN_ names are
# the function offsets + 0x100000.
KNOWN_SITES = {'2.1.0': {'fdiv': [(0x7e308c, 0x7e3080, 0x7e2f88), (0x6cbfd4, 0x6cbfcc, 0x6cbfa4),
                                  (0x6c2398, 0x6c2390, 0x6c2210)],
                         'sizes': [(0x6caff8, 0x6cb000), (0x6cb060, 0x6cb068), (0x70a634, 0x70a640)]},
               # 1.0.0: this script's own result (2026-11-03), each site read in the disassembly: a regression check,
               # not a mod's. ml::DevGraph::getAspect, ml::DevGraphNx::getPersSys (the projection builder),
               # ml::ScnCamMan::update, ml::ScnObjCam::setSize, ml::ScnObjCam::apply (the three store RENDER_INFO +0x1f0)
               '1.0.0': {'fdiv': [(0x7136c0, 0x7136b8, 0x713698), (0x72262c, 0x722624, 0x7225cc),
                                  (0x741958, 0x741950, 0x7417d0), (0x742984, 0x742978, 0x742938),
                                  (0x753668, 0x753660, 0x753638)],
                         'sizes': []}}
GET_ASPECT = '_ZN2ml8DevGraph9getAspectEv'
GET_PERS_SYS = '_ZN2ml10DevGraphNx10getPersSysERN2mm5Mat44Efff'
LEAF_LIMIT = 4          # instructions from the fdiv to the ret of a leaf for the scratch-register rule
BACK_LIMIT = 0x400      # how far back an adrp is looked for (bytes), as in fps_sites_xc2.py
MOV_LIMIT = 16          # how many instructions back a movz / movk chain is followed
CVT_LIMIT = 6           # how many instructions back from the fdiv its scvtf are looked for
LOAD_LIMIT = 16         # how many instructions back from a scvtf the load or store of its integer is looked for
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


def int_home(w, loads=True, stores=True):
    """{register: (base, offset)} of a 32-bit load or store, the place in memory the integer lives, or None: ldr /
    str w (unsigned imm; pre or post-indexed with the offset unknown), ldur / stur w, ldr / str w (reg), ldp / stp w.
    A load writes the register, a store only names where its value came from or goes."""
    rt, rn = w & 31, (w >> 5) & 31
    load = (w >> 22) & 1
    if not (loads if load else stores):
        return None
    if (w & 0xFFC00000) in (0xB9400000, 0xB9000000):
        return {rt: (rn, ((w >> 10) & 0xFFF) * 4)}
    if (w & 0xFFE00C00) in (0xB8400000, 0xB8000000):
        off = (w >> 12) & 0x1FF
        return {rt: (rn, off - 0x200 if off & 0x100 else off)}
    if (w & 0xFFE00400) in (0xB8400400, 0xB8000400):   # pre / post-indexed: the base moves, the offset is not comparable
        return {rt: (rn, None)}
    if (w & 0xFFE00C00) in (0xB8600800, 0xB8200800):
        return {rt: (rn, None)}
    if (w & 0xFFC00000) in (0x28C00000, 0x29400000, 0x29C00000, 0x28800000, 0x29000000, 0x29800000):
        off = (w >> 15) & 0x7F
        off = (off - 0x80 if off & 0x40 else off) * 4
        return {rt: (rn, off), (w >> 10) & 31: (rn, off + 4)}
    return None


def int_load(w):
    return int_home(w, stores=False)


def is_ret(w):
    return (w & 0xFFFFFC1F) == 0xD65F0000


def is_cond_branch(w):   # b.cond, cbz / cbnz, tbz / tbnz: the fall-through path goes on
    return (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000 or (w & 0x7E000000) == 0x36000000


def is_flow_end(w):   # b, bl, ret, br, blr: a walk along one path stops here
    return w >> 26 in (0x05, 0x25) or (w & 0xFFFFFC1F) in (0xD65F0000, 0xD61F0000, 0xD63F0000)


def is_branch(w):
    return is_cond_branch(w) or is_flow_end(w)


def direct_target(w, b):
    """The target of a b or bl at b, else None."""
    return b + ((((w & 0x3FFFFFF) ^ 0x2000000) - 0x2000000) << 2) if w >> 26 in (0x05, 0x25) else None


def reads_reg(w, r):
    """A conservative test: the instruction names r in any register field (so a write counts as well)."""
    return r in ((w & 31), (w >> 5) & 31, (w >> 16) & 31)


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
    """A conservative test: an instruction whose low five bits name rd and that is not a store, a compare, or a SIMD /
    FP instruction (those name V registers: mov v8.16b, v1.16b leaves w8 alone) other than a conversion to a GPR."""
    if (w & 31) != rd:
        return False
    if (w & 0x0E000000) == 0x0E000000:   # SIMD / FP data processing
        if (w & 0x5F20FC00) == 0x1E200000:   # conversion between FP and integer
            opcode, rmode = (w >> 16) & 7, (w >> 19) & 3
            return not (opcode in (2, 3) and rmode == 0 or opcode == 7)   # scvtf / ucvtf, fmov from general write FP
        return (w & 0x9FE08400) == 0x0E000400 and (w >> 11) & 0xF in (5, 7)   # smov / umov write a GPR
    if (w & 0x0A000000) == 0x08000000 and w & 0x04000000:   # loads and stores of V registers
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
        self.func_starts = set(self.func_addrs)

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
        if is_flow_end(w):
            return None
        if is_cond_branch(w):
            continue
        if (w & 31) == s and is_fp_op(w):
            return (b, (w >> 5) & 31) if is_scvtf_s(w) else None
    return None


def load_source(img, a, r):
    """(base register, offset) of the memory w<r> was loaded from, or stored to, last before a; None when another
    instruction wrote it or nothing names its home (offset None: a register or a moving base)."""
    for b in range(a - 4, max(a - 4 * LOAD_LIMIT, img.text[0]) - 4, -4):
        w = img.word(b)
        if is_flow_end(w):
            return None
        if is_cond_branch(w):   # a zero guard between the load and the conversion (cbz w<r> names r but writes nothing)
            continue
        home = int_home(w)
        if home and r in home:
            return home[r]
        if writes_reg(w, r):
            return None
    return None


def quotient_store(img, a, d):
    """'[x<n>, #imm]' when one of the instructions after the fdiv a stores s<d> there before anything else writes it, else ''."""
    for b in img.text_range(a + 4, min(a + 4 * (LEAF_LIMIT + 1), img.text[0] + img.text[1])):
        w = img.word(b)
        if (w & 0xFFC00000) == 0xBD000000 and (w & 31) == d:
            return f'[x{(w >> 5) & 31}, #{((w >> 10) & 0xFFF) * 4:#x}]'
        if is_branch(w) or ((w & 31) == d and is_fp_op(w)):
            return ''
    return ''


def leaf_scratch(img, a, regs):
    """The register among regs (the scvtf sources, as x registers) a leaf may clobber at the fdiv a: the fall-through
    path reaches ret within LEAF_LIMIT instructions without reading it. Caller-saved temporaries x8..x17 first, then
    x0..x7; never x18 or a callee-saved one. (register, None) or (None, why)."""
    order = sorted(r for r in regs if 8 <= r <= 17) + sorted(r for r in regs if r <= 7)
    if not order:
        return None, 'no caller-saved scvtf source register'
    path = []
    for b in img.text_range(a + 4, min(a + 4 * (LEAF_LIMIT + 1), img.text[0] + img.text[1])):
        w = img.word(b)
        if is_ret(w):
            break
        t = direct_target(w, b)
        if t is not None and w >> 26 == 0x05 and t in img.func_starts:   # a tail call: x0..x7 carry its arguments
            order = [r for r in order if r >= 8]
            if not order:
                return None, f'the path ends in a tail call at main+{b:#x} and both scvtf sources are argument registers'
            break
        if is_branch(w):
            return None, f'the path from the fdiv branches at main+{b:#x} before a ret'
        path.append(w)
    else:
        return None, f'no ret within {LEAF_LIMIT} instructions after the fdiv'
    for r in order:
        if not any(reads_reg(w, r) for w in path):
            return r, None
    return None, 'every scvtf source register is read again before the ret'


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
            store = quotient_store(img, a, d)
            info.append((a, f'fdiv s{d}, s{x}, s{y} of two converted integers (window main+{start:#x}) that are not '
                            f'loaded from memory just before{", stored to " + store if store else ""}: a weak match, '
                            'not patched'))
            continue
        order = None
        if lx[0] == ly[0] and lx[1] is not None and ly[1] is not None and lx[1] != ly[1]:
            order = 'w/h' if lx[1] < ly[1] else 'h/w'
        scratch, why = 30, x30_dead(img, a)
        if why:   # a leaf: one of the converted registers dies at the ret that follows
            scratch, why2 = leaf_scratch(img, a, [cx[1], cy[1]])
            if scratch is None:
                info.append((a, f'computed aspect (fdiv s{d}, s{x}, s{y}; window main+{start:#x}; loads at x{lx[0]}+'
                                f'{lx[1]}, x{ly[0]}+{ly[1]}): not patched, {why}; as a leaf, {why2}'))
                continue
        slot = SLOT_INVERSE if order == 'h/w' else SLOT_ASPECT
        sites.append((a, w, [('page', scratch), ldr_s(d, scratch, slot)], slot, start, order))
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
    """When main keeps its symbols: (text lines) on ml::DevGraph::getAspect, the pattern inside it and its callers,
    and on ml::DevGraphNx::getPersSys, where the projection's aspect comes from."""
    if GET_ASPECT not in img.syms:
        return []
    a, size = img.syms[GET_ASPECT]
    sites, info = computed_sites(img, a, a + size)
    lines = [f'{GET_ASPECT} at main+{a:#x} ({size:#x} bytes): the computed-aspect pattern is '
             f'{"found" if sites or info else "NOT found"} inside it'
             + (f', patched at main+{sites[0][0]:#x} with x{sites[0][2][0][1]}' if sites else '')]
    callers = [(b, img.word(b) >> 26 == 0x25) for b in img.text_range() if direct_target(img.word(b), b) == a]
    for b, is_bl in callers:
        lines.append(f'  {"called" if is_bl else "tail-called"} from main+{b:#x} {img.name_of(b)}')
    if not callers:
        lines.append('  no b or bl to it: inlined at every user')
    else:
        lines.append(f'  {len(callers)} users through calls (plus the users that inline it)')
    if GET_PERS_SYS in img.syms:
        p, psize = img.syms[GET_PERS_SYS]
        psites, pinfo = computed_sites(img, p, p + psize)
        calls, s_loads, fdivs = [], [], 0
        for b in img.text_range(p, p + psize):
            w = img.word(b)
            t = direct_target(w, b)
            if t is not None and w >> 26 == 0x25:
                calls.append(img.name_of(t) if img.name_of(t) != '?' else f'main+{t:#x}')
            elif is_ldr_s_imm(w):
                s_loads.append(f's{w & 31} <- [x{(w >> 5) & 31}, #{((w >> 10) & 0xFFF) * 4:#x}]')
            elif is_fdiv_s(w):
                fdivs += 1
        aspect_calls = sum(1 for c in calls if c.startswith(GET_ASPECT))
        lines.append(f'{GET_PERS_SYS} at main+{p:#x} ({psize:#x} bytes): '
                     + (f'calls getAspect {aspect_calls}x; ' if aspect_calls else 'does not call getAspect; ')
                     + (f'inlines the computed aspect ({len(psites)} patched, {len(pinfo)} weak); ' if psites or pinfo
                        else 'no computed aspect inside; ')
                     + f'{fdivs} fdiv; s loads from objects: {", ".join(s_loads[:12]) or "none"}'
                     + ('; calls: ' + ', '.join(sorted(set(calls))[:12]) if calls else ''))
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
    for a, w, repl, slot, start, order in computed:
        how = {'w/h': 'width / height', 'h/w': 'height / width', None: 'order assumed width / height'}[order]
        store = quotient_store(img, a, w & 31)
        print(f'site main+{a:#x} {img.name_of(a)}: computed aspect, window main+{start:#x}, {how} -> +{slot:#x} '
              f'through x{repl[0][1]}{", stored to " + store if store else ""}', file=out)
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
    # (p) in a leaf that never saves x30 and returns right after: the leaf rule, x8 as the scratch
    f3 = len(code) * 4
    code += [ldr_w(8, 0, 0x230), ldr_w(9, 0, 0x234), scvtf_s(0, 8), scvtf_s(1, 9), fdiv_s(0, 0, 1)]
    p3 = len(code) * 4 - 4
    code += [RET]
    # (p) in a leaf that reads both converted registers again before its ret: INFO
    code += [ldr_w(8, 0, 0x230), ldr_w(9, 0, 0x234), scvtf_s(0, 8), scvtf_s(1, 9), fdiv_s(0, 0, 1)]
    p3b = len(code) * 4 - 4
    code += [0x0B090100, RET]   # add w0, w8, w9
    # (p) shaped as 1.0.0's ml::DevGraph::getAspect: zero guards (cbz) between the loads and the conversions, the
    # guarded path's fmov s0, #1.0, loads from x9 with the height first; carries the symbol
    f5 = len(code) * 4
    code += [adrp(len(code) * 4, 0x1000, 8), 0xF9411508, 0xF9400109, ldr_w(8, 9, 0x234), fmov_s_imm(0, 0x70)]
    code += [0x34000068 | ((5 << 5)), ldr_w(9, 9, 0x230), 0x34000049 | ((3 << 5)), scvtf_s(0, 9), scvtf_s(1, 8), fdiv_s(0, 0, 1)]
    p5 = len(code) * 4 - 4
    code += [RET]
    f5_end = len(code) * 4
    # a function shaped as a getPersSys that calls getAspect: the probe names the call
    f6 = len(code) * 4
    code += [STP_X29_X30_PRE_20, bl(len(code) * 4 + 4, f5), ldr_s(1, 0, 0x1f0), LDP_X29_X30_POST_20, RET]
    f6_end = len(code) * 4
    # (p) with a vector move between the height load and its conversion, as 1.0.0's getPersSys (mov v8.16b, v1.16b)
    f7 = len(code) * 4
    code += [STP_X29_X30_PRE_20, ldr_w(8, 9, 0x234), 0x4EA11C28, 0xAA0003F4, ldr_w(9, 9, 0x230), scvtf_s(1, 9),
             scvtf_s(2, 8), fdiv_s(11, 1, 2)]
    p7 = len(code) * 4 - 4
    code += [LDP_X29_X30_POST_20, RET]
    # (p) whose integers are known by their stores (ScnCamMan::update: str w9 / w10 to +0x1e0 / +0x1e4, then the
    # quotient to +0x1f0), their loads out of reach behind a join
    f8 = len(code) * 4
    code += [STP_X29_X30_PRE_20, 0x14000002, NOP, 0xB901E109, 0xB901E50A, scvtf_s(0, 9), scvtf_s(1, 10), fdiv_s(0, 0, 1)]
    p8 = len(code) * 4 - 4
    code += [0xAA1403E0, 0xBD01F100, LDP_X29_X30_POST_20, RET]   # mov x0, x20 ; str s0, [x8, #0x1f0]
    # (p) in a leaf that ends in a tail call (ScnObjCam::setSize: str s0, [x8, #0x1f0] ; b updateViewMatrix): x9
    f9 = len(code) * 4
    code += [ldr_w(9, 1, 0), ldr_w(10, 1, 4), scvtf_s(0, 9), scvtf_s(1, 10), fdiv_s(0, 0, 1)]
    p9 = len(code) * 4 - 4
    code += [0xBD01F100, 0x14000000 | (((f1 - len(code) * 4 - 4) >> 2) & 0x3FFFFFF)]   # str s0, [x8, #0x1f0] ; b fn_a
    f9_end = len(code) * 4
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
    syms = [('fn_a', 0, 1, f1, f2 - f1), ('fn_b', 0, 1, f2, f3 - f2), ('fn_c', 0, 1, f3, f5 - f3),
            (GET_ASPECT, 0, 1, f5, f5_end - f5), (GET_PERS_SYS, 0, 1, f6, f6_end - f6), ('fn_g', 0, 1, f7, f8 - f7),
            ('fn_h', 0, 1, f8, f9 - f8), ('fn_i', 0, 1, f9, f9_end - f9)]
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
    assert [s[0] for s in computed] == [p1, p2, p3, p5, p7, p8, p9], ([hex(s[0]) for s in computed], [hex(x) for x in (p1, p2, p3, p5, p7, p8, p9)], info)
    assert computed[4][1:] == (fdiv_s(11, 1, 2), [('page', 30), ldr_s(11, 30, SLOT_ASPECT)], SLOT_ASPECT, p7 - 8, 'w/h'), computed[4]
    assert computed[5][1:] == (fdiv_s(0, 0, 1), [('page', 30), ldr_s(0, 30, SLOT_ASPECT)], SLOT_ASPECT, p8 - 8, 'w/h'), computed[5]
    assert computed[6][1:] == (fdiv_s(0, 0, 1), [('page', 9), ldr_s(0, 9, SLOT_ASPECT)], SLOT_ASPECT, p9 - 8, 'w/h'), computed[6]
    assert quotient_store(img, p8, 0) == '[x8, #0x1f0]' and quotient_store(img, p9, 0) == '[x8, #0x1f0]'
    assert quotient_store(img, p1, 0) == '' and not writes_reg(0x4EA11C28, 8) and writes_reg(0x1E260100, 0)
    assert leaf_scratch(img, p9, [9, 10]) == (9, None) and leaf_scratch(img, p9, [0, 1])[0] is None
    assert computed[0][1:] == (fdiv_s(0, 0, 1), [('page', 30), ldr_s(0, 30, SLOT_ASPECT)], SLOT_ASPECT, p1 - 12, 'w/h'), computed[0]
    assert computed[1][1:] == (fdiv_s(2, 1, 0), [('page', 30), ldr_s(2, 30, SLOT_INVERSE)], SLOT_INVERSE, p2 - 8, 'h/w'), computed[1]
    assert computed[2][1:] == (fdiv_s(0, 0, 1), [('page', 8), ldr_s(0, 8, SLOT_ASPECT)], SLOT_ASPECT, p3 - 8, 'w/h'), computed[2]
    assert computed[3][1:] == (fdiv_s(0, 0, 1), [('page', 8), ldr_s(0, 8, SLOT_ASPECT)], SLOT_ASPECT, p5 - 8, 'w/h'), computed[3]
    assert [a for a, _ in info] == [p3b, p4], [hex(a) for a, _ in info]
    assert 'x30 is live' in info[0][1] and 'read again before the ret' in info[0][1], info[0]
    assert 'not loaded from memory' in info[1][1], info[1]
    assert x30_dead(img, p1) is None and x30_dead(img, p3) and x30_dead(img, p5)
    assert leaf_scratch(img, p3, [8, 9]) == (8, None) and leaf_scratch(img, p3, [9, 8]) == (8, None)
    assert leaf_scratch(img, p3, [19, 20])[0] is None and leaf_scratch(img, p1, [8, 9])[0] is None
    assert load_source(img, p5 - 8, 9) == (9, 0x230) and load_source(img, p5 - 4, 8) == (9, 0x234), 'through the cbz'
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
    assert img.name_of(p5) == f'{GET_ASPECT}+{p5 - f5:#x}'
    symbols = check_symbols(img)
    assert symbols and 'is found' in symbols[0] and f'patched at main+{p5:#x} with x8' in symbols[0], symbols
    assert symbols[1] == f'  called from main+{f6 + 4:#x} {GET_PERS_SYS}+0x4' and symbols[2].startswith('  1 users'), symbols
    assert 'calls getAspect 1x' in symbols[3] and 's1 <- [x0, #0x1f0]' in symbols[3] and 'no computed aspect' in symbols[3], symbols[3]
    known = {'2.1.0': {'fdiv': [(p1, p1 - 12, f1), (p3b, p3b - 8, f3)], 'sizes': [(e3, e3 + 8), (0x40, 0x48)]}}
    result = check_known('2.1.0', computed, sizes, known)
    assert [ok for _, ok in result] == [True, False] + [True] * 6 + [True, False], result
    assert result[0][0].startswith(f'agree main+{p1:#x}') and ' (window' not in result[0][0], result[0]
    assert result[1][0].startswith(f'disagree main+{p3b:#x}') and result[2][0].startswith(f'new main+{p2:#x}'), result
    assert result[8][0].startswith('agree size pair') and result[9][0].startswith('disagree size pair'), result
    assert check_known('3.0.1', computed, sizes, known) == []
    # The emitted table parses, resolves @page and passes the original-word check, as gen.py --patches runs it.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'patches.txt'
        with open(path, 'w') as f:
            emit(computed + constants, 'selftest', f)
        mods = [('main', 0x10000000, len(image)), ('sdk', 0x10400000, 0x1000)]
        table = patches.load(path, mods)
        assert table.sets == [(SET_NAME, SET_ENV, 1)]
        assert sorted(table.sites['main']) == sorted([p1, p2, p3, p5, p7, p8, p9, a1, a2, b1, b2])

        class Mod:
            base = 0x10000000
            def in_text(self, a): return img.in_text(a - self.base)
            def word(self, a): return img.word(a - self.base)
        patches.check(table, Mod(), 'main')
        resolved = table.for_module('main', 0x10000000)
        assert all(adrp_target(a, words[0]) == table.page for a, (_, words) in resolved.items()), 'adrp to the page'
        assert resolved[0x10000000 + p1][1][0] & 31 == 30, 'the computed site uses x30'
        assert resolved[0x10000000 + p5][1][0] & 31 == 8, 'the leaf site uses x8'
        bad = Image(bytes(image[:p1]) + b'\0\0\0\0' + bytes(image[p1 + 4:]), img.text, img.rodata, img.data)
        try:
            class BadMod(Mod):
                def word(self, a): return bad.word(a - self.base)
            patches.check(table, BadMod(), 'main')
        except patches.PatchError:
            pass
        else:
            raise AssertionError('a changed original word must fail the check')
    print('aspect_sites_xc2: selftest ok (7 computed-aspect sites of which 3 leaves, 4 constant loads, 4 unpatched, '
          '3 size pairs, known-site and symbol checks)')


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

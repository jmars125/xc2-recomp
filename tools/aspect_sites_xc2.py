r"""Find the loads of XC2's 16:9 aspect constants in main and print them as the aspect set of a patch table
(recomp/patches.py).

    .venv\Scripts\python tools\fps_sites_xc2.py build\extracted\upd\exefs\main > recomp\patches-upd.txt
    .venv\Scripts\python tools\aspect_sites_xc2.py build\extracted\upd\exefs\main >> recomp\patches-upd.txt
    python3 tools\aspect_sites_xc2.py --selftest

XC2 draws its picture at its own size and lays the 3D camera out for 16:9: the projection takes the aspect ratio
from the f32 constant 16/9 (0x3fe38e39) and, where the code divides the other way, 9/16 (0x3f100000). The set sends
every load of those two constants to the patch page, where runtime/resolution.c res_init stores the output's own
aspect and its inverse (XC2_OUTPUT_RES); the picture then holds a wider view in its 16:9 frame, and the present
stretches it to the output's shape (gfx_present.c gfx_fit_rect). This is the way the community ultrawide cheats for
emulators work on this game: the emulator's "stretch to window" plus a cheat that rewrites the aspect constant. The
interface is laid out on the same 16:9 canvas and is stretched with the picture; the sites that place it are not found
(the INFO list below is the start of that search). The precedent for the set is the 60 fps one: tools/fps_sites_xc2.py
finds the loads of the 1/30 constant, and runtime/frame_rate.c xc2_rate_store writes the value they read.

Patch page slot map (the page is the first 4 KiB after main's image, patches.py; the runtime owns its contents):
  +0x40 .. +0x53  xc360 (frame_rate.c xc2_rate_store, xc2_wait_store): vsync period, rate, frame wait, ticks, step
  +0x60           aspect: f32 output width / height, where the 16/9 loads read (resolution.c res_init)
  +0x64           aspect: f32 output height / width, where the 9/16 loads read
XC3's sets used +0 .. +0xb and +0x50 .. +0x6b; none of them exists in XC2's table, so the slots are free here.

The encodings of a constant load and what the set does with each:
  (a) adrp x<n>, <page> ; ... ; ldr s<t>, [x<n>, #lo]   the word at <page> + lo is 16/9 or 9/16 (.rodata). Patched as
      in fps_sites_xc2.py: adrp x<n>, <patch page> ; ldr s<t>, [x<n>, #slot] ; adrp x<n>, <page>, so x<n> holds
      what it held and later loads from the same page still work.
  (b) movz w<n>, #lo16 ; movk w<n>, #hi16, lsl #16 ; fmov s<t>, w<n>   the word built in a register (the 9/16 word
      is one movz with lsl #16). Patched at the fmov: adrp x<n>, <patch page> ; ldr s<t>, [x<n>, #slot] ; then the
      movz / movk that build the word again, so w<n> ends as it did (the 32-bit moves zero the top half as before).
  (c) ldr s<t>, <literal>   a word in .text. Not patched: the replacement needs an address register and the site
      gives none; listed as INFO so that a dead register can be picked by hand.
  (d) fmov s<t>, #0.5625   9/16 is an 8-bit float immediate (16/9 is not). Not patched for the same reason; INFO.
A site's function is named from main's dynamic symbols when it has them.

INFO only, not patched: candidate sites of the interface's logical size, a 1280 and a 720 (or 1920 and 1080) within
a few instructions of each other, as immediates (movz) or as f32 constants loaded through adrp + ldr s or from a
literal (an 8-bit float immediate reaches 31 at most, so no size is one). They are where the interface's canvas
would be widened once the fit for it is written.

The version gate: the script stops when main does not hold the 3.0.1 constants NOTES.md "60 fps" names (the 1/30 at
main+0x9b5148, the 0.997 at main+0x9b558c); --no-gate scans another version anyway, and the set's comment then says
so. --selftest runs the scanner over a synthetic image that holds each encoding and checks the sites and the patch
words it emits, with recomp/patches.py parsing and checking the result as gen.py would.
"""
import bisect
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recomp'))

ASPECT = struct.unpack('<I', struct.pack('<f', 16 / 9))[0]     # 0x3fe38e39
INVERSE = struct.unpack('<I', struct.pack('<f', 9 / 16))[0]    # 0x3f100000
SLOT = {ASPECT: 0x60, INVERSE: 0x64}
SET_NAME, SET_ENV = 'aspect', 'XC2_ASPECT'
LANDMARKS = {'3.0.1': [(0x9b5148, 1 / 30), (0x9b558c, 0.997)]}   # NOTES.md "60 fps": main's f32 constants
BACK_LIMIT = 0x400      # how far back an adrp is looked for (bytes), as in fps_sites_xc2.py
MOV_LIMIT = 16          # how many instructions back a movz / movk chain is followed
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


def movz_w(rd, imm16, hw):
    return 0x52800000 | hw << 21 | imm16 << 5 | rd


def movk_w(rd, imm16, hw):
    return 0x72800000 | hw << 21 | imm16 << 5 | rd


def fmov_s_imm(rd, imm8):
    return 0x1E201000 | imm8 << 13 | rd


def ldr_s_lit(rt, pc, target):
    return 0x1C000000 | (((target - pc) >> 2) & 0x7FFFF) << 5 | rt


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


def is_branch(w):
    if w >> 26 in (0x05, 0x25):                                  # b, bl
        return True
    if (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000 or (w & 0x7E000000) == 0x36000000:
        return True                                              # b.cond, cbz / cbnz, tbz / tbnz
    return (w & 0xFFFFFC1F) in (0xD65F0000, 0xD61F0000, 0xD63F0000)   # ret, br, blr


def writes_reg(w, rd):
    """A conservative test: an instruction whose low five bits name rd and that is not a store or a compare."""
    if (w & 31) != rd:
        return False
    store = (w & 0x3B400000) == 0x39000000 or (w & 0x3A400000) == 0x28000000   # STR (imm) / STP
    compare = (w & 0x7F20001F) == 0x6B00001F or (w & 0x7F00001F) == 0x7100001F
    return not store and not compare


# ---- the image
class Image:
    """main's bytes as 32-bit words (little-endian, as the module is), with the segment bounds and the symbols."""

    def __init__(self, image, text, rodata, data, syms=()):
        self.image = bytes(image)
        self.text, self.rodata, self.data = text, rodata, data
        self.words = struct.unpack_from(f'<{len(self.image) // 4}I', self.image)
        funcs = sorted((s[3], s[0]) for s in syms if s[3] and s[2])   # (name, info, shndx, value, size)
        self.func_addrs = [a for a, _ in funcs]
        self.func_names = [s for _, s in funcs]

    @classmethod
    def from_nso(cls, path):
        from nso import Nso
        n = Nso(path)
        return cls(n.image, n.text, n.rodata, n.data, n.syms)

    def word(self, a):
        return self.words[a >> 2]

    def in_text(self, a):
        return self.text[0] <= a < self.text[0] + self.text[1]

    def in_image(self, a):
        return 0 <= a <= len(self.image) - 4

    def name_of(self, off):
        i = bisect.bisect_right(self.func_addrs, off) - 1
        return f'{self.func_names[i]}+{off - self.func_addrs[i]:#x}' if i >= 0 else '?'

    def text_range(self):
        return range(self.text[0], self.text[0] + self.text[1], 4)


# ---- the scan
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


def find_sites(img):
    """(sites, info): sites [(address, original word, replacement words)] of the forms (a) and (b); info [(address,
    what)] for the unpatched forms (c) and (d)."""
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
                        sites.append((a, w, [('page', rn), ldr_s(rt, rn, SLOT[value]), adrp(a, page, rn)]))
                    break
                if writes_reg(v, rn):
                    break
    for a in img.text_range():
        w = img.word(a)
        if is_fmov_s_w(w):
            rd, rn = w & 31, (w >> 5) & 31
            value = value_in_reg(img, a, rn)
            if value in SLOT:
                sites.append((a, w, [('page', rn), ldr_s(rd, rn, SLOT[value])] + mov_words(rn, value)))
        elif is_ldr_s_lit(w):
            t = lit_target(a, w)
            if img.in_image(t) and img.word(t) in SLOT:
                info.append((a, f'ldr s{w & 31}, =main+{t:#x} ({"16/9" if img.word(t) == ASPECT else "9/16"} literal): '
                                'not patched, no address register at the site'))
        elif is_fmov_s_imm(w) and fmov_imm_word((w >> 13) & 0xFF) in SLOT:
            info.append((a, f'fmov s{w & 31}, #0.5625 (9/16 immediate): not patched, no address register at the site'))
    sites.sort()
    return sites, info


def ui_size_sites(img):
    """INFO: [(address, what)] where a logical width and height of the interface are used together."""
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
            found.append((a, (w >> 5) & 0xFFFF, 'movz'))
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
            out.append((min(a, b), f'{v} ({how}) at main+{a:#x} and {u} ({how2}) at main+{b:#x}'))
    return sorted(set(out))


def gate(img):
    """The game version whose landmark constants main holds, or None."""
    for version, marks in LANDMARKS.items():
        if all(img.in_image(a) and img.word(a) == f32(v) for a, v in marks):
            return version
    return None


def emit(sites, version, out=sys.stdout):
    print(f'# XC2 {version} ultrawide aspect (tools/aspect_sites_xc2.py; NOTES.md "Known gaps"). Generated from the '
          'game\'s main.', file=out)
    print(f'set {SET_NAME} {SET_ENV} 1', file=out)
    for a, w, repl in sites:
        words = ' '.join(f'@page:x{r[1]}' if isinstance(r, tuple) else f'{r:08x}' for r in repl)
        print(f'site {SET_NAME} main {a:x} {w:08x} {words}', file=out)


def report(img, sites, info, ui, out=sys.stderr):
    for a, w, repl in sites:
        form = 'adrp+ldr' if is_ldr_s_imm(w) else 'movz/movk+fmov'
        print(f'site main+{a:#x} {img.name_of(a)}: {form} -> +{SLOT[ASPECT] if (repl[1] >> 10 & 0xFFF) * 4 == SLOT[ASPECT] else SLOT[INVERSE]:#x}',
              file=out)
    for a, what in info:
        print(f'INFO main+{a:#x} {img.name_of(a)}: {what}', file=out)
    for a, what in ui:
        print(f'INFO ui size main+{a:#x} {img.name_of(a)}: {what}', file=out)
    print(f'# {len(sites)} aspect loads patched, {len(info)} left (no address register), {len(ui)} interface size '
          'candidates', file=out)


# ---- self test
def selftest():
    import tempfile
    import patches
    text_base, rodata_base = 0x0, 0x2000
    rod = bytearray(0x100)
    struct.pack_into('<IIII', rod, 0x10, ASPECT, INVERSE, f32(1280.0), f32(720.0))
    pad = lambda n: [0x8B030041] * n                  # add x1, x2, x3: writes x1 only
    code = [0xD503201F] * 0x10                        # nop
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
    code += [movz_w(0, 1280, 0), 0xD503201F, movz_w(1, 720, 0)]                            # UI size: INFO
    e1 = len(code) * 4 - 12
    code += [adrp(len(code) * 4, rodata_base, 12), ldr_s(7, 12, 0x18), ldr_s(8, 12, 0x1C)]  # UI size as f32: INFO
    e2 = len(code) * 4 - 8
    while len(code) * 4 < lit:
        code.append(0xD503201F)
    code += [ASPECT, 0xD65F03C0]                                                            # the literal, ret
    text = b''.join(struct.pack('<I', w) for w in code)
    image = bytearray(rodata_base + len(rod))
    image[:len(text)] = text
    image[rodata_base:rodata_base + len(rod)] = rod
    img = Image(image, (text_base, len(text)), (rodata_base, len(rod)), (rodata_base + len(rod), 0),
                syms=[('fn_a', 0, 1, 0x40, 0x100), ('fn_b', 0, 1, 0x140, 0x100)])
    assert fmov_imm_word(0x62) == INVERSE, hex(fmov_imm_word(0x62))
    assert fmov_imm_word(0x70) == f32(1.0) and fmov_imm_word(0x00) == f32(2.0), 'fmov immediate decoding'
    sites, info = find_sites(img)
    assert [a for a, _, _ in sites] == [a1, a2, b1, b2], [hex(a) for a, _, _ in sites]
    by = {a: (w, repl) for a, w, repl in sites}
    assert by[a1] == (ldr_s(0, 8, 0x10), [('page', 8), ldr_s(0, 8, 0x60), adrp(a1, rodata_base, 8)])
    assert by[a2] == (ldr_s(3, 9, 0x14), [('page', 9), ldr_s(3, 9, 0x64), adrp(a2, rodata_base, 9)])
    assert adrp_target(a1, by[a1][1][2]) == rodata_base, 'x8 is pointed back at the constant page'
    assert by[b1] == (0x1E270100, [('page', 8), ldr_s(0, 8, 0x60), movz_w(8, 0x8E39, 0), movk_w(8, 0x3FE3, 1)])
    assert by[b2] == (0x1E270164, [('page', 11), ldr_s(4, 11, 0x64), movz_w(11, 0x3F10, 1)])
    for a in (b1, b2):   # the regenerated moves rebuild the word the original built
        fake = Image(b''.join(struct.pack('<I', w) for w in [0xD503201F] * 4 + by[a][1][2:] + [by[a][0]]),
                     (0, 4 * (5 + len(by[a][1]) - 2)), (0x1000, 0), (0x1000, 0))
        assert value_in_reg(fake, 4 * (4 + len(by[a][1]) - 2), by[a][1][0][1]) in SLOT
    assert [a for a, _ in info] == [c1, d1], [hex(a) for a, _ in info]
    assert 'literal' in info[0][1] and '0.5625' in info[1][1]
    ui = ui_size_sites(img)
    assert [a for a, _ in ui] == [e1, e2], [hex(a) for a, _ in ui]
    assert img.name_of(a1) == f'fn_a+{a1 - 0x40:#x}' and img.name_of(0x10) == '?'
    # The emitted table parses, resolves @page and passes the original-word check, as gen.py --patches runs it.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'patches.txt'
        with open(path, 'w') as f:
            emit(sites, 'selftest', f)
        mods = [('main', 0x10000000, len(image)), ('sdk', 0x10400000, 0x1000)]
        table = patches.load(path, mods)
        assert table.sets == [(SET_NAME, SET_ENV, 1)]
        assert sorted(table.sites['main']) == [a1, a2, b1, b2]

        class Mod:
            base = 0x10000000
            def in_text(self, a): return img.in_text(a - self.base)
            def word(self, a): return img.word(a - self.base)
        patches.check(table, Mod(), 'main')
        resolved = table.for_module('main', 0x10000000)
        assert all(adrp_target(a, words[0]) == table.page for a, (_, words) in resolved.items()), 'adrp to the page'
        bad = Image(bytes(image[:a1]) + b'\0\0\0\0' + bytes(image[a1 + 4:]), img.text, img.rodata, img.data)
        try:
            class BadMod(Mod):
                def word(self, a): return bad.word(a - self.base)
            patches.check(table, BadMod(), 'main')
        except patches.PatchError:
            pass
        else:
            raise AssertionError('a changed original word must fail the check')
    print('aspect_sites_xc2: selftest ok (4 sites, 2 unpatched forms, 2 interface size candidates)')


def main():
    args = sys.argv[1:]
    if args == ['--selftest']:
        return selftest()
    no_gate = '--no-gate' in args
    args = [a for a in args if a != '--no-gate']
    if len(args) != 1:
        sys.exit('usage: aspect_sites_xc2.py <main NSO> [--no-gate] | --selftest')
    img = Image.from_nso(args[0])
    version = gate(img)
    if not version and not no_gate:
        sys.exit('aspect_sites_xc2: main does not hold the 3.0.1 constants NOTES.md names (main+0x9b5148 1/30, '
                 'main+0x9b558c 0.997); another game version? --no-gate scans it anyway')
    sites, info = find_sites(img)
    ui = ui_size_sites(img)
    if not sites:
        sys.exit('aspect_sites_xc2: no patchable loads of 16/9 or 9/16 in main')
    emit(sites, version or 'unknown version (--no-gate)')
    report(img, sites, info, ui)


if __name__ == '__main__':
    main()

"""Every Maxwell shader of XC2: in the .ard archives (bf3.ard and each add-on's bf3_dlc0N.ard) and the exefs main.

An .ard is a run of stored files, most of them "xbc1" containers: magic, compression (1 zlib, 3 zstd), decompressed
size, compressed size, hash, a 28-byte name, then the data. The .arh index is not needed: scanning for the magic finds
every container in seconds, and a false match fails the checks on the header or the decompression. Effect packs nest
more streams inside the decompressed data: xbc1 again, and "cmp\\0zlib" (u32 compressed size, u32 size, zlib data).

Shaders come in three wrappers:

    HCPS   alone in a .wishp or embedded in models and effects. Header words used (index of u32, offsets from the
           container): 8 code offset, 9 code size, 10 control offset, 11 control size.
    SLCT   standalone in main, the boot shaders: an HCPS's selector without the HCPS. Words 10 to 13, offsets from the
           SLCT: control offset, control size, code offset, code size.
    GLSLC  whole compiler outputs in the effect packs (glslc_shaders has the layout).

In HCPS and SLCT the control region is a run of NVN control sections, each padded to 8 bytes, its own length at +0x20
(0x880, shorter when it carries text). The code region holds each section's code in the same order, so the sections'
lengths (control + 0x704) walk both. A blob that does not start with one of CODE_MAGICS ends the walk of that container
and is counted.

A game file is untrusted input, so decompression has limits (Budget, MAX_DEPTH): a stream stops at its declared size, the
streams nested in one file stop at a cumulative cap and a depth, and past any of them the scan fails with ShaderLimitError
instead of keeping part of the data. The memory of the workers together follows what the machine has free (memory_plan).

Needs Python 3.14 (compression.zstd). As a script it prints the census of a RomFS image and its add-on content:

    .venv-py314\\Scripts\\python tools\\ard_shaders.py build\\extracted\\upd
"""
import compression.zstd as zstd
import bisect
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recomp'))
from nso import Nso  # noqa: E402

CONTROL = 0x880
CONTROL_MAGIC = b'\x34\x12\x76\x98'
CODE_MAGICS = (bytes.fromhex('78563412'), bytes.fromhex('79563412'))   # graphics, compute
HCPS = b'HCPS'
SLCT = b'SLCT'
GLSLC = bytes.fromhex('91688619')
XBC1 = b'xbc1'
CMP = b'cmp\0zlib'
RAW_MARKS = (HCPS, GLSLC, CMP)                      # what a stored file can hold outside a compressed container
SPH_STAGES = {1: 'vs', 4: 'gs', 5: 'ps'}            # shader type in SPH word 0; tessellation has no prepared form
SCAN_CHUNK = 256 << 20
# Containers without shaders, by name: textures and animation, more than half of the data.
SKIP = ('.witx', '.witex', '.mot', '.bdat')
BATCH = 256   # entries a worker takes at a time, spread over the archive so a batch's data is about the average
DECODE_STEP = 16 << 20   # output a decoder may produce before the limits are checked again
# Levels of streams inside streams. Generous for effect packs, the files known to nest; the limit only has to stop a
# recursion without end long before Python's own limit does.
MAX_DEPTH = 16
# Bytes one stored file may expand to, its nested streams together. A real file must never hit it, so it is the most a
# single header can declare (a 32-bit size), with the textures and animation, the largest data, skipped before this.
MAX_EXPANDED = 4 << 30
# Past this much a file holds one of the LARGE_SLOTS: most files stay far below it, so the workers run freely.
LARGE = 256 << 20
LARGE_SLOTS = None   # a semaphore shared by the workers, set by init_worker; None runs without (a single process)


class ShaderLimitError(ValueError):
    """A game file whose compressed data goes past a limit: it is damaged or made to exhaust the machine."""


class Budget:
    """What one stored file may expand to. take() counts each decompressed piece before the next is decoded, and past
    LARGE waits for a slot, so that few workers at a time go on to hold a large amount (memory_plan)."""

    def __init__(self, cap=None, slots=None):
        self.used, self.cap, self.slots, self.holding = 0, cap or MAX_EXPANDED, slots or LARGE_SLOTS, False

    def take(self, n):
        self.used += n
        if self.used > self.cap:
            raise ShaderLimitError(f'a stored file expands past the limit of {self.cap >> 20} MiB')
        if self.used > LARGE and self.slots and not self.holding:
            self.slots.acquire()
            self.holding = True

    def give_back(self, n):
        self.used -= n

    def close(self):
        if self.holding:
            self.slots.release()
            self.holding = False


def pieces(kind, body):
    """The decompressed bytes of a zstd (3) or zlib stream, at most DECODE_STEP at a time, so nothing is allocated before
    the caller has seen what came before it. zstd.ZstdError or zlib.error for data that is not such a stream, or ends early."""
    if kind == 3:   # zstd.decompress's rule: frames follow each other until the data ends
        while True:
            decoder = zstd.ZstdDecompressor()
            piece = decoder.decompress(body, max_length=DECODE_STEP)
            while True:
                if piece:
                    yield piece
                if decoder.eof or decoder.needs_input:
                    break
                piece = decoder.decompress(b'', max_length=DECODE_STEP)
            if not decoder.eof:
                raise zstd.ZstdError('compressed data ended before the end of its frame')
            body = decoder.unused_data
            if not body:
                return
    else:
        decoder = zlib.decompressobj()
        piece = decoder.decompress(body, DECODE_STEP)
        while True:
            if piece:
                yield piece
            if decoder.eof:
                return
            if not decoder.unconsumed_tail and not piece:
                raise zlib.error('compressed data ended before the end of its stream')
            piece = decoder.decompress(decoder.unconsumed_tail, DECODE_STEP)


def bounded(kind, body, declared, budget):
    """A stream's bytes, whole or not at all: ShaderLimitError when it holds more than its header declares (the game
    allocates that size, so a genuine stream fits) or the budget runs out. declared None: a header whose size field is
    not relied on, so only the budget applies. Bytes that only look like a stream raise the decoder's error and give back
    what they used."""
    parts, total = [], 0
    try:
        for piece in pieces(kind, body):
            total += len(piece)
            if declared is not None and total > declared:
                raise ShaderLimitError(f'a stream holds more than the {declared} bytes its header declares')
            budget.take(len(piece))
            parts.append(piece)
    except (zstd.ZstdError, zlib.error):
        budget.give_back(total)
        raise
    return b''.join(parts)


def stage_of(code):
    """vs, gs, ps or cs from the code's header, None for the others: graphics code opens with 0x30 bytes before the SPH."""
    if code[:4] == CODE_MAGICS[1]:
        return 'cs'
    if code[:4] != CODE_MAGICS[0] or len(code) < 0x34:
        return None
    return SPH_STAGES.get(struct.unpack_from('<I', code, 0x30)[0] >> 10 & 0xf)


def shader(data, c, code):
    """(key, stage, control, code). The control is 0x880 bytes whatever its own length: what follows it is what the runtime
    reads and hashes (gfx_shader.c build_code_hash)."""
    control = data[c:c + CONTROL].ljust(CONTROL, b'\0')
    return hashlib.sha256(control + code).hexdigest(), stage_of(code), control, code


def walk(data, c, control_end, pos, code_end, damaged):
    """The shaders of a control region and its code region. damaged[0] counts walks ended by a bad blob."""
    while c < control_end:
        if c + 0x708 > control_end:
            damaged[0] += 1
            return
        size = struct.unpack_from('<I', data, c + 0x20)[0]
        c1, length = struct.unpack_from('<II', data, c + 0x700)
        if data[c:c + 4] != CONTROL_MAGIC or not 0x760 <= size <= CONTROL or c + size > control_end or not 0 < length \
                or pos + length > code_end or data[pos:pos + 4] not in CODE_MAGICS or c1 > length:
            damaged[0] += 1
            return
        found = shader(data, c, data[pos:pos + length])
        if found[1]:
            yield found
        c += (size + 7) & ~7
        pos += length if data[pos + length:pos + length + 4] in CODE_MAGICS else (length + 0xff) & ~0xff


def hcps_shaders(data, at, damaged):
    words = struct.unpack_from('<12I', data, at)
    code_at, code_size, control_at, control_size = at + words[8], words[9], at + words[10], words[11]
    if code_at + code_size <= len(data) and control_at + control_size <= len(data):
        yield from walk(data, control_at, control_at + control_size, code_at, code_at + code_size, damaged)


def slct_shaders(data, at, damaged):
    if at + 72 > len(data):
        return
    c, control_size, k, code_size = struct.unpack_from('<4I', data, at + 40)
    if min(c, k) >= 72 and at + max(c + control_size, k + code_size) <= len(data):
        yield from walk(data, at + c, at + c + control_size, at + k, at + k + code_size, damaged)


def glslc_shaders(data, at):
    """The shaders of a GLSLC output. Output +0x44 is its whole length, +0x4c its section count; section i's header is at
    +0x90 + 0x90 i: size, offset from the output, type (0 GPU code), and for GPU code at +0x30 the control offset, code
    offset and code length, from the section's data."""
    if at + 0x90 > len(data):
        return
    size, _, count = struct.unpack_from('<3I', data, at + 0x44)
    if not 0 < count <= 16 or not 0x90 * (count + 1) <= size <= len(data) - at:
        return
    for head in range(at + 0x90, at + 0x90 + 0x90 * count, 0x90):
        section_size, offset, kind = struct.unpack_from('<3I', data, head)
        control_at, code_at, code_size = struct.unpack_from('<3I', data, head + 0x30)
        if kind or offset + section_size > size or max(control_at + 0x708, code_at + code_size) > section_size:
            continue
        c, code = at + offset + control_at, at + offset + code_at
        found = shader(data, c, data[code:code + code_size])
        if data[c:c + 4] == CONTROL_MAGIC and found[1]:
            yield found


def inflated(data, at, budget):
    """The bytes of the compressed stream at `at`, None for a stored stream or bytes that only look like a header."""
    try:
        if data[at:at + 4] == XBC1:
            kind, size, packed = struct.unpack_from('<3I', data, at + 4)
            if kind not in (1, 3) or not packed or not size or at + 48 + packed > len(data):
                return None
            return bounded(kind, data[at + 48:at + 48 + packed], size, budget)
        # The size after the compressed size has never been read for anything and no real pack has been checked against
        # it, so a "cmp" stream answers to the cumulative cap alone.
        packed = struct.unpack_from('<I', data, at + 8)[0]
        return bounded(1, data[at + 16:at + 16 + packed], None, budget) if packed and at + 16 + packed <= len(data) else None
    except (struct.error, zstd.ZstdError, zlib.error):
        return None


def marks(data, magic):
    at = -1
    while (at := data.find(magic, at + 1)) >= 0:
        yield at


def data_shaders(data, damaged, budget=None, depth=0):
    """The shaders of one decompressed file, the streams nested in it included. A stored xbc1 needs no step of its own:
    its contents are in `data` as they are."""
    budget = budget or Budget()
    for magic in (XBC1, CMP):
        for at in marks(data, magic):
            inner = inflated(data, at, budget)
            if inner:
                if depth >= MAX_DEPTH:
                    raise ShaderLimitError(f'streams nested deeper than {MAX_DEPTH} levels')
                yield from data_shaders(inner, damaged, budget, depth + 1)
    for at in marks(data, HCPS):
        if at + 48 <= len(data):
            yield from hcps_shaders(data, at, damaged)
    for at in marks(data, GLSLC):
        yield from glslc_shaders(data, at)


def scan(path, offset, size):
    """Entries of an archive stored at offset, (offset, compression, decompressed, compressed, name), and the shader
    markers found outside them, each of which runs to the next container: its size is not known."""
    entries, raw = [], []
    with open(path, 'rb') as f:
        for pos in range(0, size, SCAN_CHUNK):
            f.seek(offset + pos)
            chunk = f.read(min(SCAN_CHUNK, size - pos) + 48)
            limit = min(SCAN_CHUNK, len(chunk) - 48)
            at = 0
            while 0 <= (at := chunk.find(XBC1, at)) < limit:
                kind, dec, comp, _ = struct.unpack_from('<4I', chunk, at + 4)
                name = chunk[at + 20:at + 48].split(b'\0')[0]
                if kind in (1, 3) and dec and comp and all(32 <= c < 127 for c in name):
                    entries.append((offset + pos + at, kind, dec, comp, name.decode()))
                at += 4
            for magic in RAW_MARKS:
                raw += [offset + pos + at for at in marks(chunk, magic) if at < limit]
    entries.sort()
    raw.sort()
    starts = [e[0] for e in entries]
    return [e for e in entries if not e[4].endswith(SKIP)], raw, starts


def init_worker(slots):
    global LARGE_SLOTS
    LARGE_SLOTS = slots


def worker(job):
    path, entries, raw = job
    found, bad, damaged = {}, 0, [0]
    with open(path, 'rb') as f:
        for at, kind, dec, comp, name in entries:
            f.seek(at + 48)
            budget = Budget()
            try:
                try:
                    data = bounded(kind, f.read(comp), dec, budget)
                except (zstd.ZstdError, zlib.error):
                    bad += 1
                    continue
                for key, stage, control, code in data_shaders(data, damaged, budget):
                    found.setdefault(key, (stage, control, code))
            except ShaderLimitError as e:   # the file's name and place, also for a limit found deep inside it
                raise ShaderLimitError(f'{Path(path).name} at {at:#x} ({name}): {e}') from None
            finally:
                budget.close()
        for at, size in raw:
            f.seek(at)
            budget = Budget()
            try:
                budget.take(size)
                for key, stage, control, code in data_shaders(f.read(size), damaged, budget):
                    found.setdefault(key, (stage, control, code))
            except ShaderLimitError as e:
                raise ShaderLimitError(f'{Path(path).name} at {at:#x}: {e}') from None
            finally:
                budget.close()
    return found, bad, damaged[0]


def available_memory():
    """Bytes the machine can give without swapping, None when it cannot say."""
    try:
        if os.name == 'nt':
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                            ('available', ctypes.c_ulonglong), ('rest', ctypes.c_ulonglong * 5)]
            status = Status(length=ctypes.sizeof(Status))
            return status.available if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) << 10
    except (OSError, ValueError, AttributeError):
        pass
    return None


def memory_plan(workers, available):
    """(workers, large slots) that keep the scan within half of the available memory: each worker up to LARGE, and each
    slot's holder up to the cap, twice while it joins its pieces. At least one of each, so a file within the limits is
    always scanned, if slowly. Without a figure, assumes what a low-end machine has free."""
    budget = (available or 8 << 30) // 2
    workers = max(1, min(workers, budget // LARGE))
    return workers, max(1, (budget - workers * LARGE) // (2 * MAX_EXPANDED))


def archives(root):
    """(path of the image, offset, size, name) of each .ard under an install-shaped folder: romfs/
    (romfs.bin and index.json) and aoc/<index>/."""
    index = json.loads((root / 'romfs' / 'index.json').read_text(encoding='utf-8'))
    for row in index['files']:
        if row['path'].endswith('.ard'):
            yield root / 'romfs' / 'romfs.bin', row['offset'], row['size'], row['path']
    for path in sorted((root / 'aoc').glob('*/*.ard')):
        yield path, 0, path.stat().st_size, path.name


def main_shaders(root):
    """The shaders in main's image: its SLCT, and any GLSLC output. No main (a folder of data alone) gives none."""
    path = root / 'exefs' / 'main'
    if not path.is_file():
        return
    image = bytes(Nso(path).image)
    for at in marks(image, SLCT):
        yield from slct_shaders(image, at, [0])   # a chance SLCT in code: the walk stops at once
    for at in marks(image, GLSLC):
        yield from glslc_shaders(image, at)


def inventory(root, progress=None, workers=None):
    """Every unique shader under root: key -> dict(stage, control, code, source). Also returns the problems found:
    entries that failed to decompress and HCPS walks that ended early. progress(done, total) counts entries."""
    shaders, bad, damaged = {}, 0, 0
    workers, slots = memory_plan(workers or max(1, min(os.cpu_count() or 1, 16)), available_memory())
    sources = list(archives(root))
    jobs = []
    for path, offset, size, name in sources:
        entries, raw, starts = scan(path, offset, size)
        spans = {}
        for at in raw:   # a stored run: from its first marker up to the next xbc1, within what one model can hold
            i = bisect.bisect_right(starts, at)
            spans.setdefault(starts[i] if i < len(starts) else offset + size, at)
        spans = [(at, min(stop - at, 256 << 20)) for stop, at in spans.items()]
        n = max(1, len(entries) // BATCH)
        jobs += [(name, path, entries[i::n], spans if i == 0 else []) for i in range(n)]
    total = sum(len(j[2]) for j in jobs)
    done = 0
    for key, stage, control, code in main_shaders(root):
        shaders.setdefault(key, dict(stage=stage, control=control, code=code, source='main', origin='main', startup=True))
    context = multiprocessing.get_context()
    with concurrent.futures.ProcessPoolExecutor(workers, mp_context=context, initializer=init_worker,
                                                initargs=(context.BoundedSemaphore(slots),)) as pool:
        for (name, _, entries, _), (found, b, d) in zip(jobs, pool.map(worker, [j[1:] for j in jobs])):
            for key, (stage, control, code) in found.items():
                shaders.setdefault(key, dict(stage=stage, control=control, code=code, source=name, origin='ard',
                                             startup=name == 'bf3.ard'))
            bad += b
            damaged += d
            done += len(entries)
            if progress:
                progress(done, total)
    return shaders, dict(undecoded=bad, damaged=damaged)


def main():
    root = Path(sys.argv[1])
    try:
        shaders, problems = inventory(root, lambda d, t: print(f'\r{d} of {t}', end='', flush=True))
    except ShaderLimitError as e:
        sys.exit(f'\nerror: {e}')
    print()
    by = {}
    for s in shaders.values():
        by[s['source']] = by.get(s['source'], 0) + 1
    print(f'{len(shaders)} shaders, code {sum(len(s["code"]) for s in shaders.values()) >> 20} MiB, {by}, {problems}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

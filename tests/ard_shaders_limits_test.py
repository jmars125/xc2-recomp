"""tools/ard_shaders.py's limits on decompression, on made-up archives: a file within them scans whole, whichever
compression and however large, and a declared size, depth or cumulative cap that is passed fails with a clear error.

Run under .venv-py314: python tests/ard_shaders_limits_test.py
"""
import compression.zstd as zstd
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import ard_shaders as ard  # noqa: E402

CODE_LENGTH = 0x100


def compress(kind, data):
    return zstd.compress(data) if kind == 3 else zlib.compress(data)


def xbc1(data, kind=3, declared=None, name=b'test.bin'):
    packed = compress(kind, data)
    size = len(data) if declared is None else declared
    return ard.XBC1 + struct.pack('<4I', kind, size, len(packed), 0) + name.ljust(28, b'\0') + packed


def cmp_zlib(data, declared=None):
    packed = zlib.compress(data)
    return ard.CMP + struct.pack('<II', len(packed), len(data) if declared is None else declared) + packed


def hcps(seed=b'\xaa'):
    """An HCPS holding one compute shader: the header words the walk reads, a control section and its code."""
    control = bytearray(ard.CONTROL)
    control[:4] = ard.CONTROL_MAGIC
    struct.pack_into('<I', control, 0x20, ard.CONTROL)
    struct.pack_into('<II', control, 0x700, 0, CODE_LENGTH)
    code = (ard.CODE_MAGICS[1] + seed * CODE_LENGTH)[:CODE_LENGTH]
    words = [0] * 12
    words[8:12] = 48, CODE_LENGTH, 48 + CODE_LENGTH, ard.CONTROL
    return ard.HCPS + struct.pack('<11I', *words[1:]) + code + bytes(control)


def keys(data, budget=None):
    return [s[0] for s in ard.data_shaders(data, [0], budget)]


class LimitsTest(unittest.TestCase):
    def test_a_shader_is_found_in_each_wrapper(self):
        direct = keys(hcps())
        self.assertEqual(len(direct), 1)
        for wrapped in (xbc1(hcps()), xbc1(hcps(), kind=1), cmp_zlib(hcps()), xbc1(xbc1(hcps()) + cmp_zlib(hcps(b'\xbb')))):
            self.assertIn(direct[0], keys(wrapped))

    def test_every_decoding_step_gives_the_whole_stream(self):
        data = bytes(range(256)) * ((3 * ard.DECODE_STEP) // 256 + 7)   # several decode steps, not a whole number of them
        for kind in (1, 3):
            with self.subTest(kind=kind):
                self.assertEqual(ard.bounded(kind, compress(kind, data), len(data), ard.Budget()), data)

    def test_zstd_frames_that_follow_each_other_are_read_like_zstd_decompress(self):
        data = zstd.compress(b'first') + zstd.compress(b'second')
        self.assertEqual(ard.bounded(3, data, 11, ard.Budget()), zstd.decompress(data))

    def test_a_large_shader_within_the_declared_size_is_not_truncated(self):
        shader = hcps()
        padded = bytes(40 << 20) + shader   # past a decode step, so a truncating reader would lose the shader
        self.assertEqual(keys(xbc1(padded)), keys(shader))

    def test_a_stream_larger_than_declared_fails(self):
        for stream in (xbc1(bytes(1 << 20), declared=1024), xbc1(bytes(1 << 20), kind=1, declared=1024)):
            with self.assertRaisesRegex(ard.ShaderLimitError, 'more than the 1024 bytes'):
                keys(stream)

    def test_a_cmp_stream_answers_to_the_cumulative_cap_alone(self):
        stream = cmp_zlib(bytes(1 << 20) + hcps(), declared=1024)
        self.assertEqual(keys(stream), keys(hcps()))
        with self.assertRaisesRegex(ard.ShaderLimitError, 'expands past'):
            keys(stream, ard.Budget(cap=1 << 19))

    def test_a_bomb_stops_at_the_step_not_at_its_end(self):
        bomb = zlib.compress(bytes(1 << 30))
        out = ard.pieces(1, bomb)
        self.assertLessEqual(len(next(out)), ard.DECODE_STEP)
        out.close()
        with mock.patch.object(ard.Budget, 'take', side_effect=ard.ShaderLimitError('stop')) as take:
            with self.assertRaises(ard.ShaderLimitError):
                ard.bounded(1, bomb, 1 << 30, ard.Budget())
        self.assertEqual(take.call_count, 1)

    def test_the_cumulative_cap_counts_nested_streams_together(self):
        inner = xbc1(bytes(1 << 20))
        twelve = b''.join(inner + bytes(1) for _ in range(12))
        self.assertEqual(keys(twelve, ard.Budget(cap=13 << 20)), [])
        with self.assertRaisesRegex(ard.ShaderLimitError, 'expands past the limit of 10 MiB'):
            keys(twelve, ard.Budget(cap=10 << 20))

    def test_nesting_at_the_depth_limit_passes_and_past_it_fails(self):
        def nested(levels):
            data = hcps()
            for _ in range(levels):
                data = xbc1(data)
            return data
        self.assertEqual(len(keys(nested(ard.MAX_DEPTH))), 1)
        with self.assertRaisesRegex(ard.ShaderLimitError, 'nested deeper'):
            keys(nested(ard.MAX_DEPTH + 1))

    def test_bytes_that_only_look_like_a_stream_are_skipped_and_cost_nothing(self):
        junk = ard.XBC1 + struct.pack('<4I', 3, 0xffffffff, 64, 0) + bytes(28) + b'\x55' * 64
        partial = xbc1(bytes(1 << 16))[:-8]   # decodes for a while, then ends early
        budget = ard.Budget(cap=1 << 20)
        self.assertEqual(keys(junk + partial + hcps(), budget), keys(hcps()))
        self.assertEqual(budget.used, 0)

    def test_a_large_file_holds_one_slot_and_returns_it(self):
        slots = mock.Mock()
        budget = ard.Budget(slots=slots)
        budget.take(ard.LARGE)
        slots.acquire.assert_not_called()
        budget.take(1)
        budget.take(1)
        slots.acquire.assert_called_once()
        budget.close()
        budget.close()
        slots.release.assert_called_once()

    def test_memory_plan_stays_within_half_of_what_is_free(self):
        for available in (2 << 30, 8 << 30, 16 << 30, 64 << 30, 256 << 30):
            workers, slots = ard.memory_plan(16, available)
            self.assertGreaterEqual(workers, 1)
            self.assertGreaterEqual(slots, 1)
            if slots > 1:
                self.assertLessEqual(workers * ard.LARGE + slots * 2 * ard.MAX_EXPANDED, available // 2)
        self.assertEqual(ard.memory_plan(16, 64 << 30)[0], 16)      # a normal machine keeps its speed
        self.assertEqual(ard.memory_plan(16, 2 << 30)[0], 4)        # a tight one gives up workers
        self.assertEqual(ard.memory_plan(16, None), ard.memory_plan(16, 8 << 30))
        self.assertEqual(ard.memory_plan(1, 256 << 30)[0], 1)

    def test_available_memory_reads_a_figure_here(self):
        self.assertGreater(ard.available_memory() or 1, 0)


class InventoryTest(unittest.TestCase):
    """The whole scan, worker processes included, on an install-shaped folder."""

    def install(self, d, stored):
        romfs = d / 'romfs'
        romfs.mkdir()
        (romfs / 'romfs.bin').write_bytes(stored)
        (romfs / 'index.json').write_text(json.dumps({'files': [{'path': 'bf3.ard', 'offset': 0, 'size': len(stored)}]}))
        return d

    def test_shaders_come_through_the_workers(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.install(Path(d), xbc1(hcps()) + xbc1(cmp_zlib(hcps(b'\xbb')), kind=1))
            shaders, problems = ard.inventory(root, workers=2)
        self.assertEqual(len(shaders), 2)
        self.assertEqual(problems, {'undecoded': 0, 'damaged': 0})
        self.assertEqual(sorted(shaders), sorted(hashlib.sha256(s[2] + s[3]).hexdigest()
                                                 for s in [*ard.data_shaders(hcps(), [0]),
                                                           *ard.data_shaders(hcps(b'\xbb'), [0])]))

    def test_a_limit_in_a_worker_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.install(Path(d), xbc1(bytes(1 << 20), declared=1024, name=b'bomb.wishp'))
            with self.assertRaisesRegex(ard.ShaderLimitError, r'romfs\.bin at 0x0 \(bomb\.wishp\).*1024 bytes'):
                ard.inventory(root, workers=2)

    def test_a_corrupt_entry_is_still_counted_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            broken = bytearray(xbc1(bytes(1024), name=b'x.bin'))
            broken[48:52] = b'\x55\x55\x55\x55'
            root = self.install(Path(d), bytes(broken))
            shaders, problems = ard.inventory(root, workers=2)
        self.assertEqual((shaders, problems['undecoded']), ({}, 1))


if __name__ == '__main__':
    unittest.main()

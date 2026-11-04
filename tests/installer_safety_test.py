"""Safety checks of the installer and the extraction scripts, on fabricated inputs: no game files, no real keys. Tools
that would read game data (hactool, the Vulkan loader) are small stand-ins written here.

Run: python tests/installer_safety_test.py
"""
import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from installer import state as statefile  # noqa: E402
from installer import steps  # noqa: E402
from installer.steps import extract  # noqa: E402
import exefs_xc2  # noqa: E402  (tools/, on the path once installer.steps is imported)
import extract_exefs  # noqa: E402  (the retargeted module tools/exefs_xc2.py registered)
from installer.events import Reporter  # noqa: E402
from installer.runner import Context, InstallError  # noqa: E402

GOOD_DEVICE = {'name': 'Good', 'api': [1, 3, 0], 'type': 2, 'missing': []}
LACKING_DEVICE = {'name': 'Lacking', 'api': [1, 3, 0], 'type': 2, 'missing': ['VK_A', 'VK_B']}

# A Vulkan loader with one 1.3 device that offers the swapchain extension only.
FAKE_LOADER = r'''
#include <string.h>
#include <vulkan/vulkan.h>
static VKAPI_ATTR VkResult VKAPI_CALL create(const VkInstanceCreateInfo *c, const VkAllocationCallbacks *a, VkInstance *i) {
    *i = (VkInstance)1; return VK_SUCCESS;
}
static VKAPI_ATTR void VKAPI_CALL destroy(VkInstance i, const VkAllocationCallbacks *a) {}
static VKAPI_ATTR VkResult VKAPI_CALL devices(VkInstance i, uint32_t *n, VkPhysicalDevice *d) {
    *n = 1; d[0] = (VkPhysicalDevice)1; return VK_SUCCESS;
}
static VKAPI_ATTR void VKAPI_CALL props(VkPhysicalDevice d, VkPhysicalDeviceProperties *p) {
    memset(p, 0, sizeof *p); strcpy(p->deviceName, "Fake GPU"); p->apiVersion = VK_API_VERSION_1_3;
}
static VKAPI_ATTR VkResult VKAPI_CALL exts(VkPhysicalDevice d, const char *l, uint32_t *n, VkExtensionProperties *e) {
    if (e) strcpy(e[0].extensionName, VK_KHR_SWAPCHAIN_EXTENSION_NAME);
    *n = 1; return VK_SUCCESS;
}
__attribute__((visibility("default"))) PFN_vkVoidFunction vkGetInstanceProcAddr(VkInstance i, const char *n) {
    if (!strcmp(n, "vkCreateInstance")) return (PFN_vkVoidFunction)create;
    if (!strcmp(n, "vkDestroyInstance")) return (PFN_vkVoidFunction)destroy;
    if (!strcmp(n, "vkEnumeratePhysicalDevices")) return (PFN_vkVoidFunction)devices;
    if (!strcmp(n, "vkGetPhysicalDeviceProperties")) return (PFN_vkVoidFunction)props;
    if (!strcmp(n, "vkEnumerateDeviceExtensionProperties")) return (PFN_vkVoidFunction)exts;
    return 0;
}
'''


def required_list(path):
    """The extension macros of the k_required_ext array in a C file."""
    text = path.read_text(encoding='utf-8')
    return re.findall(r'VK_\w+_EXTENSION_NAME', re.search(r'k_required_ext\[\] = \{(.*?)\};', text, re.S).group(1))


# hactool's stand-in: records where it was told to find the keys, then writes the merged image as hactool would.
FAKE_HACTOOL = r'''#!PYTHON
import json, os, sys
keys = sys.argv[sys.argv.index('-k') + 1]
titles = os.environ['MNG_TITLE_KEYS']
seen = {'keys': keys, 'titles': titles, 'folder_mode': os.stat(os.path.dirname(keys)).st_mode & 0o777}
open(os.environ['FAKE_HACTOOL_SEEN'], 'w').write(json.dumps(seen))
if os.environ.get('FAKE_HACTOOL_FAIL'):
    print('Failed to read')
    sys.exit(1)
for arg in sys.argv:
    if arg.startswith('--section0='):
        open(arg.split('=', 1)[1], 'wb').write(b'merged')
for i in range(6):
    print(f'        Level {i} (GOOD):')
'''


def fake_hactool(folder):
    tool = folder / 'hactool'
    tool.write_text(FAKE_HACTOOL.replace('PYTHON', sys.executable))
    tool.chmod(0o755)
    return tool


class KeysFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.game = self.dir / 'game folder'
        self.temp = self.dir / 'temp'
        self.logs = self.dir / 'logs'
        for folder in (self.game, self.temp, self.logs):
            folder.mkdir()
        self.keys = self.dir / 'dummy.keys'
        self.keys.write_text('header_key = ' + '00' * 32 + '\n')
        self.seen = self.dir / 'seen.json'

    def tearDown(self):
        self.tmp.cleanup()

    def merge(self, **env):
        record = {'nca_offset': 0, 'size': 1}
        header = bytearray(0x1000)
        header[0x400 + 4] = 4
        inputs = [(self.game / 'base.nsp', record, header), (self.game / 'update.nsp', record, header)]
        with mock.patch.object(extract, 'program_ncas', return_value=({bytes(16): bytes(16)}, inputs)), \
                mock.patch.object(extract, 'copy_range', side_effect=lambda s, o, n, t: Path(t).write_bytes(b'nca')), \
                mock.patch.object(extract, 'index_romfs', return_value=[]), \
                mock.patch.object(extract, 'record_offset', return_value=0), \
                mock.patch.object(extract.shutil, 'disk_usage', return_value=SimpleNamespace(free=1 << 50)), \
                mock.patch.dict(os.environ, {'FAKE_HACTOOL_SEEN': str(self.seen), **env}):
            extract.merge_update_romfs(self.game / 'base.nsp', self.game / 'update.nsp', self.keys, fake_hactool(self.dir),
                                       self.game / 'romfs', self.logs, phase=lambda name: None,
                                       key_root=self.temp / steps.KEYS_FOLDER)

    @unittest.skipUnless(os.name == 'posix', 'the stand-in for hactool is a script')
    def test_merge_keeps_key_files_out_of_the_output_folder(self):
        self.merge()
        seen = json.loads(self.seen.read_text())
        for path in (seen['keys'], seen['titles']):
            self.assertTrue(Path(path).is_relative_to(self.temp / steps.KEYS_FOLDER), path)
            self.assertFalse(Path(path).exists(), path)
        self.assertEqual(seen['folder_mode'], stat.S_IRWXU)
        self.assertEqual((self.game / 'romfs' / 'romfs.bin').read_bytes(), b'merged')
        self.assertEqual(sorted(p.name for p in self.game.iterdir()), ['romfs'])
        self.assertEqual(list((self.temp / steps.KEYS_FOLDER).iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'the stand-in for hactool is a script')
    def test_a_failed_merge_removes_the_key_files(self):
        with self.assertRaises(ValueError):
            self.merge(FAKE_HACTOOL_FAIL='1')
        self.assertFalse(Path(json.loads(self.seen.read_text())['keys']).exists())
        self.assertEqual(list((self.temp / steps.KEYS_FOLDER).iterdir()), [])

    def test_the_next_run_removes_what_a_killed_run_left(self):
        left = [self.temp / steps.KEYS_FOLDER / 'keys-abc' / 'title.keys', self.temp / 'dlc' / 'hactool.keys',
                self.game / 'update-merge-x' / 'hactool.keys']
        kept = [self.temp / 'dlc' / '1.nca', self.game / 'update-merge-x' / 'base.nca']
        for path in left + kept:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('dummy')
        layout = SimpleNamespace(missing=lambda: ['bin/hactool'])
        ctx = SimpleNamespace(layout=layout, temp=self.temp, dest=self.game, reporter=Reporter(out=io.StringIO()))
        with self.assertRaises(InstallError):   # even a run that stops at its first check cleans up
            steps.Check().run(ctx)
        self.assertEqual([p for p in left if p.exists()], [])
        self.assertEqual([p for p in kept if not p.exists()], [])


def pfs0(names):
    """A PFS0 of empty files under these names."""
    strings = b''.join(n.encode() + b'\0' for n in names)
    table, name_at = b'', 0
    for name in names:
        table += struct.pack('<QQII', 0, 0, name_at, 0)
        name_at += len(name.encode()) + 1
    return b'PFS0' + struct.pack('<III', len(names), len(strings), 0) + table + strings


class PartitionNameTest(unittest.TestCase):
    UNSAFE = ('C:probe.txt', 'C:', 'c:\\x', 'file.txt:stream', 'NUL', 'nul.txt', 'CON', 'con.tar.gz', 'AUX', 'PRN.x', 'COM1',
              'lpt9.dat', 'COM\u00b9', 'CONIN$', 'NUL .txt', 'name.', 'name ', ' name', 'a\nb', 'a\x01b', 'a\x7fb', 'a?b', 'a*b',
              'a|b', 'a"b', 'a<b', 'a>b', '.', '..', '', 'a/b', 'a\\b', '\\\\srv\\share\\x')
    SAFE = ('main', 'main.npdm', 'rtld', 'sdk', 'subsdk0', 'secure', 'normal', 'update', 'logo',
            '0123456789abcdef0123456789abcdef.cnmt.nca', '0123456789abcdef0123456789abcdef.nca',
            '01000000000000000000000000000000.tik', '01000000000000000000000000000000.cert', 'COM10', 'console.txt',
            'nullable', '.hidden', 'файл.nca')

    def test_a_drive_form_would_leave_the_output_folder(self):
        # Why the vendored check is not enough: it has no slash and no dots, and Windows paths drop the left side.
        self.assertEqual(str(PureWindowsPath('out') / 'C:probe.txt'), 'C:probe.txt')

    def test_names(self):
        self.assertEqual([n for n in self.UNSAFE if exefs_xc2.safe_partition_name(n)], [])
        self.assertEqual([n for n in self.SAFE if not exefs_xc2.safe_partition_name(n)], [])

    def test_the_swap_reaches_the_table_reader(self):
        for name in ('C:probe.txt', 'NUL', 'name.', 'a/b', '..'):
            with self.assertRaisesRegex(ValueError, 'Unsafe partition filename'):
                extract_exefs.partition_entries(io.BytesIO(pfs0([name])), 0, 1 << 20)
        self.assertEqual([e[0] for e in extract_exefs.partition_entries(io.BytesIO(pfs0(['main', 'main.npdm'])), 0, 1 << 20)],
                         ['main', 'main.npdm'])

    def test_the_extraction_script_refuses_a_crafted_package(self):
        # The script runs in a process of its own: its module has to get the swap too.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            game = d / 'crafted.nsp'
            game.write_bytes(pfs0(['C:probe.nca']))
            keys = d / 'dummy.keys'
            keys.write_text('header_key = ' + '00' * 32 + '\n')
            with self.assertRaises(ValueError):
                extract.extract_exefs(game, keys, d / 'out', d, update=False)
            self.assertIn('Unsafe partition filename', (d / 'extract_exefs-out.log').read_text(encoding='utf-8'))
            self.assertFalse((d / 'out' / 'exefs').exists() and list((d / 'out' / 'exefs').iterdir()))

    def test_the_vendored_file_is_left_alone(self):
        source = (ROOT / 'tools' / 'vendor' / 'macnativegames' / 'extract_exefs.py').read_text(encoding='utf-8')
        self.assertNotIn('safe_partition_name', source)


class RomfsRepairTest(unittest.TestCase):
    """Extract's decision about an image that changed after it was recorded, with made-up files and the merge replaced."""
    GOOD = b'genuine game data'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dest, self.temp = self.dir / 'dest', self.dir / 'temp'
        self.dest.mkdir()
        (self.temp / 'check').mkdir(parents=True)
        self.modules = {n: n.encode() for n in (*extract.EXEFS_CODE, 'main.npdm')}
        expected = {'version': 1, 'display_version': '3.0.1',
                    'exefs_sha256': {n: hashlib.sha256(d).hexdigest() for n, d in self.modules.items()},
                    'romfs': {'size': len(self.GOOD), 'sha256': hashlib.sha256(self.GOOD).hexdigest()}}
        self.expected = self.dir / 'expected.json'
        self.expected.write_text(json.dumps(expected))
        self.layout = SimpleNamespace(release='r1', expected=lambda version: self.expected)
        self.options = SimpleNamespace()
        for name in ('base', 'update', 'keys'):
            path = self.dir / name
            path.write_bytes(b'dummy')
            setattr(self.options, name, path)
        self.state = statefile.empty('r1')
        self.state['version'] = '3.0.1'
        self.merges = 0
        self.step = steps.Extract()

    def tearDown(self):
        self.tmp.cleanup()

    def write_good_image(self, *_):
        self.merges += 1
        romfs = self.dest / 'romfs'
        romfs.mkdir(exist_ok=True)
        (romfs / 'romfs.bin').write_bytes(self.GOOD)
        (romfs / 'index.json').write_text(json.dumps({'romfs_size': len(self.GOOD), 'files': [],
                                                      'romfs_sha256': hashlib.sha256(self.GOOD).hexdigest()}))

    def context(self, forced=()):
        """A context planned the way run_steps plans it, with the verify pass of the check step done."""
        ctx = Context(self.layout, self.dest, self.temp, Reporter(out=io.StringIO()), self.options, state=self.state)
        ctx.steps = [self.step]
        ctx.plan(forced)
        ctx.verify_kept('check')
        return ctx

    def run_step(self, forced=()):
        ctx = self.context(forced)
        if ctx.will_run('extract'):
            staged = self.temp / 'check' / 'update' / 'exefs'
            staged.mkdir(parents=True, exist_ok=True)
            for name, data in self.modules.items():
                (staged / name).write_bytes(data)
            with mock.patch.object(steps.Extract, 'merge', side_effect=self.write_good_image):
                fields = self.step.run(ctx)
            self.state['steps']['extract'] = {'key': ctx.keys['extract'], 'release': 'r1', **fields}
        return ctx

    def later(self, data=None):
        """Rewrite the image (or just touch it), with a modification time the record cannot hold."""
        image = self.dest / 'romfs' / 'romfs.bin'
        if data is not None:
            image.write_bytes(data)
        st = image.stat()
        os.utime(image, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))

    def test_a_fresh_extraction_is_current_afterwards(self):
        self.run_step()
        self.assertEqual(self.merges, 1)
        self.assertFalse(self.context().will_run('extract'))

    def test_same_size_damage_is_merged_again(self):
        self.run_step()
        self.later(bytes(len(self.GOOD)))
        ctx = self.context()
        self.assertTrue(ctx.will_run('extract'))
        self.run_step()
        self.assertEqual(self.merges, 2)
        self.assertEqual((self.dest / 'romfs' / 'romfs.bin').read_bytes(), self.GOOD)
        self.assertFalse(self.context().will_run('extract'))   # and not because damage was recorded as current

    def test_an_intact_image_with_a_new_time_is_hashed_and_kept(self):
        self.run_step()
        self.later()
        self.run_step()
        self.assertEqual(self.merges, 1)
        self.assertFalse(self.context().will_run('extract'))

    def test_a_damaged_image_without_a_record_is_merged_again(self):
        self.write_good_image()
        self.merges = 0
        self.later(bytes(len(self.GOOD)))   # a run killed before it recorded the step
        self.run_step()
        self.assertEqual(self.merges, 1)
        self.assertEqual((self.dest / 'romfs' / 'romfs.bin').read_bytes(), self.GOOD)

    def test_an_unchanged_image_is_not_hashed_when_the_step_runs_for_another_reason(self):
        self.run_step()
        (self.dest / 'exefs' / 'main').write_bytes(b'damaged code')
        self.assertTrue(self.context().will_run('extract'))
        with mock.patch.object(steps, 'file_sha256', wraps=steps.file_sha256) as hashed:
            self.run_step()
        self.assertEqual(self.merges, 1)
        image = self.dest / 'romfs' / 'romfs.bin'
        self.assertNotIn(image, [c.args[0] for c in hashed.call_args_list])

    def test_verify_still_catches_damage_that_keeps_the_time(self):
        self.run_step()
        image = self.dest / 'romfs' / 'romfs.bin'
        st = image.stat()
        image.write_bytes(bytes(len(self.GOOD)))
        os.utime(image, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertFalse(self.context().will_run('extract'))
        self.assertFalse(self.step.verify(self.context(), self.state['steps']['extract']))


class HostCheckTest(unittest.TestCase):
    def host(self, devices):
        """Check.host with the compile and the probe replaced: the probe reports these devices."""
        probe = json.dumps({'x86_64_v3': True, 'loader': True, 'instance': 0, 'devices': devices})
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(steps.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0, stdout='', stderr=''),
                                                                        SimpleNamespace(returncode=0, stdout=probe)]), \
                mock.patch.object(steps, 'linux_glibc', return_value=None), \
                mock.patch.object(steps, 'linux_kernel', return_value=None):
            layout = SimpleNamespace(clang=Path('clang'), deps=None, sysroot=None, dev=True)
            ctx = SimpleNamespace(layout=layout, temp=Path(d), reporter=Reporter(out=io.StringIO()))
            steps.Check().host(ctx)
            return ctx.host

    def test_a_device_lacking_extensions_alone_stops_the_check(self):
        with self.assertRaises(InstallError) as e:
            self.host([LACKING_DEVICE])
        self.assertEqual(e.exception.id, 'check.vulkan_no_extension')
        self.assertEqual(e.exception.params['devices'], 'Lacking (VK_A, VK_B)')

    def test_one_usable_device_is_enough(self):
        self.assertEqual(len(self.host([LACKING_DEVICE, GOOD_DEVICE])['devices']), 2)

    def test_a_device_below_vulkan_1_3_does_not_count_as_usable(self):
        old = {**GOOD_DEVICE, 'name': 'Old', 'api': [1, 2, 0]}
        with self.assertRaises(InstallError) as e:
            self.host([old, LACKING_DEVICE])
        self.assertEqual(e.exception.id, 'check.vulkan_no_extension')
        self.assertNotIn('Old', e.exception.params['devices'])

    def test_too_old_keeps_its_message(self):
        with self.assertRaises(InstallError) as e:
            self.host([{**LACKING_DEVICE, 'api': [1, 2, 0]}])
        self.assertEqual(e.exception.id, 'check.vulkan_too_old')

    def test_the_list_is_the_runtimes(self):
        self.assertEqual(required_list(ROOT / 'installer' / 'hostcheck.c'), required_list(ROOT / 'runtime' / 'vk_device.c'))

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('clang'), 'needs clang on Linux')
    def test_the_compiled_probe_lists_what_a_fake_loader_lacks(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'loader.c').write_text(FAKE_LOADER)
            try:
                subprocess.run(['clang', '-shared', '-fPIC', str(d / 'loader.c'), '-o', str(d / 'libvulkan.so.1')],
                               check=True, capture_output=True)
                subprocess.run(['clang', '-O1', str(ROOT / 'installer' / 'hostcheck.c'), '-o', str(d / 'probe'), '-ldl'],
                               check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                self.skipTest(f'no Vulkan headers: {e.stderr.decode(errors="replace")[:200]}')
            out = subprocess.run([str(d / 'probe')], env=dict(os.environ, LD_LIBRARY_PATH=str(d)), capture_output=True,
                                 text=True, check=True).stdout
        device = json.loads(out)['devices'][0]
        self.assertEqual(device['name'], 'Fake GPU')
        self.assertEqual(device['missing'], ['VK_KHR_push_descriptor', 'VK_EXT_depth_clip_control',
                                             'VK_EXT_external_memory_host'])


if __name__ == '__main__':
    unittest.main()

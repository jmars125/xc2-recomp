"""Safety checks of the installer and the extraction scripts, on fabricated inputs: no game files, no real keys. Tools
that would read game data (hactool, the Vulkan loader) are small stand-ins written here.

Run: python tests/installer_safety_test.py
"""
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from installer import steps  # noqa: E402
from installer.events import Reporter  # noqa: E402
from installer.runner import InstallError  # noqa: E402

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

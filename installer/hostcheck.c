// Host check of the installer's first step, compiled with the bundled clang at install time: does the CPU run
// -march=x86-64-v3 code, does a Vulkan 1.3 device exist, and which of the extensions the game cannot start without does
// each device lack. Prints one JSON object on stdout.
// The Vulkan loader is opened at run time, so a machine without one gets "loader": false instead of a failed start.
#include <cpuid.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#ifdef _WIN32
#include <windows.h>
#define open_lib() LoadLibraryA("vulkan-1.dll")
#define lib_sym(l, n) ((void *)GetProcAddress((l), (n)))
#else
#include <dlfcn.h>
#define open_lib() dlopen("libvulkan.so.1", RTLD_NOW)
#define lib_sym(l, n) dlsym((l), (n))
#endif

static void json_string(const char *s) {
    putchar('"');
    for (; *s; s++) {
        if (*s == '"' || *s == '\\') printf("\\%c", *s);
        else if ((unsigned char)*s < 0x20) printf("\\u%04x", *s);
        else putchar(*s);
    }
    putchar('"');
}

// The x86-64-v3 level from CPUID: AVX, AVX2, BMI1, BMI2, F16C, FMA, LZCNT and MOVBE, with the OS saving the YMM state.
// Not __builtin_cpu_supports("x86-64-v3"): clang reads that from the C runtime's CPU model, and libgcc before GCC 12
// (the Linux release's sysroot has GCC 10) has no level bits, so it answers false on every CPU.
static int x86_64_v3(void) {
    unsigned a, b, c, d;
    if (!__get_cpuid(1, &a, &b, &c, &d)) return 0;
    const unsigned fma = 1u << 12, movbe = 1u << 22, osxsave = 1u << 27, avx = 1u << 28, f16c = 1u << 29;
    if ((c & (fma | movbe | osxsave | avx | f16c)) != (fma | movbe | osxsave | avx | f16c)) return 0;
    unsigned lo, hi;
    __asm__("xgetbv" : "=a"(lo), "=d"(hi) : "c"(0));
    if ((lo & 6) != 6) return 0;   // XMM and YMM state enabled by the OS
    if (!__get_cpuid_count(7, 0, &a, &b, &c, &d)) return 0;
    const unsigned bmi1 = 1u << 3, avx2 = 1u << 5, bmi2 = 1u << 8;
    if ((b & (bmi1 | avx2 | bmi2)) != (bmi1 | avx2 | bmi2)) return 0;
    if (!__get_cpuid(0x80000001, &a, &b, &c, &d)) return 0;
    return (c & (1u << 5)) != 0;   // LZCNT (ABM)
}

// The same list as runtime/vk_device.c k_required_ext, whose pick_device skips a device lacking any of them. The runtime
// sets no platform condition on it, so Windows and Linux share it. tests/installer_safety_test.py compares the two lists.
static const char *const k_required_ext[] = {
    VK_KHR_SWAPCHAIN_EXTENSION_NAME, VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME, VK_EXT_DEPTH_CLIP_CONTROL_EXTENSION_NAME,
    VK_EXT_EXTERNAL_MEMORY_HOST_EXTENSION_NAME};

// Prints the JSON array of the required extensions the device lacks. A failed enumeration leaves the list empty, so every
// one counts as missing, as in runtime/vk_device.c missing_required.
static void print_missing_extensions(PFN_vkEnumerateDeviceExtensionProperties enumerate, VkPhysicalDevice dev) {
    uint32_t n = 0;
    VkExtensionProperties *ext = NULL;
    if (enumerate && enumerate(dev, NULL, &n, NULL) >= 0 && n) ext = calloc(n, sizeof *ext);
    if (!ext || enumerate(dev, NULL, &n, ext) < 0) n = 0;
    printf("[");
    int printed = 0;
    for (size_t i = 0; i < sizeof k_required_ext / sizeof *k_required_ext; i++) {
        int found = 0;
        for (uint32_t e = 0; e < n && !found; e++) found = !strcmp(ext[e].extensionName, k_required_ext[i]);
        if (found) continue;
        printf("%s", printed++ ? ", " : "");
        json_string(k_required_ext[i]);
    }
    printf("]");
    free(ext);
}

int main(void) {
    printf("{\"x86_64_v3\": %s, ", x86_64_v3() ? "true" : "false");
    void *lib = open_lib();
    PFN_vkGetInstanceProcAddr gipa = lib ? (PFN_vkGetInstanceProcAddr)lib_sym(lib, "vkGetInstanceProcAddr") : NULL;
    if (!gipa) {
        printf("\"loader\": false, \"devices\": []}\n");
        return 0;
    }
    printf("\"loader\": true, ");
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "xc2-install",
                             .apiVersion = VK_API_VERSION_1_3};
    VkInstanceCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
    VkInstance inst = VK_NULL_HANDLE;
    VkResult r = create ? create(&ci, NULL, &inst) : VK_ERROR_INITIALIZATION_FAILED;
    if (r != VK_SUCCESS) {
        printf("\"instance\": %d, \"devices\": []}\n", (int)r);
        return 0;
    }
    PFN_vkEnumeratePhysicalDevices enumerate = (PFN_vkEnumeratePhysicalDevices)gipa(inst, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties props = (PFN_vkGetPhysicalDeviceProperties)gipa(inst, "vkGetPhysicalDeviceProperties");
    PFN_vkEnumerateDeviceExtensionProperties extensions =
        (PFN_vkEnumerateDeviceExtensionProperties)gipa(inst, "vkEnumerateDeviceExtensionProperties");
    PFN_vkDestroyInstance destroy = (PFN_vkDestroyInstance)gipa(inst, "vkDestroyInstance");
    VkPhysicalDevice devs[16];
    uint32_t n = 16;
    if (enumerate(inst, &n, devs) < 0) n = 0;
    printf("\"instance\": 0, \"devices\": [");
    for (uint32_t i = 0; i < n; i++) {
        VkPhysicalDeviceProperties p;
        props(devs[i], &p);
        printf("%s{\"name\": ", i ? ", " : "");
        json_string(p.deviceName);
        printf(", \"api\": [%u, %u, %u], \"type\": %d, \"missing\": ", VK_API_VERSION_MAJOR(p.apiVersion),
               VK_API_VERSION_MINOR(p.apiVersion), VK_API_VERSION_PATCH(p.apiVersion), (int)p.deviceType);
        print_missing_extensions(extensions, devs[i]);
        printf("}");
    }
    printf("]}\n");
    destroy(inst, NULL);
    return 0;
}

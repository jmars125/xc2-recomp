"""Run the attachment feedback decisions of the Vulkan replay against a fake Vulkan device.

The pass functions of runtime/vk_exec.c and the feedback functions of runtime/vk_exec_draw.c are copied unchanged from
the source into a test program with fake Vulkan commands and fake texture slots, then compiled and run. No GPU, game
files or validation layer: this checks what the replay asks for, not what a driver does with it.

Usage: feedback_check.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests' / 'diff'))
from common import MSYS_BIN, compiler  # noqa: E402

PREFIX = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cfg.h"
#include "host.h"
#include "vk_exec.h"
#define NVN_STAGE_FS 1

static VkCtx ctx;
static VkTexImage images[3];
static int selected, lookups, barriers, begins;
static uint32_t generation = 1;
static uint64_t token = 1;
static VkAttachmentStoreOp store_op;
static VkImageLayout color_layout, depth_layout;
VkExecFrame vk_exec_frame;
GfxStats gfx_counters;
int vk_dump_armed;

VkCtx *vk_ctx(void) { return &ctx; }
const char *cfg_value(const char *name) { (void)name; return "1"; }
void rt_fatal(const char *format, ...) { puts(format); exit(1); }
uint32_t vk_texture_slots_gen(void) { return generation; }
uint64_t vk_texture_slot_token(int id) { (void)id; return token; }
void vk_texture_lock(void) {}
void vk_texture_unlock(void) {}
const VkTexImage *vk_texture_by_id_locked(int id, view_t *v, int *hv) {
    (void)id;
    lookups++;
    if (v) memset(v, 0, sizeof *v);
    if (hv) *hv = 0;
    return &images[selected];
}
int gfx_shader_resources(const GfxShader *s, int kind, const GfxShaderRes **res) {
    static const GfxShaderRes r = {.slot = 0, .type = 3, .count = 1};
    (void)s;
    *res = &r;
    return kind == GFX_RES_TEX;
}
void vk_exec_xfb_pause(VkExec *ex) { (void)ex; }
void vk_exec_oq_pass_end(VkExec *ex) { (void)ex; }
void vk_dump_pass_end(VkExec *ex) { (void)ex; }
void vk_texture_gpu_written(const tex_t *t) { (void)t; }
static void resolve_rt(VkExec *ex) { (void)ex; }
static VkImageView view_of(VkExec *ex, const VkExecTarget *t) { (void)ex, (void)t; return (VkImageView)1; }
static void bc_copy_back(VkExec *ex, const VkExecTarget *t) { (void)ex, (void)t; }
static void tfr_note(const VkExecTarget *t, uint64_t stamp) { (void)t, (void)stamp; }
void rc_vkCmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo *di) { (void)cb, (void)di; barriers++; }
void rc_vkCmdBeginRendering(VkCommandBuffer cb, const VkRenderingInfo *ri) {
    (void)cb;
    begins++;
    if (ri->colorAttachmentCount) store_op = ri->pColorAttachments[0].storeOp, color_layout = ri->pColorAttachments[0].imageLayout;
    if (ri->pDepthAttachment) store_op = ri->pDepthAttachment->storeOp, depth_layout = ri->pDepthAttachment->imageLayout;
}
void rc_vkCmdEndRendering(VkCommandBuffer cb) { (void)cb; }
'''

TESTS = r'''
#define FBL VK_IMAGE_LAYOUT_ATTACHMENT_FEEDBACK_LOOP_OPTIMAL_EXT
#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            printf("FAILED at line %d: %s\n", __LINE__, #cond);         \
            return 1;                                                   \
        }                                                               \
    } while (0)

static const GfxShader *const FS = (const GfxShader *)1;

static void reset(int mode) {
    ctx.feedback = mode;
    for (int i = 0; i < 3; i++)
        images[i] = (VkTexImage){.image = (VkImage)(uintptr_t)(i + 1), .levels = 1, .layers = 1, .fb_usage = 1,
                                 .aspect = VK_IMAGE_ASPECT_COLOR_BIT};
    images[2].aspect = VK_IMAGE_ASPECT_DEPTH_BIT;
    selected = 0, generation++, token++;
    vk_exec_frame.fb_restarts = 0, vk_exec_frame.fb_draws = 0;
}

static VkExec color_pass(void) {   // image 0 attached as colour 0; slot 0 of the fragment stage sampled
    VkExec ex = {.barrier_at = -1, .pass_ncolor = 1, .pass_w = 4, .pass_h = 4, .pass_layers = 1};
    ex.color[0] = (VkExecTarget){.image = images[0].image, .img = &images[0], .layers = 1};
    ex.tex[NVN_STAGE_FS][0] = 1;
    return ex;
}

static int first_sample_in_a_clean_pass(void) {
    reset(VK_FEEDBACK_LAYOUT);
    VkExec ex = color_pass();
    vk_exec_pass_begin(&ex);
    CHECK(store_op == VK_ATTACHMENT_STORE_OP_STORE && color_layout == VK_IMAGE_LAYOUT_GENERAL);
    CHECK(ex.fb_dirty == 0);
    int b0 = begins;
    uint32_t mask = feedback_prepare(&ex, FS);
    CHECK(mask == 1);                                 // the pipeline gets the colour feedback flag
    CHECK(images[0].fb_learned && color_layout == FBL);
    CHECK(begins == b0 + 1 && vk_exec_frame.fb_restarts == 1 && ex.nfbl == 1);
    CHECK(!(mask & ex.fb_dirty));                     // no by-region barrier: nothing written since the full one

    // The same draw again, and a new pass: no second restart, still the flag.
    CHECK(feedback_prepare(&ex, FS) == 1 && begins == b0 + 1);
    vk_exec_pass_end(&ex);
    vk_exec_pass_begin(&ex);
    CHECK(color_layout == FBL);
    b0 = begins;
    int bars = barriers;
    CHECK(feedback_prepare(&ex, FS) == 1 && begins == b0 && barriers == bars && vk_exec_frame.fb_restarts == 1);
    return 0;
}

static int read_only_depth(void) {
    reset(VK_FEEDBACK_LAYOUT);
    selected = 2;
    VkExec ex = {.barrier_at = -1, .pass_w = 4, .pass_h = 4, .pass_layers = 1, .pass_depth = 1};
    ex.depth = (VkExecTarget){.image = images[2].image, .img = &images[2], .layers = 1, .aspect = VK_IMAGE_ASPECT_DEPTH_BIT};
    ex.tex[NVN_STAGE_FS][0] = 1;
    vk_exec_pass_begin(&ex);
    CHECK(depth_layout == VK_IMAGE_LAYOUT_GENERAL);
    CHECK(feedback_prepare(&ex, FS) == 0x100);        // no draw wrote it; the pass's STORE still counts
    CHECK(images[2].fb_learned && depth_layout == FBL && vk_exec_frame.fb_restarts == 1);
    return 0;
}

static int written_attachment(void) {             // the path that worked before: a write, then a sample
    reset(VK_FEEDBACK_LAYOUT);
    VkExec ex = color_pass();
    vk_exec_pass_begin(&ex);
    ex.fb_dirty = 1;
    CHECK(feedback_prepare(&ex, FS) == 1 && images[0].fb_learned && color_layout == FBL);
    CHECK(vk_exec_frame.fb_draws == 1 && vk_exec_frame.fb_restarts == 1 && ex.fb_dirty == 0);
    ex.fb_dirty = 1;                                  // a later write: the barrier's turn, not a restart
    int b0 = begins;
    uint32_t mask = feedback_prepare(&ex, FS);
    CHECK(mask & ex.fb_dirty);
    CHECK(begins == b0 && vk_exec_frame.fb_restarts == 1);
    return 0;
}

static int no_overlap_costs_nothing(void) {
    reset(VK_FEEDBACK_LAYOUT);
    selected = 1;                                     // samples image 1, renders image 0
    VkExec ex = color_pass();
    vk_exec_pass_begin(&ex);
    ex.fb_dirty = 1;
    int b0 = begins, bars = barriers, l0 = lookups;
    CHECK(feedback_prepare(&ex, FS) == 0);
    CHECK(lookups == l0 + 1);
    for (int i = 0; i < 100; i++) CHECK(feedback_prepare(&ex, FS) == 0);
    CHECK(lookups == l0 + 1 && begins == b0 && barriers == bars);
    CHECK(!images[0].fb_learned && !images[1].fb_learned && color_layout == VK_IMAGE_LAYOUT_GENERAL);
    CHECK(vk_exec_frame.fb_restarts == 0 && vk_exec_frame.fb_draws == 0);
    return 0;
}

static int image_without_feedback_usage(void) {
    reset(VK_FEEDBACK_LAYOUT);
    images[0].fb_usage = 0;
    VkExec ex = color_pass();
    vk_exec_pass_begin(&ex);
    int b0 = begins;
    for (int i = 0; i < 10; i++) CHECK(feedback_prepare(&ex, FS) == 0);
    CHECK(begins == b0 && !images[0].fb_learned);     // it cannot be learned: no restart per draw
    ex.fb_dirty = 1;
    CHECK(feedback_prepare(&ex, FS) == 0);
    CHECK(begins == b0 + 1 && ex.fb_dirty == 0);      // a write still restarts behind the full barrier
    return 0;
}

static int restart_and_off_modes(void) {
    reset(VK_FEEDBACK_RESTART);
    VkExec ex = color_pass();
    vk_exec_pass_begin(&ex);
    int b0 = begins;
    CHECK(feedback_prepare(&ex, FS) == 0 && begins == b0);
    ex.fb_dirty = 1;
    CHECK(feedback_prepare(&ex, FS) == 0 && begins == b0 + 1 && !images[0].fb_learned);
    reset(VK_FEEDBACK_OFF);
    ex = color_pass();
    vk_exec_pass_begin(&ex);
    ex.fb_dirty = 1;
    b0 = begins;
    int l0 = lookups;
    CHECK(feedback_prepare(&ex, FS) == 0 && begins == b0 && lookups == l0);
    return 0;
}

static int slot_changes_without_a_bind(void) {
    reset(VK_FEEDBACK_LAYOUT);
    selected = 1;
    VkExec ex = color_pass();
    vk_exec_pass_begin(&ex);
    CHECK(feedback_scan(&ex, FS) == 0);
    int l0 = lookups;
    generation++;                                     // another slot changed: rescan, answered by the handle's memo
    CHECK(feedback_scan(&ex, FS) == 0 && lookups == l0);
    generation++, token++, selected = 0;              // this slot now resolves to the attachment; no OP_BIND_TEX
    CHECK(feedback_scan(&ex, FS) == 1 && lookups == l0 + 1);
    CHECK(feedback_prepare(&ex, FS) == 1 && images[0].fb_learned && color_layout == FBL);
    return 0;
}

#define RUN(t)                                                          \
    do {                                                                \
        if (t()) return printf("%s failed\n", #t), 1;                   \
        printf("%s: ok\n", #t);                                         \
    } while (0)

int main(void) {
    RUN(first_sample_in_a_clean_pass);
    RUN(read_only_depth);
    RUN(written_attachment);
    RUN(no_overlap_costs_nothing);
    RUN(image_without_feedback_usage);
    RUN(restart_and_off_modes);
    RUN(slot_changes_without_a_bind);
    return 0;
}
'''


def between(source, start, end, what):
    """The text of source from start up to end; the test stops when the code it copies has moved."""
    a = source.find(start)
    b = source.find(end, a)
    if a < 0 or b < 0:
        sys.exit(f'feedback_check: cannot find {what} ({start!r} .. {end!r}): update this test')
    return source[a:b]


def function(source, name):
    match = re.search(r'^static [^\n;]*\b' + name + r'\([^;{]*\)\s*\{', source, re.M)
    if not match:
        sys.exit(f'feedback_check: cannot find {name}: update this test')
    pos = match.end()
    depth = 1
    while depth:
        depth += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    return source[match.start():pos] + '\n'


def main():
    runtime = ROOT / 'runtime'
    exec_c = (runtime / 'vk_exec.c').read_text(encoding='utf-8')
    draw_c = (runtime / 'vk_exec_draw.c').read_text(encoding='utf-8')
    code = (PREFIX
            + between(exec_c, 'static int has_image(', 'VkCommandBuffer vk_exec_inline_begin(', 'the pass functions')
            + function(draw_c, 'token_of') + function(draw_c, 'slot_still')
            + between(draw_c, '// The image and the levels [l0, l1)', '// By-region barrier inside the pass:', 'the feedback functions')
            + TESTS)
    work = ROOT / 'build' / 'test' / 'feedback'
    work.mkdir(parents=True, exist_ok=True)
    src = work / 'feedback_check.c'
    src.write_text(code, encoding='utf-8')
    exe = work / ('feedback_check.exe' if os.name == 'nt' else 'feedback_check')
    env = dict(os.environ)
    if os.name == 'nt' and MSYS_BIN.exists():
        env['PATH'] = str(MSYS_BIN) + os.pathsep + env.get('PATH', '')
    subprocess.check_call([compiler(), '-std=gnu11', '-mavx2', '-mfma', '-Wno-unused-function', '-I', str(runtime),
                           '-I', str(ROOT / 'toolchain' / 'vma'), str(src), '-o', str(exe)], env=env)
    return subprocess.run([str(exe)], env=env).returncode


if __name__ == '__main__':
    sys.exit(main())

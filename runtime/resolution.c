// Game resolution: the size XC2 draws its picture at and the shape of that picture, wider or narrower than the
// shipped 16:9 (21:9 3440x1440, 32:9 5120x1440 or 7680x2160, the Steam Deck's 16:10). Three patch sets of the game's
// code read the patch page (tools/size_sites_xc2.py and tools/aspect_sites_xc2.py -> recomp/patches-upd.txt), the
// precedent being the 60 fps set, whose patched loads of the 1/30 constant read what frame_rate.c xc2_rate_store
// writes:
//   size    XC2's display builds its two window textures at 1280x720 (grlib::CGLibDisplay::setup, two movz; the
//           community 1080p and 1440p mods overwrite the immediates). The set loads them from +0x68 / +0x6c, where
//           res_init stores XC2_OUTPUT_RES (default 1920x1080), and is on when that is not 1280x720: the game then draws
//           its picture at the output's own size and shape, the viewport and the render size the camera code divides
//           follow the textures, and the interface is laid out on its 1280x720 canvas and scaled with them. The
//           render targets live in a region of the game's heap with a constant budget, GLIBPXL, 362 MiB in 3.0.1
//           (grlib::CGLibManager::deviceInit, one movz); the targets of 1280x720 take about 80 MiB of it, 3840x1080
//           still fits and 5120x1440 does not (the game then has no region and aborts in its first allocation). The
//           set's third site loads that constant from +0x78, where res_init stores a budget grown with the pixel
//           count, and res_heap_extra_bytes grows the application pool by the same bytes, so the heap the game asks
//           for (nninitStartup: TotalMemorySize - UsedMemorySize, memory.c mem_info) holds the larger region.
//   scale   The game's dynamic resolution (lib_nx.ini red_sclX / red_sclY / red_Auto) ends in
//           ml::DrPixlPostParm::isReductionBuffer, which multiplies the scale pair by 100.0 and draws the scene at
//           width * percent / 100. The set loads both percents from +0x70, where res_init stores 100 when the set
//           size is on (a picture drawn at its size is not scaled below it) or XC2_RENDER_SCALE's percentage when one
//           is given; XC2_RENDER_SCALE=game at the shipped size keeps the game's dynamic resolution (the set off).
//   aspect  XC2 computes its camera's aspect at run time as render width / height (ml::DevGraph::getAspect, inlined
//           at its users); the set replaces the quotient at each site with a load of +0x60 (+0x64 where the code
//           divides the other way round), where res_init stores the output's aspect and its inverse, and is on for a
//           shape other than 16:9. The camera constructors take the root canvas's 16:9 for their aspect, not the
//           render size, so a wide picture needs this set as well as the set size. The 2.1.0 ultrawide mods by Fl4sh_
//           and theboy181 overwrite the same quotient and leave the frame to the emulator's "stretch to window".
// The present shows the picture at the output's shape (gfx_present.c present_image through res_aspect_shape), and
// XC2_PICTURE_FIT decides the bars when the window's shape differs. Without the sets (a build whose patch table was
// made before the finders ran, or another game version) the picture stays the game's own 1280x720 at 16:9, and one
// line per set says so.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "layout.h"
#include "platform/platform.h"

#define BASE_W 1920         // the output when XC2_OUTPUT_RES does not parse
#define BASE_H 1080
#define GAME_W 1280         // the size the game builds its window textures at (tools/size_sites_xc2.py)
#define GAME_H 720
#define PAGE_ASPECT 0x60    // f32 output width / height, the quotient the set aspect's sites load (tools/aspect_sites_xc2.py)
#define PAGE_INVERSE 0x64   // f32 output height / width, for a site that divides the other way round
#define PAGE_WIDTH 0x68     // u32 render width, the set size's loads (tools/size_sites_xc2.py)
#define PAGE_HEIGHT 0x6c    // u32 render height
#define PAGE_SCALE 0x70     // f32 render scale in percent, the set scale's loads
#define PAGE_BUDGET 0x78    // u64, the pixel memory budget in its top 32 bits (the set size's third site)
#define PXL_BUDGET 0x16a00000ull        // the game's GLIBPXL region: 362 MiB in 3.0.1 (1.0.0 has 342 MiB)
#define BUDGET_PIXELS (3840ull * 1080)  // the largest picture that ran within the game's budget
#define EXTRA_CAP 0x35000000ull         // the pool may grow this much before the game's heap would pass memory.c HEAP_CAP (4 GiB)
#define ASPECT_EPS 0.005f   // 1366x768 counts as 16:9; 16:10 and 21:9 do not

static struct {
    int decided;
    unsigned ow, oh;   // output: the size and shape the picture is drawn at with the set size, its shape without (XC2_OUTPUT_RES)
    unsigned rw, rh;   // the render size: ow x oh when the set size is on, else the game's 1280x720
    int size;          // the set size is on
    int aspect;        // the set aspect is on: the 3D view is laid out for ow:oh
    int scale;         // XC2_RENDER_SCALE in percent, 0 for game
    int fixed;         // the set scale is on: the scene is drawn at percent of the render size, the game's dynamic resolution off
    int percent;       // that percent
    uint64_t budget;   // the pixel memory budget the set size stores: the game's, grown with the pixel count past BUDGET_PIXELS
    uint64_t extra;    // what the application pool grows by for it (res_heap_extra_bytes), at most EXTRA_CAP
} R;

static int parse(const char *s, unsigned *w, unsigned *h) {
    char tail;
    return s && sscanf(s, "%ux%u%c", w, h, &tail) == 2 && *w >= 640 && *h >= 360 && *w <= 7680 && *h <= 4320;
}

static void decide(void) {
    if (R.decided) return;
    R.decided = 1;
    R.ow = BASE_W;
    R.oh = BASE_H;
    const char *o = cfg_value("XC2_OUTPUT_RES");
    unsigned w, h;
    if (parse(o, &w, &h)) {
        R.ow = w & ~1u;
        R.oh = h & ~1u;
    } else {
        rt_log("resolution: XC2_OUTPUT_RES=%s is not <width>x<height> in 640x360..7680x4320; 1920x1080", o);
    }
    uint64_t pixels = (uint64_t)R.ow * R.oh;
    R.budget = PXL_BUDGET;
    if (pixels > BUDGET_PIXELS)   // the targets grow with the pixels: the budget in the same proportion, whole MiB
        R.budget = (PXL_BUDGET * pixels / BUDGET_PIXELS + (1u << 20) - 1) & ~((1ull << 20) - 1);
    R.extra = R.budget - PXL_BUDGET;
    if (R.extra > EXTRA_CAP) {
        R.extra = EXTRA_CAP;
        rt_log("resolution: %ux%u needs a pixel memory budget of %llu MiB; the application pool grows by %llu MiB only, "
               "the most the game's heap can take (memory.c HEAP_CAP)", R.ow, R.oh, (unsigned long long)(R.budget >> 20),
               (unsigned long long)(R.extra >> 20));
    }
    const char *s = cfg_value("XC2_RENDER_SCALE");
    int pct = s ? atoi(s) : 0;
    if (pct >= 25) {
        R.scale = pct > 100 ? 100 : pct;
    } else if (s && strcmp(s, "game")) {
        rt_log("resolution: XC2_RENDER_SCALE=%s is not game or a percentage from 25 to 100; game", s);
    }
}

// TotK Recomp grows the texture heap through its HeapDef table; XC2 has no such table, but its pixel memory budget
// is a constant carved from its heap (GLIBPXL, see the top), so the application pool grows by what the set size adds
// to that budget for an output larger than BUDGET_PIXELS, and the game's heap request grows with the pool. Decided
// with the sizes (memory.c mem_init asks before the guest starts); the pool grows whether or not the set is there,
// which costs nothing but address space.
uint64_t res_heap_extra_bytes(void) {
    decide();
    return R.extra;
}
uint64_t res_heap_extra_kib(void) { return res_heap_extra_bytes() >> 10; }
int res_heapdef_build(const void *in, size_t n, void **out, size_t *out_n) {
    (void)in, (void)n, (void)out_n;
    *out = NULL;
    return 0;
}
void res_heapdef_served(void) {}

// Stores the render size, the render scale and the output's aspect where the sets read them and switches each set
// on or off; before the guest starts, so plain stores. patches.c switched each set on from its environment switch
// (XC2_RENDER_RES, XC2_FIXED_SCALE, XC2_ASPECT; default 1): 0 keeps the game's own size, dynamic resolution or 16:9
// view whatever the output says.
void res_init(void) {
    decide();
    uint8_t *page = rt_patch_page();
    R.rw = GAME_W, R.rh = GAME_H;
    R.percent = R.scale ? R.scale : 100;
    int set = rt_patch_set("size");
    if (set < 0 || !page) {
        rt_log("resolution: this %s build has no size patch set (tools/size_sites_xc2.py): the picture stays the game's "
               "%ux%u, and XC2_OUTPUT_RES only shapes the view", rt_game_name, GAME_W, GAME_H);
    } else {
        uint32_t w = R.ow, h = R.oh;
        uint64_t budget = R.budget << 32;   // the movk after the patched movz fills the low half
        memcpy(page + PAGE_WIDTH, &w, sizeof w);
        memcpy(page + PAGE_HEIGHT, &h, sizeof h);
        memcpy(page + PAGE_BUDGET, &budget, sizeof budget);
        int wanted = rt_patch_enabled(set), on = wanted && (R.ow != GAME_W || R.oh != GAME_H);
        rt_patch_switch(set, on);
        R.size = on;
        if (on) {
            R.rw = R.ow, R.rh = R.oh;
            rt_log("resolution: render size %ux%u (the display's window textures, set size)", R.rw, R.rh);
            if (R.budget != PXL_BUDGET)
                rt_log("resolution: pixel memory budget %llu MiB (the game's %llu MiB holds up to %llux%llu); the "
                       "application pool grows by %llu MiB", (unsigned long long)(R.budget >> 20),
                       (unsigned long long)(PXL_BUDGET >> 20), 3840ull, 1080ull, (unsigned long long)(R.extra >> 20));
        } else {
            rt_log("resolution: render size %ux%u, the game's own (%s)", GAME_W, GAME_H,
                   wanted ? "XC2_OUTPUT_RES is 1280x720" : "XC2_RENDER_RES=0");
        }
    }
    set = rt_patch_set("scale");
    if (set < 0 || !page) {
        if (R.scale || R.size)
            rt_log("resolution: this %s build has no scale patch set (tools/size_sites_xc2.py): the game's own dynamic "
                   "resolution%s", rt_game_name, R.scale ? ", XC2_RENDER_SCALE has no effect" : " scales the picture");
    } else {
        float percent = (float)R.percent;
        memcpy(page + PAGE_SCALE, &percent, sizeof percent);
        int wanted = rt_patch_enabled(set), on = wanted && (R.scale || R.size);
        rt_patch_switch(set, on);
        R.fixed = on;
        if (on)
            rt_log("resolution: render scale %d%% of %ux%u, fixed (set scale; the game's dynamic resolution is off)",
                   R.percent, R.rw, R.rh);
        else
            rt_log("resolution: render scale: the game's own dynamic resolution (%s)",
                   wanted ? "XC2_RENDER_SCALE=game at the game's own size" : "XC2_FIXED_SCALE=0");
    }
    set = rt_patch_set("aspect");
    if (set < 0 || !page) {
        rt_log("resolution: this %s build has no aspect patch set (tools/aspect_sites_xc2.py): the 3D view stays 16:9 "
               "whatever XC2_OUTPUT_RES says, and XC2_PICTURE_FIT decides the bars", rt_game_name);
        return;
    }
    float aspect = (float)R.ow / (float)R.oh, inverse = (float)R.oh / (float)R.ow, wide = aspect - 16.0f / 9;
    memcpy(page + PAGE_ASPECT, &aspect, sizeof aspect);
    memcpy(page + PAGE_INVERSE, &inverse, sizeof inverse);
    int wanted = rt_patch_enabled(set), on = wanted && (wide > ASPECT_EPS || wide < -ASPECT_EPS);
    rt_patch_switch(set, on);
    R.aspect = on;
    if (on)
        rt_log("resolution: 3D view laid out for %ux%u (aspect %.4f against 16:9 %.4f); the interface stays on the "
               "16:9 canvas, in the left part of the picture", R.ow, R.oh, (double)aspect, 16.0 / 9);
    else
        rt_log("resolution: %ux%u, the 3D view stays 16:9 (%s)", R.ow, R.oh, wanted ? "the output is 16:9" : "XC2_ASPECT=0");
}

// The canvas is the size the game draws its picture at (the window textures: the output with the set size, else the
// game's 1280x720), the scene its share of that: the fixed percent with the set scale, else the whole (the game's
// dynamic share is not read back).
void res_sizes(unsigned out[2], unsigned scene[2]) {
    decide();
    out[0] = R.rw, out[1] = R.rh;
    scene[0] = R.fixed ? R.rw * (unsigned)R.percent / 100 : R.rw;
    scene[1] = R.fixed ? R.rh * (unsigned)R.percent / 100 : R.rh;
}

// The shape the picture is meant to be shown in: 1 and {w, h} when the set aspect laid the 3D view out for it, so the
// present fits the 16:9 frame into a rectangle of that shape; 0 when the frame's own 16:9 is the shape (the set absent,
// off, or the output 16:9).
int res_aspect_shape(unsigned shape[2]) {
    shape[0] = R.ow, shape[1] = R.oh;
    return R.aspect;
}

// The interface's horizontal scale on a frame wider than 16:9: 1 for XC2. XCX's fit (nvn_api_cmd.c, in the history)
// narrowed the interface's uniform blocks, viewports and scissors at XCX's own sites; XC2's are not found, so its
// interface stays on its 16:9 canvas, in the left part of a wider picture. The API stays so that the fit returns here once the sites are known.
float res_ui_fit(void) { return 1; }

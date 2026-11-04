// Game resolution: the shape of the picture, wider or narrower than the shipped 16:9 (21:9 3440x1440, 32:9 5120x1440,
// the Steam Deck's 16:10). XC2 draws its picture at its own size and computes its camera's aspect at run time as
// render width / height (ml::DevGraph::getAspect, inlined at its users). The patch set "aspect"
// (tools/aspect_sites_xc2.py -> recomp/patches-upd.txt) replaces that quotient at each site with a load from the
// patch page, +0x60 (and +0x64 where the code divides the other way round), where res_init stores the output's own
// aspect ratio and its inverse, computed from the shape of XC2_OUTPUT_RES (default 1920x1080; only its shape counts).
// The picture then holds a wider view squeezed into its 16:9 frame, and the present stretches that frame to the
// output's shape (gfx_present.c present_image through res_aspect_shape). The 2.1.0 ultrawide mods by Fl4sh_ and
// theboy181 overwrite the same quotient and leave the frame to the emulator's "stretch to window". The precedent in
// this runtime is the 60 fps set: frame_rate.c xc2_rate_store writes the value the patched loads of the 1/30
// constant read.
//
// What is not done: the interface is laid out on the same 16:9 canvas and is stretched with the picture (res_ui_fit
// returns 1: the sites that place XC2's interface are not found; the finder lists candidates as INFO), and the pixel
// size stays the game's own: XC2's main holds no size table like XC3's {1920, 1080, 1280, 720}, and the sites of its
// dynamic scene share are not found either, so XC2_RENDER_SCALE has no effect. Without the set the 3D picture stays
// 16:9 whatever the output says, and XC2_PICTURE_FIT decides the bars.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "layout.h"
#include "platform/platform.h"

#define BASE_W 1920
#define BASE_H 1080
#define PAGE_ASPECT 0x60    // f32 output width / height, the quotient the set's sites load (tools/aspect_sites_xc2.py)
#define PAGE_INVERSE 0x64   // f32 output height / width, for a site that divides the other way round
#define ASPECT_EPS 0.005f   // 1366x768 counts as 16:9; 16:10 and 21:9 do not

static struct {
    int decided;
    unsigned ow, oh;   // output: the shape the picture is shown in (XC2_OUTPUT_RES)
    int aspect;        // the set aspect is on: the 3D view is laid out for ow:oh
    int scale;         // XC2_RENDER_SCALE in percent, 0 for the game's own
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
    const char *s = cfg_value("XC2_RENDER_SCALE");
    int pct = s ? atoi(s) : 0;
    if (pct >= 25) {
        R.scale = pct > 100 ? 100 : pct;
    } else if (s && strcmp(s, "game")) {
        rt_log("resolution: XC2_RENDER_SCALE=%s is not game or a percentage from 25; the game's own", s);
    }
}

// TotK Recomp grows the texture heap through its HeapDef table; XC2 has no such table, and the 1.0.1 mods run at
// 3840x2160 without a bigger heap.
uint64_t res_heap_extra_kib(void) { return 0; }
uint64_t res_heap_extra_bytes(void) { return 0; }
int res_heapdef_build(const void *in, size_t n, void **out, size_t *out_n) {
    (void)in, (void)n, (void)out_n;
    *out = NULL;
    return 0;
}
void res_heapdef_served(void) {}

// Stores the output's aspect ratio and its inverse where the set aspect reads them and switches the set on for a shape
// other than 16:9; before the guest starts, so plain stores. patches.c switched the set on from XC2_ASPECT (default 1):
// 0 keeps the 3D view at 16:9 whatever the output, with the bars of XC2_PICTURE_FIT. Without the set (a build whose
// patch table was made before the finder ran, or another game version) one line says what the output cannot do.
void res_init(void) {
    decide();
    if (R.scale)
        rt_log("resolution: XC2_RENDER_SCALE has no effect on XC2 (the scene sites are not found); the game's own "
               "dynamic resolution");
    int set = rt_patch_set("aspect");
    uint8_t *page = rt_patch_page();
    if (set < 0 || !page) {
        rt_log("resolution: this %s build has no aspect patch set (tools/aspect_sites_xc2.py): the 3D picture stays "
               "16:9 whatever XC2_OUTPUT_RES says, and XC2_PICTURE_FIT decides the bars", rt_game_name);
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
               "16:9 canvas, stretched with the picture", R.ow, R.oh, (double)aspect, 16.0 / 9);
    else
        rt_log("resolution: %ux%u, the 3D view stays 16:9 (%s)", R.ow, R.oh, wanted ? "the output is 16:9" : "XC2_ASPECT=0");
}

// XC2 draws at its own size: the canvas reported is the shipped docked one, and the scene is the game's dynamic share
// of it, which nothing reads back. XC2_OUTPUT_RES only shapes the view (res_aspect_shape).
void res_sizes(unsigned out[2], unsigned scene[2]) {
    decide();
    out[0] = BASE_W, out[1] = BASE_H;
    scene[0] = out[0], scene[1] = out[1];
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
// interface is stretched with the picture. The API stays so that the fit returns here once the sites are known.
float res_ui_fit(void) { return 1; }

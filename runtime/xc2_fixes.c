// Host halves of the game fixes in recomp/fixes-upd.txt (XC2 3.0.1). The sites come from Aegis (aegis-xc2,
// games/xc2/patches.py, MIT); this is our own code.
//
// Wind removal (set wind, XC2_WIND_GUARD): main+0x1ab7c0 (manager x0, object x1) is the game's function below, which
// its only call (main+0x1abcd8) reaches on the patch page. When the object is the manager's current one it drops a
// reference, and at zero the object's destructor already takes it out of the broad phase and of the manager's list;
// the game then takes it out of both again and stops on wind.m_pProxy != nullptr or node->intoNode(). Seen in Aegis in
// the Events Theater's chapter 4 and on a map jump. Before the second removal the game's own state says what is left:
// the object's list node pointing at itself means it is out of the list (nothing left to do), and its wind without a
// proxy, or with its own node pointing at itself, means it is out of the broad phase (only that removal is skipped).
// The cause of the double removal is not known; the checks only keep the game from stopping on it.
//
// Widen view (set wide): the scene's and the camera's 16:9 aspects are multiplied by the patch page's +0x110, which
// xc2_view_widen sets for each presented frame (recomp/fixes-upd.txt has the sites).
#include <stdint.h>
#include <string.h>

#include "host.h"
#include "layout.h"

#define MAIN(off) (MOD_MAIN_BASE + (off))
#define WIND_HOST 0xfd0   // patch page offset, recomp/fixes-upd.txt @host:fd0
#define WIDE_AT 0x108     // patch page: 16/9, the tolerance, the factor (set wide)

static uint64_t ld64(uint64_t a) { return *(volatile uint64_t *)(uintptr_t)a; }
static volatile int32_t *w32(uint64_t a) { return (volatile int32_t *)(uintptr_t)a; }

// The game's assertion handler, main+0x6983f8 (file, expression, line): it logs and returns.
static void game_assert(Cpu *c, uint64_t file, uint64_t expr, uint64_t line) {
    rt_call(c, MAIN(0x6983f8), 3, MAIN(file), MAIN(expr), line);
}

static void wind_guard_log(int which, uint64_t obj) {
    static int logged[2];
    if (logged[which - 1]++ < 8)
        rt_log("wind guard: object %#llx already %s", (unsigned long long)obj,
               which == 1 ? "out of its list, its removal skipped" : "out of the broad phase, that removal skipped");
}

static void wind_remove(Cpu *c) {
    uint64_t mgr = c->x[0], obj = c->x[1];
    if (ld64(mgr + 0x90) == obj) {   // the manager's current object: drop its reference
        *(volatile uint64_t *)(uintptr_t)(mgr + 0x90) = 0;
        if (obj) {
            if (*w32(obj + 8) <= 0) game_assert(c, 0x97baec, 0x97bafb, 0x3c);
            int32_t n = *w32(obj + 8) - 1;
            *w32(obj + 8) = n;
            if (!n) rt_call(c, ld64(ld64(obj) + 8), 1, obj);   // its destructor (vtable slot 1)
        }
    }
    if (obj && ld64(obj + 0x10) == obj + 0x10) {
        wind_guard_log(1, obj);
        return;
    }
    uint64_t world = ld64(mgr + 0x18);
    if (world) {   // out of the broad phase: main+0x895028 (world, wind)
        uint64_t wind = ld64(obj + 0x20);
        if (wind && (!ld64(wind + 0x60) || ld64(wind + 0x10) == wind + 0x10)) wind_guard_log(2, obj);
        else rt_call(c, MAIN(0x895028), 2, world, wind);
    }
    rt_call(c, MAIN(0x698618), 1, obj ? obj + 0x10 : 0);   // out of the manager's list
    int32_t count = *w32(mgr + 0x30);
    *w32(mgr + 0x30) = count - 1;
    if (count <= 0) game_assert(c, 0x9804ac, 0x98044d, 0xaa);
}

void xc2_view_widen(float factor) {
    uint8_t *page = rt_patch_page();
    if (page) *(volatile float *)(page + WIDE_AT + 8) = factor;
}

void xc2_fixes_init(void) {
    uint8_t *page = rt_patch_page();
    if (page) {
        float wide[3] = {16.0f / 9.0f, 0.01f, 1.0f};
        memcpy(page + WIDE_AT, wide, sizeof wide);
    }
    if (page && rt_patch_enabled(rt_patch_set("wind"))) rt_register_host((uint64_t)(uintptr_t)(page + WIND_HOST), wind_remove);
}

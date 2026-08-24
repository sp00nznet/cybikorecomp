/* A Cybiko in a window.
 *
 *   cybiko-sdl <cybiko.img> [cyos]
 *   cybiko-sdl <cybiko.img> [cyos] --shot out.bmp [seconds]
 *
 * Escape or the close button quits. $CYFLASH names a flash image, without
 * which CyOS stops at "Initializing flash device...".
 *
 * --shot runs without pacing and writes one frame to a BMP. It exists because
 * a renderer you cannot look at is a renderer you have not tested; it also
 * works under SDL_VIDEODRIVER=dummy, which is how it gets checked here.
 *
 * Nothing in here reaches into the emulator. It calls cy_run to advance time
 * and cy_lcd_dot to read the panel, the same two things the terminal probe
 * uses -- the recompiled image has no idea it is being drawn.
 *
 * There is no input yet. The Cybiko's keyboard is the next unimplemented
 * peripheral and CyOS is currently waiting on it, so what the window shows is
 * whatever CyOS drew on its way there.
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Take main() back from SDL2main. Its WinMain shim forces the Windows
 * subsystem, which throws away stderr -- and stderr is where a trap gets
 * reported. */
#define SDL_MAIN_HANDLED
#include <SDL2/SDL.h>

#include "cybikorecomp/h8s.h"

#define SCALE   5                          /* screen pixels per LCD dot */
#define BEZEL   24
#define LCD_X   BEZEL
#define LCD_Y   BEZEL
#define LCD_W   (CY_LCD_W * SCALE)
#define LCD_H   (CY_LCD_H * SCALE)
#define WIN_W   (LCD_W + 2 * BEZEL)
#define WIN_H   (LCD_H + 2 * BEZEL)

#define FPS     60
#define SLICE   (CY_DISPATCH_HZ / FPS)     /* dispatches in one frame */

static const SDL_Color SHELL = { 0x27, 0x2A, 0x2E, 0xFF };

/* Four grey levels, darkest first. Level 3 is what the panel is cleared to,
 * so it is the colour of an idle STN panel and everything else is a step
 * down from it. */
static const uint32_t PALETTE[4] = {
    0xFF1E2219u, 0xFF454C3Bu, 0xFF737C63u, 0xFF9EAA8Eu,
};

static void render(SDL_Renderer *ren, SDL_Texture *tex, const cy_lcd_t *l)
{
    uint32_t *px;
    int pitch;

    SDL_SetRenderDrawColor(ren, SHELL.r, SHELL.g, SHELL.b, SHELL.a);
    SDL_RenderClear(ren);

    /* One streaming texture at panel resolution rather than 16,000 rects: the
     * scaling is the renderer's problem and it is better at it. */
    if (SDL_LockTexture(tex, NULL, (void **)&px, &pitch) == 0) {
        for (int y = 0; y < CY_LCD_H; y++) {
            uint32_t *row = (uint32_t *)((uint8_t *)px + (size_t)y * pitch);
            for (int x = 0; x < CY_LCD_W; x++)
                row[x] = PALETTE[cy_lcd_dot(l, x, y)];
        }
        SDL_UnlockTexture(tex);
    }

    SDL_Rect dst = { LCD_X, LCD_Y, LCD_W, LCD_H };
    SDL_RenderCopy(ren, tex, NULL, &dst);
    SDL_RenderPresent(ren);
}

int main(int argc, char **argv)
{
    const char *shot = NULL;
    int shot_secs = 5;

    if (argc < 2) {
        fprintf(stderr, "usage: cybiko-sdl <cybiko.img> [cyos] "
                        "[--shot out.bmp [seconds]]\n");
        return 2;
    }
    int cyos = 0;
    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "cyos") == 0) {
            cyos = 1;
        } else if (strcmp(argv[i], "--shot") == 0 && i + 1 < argc) {
            shot = argv[++i];
            if (i + 1 < argc && argv[i + 1][0] != '-'
                && strcmp(argv[i + 1], "cyos") != 0)
                shot_secs = atoi(argv[++i]);
        }
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    static uint8_t img[CY_MEM_SIZE];
    size_t n = fread(img, 1, CY_MEM_SIZE, f);
    fclose(f);

    cy_t *c = (cy_t *)calloc(1, sizeof(cy_t));
    if (!c || cy_init(c) != 0)
        return 2;
    cy_load(c, 0, img, (uint32_t)n);
    cy_flash_load_env(c);

    /* Straight into CyOS, or through the boot ROM from the reset vector. */
    if (cyos) {
        c->pc = cy_read32(c, CY_RAM_BASE + 4) & CY_ADDR_MASK;
        c->e[7] = 0x27FF00;
    } else {
        c->pc = cy_read32(c, 0) & CY_ADDR_MASK;
        c->e[7] = 0x23FF00;
    }

    SDL_SetMainReady();
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    SDL_Window *win = SDL_CreateWindow("Cybiko",
                                       SDL_WINDOWPOS_CENTERED,
                                       SDL_WINDOWPOS_CENTERED,
                                       WIN_W, WIN_H, 0);
    /* No flags: SDL picks accelerated where it can and software where it
     * cannot, which is what lets --shot work under SDL_VIDEODRIVER=dummy.
     * Demanding ACCELERATED just fails there. */
    SDL_Renderer *ren = SDL_CreateRenderer(win, -1, 0);
    SDL_Texture *tex = ren
        ? SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
                            SDL_TEXTUREACCESS_STREAMING, CY_LCD_W, CY_LCD_H)
        : NULL;
    if (!win || !ren || !tex) {
        fprintf(stderr, "SDL window: %s\n", SDL_GetError());
        return 1;
    }

    int running = 1;
    while (running) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT
                || (e.type == SDL_KEYDOWN
                    && e.key.keysym.sym == SDLK_ESCAPE))
                running = 0;
        }

        if (!c->trapped)
            cy_run(c, c->cycles + SLICE);
        if (c->trapped) {
            fprintf(stderr, c->trapped == 2
                    ? "unimplemented opcode at 0x%06X\n"
                    : "left the traced image, wanted 0x%06X\n", c->trap_pc);
            running = 0;
        }

        render(ren, tex, &c->lcd);

        if (shot) {
            /* Run flat out until the mark rather than pacing to it. */
            if (!c->trapped
                && c->cycles < (uint64_t)shot_secs * CY_DISPATCH_HZ)
                continue;
            SDL_Surface *s = SDL_CreateRGBSurfaceWithFormat(
                0, WIN_W, WIN_H, 32, SDL_PIXELFORMAT_ARGB8888);
            SDL_RenderReadPixels(ren, NULL, SDL_PIXELFORMAT_ARGB8888,
                                 s->pixels, s->pitch);
            SDL_SaveBMP(s, shot);
            SDL_FreeSurface(s);
            printf("%s: %dx%d at %.1fs of guest time, display %s\n",
                   shot, WIN_W, WIN_H,
                   (double)c->cycles / CY_DISPATCH_HZ,
                   cy_lcd_on(&c->lcd) ? "on" : "off");
            running = 0;
            continue;
        }
        SDL_Delay(1000 / FPS);
    }

    if (c->serial_len)
        printf("%.*s\n", (int)c->serial_len, c->serial);

    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
    cy_free(c);
    free(c);
    return 0;
}

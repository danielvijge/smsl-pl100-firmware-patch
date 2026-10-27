#!/usr/bin/env python3
"""Build a patched PL100 MCU firmware from IAP_PL100_1v1_b250219.hex.

Patch 1 - track display "Tr03" -> "03/09" (current / total tracks).
  * Both playback branches of the display update (0x0800D4E4) call a new
    routine fmt_track() placed in unused flash after the original image.
  * "03/09" is 86 px in the 33 px font with 2 px letter spacing and fits the
    original 88 px label (x 135..223). "Tr03/09" (117 px) did not: the right
    edge of the screen (~x 230) is hidden behind the front panel window.
  * Discs with 0 or >= 100 tracks (MP3) keep the original "Tr03" / "Tr123".

Patch 2 - backlight fully off in standby.
  * The backlight is active-low (PB1 low = lit; confirmed on the device).
  * Standby entry (0x0800AA20) stops TIM3 and re-inits PB1 (TIM3_CH4) as
    input-pull-up - meant as "off" - but then writes BRR, which turns the
    pull-up into the ~40k pull-down: a weak "on", so the backlight glows.
  * Init PB1 as push-pull output and call GPIO_SetBits instead of
    GPIO_ResetBits, so PB1 is driven high (off). Wake-up (0x0800AA08)
    re-inits PB1 as PWM.

Patch 3 - total time of the previous disc shown after a disc change.
  * The CD module's 0x20 message is latched as the disc total time only while
    total_min (+0x110) is 0; later 0x20 messages are track lengths (+0x108).
    The disc info is only reset by the Open/Close key (0x0800E6E0), so a tray
    pushed shut by hand, or an old-disc 0x20 arriving after the key reset,
    leaves the previous disc's total in place.
  * Also reset the disc info when the module reports the tray open (status
    0x21, handler 0x0800DCDE), mirroring the fields the key handler clears,
    including the "disc ready" bit ([+0x11C] bit1).

Patch 4 - Play pressed while the disc is still loading is lost.
  * The Play/Pause handler (0x0800E10E) sends "play track 1" while the module
    is still reading the TOC (ignored) and sets the play state to 6 anyway,
    so the player shows the play icon and stays on "Read" forever.
  * Play while stopped and loading only sets a pending flag (spare byte
    0x20000238). A hook on the main loop starts playback through the original
    handler once the disc is ready (TOC done, tracks known, total time known
    for audio CDs). Opening the tray, no disc, any other play-state change or
    standby cancels it. Needs disctime (added automatically).

Patch 5 - track time remaining, with an hourglass icon.
  * Remote key DISP (TIME_IR) toggles line 2 between elapsed track time and
    track time remaining = track length (+0x108/+0x10C) - elapsed. MENU
    (IR 0x04) natively gives the same key code and is mapped to a no-op key.
  * Indicator: the unused shuffle icon object (ui+0x24, always hidden) gets a
    30x30 hourglass (icons.py, same format and colour as the repeat icons) and
    is moved to (52,8), right of the play/pause icon. A hook before every
    display update shows it in remaining mode while playing/paused/seeking.
    REMAINING_ICON_ON = False leaves the icon (code, image and hooks) out.
  * The mode lives in spare byte 0x20000239.

Patch 6 - FN cycles the backlight brightness.
  * FN (BRIGHT_IR) has no function on the PL100. It is mapped to key 0x14,
    and a hook on the main loop's get_key then steps the brightness setting
    (0x200004A5) through levels
    5,4,3,2,1,0 = 10/20/35/55/65/100 % (the backlight is active-low, so the
    menu's levels run backwards) and saves it like the settings menu would.
  * The settings load clamps brightness to 1..6, which would turn level 0
    into 1; brightness gets its own check instead (0..5 valid, else 3).
  * After each press line 1 shows the new level as "10%".."100%" for about
    2.5 s, like the firmware shows the volume: a hook on the timer check that
    follows every display update (0x0800E0BC) puts the text into the line 1
    label after the display update has written it. The duration is measured
    on the firmware's 75 ms clock (0x20000560, counted in the TIM1 interrupt),
    not in display updates: those run once per main-loop pass (~40 ms).
  * IR_DIAG_ON (off by default): show the last received IR command as
    "IRxx" on line 1, e.g. to identify remote buttons.

Boot screen version (--version) - "patch VERSION" below "Ver 1.1".
  * The boot screen (0x08004AFA) is drawn straight to the LCD, not through
    LVGL. "Ver 1.1" moves up a little and the patch line is drawn below it in
    the same 12x16 font, centred, 12 px per char (max 18 chars).
  * Without --version the boot screen stays original.

Usage: build_patch.py [--version VERSION] <original.hex> <patched.hex> [patch,...]
  patches: track, backlight, disctime, play, remaining, brightness (default: all)
"""
import argparse
import struct

from icons import hourglass, lv_img_true_color_alpha
from thumbasm import assemble, reglist

BASE = 0x08004000
ENTRY = 0x080041B5
SETTINGS_PAGE = 0x0807FC00  # firmware stores user settings here - never touch

# firmware routines / data (v1.1 b250219)
PUT_CHAR_L1 = 0x0800614A   # (pos, ch)            -> line1[pos] = ch
PUT_NUM_L1 = 0x08006152    # (pos, value, ndigits) -> zero-padded digits into line1
CD_STATE = 0x200008AC      # +0xF4 total tracks, +0xFC current track
GPIO_SET_BITS = 0x0800FB0E  # (port, pins) -> BSRR
PLAY_HANDLER = 0x0800E10E  # Play/Pause key (0x2F) handler
MAIN_TASK = 0x08007F30     # called every main-loop pass while powered on
STANDBY_FIRST_CALL = 0x08008B04  # first call made by standby entry 0x0800A7E0
DISPLAY_REDRAW = 0x2000018C  # set to 1 to refresh the display
PLAY_PENDING = 0x20000238  # spare byte: key-history buffer of the dead hidden-mode detector
TIME_MODE = 0x20000239     # spare byte: 0 elapsed, 1 track remaining
PUT_CHAR_L2 = 0x08006060   # (pos, ch)            -> line2[pos] = ch
PUT_NUM_L2 = 0x08006090    # (pos, value, ndigits) -> zero-padded digits into line2
DISPLAY_UPDATE = 0x0800D4E4
LAST_SHOWN_MIN = 0x20000620  # minutes last written to the time label
IR_TABLE = 0x0802D213      # IR command -> key code
IR_TABLE_LEN = 0x58
TIME_KEY = 0x26            # key case patched to time_toggle (natively MENU, no-op)
BRIGHT_KEY = 0x14          # key caught by key_hook (natively DISP, no function)
NOOP_KEY = 0x5C            # key with no function (natively FN)
SETUP_UI = 0x08028FD8      # GUI-Guider setup_ui(&ui), called once from main
IMG_SET_SRC = 0x0802600E   # lv_img_set_src(obj, src)
OBJ_SET_POS = 0x08013F2E   # lv_obj_set_pos(obj, x, y)
OBJ_SET_SIZE = 0x08015B88  # lv_obj_set_size(obj, w, h)
OBJ_SET_HIDDEN = 0x08015F4A  # lv_obj_set_hidden(obj, en)
OBJ_FLAGS = 0x34           # lv_obj_t byte with the hidden flag (bit 4)
ICON_X, ICON_Y, ICON_SIZE = 52, 8, 30
IR_RAW = 0x200001E0        # last raw IR command byte (cleared after a timeout)
IR_DIAG = 0x2000023B       # spare byte: last IR command, for the diagnostic display
LINE1_BUF = 0x20000860     # line 1 text buffer (10 bytes)
UI = 0x2000082C            # GUI-Guider ui struct, +0x08 line 1 label
LABEL_SET_TEXT = 0x0802758C  # lv_label_set_text(obj, text)
GET_KEY = 0x0800882C       # main-loop key reader (IR > panel > knob)
POWER_ON = 0x2000004C      # 1 = on, 0 = standby
BRIGHTNESS = 0x200004A5    # setting, level 0..6 (saved)
SET_BRIGHTNESS = 0x08005F70
SCHEDULE_SAVE = 0x0800A798  # save settings to flash after a short delay
TIMER_EXPIRED = 0x0800AA7C  # (u16 *t): count down, 1 when it reaches 0
CLOCK_75MS = 0x20000560    # u16, +1 every 10 TIM1 ticks (96 MHz / 72 / 10000 = 7.5 ms)
BRIGHT_OSD = 0x20000294    # spare: dead settings menu cursor bytes, 0 after boot
                           # +0 u16 end time (CLOCK_75MS), +2 u8 active
BRIGHT_OSD_STEPS = 33      # show the level for 33 x 75 ms = 2.5 s
BRIGHT_OSD_TEXT = ['100%', '65%', '55%', '35%', '20%', '10%']   # levels 0..5
DRAW_STR = 0x08009A42      # boot screen: (col, row, str, fg, [sp] bg), 13 px per char
DRAW_CHAR = 0x0800994A     # boot screen: (col, row, ch, fg, [sp] bg), 12x16 glyph
SPLASH_VER_COL_ORIG, SPLASH_VER_COL = 100, 82  # "Ver 1.1" line (panel column = y)
SPLASH_PATCH_COL = 104     # patch version line, below "Ver 1.1"
SPLASH_CENTER_ROW = 116    # horizontal centre of the original "Ver 1.1" (panel row = x)
SPLASH_ADVANCE = 12        # px per char; draw_str's 13 makes "patch v2026-10-25" too wide
SPLASH_MAX_CHARS = 18      # 216 px; the screen edge beyond ~x 230 is hidden
SPLASH_CHARS = set(' .:-+=<>/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')

# Remote buttons (IR commands, tested): MENU 0x04, FN 0x08, DISP 0x0C
TIME_IR = 0x0C             # elapsed / remaining time toggle: DISP
BRIGHT_IR = 0x08           # brightness cycle: FN
IR_DIAG_ON = False         # show the last IR command as "IRxx" on line 1 (diagnostic)
REMAINING_ICON_ON = True   # hourglass icon next to the play icon in remaining-time mode

CAVE = 0x08074350          # first free flash after the original image (ends 0x08074347)


def read_hex(path):
    mem, base = {}, 0
    for ln in open(path):
        ln = ln.strip()
        if not ln:
            continue
        b = bytes.fromhex(ln[1:])
        assert sum(b) & 0xFF == 0, 'bad checksum: ' + ln
        n, addr, t = b[0], (b[1] << 8) | b[2], b[3]
        if t == 0:
            for i, x in enumerate(b[4:4 + n]):
                mem[base + addr + i] = x
        elif t == 4:
            base = int.from_bytes(b[4:6], 'big') << 16
    lo, hi = min(mem), max(mem)
    assert lo == BASE and len(mem) == hi - lo + 1, 'unexpected image layout'
    return bytearray(mem[a] for a in range(lo, hi + 1))


def line_ending(path):
    """Line ending used by the source file, so the output diffs cleanly against it."""
    return '\r\n' if b'\r\n' in open(path, 'rb').read() else '\n'


def write_hex(path, img, eol):
    def rec(n, addr, t, data):
        b = bytes([n, addr >> 8, addr & 0xFF, t]) + data
        return ':' + (b + bytes([-sum(b) & 0xFF])).hex().upper() + eol

    out, cur_hi = [], None
    for off in range(0, len(img), 16):
        a = BASE + off
        if a >> 16 != cur_hi:
            cur_hi = a >> 16
            out.append(rec(2, 0, 4, struct.pack('>H', cur_hi)))
        chunk = bytes(img[off:off + 16])
        out.append(rec(len(chunk), a & 0xFFFF, 0, chunk))
    out.append(rec(4, 0, 5, struct.pack('>I', ENTRY)))
    out.append(':00000001FF' + eol)
    open(path, 'w', newline='').write(''.join(out))


def patch(img, addr, expect, new):
    o = addr - BASE
    cur = bytes(img[o:o + len(expect)])
    assert cur == expect, f'{addr:#x}: expected {expect.hex()} found {cur.hex()}'
    assert len(new) <= len(expect)
    img[o:o + len(new)] = new


def put(img, addr, data):
    o = addr - BASE
    if len(img) < o + len(data):
        img.extend(b'\xff' * (o + len(data) - len(img)))
    assert all(x == 0xFF for x in img[o:o + len(data)]), f'{addr:#x} not free'
    img[o:o + len(data)] = data


# fmt_track(): writes "CC/TT" when the disc has 1..99 tracks,
# otherwise the original "TrCC" / "TrCCC".
FMT_TRACK = [
    'fmt_track:',
    ('push', reglist('r4', 'r5', lr=True)),
    ('ldr_lit', 'r3', 'lit_state'),
    ('ldr', 'r4', 'r3', 8),          # cur = [state+0xFC]
    ('ldr', 'r5', 'r3', 0),          # tot = [state+0xF4]
    ('cbz', 'r5', 'orig'),
    ('cmp', 'r5', 100),
    ('bhs', 'orig'),
    ('movs', 'r0', 0),
    ('uxth', 'r1', 'r4'),
    ('movs', 'r2', 2),
    ('bl', PUT_NUM_L1),
    ('movs', 'r0', 2),
    ('movs', 'r1', 0x2F),            # '/'
    ('bl', PUT_CHAR_L1),
    ('movs', 'r0', 3),
    ('uxth', 'r1', 'r5'),
    ('movs', 'r2', 2),
    ('bl', PUT_NUM_L1),
    ('pop', reglist('r4', 'r5', pc=True)),
    'orig:',
    ('movs', 'r0', 0),
    ('movs', 'r1', 0x54),            # 'T'
    ('bl', PUT_CHAR_L1),
    ('movs', 'r0', 1),
    ('movs', 'r1', 0x72),            # 'r'
    ('bl', PUT_CHAR_L1),
    ('movs', 'r2', 2),
    ('cmp', 'r4', 100),
    ('blo', 'orig_num'),
    ('movs', 'r2', 3),
    'orig_num:',
    ('movs', 'r0', 2),
    ('uxth', 'r1', 'r4'),
    ('bl', PUT_NUM_L1),
    ('pop', reglist('r4', 'r5', pc=True)),
    ('align',),
    'lit_state:',
    ('word', CD_STATE + 0xF4),
]


def cave_addr(img):
    """Next free word-aligned address in the area after the original image."""
    return max(CAVE, (BASE + len(img) + 3) & ~3)


def patch_track(img):
    cave, labels = assemble(FMT_TRACK, cave_addr(img))
    fmt = labels['fmt_track']

    # Playback (state 3/6): replace "print current track" block, continue at 0x0800D70A
    site1, _ = assemble([('bl', fmt), ('b', 0x0800D70A)], 0x0800D6DE)
    patch(img, 0x0800D6DE, bytes.fromhex('4148d0f8fc00'), site1)
    # Seek (state 7/8): same, continue at 0x0800D77E
    site2, _ = assemble([('bl', fmt), ('b', 0x0800D77E)], 0x0800D752)
    patch(img, 0x0800D752, bytes.fromhex('2448d0f8fc00'), site2)

    put(img, fmt, cave)
    print(f'track: fmt_track at {fmt:#x}, {len(cave)} bytes')


def patch_backlight(img):
    # backlight_off(): GPIO_InitTypeDef.mode = 0x48 (IPU) -> 0x10 (Out_PP); speed 3 stays
    patch(img, 0x0800AA40, bytes([0x48, 0x20]), bytes([0x10, 0x20]))
    # GPIO_ResetBits(GPIOB, PB1) -> GPIO_SetBits(GPIOB, PB1)
    site, _ = assemble([('bl', GPIO_SET_BITS)], 0x0800AA58)
    patch(img, 0x0800AA58, bytes.fromhex('05f05bf8'), site)
    print('backlight: PB1 driven high (off) in standby')


# tray_open(): status 0x21 handler - [+7] = 2 ("Eject") as before, then clear
# the disc info like the Open/Close key does (0x0800E6F0..0x0800E714).
TRAY_OPEN = [
    'tray_open:',
    ('ldr_lit', 'r1', 'lit_state'),
    ('movs', 'r0', 2),
    ('strb', 'r0', 'r1', 7),         # tray status = Eject
    ('adds_i8', 'r1', 0xF4),         # r1 = state + 0xF4
    ('movs', 'r0', 0),
    ('movs', 'r2', 1),
    ('str', 'r0', 'r1', 0x00),       # +0xF4  total tracks
    ('str', 'r2', 'r1', 0x08),       # +0xFC  current track = 1
    ('str', 'r0', 'r1', 0x0C),       # +0x100 minutes
    ('strb', 'r0', 'r1', 0x10),      # +0x104 seconds
    ('str', 'r0', 'r1', 0x14),       # +0x108 track length min
    ('strb', 'r0', 'r1', 0x18),      # +0x10C track length sec
    ('str', 'r0', 'r1', 0x1C),       # +0x110 disc total min
    ('adds_i8', 'r1', 0x20),         # r1 = state + 0x114
    ('strb', 'r0', 'r1', 0x00),      # +0x114 disc total sec
    ('strb', 'r0', 'r1', 0x04),      # +0x118 disc type flags
    ('ldr', 'r0', 'r1', 0x08),       # +0x11C status flags:
    ('movs', 'r2', 2),
    ('bics', 'r0', 'r2'),            #   clear bit1 "disc ready"
    ('str', 'r0', 'r1', 0x08),
    ('bx_lr',),
    ('align',),
    'lit_state:',
    ('word', CD_STATE),
]


# disc_ready() -> r0: TOC done ([+0x11C] bit1), track count known and, for an
# audio CD ([+0x118] bit0), the total time received. Clobbers r0-r2.
DISC_READY = [
    'disc_ready:',
    ('ldr_lit', 'r2', 'lit_state_f4'),
    ('ldr', 'r0', 'r2', 0x28),       # +0x11C
    ('movs', 'r1', 2),
    ('tst', 'r0', 'r1'),
    ('beq', 'not_ready'),
    ('ldr', 'r0', 'r2', 0x00),       # +0xF4 total tracks
    ('cbz', 'r0', 'not_ready'),
    ('ldr', 'r0', 'r2', 0x24),       # +0x118 disc type
    ('lsls', 'r0', 'r0', 31),
    ('beq', 'ready'),                # not CD-DA: no total time to wait for
    ('ldr', 'r0', 'r2', 0x1C),       # +0x110 total min
    ('cbnz', 'r0', 'ready'),
    ('adds_i8', 'r2', 0x20),
    ('ldrb', 'r0', 'r2', 0),         # +0x114 total sec
    ('cbnz', 'r0', 'ready'),
    'not_ready:',
    ('movs', 'r0', 0),
    ('bx_lr',),
    'ready:',
    ('movs', 'r0', 1),
    ('bx_lr',),
]

# play_key(): Play/Pause pressed. While stopped and the disc is still loading
# (tray status 0 Read / 1 Load / 5 Read, disc not ready) only remember it;
# otherwise run the original handler.
PLAY_KEY = [
    'play_key:',
    ('push', reglist('r4', lr=True)),
    ('ldr_lit', 'r3', 'lit_state'),
    ('ldrb', 'r0', 'r3', 4),         # play state
    ('cmp', 'r0', 1),                # 1 = stopped
    ('bne', 'play_now'),
    ('ldrb', 'r0', 'r3', 7),         # tray status
    ('cbz', 'r0', 'loading'),
    ('cmp', 'r0', 1),
    ('beq', 'loading'),
    ('cmp', 'r0', 5),
    ('bne', 'play_now'),
    'loading:',
    ('bl', 'disc_ready'),
    ('cbnz', 'r0', 'play_now'),
    ('ldr_lit', 'r1', 'lit_pending'),
    ('movs', 'r0', 1),
    ('strb', 'r0', 'r1', 0),
    ('pop', reglist('r4', pc=True)),
    'play_now:',
    ('bl', PLAY_HANDLER),
    ('pop', reglist('r4', pc=True)),

    # play_poll(): replaces the main loop's call to 0x08007F30. Starts a
    # pending Play once the disc is ready; drops it if the tray opens, there
    # is no disc / the tray is blocked, or the play state changed meanwhile.
    'play_poll:',
    ('push', reglist('r4', lr=True)),
    ('bl', MAIN_TASK),
    ('ldr_lit', 'r4', 'lit_pending'),
    ('ldrb', 'r0', 'r4', 0),
    ('cbz', 'r0', 'poll_done'),
    ('ldr_lit', 'r3', 'lit_state'),
    ('ldrb', 'r0', 'r3', 7),         # tray status 2 Eject / 3 Disc / 4 Block
    ('subs_i3', 'r0', 'r0', 2),
    ('cmp', 'r0', 2),
    ('bls', 'poll_cancel'),
    ('ldrb', 'r0', 'r3', 4),
    ('cmp', 'r0', 1),
    ('bne', 'poll_cancel'),
    ('bl', 'disc_ready'),
    ('cbz', 'r0', 'poll_done'),
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r4', 0),
    ('bl', PLAY_HANDLER),
    ('ldr_lit', 'r1', 'lit_redraw'),
    ('movs', 'r0', 1),
    ('strb', 'r0', 'r1', 0),         # same as the key dispatcher after a key
    'poll_done:',
    ('pop', reglist('r4', pc=True)),
    'poll_cancel:',
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r4', 0),
    ('pop', reglist('r4', pc=True)),

    # play_standby(): standby entry - forget a pending Play, then continue
    # with the original first call of the standby routine.
    'play_standby:',
    ('ldr_lit', 'r1', 'lit_pending'),
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r1', 0),
    ('b.w', STANDBY_FIRST_CALL),
] + DISC_READY + [
    ('align',),
    'lit_state:',
    ('word', CD_STATE),
    'lit_state_f4:',
    ('word', CD_STATE + 0xF4),
    'lit_pending:',
    ('word', PLAY_PENDING),
    'lit_redraw:',
    ('word', DISPLAY_REDRAW),
]


def patch_disctime(img):
    cave, labels = assemble(TRAY_OPEN, cave_addr(img))
    fn = labels['tray_open']
    # case 0x21: movs r0,#2 / ldr r1,=state / strb r0,[r1,#7] / b 0x0800DD3A
    site, _ = assemble([('bl', fn), ('b', 0x0800DD3A), ('nop',)], 0x0800DCDE)
    patch(img, 0x0800DCDE, bytes.fromhex('0220e649c87129e0'), site)
    put(img, fn, cave)
    print(f'disctime: tray_open at {fn:#x}, {len(cave)} bytes')


def patch_play(img):
    cave, labels = assemble(PLAY_KEY, cave_addr(img))
    # key 0x2F case in the dispatcher: bl 0x0800E10E -> bl play_key
    site, _ = assemble([('bl', labels['play_key'])], 0x0800E766)
    patch(img, 0x0800E766, bytes.fromhex('fff7d2fc'), site)
    # main loop (powered on): bl 0x08007F30 -> bl play_poll
    site, _ = assemble([('bl', labels['play_poll'])], 0x08004324)
    patch(img, 0x08004324, bytes.fromhex('03f004fe'), site)
    # standby entry 0x0800A7E0: bl 0x08008B04 -> bl play_standby
    site, _ = assemble([('bl', labels['play_standby'])], 0x0800A7E2)
    patch(img, 0x0800A7E2, bytes.fromhex('fef78ff9'), site)
    put(img, labels['play_key'], cave)
    print(f"play: play_key at {labels['play_key']:#x}, {len(cave)} bytes")


ICON_HEADER, ICON_DATA = lv_img_true_color_alpha(hourglass(ICON_SIZE), ICON_SIZE, ICON_SIZE)
DISP_HOOK_ON = REMAINING_ICON_ON or IR_DIAG_ON

# Hourglass visibility, part of disp_hook (REMAINING_ICON_ON only); r4 = want hidden.
ICON_VISIBILITY = [
    ('movs', 'r4', 1),               # want hidden
    ('ldr_lit', 'r1', 'lit_mode'),
    ('ldrb', 'r0', 'r1', 0),
    ('cbz', 'r0', 'apply'),
    ('ldr_lit', 'r1', 'lit_state'),
    ('ldrb', 'r0', 'r1', 4),         # play state 3/6/7/8
    ('cmp', 'r0', 3),
    ('beq', 'want_shown'),
    ('cmp', 'r0', 6),
    ('beq', 'want_shown'),
    ('cmp', 'r0', 7),
    ('beq', 'want_shown'),
    ('cmp', 'r0', 8),
    ('bne', 'apply'),
    'want_shown:',
    ('movs', 'r4', 0),
    'apply:',
    ('ldr_lit', 'r1', 'lit_ui'),
    ('ldr', 'r0', 'r1', 0x24),       # icon object
    ('cbz', 'r0', 'disp_orig'),
    ('mov', 'r2', 'r0'),
    ('adds_i8', 'r2', OBJ_FLAGS),
    ('ldrb', 'r2', 'r2', 0),
    ('lsrs', 'r2', 'r2', 4),         # bit 4 = hidden
    ('movs', 'r3', 1),
    ('ands', 'r2', 'r3'),
    ('cmp', 'r2', 'r4'),
    ('beq', 'disp_orig'),
    ('mov', 'r1', 'r4'),
    ('bl', OBJ_SET_HIDDEN),
]

UI_SETUP = [
    # ui_setup(): wraps setup_ui() in main. Turns the unused shuffle icon
    # object (ui+0x24, always hidden) into the hourglass, right of the
    # play/pause icon (x 5..44) and left of the repeat icon (x 90).
    'ui_setup:',
    ('push', reglist('r4', lr=True)),
    ('bl', SETUP_UI),
    ('ldr_lit', 'r1', 'lit_ui'),
    ('ldr', 'r4', 'r1', 0x24),
    ('mov', 'r0', 'r4'),
    ('ldr_lit', 'r1', 'lit_icon'),
    ('bl', IMG_SET_SRC),
    ('mov', 'r0', 'r4'),
    ('movs', 'r1', ICON_X),
    ('movs', 'r2', ICON_Y),
    ('bl', OBJ_SET_POS),
    ('mov', 'r0', 'r4'),
    ('movs', 'r1', ICON_SIZE),
    ('movs', 'r2', ICON_SIZE),
    ('bl', OBJ_SET_SIZE),
    ('pop', reglist('r4', pc=True)),
]



# Diagnostic (IR_DIAG_ON only), called after each display update.
IR_SHOW = [
    # ir_show(): diagnostic - once an IR command has been seen (IR_DIAG, set
    # by key_hook in the brightness patch), show it as "IRxx" on line 1.
    'ir_show:',
    ('ldr_lit', 'r1', 'lit_ir_diag'),
    ('ldrb', 'r2', 'r1', 0),
    ('cbz', 'r2', 'ir_show_done'),
    ('push', reglist('r4', lr=True)),
    ('ldr_lit', 'r3', 'lit_line1'),
    ('movs', 'r0', 0x49),            # 'I'
    ('strb', 'r0', 'r3', 0),
    ('movs', 'r0', 0x52),            # 'R'
    ('strb', 'r0', 'r3', 1),
    ('lsrs', 'r0', 'r2', 4),
    ('bl', 'hex_digit'),
    ('strb', 'r0', 'r3', 2),
    ('movs', 'r0', 15),
    ('ands', 'r0', 'r2'),
    ('bl', 'hex_digit'),
    ('strb', 'r0', 'r3', 3),
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r3', 4),
    ('ldr_lit', 'r1', 'lit_ui'),
    ('ldr', 'r0', 'r1', 8),          # line 1 label
    ('mov', 'r1', 'r3'),
    ('bl', LABEL_SET_TEXT),
    ('pop', reglist('r4', pc=True)),
    'ir_show_done:',
    ('bx_lr',),
    'hex_digit:',
    ('adds_i8', 'r0', 0x30),
    ('cmp', 'r0', 0x39),
    ('bls', 'hex_done'),
    ('adds_i8', 'r0', 7),
    'hex_done:',
    ('bx_lr',),
]


# fmt_time(): line 2 time during play/pause/seek. Elapsed track time, or in
# remaining mode track length - elapsed (falls back to elapsed while the
# length is unknown).
FMT_TIME = [
    'fmt_time:',
    ('push', reglist('r4', 'r5', lr=True)),
    ('ldr_lit', 'r3', 'lit_state_f4'),
    ('ldr', 'r4', 'r3', 0x0C),       # +0x100 elapsed min
    ('ldrb', 'r5', 'r3', 0x10),      # +0x104 elapsed sec
    ('ldr_lit', 'r0', 'lit_mode'),
    ('ldrb', 'r0', 'r0', 0),
    ('cbz', 'r0', 'show'),
    ('ldr', 'r1', 'r3', 0x14),       # +0x108 track length min
    ('ldrb', 'r2', 'r3', 0x18),      # +0x10C track length sec
    ('movs', 'r0', 60),
    ('muls', 'r1', 'r0'),
    ('adds', 'r1', 'r1', 'r2'),      # length in s
    ('cbz', 'r1', 'show'),
    ('muls', 'r4', 'r0'),
    ('adds', 'r4', 'r4', 'r5'),      # elapsed in s
    ('subs', 'r1', 'r1', 'r4'),
    ('bpl', 'non_neg'),
    ('movs', 'r1', 0),
    'non_neg:',
    ('udiv', 'r4', 'r1', 'r0'),      # minutes
    ('muls', 'r0', 'r4'),
    ('subs', 'r5', 'r1', 'r0'),      # seconds
    'show:',
    ('movs', 'r0', 0),
    ('uxth', 'r1', 'r4'),
    ('movs', 'r2', 2),
    ('bl', PUT_NUM_L2),
    ('movs', 'r0', 2),
    ('movs', 'r1', 0x2E),            # '.'
    ('bl', PUT_CHAR_L2),
    ('movs', 'r0', 3),
    ('uxth', 'r1', 'r5'),
    ('movs', 'r2', 2),
    ('bl', PUT_NUM_L2),
    ('pop', reglist('r4', 'r5', pc=True)),

    # time_toggle(): key 0x26 (TIME_IR) - flip elapsed <-> remaining, force the
    # time label to be rewritten and the screen redrawn.
    'time_toggle:',
    ('ldr_lit', 'r1', 'lit_mode'),
    ('ldrb', 'r0', 'r1', 0),
    ('movs', 'r2', 1),
    ('subs', 'r0', 'r2', 'r0'),
    ('strb', 'r0', 'r1', 0),
    ('ldr_lit', 'r1', 'lit_last_min'),
    ('movs', 'r0', 0xFF),
    ('str', 'r0', 'r1', 0),
    ('ldr_lit', 'r1', 'lit_redraw'),
    ('movs', 'r0', 1),
    ('strb', 'r0', 'r1', 0),
    ('bx_lr',),

    # disp_hook(): runs before every display update (only installed when the
    # icon or the IR diagnostic is enabled). Icon: show the "time remaining"
    # hourglass (object ui+0x24) in remaining mode while playing/paused/seeking,
    # hide it otherwise; only calls lv_obj_set_hidden when that changes.
    *(['disp_hook:',
       ('push', reglist('r4', lr=True)),
       *(ICON_VISIBILITY if REMAINING_ICON_ON else []),
       'disp_orig:',
       ('bl', DISPLAY_UPDATE),
       *([('bl', 'ir_show')] if IR_DIAG_ON else []),
       ('pop', reglist('r4', pc=True))] if DISP_HOOK_ON else []),

    *(IR_SHOW if IR_DIAG_ON else []),

    *(UI_SETUP if REMAINING_ICON_ON else []),
    ('align',),
    'lit_state:',
    ('word', CD_STATE),
    'lit_state_f4:',
    ('word', CD_STATE + 0xF4),
    'lit_mode:',
    ('word', TIME_MODE),
    'lit_last_min:',
    ('word', LAST_SHOWN_MIN),
    'lit_redraw:',
    ('word', DISPLAY_REDRAW),
    *(['lit_ui:', ('word', UI)] if DISP_HOOK_ON else []),
    *(['lit_ir_diag:', ('word', IR_DIAG),
       'lit_line1:', ('word', LINE1_BUF)] if IR_DIAG_ON else []),
    *(['lit_icon:', ('word', 'icon_dsc'),
       # lv_img_dsc_t: header, data_size, data
       'icon_dsc:', ('word', ICON_HEADER), ('word', len(ICON_DATA)), ('word', 'icon_data'),
       'icon_data:', ('bytes', ICON_DATA)] if REMAINING_ICON_ON else []),
]


# key_hook(): replaces the main loop's call to get_key (0x0800882C).
# Key 0x14 (BRIGHT_IR; natively DISP, no function on the PL100) cycles the
# backlight brightness while powered on. With IR_DIAG_ON, also records the
# last IR command.
KEY_HOOK = [
    'key_hook:',
    ('push', reglist('r4', lr=True)),
    ('bl', GET_KEY),
    ('mov', 'r4', 'r0'),
] + ([
    ('cmp', 'r4', 0xFF),
    ('beq', 'no_diag'),
    ('ldr_lit', 'r1', 'lit_ir_raw'),
    ('ldrb', 'r0', 'r1', 0),         # raw IR command, 0 if the key was not IR
    ('cbz', 'r0', 'no_diag'),
    ('ldr_lit', 'r1', 'lit_ir_diag'),
    ('strb', 'r0', 'r1', 0),
    'no_diag:',
] if IR_DIAG_ON else []) + [
    ('cmp', 'r4', BRIGHT_KEY),
    ('bne', 'key_ret'),
    ('ldr_lit', 'r1', 'lit_power'),
    ('ldrb', 'r0', 'r1', 0),
    ('cbz', 'r0', 'key_ret'),        # standby: leave it to the standby handler
    ('bl', 'bright_cycle'),
    ('movs', 'r4', 0xFF),            # consumed
    'key_ret:',
    ('mov', 'r0', 'r4'),
    ('pop', reglist('r4', pc=True)),

    # bright_cycle(): levels 5,4,3,2,1,0 = 10,20,35,55,65,100 % (active-low
    # backlight), then back to 5. Level 6 (off) is skipped. Saved like the
    # settings menu does.
    'bright_cycle:',
    ('push', reglist('r4', lr=True)),
    ('ldr_lit', 'r4', 'lit_bright'),
    ('ldrb', 'r0', 'r4', 0),
    ('cbz', 'r0', 'bright_wrap'),
    ('cmp', 'r0', 5),
    ('bhi', 'bright_wrap'),
    ('subs_i3', 'r0', 'r0', 1),
    ('b', 'bright_set'),
    'bright_wrap:',
    ('movs', 'r0', 5),
    'bright_set:',
    ('strb', 'r0', 'r4', 0),
    ('bl', SET_BRIGHTNESS),
    ('bl', SCHEDULE_SAVE),
    ('ldr_lit', 'r1', 'lit_clock'),  # show the new level on line 1
    ('ldrh', 'r0', 'r1', 0),
    ('adds_i8', 'r0', BRIGHT_OSD_STEPS),
    ('ldr_lit', 'r1', 'lit_osd'),
    ('strh', 'r0', 'r1', 0),         # end time
    ('movs', 'r0', 1),
    ('strb', 'r0', 'r1', 2),         # active
    ('pop', reglist('r4', pc=True)),

    # bright_tick(): replaces the timer check right after the display update
    # (once per tick). While the OSD timer runs, line 1 shows the level.
    'bright_tick:',
    ('push', reglist('r4', lr=True)),
    ('mov', 'r4', 'r0'),
    ('ldr_lit', 'r3', 'lit_osd'),
    ('ldrb', 'r0', 'r3', 2),
    ('cbz', 'r0', 'osd_done'),       # not active
    ('ldrh', 'r0', 'r3', 0),
    ('ldr_lit', 'r1', 'lit_clock'),
    ('ldrh', 'r1', 'r1', 0),
    ('subs', 'r0', 'r0', 'r1'),
    ('uxth', 'r0', 'r0'),            # time left (75 ms steps), 16-bit wrap
    ('cbz', 'r0', 'osd_end'),
    ('cmp', 'r0', BRIGHT_OSD_STEPS),
    ('bhi', 'osd_end'),
    ('ldr_lit', 'r1', 'lit_bright'),
    ('ldrb', 'r1', 'r1', 0),
    ('cmp', 'r1', 5),
    ('bhi', 'osd_done'),
    ('lsls', 'r1', 'r1', 2),
    ('ldr_lit', 'r0', 'lit_osd_text'),
    ('adds', 'r1', 'r0', 'r1'),
    ('ldr', 'r1', 'r1', 0),          # text for this level
    ('ldr_lit', 'r0', 'lit_ui_osd'),
    ('ldr', 'r0', 'r0', 8),          # line 1 label
    ('bl', LABEL_SET_TEXT),
    ('b', 'osd_done'),
    'osd_end:',                      # time is up: the next display update
    ('movs', 'r0', 0),               # shows the track again
    ('strb', 'r0', 'r3', 2),
    'osd_done:',
    ('mov', 'r0', 'r4'),
    ('bl', TIMER_EXPIRED),
    ('pop', reglist('r4', pc=True)),

    # bright_load(): replaces the generic 1..6 clamp when the saved brightness
    # is loaded, so level 0 (100 %) survives a power cycle. Anything else -> 3.
    'bright_load:',
    ('cmp', 'r0', 5),
    ('bls', 'bright_ok'),
    ('movs', 'r0', 3),
    'bright_ok:',
    ('bx_lr',),
    ('align',),
    'lit_ir_raw:',
    ('word', IR_RAW),
    'lit_ir_diag:',
    ('word', IR_DIAG),
    'lit_power:',
    ('word', POWER_ON),
    'lit_bright:',
    ('word', BRIGHTNESS),
    'lit_osd:',
    ('word', BRIGHT_OSD),
    'lit_clock:',
    ('word', CLOCK_75MS),
    'lit_ui_osd:',
    ('word', UI),
    'lit_osd_text:',
    ('word', 'osd_text'),
    'osd_text:',                     # text pointer per level
    *[('word', f'osd_text_{i}') for i in range(len(BRIGHT_OSD_TEXT))],
    *[x for i, t in enumerate(BRIGHT_OSD_TEXT) for x in (f'osd_text_{i}:', ('bytes', t.encode() + b'\0'))],
]


def patch_brightness(img):
    cave, lab = assemble(KEY_HOOK, cave_addr(img))
    # main loop: bl get_key -> bl key_hook
    code, _ = assemble([('bl', lab['key_hook'])], 0x08004300)
    patch(img, 0x08004300, bytes.fromhex('04f094fa'), code)
    # settings load: brightness clamp(val, 7) -> bright_load
    code, _ = assemble([('bl', lab['bright_load'])], 0x08006EBC)
    patch(img, 0x08006EBC, bytes.fromhex('fff778fe'), code)
    # timer check right after the display update -> bright_tick (level on line 1)
    old, _ = assemble([('bl', TIMER_EXPIRED)], 0x0800E0BC)
    code, _ = assemble([('bl', lab['bright_tick'])], 0x0800E0BC)
    patch(img, 0x0800E0BC, old, code)
    put(img, lab['key_hook'], cave)
    print(f"brightness: key_hook at {lab['key_hook']:#x}, {len(cave)} bytes"
          + (' (with IR code diagnostic)' if IR_DIAG_ON else ''))


def patch_remaining(img):
    cave, lab = assemble(FMT_TIME, cave_addr(img))
    # line-2 time in the play/pause (0x0800D70A) and seek (0x0800D77E) branches
    for site, cont in ((0x0800D70A, 0x0800D730), (0x0800D77E, 0x0800D7A4)):
        code, _ = assemble([('bl', lab['fmt_time']), ('b', cont)], site)
        expect = bytes(img[site - BASE:site - BASE + 6])
        assert expect[2:] == bytes.fromhex('b0f80001'), f'{site:#x}: unexpected code'
        patch(img, site, expect, code)
    # key 0x26 case (did only "0x20000186 = 2") -> time_toggle
    code, _ = assemble([('bl', lab['time_toggle']), ('b', 0x0800ED4C), ('nop',)], 0x0800ED42)
    patch(img, 0x0800ED42, bytes.fromhex('02200f49088000e0'), code)
    if DISP_HOOK_ON:
        # display update call in the main task -> disp_hook
        code, _ = assemble([('bl', lab['disp_hook'])], 0x0800E0B6)
        patch(img, 0x0800E0B6, bytes.fromhex('fff715fa'), code)
    if REMAINING_ICON_ON:
        # main: bl setup_ui -> bl ui_setup (set up the hourglass icon object)
        code, _ = assemble([('bl', lab['ui_setup'])], 0x080042C6)
        patch(img, 0x080042C6, bytes.fromhex('24f087fe'), code)
    put(img, lab['fmt_time'], cave)
    print(f"remaining: fmt_time at {lab['fmt_time']:#x}, {len(cave)} bytes"
          + (' (with hourglass icon)' if REMAINING_ICON_ON else ' (no icon)'))


# splash_hook(): draws the original "Ver 1.1" line, then the patch version
# line below it. Replaces the bl draw_str at 0x08004B1A, so r0-r3 still hold
# the original arguments.
def splash_hook(text, row):
    return [
        'splash_hook:',
        ('push', reglist('r4', 'r5', 'r6', lr=True)),
        ('sub_sp', 8),
        ('movs', 'r4', 0),
        ('str_sp', 'r4', 0),             # background: black
        ('bl', DRAW_STR),
        ('ldr_lit', 'r4', 'lit_text'),
        ('movs', 'r5', row),
        'next_char:',
        ('ldrb', 'r2', 'r4', 0),
        ('cbz', 'r2', 'done'),
        ('movs', 'r0', SPLASH_PATCH_COL),
        ('mov', 'r1', 'r5'),
        ('ldr_lit', 'r3', 'lit_white'),
        ('bl', DRAW_CHAR),
        ('adds_i8', 'r4', 1),
        ('adds_i8', 'r5', SPLASH_ADVANCE),
        ('b', 'next_char'),
        'done:',
        ('add_sp', 8),
        ('pop', reglist('r4', 'r5', 'r6', pc=True)),
        ('align',),
        'lit_text:',
        ('word', 'text'),
        'lit_white:',
        ('word', 0xFFFF),
        'text:',
        ('bytes', text.encode('ascii') + b'\0'),
    ]


def patch_splash(img, version):
    text = 'patch ' + version
    bad = sorted(set(c for c in text if c not in SPLASH_CHARS))
    if bad:
        raise SystemExit(f'--version: unsupported character(s) {"".join(bad)!r} '
                         f'(boot screen font has A-Z a-z 0-9 and " .:-+=<>/")')
    if len(text) > SPLASH_MAX_CHARS:
        raise SystemExit(f'--version: "{text}" is {len(text)} characters, '
                         f'at most {SPLASH_MAX_CHARS} fit on the boot screen')
    row = SPLASH_CENTER_ROW - len(text) * SPLASH_ADVANCE // 2
    cave, lab = assemble(splash_hook(text, row), cave_addr(img))
    # "Ver 1.1": column 100 -> 82, to make room for the patch line below it
    patch(img, 0x08004B18, bytes([SPLASH_VER_COL_ORIG, 0x20]), bytes([SPLASH_VER_COL, 0x20]))
    code, _ = assemble([('bl', lab['splash_hook'])], 0x08004B1A)
    patch(img, 0x08004B1A, bytes.fromhex('04f092ff'), code)
    put(img, lab['splash_hook'], cave)
    print(f"splash: \"{text}\" at {lab['splash_hook']:#x}, {len(cave)} bytes")


def remap_buttons(img, names):
    """IR command -> key table: TIME_IR gives the time toggle key, BRIGHT_IR
    the brightness key; any other button that natively gives one of those
    keys (MENU gives 0x26, DISP 0x14) gets a no-op key instead."""
    want = {}
    if 'remaining' in names:
        want[TIME_IR] = TIME_KEY
    if 'brightness' in names:
        want[BRIGHT_IR] = BRIGHT_KEY
    used = set(want.values())
    for ir in range(IR_TABLE_LEN):
        key = img[IR_TABLE + ir - BASE]
        new = want.get(ir, NOOP_KEY if key in used else key)
        if new != key:
            patch(img, IR_TABLE + ir, bytes([key]), bytes([new]))


PATCHES = {'track': patch_track, 'backlight': patch_backlight, 'disctime': patch_disctime,
           'play': patch_play, 'remaining': patch_remaining, 'brightness': patch_brightness}
# 'play' relies on disctime clearing the disc-ready state when the tray opens
REQUIRES = {'play': ['disctime']}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('patches', nargs='?', default=','.join(PATCHES))
    ap.add_argument('--version', help='show "patch VERSION" on the boot screen, e.g. v2026-10-25')
    args = ap.parse_args()

    names = args.patches.split(',')
    for name in list(names):
        for dep in REQUIRES.get(name, []):
            if dep not in names:
                print(f'{name} needs {dep}: adding it')
                names.insert(names.index(name), dep)

    img = read_hex(args.src)
    for name in names:
        PATCHES[name](img)
    remap_buttons(img, names)
    if args.version:
        patch_splash(img, args.version)
    # ispV2.4 fails ("Index was outside the bounds of the array") on an image
    # that is not a whole number of 32-bit words; pad with erased-flash 0xFF
    img.extend(b'\xff' * (-len(img) % 4))
    assert BASE + len(img) <= SETTINGS_PAGE
    write_hex(args.dst, img, line_ending(args.src))
    print(f'image ends at {BASE + len(img) - 1:#x}')


if __name__ == '__main__':
    main()

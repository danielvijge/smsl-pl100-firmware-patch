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
  * Play while stopped and loading queues it (spare byte 0x20000238); Play
    again or Stop cancels it (the first Stop only cancels; the firmware turns
    Stop while stopped into Eject). A hook on the main loop starts playback
    through the original handler once the disc is ready (TOC done, tracks
    known, total time known for audio CDs). Eject, no disc, any other
    play-state change or standby cancels it. Needs disctime (added
    automatically).
  * The play icon means "it is going to play": a tick hook shows it (and
    hides the stop icon) while a Play is queued.
  * Standby switches the CD module off; it reloads the disc at power-on (also
    after a cold start, which runs the standby entry once). Standby entry
    therefore resets the disc state (disctime's disc_reset), so Play during
    that reload is queued too.
  * AUTOPLAY_ON - auto-play on insert, switched on the player: Play at an
    empty slot ("Disc", where the dispatcher drops Play) toggles it, shows
    "AUTO" / "OFF" on line 1 for 2.5 s and saves it in a settings byte of the
    dead settings menu (0x200004DA = 2, record +0x2C). While it is on, the
    play icon shows at the empty slot, and a disc inserted later queues a Play
    when it starts loading (once per disc). Not for the reload after power-on.

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
  * PREGAP_MINUS_ON: the gap before a track, which the module counts down,
    is shown as "-0.03".."-0.01" (rounded up) in both modes. Needs cdtime's
    gap detection (added automatically).

Patch shuffle - true shuffle and a safer end-of-track check.
  * Repeat and shuffle are one play mode (0x20000189: 0 normal, 1 repeat one,
    2 repeat disc, 3 shuffle) shown by one icon, so they exclude each other.
    The firmware's shuffle picks rand() % tracks + 1 at every track end, Next
    and Previous: tracks repeat and it never ends.
  * TRUE_SHUFFLE_ON: every track once in random order, then stop (shuffle
    stays selected; Play starts a new round with a random first track).
    Previous goes back through the order played; Stop + Play continues the
    round. Switching shuffle on starts a new round and reseeds rand(). More
    than 255 tracks: the firmware's behaviour.
  * TRACK_END_FIX_ON: the firmware acts 2 s before the stored track length
    ends (shuffle, repeat one, stop after the last track), but that length is
    the previous track's until the module's next length message (~22 s). The
    check now only runs with the playing track's own length. It also skipped
    every length with 0 minutes or 0 seconds (tracks under 1 min, or x:00);
    now only an unknown length (0:00).
  * LAST_TRACK_FULL_ON: in normal mode the firmware stopped the last track 2 s
    before its length (the remaining time never got below 0:03, and the end
    of the disc was cut). Now it plays to the end and the module's own
    end-of-disc message stops it (0x0800D9C4); as a safety net, still playing
    3 s past the last track's length (time fill keeps counting) stops it.

Patch cdtime - time messages of the CD module.
  * About 7 % of the module's messages fail the checksum and are dropped, so
    the time sometimes jumps by 2 s. TIME_FILL_ON: when playing and no time
    message came for 1.275 s, advance the elapsed time by 1 s (count down in
    the gap); the next message sets the module's own time again.
  * Notes for each time message whether it is from the gap before a track,
    for PREGAP_MINUS_ON: the module counts the gap down, and those messages
    have a non-zero frames byte (normal play does too, occasionally, so a
    count down or a new track is required as well).

Patch 6 - FN cycles the backlight brightness.
  * FN (BRIGHT_IR) has no function on the PL100. It is mapped to key 0x14,
    and a hook on the main loop's get_key then steps the brightness setting
    (0x200004A5) through levels
    5,4,3,2,1,0 = 10/20/35/55/65/100 % (the backlight is active-low, so the
    menu's levels run backwards) and saves it like the settings menu would.
  * The settings load clamps brightness to 1..6, which would turn level 0
    into 1; brightness gets its own check instead (0..5 valid, else 3).
  * After each press line 1 shows the new level as "10%".."100%" for about
    2.5 s, like the firmware shows the volume: a tick hook (see
    install_tick_hooks) puts the text into the line 1 label after the display
    update has written it. The duration is measured
    on the firmware's 75 ms clock (0x20000560, counted in the TIM1 interrupt),
    not in display updates: those run once per main-loop pass (~40 ms).
  * PANEL_VOL_ON: without a headphone the player's own Vol- and Vol+ (keys
    0x11 / 0x10, the same as the remote's; told apart by the IR flag) did
    nothing. Vol- now toggles elapsed / remaining (needs the remaining patch)
    and Vol+ cycles normal, repeat one, repeat disc, shuffle via the
    firmware's Repeat / Shuffle keys; the icons show the result. Holding a
    button is one press. With a headphone, and on the remote, unchanged.
  * IR_DIAG_ON (off by default): show the last received IR command as
    "IRxx" on line 1, e.g. to identify remote buttons.

Boot screen version (--version) - "patch VERSION" below "Ver 1.1".
  * The boot screen (0x08004AFA) is drawn straight to the LCD, not through
    LVGL. "Ver 1.1" moves up a little and the patch line is drawn below it in
    the same 12x16 font, centred, 12 px per char (max 18 chars).
  * Without --version the boot screen stays original.

Usage: build_patch.py [--version VERSION] <original.hex> <patched.hex> [patch,...]
  patches: track, backlight, disctime, shuffle, play, cdtime, remaining, brightness (default: all)
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
OSD = 0x20000294           # spare: dead settings menu cursor bytes, 0 after boot
                           # +0 u16 end time (CLOCK_75MS), +2 u8 active
OSD_TEXT = 0x200002A0      # u32 spare (dead menu table): text the OSD shows on line 1
OSD_STEPS = 33             # show an OSD text for 33 x 75 ms = 2.5 s
TIME_STAMP = 0x20000298    # u16 spare (dead menu table): CLOCK_75MS at the last time message
TIME_ARMED = 0x20000297    # u8 spare (dead menu byte, 0 after boot): a time message arrived while playing
PREGAP = 0x2000023A        # u8 spare (0 after boot): last time message was in the gap before a track
AUTOPLAY_SETTING = 0x200004DA  # saved setting byte of the dead settings menu (record +0x2C): 2 = on
AUTOPLAY_RELOAD = 0x2000028E   # u8 spare (dead menu byte, 0 after boot): 1 reloading after power-on,
                               # 2 same, "Disc" seen (timing)
AUTOPLAY_LATCH = 0x2000028F    # u8 spare (dead menu byte, 0 after boot): auto-play queued for this disc
AUTOPLAY_SINCE = 0x2000029A    # u16 spare (dead menu table): CLOCK_75MS when "Disc" was first seen
AUTOPLAY_NODISC_STEPS = 14     # "Disc" again 14 x 75 ms = 1 s later: no disc after all
AUTOPLAY_TEXT = ('AUTO', 'OFF')  # line 1 when auto-play is switched on / off
DISPATCH = 0x0800E5C2          # key dispatcher, called from the main loop at 0x08004320
CD_QUEUE = 0x0800D03A      # queue a command for the CD module (command number)
RAND = 0x08029C14          # rand(): LCG, seed at RAND_SEED, returns seed >> 1
RAND_SEED = 0x20000828
TIM1_CNT = 0x40012C24      # TIM1 counter (1.33 MHz): entropy for a new seed
PLAY_MODE = 0x20000189     # 0 normal, 1 repeat one, 2 repeat disc, 3 shuffle (one icon ui+0x28)
NEXT_TRACK = 0x20000182    # u16 track the play handler plays when NEXT_FLAG is set
NEXT_FLAG = 0x20000184
END_CHECK = 0x0800D190     # each pass: 2 s before the stored track length ends, act on the play mode
END_STOP = 0x0800D2A0      # in END_CHECK: stop as at the end of the disc (exits END_CHECK)
SH = 0x200002A4            # spare (dead menu table): +0 track of the stored length, +1 history count,
                           # +2 track seen last, +3 track asked for, +4 u16 time asked, +6 waiting
SH_PLAYED = 0x200002B0     # 256 x u8 spare (dead menu table): track played in this shuffle round
SH_HIST = 0x200003B0       # 128 x u8 spare (dead menu table): tracks in the order they played
SH_HIST_MAX = 128
SH_WAIT_STEPS = 100        # 7.5 s: the end check keeps firing until the asked-for track plays
CD_LEN_KIND = CD_STATE + 0x93  # length message: 0 the disc, 1 a track; +0x95 its track number
LAST_TRACK_GRACE = 3       # LAST_TRACK_FULL_ON: still playing 3 s after the last track's length: stop
IR_PENDING = 0x200004BC    # set when an IR command is waiting: get_key's key comes from the remote
HEADPHONE = 0x200004A0     # 1 headphone plugged in (PE13 low), 2 none; copied in the TIM1 interrupt
REPEAT_KEY, SHUFFLE_KEY = 0x1D, 0x1C
PANEL_VOLUP_KEY = 0x10     # key of the player's Vol+ button (PC5; tested on the device)
PANEL_VOLDN_KEY = 0x11     # key of the player's Vol- button (PC6)
PANEL_VOL_PEND = 0x2000028C  # u8 spare (0 after boot, unused): key to hand out on the next pass
PANEL_VOL_LAST = 0x2000028D  # u8 spare (0 after boot, unused): last panel volume key
PANEL_VOL_T = 0x200002AC     # u16 spare (dead menu table): CLOCK_75MS of that key
PANEL_VOL_HOLD_STEPS = 4     # volume key events < 300 ms apart are one press (hold / release)
BUILD_NAMES = set()          # patches in this build (set by main)
TIME_PREV = 0x2000029C     # 3 x u8 spare (dead menu table): track, sec, min of the previous time message
CD_MSG_TRACK = CD_STATE + 0x99  # time message: track number
CD_FRAMES = CD_STATE + 0x9D  # time message: frames byte, only non-zero in the gap before a track
TIME_FILL_STEPS = 17       # no time message for 17 x 75 ms = 1.275 s: one was lost
TIME_FILL_STEP = 13        # then again every ~1 s (13 x 75 ms) while they stay missing
TICK_HOOKS = []            # cave functions to run after every display update (see install_tick_hooks)
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
TIME_FILL_ON = True        # advance the time by 1 s when a time message of the CD module is lost
PREGAP_MINUS_ON = True     # show the gap before a track as "-0.02" (needs the remaining patch)
AUTOPLAY_ON = True         # Play at an empty slot ("Disc") switches auto-play on insert on/off
TRUE_SHUFFLE_ON = True     # shuffle plays every track once in random order, then stops
TRACK_END_FIX_ON = True    # end-of-track check: only the playing track's own length; also x:00 and < 1 min
LAST_TRACK_FULL_ON = True  # normal mode: play the last track to its end (the module stops), not 2 s early
PANEL_VOL_ON = True        # without headphone the player's own Vol- = time toggle, Vol+ = play mode cycle

EXPORTS = {}               # cave addresses one patch provides for another
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
# disc_reset(): same for standby entry (the CD module is switched off and
# reloads the disc at power-on): play state 1 (stopped), tray status 1 (Load).
TRAY_OPEN = [
    'tray_open:',
    ('ldr_lit', 'r1', 'lit_state'),
    ('movs', 'r0', 2),
    ('strb', 'r0', 'r1', 7),         # tray status = Eject
    ('b', 'disc_clear'),
    'disc_reset:',
    ('ldr_lit', 'r1', 'lit_state'),
    ('movs', 'r0', 1),
    ('strb', 'r0', 'r1', 4),         # play state = stopped
    ('strb', 'r0', 'r1', 7),         # tray status = Load
    'disc_clear:',
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

# play_key(): Play/Pause pressed (dispatcher case 0x2F). While stopped and the
# disc is still loading (tray status 0 Read / 1 Load / 5 Read, disc not
# ready) it toggles a queued Play; otherwise the original handler runs.
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
    ('ldrb', 'r0', 'r1', 0),
    ('movs', 'r2', 1),
    ('subs', 'r0', 'r2', 'r0'),      # queue / cancel
    ('strb', 'r0', 'r1', 0),
    ('pop', reglist('r4', pc=True)),
    'play_now:',
    ('bl', 'SHUFFLE_START'),         # shuffle patch, if built: random first track
    ('bl', PLAY_HANDLER),
    ('pop', reglist('r4', pc=True)),

    # play_dispatch(r0 = key): replaces the main loop's call to the key
    # dispatcher, which drops most keys at "Eject" / "Disc".
    #   Play at an empty slot ("Disc", stopped): switch auto-play on/off
    #   (saved setting), "AUTO" / "OFF" on line 1.
    #   Stop with a Play queued: only cancel the queue (the firmware turns
    #   Stop while stopped into Eject; a second Stop still does that).
    'play_dispatch:',
    ('push', reglist('r4', lr=True)),
    ('mov', 'r4', 'r0'),
    *([('cmp', 'r4', 0x2F),          # Play/Pause
       ('bne', 'pd_stop'),
       ('ldr_lit', 'r3', 'lit_state'),
       ('ldrb', 'r0', 'r3', 4),
       ('cmp', 'r0', 1),
       ('bne', 'pd_go'),
       ('ldrb', 'r0', 'r3', 7),
       ('cmp', 'r0', 3),
       ('beq', 'pd_toggle'),
       ('cmp', 'r0', 6),
       ('bne', 'pd_go'),
       'pd_toggle:',
       ('ldr_lit', 'r1', 'lit_ap_setting'),
       ('ldrb', 'r0', 'r1', 0),
       ('cmp', 'r0', 2),
       ('beq', 'pd_off'),
       ('movs', 'r0', 2),
       ('strb', 'r0', 'r1', 0),
       ('ldr_lit', 'r0', 'lit_txt_on'),
       ('b', 'pd_show'),
       'pd_off:',
       ('movs', 'r0', 0),
       ('strb', 'r0', 'r1', 0),
       ('ldr_lit', 'r0', 'lit_txt_off'),
       'pd_show:',
       ('bl', 'OSD_SHOW'),
       ('bl', SCHEDULE_SAVE),
       ('movs', 'r4', 0xFF),         # consumed
       ('b', 'pd_go')] if AUTOPLAY_ON else []),
    'pd_stop:',
    ('cmp', 'r4', 0x36),             # Stop/Eject
    ('bne', 'pd_go'),
    ('ldr_lit', 'r1', 'lit_pending'),
    ('ldrb', 'r0', 'r1', 0),
    ('cbz', 'r0', 'pd_go'),
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r1', 0),
    ('movs', 'r4', 0xFF),            # consumed
    'pd_go:',
    ('mov', 'r0', 'r4'),
    ('bl', DISPATCH),
    ('pop', reglist('r4', pc=True)),

    # play_poll(): replaces the main loop's call to 0x08007F30. Starts a
    # pending Play once the disc is ready; drops it if the tray opens, there
    # is no disc / the tray is blocked, or the play state changed meanwhile.
    'play_poll:',
    ('push', reglist('r4', lr=True)),
    ('bl', MAIN_TASK),
    # auto-play on insert: when a disc starts loading (Load / Read, stopped,
    # not ready) and auto-play is on, queue a Play once for that disc (latch,
    # cleared at "Eject" / "Disc"). Not for the reload after power-on: that
    # ends when the disc is ready, at "Eject", or at a "Disc" seen 1 s after
    # the first one (no disc after all; load retries in between are ignored).
    *([('ldr_lit', 'r3', 'lit_state'),
       ('ldrb', 'r0', 'r3', 7),          # tray status
       ('ldr_lit', 'r1', 'lit_reload'),
       ('ldrb', 'r2', 'r1', 0),
       ('cbz', 'r2', 'ap_insert'),
       ('cmp', 'r0', 2),
       ('beq', 'ap_reload_end'),
       ('cmp', 'r0', 3),
       ('beq', 'ap_nodisc'),
       ('cmp', 'r0', 6),
       ('beq', 'ap_nodisc'),
       ('bl', 'disc_ready'),
       ('cmp', 'r0', 0),
       ('beq', 'ap_done'),
       ('b', 'ap_reload_end'),
       'ap_nodisc:',
       ('cmp', 'r2', 1),
       ('bne', 'ap_timing'),
       ('movs', 'r2', 2),                # first "Disc": start timing
       ('strb', 'r2', 'r1', 0),
       ('ldr_lit', 'r0', 'lit_clock'),
       ('ldrh', 'r0', 'r0', 0),
       ('ldr_lit', 'r2', 'lit_ap_since'),
       ('strh', 'r0', 'r2', 0),
       ('b', 'ap_done'),
       'ap_timing:',
       ('ldr_lit', 'r0', 'lit_clock'),
       ('ldrh', 'r0', 'r0', 0),
       ('ldr_lit', 'r2', 'lit_ap_since'),
       ('ldrh', 'r2', 'r2', 0),
       ('subs', 'r0', 'r0', 'r2'),
       ('uxth', 'r0', 'r0'),
       ('cmp', 'r0', AUTOPLAY_NODISC_STEPS),
       ('blo', 'ap_done'),
       'ap_reload_end:',
       ('ldr_lit', 'r1', 'lit_reload'),
       ('movs', 'r0', 0),
       ('strb', 'r0', 'r1', 0),
       ('b', 'ap_done'),
       'ap_insert:',
       ('ldr_lit', 'r1', 'lit_latch'),
       ('cmp', 'r0', 2),
       ('beq', 'ap_unlatch'),
       ('cmp', 'r0', 3),
       ('beq', 'ap_unlatch'),
       ('cmp', 'r0', 6),
       ('beq', 'ap_unlatch'),
       ('ldrb', 'r2', 'r1', 0),
       ('cbnz', 'r2', 'ap_done'),        # already queued for this disc
       ('cmp', 'r0', 1),
       ('beq', 'ap_load'),
       ('cmp', 'r0', 5),
       ('bne', 'ap_done'),
       'ap_load:',
       ('ldrb', 'r0', 'r3', 4),
       ('cmp', 'r0', 1),
       ('bne', 'ap_done'),
       ('ldr_lit', 'r0', 'lit_ap_setting'),
       ('ldrb', 'r0', 'r0', 0),
       ('cmp', 'r0', 2),
       ('bne', 'ap_done'),
       ('bl', 'disc_ready'),
       ('cmp', 'r0', 0),
       ('bne', 'ap_done'),
       ('movs', 'r0', 1),
       ('ldr_lit', 'r1', 'lit_latch'),
       ('strb', 'r0', 'r1', 0),
       ('ldr_lit', 'r1', 'lit_pending'),
       ('strb', 'r0', 'r1', 0),
       ('b', 'ap_done'),
       'ap_unlatch:',
       ('movs', 'r2', 0),
       ('strb', 'r2', 'r1', 0),
       'ap_done:'] if AUTOPLAY_ON else []),
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
    ('bl', 'SHUFFLE_START'),
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

    # play_icon(): tick hook. The play icon means "it is going to play":
    # shown (and the stop icon hidden) while a Play is queued, and with
    # auto-play on at an empty slot. Otherwise the firmware's icons stay.
    'play_icon:',
    ('push', reglist('r4', lr=True)),
    ('ldr_lit', 'r0', 'lit_pending'),
    ('ldrb', 'r0', 'r0', 0),
    ('cbnz', 'r0', 'pi_show'),
    *([('ldr_lit', 'r3', 'lit_state'),
       ('ldrb', 'r0', 'r3', 4),
       ('cmp', 'r0', 1),
       ('bne', 'pi_done'),
       ('ldrb', 'r0', 'r3', 7),
       ('cmp', 'r0', 3),
       ('beq', 'pi_ap'),
       ('cmp', 'r0', 6),
       ('bne', 'pi_done'),
       'pi_ap:',
       ('ldr_lit', 'r0', 'lit_ap_setting'),
       ('ldrb', 'r0', 'r0', 0),
       ('cmp', 'r0', 2),
       ('beq', 'pi_show')] if AUTOPLAY_ON else []),
    ('b', 'pi_done'),
    'pi_show:',
    ('ldr_lit', 'r4', 'lit_ui'),
    ('ldr', 'r0', 'r4', 0x10),       # play icon
    ('ldr', 'r1', 'r0', OBJ_FLAGS),
    ('lsls', 'r1', 'r1', 27),        # hidden flag (bit 4) -> sign
    ('bpl', 'pi_stop'),
    ('movs', 'r1', 0),
    ('bl', OBJ_SET_HIDDEN),
    'pi_stop:',
    ('ldr', 'r0', 'r4', 0x18),       # stop icon
    ('ldr', 'r1', 'r0', OBJ_FLAGS),
    ('lsls', 'r1', 'r1', 27),
    ('bmi', 'pi_done'),
    ('movs', 'r1', 1),
    ('bl', OBJ_SET_HIDDEN),
    'pi_done:',
    ('pop', reglist('r4', pc=True)),

    # play_standby(): standby entry (also once at cold start) - forget a
    # pending Play and the disc state: the CD module is switched off and
    # reloads the disc at power-on, so Play must be queued again until it is
    # ready; that reload is not an insert (no auto-play). Then the original
    # first call of the standby routine.
    'play_standby:',
    ('push', reglist('r4', lr=True)),
    ('ldr_lit', 'r1', 'lit_pending'),
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r1', 0),
    *([('ldr_lit', 'r1', 'lit_latch'),
       ('strb', 'r0', 'r1', 0),
       ('ldr_lit', 'r1', 'lit_reload'),
       ('movs', 'r0', 1),
       ('strb', 'r0', 'r1', 0)] if AUTOPLAY_ON else []),
    ('bl', 'DISC_RESET'),            # disctime's disc_reset (filled in by patch_play)
    ('bl', STANDBY_FIRST_CALL),
    ('pop', reglist('r4', pc=True)),
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
    'lit_ui:',
    ('word', UI),
    *(['lit_ap_setting:', ('word', AUTOPLAY_SETTING),
       'lit_reload:', ('word', AUTOPLAY_RELOAD),
       'lit_latch:', ('word', AUTOPLAY_LATCH),
       'lit_ap_since:', ('word', AUTOPLAY_SINCE),
       'lit_clock:', ('word', CLOCK_75MS),
       'lit_txt_on:', ('word', 'txt_on'),
       'lit_txt_off:', ('word', 'txt_off'),
       'txt_on:', ('bytes', AUTOPLAY_TEXT[0].encode() + b'\0'),
       'txt_off:', ('bytes', AUTOPLAY_TEXT[1].encode() + b'\0')] if AUTOPLAY_ON else []),
]


def patch_disctime(img):
    cave, labels = assemble(TRAY_OPEN, cave_addr(img))
    fn = labels['tray_open']
    # case 0x21: movs r0,#2 / ldr r1,=state / strb r0,[r1,#7] / b 0x0800DD3A
    site, _ = assemble([('bl', fn), ('b', 0x0800DD3A), ('nop',)], 0x0800DCDE)
    patch(img, 0x0800DCDE, bytes.fromhex('0220e649c87129e0'), site)
    put(img, fn, cave)
    EXPORTS['disc_reset'] = labels['disc_reset']
    print(f'disctime: tray_open at {fn:#x}, {len(cave)} bytes')


def patch_play(img):
    if AUTOPLAY_ON:
        ensure_osd(img)
    cave, labels = assemble(resolve(PLAY_KEY), cave_addr(img))
    # key 0x2F case in the dispatcher: bl 0x0800E10E -> bl play_key
    site, _ = assemble([('bl', labels['play_key'])], 0x0800E766)
    patch(img, 0x0800E766, bytes.fromhex('fff7d2fc'), site)
    # main loop (powered on): bl 0x08007F30 -> bl play_poll
    site, _ = assemble([('bl', labels['play_poll'])], 0x08004324)
    patch(img, 0x08004324, bytes.fromhex('03f004fe'), site)
    # standby entry 0x0800A7E0: bl 0x08008B04 -> bl play_standby
    site, _ = assemble([('bl', labels['play_standby'])], 0x0800A7E2)
    patch(img, 0x0800A7E2, bytes.fromhex('fef78ff9'), site)
    # main loop: bl key dispatcher -> bl play_dispatch
    old, _ = assemble([('bl', DISPATCH)], 0x08004320)
    site, _ = assemble([('bl', labels['play_dispatch'])], 0x08004320)
    patch(img, 0x08004320, old, site)
    TICK_HOOKS.append(labels['play_icon'])
    put(img, labels['play_key'], cave)
    print(f"play: play_key at {labels['play_key']:#x}, {len(cave)} bytes"
          + (' (with auto-play on insert)' if AUTOPLAY_ON else ''))


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
    *([('ldr_lit', 'r0', 'lit_pregap'),
       ('ldrb', 'r0', 'r0', 0),
       ('cbz', 'r0', 'not_gap'),
       ('adds_i8', 'r5', 1),         # gap: whole seconds left, rounded up
       ('b', 'show'),
       'not_gap:'] if PREGAP_MINUS_ON else []),
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
    *([('ldr_lit', 'r0', 'lit_pregap'),
       ('ldrb', 'r0', 'r0', 0),
       ('cbz', 'r0', 'fmt_done'),
       ('movs', 'r0', 0),
       ('movs', 'r1', 0x2D),         # '-' over the minutes' tens digit: "-0.03"
       ('bl', PUT_CHAR_L2),
       'fmt_done:'] if PREGAP_MINUS_ON else []),
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
    'lit_pregap:',
    ('word', PREGAP),
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
] + ([
    ('ldr_lit', 'r1', 'lit_vol_pend'),
    ('ldrb', 'r0', 'r1', 0),
    ('cbz', 'r0', 'kh_get'),
    ('movs', 'r2', 0),               # second key of a panel Vol+ press
    ('strb', 'r2', 'r1', 0),
    ('mov', 'r4', 'r0'),
    ('b', 'key_ret'),
    'kh_get:',
    ('ldr_lit', 'r1', 'lit_ir_pending'),
    ('ldrb', 'r4', 'r1', 0),         # key will come from the remote?
] if PANEL_VOL_ON else []) + [
    ('bl', GET_KEY),
] + ([
    ('mov', 'r1', 'r4'),
    ('bl', 'panel_vol'),
] if PANEL_VOL_ON else []) + [
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
    ('ldrb', 'r0', 'r4', 0),         # show the new level on line 1
    ('lsls', 'r0', 'r0', 2),
    ('ldr_lit', 'r1', 'lit_level_text'),
    ('adds', 'r1', 'r1', 'r0'),
    ('ldr', 'r0', 'r1', 0),
    ('bl', 'OSD_SHOW'),
    ('pop', reglist('r4', pc=True)),

    # panel_vol(r0 = key, r1 = from remote) -> key. The player's own Vol- / Vol+
    # do nothing without a headphone; then Vol- toggles elapsed / remaining
    # (like DISP) and Vol+ cycles normal -> repeat one -> repeat disc ->
    # shuffle -> normal through the firmware's Repeat / Shuffle keys (from
    # repeat disc: Repeat, then Shuffle on the next pass). Key events closer
    # than 300 ms are one press (holding repeats, release after a hold).
    *(['panel_vol:',
       ('push', reglist('r4', lr=True)),
       ('mov', 'r4', 'r0'),
       ('cmp', 'r0', 0x10),
       ('beq', 'pv_vol'),
       ('cmp', 'r0', 0x11),
       ('bne', 'pv_out'),
       'pv_vol:',
       ('cmp', 'r1', 0),
       ('bne', 'pv_out'),            # remote: unchanged
       ('ldr_lit', 'r1', 'lit_headphone'),
       ('ldrb', 'r1', 'r1', 0),
       ('cmp', 'r1', 1),
       ('beq', 'pv_out'),            # headphone: volume
       ('ldr_lit', 'r1', 'lit_power'),
       ('ldrb', 'r1', 'r1', 0),
       ('cmp', 'r1', 0),
       ('beq', 'pv_out'),            # standby
       ('ldr_lit', 'r3', 'lit_vol_t'),
       ('ldrh', 'r1', 'r3', 0),
       ('ldr_lit', 'r2', 'lit_clock_kh'),
       ('ldrh', 'r2', 'r2', 0),
       ('strh', 'r2', 'r3', 0),
       ('subs', 'r1', 'r2', 'r1'),
       ('uxth', 'r1', 'r1'),         # 75 ms steps since the previous event
       ('ldr_lit', 'r3', 'lit_vol_last'),
       ('ldrb', 'r2', 'r3', 0),
       ('strb', 'r0', 'r3', 0),
       ('cmp', 'r2', 'r0'),
       ('bne', 'pv_new'),
       ('cmp', 'r1', PANEL_VOL_HOLD_STEPS),
       ('bhs', 'pv_new'),
       ('movs', 'r4', 0xFF),         # same press
       ('b', 'pv_out'),
       'pv_new:',
       ('cmp', 'r0', PANEL_VOLDN_KEY),
       ('bne', 'pv_mode'),
       ('movs', 'r4', 'VOLDN_FN'),   # the time toggle key if the remaining patch is built
       ('b', 'pv_out'),
       'pv_mode:',
       ('ldr_lit', 'r1', 'lit_play_mode'),
       ('ldrb', 'r1', 'r1', 0),
       ('movs', 'r4', REPEAT_KEY),   # normal / repeat one: Repeat
       ('cmp', 'r1', 2),
       ('bne', 'pv_m3'),
       ('ldr_lit', 'r2', 'lit_vol_pend'),
       ('movs', 'r3', SHUFFLE_KEY),  # repeat disc: Repeat (-> normal), then Shuffle
       ('strb', 'r3', 'r2', 0),
       ('b', 'pv_out'),
       'pv_m3:',
       ('cmp', 'r1', 3),
       ('bne', 'pv_out'),
       ('movs', 'r4', SHUFFLE_KEY),  # shuffle: Shuffle (-> normal)
       'pv_out:',
       ('mov', 'r0', 'r4'),
       ('pop', reglist('r4', pc=True))] if PANEL_VOL_ON else []),

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
    *(['lit_vol_pend:', ('word', PANEL_VOL_PEND),
       'lit_vol_last:', ('word', PANEL_VOL_LAST),
       'lit_vol_t:', ('word', PANEL_VOL_T),
       'lit_ir_pending:', ('word', IR_PENDING),
       'lit_headphone:', ('word', HEADPHONE),
       'lit_clock_kh:', ('word', CLOCK_75MS),
       'lit_play_mode:', ('word', PLAY_MODE)] if PANEL_VOL_ON else []),
    'lit_level_text:',
    ('word', 'osd_text'),
    'osd_text:',                     # text pointer per level
    *[('word', f'osd_text_{i}') for i in range(len(BRIGHT_OSD_TEXT))],
    *[x for i, t in enumerate(BRIGHT_OSD_TEXT) for x in (f'osd_text_{i}:', ('bytes', t.encode() + b'\0'))],
]


def patch_brightness(img):
    ensure_osd(img)
    voldn = TIME_KEY if 'remaining' in BUILD_NAMES else 0xFF
    prog = [('movs', 'r4', voldn) if ins == ('movs', 'r4', 'VOLDN_FN') else ins for ins in resolve(KEY_HOOK)]
    cave, lab = assemble(prog, cave_addr(img))
    # main loop: bl get_key -> bl key_hook
    code, _ = assemble([('bl', lab['key_hook'])], 0x08004300)
    patch(img, 0x08004300, bytes.fromhex('04f094fa'), code)
    # settings load: brightness clamp(val, 7) -> bright_load
    code, _ = assemble([('bl', lab['bright_load'])], 0x08006EBC)
    patch(img, 0x08006EBC, bytes.fromhex('fff778fe'), code)
    put(img, lab['key_hook'], cave)
    print(f"brightness: key_hook at {lab['key_hook']:#x}, {len(cave)} bytes"
          + (' (panel Vol-/Vol+ without headphone)' if PANEL_VOL_ON else '')
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


# osd_show(r0 = text): show the text on line 1 for OSD_STEPS (2.5 s), measured
# on the 75 ms clock. osd_tick(): tick hook, puts the text into the line 1
# label after every display update while the time runs; afterwards the next
# display update shows the track again. Shared by brightness and auto-play.
OSD_CODE = [
    'osd_show:',
    ('ldr_lit', 'r1', 'lit_osd_text'),
    ('str', 'r0', 'r1', 0),
    ('ldr_lit', 'r1', 'lit_clock'),
    ('ldrh', 'r0', 'r1', 0),
    ('adds_i8', 'r0', OSD_STEPS),
    ('ldr_lit', 'r1', 'lit_osd'),
    ('strh', 'r0', 'r1', 0),         # end time
    ('movs', 'r0', 1),
    ('strb', 'r0', 'r1', 2),         # active
    ('bx_lr',),

    'osd_tick:',
    ('push', reglist('r4', lr=True)),
    ('ldr_lit', 'r3', 'lit_osd'),
    ('ldrb', 'r0', 'r3', 2),
    ('cbz', 'r0', 'osd_done'),       # not active
    ('ldrh', 'r0', 'r3', 0),
    ('ldr_lit', 'r1', 'lit_clock'),
    ('ldrh', 'r1', 'r1', 0),
    ('subs', 'r0', 'r0', 'r1'),
    ('uxth', 'r0', 'r0'),            # time left (75 ms steps), 16-bit wrap
    ('cbz', 'r0', 'osd_end'),
    ('cmp', 'r0', OSD_STEPS),
    ('bhi', 'osd_end'),
    ('ldr_lit', 'r1', 'lit_osd_text'),
    ('ldr', 'r1', 'r1', 0),
    ('ldr_lit', 'r0', 'lit_ui'),
    ('ldr', 'r0', 'r0', 8),          # line 1 label
    ('bl', LABEL_SET_TEXT),
    ('b', 'osd_done'),
    'osd_end:',                      # time is up: the next display update
    ('movs', 'r0', 0),               # shows the track again
    ('strb', 'r0', 'r3', 2),
    'osd_done:',
    ('pop', reglist('r4', pc=True)),
    ('align',),
    'lit_osd:',
    ('word', OSD),
    'lit_osd_text:',
    ('word', OSD_TEXT),
    'lit_clock:',
    ('word', CLOCK_75MS),
    'lit_ui:',
    ('word', UI),
]


def ensure_osd(img):
    """Put the shared OSD code in the cave once; returns osd_show."""
    if 'osd_show' not in EXPORTS:
        cave, lab = assemble(OSD_CODE, cave_addr(img))
        put(img, lab['osd_show'], cave)
        EXPORTS['osd_show'] = lab['osd_show']
        TICK_HOOKS.append(lab['osd_tick'])
        print(f"osd: osd_show at {lab['osd_show']:#x}, {len(cave)} bytes")
    return EXPORTS['osd_show']


def resolve(prog):
    """Fill in placeholders for code another patch provides (see EXPORTS);
    optional ones are left out when that patch is not built."""
    ext = {'DISC_RESET': 'disc_reset', 'OSD_SHOW': 'osd_show', 'SHUFFLE_START': 'sh_start'}
    optional = {'SHUFFLE_START'}
    out = []
    for ins in prog:
        if isinstance(ins, tuple) and len(ins) == 2 and ins[1] in ext:
            if ext[ins[1]] in EXPORTS:
                ins = (ins[0], EXPORTS[ext[ins[1]]])
            elif ins[1] in optional:
                continue
        out.append(ins)
    return out


# time_msg(): replaces "strb.w r0, [r1, #0x104]" (elapsed seconds) in both
# branches of the CD module's time message (0x21) handler. Does that store,
# then notes the time of arrival and whether the message is from the gap
# before a track, which the module counts down: while playing, minutes 0, a
# non-zero frames byte (normal play mostly reports whole seconds, but not
# always), and either a new track or fewer seconds than the previous message
# (the same second again keeps the state). r1 (CD state) must survive.
# time_fill(): tick hook. While playing, if no time message came for 1.275 s
# one was lost (~7 % fail the checksum): advance the elapsed time by 1 s
# (count down in the gap), then every ~1 s while they stay missing. The next
# message overwrites it with the module's own time.
def cd_time():
    return [
        'time_msg:',
        ('push', reglist('r4', 'r5', lr=True)),
        ('ldr_lit', 'r2', 'lit_elapsed'),
        ('strb', 'r0', 'r2', 4),         # +0x104 elapsed sec (the replaced store)
        ('movs', 'r4', 0),               # in the gap?
        ('ldr', 'r3', 'r2', 0),          # +0x100 elapsed min
        ('cbnz', 'r3', 'gap_set'),
        ('ldr_lit', 'r3', 'lit_state'),
        ('ldrb', 'r3', 'r3', 4),
        ('cmp', 'r3', 6),                # playing
        ('bne', 'gap_set'),
        ('ldr_lit', 'r3', 'lit_frames'),
        ('ldrb', 'r3', 'r3', 0),
        ('cbz', 'r3', 'gap_set'),
        ('ldr_lit', 'r5', 'lit_prev'),
        ('ldr_lit', 'r3', 'lit_msg_track'),
        ('ldrb', 'r3', 'r3', 0),
        ('ldrb', 'r2', 'r5', 0),
        ('cmp', 'r3', 'r2'),
        ('bne', 'is_gap'),               # a new track that starts with a countdown
        ('ldrb', 'r2', 'r5', 2),
        ('cbnz', 'r2', 'gap_set'),       # previous message was past the first minute
        ('ldrb', 'r2', 'r5', 1),
        ('cmp', 'r0', 'r2'),
        ('blo', 'is_gap'),               # counting down
        ('bne', 'gap_set'),
        ('ldr_lit', 'r2', 'lit_pregap'),
        ('ldrb', 'r2', 'r2', 0),
        ('cbz', 'r2', 'gap_set'),        # same second again: keep the state
        'is_gap:',
        ('movs', 'r4', 1),
        'gap_set:',
        ('ldr_lit', 'r2', 'lit_pregap'),
        ('ldrb', 'r3', 'r2', 0),
        ('cmp', 'r3', 'r4'),
        ('beq', 'gap_same'),
        ('ldr_lit', 'r3', 'lit_last_min'),  # gap ended / began: the firmware only rewrites the
        ('movs', 'r5', 0xFF),               # time label when min/sec change (the gap's last
        ('str', 'r5', 'r3', 0),             # 0:00 and the track's first 0:00 are equal)
        'gap_same:',
        ('strb', 'r4', 'r2', 0),
        ('ldr_lit', 'r5', 'lit_prev'),   # remember track, sec, min
        ('ldr_lit', 'r3', 'lit_msg_track'),
        ('ldrb', 'r3', 'r3', 0),
        ('strb', 'r3', 'r5', 0),
        ('strb', 'r0', 'r5', 1),
        ('ldr_lit', 'r3', 'lit_elapsed'),
        ('ldr', 'r3', 'r3', 0),
        ('strb', 'r3', 'r5', 2),
        ('ldr_lit', 'r0', 'lit_clock'),
        ('ldrh', 'r3', 'r0', 0),
        ('ldr_lit', 'r0', 'lit_stamp'),
        ('strh', 'r3', 'r0', 0),
        ('ldr_lit', 'r0', 'lit_armed'),
        ('movs', 'r3', 1),
        ('strb', 'r3', 'r0', 0),
        ('pop', reglist('r4', 'r5', pc=True)),

        'time_fill:',
        ('ldr_lit', 'r3', 'lit_state'),
        ('ldrb', 'r0', 'r3', 4),         # play state
        ('ldr_lit', 'r2', 'lit_armed'),
        ('cmp', 'r0', 6),
        ('beq', 'tf_play'),
        ('movs', 'r0', 0),               # not playing: wait for a fresh message
        ('strb', 'r0', 'r2', 0),
        ('bx_lr',),
        'tf_play:',
        ('ldrb', 'r0', 'r2', 0),
        ('cbz', 'r0', 'tf_ret'),         # no message yet since play started
        ('ldr_lit', 'r2', 'lit_stamp'),
        ('ldrh', 'r0', 'r2', 0),
        ('ldr_lit', 'r1', 'lit_clock'),
        ('ldrh', 'r1', 'r1', 0),
        ('subs', 'r1', 'r1', 'r0'),
        ('uxth', 'r1', 'r1'),            # 75 ms steps since the last message
        ('cmp', 'r1', TIME_FILL_STEPS),
        ('blo', 'tf_ret'),
        ('adds_i8', 'r0', TIME_FILL_STEP),
        ('strh', 'r0', 'r2', 0),
        ('ldr_lit', 'r2', 'lit_elapsed'),
        ('ldrb', 'r1', 'r2', 4),         # seconds
        ('ldr_lit', 'r0', 'lit_pregap'),
        ('ldrb', 'r0', 'r0', 0),
        ('cbnz', 'r0', 'tf_down'),
        ('adds_i8', 'r1', 1),
        ('cmp', 'r1', 60),
        ('blo', 'tf_store'),
        ('movs', 'r1', 0),
        ('ldr', 'r0', 'r2', 0),
        ('adds_i8', 'r0', 1),
        ('str', 'r0', 'r2', 0),          # minutes
        'tf_store:',
        ('strb', 'r1', 'r2', 4),
        'tf_ret:',
        ('bx_lr',),
        'tf_down:',
        ('cmp', 'r1', 0),
        ('beq', 'tf_ret'),
        ('subs_i3', 'r1', 'r1', 1),
        ('b', 'tf_store'),
        ('align',),
        'lit_elapsed:',
        ('word', CD_STATE + 0x100),
        'lit_frames:',
        ('word', CD_FRAMES),
        'lit_pregap:',
        ('word', PREGAP),
        'lit_clock:',
        ('word', CLOCK_75MS),
        'lit_stamp:',
        ('word', TIME_STAMP),
        'lit_armed:',
        ('word', TIME_ARMED),
        'lit_state:',
        ('word', CD_STATE),
        'lit_prev:',
        ('word', TIME_PREV),
        'lit_last_min:',
        ('word', LAST_SHOWN_MIN),
        'lit_msg_track:',
        ('word', CD_MSG_TRACK),
    ]


def patch_cdtime(img):
    if not (TIME_FILL_ON or PREGAP_MINUS_ON):
        print('cdtime: off (TIME_FILL_ON and PREGAP_MINUS_ON are False)')
        return
    cave, lab = assemble(cd_time(), cave_addr(img))
    for site in (0x0800DDA6, 0x0800DDDC):      # seek / play branch of the time message
        code, _ = assemble([('bl', lab['time_msg'])], site)
        patch(img, site, bytes.fromhex('81f80401'), code)
    if TIME_FILL_ON:
        TICK_HOOKS.insert(0, lab['time_fill'])  # before the display text hooks
    put(img, lab['time_msg'], cave)
    print(f"cdtime: time_msg at {lab['time_msg']:#x}, {len(cave)} bytes"
          + (' (time fill)' if TIME_FILL_ON else '') + (' (gap detection)' if PREGAP_MINUS_ON else ''))


# Shuffle (play mode 3) picks a random track with rand() % tracks + 1 at the
# end of a track (END_CHECK), on Next and on Previous, so tracks repeat and it
# never ends. TRUE_SHUFFLE_ON replaces those rand() calls: a random track not
# played yet in this round (SH_PLAYED), Previous goes back through the order
# played (SH_HIST), and when all have played it stops like the end of a disc.
# Switching shuffle on starts a new round and reseeds rand() (it is otherwise
# seeded once at cold start with an almost constant value). A tick hook notes
# every track that starts playing. More than 255 tracks: the old behaviour.
# TRACK_END_FIX_ON: END_CHECK uses the stored track length (+0x108), which
# keeps the previous track's length until the module's next length message
# (~every 22 s), so a short previous track could end the next one early. The
# length message says which track it is for (+0x93 = 1, track +0x95); END_CHECK
# now only runs when that is the playing track.
def shuffle_code():
    prog = []
    if TRACK_END_FIX_ON or LAST_TRACK_FULL_ON:
        prog += [
            'len_msg:',                  # replaces strb.w r0, [r1, #0x10c] (track length sec)
            ('mov', 'r2', 'r1'),
            ('adds_i8', 'r2', 0xFF),
            ('adds_i8', 'r2', 0x0D),     # CD state + 0x10C
            ('strb', 'r0', 'r2', 0),
            ('ldr_lit', 'r2', 'lit_len_kind'),
            ('ldrb', 'r0', 'r2', 0),
            ('cmp', 'r0', 1),
            ('bne', 'len_none'),
            ('ldrb', 'r0', 'r2', 2),     # track number
            ('b', 'len_set'),
            'len_none:',
            ('movs', 'r0', 0),           # the disc total, filed as a track length
            'len_set:',
            ('ldr_lit', 'r2', 'lit_sh'),
            ('strb', 'r0', 'r2', 0),
            ('bx_lr',),

            'end_check:',                # replaces bl END_CHECK in the main task
            ('push', reglist('r4', lr=True)),
            *([('bl', 'last_full'),
               ('cmp', 'r0', 0),
               ('bne', 'ec_done')] if LAST_TRACK_FULL_ON else []),
            *([('ldr_lit', 'r2', 'lit_sh'),
               ('ldrb', 'r0', 'r2', 0),
               ('ldr_lit', 'r1', 'lit_cur'),
               ('ldr', 'r1', 'r1', 0),
               ('cmp', 'r0', 'r1'),
               ('bne', 'ec_done')] if TRACK_END_FIX_ON else []),
            ('bl', END_CHECK),
            'ec_done:',
            ('pop', reglist('r4', pc=True)),
        ]
    if LAST_TRACK_FULL_ON:
        prog += [
            # last_full() -> r0 = 1 if it stopped: normal mode no longer stops
            # the last track 2 s early, the module's end-of-disc message does.
            # Safety net if that message does not come: still playing the last
            # track LAST_TRACK_GRACE s after its own length (the time fill keeps
            # counting when the module is silent): stop as the firmware would.
            'last_full:',
            ('push', reglist('r4', lr=True)),
            ('movs', 'r4', 0),
            ('ldr_lit', 'r0', 'lit_mode'),
            ('ldrb', 'r0', 'r0', 0),
            ('cmp', 'r0', 0),
            ('bne', 'lf_out'),
            ('ldr_lit', 'r3', 'lit_state'),
            ('ldrb', 'r0', 'r3', 4),
            ('cmp', 'r0', 6),
            ('bne', 'lf_out'),
            ('ldr_lit', 'r3', 'lit_cur'),
            ('ldr', 'r0', 'r3', 0),      # track
            ('ldr_lit', 'r1', 'lit_tracks'),
            ('ldr', 'r1', 'r1', 0),
            ('cmp', 'r0', 'r1'),
            ('blo', 'lf_out'),           # not the last track
            ('ldr_lit', 'r2', 'lit_sh'),
            ('ldrb', 'r2', 'r2', 0),
            ('cmp', 'r2', 'r0'),
            ('bne', 'lf_out'),           # length not known for this track
            ('ldr', 'r1', 'r3', 0x0C),   # +0x108 length min
            ('movs', 'r2', 60),
            ('muls', 'r1', 'r2'),
            ('ldrb', 'r2', 'r3', 0x10),  # +0x10C length sec
            ('adds', 'r1', 'r1', 'r2'),
            ('cmp', 'r1', 0),
            ('beq', 'lf_out'),
            ('ldr', 'r0', 'r3', 4),      # +0x100 elapsed min
            ('movs', 'r2', 60),
            ('muls', 'r0', 'r2'),
            ('ldrb', 'r2', 'r3', 8),     # +0x104 elapsed sec
            ('adds', 'r0', 'r0', 'r2'),
            ('adds_i8', 'r1', LAST_TRACK_GRACE),
            ('cmp', 'r0', 'r1'),
            ('blo', 'lf_out'),
            ('bl', 'sh_stop'),
            ('movs', 'r4', 1),
            'lf_out:',
            ('mov', 'r0', 'r4'),
            ('pop', reglist('r4', pc=True)),
        ]
    if TRUE_SHUFFLE_ON or LAST_TRACK_FULL_ON:
        prog += [
            'sh_stop:',                  # stop as at the end of the disc (like END_STOP)
            ('ldr_lit', 'r1', 'lit_state'),
            ('movs', 'r0', 1),
            ('strb', 'r0', 'r1', 4),
            ('ldr_lit', 'r1', 'lit_cur'),
            ('str', 'r0', 'r1', 0),      # track 1
            ('movs', 'r0', 0),
            ('str', 'r0', 'r1', 4),      # 0:00
            ('strb', 'r0', 'r1', 8),
            ('movs', 'r0', 3),
            ('b.w', CD_QUEUE),
        ]
    if TRUE_SHUFFLE_ON:
        prog += [
            'sh_n:',                     # r0 = number of tracks if 1..255, else 0
            ('ldr_lit', 'r0', 'lit_tracks'),
            ('ldr', 'r0', 'r0', 0),
            ('cmp', 'r0', 255),
            ('bls', 'shn_ok'),
            ('movs', 'r0', 0),
            'shn_ok:',
            ('bx_lr',),

            'sh_pick:',                  # r0 = random unplayed track, marked played; 0 if none
            ('push', reglist('r4', 'r5', 'r6', 'r7', lr=True)),
            ('bl', 'sh_n'),
            ('mov', 'r5', 'r0'),
            ('ldr_lit', 'r6', 'lit_played'),
            ('movs', 'r4', 0),
            ('movs', 'r7', 1),
            'pk_count:',
            ('cmp', 'r7', 'r5'),
            ('bhi', 'pk_counted'),
            ('adds', 'r2', 'r6', 'r7'),
            ('ldrb', 'r2', 'r2', 0),
            ('cbnz', 'r2', 'pk_c_next'),
            ('adds_i8', 'r4', 1),
            'pk_c_next:',
            ('adds_i8', 'r7', 1),
            ('b', 'pk_count'),
            'pk_counted:',
            ('movs', 'r0', 0),
            ('cmp', 'r4', 0),
            ('beq', 'pk_ret'),
            ('bl', RAND),
            ('udiv', 'r1', 'r0', 'r4'),
            ('muls', 'r1', 'r4'),
            ('subs', 'r0', 'r0', 'r1'),  # k = rand() % unplayed
            ('movs', 'r7', 1),
            'pk_find:',
            ('adds', 'r2', 'r6', 'r7'),
            ('ldrb', 'r2', 'r2', 0),
            ('cbnz', 'r2', 'pk_f_next'),
            ('cmp', 'r0', 0),
            ('beq', 'pk_found'),
            ('subs_i3', 'r0', 'r0', 1),
            'pk_f_next:',
            ('adds_i8', 'r7', 1),
            ('b', 'pk_find'),
            'pk_found:',
            ('adds', 'r2', 'r6', 'r7'),
            ('movs', 'r1', 1),
            ('strb', 'r1', 'r2', 0),
            ('mov', 'r0', 'r7'),
            'pk_ret:',
            ('pop', reglist('r4', 'r5', 'r6', 'r7', pc=True)),

            'sh_reset:',                 # new round: nothing played, no history
            ('ldr_lit', 'r0', 'lit_played'),
            ('movs', 'r1', 0),
            ('movs', 'r2', 64),
            'rs_loop:',
            ('str', 'r1', 'r0', 0),
            ('adds_i8', 'r0', 4),
            ('subs_i3', 'r2', 'r2', 1),
            ('bne', 'rs_loop'),
            ('ldr_lit', 'r0', 'lit_sh'),
            ('strb', 'r1', 'r0', 1),
            ('strb', 'r1', 'r0', 2),
            ('strb', 'r1', 'r0', 6),
            ('bx_lr',),

            'sh_expect:',                # r0 = track asked for (kept); END_CHECK repeats it meanwhile
            ('ldr_lit', 'r3', 'lit_sh'),
            ('strb', 'r0', 'r3', 3),
            ('ldr_lit', 'r1', 'lit_clock'),
            ('ldrh', 'r1', 'r1', 0),
            ('strh', 'r1', 'r3', 4),
            ('movs', 'r1', 1),
            ('strb', 'r1', 'r3', 6),
            ('bx_lr',),

            'sh_seen:',                  # r0 = track that started: played, add to the history
            ('ldr_lit', 'r3', 'lit_sh'),
            ('strb', 'r0', 'r3', 2),
            ('ldrb', 'r1', 'r3', 3),
            ('cmp', 'r1', 'r0'),
            ('bne', 'ss_mark'),
            ('movs', 'r1', 0),
            ('strb', 'r1', 'r3', 6),     # the track asked for is playing
            'ss_mark:',
            ('ldr_lit', 'r2', 'lit_played'),
            ('adds', 'r2', 'r2', 'r0'),
            ('movs', 'r1', 1),
            ('strb', 'r1', 'r2', 0),
            ('ldrb', 'r1', 'r3', 1),
            ('cbz', 'r1', 'ss_push'),
            ('ldr_lit', 'r2', 'lit_hist'),
            ('adds', 'r2', 'r2', 'r1'),
            ('subs_i3', 'r2', 'r2', 1),
            ('ldrb', 'r2', 'r2', 0),
            ('cmp', 'r2', 'r0'),
            ('beq', 'ss_done'),          # already the last one (Previous)
            'ss_push:',
            ('cmp', 'r1', SH_HIST_MAX),
            ('bhs', 'ss_done'),
            ('ldr_lit', 'r2', 'lit_hist'),
            ('adds', 'r2', 'r2', 'r1'),
            ('strb', 'r0', 'r2', 0),
            ('adds_i8', 'r1', 1),
            ('strb', 'r1', 'r3', 1),
            'ss_done:',
            ('bx_lr',),

            'sh_tick:',                  # tick hook: note the track that is playing
            ('push', reglist('r4', lr=True)),
            ('ldr_lit', 'r0', 'lit_mode'),
            ('ldrb', 'r0', 'r0', 0),
            ('cmp', 'r0', 3),
            ('bne', 'st_done'),
            ('ldr_lit', 'r3', 'lit_state'),
            ('ldrb', 'r0', 'r3', 4),
            ('cmp', 'r0', 6),
            ('bne', 'st_done'),
            ('bl', 'sh_n'),
            ('mov', 'r4', 'r0'),
            ('ldr_lit', 'r0', 'lit_cur'),
            ('ldr', 'r0', 'r0', 0),
            ('cmp', 'r0', 0),
            ('beq', 'st_done'),
            ('cmp', 'r0', 'r4'),
            ('bhi', 'st_done'),
            ('ldr_lit', 'r3', 'lit_sh'),
            ('ldrb', 'r1', 'r3', 2),
            ('cmp', 'r0', 'r1'),
            ('beq', 'st_done'),
            ('bl', 'sh_seen'),
            'st_done:',
            ('pop', reglist('r4', pc=True)),

            'sh_end:',                   # replaces rand() in END_CHECK's shuffle branch
            ('push', reglist('r4', lr=True)),
            ('bl', 'sh_n'),
            ('cmp', 'r0', 0),
            ('beq', 'se_fb'),
            ('ldr_lit', 'r3', 'lit_sh'),
            ('ldrb', 'r0', 'r3', 6),
            ('cbz', 'r0', 'se_new'),
            ('ldrh', 'r0', 'r3', 4),
            ('ldr_lit', 'r1', 'lit_clock'),
            ('ldrh', 'r1', 'r1', 0),
            ('subs', 'r1', 'r1', 'r0'),
            ('uxth', 'r1', 'r1'),
            ('cmp', 'r1', SH_WAIT_STEPS),
            ('bhs', 'se_new'),
            ('ldrb', 'r0', 'r3', 3),     # still waiting for the track asked for
            ('b', 'se_ret'),
            'se_new:',
            ('bl', 'sh_pick'),
            ('cbz', 'r0', 'se_done'),
            ('bl', 'sh_expect'),
            'se_ret:',
            ('subs_i3', 'r0', 'r0', 1),  # the firmware plays rand() % tracks + 1
            ('pop', reglist('r4', pc=True)),
            'se_done:',                  # all played: new round next time, stop
            ('bl', 'sh_reset'),
            ('pop', reglist('r4')),
            ('add_sp', 4),
            ('b.w', END_STOP),
            'se_fb:',
            ('bl', RAND),
            ('pop', reglist('r4', pc=True)),

            'sh_next:',                  # replaces rand() for Next in shuffle
            ('push', reglist('r4', lr=True)),
            ('bl', 'sh_n'),
            ('cbz', 'r0', 'sn_fb'),
            ('bl', 'sh_pick'),
            ('cbz', 'r0', 'sn_done'),
            ('bl', 'sh_expect'),
            ('subs_i3', 'r0', 'r0', 1),
            ('pop', reglist('r4', pc=True)),
            'sn_done:',                  # all played: stop, new round next time
            ('bl', 'sh_reset'),
            ('bl', 'sh_stop'),
            ('pop', reglist('r4')),
            ('add_sp', 4),
            ('b.w', 0x0800E822),         # skip the firmware's "play track" part
            'sn_fb:',
            ('bl', RAND),
            ('pop', reglist('r4', pc=True)),

            'sh_prev:',                  # replaces rand() for Previous in shuffle
            ('push', reglist('r4', lr=True)),
            ('bl', 'sh_n'),
            ('cbz', 'r0', 'sp_fb'),
            ('ldr_lit', 'r3', 'lit_sh'),
            ('ldrb', 'r1', 'r3', 1),
            ('cmp', 'r1', 2),
            ('blo', 'sp_restart'),
            ('subs_i3', 'r1', 'r1', 1),
            ('strb', 'r1', 'r3', 1),     # drop the current track from the history
            ('ldr_lit', 'r2', 'lit_hist'),
            ('adds', 'r2', 'r2', 'r1'),
            ('ldrb', 'r0', 'r2', 0),
            ('ldr_lit', 'r2', 'lit_played'),
            ('adds', 'r2', 'r2', 'r0'),
            ('movs', 'r0', 0),
            ('strb', 'r0', 'r2', 0),     # and put it back in the round
            ('subs_i3', 'r1', 'r1', 1),
            ('ldr_lit', 'r2', 'lit_hist'),
            ('adds', 'r2', 'r2', 'r1'),
            ('ldrb', 'r0', 'r2', 0),     # the track played before it
            ('b', 'sp_ret'),
            'sp_restart:',
            ('ldr_lit', 'r0', 'lit_cur'),
            ('ldr', 'r0', 'r0', 0),      # first of the round: restart it
            'sp_ret:',
            ('bl', 'sh_expect'),
            ('subs_i3', 'r0', 'r0', 1),
            ('pop', reglist('r4', pc=True)),
            'sp_fb:',
            ('bl', RAND),
            ('pop', reglist('r4', pc=True)),

            'sh_on:',                    # replaces queue(0x0D) when shuffle is switched on
            ('push', reglist('r4', lr=True)),
            ('mov', 'r4', 'r0'),
            ('ldr_lit', 'r0', 'lit_tim1_cnt'),
            ('ldr', 'r0', 'r0', 0),
            ('ldr_lit', 'r1', 'lit_clock'),
            ('ldrh', 'r1', 'r1', 0),
            ('lsls', 'r1', 'r1', 16),
            ('adds', 'r0', 'r0', 'r1'),
            ('ldr_lit', 'r1', 'lit_seed'),
            ('ldr', 'r2', 'r1', 0),
            ('adds', 'r0', 'r0', 'r2'),
            ('str', 'r0', 'r1', 0),      # new seed
            ('bl', 'sh_reset'),
            ('ldr_lit', 'r3', 'lit_state'),
            ('ldrb', 'r0', 'r3', 4),
            ('cmp', 'r0', 6),
            ('beq', 'on_cur'),
            ('cmp', 'r0', 3),
            ('bne', 'on_done'),
            'on_cur:',                   # playing / paused: this track counts as played
            ('bl', 'sh_n'),
            ('ldr_lit', 'r1', 'lit_cur'),
            ('ldr', 'r1', 'r1', 0),
            ('cmp', 'r1', 'r0'),
            ('bhi', 'on_done'),
            ('cmp', 'r1', 0),
            ('beq', 'on_done'),
            ('mov', 'r0', 'r1'),
            ('bl', 'sh_seen'),
            'on_done:',
            ('mov', 'r0', 'r4'),
            ('bl', CD_QUEUE),
            ('pop', reglist('r4', pc=True)),

            'sh_start:',                 # before the play handler (play patch): from stop in
            ('push', reglist('r4', lr=True)),   # shuffle, start with a random track
            ('ldr_lit', 'r0', 'lit_mode'),
            ('ldrb', 'r0', 'r0', 0),
            ('cmp', 'r0', 3),
            ('bne', 'sst_out'),
            ('ldr_lit', 'r3', 'lit_state'),
            ('ldrb', 'r0', 'r3', 4),
            ('cmp', 'r0', 1),
            ('bne', 'sst_out'),
            ('bl', 'sh_n'),
            ('cbz', 'r0', 'sst_out'),
            ('bl', 'sh_pick'),
            ('cbnz', 'r0', 'sst_have'),
            ('bl', 'sh_reset'),          # last round complete: a new one
            ('bl', 'sh_pick'),
            ('cbz', 'r0', 'sst_out'),
            'sst_have:',
            ('bl', 'sh_expect'),
            ('ldr_lit', 'r1', 'lit_next_track'),
            ('strh', 'r0', 'r1', 0),
            ('ldr_lit', 'r1', 'lit_next_flag'),
            ('movs', 'r0', 1),
            ('strb', 'r0', 'r1', 0),
            'sst_out:',
            ('pop', reglist('r4', pc=True)),
        ]
    prog += [
        ('align',),
        'lit_sh:', ('word', SH),
        'lit_cur:', ('word', CD_STATE + 0xFC),
        'lit_len_kind:', ('word', CD_LEN_KIND),
        'lit_tracks:', ('word', CD_STATE + 0xF4),
        'lit_state:', ('word', CD_STATE),
        'lit_played:', ('word', SH_PLAYED),
        'lit_hist:', ('word', SH_HIST),
        'lit_mode:', ('word', PLAY_MODE),
        'lit_clock:', ('word', CLOCK_75MS),
        'lit_seed:', ('word', RAND_SEED),
        'lit_tim1_cnt:', ('word', TIM1_CNT),
        'lit_next_track:', ('word', NEXT_TRACK),
        'lit_next_flag:', ('word', NEXT_FLAG),
    ]
    return prog


def patch_shuffle(img):
    if not (TRUE_SHUFFLE_ON or TRACK_END_FIX_ON or LAST_TRACK_FULL_ON):
        print('shuffle: off (TRUE_SHUFFLE_ON, TRACK_END_FIX_ON and LAST_TRACK_FULL_ON are False)')
        return
    cave, lab = assemble(shuffle_code(), cave_addr(img))
    def hook(site, old_target, new):
        old, _ = assemble([('bl', old_target)], site)
        code, _ = assemble([('bl', lab[new])], site)
        patch(img, site, old, code)
    if TRACK_END_FIX_ON or LAST_TRACK_FULL_ON:
        code, _ = assemble([('bl', lab['len_msg'])], 0x0800DE34)
        patch(img, 0x0800DE34, bytes.fromhex('81f80c01'), code)
        hook(0x0800E0B2, END_CHECK, 'end_check')
    if LAST_TRACK_FULL_ON:
        # END_CHECK, normal mode (and any mode but 1..3): "bne stop-at-last-track"
        # -> "bne exit": the module's end-of-disc message stops (0x0800D9C4)
        old, _ = assemble([('bne', 0x0800D290)], 0x0800D1F0)
        code, _ = assemble([('bne', 0x0800D2BE)], 0x0800D1F0)
        patch(img, 0x0800D1F0, old, code)
    if TRACK_END_FIX_ON:
        # END_CHECK skipped when the length's minutes OR seconds were 0 (meant
        # as "no length known"): tracks under 1 min or of x:00 never ended
        # early. Skip only when both are 0: "minutes 0 -> skip" becomes
        # "minutes not 0 -> skip the seconds test".
        code, _ = assemble([('bne', 0x0800D1CE)], 0x0800D1C2)
        patch(img, 0x0800D1C2, bytes.fromhex('7cd0'), code)
    if TRUE_SHUFFLE_ON:
        hook(0x0800D1F2, RAND, 'sh_end')
        hook(0x0800E7D6, RAND, 'sh_next')
        hook(0x0800E82C, RAND, 'sh_prev')
        hook(0x0800E7B4, CD_QUEUE, 'sh_on')
        TICK_HOOKS.append(lab['sh_tick'])
        EXPORTS['sh_start'] = lab['sh_start']
    first = min(lab[n] for n in ('len_msg', 'sh_n') if n in lab)
    put(img, first, cave)
    print(f'shuffle: at {first:#x}, {len(cave)} bytes'
          + (' (true shuffle)' if TRUE_SHUFFLE_ON else '') + (' (track end fix)' if TRACK_END_FIX_ON else '')
          + (' (last track in full)' if LAST_TRACK_FULL_ON else ''))


def install_tick_hooks(img):
    """Run the TICK_HOOKS cave functions after every display update: they
    replace the timer check that follows it in the main task (0x0800E0BC,
    bl TIMER_EXPIRED with r0 = its timer), once per main-loop pass."""
    if not TICK_HOOKS:
        return
    prog = ['tick_hooks:', ('push', reglist('r4', lr=True)), ('mov', 'r4', 'r0')]
    prog += [('bl', fn) for fn in TICK_HOOKS]
    prog += [('mov', 'r0', 'r4'), ('bl', TIMER_EXPIRED), ('pop', reglist('r4', pc=True))]
    cave, lab = assemble(prog, cave_addr(img))
    old, _ = assemble([('bl', TIMER_EXPIRED)], 0x0800E0BC)
    code, _ = assemble([('bl', lab['tick_hooks'])], 0x0800E0BC)
    patch(img, 0x0800E0BC, old, code)
    put(img, lab['tick_hooks'], cave)
    print(f"tick hooks: {len(TICK_HOOKS)} at {lab['tick_hooks']:#x}")


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
           'shuffle': patch_shuffle, 'play': patch_play, 'cdtime': patch_cdtime, 'remaining': patch_remaining,
           'brightness': patch_brightness}
# 'play' relies on disctime clearing the disc-ready state when the tray opens;
# the gap display in 'remaining' needs cdtime's gap detection
REQUIRES = {'play': ['disctime'], 'remaining': ['cdtime'] if PREGAP_MINUS_ON else []}


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
    BUILD_NAMES.update(names)
    for name in names:
        PATCHES[name](img)
    install_tick_hooks(img)
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

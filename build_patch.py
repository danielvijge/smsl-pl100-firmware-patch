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
  * The empty slot is tray status 3 or 6 with no disc ready ([+0x11C] bit1,
    the display's own test for "Disc"): a stopped MP3 disc also reports 6,
    and Play there must start the disc, not toggle auto-play.

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
    is shown as "-0.03".."-0.01" (rounded up). Needs cdtime's gap detection
    (added automatically). MINUS_DIGIT_WIDTH_ON: the time font's "-" is 26.6
    px wide, the digits 44 px, so the centred time shifted ~9 px between
    "-0.01" and "00.00"; its glyph descriptor (0x0806E390) now has the
    digits' advance with the dash centred in it. In remaining mode without the "-" ("0.03".."0.01",
    unless PREGAP_MINUS_REMAINING): with REMAINING_ADD_S the track ends at
    the gap's length, so the gap continues the count down to 0:00, where the
    next track's music starts.
  * REMAINING_ADD_S: the module's track length is the time from this track's
    start to the next one's minus 2 s (tested on discs with no gap and with
    0.3, 5 and 35.7 s gaps). Remaining time adds it back, so it counts down to
    the start of the next track's music: gapless tracks end at 0:00, a track
    before a g-second gap ends at g, then the gap counts down from -g (the
    track number changes when the gap starts). Only on audio CDs ([+0x118]
    bit0): MP3 / WMA files have exact lengths. Not for the last track: its
    length (to the end of the disc) is exact, and with the 2 s added it
    stopped at 0:02. Display only: the stored length (end-of-track check,
    length request) stays as reported.

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
  * TRACK_END_EXACT_ON: the firmware acted 2 s before the stored length in
    repeat one, shuffle and repeat disc (last track); with the module's
    lengths (audio CD 2 s short, MP3 exact) that cut 2-4 s off the track.
    Repeat one and shuffle now put the module in "stop at each track end"
    mode (0x24; every play command is preceded by the play mode's 0x24 or
    0x25), and its "track ended" or "end of disc" report starts the mode's
    next track (a short pause; continuous play in normal and repeat disc
    stays gapless). The module applies the mode only with a play command:
    after switching to repeat one / shuffle while playing, the moment it
    moves on to the next track by itself counts as the track's end. The
    time-based check only acts TRACK_END_LATE_S after the stored length in
    those modes, as a fallback.
    The module can report the end twice ("end of disc", then "track
    ended"): the late one arrived after repeat disc had started track 1 and
    played track 2. A track-end report now only counts once the module has
    sent a time message since the last play command, and not while a track
    change is pending (NEXT_FLAG).
  * LAST_TRACK_END_ON: the module's "track ended" status on the last track
    played it again (+0x115 is not below the track count); MP3 discs end
    that way, audio CDs send "end of disc". Now the last track continues in
    the end-of-disc handler (0x0800D9C4), which acts on the play mode.
  * LAST_TRACK_FULL_ON: in normal mode the firmware stopped the last track 2 s
    before its length (the remaining time never got below 0:03, and the end
    of the disc was cut). Now it plays to the end and the module's own
    end-of-disc message stops it (0x0800D9C4); as a safety net, still playing
    3 s past the last track's length (time fill keeps counting) stops it.

Patch cdtime - time messages of the CD module.
  * About 7 % of the module's messages fail the checksum and are dropped, so
    the time sometimes jumps by 2 s. TIME_FILL_ON: when playing and the
    shown second has not changed for 1.125 s, advance the elapsed time by 1 s
    (count down in the gap); the next message sets the module's own time
    again. The 1.125 s count from the first message with that second (a
    repeat of the same second does not restart it): that message arrives at
    or after the second began, so the next second has always begun by then
    and the filled time is never ahead of the disc. Counted from the last
    message instead, a late or repeated message delayed the fill until just
    before the next real one, which then showed it only briefly.
  * TIME_FILL_PHASE_ON: the fill follows the estimated start of each second
    (phase P, in 7.5 ms TIM1 ticks) instead. A message can only arrive after
    its second began, so each one gives P = min(arrival, P + 1 s) when it is
    the next second (P = min(arrival, P) for the same second again); P then
    settles on the earliest arrivals and late ones no longer shift it. Any
    other change (a jump, another track, into or out of the gap, the first
    message since playing) restarts P at the arrival. The fill comes at
    P + 1 s + 37.5 ms, so a filled second appears about when it really
    starts and the real message after it changes nothing.
  * TIME_MSG_CHECK_ON: the module once sent a time message (class 4, type
    0x21) for track 1 at 1:11 with frames 91 in the middle of track 4; frames
    only go to 74. The firmware stored it like any other, so for one message
    the track and time were wrong (and shuffle, the length request and the
    time fill saw a track change). Time messages with frames > 74 or seconds
    > 59 are now dropped before anything is stored, the way the firmware
    already skips them while its timer 0x20000566 runs.
  * MP3 / WMA discs (experiment, MP3_ALL_FOLDERS_ON + MP3_DISC_NUMBERS_ON):
    the module plays files by their number on the whole disc but reports
    the folder's file count and the number within the folder, so the
    firmware stayed in folder 1 (Next from file 2 of folder 2 played file 3
    of folder 1; the last file repeated). The count is no longer lowered,
    and the reported numbers get a folder offset learned from the track the
    firmware asked for (see mp3_msg).
  * Notes for each time message whether it is from the gap before a track,
    for PREGAP_MINUS_ON: the module counts the gap down, and those messages
    have a non-zero frames byte (normal play does too, occasionally, so a
    count down or a new track is required as well).
  * LENGTH_REQUEST_ON: the module only sends a track length when asked. The
    firmware asks with command 0x22 ([04 20 01 01 80], current track) every
    2000 main-loop passes (~22 s, timer 0x20000562, 0x0800E0D0), and on the
    Repeat key, so after a track change the remaining time and the end check
    used the previous track's length for up to 22 s. The length message says
    which track it is for (noted by the shuffle patch, see TRACK_END_FIX_ON).
    Each time message (~1 s) now compares that with the track it reports,
    and while playing and they differ, or the stored length is 0:00 (eject
    and standby clear it, but not the track noted with it, so track 1 of a
    new disc could match track 1 of the old one), it asks: on the first message, then
    every other one until the answer arrives (in the gap before a track, or
    after a checksum failure, the answer may not match yet).

Patch 6 - FN cycles the backlight brightness.
  * FN (BRIGHT_IR) has no function on the PL100. It is mapped to key 0x14,
    and a hook on the main loop's get_key then steps the brightness setting
    (0x200004A5) through levels
    5,4,3,2,1,0 = 10/20/35/55/65/100 % (the backlight is active-low, so the
    menu's levels run backwards) and saves it like the settings menu would.
  * The settings load clamps brightness to 1..6, which would turn level 0
    into 1; brightness gets its own check instead (0..5 valid, else 3).
  * Line 1 shows the level as "10%".."100%" for about 2.5 s, like the
    firmware shows the volume. The first press only shows the current level;
    presses while it is shown step to the next one (osd_showing). The text
    is put on line 1 by a tick hook (see
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

Patch 7 - gaps between tracks after fast forward / rewind.
  * [02 01 09 01 01] (command 0x24) puts the CD module in a mode where it
    stops at the end of each track and reports it; the firmware then starts
    the next track itself (0x0800DA84): a seek, so an audible gap.
    [02 01 09 01 02] (0x25) is continuous play. Fast forward / rewind
    (0x0800E87E / 0x0800E8A0) and Shuffle on send 0x24; the Play key
    (0x0800E10E) sends 0x25 before every play.
  * The release of fast forward / rewind (0x0800D134) only sends "play from
    here" (command 8), so the module stays in stop-at-end mode and every
    later track change has a gap, until Play is pressed again.
  * Send 0x25 before that play command, as the Play key does.

Patch number - track number entry on the remote.
  * The digit keys build a number (0x20000182) shown as "Tr12" on line 2;
    2.25 s after the last digit (timer 0x20000186, in the TIM1 interrupt) the
    firmware presses Play, which plays that track. A helper (0x0800E518)
    starts it at once when no further digit seems possible, with fixed
    limits per disc size: on discs with 30-99 tracks every number from 4 on,
    so 40-99 could never be entered (likewise 160-199 on 100-199 tracks). A
    number above the track count played the last track.
  * Now another digit can follow while number x 10 <= track count and fewer
    digits were typed than the track count has; line 2 then shows a "-"
    ("Tr1-"), and the number plays after the 2.25 s. Otherwise it plays at
    once. Digits show as typed, so a leading 0 is a quick way to a track
    below 10 ("0" "2" on a 50-track disc plays track 2 at once; "Tr05-" on
    a disc with 100 or more). A number above the track count, or only
    zeros, cancels the entry: the time shows again and play goes on.

Patch saver - screensaver while stopped.
  * After SAVER_IDLE_S without a key (remote, panel or knob), while stopped
    with a disc (TOC read) or at the empty slot ("Disc"), the backlight dims to SAVER_DIM_LEVEL (not saved)
    or goes off (DARK). The CD modes (SAVER_CD_ON) also hide everything
    except a 64 px CD (icons.py) that moves to a random position every
    SAVER_MOVE_S; for CD/c each time in a random colour from
    SAVER_CD_COLOURS. The CD is an ALPHA_4BIT image (2 KB; the firmware's
    LVGL decodes it, 0x0801D95A), drawn in the image recolor colour of the
    object's own style: SAVER_CD_WHITE for CD/w. The CD borrows the hourglass object
    (ui+0x24, always hidden when not playing); on waking it gets its own
    image, place and size back (the firmware's unused shuffle icon when the
    remaining patch or its icon is not built). Never while playing,
    paused, seeking or loading.
  * Any key restores the screen and still does its normal function; so does
    leaving those states (disc inserted or ejected, playing). The play state
    byte also gets the CD module's own status codes, so "stopped" is any
    state other than paused (3), playing (6) or seeking (7/8). key_hook (brightness patch) notes
    the key, a tick hook after the display update does the rest, so the
    display update's own hide/show logic is overridden every pass.
  * Except the power key: it switches off before that pass's display update
    and standby follows on the next pass, so the screensaver stays as it is
    (no flash of the normal screen) and wakes at the next power-on.
  * MENU (SAVER_IR, no function so far) cycles the mode, saved in a settings
    byte of the dead settings menu (0x200004DB, record +0x2D) and shown on
    line 1 like the brightness: NONE (no screensaver), DIM (dim to
    SAVER_DIM_LEVEL only), DARK (backlight off), CD/w (dim + moving white
    CD), CD/c (the same, a new colour on every move); the CD modes only with
    SAVER_CD_ON (a saved CD mode then counts as NONE). After flashing it is
    NONE. Like FN, the first press only shows the current mode, presses
    while it is shown step on. While the screensaver runs, MENU only wakes it. This part lives in
    key_hook (brightness patch, added automatically) and is only built with
    the saver patch.
  * The firmware's own idle dimmer (setting 0x200004D5, timer 0x2000054C)
    stays unused: it is only reachable from the dead settings menu and sets
    the backlight PWM to 1, which on the PL100 (active-low) is full brightness.

Boot screen version (--version) - "patch VERSION" below "Ver 1.1".
  * The boot screen (0x08004AFA) is drawn straight to the LCD, not through
    LVGL. "Ver 1.1" moves up a little and the patch line is drawn below it in
    the same 12x16 font, centred, 12 px per char (max 18 chars).
  * Without --version the boot screen stays original.

Usage: build_patch.py [--version VERSION] <original.hex> <patched.hex> [patch,...]
  patches: track, backlight, disctime, shuffle, play, cdtime, remaining, brightness, gapless,
           number, saver (default: all)
"""
import argparse
import struct

from icons import cd, hourglass, lv_img_alpha4, lv_img_true_color_alpha
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
SAVER_KEY = 0x5D           # key caught by key_hook for the screensaver mode (no IR command gives it natively)
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
SAVER_SETTING = 0x200004DB  # saved setting byte of the dead settings menu (record +0x2D, loaded
                           # unchecked): 2 DIM, 3 DARK, 4 white CD, 5 colour-changing CD (only
                           # with SAVER_CD_ON), anything else (1, 0, erased) NONE
SAVER_TEXT = ('NONE', 'DIM', 'DARK')  # line 1 per mode; the font has no space or comma
SAVER_TEXT_CD = ('CD/w', 'CD/c')        # after those with SAVER_CD_ON
SAVER_DARK_LEVEL = 6       # backlight off
SAVER = 0x20000430         # 12 bytes spare (dead menu table): +0 u16 last activity (CLOCK_75MS),
                           # +2 u16 last move, +4 active, +5 key seen (key_hook), +6 mode running
                           # (1 DIM, 2 DARK, 3 CD/w, 4 CD/c), +7 CD colour index,
                           # +8 x, +9 y of the icons, +10 objects that were
                           # visible (bits, SAVER_HIDE order), +11 0xA5 once initialised
LEN_REQ_SKIP = 0x200002AB  # u8 spare (dead menu table): time messages to skip before asking again
PANEL_VOL_T = 0x200002AC     # u16 spare (dead menu table): CLOCK_75MS of that key
PANEL_VOL_HOLD_STEPS = 4     # volume key events < 300 ms apart are one press (hold / release)
BUILD_NAMES = set()          # patches in this build (set by main)
TIME_PREV = 0x2000029C     # 3 x u8 spare (dead menu table): track, sec, min of the previous time message
CD_MSG_TRACK = CD_STATE + 0x99  # time message: track number
CD_FRAMES = CD_STATE + 0x9D  # time message: frames byte, only non-zero in the gap before a track
TIME_FILL_STEPS = 15       # shown second unchanged for 15 x 75 ms = 1.125 s: its successor was lost
TIME_FILL_STEP = 14        # a fill counts as that second's start + 1.05 s (14 x 75 ms), so further
                           # fills follow every 1.05 s; both include a step for the 75 ms rounding
TIME_SUB_TICKS = 0x2000018A  # u16: TIM1 ticks (7.5 ms) left until CLOCK_75MS counts (10..1)
TIME_PHASE_SEC = 134       # TIME_FILL_PHASE_ON: 1 s in 7.5 ms ticks (133.3, rounded up: the
                           # estimate drifts late, never early, and early messages pull it back)
TIME_PHASE_MARGIN = 5      # fill 37.5 ms after the estimated start of the next second
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
SAVER_IR = 0x04            # screensaver mode cycle: MENU
BRIGHT_IR = 0x08           # brightness cycle: FN
IR_DIAG_ON = False         # show the last IR command as "IRxx" on line 1 (diagnostic)
REMAINING_ICON_ON = True   # hourglass icon next to the play icon in remaining-time mode
TIME_FILL_ON = True        # advance the time by 1 s when a time message of the CD module is lost
TIME_FILL_PHASE_ON = True  # time fill on the tracked start of each second, not 1.125 s after a message
PREGAP_MINUS_ON = True     # show the gap before a track as "-0.02" (needs the remaining patch)
PREGAP_MINUS_REMAINING = False  # also the "-" in remaining mode (else "0.02": counts on to 0:00)
MINUS_DIGIT_WIDTH_ON = True  # the time font's "-" as wide as a digit, so "-0.01" lines up with "00.00"
REMAINING_ADD_S = 2        # added to the module's track length for remaining time (0..255; 0 = as reported)
AUTOPLAY_ON = True         # Play at an empty slot ("Disc") switches auto-play on insert on/off
TRUE_SHUFFLE_ON = True     # shuffle plays every track once in random order, then stops
TRACK_END_FIX_ON = True    # end-of-track check: only the playing track's own length; also x:00 and < 1 min
LAST_TRACK_FULL_ON = True  # normal mode: play the last track to its end (the module stops), not 2 s early
LAST_TRACK_END_ON = True   # "track ended" on the last track = end of the disc (MP3: it was played again)
TRACK_END_EXACT_ON = True  # repeat one / shuffle / repeat disc: act at the real end of a track, not 2 s early
TRACK_END_LATE_S = 4       # TRACK_END_EXACT_ON: fallback if the module does not report it: length + 4 s
LENGTH_REQUEST_ON = True   # ask the CD module for the track length right after a track change
TIME_MSG_CHECK_ON = True   # drop time messages with impossible values (frames > 74, seconds > 59)
MP3_ALL_FOLDERS_ON = True  # EXPERIMENT: MP3/WMA discs keep the whole disc's file count (all folders)
MP3_DISC_NUMBERS_ON = True  # EXPERIMENT: MP3/WMA track numbers from the module (per folder) -> whole disc
SAVER_CD_ON = True         # saver patch: also the moving CD modes CD/w and CD/c (~2.6 KB more)
SAVER_IDLE_S = 180         # idle time before the screensaver starts
SAVER_DIM_LEVEL = 5        # backlight level for DIM and CD (5 = 10 %; the brightness levels run backwards)
SAVER_CD_WHITE = 0xE8E8E8  # CD/w colour (the same white as the firmware's icons)
SAVER_CD_COLOURS = (0xFF4040, 0xFF9020, 0xFFE030, 0x40E040,   # CD/c: a random one of these on every move,
                    0x30E0E0, 0x4080FF, 0xA060FF, 0xFF50C0)   # never the same twice; () keeps it white
SAVER_MOVE_S = 10          # the icons move to a new position this often
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


# slot_empty() -> r0: 1 at an empty slot ("Disc" on screen): tray status 3
# or 6 and no disc ready ([+0x11C] bit1, the display's own test). A stopped
# MP3 disc also reports 6, with the disc ready. Clobbers r0, r1.
SLOT_EMPTY = [
    'slot_empty:',
    ('ldr_lit', 'r1', 'lit_state'),
    ('ldrb', 'r0', 'r1', 7),
    ('cmp', 'r0', 3),
    ('beq', 'se_ready'),
    ('cmp', 'r0', 6),
    ('bne', 'se_no'),
    'se_ready:',
    ('ldr_lit', 'r1', 'lit_state_f4'),
    ('ldr', 'r0', 'r1', 0x28),       # +0x11C
    ('lsls', 'r0', 'r0', 30),        # bit1 -> sign
    ('bmi', 'se_no'),
    ('movs', 'r0', 1),
    ('bx_lr',),
    'se_no:',
    ('movs', 'r0', 0),
    ('bx_lr',),
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
       ('bl', 'slot_empty'),
       ('cmp', 'r0', 0),
       ('beq', 'pd_go'),
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
    # is no disc ("Disc", status 3 or 6) / the tray is blocked, or the play
    # state changed meanwhile.
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
       ('cmp', 'r0', 2),
       ('beq', 'ap_unlatch_l'),
       ('bl', 'slot_empty'),
       ('cbnz', 'r0', 'ap_unlatch_l'),
       ('ldrb', 'r0', 'r3', 7),
       ('ldr_lit', 'r1', 'lit_latch'),
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
       'ap_unlatch_l:',
       ('ldr_lit', 'r1', 'lit_latch'),
       ('movs', 'r2', 0),
       ('strb', 'r2', 'r1', 0),
       'ap_done:'] if AUTOPLAY_ON else []),
    ('ldr_lit', 'r4', 'lit_pending'),
    ('ldrb', 'r0', 'r4', 0),
    ('cbz', 'r0', 'poll_done'),
    ('ldr_lit', 'r3', 'lit_state'),
    ('ldrb', 'r0', 'r3', 7),         # tray status 2 Eject / 4 Block / 3, 6 Disc
    ('cmp', 'r0', 2),                # (6: load failed, no disc, e.g. Stop at an
    ('beq', 'poll_cancel'),          # empty slot retries the load; but also a
    ('cmp', 'r0', 4),                # stopped MP3 disc, see slot_empty)
    ('beq', 'poll_cancel'),
    ('bl', 'slot_empty'),
    ('cbnz', 'r0', 'poll_cancel'),
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
       ('bl', 'slot_empty'),
       ('cmp', 'r0', 0),
       ('beq', 'pi_done'),
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
] + SLOT_EMPTY + DISC_READY + [
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
    *([('ldr', 'r2', 'r3', 0x24),    # +0x118 disc type: bit0 audio CD
       ('lsls', 'r2', 'r2', 31),
       ('beq', 'add_done'),          # MP3 / WMA: the lengths are exact
       ('ldr', 'r2', 'r3', 0),       # +0xF4 total tracks
       ('ldr', 'r0', 'r3', 8),       # +0xFC current track
       ('cmp', 'r0', 'r2'),
       ('beq', 'add_done'),          # the last track's length is exact
       ('adds_i8', 'r1', REMAINING_ADD_S),   # the module's 2 s
       'add_done:',
       ('movs', 'r0', 60)] if REMAINING_ADD_S else []),
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
       *([] if PREGAP_MINUS_REMAINING else
         [('ldr_lit', 'r0', 'lit_mode'),
          ('ldrb', 'r0', 'r0', 0),
          ('cbnz', 'r0', 'fmt_done')]),   # remaining mode: no '-'
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
def key_hook_code(saver):
    texts = SAVER_TEXT + (SAVER_TEXT_CD if SAVER_CD_ON else ())   # screensaver modes
    return [
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
        ('beq', 'kh_no_key'),
        ('ldr_lit', 'r1', 'lit_saver'),      # a key: tell the screensaver
        ('movs', 'r0', 1),
        ('strb', 'r0', 'r1', 5),
        ('cmp', 'r4', SAVER_KEY),
        ('bne', 'kh_no_key'),
        ('movs', 'r4', 0xFF),                # MENU: consumed
        ('ldrb', 'r0', 'r1', 4),
        ('cmp', 'r0', 1),
        ('beq', 'kh_no_key'),                # the screensaver runs: only wake it
        ('ldr_lit', 'r1', 'lit_power'),
        ('ldrb', 'r0', 'r1', 0),
        ('cbz', 'r0', 'kh_no_key'),          # standby
        ('bl', 'saver_cycle'),
        'kh_no_key:',
    ] if saver else []) + ([
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
        # settings menu does. Only shows the level unless it is already shown.
        'bright_cycle:',
        ('push', reglist('r4', lr=True)),
        ('ldr_lit', 'r4', 'lit_bright'),
        ('ldrb', 'r0', 'r4', 0),
        ('cmp', 'r0', 5),
        ('bhi', 'bright_step'),          # (not a level with a text: step to 5)
        ('bl', 'bright_text'),
        ('bl', 'OSD_SHOWING'),
        ('cbz', 'r0', 'bright_show'),    # first press: the current level
        'bright_step:',
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
        'bright_show:',                  # show the level on line 1
        ('bl', 'bright_text'),
        ('bl', 'OSD_SHOW'),
        ('pop', reglist('r4', pc=True)),
        'bright_text:',                  # r0 = text of level [r4]
        ('ldrb', 'r0', 'r4', 0),
        ('lsls', 'r0', 'r0', 2),
        ('ldr_lit', 'r1', 'lit_level_text'),
        ('adds', 'r1', 'r1', 'r0'),
        ('ldr', 'r0', 'r1', 0),
        ('bx_lr',),

        # saver_cycle(): MENU - next screensaver mode, saved, shown on line 1;
        # only shows the mode unless it is already shown
        *(['saver_cycle:',
           ('push', reglist('r4', 'r5', lr=True)),
           ('ldr_lit', 'r4', 'lit_saver_setting'),
           ('ldrb', 'r5', 'r4', 0),
           ('subs_i3', 'r5', 'r5', 1),       # mode: index in texts (NONE, DIM, DARK, CD/w, CD/c)
           ('cmp', 'r5', len(texts) - 1),
           ('bls', 'sc_mode'),
           ('movs', 'r5', 0),                # 0, erased, junk (CD without SAVER_CD_ON): NONE
           'sc_mode:',
           ('bl', 'sc_text'),
           ('bl', 'OSD_SHOWING'),
           ('cbz', 'r0', 'sc_show'),         # first press: the current mode
           ('adds_i8', 'r5', 1),
           ('cmp', 'r5', len(texts)),
           ('blo', 'sc_store'),              # next mode
           ('movs', 'r5', 0),                # after the last: NONE
           'sc_store:',
           ('adds_i3', 'r1', 'r5', 1),
           ('strb', 'r1', 'r4', 0),
           ('bl', SCHEDULE_SAVE),
           'sc_show:',
           ('bl', 'sc_text'),
           ('bl', 'OSD_SHOW'),
           ('pop', reglist('r4', 'r5', pc=True)),
           'sc_text:',                       # r0 = text of mode r5
           ('lsls', 'r0', 'r5', 2),
           ('ldr_lit', 'r1', 'lit_saver_text'),
           ('adds', 'r1', 'r1', 'r0'),
           ('ldr', 'r0', 'r1', 0),
           ('bx_lr',)] if saver else []),

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
        *(['lit_saver:', ('word', SAVER),
           'lit_saver_setting:', ('word', SAVER_SETTING),
           'lit_saver_text:', ('word', 'saver_text')] if saver else []),
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
        *([('align',), 'saver_text:', *[('word', f'saver_text_{i}') for i in range(len(texts))],
           *[x for i, t in enumerate(texts) for x in (f'saver_text_{i}:', ('bytes', t.encode() + b'\0'))]]
          if saver else []),
    ]


def patch_brightness(img):
    ensure_osd(img)
    voldn = TIME_KEY if 'remaining' in BUILD_NAMES else 0xFF
    prog = resolve(key_hook_code('saver' in BUILD_NAMES))
    prog = [('movs', 'r4', voldn) if ins == ('movs', 'r4', 'VOLDN_FN') else ins for ins in prog]
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


TIME_FONT_GLYPHS = 0x0806E330  # line-2 time font (88 px, lv_font_fmt_txt): glyph descriptors,
                               # 8 bytes (bitmap index:20, adv_w:12 in 1/16 px; box w, h; ofs x, y)
TIME_FONT_MINUS = TIME_FONT_GLYPHS + 8 * 12   # glyph 12 = "-" (cmap: '-'..'~' from glyph 12)


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
    if PREGAP_MINUS_ON and MINUS_DIGIT_WIDTH_ON:
        # time font: "-" advance 26.6 -> 44 px (the digits' width), its 24 px
        # dash centred in that cell (x offset 1 -> 10)
        o = TIME_FONT_MINUS - BASE
        old = bytes(img[o:o + 8])
        word, box_w, box_h, ofs_x, ofs_y = struct.unpack('<IBBbb', old)
        assert word >> 20 == 425 and (box_w, ofs_x) == (24, 1), f'"-" glyph: unexpected {old.hex()}'
        digit_adv = struct.unpack_from('<I', img, TIME_FONT_GLYPHS + 8 * 15 - BASE)[0] >> 20   # "0"
        new = struct.pack('<IBBbb', word & 0xFFFFF | digit_adv << 20, box_w, box_h,
                          (digit_adv // 16 - box_w) // 2, ofs_y)
        patch(img, TIME_FONT_MINUS, old, new)
    if REMAINING_ICON_ON:
        # main: bl setup_ui -> bl ui_setup (set up the hourglass icon object)
        code, _ = assemble([('bl', lab['ui_setup'])], 0x080042C6)
        patch(img, 0x080042C6, bytes.fromhex('24f087fe'), code)
    put(img, lab['fmt_time'], cave)
    if REMAINING_ICON_ON:
        EXPORTS['hourglass'] = lab['icon_dsc']   # the saver borrows the icon object
    print(f"remaining: fmt_time at {lab['fmt_time']:#x}, {len(cave)} bytes"
          + (' (with hourglass icon)' if REMAINING_ICON_ON else ' (no icon)'))


# osd_show(r0 = text): show the text on line 1 for OSD_STEPS (2.5 s), measured
# on the 75 ms clock. osd_tick(): tick hook, puts the text into the line 1
# label after every display update while the time runs; afterwards the next
# display update shows the track again. Shared by brightness and auto-play.
# osd_showing(r0 = text) -> r0 = 1 if line 1 shows that text right now: a
# setting key then steps on, else it first only shows the current value.
OSD_CODE = [
    'osd_showing:',
    ('ldr_lit', 'r3', 'lit_osd'),
    ('ldrb', 'r1', 'r3', 2),
    ('cbz', 'r1', 'os_no'),          # not active
    ('ldr_lit', 'r1', 'lit_osd_text'),
    ('ldr', 'r1', 'r1', 0),
    ('cmp', 'r0', 'r1'),
    ('bne', 'os_no'),                # another text
    ('ldrh', 'r0', 'r3', 0),
    ('ldr_lit', 'r1', 'lit_clock'),
    ('ldrh', 'r1', 'r1', 0),
    ('subs', 'r0', 'r0', 'r1'),
    ('uxth', 'r0', 'r0'),            # time left, as osd_tick
    ('cbz', 'r0', 'os_no'),
    ('cmp', 'r0', OSD_STEPS),
    ('bhi', 'os_no'),
    ('movs', 'r0', 1),
    ('bx_lr',),
    'os_no:',
    ('movs', 'r0', 0),
    ('bx_lr',),

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
        put(img, lab['osd_showing'], cave)
        EXPORTS['osd_show'] = lab['osd_show']
        EXPORTS['osd_showing'] = lab['osd_showing']
        TICK_HOOKS.append(lab['osd_tick'])
        print(f"osd: osd_show at {lab['osd_show']:#x}, {len(cave)} bytes")
    return EXPORTS['osd_show']


def resolve(prog):
    """Fill in placeholders for code another patch provides (see EXPORTS);
    optional ones are left out when that patch is not built."""
    ext = {'DISC_RESET': 'disc_reset', 'OSD_SHOW': 'osd_show', 'OSD_SHOWING': 'osd_showing',
           'SHUFFLE_START': 'sh_start'}
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
# then notes when the shown time changed (a different second or track, or
# the first message since playing started) and whether the message is from the gap
# before a track, which the module counts down: while playing, minutes 0, a
# non-zero frames byte (normal play mostly reports whole seconds, but not
# always), and either a new track or fewer seconds than the previous message
# (the same second again keeps the state). r1 (CD state) must survive.
# time_fill(): tick hook. While playing, if the shown second has not changed
# for 1.125 s a message was lost (~7 % fail the checksum): advance the
# elapsed time by 1 s (count down in the gap), then every 1.05 s while they
# stay missing. The next message overwrites it with the module's own time;
# one with the second the fill already shows does not restart the count.
PH_RESTART = 100           # TIME_FILL_PHASE_ON: not a step of one second


def cd_time():
    ph = TIME_FILL_ON and TIME_FILL_PHASE_ON
    return [
        'time_msg:',
        ('push', reglist('r4', 'r5', 'r6', *(['r7'] if ph else []), lr=True)),
        ('ldr_lit', 'r2', 'lit_elapsed'),
        ('ldrb', 'r6', 'r2', 4),         # second shown so far (by a message or a fill)
        *([('subs', 'r7', 'r0', 'r6')] if ph else []),   # seconds on from the shown one
        ('subs', 'r6', 'r6', 'r0'),      # r6 != 0: the shown time changes
        ('cbnz', 'r6', 'changed'),
        ('ldr_lit', 'r3', 'lit_msg_track'),
        ('ldrb', 'r3', 'r3', 0),
        ('ldr_lit', 'r6', 'lit_cur_track'),
        ('ldrb', 'r6', 'r6', 0),         # +0xFC is only written after this hook
        ('subs', 'r6', 'r6', 'r3'),
        ('cbnz', 'r6', 'changed'),
        ('ldr_lit', 'r3', 'lit_armed'),
        ('ldrb', 'r6', 'r3', 0),
        ('subs_i3', 'r6', 'r6', 1),      # not armed yet: first message since playing
        'changed:',
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
        *([('movs', 'r7', PH_RESTART)] if ph else []),
        'gap_same:',
        ('strb', 'r4', 'r2', 0),
        ('ldr_lit', 'r5', 'lit_prev'),   # remember track, sec, min
        ('ldr_lit', 'r3', 'lit_msg_track'),
        ('ldrb', 'r3', 'r3', 0),
        *([('ldrb', 'r2', 'r5', 0),
           ('cmp', 'r2', 'r3'),
           ('beq', 'ph_same_track'),
           ('movs', 'r7', PH_RESTART),   # another track: its seconds start elsewhere
           'ph_same_track:'] if ph else []),
        ('strb', 'r3', 'r5', 0),
        ('strb', 'r0', 'r5', 1),
        ('ldr_lit', 'r3', 'lit_elapsed'),
        ('ldr', 'r3', 'r3', 0),
        ('strb', 'r3', 'r5', 2),
    ] + ([
        # TIME_FILL_PHASE_ON: P = estimated start of the shown second.
        # r7 = seconds on from the shown one, or PH_RESTART; r4 = in the gap
        ('bl', 'now_fine'),              # r0 = now (r1 survives)
        ('ldr_lit', 'r2', 'lit_stamp'),
        ('ldr_lit', 'r3', 'lit_armed'),
        ('ldrb', 'r3', 'r3', 0),
        ('cbz', 'r3', 'ph_set'),         # first message since playing
        ('ldrh', 'r3', 'r2', 0),
        ('cmp', 'r7', 0),
        ('beq', 'ph_min'),               # the same second again
        ('cbz', 'r4', 'ph_up'),
        ('adds_i8', 'r7', 1),            # gap (counts down): -1, or 59 from x:00
        ('b', 'ph_next'),
        'ph_up:',
        ('adds_i8', 'r7', 59),           # +1, or -59 from x:59
        'ph_next:',
        ('cmp', 'r7', 0),
        ('beq', 'ph_one'),
        ('cmp', 'r7', 60),
        ('bne', 'ph_set'),               # a jump: restart
        'ph_one:',
        ('adds_i8', 'r3', TIME_PHASE_SEC),
        'ph_min:',
        ('subs', 'r7', 'r0', 'r3'),
        ('lsls', 'r7', 'r7', 16),
        ('bmi', 'ph_set'),               # arrived before P (+ 1 s): it began earlier
        ('mov', 'r0', 'r3'),
        'ph_set:',
        ('strh', 'r0', 'r2', 0),
    ] if ph else [
        ('cbz', 'r6', 'same_time'),
        ('ldr_lit', 'r0', 'lit_clock'),
        ('ldrh', 'r3', 'r0', 0),
        ('ldr_lit', 'r0', 'lit_stamp'),
        ('strh', 'r3', 'r0', 0),
    ]) + [
        'same_time:',
        ('ldr_lit', 'r0', 'lit_armed'),
        ('movs', 'r3', 1),
        ('strb', 'r3', 'r0', 0),
    ] + ([
        # LENGTH_REQUEST_ON: while playing, ask for the length until the
        # stored one is for this message's track
        ('ldr_lit', 'r3', 'lit_state'),
        ('ldrb', 'r3', 'r3', 4),
        ('cmp', 'r3', 6),
        ('bne', 'lr_done'),
        ('ldr_lit', 'r2', 'lit_skip'),
        ('movs', 'r0', 0),
        ('ldr_lit', 'r3', 'lit_msg_track'),
        ('ldrb', 'r3', 'r3', 0),
        ('ldr_lit', 'r5', 'lit_len_track'),
        ('ldrb', 'r5', 'r5', 0),
        ('cmp', 'r3', 'r5'),
        ('bne', 'lr_differ'),
        ('ldr_lit', 'r5', 'lit_elapsed'),
        ('ldr', 'r3', 'r5', 8),          # +0x108 length min
        ('ldrb', 'r5', 'r5', 0x0C),      # +0x10C length sec
        ('orrs', 'r3', 'r5'),
        ('bne', 'lr_store'),             # the right length: ask at once on the next change
        'lr_differ:',                    # (0:00: cleared at eject / standby, the track noted is stale)
        ('ldrb', 'r0', 'r2', 0),
        ('cbz', 'r0', 'lr_ask'),
        ('movs', 'r0', 0),               # skipped this one
        ('b', 'lr_store'),
        'lr_ask:',
        ('movs', 'r0', 1),               # skip the next message: the answer takes ~1 s
        ('strb', 'r0', 'r2', 0),
        ('ldr_lit', 'r2', 'lit_period'),
        ('ldr_lit', 'r0', 'lit_period_n'),
        ('strh', 'r0', 'r2', 0),         # restart the firmware's own 22 s timer
        ('mov', 'r4', 'r1'),
        ('movs', 'r0', CMD_REQ_TRACK_LENGTH),
        ('bl', CD_QUEUE),
        ('mov', 'r1', 'r4'),
        ('b', 'lr_done'),
        'lr_store:',
        ('strb', 'r0', 'r2', 0),
        'lr_done:',
    ] if LENGTH_REQUEST_ON else []) + [
        ('pop', reglist('r4', 'r5', 'r6', *(['r7'] if ph else []), pc=True)),

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
    ] + ([
        ('push', reglist('r4', lr=True)),
        ('bl', 'now_fine'),
        ('ldr_lit', 'r2', 'lit_stamp'),
        ('ldrh', 'r1', 'r2', 0),
        ('subs', 'r0', 'r0', 'r1'),
        ('uxth', 'r0', 'r0'),            # ticks since the shown second began
        ('cmp', 'r0', TIME_PHASE_SEC + TIME_PHASE_MARGIN),
        ('blo', 'tf_pop'),
        ('adds_i8', 'r1', TIME_PHASE_SEC),
        ('strh', 'r1', 'r2', 0),
        ('bl', 'tf_advance'),
        'tf_pop:',
        ('pop', reglist('r4', pc=True)),

        # now_fine() -> r0 = time in 7.5 ms TIM1 ticks (u16); uses r2, r3
        'now_fine:',
        ('push', reglist('r4', lr=True)),
        ('ldr_lit', 'r3', 'lit_clock'),
        'nf_again:',
        ('ldrh', 'r4', 'r3', 0),
        ('ldr_lit', 'r2', 'lit_sub'),
        ('ldrh', 'r2', 'r2', 0),
        ('ldrh', 'r0', 'r3', 0),
        ('cmp', 'r0', 'r4'),
        ('bne', 'nf_again'),             # the clock counted in between
        ('movs', 'r4', 10),
        ('muls', 'r0', 'r4'),
        ('subs', 'r0', 'r0', 'r2'),
        ('adds_i8', 'r0', 10),
        ('uxth', 'r0', 'r0'),
        ('pop', reglist('r4', pc=True)),

        'tf_advance:',
    ] if ph else [
        ('ldr_lit', 'r2', 'lit_stamp'),
        ('ldrh', 'r0', 'r2', 0),
        ('ldr_lit', 'r1', 'lit_clock'),
        ('ldrh', 'r1', 'r1', 0),
        ('subs', 'r1', 'r1', 'r0'),
        ('uxth', 'r1', 'r1'),            # 75 ms steps since the shown second began
        ('cmp', 'r1', TIME_FILL_STEPS),
        ('blo', 'tf_ret'),
        ('adds_i8', 'r0', TIME_FILL_STEP),
        ('strh', 'r0', 'r2', 0),
    ]) + [
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
        'lit_cur_track:',
        ('word', CD_STATE + 0xFC),
        *(['lit_sub:', ('word', TIME_SUB_TICKS)] if ph else []),
        *(['lit_skip:', ('word', LEN_REQ_SKIP),
           'lit_len_track:', ('word', SH),        # +0: track of the stored length (shuffle patch)
           'lit_period:', ('word', LEN_PERIOD_TIMER),
           'lit_period_n:', ('word', LEN_PERIOD)] if LENGTH_REQUEST_ON else []),
    ]


# LENGTH_REQUEST_ON: the firmware's own request for the current track's length
CMD_REQ_TRACK_LENGTH = 0x22  # [04 20 01 01 80]
LEN_PERIOD_TIMER = 0x20000562  # u16: main-loop passes until the firmware's next 0x22
LEN_PERIOD = 2000


# TIME_MSG_CHECK_ON: the time message handler (type 0x21, 0x0800DD7C) starts
# with "ldr r0, =0x20000566; ldrh r0, [r0]; cbz r0, go; b 0x0800D89E" (a
# firmware timer that skips time messages while set; 0x0800D89E returns from
# the parser). time_check() replaces the load and also reports "skip" for a
# message with impossible values, so nothing of it is stored.
# With TRACK_END_EXACT_ON (shuffle patch, EXPORTS['EC_ACTION']) it also
# catches the module moving on to the next track by itself in repeat one /
# shuffle: possible only when the mode was switched while playing (see
# MODE_STATE); the message is skipped and the mode's action runs instead.
TIME_MSG_SITE = 0x0800DD7C
TIME_MSG_HOLD = 0x20000566


def time_check_code():
    ec = EXPORTS.get('EC_ACTION')
    return [
    'time_check:',
    ('ldr_lit', 'r0', 'lit_hold'),
    ('ldrh', 'r0', 'r0', 0),
    ('cbnz', 'r0', 'tc_ret'),
    ('ldr_lit', 'r1', 'lit_msg_sec'),
    ('ldrb', 'r0', 'r1', 0),         # +0x9C seconds
    ('cmp', 'r0', 59),
    ('bhi', 'tc_bad'),
    ('ldrb', 'r0', 'r1', 1),         # +0x9D frames (1/75 s)
    ('cmp', 'r0', 74),
    ('bhi', 'tc_bad'),
    *([('ldr_lit', 'r2', 'lit_tc_cd'),
       ('ldrb', 'r0', 'r2', 4),      # playing
       ('cmp', 'r0', 6),
       ('bne', 'tc_ok'),
       ('ldr_lit', 'r2', 'lit_tc_mode'),
       ('ldrb', 'r0', 'r2', 0),      # in repeat one / shuffle
       ('cmp', 'r0', 1),
       ('beq', 'tc_mode'),
       ('cmp', 'r0', 3),
       ('bne', 'tc_ok'),
       'tc_mode:',
       ('ldr_lit', 'r2', 'lit_tc_state'),
       ('ldrb', 'r0', 'r2', 0),      # but the module plays on
       ('cmp', 'r0', 0x25),
       ('bne', 'tc_ok'),
       ('ldr_lit', 'r3', 'lit_tc_cur'),
       ('ldr', 'r0', 'r3', 0),
       ('adds_i8', 'r0', 1),
       ('ldr_lit', 'r3', 'lit_tc_track'),
       ('ldrb', 'r3', 'r3', 0),
       ('cmp', 'r0', 'r3'),
       ('bne', 'tc_ok'),             # and has reached the next track:
       ('movs', 'r0', 0),
       ('strb', 'r0', 'r2', 0),      # once (the next play command sets it)
       ('push', reglist(lr=True)),
       ('bl', ec),                   # the mode's action
       ('movs', 'r0', 1),            # skip the message
       ('pop', reglist(pc=True)),
       'tc_ok:',
       ('ldr_lit', 'r2', 'lit_tc_state'),
       ('movs', 'r0', 0),
       ('strb', 'r0', 'r2', 2)] if ec else []),   # the module confirmed playing
    ('movs', 'r0', 0),
    'tc_ret:',
    ('bx_lr',),
    'tc_bad:',
    ('movs', 'r0', 1),
    ('bx_lr',),
    ('align',),
    'lit_hold:', ('word', TIME_MSG_HOLD),
    'lit_msg_sec:', ('word', CD_STATE + 0x9C),
    *(['lit_tc_cd:', ('word', CD_STATE),
       'lit_tc_mode:', ('word', PLAY_MODE),
       'lit_tc_state:', ('word', MODE_STATE),
       'lit_tc_cur:', ('word', CD_STATE + 0xFC),
       'lit_tc_track:', ('word', CD_MSG_TRACK)] if ec else []),
    ]


# MP3_ALL_FOLDERS_ON (experiment): the module numbers MP3 files across the
# whole disc. The disc info message (type 0x24, 0x0800DE3E) gives the whole
# disc's file count; the status message while playing (type 0x26, 0x0800DDEA:
# +0x95 current track, +0x9D track count) only the current folder's, which
# then limits the display, number entry, Next/Prev and the end of the disc
# to the first folder until eject. mp3_total() replaces that message's store
# of the count: on discs other than audio CDs it never lowers it.
MP3_TOTAL_SITE = 0x0800DDFC   # str.w r0, [r1, #0xf4] (r1 = CD state)
MP3_TOTAL = [
    'mp3_total:',
    ('mov', 'r2', 'r1'),
    ('adds_i8', 'r2', 0xF4),
    ('ldr', 'r3', 'r2', 0x24),       # +0x118 disc type: bit0 audio CD
    ('lsls', 'r3', 'r3', 31),
    ('bne', 'mt_store'),
    ('ldr', 'r3', 'r2', 0),          # +0xF4 track count so far
    ('cmp', 'r0', 'r3'),
    ('bhs', 'mt_store'),
    ('mov', 'r0', 'r3'),
    'mt_store:',
    ('str', 'r0', 'r2', 0),
    ('bx_lr',),
]


# MP3_DISC_NUMBERS_ON (experiment): the module plays MP3 files by their
# number on the whole disc (command 8), but reports the track number within
# the folder (file 12 = first of folder 2 is reported as 1). The firmware then
# took Next from there to file 2 of folder 1, and never saw the last file as
# the last (it repeated it). mp3_msg() replaces the call of the message
# parser (0x0800E0A2): on MP3 / WMA discs ([+0x118] bit1 / [+0x119] bit1) it
# adds a folder offset to the track number in length (type 0x20, +0x95),
# time (0x21, +0x99) and status (0x26, +0x95) messages first. The offset is
# learned when the firmware asks for a track (+0x115 changes to N): the first
# reported number r that is new (or a time message at 0:00-0:01) gives
# offset = N - r; a report that the current offset already explains (resume,
# a jump within the folder) just ends the wait. Discs other than MP3 / WMA
# reset it; numbers above 255 stay as they are.
MP3_NUM = 0x2000043C       # 4 bytes spare (dead menu table, after SAVER): +0 folder offset,
                           # +1 track asked for (0: none), +2 last reported number, +3 last +0x115
MP3_PARSE_SITE = 0x0800E0A2   # bl CD_PARSE in the main task
CD_PARSE = 0x0800D890
MP3_NUMBERS = [
    'mp3_msg:',
    ('push', reglist('r4', 'r5', 'r6', lr=True)),
    ('ldr_lit', 'r4', 'lit_cd_100'),
    ('ldr_lit', 'r5', 'lit_mp3'),
    ('movs', 'r1', 2),
    ('ldrb', 'r0', 'r4', 0x18),      # +0x118 bit1 MP3
    ('tst', 'r0', 'r1'),
    ('bne', 'mm_file'),
    ('ldrb', 'r0', 'r4', 0x19),      # +0x119 bit1 WMA
    ('tst', 'r0', 'r1'),
    ('bne', 'mm_file'),
    ('movs', 'r0', 0),               # another disc: forget the offset
    ('str', 'r0', 'r5', 0),
    ('b', 'mm_parse'),
    'mm_file:',
    ('ldrb', 'r0', 'r4', 0x1A),      # +0x11A bit0: good checksum
    ('lsls', 'r0', 'r0', 31),
    ('beq', 'mm_parse'),
    ('ldrb', 'r0', 'r4', 0x15),      # +0x115 track asked for (command 8)
    ('ldrb', 'r1', 'r5', 3),
    ('cmp', 'r0', 'r1'),
    ('beq', 'mm_asked'),
    ('strb', 'r0', 'r5', 3),
    ('cbz', 'r0', 'mm_asked'),       # (0: the stopped screen clears it)
    ('strb', 'r0', 'r5', 1),
    'mm_asked:',
    ('ldr_lit', 'r3', 'lit_cd_80'),
    ('ldrb', 'r0', 'r3', 0x0F),      # +0x8F class
    ('cmp', 'r0', 4),
    ('bne', 'mm_parse'),
    ('mov', 'r6', 'r3'),
    ('ldrb', 'r0', 'r3', 0x10),      # +0x90 type
    ('cmp', 'r0', 0x21),
    ('beq', 'mm_time'),
    ('cmp', 'r0', 0x26),
    ('beq', 'mm_status'),
    ('cmp', 'r0', 0x20),
    ('bne', 'mm_parse'),
    ('ldrb', 'r0', 'r3', 0x13),      # length: +0x93 1 = of a track
    ('cmp', 'r0', 1),
    ('bne', 'mm_parse'),
    'mm_status:',
    ('adds_i8', 'r6', 0x15),         # +0x95
    ('b', 'mm_have'),
    'mm_time:',
    ('adds_i8', 'r6', 0x19),         # +0x99
    'mm_have:',
    ('ldrb', 'r0', 'r6', 0),         # reported number
    ('ldrb', 'r1', 'r5', 1),
    ('cbz', 'r1', 'mm_xlate'),       # not waiting
    ('ldrb', 'r2', 'r5', 0),
    ('adds', 'r3', 'r0', 'r2'),
    ('cmp', 'r3', 'r1'),
    ('beq', 'mm_done'),              # the offset already fits
    ('ldrb', 'r3', 'r5', 2),
    ('cmp', 'r0', 'r3'),
    ('bne', 'mm_learn'),             # a new number
    ('ldr_lit', 'r3', 'lit_cd_80'),
    ('ldrb', 'r2', 'r3', 0x10),
    ('cmp', 'r2', 0x21),
    ('bne', 'mm_xlate'),
    ('ldrb', 'r2', 'r6', 2),         # time message: +0x9B min
    ('cbnz', 'r2', 'mm_xlate'),
    ('ldrb', 'r2', 'r6', 3),         # +0x9C sec
    ('cmp', 'r2', 1),
    ('bhi', 'mm_xlate'),             # same number, but the file just started
    'mm_learn:',
    ('cbz', 'r0', 'mm_xlate'),
    ('cmp', 'r0', 'r1'),
    ('bhi', 'mm_xlate'),
    ('subs', 'r2', 'r1', 'r0'),
    ('strb', 'r2', 'r5', 0),
    'mm_done:',
    ('movs', 'r2', 0),
    ('strb', 'r2', 'r5', 1),
    'mm_xlate:',
    ('strb', 'r0', 'r5', 2),
    ('ldrb', 'r2', 'r5', 0),
    ('adds', 'r0', 'r0', 'r2'),
    ('cmp', 'r0', 255),
    ('bhi', 'mm_parse'),
    ('strb', 'r0', 'r6', 0),
    'mm_parse:',
    ('bl', CD_PARSE),
    ('pop', reglist('r4', 'r5', 'r6', pc=True)),
    ('align',),
    'lit_cd_100:', ('word', CD_STATE + 0x100),
    'lit_cd_80:', ('word', CD_STATE + 0x80),
    'lit_mp3:', ('word', MP3_NUM),
]


def patch_cdtime(img):
    if MP3_DISC_NUMBERS_ON:
        cave, lab = assemble(MP3_NUMBERS, cave_addr(img))
        old, _ = assemble([('bl', CD_PARSE)], MP3_PARSE_SITE)
        site, _ = assemble([('bl', lab['mp3_msg'])], MP3_PARSE_SITE)
        patch(img, MP3_PARSE_SITE, old, site)
        put(img, lab['mp3_msg'], cave)
        print(f"cdtime: mp3_msg at {lab['mp3_msg']:#x}, {len(cave)} bytes")
    if MP3_ALL_FOLDERS_ON:
        cave, lab = assemble(MP3_TOTAL, cave_addr(img))
        site, _ = assemble([('bl', lab['mp3_total'])], MP3_TOTAL_SITE)
        patch(img, MP3_TOTAL_SITE, bytes.fromhex('c1f8f400'), site)
        put(img, lab['mp3_total'], cave)
        print(f"cdtime: mp3_total at {lab['mp3_total']:#x}, {len(cave)} bytes")
    if TIME_MSG_CHECK_ON:
        cave, lab = assemble(time_check_code(), cave_addr(img))
        site, _ = assemble([('bl', lab['time_check'])], TIME_MSG_SITE)
        patch(img, TIME_MSG_SITE, bytes.fromhex('c0480088'), site)   # ldr r0, =0x20000566; ldrh r0, [r0]
        put(img, lab['time_check'], cave)
        print(f"cdtime: time_check at {lab['time_check']:#x}, {len(cave)} bytes")
    if not (TIME_FILL_ON or PREGAP_MINUS_ON or LENGTH_REQUEST_ON):
        print('cdtime: off (TIME_FILL_ON, PREGAP_MINUS_ON and LENGTH_REQUEST_ON are False)')
        return
    # the length request compares with the track of the stored length, which the shuffle patch notes
    assert not LENGTH_REQUEST_ON or TRACK_END_FIX_ON or LAST_TRACK_FULL_ON, \
        'LENGTH_REQUEST_ON needs TRACK_END_FIX_ON or LAST_TRACK_FULL_ON'
    cave, lab = assemble(cd_time(), cave_addr(img))
    for site in (0x0800DDA6, 0x0800DDDC):      # seek / play branch of the time message
        code, _ = assemble([('bl', lab['time_msg'])], site)
        patch(img, site, bytes.fromhex('81f80401'), code)
    if TIME_FILL_ON:
        TICK_HOOKS.insert(0, lab['time_fill'])  # before the display text hooks
    put(img, lab['time_msg'], cave)
    print(f"cdtime: time_msg at {lab['time_msg']:#x}, {len(cave)} bytes"
          + (' (time fill)' if TIME_FILL_ON else '') + (' (gap detection)' if PREGAP_MINUS_ON else '')
          + (' (length request)' if LENGTH_REQUEST_ON else ''))


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
            *([('ldr_lit', 'r0', 'lit_mode'),  # repeat one / disc, shuffle: the real end
               ('ldrb', 'r0', 'r0', 0),        # comes from the module; only a late
               ('cmp', 'r0', 0),               # fallback here
               ('beq', 'ec_orig'),
               ('cmp', 'r0', 3),
               ('bhi', 'ec_orig'),
               ('ldr_lit', 'r3', 'lit_cur'),
               ('ldr', 'r1', 'r3', 0x0C),      # +0x108 length min
               ('movs', 'r2', 60),
               ('muls', 'r1', 'r2'),
               ('ldrb', 'r2', 'r3', 0x10),     # +0x10C length sec
               ('adds', 'r1', 'r1', 'r2'),
               ('cbz', 'r1', 'ec_done'),
               ('ldr', 'r0', 'r3', 4),         # +0x100 elapsed min
               ('movs', 'r2', 60),
               ('muls', 'r0', 'r2'),
               ('ldrb', 'r2', 'r3', 8),        # +0x104 elapsed sec
               ('adds', 'r0', 'r0', 'r2'),
               ('adds_i8', 'r1', TRACK_END_LATE_S),
               ('cmp', 'r0', 'r1'),
               ('blo', 'ec_done'),
               ('bl', EXPORTS['EC_ACTION']),
               ('b', 'ec_done'),
               'ec_orig:'] if TRACK_END_EXACT_ON else []),
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


# LAST_TRACK_END_ON: the module's "track ended" status (class 3 type 3,
# 40 30 40) while playing goes to 0x0800DAAC: it plays track +0xFC + 1 while
# the last requested track (+0x115) is below the track count, else it plays
# +0x115 again. MP3 discs report the end of the last file this way (audio CDs
# send "end of disc", 41 30 41, to 0x0800D9C4), so the last file repeated.
# last_end() replaces the "cmp +0x115, count; bhs" there: when the current
# track is the last, it continues in the end-of-disc handler instead (normal:
# stop, repeat one: again, repeat disc: track 1, shuffle: left to END_CHECK).
LAST_END_SITE = 0x0800DAD2  # cmp r0, r1; bhs 0x0800DAE4 (r0 = +0x115, r1 = track count)
LAST_END_PLAY = 0x0800DAE4  # play +0x115 (again)
END_OF_DISC = 0x0800D9C4
# TRACK_END_EXACT_ON: END_CHECK acts 2 s before the stored length in repeat
# one, shuffle and repeat disc (last track). Audio CD lengths are 2 s short
# (to the next track's start - 2 s), MP3 lengths exact: 2-4 s of the track
# were cut. The module knows the real end: in "stop at each track end" mode
# (command 0x24) it stops there and reports "track ended" (the last track:
# "end of disc"). Now:
#  - repeat one and shuffle use that mode. q_hook() wraps CD_QUEUE: every
#    play command (8, from any of the firmware's ~10 places) is preceded by
#    0x24 (repeat one, shuffle) or 0x25 (continuous), unless that was the
#    last mode command queued (also the firmware's own: 0x24 before FF/REW,
#    0x25 in Play, Shuffle on 0x0D / off 0x23 with the same bytes).
#    Continuous play (normal, repeat disc) stays 0x25: gapless.
#  - the module applies the mode only with a play command (a mode command
#    while playing is ignored). MODE_STATE+0 holds the mode sent with the
#    last play command; when it is continuous in repeat one / shuffle (the
#    mode was switched while playing), a time message for the next track
#    (the module moved on by itself, at the gap's start) counts as the
#    track's end (time_check in cdtime).
#  - "track ended" in repeat one / shuffle runs END_CHECK's own action for
#    the mode (0x0800D1E2: the same track again / a random one) instead of
#    the next track; so does "end of disc" in shuffle (eod_mode(), the
#    firmware did nothing there). A short pause; the laser moves anyway.
#  - END_CHECK itself only acts TRACK_END_LATE_S after the stored length in
#    those modes (and repeat disc, whose last track ends with "end of disc"),
#    as a fallback when that report does not come.
#  - the module may report a track's end twice (seen: "end of disc", then
#    "track ended" once repeat disc had already started track 1, which then
#    played track 2). q_hook marks every play command (MODE_STATE+2), the
#    next time message (time_check) clears it; te_gate() (0x0800DAAC) and
#    eod_mode() drop a "track ended" / "end of disc" while it is set or a
#    track change is pending (NEXT_FLAG): a report about the previous track.
MODE_STATE = 0x20000440    # 3 bytes spare (dead menu table, after MP3_NUM): +0 mode (0x24 / 0x25)
                           # sent with the last play command, +1 last mode command queued,
                           # +2 play command sent, no time message since
TE_SITE = 0x0800DAAC       # "track ended": ldr r0, =CD_STATE; ldrb r0, [r0, #4] (play state)
END_ACTION = 0x0800D1E2    # in END_CHECK, after the time check: act on the play mode
PARSE_RETURN = 0x0800D89E  # pop {pc}: the end of the message parser
CD_QUEUE_COUNT = CD_STATE + 0x24  # u8: commands in the queue (CD_QUEUE takes at most 5)
LAST_END = [
    *(['ec_action:',                 # END_CHECK's action for the play mode, in its own frame
       ('push', reglist('r4', 'r5', 'r6', lr=True)),
       ('b.w', END_ACTION),

       'q_hook:',                    # CD_QUEUE(r0 = command)
       ('cmp', 'r0', 8),
       ('beq', 'qh_play'),
       ('movs', 'r1', 0x24),
       ('cmp', 'r0', 0x24),
       ('beq', 'qh_note'),
       ('cmp', 'r0', 0x0D),          # Shuffle on: the same bytes
       ('beq', 'qh_note'),
       ('movs', 'r1', 0x25),
       ('cmp', 'r0', 0x25),
       ('beq', 'qh_note'),
       ('cmp', 'r0', 0x23),          # Shuffle off: the same bytes
       ('bne', 'q_orig'),
       'qh_note:',
       ('ldr_lit', 'r2', 'lit_mode_state'),
       ('strb', 'r1', 'r2', 1),
       ('b', 'q_orig'),
       'qh_play:',
       ('push', reglist('r4', lr=True)),
       ('ldr_lit', 'r1', 'lit_le_mode'),
       ('ldrb', 'r1', 'r1', 0),
       ('movs', 'r2', 0x25),
       ('cmp', 'r1', 1),
       ('beq', 'qp_stop'),
       ('cmp', 'r1', 3),
       ('bne', 'qp_mode'),
       'qp_stop:',
       ('movs', 'r2', 0x24),
       'qp_mode:',
       ('ldr_lit', 'r4', 'lit_mode_state'),
       ('strb', 'r2', 'r4', 0),      # the mode this play command starts
       ('movs', 'r1', 1),
       ('strb', 'r1', 'r4', 2),      # until the module's next time message
       ('ldrb', 'r1', 'r4', 1),
       ('cmp', 'r1', 'r2'),
       ('beq', 'qp_play'),           # already queued
       ('ldr_lit', 'r1', 'lit_q_count'),
       ('ldrb', 'r1', 'r1', 0),
       ('cmp', 'r1', 3),
       ('bhi', 'qp_play'),           # no room for both: the play command first
       ('strb', 'r2', 'r4', 1),
       ('mov', 'r0', 'r2'),
       ('bl', 'q_orig'),
       'qp_play:',
       ('movs', 'r0', 8),
       ('bl', 'q_orig'),
       ('pop', reglist('r4', pc=True)),
       'q_orig:',                    # CD_QUEUE's own first instructions
       ('push', reglist(lr=True)),
       ('mov', 'r3', 'r0'),
       ('b.w', CD_QUEUE + 4),

       'eod_mode:',                  # end of disc (0x0800D9C4: r0 = play mode)
       ('push', reglist(lr=True)),
       ('bl', 'stale'),
       ('beq', 'eod_go'),
       ('pop', reglist('r0')),
       ('b.w', PARSE_RETURN),
       'eod_go:',
       ('ldr_lit', 'r0', 'lit_le_mode'),
       ('ldrb', 'r0', 'r0', 0),
       ('cmp', 'r0', 3),
       ('bne', 'eod_ret'),
       ('pop', reglist('r1')),
       ('bl', 'ec_action'),          # shuffle: the next random track
       ('b.w', PARSE_RETURN),
       'eod_ret:',
       ('pop', reglist(pc=True)),

       'te_gate:',                   # track ended (0x0800DAAC: r0 = play state)
       ('push', reglist(lr=True)),
       ('bl', 'stale'),
       ('beq', 'tg_go'),
       ('pop', reglist('r0')),
       ('b.w', PARSE_RETURN),
       'tg_go:',
       ('ldr_lit', 'r0', 'lit_le_cd'),
       ('ldrb', 'r0', 'r0', 4),
       ('pop', reglist(pc=True)),

       'stale:',                     # -> Z clear: a report about the previous track
       ('ldr_lit', 'r0', 'lit_mode_state'),
       ('ldrb', 'r0', 'r0', 2),
       ('ldr_lit', 'r1', 'lit_le_next'),
       ('ldrb', 'r1', 'r1', 0),
       ('orrs', 'r0', 'r1'),
       ('bx_lr',)] if TRACK_END_EXACT_ON else []),

    'last_end:',
    *([('ldr_lit', 'r2', 'lit_le_mode'),   # "track ended" in repeat one / shuffle:
       ('ldrb', 'r2', 'r2', 0),            # the mode's own action
       ('cmp', 'r2', 1),
       ('beq', 'le_mode'),
       ('cmp', 'r2', 3),
       ('bne', 'le_seq'),
       'le_mode:',
       ('bl', 'ec_action'),
       ('b.w', PARSE_RETURN),
       'le_seq:'] if TRACK_END_EXACT_ON else []),
    ('ldr_lit', 'r2', 'lit_le_state'),
    ('ldr', 'r3', 'r2', 8),          # +0xFC current track
    ('cmp', 'r3', 'r1'),
    ('bhs', 'le_disc'),
    ('cmp', 'r0', 'r1'),
    ('bhs', 'le_again'),
    ('bx_lr',),                      # the next track (0x0800DAD6)
    'le_again:',
    ('b.w', LAST_END_PLAY),
    'le_disc:',
    ('b.w', END_OF_DISC),            # (no stack of its own: ends in the parser's return)
    ('align',),
    'lit_le_state:', ('word', CD_STATE + 0xF4),
    *(['lit_le_cd:', ('word', CD_STATE),
       'lit_le_next:', ('word', NEXT_FLAG),
       'lit_q_count:', ('word', CD_QUEUE_COUNT),
       'lit_le_mode:', ('word', PLAY_MODE),
       'lit_mode_state:', ('word', MODE_STATE)] if TRACK_END_EXACT_ON else []),
]


def patch_shuffle(img):
    assert not TRACK_END_EXACT_ON or (LAST_TRACK_END_ON and TRACK_END_FIX_ON), \
        'TRACK_END_EXACT_ON needs LAST_TRACK_END_ON and TRACK_END_FIX_ON'
    if LAST_TRACK_END_ON:
        cave, lab = assemble(LAST_END, cave_addr(img))
        site, _ = assemble([('bl', lab['last_end'])], LAST_END_SITE)
        patch(img, LAST_END_SITE, bytes.fromhex('884206d2'), site)
        put(img, lab['ec_action' if TRACK_END_EXACT_ON else 'last_end'], cave)
        print(f"shuffle: last_end at {lab['last_end']:#x}, {len(cave)} bytes"
              + (' (exact track end)' if TRACK_END_EXACT_ON else ''))
        if TRACK_END_EXACT_ON:
            EXPORTS['EC_ACTION'] = lab['ec_action']
            code, _ = assemble([('b.w', lab['q_hook'])], CD_QUEUE)
            patch(img, CD_QUEUE, bytes.fromhex('00b50346'), code)
            code, _ = assemble([('bl', lab['eod_mode'])], END_OF_DISC)
            patch(img, END_OF_DISC, bytes.fromhex('ad480078'), code)
            code, _ = assemble([('bl', lab['te_gate'])], TE_SITE)
            patch(img, TE_SITE, bytes.fromhex('6e480079'), code)
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


# seek_end(): replaces bl CD_QUEUE (command 8, play from here) at the end of
# fast forward / rewind; queues continuous play first, like the Play key.
CMD_CONTINUOUS = 0x25      # [02 01 09 01 02]: the module plays on at a track end
CMD_PLAY_FROM = 8          # play track +0x115 from +0x116:+0x117
SEEK_END_SITE = 0x0800D188
SEEK_END = [
    'seek_end:',
    ('push', reglist(lr=True)),
    ('movs', 'r0', CMD_CONTINUOUS),
    ('bl', CD_QUEUE),
    ('movs', 'r0', CMD_PLAY_FROM),
    ('bl', CD_QUEUE),
    ('pop', reglist(pc=True)),
]


def patch_gapless(img):
    cave, lab = assemble(SEEK_END, cave_addr(img))
    old, _ = assemble([('bl', CD_QUEUE)], SEEK_END_SITE)
    site, _ = assemble([('bl', lab['seek_end'])], SEEK_END_SITE)
    patch(img, SEEK_END_SITE, old, site)
    put(img, lab['seek_end'], cave)
    print(f"gapless: seek_end at {lab['seek_end']:#x}, {len(cave)} bytes")


# Number entry (see "Patch number"). The digit key handlers (0x0800E8C2..,
# keys 1-9 and 0x0A for 0) each start with mov.w r0, #300 (the timer), then
# update NEXT_TRACK / NEXT_FLAG, call the helper 0x0800E518 and sprintf
# "Tr%d" into the line 2 text.
NUM_ENTRY = 0x2000029F     # u8 spare (dead menu table): digits typed, bit 7 another may follow
NUM_TIMER = 0x20000186     # u16 TIM1 ticks until the entry plays (Play key, 0x0800E202)
NUM_SHOWN = 0x20000188     # u8: line 2 shows the entry, not the time
NUM_HELPER = 0x0800E518
NUM_TIMEOUT_SITE = 0x0800E202  # bl PLAY_HANDLER, in the TIM1 interrupt when the timer runs out
SPRINTF = 0x0802A2EC
NUM_DIGIT_KEYS = (0x0800E8C2, 0x0800E94E, 0x0800E9BA, 0x0800EA26, 0x0800EA92,
                  0x0800EAFE, 0x0800EB6A, 0x0800EBD6, 0x0800EC42, 0x0800ECAE)  # keys 0x0A, 1..9
NUM_SPRINTF_SITES = (0x0800E934, 0x0800E9A0, 0x0800EA0C, 0x0800EA78, 0x0800EAE4,
                     0x0800EB50, 0x0800EBBC, 0x0800EC28, 0x0800EC94, 0x0800ED00)  # their bl sprintf
NUM_WAIT = 300             # the firmware's 2.25 s (7.5 ms ticks)

NUMBER = [
    # num_pre(): replaces mov.w r0, #300 at the start of each digit key
    'num_pre:',
    ('ldr_lit', 'r1', 'lit_flag'),
    ('ldrb', 'r1', 'r1', 0),
    ('cbnz', 'r1', 'np_more'),
    ('ldr_lit', 'r1', 'lit_entry'),  # a new entry: no digits yet
    ('movs', 'r0', 0),
    ('strb', 'r0', 'r1', 0),
    'np_more:',
    ('ldr_lit', 'r0', 'lit_wait'),
    ('bx_lr',),

    # num_check(): replaces the helper; NEXT_TRACK has the new digit
    'num_check:',
    ('push', reglist('r4', 'r5', lr=True)),
    ('ldr_lit', 'r3', 'lit_entry'),
    ('ldrb', 'r4', 'r3', 0),
    ('lsls', 'r4', 'r4', 25),
    ('lsrs', 'r4', 'r4', 25),
    ('cmp', 'r4', 4),
    ('bhs', 'nc_count'),             # (only zeros keep the number small)
    ('adds_i8', 'r4', 1),            # digits typed
    'nc_count:',
    ('ldr_lit', 'r1', 'lit_total'),
    ('ldr', 'r1', 'r1', 0),
    ('ldr_lit', 'r2', 'lit_next'),
    ('ldrh', 'r2', 'r2', 0),
    ('cmp', 'r2', 'r1'),
    ('bhi', 'nc_cancel'),            # above the track count
    ('movs', 'r5', 10),
    ('movs', 'r0', 1),               # digits of the track count
    ('movs', 'r3', 10),
    'nc_digits:',
    ('cmp', 'r1', 'r3'),
    ('blo', 'nc_has'),
    ('adds_i8', 'r0', 1),
    ('muls', 'r3', 'r5'),
    ('cmp', 'r0', 4),
    ('blo', 'nc_digits'),
    'nc_has:',
    ('cmp', 'r4', 'r0'),
    ('bhs', 'nc_last'),
    ('mov', 'r3', 'r2'),
    ('muls', 'r3', 'r5'),
    ('cmp', 'r3', 'r1'),
    ('bhi', 'nc_last'),
    ('movs', 'r0', 0x80),            # another digit may follow: wait the 2.25 s
    ('orrs', 'r4', 'r0'),
    ('b', 'nc_store'),
    'nc_last:',
    ('cbnz', 'r2', 'nc_play'),
    'nc_cancel:',
    ('movs', 'r0', 0),               # number 0: the timeout cancels the entry
    ('ldr_lit', 'r3', 'lit_next'),
    ('strh', 'r0', 'r3', 0),
    'nc_play:',
    ('ldr_lit', 'r3', 'lit_timer'),
    ('movs', 'r0', 2),               # 15 ms
    ('strh', 'r0', 'r3', 0),
    'nc_store:',
    ('ldr_lit', 'r3', 'lit_entry'),
    ('strb', 'r4', 'r3', 0),
    ('pop', reglist('r4', 'r5', pc=True)),

    # num_text(buf, -, -, number): replaces sprintf(buf, "%s%d", "Tr", number):
    # "Tr" + the digits as typed (leading zeros) + "-" while another may follow
    'num_text:',
    ('push', reglist('r4', 'r5', 'r6', 'r7', lr=True)),
    ('movs', 'r1', 0x54),            # 'T'
    ('strb', 'r1', 'r0', 0),
    ('movs', 'r1', 0x72),            # 'r'
    ('strb', 'r1', 'r0', 1),
    ('ldr_lit', 'r1', 'lit_entry'),
    ('ldrb', 'r1', 'r1', 0),
    ('lsls', 'r1', 'r1', 25),
    ('lsrs', 'r1', 'r1', 25),
    ('cbnz', 'r1', 'nt_count'),
    ('movs', 'r1', 1),
    'nt_count:',
    ('adds_i3', 'r2', 'r0', 2),      # first digit
    ('adds', 'r4', 'r2', 'r1'),      # after the last
    ('mov', 'r1', 'r4'),
    ('movs', 'r5', 10),
    'nt_digit:',
    ('subs_i3', 'r1', 'r1', 1),
    ('udiv', 'r6', 'r3', 'r5'),
    ('mov', 'r7', 'r6'),
    ('muls', 'r7', 'r5'),
    ('subs', 'r7', 'r3', 'r7'),
    ('adds_i8', 'r7', 0x30),
    ('strb', 'r7', 'r1', 0),
    ('mov', 'r3', 'r6'),
    ('cmp', 'r1', 'r2'),
    ('bhi', 'nt_digit'),
    ('ldr_lit', 'r1', 'lit_entry'),
    ('ldrb', 'r1', 'r1', 0),
    ('lsrs', 'r1', 'r1', 7),
    ('cbz', 'r1', 'nt_end'),
    ('movs', 'r1', 0x2D),            # '-'
    ('strb', 'r1', 'r4', 0),
    ('adds_i8', 'r4', 1),
    'nt_end:',
    ('movs', 'r1', 0),
    ('strb', 'r1', 'r4', 0),
    ('pop', reglist('r4', 'r5', 'r6', 'r7', pc=True)),

    # num_timeout(): replaces bl PLAY_HANDLER when the timer runs out (TIM1
    # interrupt): an entry with number 0 is cancelled instead of played
    'num_timeout:',
    ('ldr_lit', 'r0', 'lit_flag'),
    ('ldrb', 'r1', 'r0', 0),
    ('cbz', 'r1', 'nto_play'),
    ('ldr_lit', 'r2', 'lit_next'),
    ('ldrh', 'r3', 'r2', 0),
    ('cbnz', 'r3', 'nto_play'),
    ('movs', 'r1', 0),
    ('strb', 'r1', 'r0', 0),
    ('ldr_lit', 'r0', 'lit_shown'),
    ('strb', 'r1', 'r0', 0),         # line 2: the time again
    ('ldr_lit', 'r0', 'lit_entry'),
    ('strb', 'r1', 'r0', 0),
    ('ldr_lit', 'r0', 'lit_last_min'),
    ('movs', 'r1', 0xFF),
    ('str', 'r1', 'r0', 0),
    ('ldr_lit', 'r0', 'lit_redraw'),
    ('movs', 'r1', 1),
    ('strb', 'r1', 'r0', 0),
    ('bx_lr',),
    'nto_play:',
    ('b.w', PLAY_HANDLER),
    ('align',),
    'lit_flag:', ('word', NEXT_FLAG),
    'lit_next:', ('word', NEXT_TRACK),
    'lit_entry:', ('word', NUM_ENTRY),
    'lit_wait:', ('word', NUM_WAIT),
    'lit_total:', ('word', CD_STATE + 0xF4),
    'lit_timer:', ('word', NUM_TIMER),
    'lit_shown:', ('word', NUM_SHOWN),
    'lit_last_min:', ('word', LAST_SHOWN_MIN),
    'lit_redraw:', ('word', DISPLAY_REDRAW),
]


def patch_number(img):
    cave, lab = assemble(NUMBER, cave_addr(img))
    for handler, call in zip(NUM_DIGIT_KEYS, NUM_SPRINTF_SITES):
        site, _ = assemble([('bl', lab['num_pre'])], handler)
        patch(img, handler, bytes.fromhex('4ff49670'), site)       # mov.w r0, #300
        old, _ = assemble([('bl', SPRINTF)], call)
        site, _ = assemble([('bl', lab['num_text'])], call)
        patch(img, call, old, site)
    site, _ = assemble([('b.w', lab['num_check'])], NUM_HELPER)
    patch(img, NUM_HELPER, bytes.fromhex('f948d0f8'), site)        # ldr r0, =CD_STATE; ldr.w ...
    old, _ = assemble([('bl', PLAY_HANDLER)], NUM_TIMEOUT_SITE)
    site, _ = assemble([('bl', lab['num_timeout'])], NUM_TIMEOUT_SITE)
    patch(img, NUM_TIMEOUT_SITE, old, site)
    put(img, lab['num_pre'], cave)
    print(f"number: num_check at {lab['num_check']:#x}, {len(cave)} bytes")


# saver_tick(): tick hook for the screensaver (see "Patch saver"). r4 = SAVER
# throughout; r5 = now (CLOCK_75MS).
SAVER_HIDE = (0x08, 0x0C, 0x10, 0x14, 0x18, 0x28, 0x2C, 0x30)  # ui slots hidden while it runs:
                           # line 1, line 2, play, pause, stop, play mode, two status icons
SAVER_CD = 0x24            # ui slot borrowed for the CD (hourglass / unused shuffle icon)
SAVER_CD_SIZE = 64
SAVER_CD_HEADER, SAVER_CD_DATA = lv_img_alpha4(cd(SAVER_CD_SIZE), SAVER_CD_SIZE, SAVER_CD_SIZE)  # 2 KB
SHUFFLE_ICON = (0x08030338, 89, 4, 49, 27)  # ui+0x24 as setup_ui (0x08029184) leaves it: src, x, y, w, h
SAVER_MAX_X = 230 - SAVER_CD_SIZE - 4       # the panel window hides the screen beyond x ~230
SAVER_MAX_Y = 135 - SAVER_CD_SIZE
SAVER_IDLE_STEPS = SAVER_IDLE_S * 40 // 3   # in 75 ms steps
SAVER_MOVE_STEPS = SAVER_MOVE_S * 40 // 3
assert 0 < SAVER_IDLE_STEPS < 0x10000 and 0 < SAVER_MOVE_STEPS < 0x10000, \
    'SAVER_IDLE_S / SAVER_MOVE_S: 1 s .. 81 min (16-bit 75 ms clock)'
RAND = 0x08029C14          # C library rand()
CD_STYLE = 0x200007C0      # style setup_ui gives ui+0x24 alone: image recolor white, recolor opa 0, opa 255
                           # (the alpha-only CD is drawn in the recolor colour, which LVGL only
                           # reads while the recolor opa is not 0)
STYLE_SET_IMG_RECOLOR = 0x08029B5A      # setup_ui's helpers: (style, state, value)
STYLE_SET_IMG_RECOLOR_OPA = 0x08029B8C
REFRESH_STYLE = 0x08013C14  # lv_obj_refresh_style(obj, part, prop); LVGL caches "recolor transparent"
STYLE_PROP_ALL = 0xFF


def rgb565(c):
    return (c >> 19 & 31) << 11 | (c >> 10 & 63) << 5 | (c >> 3 & 31)


def saver_code(restore):
    """restore = (src, x, y, w, h) of the borrowed object after the screensaver
    (SAVER_CD_ON), else None."""
    hide = []
    for n, slot in enumerate(SAVER_HIDE):
        skip = f'sh_skip{n}'
        hide += [('ldr_lit', 'r0', 'lit_ui'), ('ldr', 'r0', 'r0', slot), ('cbz', 'r0', skip),
                 ('ldr', 'r1', 'r0', OBJ_FLAGS), ('lsls', 'r1', 'r1', 27), ('bmi', skip),  # hidden already
                 ('movs', 'r1', 1), ('bl', OBJ_SET_HIDDEN), skip + ':']
    hide += [('ldr_lit', 'r0', 'lit_ui'), ('ldr', 'r0', 'r0', SAVER_CD), ('cbz', 'r0', 'sh_cd'),
             ('ldr', 'r1', 'r0', OBJ_FLAGS), ('lsls', 'r1', 'r1', 27), ('bpl', 'sh_cd'),
             ('movs', 'r1', 0), ('bl', OBJ_SET_HIDDEN), 'sh_cd:']
    save = [('movs', 'r6', 0)]
    for n, slot in enumerate(SAVER_HIDE):
        skip = f'sv_skip{n}'
        save += [('ldr_lit', 'r0', 'lit_ui'), ('ldr', 'r0', 'r0', slot), ('cbz', 'r0', skip),
                 ('ldr', 'r1', 'r0', OBJ_FLAGS), ('lsls', 'r1', 'r1', 27), ('bmi', skip),
                 ('movs', 'r1', 1 << n), ('orrs', 'r6', 'r1'), skip + ':']
    save += [('strb', 'r6', 'r4', 10)]
    show = [('ldrb', 'r6', 'r4', 10)]
    for n, slot in enumerate(SAVER_HIDE):
        skip = f'sw_skip{n}'
        show += [('movs', 'r1', 1 << n), ('tst', 'r6', 'r1'), ('beq', skip),
                 ('ldr_lit', 'r0', 'lit_ui'), ('ldr', 'r0', 'r0', slot), ('cbz', 'r0', skip),
                 ('movs', 'r1', 0), ('bl', OBJ_SET_HIDDEN), skip + ':']

    def cd_obj(fn, *args):  # fn(ui[SAVER_CD], args...); args are numbers or literal labels
        out = [('ldr_lit', 'r0', 'lit_ui'), ('ldr', 'r0', 'r0', SAVER_CD)]
        for reg, v in zip(('r1', 'r2'), args):
            out += [('ldr_lit', reg, v)] if isinstance(v, str) else [('movs', reg, v)]
        return out + [('bl', fn)]
    def recolor_opa(opa):  # tint strength on the CD's own style, then let LVGL notice
        return [('ldr_lit', 'r0', 'lit_cd_style'), ('movs', 'r1', 0), ('movs', 'r2', opa),
                ('bl', STYLE_SET_IMG_RECOLOR_OPA)] + cd_obj(REFRESH_STYLE, 0, STYLE_PROP_ALL)
    n = len(SAVER_CD_COLOURS)
    assert n != 1, 'SAVER_CD_COLOURS: at least two colours, or none'
    modes = len(SAVER_TEXT) - 1 + (len(SAVER_TEXT_CD) if SAVER_CD_ON else 0)   # without NONE
    if not SAVER_CD_ON:
        restore = (0, 0, 0, 0, 0)    # unused
    src, x, y, w, h = restore
    restore_code = (cd_obj(IMG_SET_SRC, 'lit_restore_src') + cd_obj(OBJ_SET_POS, x, y)
                    + cd_obj(OBJ_SET_SIZE, w, h) + cd_obj(OBJ_SET_HIDDEN, 1) + recolor_opa(0))
    # the CD (alpha only) in SAVER_CD_WHITE at full strength; CD/c's first move colours it
    cd_start = ([('ldr_lit', 'r0', 'lit_cd_style'), ('movs', 'r1', 0), ('ldr_lit', 'r2', 'lit_cd_white'),
                 ('bl', STYLE_SET_IMG_RECOLOR),
                 ('ldr_lit', 'r0', 'lit_cd_style'), ('movs', 'r1', 0), ('movs', 'r2', 0xFF),
                 ('bl', STYLE_SET_IMG_RECOLOR_OPA)]
                + cd_obj(IMG_SET_SRC, 'lit_cd_dsc') + cd_obj(OBJ_SET_SIZE, SAVER_CD_SIZE, SAVER_CD_SIZE)
                + cd_obj(REFRESH_STYLE, 0, STYLE_PROP_ALL))
    move = [('ldr_lit', 'r0', 'lit_ui'), ('ldr', 'r0', 'r0', SAVER_CD),
            ('ldrb', 'r1', 'r4', 8), ('ldrb', 'r2', 'r4', 9), ('bl', OBJ_SET_POS)]
    if n:
        move += [
            ('ldrb', 'r0', 'r4', 6),
            ('cmp', 'r0', 4),
            ('bne', 'col_done'),             # CD/w
            ('bl', RAND),                    # next colour: previous + 1 + rand % (n - 1), mod n
            ('movs', 'r1', n - 1),
            ('udiv', 'r2', 'r0', 'r1'),
            ('muls', 'r2', 'r1'),
            ('subs', 'r0', 'r0', 'r2'),
            ('ldrb', 'r1', 'r4', 7),
            ('cmp', 'r1', n),
            ('blo', 'col_prev_ok'),
            ('movs', 'r1', 0),               # junk after reset
            'col_prev_ok:',
            ('adds', 'r0', 'r0', 'r1'),
            ('adds_i8', 'r0', 1),
            ('cmp', 'r0', n),
            ('blo', 'col_ok'),
            ('movs', 'r1', n),
            ('subs', 'r0', 'r0', 'r1'),
            'col_ok:',
            ('strb', 'r0', 'r4', 7),
            ('lsls', 'r0', 'r0', 1),
            ('ldr_lit', 'r1', 'lit_palette'),
            ('adds', 'r1', 'r1', 'r0'),
            ('ldrh', 'r2', 'r1', 0),
            ('ldr_lit', 'r0', 'lit_cd_style'),
            ('movs', 'r1', 0),
            ('bl', STYLE_SET_IMG_RECOLOR),
        ] + cd_obj(REFRESH_STYLE, 0, STYLE_PROP_ALL) + ['col_done:']
    return [
        'saver_tick:',
        ('push', reglist('r4', 'r5', 'r6', lr=True)),
        ('ldr_lit', 'r4', 'lit_saver'),
        ('ldr_lit', 'r0', 'lit_clock'),
        ('ldrh', 'r5', 'r0', 0),
        ('ldrb', 'r0', 'r4', 11),
        ('cmp', 'r0', 0xA5),
        ('beq', 'st_init_done'),
        ('movs', 'r0', 0),               # first run after reset: the area held menu tables
        ('str', 'r0', 'r4', 4),          # active, key seen
        ('str', 'r0', 'r4', 8),          # position, visible objects
        ('movs', 'r0', 0xA5),
        ('strb', 'r0', 'r4', 11),
        ('strh', 'r5', 'r4', 0),
        'st_init_done:',
        # Power just switched off (the dispatcher runs before this pass's
        # display update; standby follows on the next pass): stay as it is,
        # waking would light the screen for a moment (the CD still hides what
        # the display update showed). The key stays noted, so the first pass
        # after power-on wakes it.
        ('ldr_lit', 'r0', 'lit_power'),
        ('ldrb', 'r0', 'r0', 0),
        ('cmp', 'r0', 0),
    ] + ([
        ('bne', 'st_on'),
        ('ldrb', 'r0', 'r4', 4),
        ('cmp', 'r0', 0),
        ('beq', 'to_ret'),
        ('ldrb', 'r0', 'r4', 6),
        ('cmp', 'r0', 3),
        ('blo', 'to_ret'),               # DIM / DARK
        ('b', 'st_hide'),
        'st_on:',
    ] if SAVER_CD_ON else [
        ('beq', 'to_ret'),
    ]) + [
        # activity: a key (a disc going in or out, or playing, is not allowed below)
        ('ldr_lit', 'r3', 'lit_state'),
        ('ldrb', 'r1', 'r3', 4),
        ('ldrb', 'r2', 'r3', 7),
        ('ldrb', 'r6', 'r4', 5),         # key seen
        ('movs', 'r0', 0),
        ('strb', 'r0', 'r4', 5),
        # allowed: not paused (3), playing (6) or seeking (7/8) - the module's
        # status messages also write their own codes here (0x0800D924) - and
        # the empty slot (tray 3/6) or a read disc
        ('cmp', 'r1', 3),
        ('beq', 'to_wake'),
        ('cmp', 'r1', 6),
        ('blo', 'st_not_playing'),
        ('cmp', 'r1', 8),
        ('bls', 'to_wake'),
        'st_not_playing:',
        ('cmp', 'r2', 3),
        ('beq', 'st_allowed'),
        ('cmp', 'r2', 6),
        ('beq', 'st_allowed'),
        ('ldr_lit', 'r3', 'lit_state_f4'),
        ('ldr', 'r0', 'r3', 0x28),       # +0x11C bit1: TOC read
        ('movs', 'r1', 2),
        ('tst', 'r0', 'r1'),
        ('beq', 'to_wake'),
        ('ldr', 'r0', 'r3', 0),          # +0xF4 tracks
        ('cbz', 'r0', 'to_wake'),
        'st_allowed:',
        ('ldr_lit', 'r0', 'lit_setting'),
        ('ldrb', 'r0', 'r0', 0),
        ('subs_i3', 'r0', 'r0', 2),      # DIM 0, DARK 1, CD/w 2, CD/c 3
        ('cmp', 'r0', modes - 1),
        ('bhi', 'to_wake'),              # NONE (or junk): no screensaver
        ('cbz', 'r6', 'st_idle'),
        'to_wake:',                      # conditional branches only reach 256 bytes
        ('b', 'st_wake'),
        'to_ret:',
        ('b', 'st_ret'),
        'st_idle:',
        ('mov', 'r6', 'r0'),             # mode
        ('ldrb', 'r0', 'r4', 4),
        ('cmp', 'r0', 0),
        ('bne', 'st_active'),
        ('ldrh', 'r0', 'r4', 0),
        ('subs', 'r0', 'r5', 'r0'),
        ('uxth', 'r0', 'r0'),
        ('ldr_lit', 'r1', 'lit_idle'),
        ('cmp', 'r0', 'r1'),
        ('blo', 'to_ret'),
        # start: r6 = mode (DIM 0, DARK 1, CD/w 2, CD/c 3)
        ('adds_i3', 'r1', 'r6', 1),
        ('strb', 'r1', 'r4', 6),         # mode running: 1 DIM, 2 DARK, 3 CD/w, 4 CD/c
        ('movs', 'r1', 1),
        ('strb', 'r1', 'r4', 4),
        ('movs', 'r1', 0),
        ('strb', 'r1', 'r4', 10),        # no objects to show again (DIM, DARK)
        ('movs', 'r0', SAVER_DARK_LEVEL),
        ('cmp', 'r6', 1),
        ('beq', 'st_level'),
        ('movs', 'r0', SAVER_DIM_LEVEL),
        ('ldr_lit', 'r1', 'lit_bright'),
        ('ldrb', 'r1', 'r1', 0),
        ('cmp', 'r1', 5),
        ('bhi', 'st_level'),             # (an invalid brightness: the dim level)
        ('cmp', 'r1', 'r0'),
        ('bls', 'st_level'),
        ('mov', 'r0', 'r1'),             # already darker than the dim level: keep it
        'st_level:',
        ('bl', SET_BRIGHTNESS),
    ] + ([
        ('cmp', 'r6', 2),
        ('blo', 'to_ret'),
        # CD: note what is visible, the CD image, first position
        *save,
        *cd_start,
        ('b', 'st_move'),
        'to_ret2:',
        ('b', 'st_ret'),
        'st_active:',
        ('ldrb', 'r0', 'r4', 6),
        ('cmp', 'r0', 3),
        ('blo', 'to_ret2'),              # DIM / DARK: nothing to do while it runs
        ('ldrh', 'r0', 'r4', 2),
        ('subs', 'r0', 'r5', 'r0'),
        ('uxth', 'r0', 'r0'),
        ('ldr_lit', 'r1', 'lit_move'),   # (a literal: SAVER_MOVE_S > 19 does not fit cmp #imm8)
        ('cmp', 'r0', 'r1'),
        ('blo', 'st_hide'),
        'st_move:',
        ('strh', 'r5', 'r4', 2),
        ('bl', RAND),
        ('movs', 'r1', SAVER_MAX_X + 1),
        ('udiv', 'r2', 'r0', 'r1'),
        ('muls', 'r2', 'r1'),
        ('subs', 'r0', 'r0', 'r2'),
        ('strb', 'r0', 'r4', 8),
        ('bl', RAND),
        ('movs', 'r1', SAVER_MAX_Y + 1),
        ('udiv', 'r2', 'r0', 'r1'),
        ('muls', 'r2', 'r1'),
        ('subs', 'r0', 'r0', 'r2'),
        ('strb', 'r0', 'r4', 9),
        *move,
        'st_hide:',                      # the display update shows its objects again every pass
        *hide,
        ('b', 'st_ret'),
    ] if SAVER_CD_ON else [
        'st_active:',                    # DIM / DARK: nothing to do while it runs
        ('b', 'st_ret'),
    ]) + [
        'st_wake:',
        ('strh', 'r5', 'r4', 0),         # idle time starts again
        ('ldrb', 'r0', 'r4', 4),
        ('cmp', 'r0', 0),
        ('beq', 'st_ret'),
        ('movs', 'r0', 0),
        ('strb', 'r0', 'r4', 4),
        ('ldr_lit', 'r0', 'lit_bright'),
        ('ldrb', 'r0', 'r0', 0),
        ('bl', SET_BRIGHTNESS),
    ] + ([
        ('ldrb', 'r0', 'r4', 6),
        ('cmp', 'r0', 3),
        ('blo', 'st_redraw'),
        *restore_code,
        *show,
        'st_redraw:',
    ] if SAVER_CD_ON else []) + [
        ('ldr_lit', 'r0', 'lit_last_min'),  # rewrite the time label
        ('movs', 'r1', 0xFF),
        ('str', 'r1', 'r0', 0),
        ('ldr_lit', 'r0', 'lit_redraw'),
        ('movs', 'r1', 1),
        ('strb', 'r1', 'r0', 0),
        'st_ret:',
        ('pop', reglist('r4', 'r5', 'r6', pc=True)),
        ('align',),
        'lit_saver:', ('word', SAVER),
        'lit_clock:', ('word', CLOCK_75MS),
        'lit_state:', ('word', CD_STATE),
        'lit_state_f4:', ('word', CD_STATE + 0xF4),
        'lit_idle:', ('word', SAVER_IDLE_STEPS),
        'lit_setting:', ('word', SAVER_SETTING),
        'lit_ui:', ('word', UI),
        'lit_bright:', ('word', BRIGHTNESS),
        'lit_power:', ('word', POWER_ON),
        'lit_last_min:', ('word', LAST_SHOWN_MIN),
        'lit_redraw:', ('word', DISPLAY_REDRAW),
    ] + ([
        'lit_move:', ('word', SAVER_MOVE_STEPS),
        'lit_cd_dsc:', ('word', 'cd_dsc'),
        'lit_restore_src:', ('word', src),
        'lit_cd_style:', ('word', CD_STYLE),
        'lit_cd_white:', ('word', rgb565(SAVER_CD_WHITE)),
        'lit_palette:', ('word', 'palette'),
        'palette:', *[('bytes', struct.pack('<H', rgb565(c))) for c in SAVER_CD_COLOURS],
        ('align',),
        # lv_img_dsc_t: header, data_size, data
        'cd_dsc:', ('word', SAVER_CD_HEADER), ('word', len(SAVER_CD_DATA)), ('word', 'cd_data'),
        'cd_data:', ('bytes', SAVER_CD_DATA),
    ] if SAVER_CD_ON else [])


def patch_saver(img):
    if not SAVER_CD_ON:
        restore = None
    elif 'hourglass' in EXPORTS:
        restore = (EXPORTS['hourglass'], ICON_X, ICON_Y, ICON_SIZE, ICON_SIZE)
    else:
        restore = SHUFFLE_ICON
    cave, lab = assemble(saver_code(restore), cave_addr(img))
    put(img, lab['saver_tick'], cave)
    TICK_HOOKS.append(lab['saver_tick'])     # last: after play_icon / osd have set the icons
    print(f"saver: saver_tick at {lab['saver_tick']:#x}, {len(cave)} bytes"
          + (' (with CD)' if SAVER_CD_ON else ' (no CD)'))


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
    if 'saver' in names:
        want[SAVER_IR] = SAVER_KEY
    used = set(want.values())
    for ir in range(IR_TABLE_LEN):
        key = img[IR_TABLE + ir - BASE]
        new = want.get(ir, NOOP_KEY if key in used else key)
        if new != key:
            patch(img, IR_TABLE + ir, bytes([key]), bytes([new]))


PATCHES = {'track': patch_track, 'backlight': patch_backlight, 'disctime': patch_disctime,
           'shuffle': patch_shuffle, 'play': patch_play, 'cdtime': patch_cdtime, 'remaining': patch_remaining,
           'brightness': patch_brightness, 'gapless': patch_gapless, 'number': patch_number,
           'saver': patch_saver}
# 'play' relies on disctime clearing the disc-ready state when the tray opens;
# the gap display in 'remaining' needs cdtime's gap detection; cdtime's length request
# needs the track of the stored length, which 'shuffle' notes
REQUIRES = {'play': ['disctime'], 'remaining': ['cdtime'] if PREGAP_MINUS_ON else [],
            'cdtime': ['shuffle'] if LENGTH_REQUEST_ON else [], 'saver': ['brightness']}


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

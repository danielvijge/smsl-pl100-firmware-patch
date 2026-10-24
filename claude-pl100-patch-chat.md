Claude Code v2.1.306
Opus 5.5 · Claude Team

❯ I want to reverse engineer some firmware. The firmware is in the file         
  IAP_PL100_1v1_b250219.hex. Analyse this file first                            

⏺ Analysis of IAP_PL100_1v1_b250219.hex

  The file is clean and simple. All checksums pass. It's one contiguous block of
  459,592 bytes, from 0x08004000 to 0x08074347. Nothing is encrypted or
  compressed apart from a small RAM‑init blob.

  Target and how it gets flashed

  - MCU: MindMotion MM32F103, an ARM Cortex‑M3 whose memory map copies the
    STM32F103. The update guide and isp.ini both name the "MM32F103xx_o" device.
    The firmware confirms the STM32F1‑style peripherals: RCC at 0x40021000,
    FLASH at 0x40022000, TIM1/TIM8, USART1, option bytes at 0x1FFFF800.
  - Clock: 8 MHz crystal, CPU at 96 MHz (the MM32F103's top speed). It also
    writes to an unknown peripheral at 0x40016000 early in SystemInit, which
    looks MindMotion‑specific.
  - Bootloader: the hex starts at 0x08004000, so a 16 KB bootloader sits at
    0x08000000 and is not included in this file. You enter it by holding the
    knob at power‑on. The PC tool ispV2.4.exe then talks to it over serial at
    115200 baud and reports "ISP version V322".

  How the program is built

  It was compiled with Keil MDK (ARMCC), so the standard startup chain is easy
  to follow:

  ┌───────────────────────┬─────────────────────────────────────────────────┐
  │         What          │                     Address                     │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ Initial stack pointer │ 0x20009240 (about 37 KB of RAM used)            │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ Reset_Handler         │ 0x0800F03C                                      │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ SystemInit (clock     │ 0x0800EFC2                                      │
  │ setup)                │                                                 │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ __main /              │ 0x080041B4 / 0x0802A268                         │
  │ __scatterload         │                                                 │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ main                  │ 0x0800428C; it moves the vector table to        │
  │                       │ 0x08004000                                      │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ RAM‑init table        │ 0x08074114                                      │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ Initialised variables │ packed at 0x08074134, unpacked to 0x20000000    │
  │                       │ (0x82C bytes)                                   │
  ├───────────────────────┼─────────────────────────────────────────────────┤
  │ Zero‑filled variables │ 0x2000082C, 0x8A14 bytes                        │
  └───────────────────────┴─────────────────────────────────────────────────┘

  - Interrupts: there are 93 interrupt slots and only 7 have real handlers (IRQ
    0, 23, 25, 30, 38, 40, 44). The rest go to the default handler.
  - Layout: code runs from about 0x08004000 to 0x0802B000 (~160 KB). The
    remaining ~290 KB is low‑entropy constant data, which is almost certainly
    display fonts and bitmaps.

  What the strings show

  - Version info: VERSIONS, HW_ver: 1.0, Ver 1.1, (C) SMSL AUDIO.
  - Settings menu: PCM FILTER, DSD FILTER, HPA GAIN, SOUND COLOR, PRE MODE, DPLL
    BANDWIDTH, I2S MODE, AUDIO PHASE, ASRC1–3 (D-D), I2S MCLK RATIO, XMOS MODE,
    BRIGHTNESS.
  - Sample‑rate labels from 32k up to 768k, plus DSD rates 2.82M to 22.58M.
  - Hidden modes: Factory Mode, Engineering Mode, Laser Current, HCD UPDATE!,
    HOLD MENU RESET BT! / HOLD MENU RESET ALL!. "HCD" probably refers to the CD
    loader/servo module, so the MCU can likely update it too.
  - The XMOS, ASRC and BT entries suggest this code base is shared with other
    SMSL DAC products.

  Ready for a disassembler

  - I converted the hex to a flat binary:
    /private/tmp/scratchpad/out/fw.bin
  - To load it in Ghidra or IDA: choose ARM Cortex‑M, little‑endian, Thumb, base
    address 0x08004000. Add RAM at 0x20000000 and use an STM32F103 SVD file for
    peripheral names.
  - I also set up a small capstone disassembler script in the scratchpad.
  - I saved these facts to memory for future sessions.

  Useful next steps would be naming main's init calls, finding the UART/I²C/SPI
  drivers (the links to the CD module, DAC and display), and mapping where the
  factory and engineering modes are triggered. Tell me which area to dig into
  first.

  Sources: these web searches didn't identify the MCU; the PDF and isp.ini did.
  - ithelp.ithome.com.tw (https://ithelp.ithome.com.tw/articles/10266530)
  - apos.audio – SMSL PL100 (https://apos.audio/products/smsl-pl100-cd-player)

❯ There is a settings menu and hidden modes. How can these be enabled/accessed on 
  the device? Any buttons or IR remotes that need to be pressed?                

⏺ There is no button or remote combination in this firmware (v1.1) that opens 
  the settings menu or the hidden modes. The code for them is in the image, but
  no button, knob or remote input can reach it.

  How input reaches the menus

  The main loop reads one key per pass from three sources, each turned into an
  internal key code: IR remote first, then front panel, then knob. That code
  goes to the UI handler at 0x0800707A.

  Front panel: six buttons on pins PC1–PC6, pressed = low. A button is "held"
  after 80 scan ticks; I didn't work out the tick period.

  ┌─────┬────────────────────────────────────────┬──────────────┐
  │ Pin │              Short press               │  Long press  │
  ├─────┼────────────────────────────────────────┼──────────────┤
  │ PC1 │ 0x36                                   │ 0x36         │
  ├─────┼────────────────────────────────────────┼──────────────┤
  │ PC2 │ 0x21                                   │ 0x19         │
  ├─────┼────────────────────────────────────────┼──────────────┤
  │ PC3 │ 0x20                                   │ 0x18         │
  ├─────┼────────────────────────────────────────┼──────────────┤
  │ PC4 │ 0x2F                                   │ 0x0C (power) │
  ├─────┼────────────────────────────────────────┼──────────────┤
  │ PC5 │ 0x10 (volume up, repeats while held)   │              │
  ├─────┼────────────────────────────────────────┼──────────────┤
  │ PC6 │ 0x11 (volume down, repeats while held) │              │
  └─────┴────────────────────────────────────────┴──────────────┘

  Knob: a rotary encoder on PE2/PE3 that only sends volume up/down (0x10/0x11 or
  0x5A/0x5B). It has no push‑switch input.

  IR remote: standard NEC protocol with address 0x3712. A 256‑entry table at
  0x0802D213 turns each IR command into a key code; 33 commands are mapped
  (digits 0–9, power, volume, prev/next, and so on). Holding prev/next on the
  remote gives fast‑forward/rewind.

  Why the menus can't be opened

  - Settings menu (SETTINGS, PCM FILTER, HPA GAIN, HOLD MENU RESET ALL! …): key
    0x27 is what opens it (0x080076BE). But the handler replaces 0x27 and 0x57
    with "no key" at 0x08007104, before acting on them. The only other way to
    get 0x27 is a remap from 0x24, and that only applies once the menu is
    already open. None of the three sources above can produce 0x24, 0x27 or
    0x57.
  - Hidden modes: these live in a 4‑key sequence detector at 0x080086C0. It
    watches for 0x0F, 0x24, 0x0F followed by:
    - 0x27 → Factory Mode
    - 0x57 → Engineering Mode
    - 0x14 → Laser Current
    - 0x10 → HCD UPDATE!, which also pulses GPIO pins, probably to put the CD
      loader into update mode

    Nothing calls this function. I scanned the whole image for direct calls,
    tail jumps and stored function pointers (including the RAM data that is
    unpacked at startup) and found none. The same is true of the VERSIONS screen
    (0x08004AAA), the Factory Reset routine (0x08004B20) and BT CLEAR
    (0x08006BC0).

  The XMOS, Bluetooth and ASRC strings point the same way: this is a shared SMSL
  DAC code base, and the PL100 build leaves these features in the image but
  unwired. The rest of the mode variable's uses only clear or read it.

  One thing I can't rule out: the 16 KB bootloader isn't in the hex, so I can't
  tell whether it has its own hidden options. The only entry I know of is from
  the update guide: hold the knob while powering on. That starts the serial
  updater, not a menu.

  Patching the firmware would make them reachable

  1. Map two unused IR commands (for example 0x0F and 0x1A, both empty in the
     table) to key codes 0x27 and 0x24.
  2. Remove the 0x27/0x57 filter at 0x08007104. That makes the settings menu
     reachable from the remote.
  3. Add a call to the detector at 0x080086C0 inside the key reader at
     0x0800882C. This needs a few bytes of spare flash, and there is plenty of
     empty space in the data area. Then the remote sequence MUTE?, X, MUTE?, Y
     would open the hidden modes. The "MUTE?" key is 0x0F (remote command 0x09);
     0x0F toggles a flag that looks like mute, but I haven't confirmed it.

  Flashing a patched image uses the same serial updater, so it is reversible as
  long as the bootloader stays intact. Some caution is still warranted: Laser 
  Current and HCD UPDATE control the CD mechanism directly. I can prepare a
  patched .hex and a diff for you to review if you want to go that way.

❯ I want to patch some things in the firmware. When flashing that on the        
  device, is there a chance to hard-brick it? That is, does this firmware have  
  code that handled the update? Or can I always flash an older version again in 
  case of a bad flash?                                                          

⏺ The firmware has no update code, so a bad patch most likely can't hard‑brick 
  the device. You should be able to reflash the original hex. The one real risk
  is the 16 KB block at the start of flash, which isn't in this hex.

  What the firmware does with flash

  - No update code. The vendor flash driver is linked in
    (0x0800F3B0–0x0800F920), but only one place calls it: a settings save at
    0x080064DA. That code erases the last 1 KB page (0x0807FC00) and writes 50
    bytes of settings there. Nothing else is ever erased or written, and nothing
    touches 0x08000000–0x08003FFF.
  - No option‑byte or lock‑out changes. The driver functions for option bytes,
    read protection and write protection are present but never called.
  - No jump into a bootloader. I found no jump to 0x08000000 or system memory,
    and no "set flag and reset into update mode" logic.
  - No self‑check. I saw no CRC or checksum check of the firmware, so patched
    bytes won't be rejected by this code.

  What does the updating

  The PC tool ispV2.4.exe is MindMotion's generic chip programmer. It has
  commands for reading the chip ID, option bytes, read/write protection and
  erasing flash, which is the chip maker's built‑in ROM bootloader protocol, not
  something SMSL wrote. The "ISP version V322" it reports fits a ROM bootloader
  too.

  The guide says to hold the knob while powering on to enter update mode. The
  firmware never reads a knob switch at all; the knob only turns. So the knob's
  push contact is most likely wired straight to the chip's BOOT0 pin, which
  makes the chip start its ROM bootloader in hardware before any flash code
  runs. If that's right, no firmware you flash can disable update mode, and a
  failed or interrupted flash just means repeating the knob procedure with the
  original IAP_PL100_1v1_b250219.hex.

  I haven't confirmed this on the hardware. You can check it by tracing the knob
  switch to BOOT0 on the board (pin 60 on a 64‑pin MM32F103, pin 94 on a
  100‑pin one).

  Ways you could still lose the device or a feature

  1. The 16 KB at 0x08000000 isn't in this hex. Something there boots the app at
     0x08004000. If it's ever erased, the original hex can't restore it, and
     the player won't start normally even though update mode still works.
     - Don't use Initialize (chip init / full erase) in the tool.
     - Don't use SecureProg or OptionByte. Turning read protection on and then
       off forces a full‑chip erase, which wipes this block too.
     - Only tick Run_Prog, as the guide says.
  2. Back up the whole chip before your first patch. The best way is an SWD
     debugger (any CMSIS‑DAP or J‑Link probe, OpenOCD or Keil) to dump all 512
     KB, including the first 16 KB. With that dump you can restore anything.
  3. Keep the layout. Code must stay at 0x08004000 (main sets the vector table
     there), and the patched image must stay below 0x0807FC00, where the
     settings live. The current image ends at 0x08074347, leaving about 46 KB of
     room.
  4. Hardware risk, not a brick. The hidden Laser Current and HCD UPDATE modes
     drive the CD mechanism directly (laser current, update pins on the CD
     loader module). Enabling and using them could damage the drive or the
     module's firmware, and reflashing this hex can't repair that.

  Before patching, I'd confirm the knob/BOOT0 wiring and take an SWD dump if you
  have a probe. After that, flashing patched builds is low risk.

❯ I want to have some modifications to the firmware. First modification is the  
  display of the number of tracks. When playing, it displays "Tr 03". I want    
  that to be "Tr 03 / 09", where 09 is the total number of tracks on the disc.  
  When inserting the disc, the display already displays the total time and      
  total number of tracks.                                                       

⏺ I've built the patched firmware: patch/IAP_PL100_1v1_b250219_trk.hex. During
  playback the top‑right now shows Tr03/09, but I haven't flashed it to a
  device, so it's untested on hardware. I ran the new routine in an ARM emulator
  against the real firmware image; it produced the right text for every case
  and left the time line untouched.

  The original actually draws Tr03 with no space, because the 33‑px font has no
  space character, so the new text is Tr03/09 the same way.

  How the display works

  - Display update (0x0800D4E4): while playing it writes T, r and the current
    track number into the 10‑byte text buffer for the top line. It then hands
    that buffer to an on‑screen text label (the UI library is LVGL v7).
  - Total tracks: the disc‑info screen you see after inserting a disc reads the
    total from [0x200008AC+0xF4]. That same variable is available during
    playback, so the new routine reads it from there.
  - Space on screen: the track label sat at x=135 and was 88 px wide. At 117 px,
    Tr03/09 wouldn't fit. The play/pause/stop icons are on the left, and the
    only other icon on the top row is the 30‑px repeat icon at x=90–119.

  What the patch changes

  ┌─────────────────────────┬───────────────────────────────────────────────┐
  │          Where          │                    Change                     │
  ├─────────────────────────┼───────────────────────────────────────────────┤
  │                         │ Track label moved to x=121 and widened to 119 │
  │ 0x08029402 / 0x08029410 │  px (to the screen edge, clear of the repeat  │
  │                         │ icon)                                         │
  ├─────────────────────────┼───────────────────────────────────────────────┤
  │ 0x0800D6DE (playing)    │ The "print current track" code now calls the  │
  │ and 0x0800D752 (seek)   │ new routine                                   │
  ├─────────────────────────┼───────────────────────────────────────────────┤
  │ 0x08074350 (new, 84     │ New routine in empty flash after the original │
  │ bytes)                  │  image, far below the settings page at        │
  │                         │ 0x0807FC00                                    │
  └─────────────────────────┴───────────────────────────────────────────────┘

  Everything else in the image is byte‑for‑byte identical.

  ┌───────────────────┬─────────────────────────────────────────────────────┐
  │       Disc        │                        Shows                        │
  ├───────────────────┼─────────────────────────────────────────────────────┤
  │ 1–99 tracks       │ Tr03/09 (117 of 119 px available)                   │
  ├───────────────────┼─────────────────────────────────────────────────────┤
  │ 100+ tracks (MP3  │ Original Tr123; a 3+3‑digit string is 124 px and    │
  │ discs)            │ would wrap onto two lines                           │
  ├───────────────────┼─────────────────────────────────────────────────────┤
  │ Total not known   │ Original Tr03                                       │
  │ (0)               │                                                     │
  └───────────────────┴─────────────────────────────────────────────────────┘

  The disc‑info screen still shows Tr09 plus the total time; it now sits 1–2 px
  further right because the label is wider.

  Before flashing

  - Tight fit: there's only 2 px to spare. I calculated the widths from the
    font's glyph table and letter‑spacing style, not from a real screen, so
    check that the digits aren't clipped at the right edge.
  - One unknown: I assumed the total‑tracks value stays set during playback. If
    it ever reads 0, you'll just see the old Tr03, not garbage.
  - Flashing: same steps as the update guide, with only Run_Prog ticked. To go
    back, flash the original IAP_PL100_1v1_b250219.hex. If you have an SWD
    probe, take a full flash dump first.

  To rebuild: cd patch && python3 build_patch.py ../IAP_PL100_1v1_b250219.hex 
  out.hex. The script refuses to patch if the original bytes at any patch site
  don't match, so later modifications can be added to the same script.

  Files are in patch/:
  - IAP_PL100_1v1_b250219_trk.hex
  - build_patch.py
  - thumbasm.py

❯ Next patch. When the device is switch off, the dispay stays on in a low       
  brightness. Can this be patched so the display is truely off when the device  
  is in standby?                                                                

⏺ Yes, and it's a one‑byte patch. I've confirmed it in an emulator but not on a
  device.

  Why the display glows in standby

  The backlight is PWM‑driven from timer TIM3 on pin PB1, at a brightness level
  you set in the menu. When the player goes into standby, 0x0800AA20:
  1. stops the timer, and
  2. sets PB1 to "input with pull‑up", then writes the pin's reset register
     (BRR).

  On an input pin, writing BRR switches the pull‑up to the chip's internal 
  pull‑down (about 40 kΩ). So PB1 isn't actively driven low; it's only weakly
  pulled down. These display modules usually have their own pull‑up on the
  backlight pin so the backlight defaults on. The weak pull‑down loses part of
  that tug‑of‑war, so the backlight stays faintly lit.

  The fix

  At 0x0800AA40, change the pin mode from 0x48 (input, pull‑up) to 0x10
  (push‑pull output). The reset write that follows then actively drives PB1 to 0
  V, so the backlight is fully off.

  I ran the firmware's own pin‑setup code in the emulator with both values:
  - Original: PB1 ends up as an input with pull‑down.
  - Patched: PB1 ends up as a push‑pull output driven low.

  Power‑on is unaffected: the wake path (0x0800AA08) already sets PB1 high and
  switches it back to PWM at your brightness level.

  The circuit is an inference. I'm assuming the module has a pull‑up on the
  backlight pin; the firmware alone can't show that. If the glow turns out to
  come from something else (for example the panel itself staying powered), this
  patch won't remove it. That would need a second patch to send the display
  controller its sleep command, which I can look into.

  Files in patch/

  ┌──────────────────────────────────┬─────────────────────────────────────┐
  │               File               │              Contains               │
  ├──────────────────────────────────┼─────────────────────────────────────┤
  │ IAP_PL100_1v1_b250219_bl.hex     │ Backlight fix only (1 byte changed) │
  ├──────────────────────────────────┼─────────────────────────────────────┤
  │ IAP_PL100_1v1_b250219_trk_bl.hex │ Track display + backlight fix       │
  ├──────────────────────────────────┼─────────────────────────────────────┤
  │ IAP_PL100_1v1_b250219_trk.hex    │ Track display only (from before)    │
  └──────────────────────────────────┴─────────────────────────────────────┘

  build_patch.py now takes an optional list of patches: python3 build_patch.py 
  ../IAP_PL100_1v1_b250219.hex out.hex backlight, or track,backlight, which is
  also the default. As before, it checks the original bytes at each patch site
  before changing anything.

  Flashing the backlight‑only file first is the quickest test: if the glow goes
  away in standby, the cause is confirmed. Flash with only Run_Prog ticked, as
  before.

❯ A third problem: when inserting the disc it displays the total playing time.  
  But sometimes this is the time of the previous disc. Can this bug be fixed?   

⏺ I've found the bug and built a fix as patch 3 (disctime); like the others it's
  untested on the device.

  Why the old time sticks

  The CD module reports times in a message of type 0x20. Its parser (0x0800DE02)
  uses one rule for two different things:
  - If the stored disc total is still 0, the incoming time is saved as the
    disc's total playing time.
  - Otherwise, it's saved as the current track's length, which the firmware uses
    to detect the end of a track.

  So the total time is only taken once per disc, and that relies on it being
  reset to 0 between discs. The only code that resets it is the Open/Close key
  handler (0x0800E6E0). That's why it happens only sometimes:
  - Tray pushed shut by hand: no reset at all. The old total stays, and the new
    disc's total is filed as a "track length".
  - A late message after Open: if the module sends one more time message for the
    old disc after the key reset, the old time is saved again as the total.

  The track count is always correct, because every disc load overwrites it.

  The fix

  The module also reports when the tray is open (status 0x21, which makes the
  screen show "Eject"). A disc can't be changed without the tray opening, so the
  patch resets the disc info at that moment too. It clears the same fields the
  Open/Close key clears: track count, current track and position, track length
  and total time. The status handler at 0x0800DCDE now calls a 40‑byte routine
  in the free flash area, which still sets the "Eject" status as before.

  In the emulator, the routine changes exactly those fields and nothing else in
  the CD state.

  I chose the tray‑open point because it's always a safe time to forget the
  disc. I didn't reset when reading starts, because without a capture of the
  module's messages I can't tell whether "reading" status messages also arrive
  after the total time. If the wrong time still shows up occasionally, a capture
  of the serial link between the MCU and the CD module during a disc change
  would show the exact message order.

  Files in patch/

  ┌────────────────────────────────────┬─────────────────────────────────────┐
  │                File                │              Contains               │
  ├────────────────────────────────────┼─────────────────────────────────────┤
  │ IAP_PL100_1v1_b250219_disctime.hex │ This fix only                       │
  ├────────────────────────────────────┼─────────────────────────────────────┤
  │ IAP_PL100_1v1_b250219_all.hex      │ Track display + backlight + this    │
  │                                    │ fix                                 │
  ├────────────────────────────────────┼─────────────────────────────────────┤
  │ _trk, _bl, _trk_bl                 │ Earlier builds                      │
  └────────────────────────────────────┴─────────────────────────────────────┘

  build_patch.py now accepts track, backlight and disctime in any combination.
  Each patch's code is placed one after another in the free area, so any subset
  works on its own.

  To test: play a disc, open the tray with the button, swap discs and push the
  tray shut by hand. The new disc's total time should appear.

❯ I did a diff of the original file and the patched file. It shows a change on  
  all the lines as in the original each line ends with <0x0d>                   

⏺ You're right. The original .hex uses Windows line endings (CR LF, 0x0D 0x0A),
  and my writer produced plain LF. The bytes that end up in flash are the same
  either way, but the diff was useless.

  What changed: build_patch.py now uses whatever line ending the source file has
  (CRLF here) and writes the file without any newline translation. I rebuilt
  all five .hex files.

  Result: every line now ends in CRLF, and a diff against the original shows
  only the patched records:

  ┌───────────┬───────────────────────────────────┐
  │   File    │ Lines differing from the original │
  ├───────────┼───────────────────────────────────┤
  │ _bl       │ 1                                 │
  ├───────────┼───────────────────────────────────┤
  │ _disctime │ 6                                 │
  ├───────────┼───────────────────────────────────┤
  │ _trk      │ 12                                │
  ├───────────┼───────────────────────────────────┤
  │ _trk_bl   │ 13                                │
  ├───────────┼───────────────────────────────────┤
  │ _all      │ 17                                │
  └───────────┴───────────────────────────────────┘

  In _all that's one line for the backlight byte, three for the two
  track‑display calls, two for the tray‑open hook, two for the label
  size/position, and the new code appended at the end.

  One harmless difference remains. The original's last data record held 8 bytes.
  In the patched files it's a full 16‑byte record, padded with 0xFF up to where
  the new code starts at 0x08074350. 0xFF is the value erased flash already
  has, so programming it changes nothing on the chip.

❯ give a confidence score that flashing this will not hard brick the cd player  

⏺ About 95% confident that flashing IAP_PL100_1v1_b250219_all.hex will not leave
  the player unrecoverable. That's a judgement based on the analysis, not a
  measured figure. My confidence that all three patches work as intended on the
  first try is lower, around 70–80%, but a patch that doesn't work isn't a
  brick.

  Why it's high

  1. Update mode doesn't depend on the code being patched. Holding the knob at
     power‑on is handled before the application starts: either by the chip's ROM
     bootloader through the BOOT0 pin, or by the 16 KB block at 0x08000000. In
     both cases a crashing or looping patched app can't stop you entering update
     mode and flashing the original .hex again.
  2. The bootloader area isn't touched. The patched file, like the original,
     only covers 0x08004000 and up.
  3. It erases the same flash as an official update. The patched image ends at
     0x080743CB, inside the same 1 KB flash page as the original end
     (0x08074347). The tool erases and writes exactly the same pages as SMSL's
     own update, and the settings page at 0x0807FC00 is left alone.
  4. The patches don't touch anything that writes flash. They leave the flash
     driver, option bytes and read protection alone, and contain no erase or
     write code.
  5. No electrical risk from the backlight patch. In normal operation PB1 is
     already a push‑pull output switching high and low, so holding it low in
     standby is within its normal use.

  What makes up the remaining ~5%

  - Unverified hardware assumption: I inferred from the firmware, not from the
    board, that the knob drives BOOT0 or is read by the bootloader. This is the
    biggest unknown, but SMSL's own update procedure relies on the same
    mechanism.
  - Tool settings: ticking Initialize, SecureProg or OptionByte in the ISP tool
    could erase the 16 KB block, which isn't in any .hex you have. Only tick
    Run_Prog.
  - Power loss during flashing: the same risk as any official update. It should
    still be recoverable, because the bootloader area isn't erased.
  - Unknowns about the closed‑source 16 KB block: for example, if it checksums
    the application. I saw no sign of this, and the original image has no stored
    checksum.

  To make it close to 100%

  - Dump the whole flash with an SWD probe before flashing. That backup covers
    the unknown 16 KB block too.
  - Flash the smallest patch first (_bl, a one‑byte change). Then re‑enter
    update mode once to confirm recovery works before trying the larger patches.

❯ It's flashed. Good news is that the player isn't bricked. For the patches:    
  the brightness when off is actually brighter than it was before, even         
  brighter then when on. And for the track display, this works, but it's a bit  
  too far to the right. E.g. with "Tr01/09" half of the 9 isn't displayed.      

⏺ I've rebuilt both fixes. They pass the emulator checks but haven't been on the
  player yet.

  Backlight in standby

  Your result showed the backlight is active‑low: PB1 low means lit, so my first
  patch switched it fully on. The original code tried to turn it off with a
  pull‑up, but the very next call (GPIO reset) turned that into a weak
  pull‑down, which is the glow you saw before.

  The patch now keeps the push‑pull output and calls GPIO set instead of GPIO
  reset at 0x0800AA58, so PB1 is driven high. High is the "off" part of the
  normal brightness signal, so the backlight should be fully dark. Running the
  real standby routine in the emulator leaves PB1 as a push‑pull output driven
  high. Waking up is unchanged: it switches PB1 back to the brightness PWM.

  Track display

  Now shows 01/09, using the original label position and width (x 135–223), so
  nothing is moved any more. In the emulator:

  ┌────────────────────────┬───────────────────────┬────────────────────────┐
  │          Disc          │         Shows         │ Width (label is 88 px) │
  ├────────────────────────┼───────────────────────┼────────────────────────┤
  │ 1–99 tracks            │ 01/09, 12/15, 99/99   │ 86 px                  │
  ├────────────────────────┼───────────────────────┼────────────────────────┤
  │ 0 or 100+ tracks (MP3) │ original Tr05 / Tr123 │ 67 / 86 px             │
  └────────────────────────┴───────────────────────┴────────────────────────┘

  The disc‑info screen after loading is unchanged (Tr09 plus total time).

  Files

  In patch/, all with CRLF line endings like the original:

  ┌────────────────────────────────────┬─────────────┬──────────────────────┐
  │                File                │   Patches   │ Lines differing from │
  │                                    │             │     the original     │
  ├────────────────────────────────────┼─────────────┼──────────────────────┤
  │ IAP_PL100_1v1_b250219_all.hex      │ all three   │ 16                   │
  ├────────────────────────────────────┼─────────────┼──────────────────────┤
  │ IAP_PL100_1v1_b250219_trk.hex      │ track       │ 10                   │
  │                                    │ display     │                      │
  ├────────────────────────────────────┼─────────────┼──────────────────────┤
  │ IAP_PL100_1v1_b250219_bl.hex       │ backlight   │ 2                    │
  ├────────────────────────────────────┼─────────────┼──────────────────────┤
  │ IAP_PL100_1v1_b250219_disctime.hex │ total‑time  │ 6                    │
  │                                    │ fix         │                      │
  └────────────────────────────────────┴─────────────┴──────────────────────┘

  I deleted the old _trk_bl file, since it held the wrong backlight fix.

  Flash _all.hex the same way as before. Please also check the total‑time fix
  when you get a chance: swap discs, push the tray shut by hand, and see whether
  the new disc's total time appears.


❯ All 3 patches now seem to work. There is one more bug in the original         
  firmware. When inserting a disc, it loads the TOC and when done displays the  
  time. But when pressing play before the loading is fully complete, it never   
  actually starts playing. The play icon is displayed but the screen just stays 
  on "read". Can this be patches as well? So if during loading play is          
  pressed, queue the play action, finish loading, then start playing.           

⏺ Yes, I've built that as patch 4 (play). It behaves correctly in the emulator,
  but it hasn't been on the player yet.

  Why playback never starts

  The Play/Pause handler (0x0800E10E) doesn't check whether the disc has
  finished loading.
  - If the player is stopped, which is also its state while a disc loads, it
    sends "play track 1" to the CD module. While the module is still reading the
    TOC, it ignores that command.
  - Then it always sets "playing", so the play icon appears. From then on the
    firmware thinks it's playing, so it never retries, and the screen stays on
    "Read".

  What the patch does

  1. Queues the press. When Play/Pause is pressed while stopped, the screen
     shows Read or Load, and the disc isn't ready, it only sets a "play pending"
     flag. It doesn't send a command or show the play icon; "Read" stays on
     screen.
  2. Starts playback once loading is done. Every pass of the main loop checks
     the flag. Loading counts as done when:
     - the TOC‑done bit is set (the same bit that switches the screen from
       "Read" to the disc info),
     - the track count is known, and
     - for audio CDs, the total time has arrived.

     It then runs the original Play handler, so playback starts exactly as if
     you'd pressed Play at that moment. The firmware's own end‑of‑loading
     commands go out first, because the module's command queue is first‑in,
     first‑out.
  3. Cancels the press when the tray opens, there's no disc or the tray is
     blocked, you press something else that changes the play state (Stop, for
     example), or the player goes to standby. A stale press can't start playback
     later.

  In every other situation (disc already loaded, pause, resume, tray blocked)
  Play goes straight to the original handler.

  What I checked in the emulator

  - Audio CD: Play during "Read" is held. Playback starts only once the TOC,
    track count and total time are all in, and it starts exactly once.
  - MP3 disc: starts as soon as the TOC and file count are known, since there's
    no total time to wait for.
  - Cancelling: opening the tray, standby, or another change to the play state
    cancels the pending Play; a later disc doesn't start on its own.
  - Normal Play/Pause: unchanged in all other states.

  Things to know

  - One assumption is unconfirmed on the device: that the play state is
    "stopped" while the screen shows "Read". If it isn't, the press is handled
    the original way, so the patch can't make things worse.
  - Patch 3 is now improved and required. Patch 4 depends on disctime, which now
    also clears the "disc ready" bit when the tray opens (the Open/Close key
    already did this). Without that, a hand‑closed tray could look ready using
    the previous disc's state. The build script adds disctime automatically when
    you choose play.
  - The flag lives in an unused RAM byte (0x20000238). It belongs to the dead
    hidden‑mode key detector, so if we ever enable the hidden modes, the flag
    needs to move.

  Files in patch/

  ┌────────────────────────────────┬────────────────────┬───────────────────┐
  │              File              │      Patches       │ Lines differing   │
  │                                │                    │ from the original │
  ├────────────────────────────────┼────────────────────┼───────────────────┤
  │ IAP_PL100_1v1_b250219_all.hex  │ track + backlight  │ 30                │
  │                                │ + disctime + play  │                   │
  ├────────────────────────────────┼────────────────────┼───────────────────┤
  │ IAP_PL100_1v1_b250219_play.hex │ disctime + play    │ 20                │
  ├────────────────────────────────┼────────────────────┼───────────────────┤
  │ _trk, _bl, _disctime           │ single patches     │ 10 / 2 / 6        │
  └────────────────────────────────┴────────────────────┴───────────────────┘

  Flash _all.hex as before, with only Run_Prog ticked. To test: insert a disc
  and press Play while it shows "Read". It should keep showing "Read", then the
  disc info, then start playing track 1 by itself. Also try opening the tray
  right after pressing Play; it should not start playing when you close it
  again.

❯ Does the firmware contain the code for actually playing (decoding) the disc?  
  Or is that handled by a different chip?                                       

⏺ No. The MCU firmware only controls the player; it doesn't touch the audio.
  Reading and decoding the disc happens on the CD loader module. The MCU sends
  it commands and gets back status, track and time messages.

  Evidence from the firmware

  - It's a two‑wire command link, not an audio link. The MCU talks to the CD
    module over an I2C‑style bus bit‑banged on two GPIO pins (PC10/PC11) at bus
    address 0x70 (0xE0 write / 0xE1 read in the routines at 0x080066E4 and
    0x08006840). Everything that goes over it is a small command or a short
    status message:
    - commands from the queue at 0x0800D03A: 3 = stop, 4 = pause, 6 = load, 7 =
      open, 8 = play
    - messages back from the module: tray status, TOC/track count (0x24), total
      time and track length (0x20), current track and time (0x21), disc type
      (0x01)

    That bus is far too slow to carry CD audio.
  - No audio path on the MCU. The only fast peripheral in use is SPI2 with DMA
    channel 5, and that drives the display: the same code sends
    display‑controller commands such as 0x2A (column address) at 0x08008B4C.
    Nothing sets up I2S, and there are no audio sample buffers.
  - No decoder code. The ~160 KB of code is the UI library (LVGL), the UI,
    button/IR/knob handling, the CD‑module protocol and the vendor driver
    library. There's no CD error correction or EFM demodulation, and no MP3/WMA
    decoder, which would need recognizable tables and much more code. The
    remaining ~290 KB is fonts and images.
  - The module even reports the disc type. The "MP3" and "WMA" labels on screen
    come from flags the module sends ([+0x118], [+0x119]), so it reads
    compressed files itself as well as audio CDs.
  - The module has its own firmware. The hidden HCD UPDATE! mode pulses control
    lines on the module, which only makes sense if it has its own updatable
    firmware.

  How the audio flows (inferred)

  Disc → CD module (laser, servo, error correction, CD‑DA/MP3/WMA decoding) → 
  digital audio → second PLL / clock clean‑up → CS43131 DAC → outputs.

  SMSL's own product text also says the CS43131 does the conversion and a
  separate PLL stage reduces jitter. The MCU's part is user input, the display,
  sending commands to the module, probably setting up the DAC (I haven't traced
  that), and the standby and power switching.

  What this means for patching: anything about how the disc is read or how it
  sounds (seeking, gapless playback, error handling, decoding) is in the
  module's own firmware and can't be changed from this file. The MCU can only
  change what it asks the module to do and how it presents the result, which is
  what the four patches so far do.

  I can't tell which chip is on the module from this firmware. The markings on
  the loader's main IC would identify it, and with them you could look for that
  chip's datasheet or its firmware‑update procedure.

❯ When playing a disc it displayed the time. But sometimes it skips a second.   
  I.e. it goes from "0:31" to "0:33". Is this because clocks between playing    
  and the display are misaligned?                                               

⏺ No, the display isn't counting on its own clock. It shows exactly what the CD
  module reports, so a skipped second means a position report for that second
  either was never sent by the module or was lost on the way to the MCU.

  How the time gets to the screen

  1. The module pushes the position. When it has a message, it pulls a "data
     ready" line low (PD2). The main loop sees that and reads the message over
     the two‑wire bit‑banged link (0x0800E03A → 0x0800DE8C).
  2. The parser stores it. A type‑0x21 message carries minutes and seconds,
     which go into [+0x100] and [+0x104] (0x0800DDC0).
  3. The display refreshes quickly. The TIM1 tick requests a redraw on every
     tick, the same tick that scans the buttons, so many times per second. The
     display routine redraws line 2 whenever the stored time differs from what's
     on screen.

  So the screen reacts to a new report within milliseconds. It doesn't add or
  drop seconds by itself.

  Where a second can be lost

  - The MCU drops a corrupted message. The read routine adds up a checksum
    (starting at 0x5A). If it doesn't match, the message is discarded without
    any retry or error count (0x0800DF50–0x0800DFA4). The read is clocked by
    software and can be interrupted by the timer interrupt, which does a fair
    amount of work (button scan, IR, brightness). If the module's side of the
    link is timing‑sensitive, an occasional corrupted read is plausible.
  - The module doesn't report every second. If it sends position updates on its
    own timer instead of exactly when the disc's time code moves to the next
    second, its report timing drifts against the second boundaries. That's the
    "misaligned clocks" effect you suspected, but it's between the module's
    reporting timer and the disc time, not the display, and it would be inside
    the module, where the MCU firmware can't change it.

  Both are possible from the code alone. A quick observation could tell them
  apart: when it jumps from 0:31 to 0:33, did 0:31 stay on screen for about 2 
  seconds? If so, the report for 0:32 was dropped or missing. If 0:31 lasted a
  normal second, the module's reports are drifting against the seconds.

  What I can do next

  - A diagnostic build: count dropped (bad‑checksum) messages and show the count
    on the display, for example in place of the track number. If the count goes
    up exactly when a second is skipped, the cause is in the MCU and can
    probably be fixed, for example by keeping the timer interrupt from
    interrupting the read, or by asking the module for the position again.
  - A logic analyzer on PC10/PC11 (data/clock) and PD2 (data ready) would show
    directly whether a report for the missing second was sent.

  If the module turns out not to report every second, the only MCU‑side option
  is cosmetic smoothing of the displayed time, and I'd only suggest that once we
  know the cause. Shall I build the diagnostic version?

❯ Other question, would it be possible to patch the firmware to display the     
  clock counting down, for either track or total disc? And have a button on the 
  IR to toggle between normal time, track time remaining, disc time remaining?  

⏺ Yes for track time remaining, with a free remote button for the toggle. Disc
  time remaining is only possible if the CD module reports more than I can see
  so far.

  What the firmware has to work with

  Display mode: Elapsed (current)
  Data available: track minutes/seconds from the module's position message
  ([+0x100]/[+0x104])
  Feasible?: already shown
  ────────────────────────────────────────
  Display mode: Track remaining
  Data available: current track length [+0x108]/[+0x10C] (the firmware already
  uses it to detect the end of a track, at 0x0800D190) minus elapsed
  Feasible?: Yes
  ────────────────────────────────────────
  Display mode: Disc remaining
  Data available: disc total [+0x110]/[+0x114] is known, but how far into the 
  disc we are isn't: the module reports time within the track, and I can't see
  track start times or an absolute disc time
  Feasible?: Not yet

  For disc remaining, the module's position message has bytes whose meaning I
  haven't decoded. One of them may well be the absolute disc time. A small
  diagnostic build that shows those raw bytes on screen during playback (or a
  logic‑analyzer capture) would tell. Without that, the only fallback is adding
  up the lengths of the tracks before the current one, which isn't possible
  unless the module gives the track lengths up front.

  A smaller caveat for track remaining: right after a track change there may be
  a moment where the length is still the previous track's. That only shows up on
  the real player.

  The toggle button

  The IR decoder maps three remote codes to key codes that currently do nothing:
  IR command 0x08 (key 0x5C), 0x1B (key 0x31) and 0x04 (key 0x26). I don't know
  which physical buttons send those. If your remote has a button that does
  nothing on the PL100 today (a "Time" or "Display" button, for example), it's
  very likely one of these. Please tell me which remote buttons currently have
  no effect, or a photo of the remote's button labels would help.

  The patch would make that key cycle elapsed → track remaining → (disc 
  remaining), keep the chosen mode in a spare RAM byte, and work out the
  displayed time in the existing display routine.

  Fitting it on screen

  The time uses the large 88‑px font with 3 px letter spacing. The visible width
  is about 230 px (the right edge is behind the front panel window, as with the
  track display).

  ┌─────────────┬────────┬─────────────────────────┐
  │    Text     │ Width  │          Fits?          │
  ├─────────────┼────────┼─────────────────────────┤
  │ 03.12 (now) │ 202 px │ yes                     │
  ├─────────────┼────────┼─────────────────────────┤
  │ -03.12      │ 232 px │ no, would wrap or clip  │
  ├─────────────┼────────┼─────────────────────────┤
  │ -3.12       │ 185 px │ yes, but -13.12 doesn't │
  └─────────────┴────────┴─────────────────────────┘

  So the remaining‑time mode needs some indicator other than a minus sign in
  front of the time. Options:
  - Indicator on line 1: for example R01/09 during track remaining (needs a
    small width check), or a different short marker.
  - Minus sign, leading zero dropped: -3.12 style. That works under 10 minutes,
    then the indicator has to drop.
  - No indicator: the time simply counts down. Simplest, but you can't tell the
    modes apart at a glance.

  Which buttons on your remote do nothing, and which indicator do you prefer?
  With that I can build the track‑remaining mode now. I can also build the small
  diagnostic version alongside it to find out whether disc‑remaining is
  possible.

❯ would it be possible to make the counter red when showing time remaining?     

⏺ Yes, and it's one of the easier changes, because the firmware already does it
  for mute.

  What's already there

  - 0x08029020 = red time display. It rebuilds the time label's style (88‑px
    font, 3 px letter spacing) with text colour lv_color_make(0xFF, 0x00, 0x00),
    pure red. The mute key uses it: mute on gives red "MUTE".
  - 0x080290D2 = normal white time display. It's used when un‑muting, after the
    volume display, at power‑on, and during initial setup.
  - Safe to switch often. Both rebuild the same style object in place: the old
    style data is freed first (lv_style_reset at 0x08016A0A → lv_mem_free), and
    LVGL redraws the label by itself. Muting already switches colour this way,
    so changing colour on every mode toggle shouldn't leak memory or need extra
    redraw code.

  How it would fit into the countdown patch

  - Remaining mode → red style; elapsed → white style. This happens when you
    press the toggle button.
  - The four places that restore white (un‑mute, after the volume display,
    power‑on, setup) get redirected through a small check, so they restore red
    if a remaining mode is active. Otherwise, adjusting the volume would
    silently turn the countdown white again.
  - Mute is unchanged: "MUTE" stays red, and un‑muting returns to the correct
    colour for the current mode.

  This also solves the space problem

  Red can be the indicator, so no minus sign is needed: elapsed shows white
  03.12, and track remaining shows red 03.12 counting down. Both fit the
  existing 202 px. If disc remaining turns out to be possible, it could use a
  second colour, for example amber, to tell the two countdown modes apart. That
  needs a small extra routine that sets a different colour, using the same LVGL
  functions.

  One possible confusion: mute uses red too. Mute shows the word "MUTE" rather
  than a time, though, so I don't think they'd be mixed up.

  To build it I still need the toggle button: which remote button currently does
  nothing on the PL100? It's most likely one sending IR command 0x08, 0x1B or
  0x04. If you're not sure, I can build a test version where all three toggle
  the mode, and you can see which button does it.

❯ I think the 3 keys that don't do anything are MENU, FN, and DISP. Display     
  would seem to most appropriate, I think                                       

⏺ The countdown is built as patch 5 (remaining). It behaves correctly in the
  emulator but hasn't been on the player yet.

  What it does

  - The button: MENU, FN and DISP all toggle the time display between elapsed 
    (white) and track time remaining (red). They send IR commands 0x04, 0x08 and
    0x1B, which the PL100 ignores, but I can't tell which code is DISP. Once
    you know, I can make DISP the only toggle.
  - Remaining time = track length minus elapsed, in the same 03.41 format as
    now. If the track length isn't known yet, it shows elapsed.
  - When it's red: only while playing, paused or seeking, and only in remaining
    mode. It's white again on the stopped/disc‑info screen and during the volume
    display. Mute keeps its red "MUTE" and, when you un‑mute, the right colour
    comes back.
  - Uses the firmware's own styles: the red one it already uses for MUTE and the
    normal white one.

  Checked in the emulator

  ┌─────────┬──────────────┬──────────────┬────────────────────────┐
  │ Elapsed │ Track length │ Elapsed mode │     Remaining mode     │
  ├─────────┼──────────────┼──────────────┼────────────────────────┤
  │ 00:31   │ 04:12        │ 00.31        │ 03.41 (red)            │
  ├─────────┼──────────────┼──────────────┼────────────────────────┤
  │ 03:59   │ 04:00        │ 03.59        │ 00.01                  │
  ├─────────┼──────────────┼──────────────┼────────────────────────┤
  │ 04:15   │ 04:12        │ 04.15        │ 00.00 (never negative) │
  ├─────────┼──────────────┼──────────────┼────────────────────────┤
  │ 01:05   │ unknown      │ 01.05        │ 01.05 (falls back)     │
  └─────────┴──────────────┴──────────────┴────────────────────────┘

  The colour logic was checked for playing, paused, seeking, stopped, the volume
  screen and mute. The style is only rebuilt when the colour actually changes,
  not on every refresh.

  What to check on the player

  - Just after a track change: if the module sends the new track's length a
    moment after the track starts, the countdown may briefly be calculated from
    the previous track's length.
  - The end of a track: the countdown should reach about 00.00 as the next track
    starts. The firmware's own end‑of‑track logic works 2 seconds before the
    reported length, so the last value you see may be 00.01 or 00.02.
  - Which button: tell me which of MENU, FN or DISP you want to keep for this.

  Disc remaining

  Still not possible: the firmware doesn't receive how far into the disc
  playback is. If you want, I can make a small diagnostic build that shows the
  CD module's raw position bytes on screen, to see whether one of them is the
  absolute disc time.

  Files in patch/

  File: IAP_PL100_1v1_b250219_all.hex
  Contains: all 5 patches
  Lines differing from the original: 55
  ────────────────────────────────────────
  File: IAP_PL100_1v1_b250219_remaining.hex
  Contains: countdown only
  Lines differing from the original: 26
  ────────────────────────────────────────
  File: IAP_PL100_1v1_b250219_patch.hex
  Contains: yours; I left it untouched (looks like your copy of the previous
  4‑patch build)
  Lines differing from the original: 30

  To test: start a disc, press DISP. The time should turn red and count down;
  press it again to return to white elapsed time.

❯ The button MENU and FN work in toggling remaining time, but DISP does nothing 

⏺ I've rebuilt the firmware so DISP should now toggle the countdown as well. I
  haven't confirmed it, because the code DISP sends is a best guess.

  Why I think DISP is key 0x14

  - The remote code: IR command 0x0C produces key 0x14.
  - Does nothing today: the key dispatcher's case for key 0x14 is empty, which
    matches "DISP does nothing".
  - Display‑related: it's the one key the auto‑dim logic (0x080070B0) treats
    specially. When the screen has dimmed itself, every other key only wakes the
    display, but key 0x14 is passed through.

  The change

  I pointed key 0x14's entry in the dispatcher's jump table (0x0800E66E) to the
  same toggle that MENU and FN use. DISP still produces key 0x14 itself; I
  didn't change its IR mapping. So if auto‑dim is on and the screen has dimmed,
  one press of DISP both wakes the display and toggles, while other keys only
  wake it.

  Files

  - IAP_PL100_1v1_b250219_all.hex: all 5 patches (56 lines differ from the
    original)
  - IAP_PL100_1v1_b250219_remaining.hex: countdown only (27 lines)

  Your _patch.hex is untouched.

  What to report back

  - DISP toggles: confirmed. Tell me whether MENU and FN should keep toggling
    too, or go back to doing nothing. If they should go back, I'll remove their
    two remappings, so those buttons stay free for something else later.
  - DISP still does nothing: its code is somewhere I haven't found. Then I'd
    build a short diagnostic version that shows the last received IR code on the
    display, so we know for sure.

❯ What is the auto-dim feature? As far as I can tell DISP does nothing in the   
  original firmware.                                                            

⏺ You're right: on the PL100, DISP has never done anything, and what I called
  "auto‑dim" can't switch on either. It's dormant code from the shared SMSL
  firmware, like the settings menu.

  What the code is

  - A setting: byte 0x200004D5 is a display‑timeout setting.
  - What it would do: if the value is greater than 1, then after (value − 1) × 
    500 timer ticks without a key press the firmware sets the backlight to
    "level 1". When a key is pressed, that first press only wakes the display
    and is otherwise ignored, except key 0x14, which is passed through.
  - Its menu screen: 0x0800601A, which shows OFF together with Display always 
    ON! for the value 1.

  Why it never runs on your PL100

  - Default is 1 = OFF. The factory defaults set it to 1 (0x08006C34–0x08006C40
    and 0x08006CDA–0x08006CE6).
  - Only the SETTINGS menu changes it (0x0800C920, and the menu screen at
    0x08009F7E). We found earlier that this menu can't be opened in this build.
  - Otherwise it's only loaded from the saved settings page, which can only
    contain what the defaults or the menu wrote.

  So the value stays 1, the timeout never fires, and the special case for key
  0x14 never comes into play. I also wouldn't trust my "dim" label: with the
  backlight now known to be active‑low, that "level 1" value might not even dim
  it. It doesn't matter, because it never runs.

  What that means for the DISP guess

  The auto‑dim hint is weaker than I made it sound. It only shows that SMSL's
  shared code treats key 0x14 as display‑related on products where that setting
  exists. The stronger evidence is the remote side:
  - the IR table maps IR command 0x0C to key 0x14,
  - key 0x14 lands in an empty case in the key dispatcher, so it does nothing,
  - MENU and FN turned out to be two of the three other "do nothing" codes.

  It's still a best guess. If DISP doesn't toggle with the new build, the next
  step is the diagnostic version that shows the last received IR code on screen,
  so the code is known instead of inferred. The DISP change doesn't depend on
  the dim setting either way: pressing DISP should toggle remaining time whether
  or not that dormant code is there.

❯ Yes, DISP now works too as a toggle.                                          
  During the testing of the backlight patch, the initial patch increased the    
  brightness. And the original firmware had really low brightness in standby.   
  Given that DISP might originally be a toggle for different brightness         
  settings, can that be restored?                                               

⏺ The test build is ready: patch/IAP_PL100_1v1_b250219_all_irtest.hex, with all
  six patches plus a temporary IR‑code display. It passes the emulator checks
  but hasn't been on the player.

  DISP: brightness (patch 6)

  Each press steps to the next brightness level and wraps around; "backlight
  off" is skipped:

  ┌───────────────────────────────┬──────┬──────┬───────┬──────┬──────┬──────┐
  │             Press             │  1   │  2   │   3   │  4   │  5   │  6   │
  ├───────────────────────────────┼──────┼──────┼───────┼──────┼──────┼──────┤
  │ Starting at your current 35 % │ 55 % │ 65 % │ 100 % │ 10 % │ 20 % │ 35 % │
  └───────────────────────────────┴──────┴──────┴───────┴──────┴──────┴──────┘

  - It's saved the same way the settings menu saves it, so it survives standby
    and power‑off.
  - Level 0 now survives a reload. The original load check clamps brightness to
    levels 1–6, so the 100 % step (level 0) would have come back as 65 % after a
    power cycle. Brightness now has its own check: levels 0–5 are kept,
    anything else becomes the default 3. That also means a corrupted value can
    never load as "off".
  - Standby: DISP does nothing there.
  - All other keys pass through unchanged (checked in the emulator).

  These percentages assume the active‑low backlight we found. If the steps look
  wrong on the device, they're easy to adjust.

  FN and MENU: one test needed

  In this build MENU and FN both still toggle the remaining time. Line 1 now
  shows the last IR code received, for example IR1B, instead of the track
  number. Please press each of these and note what appears:
  - FN: IR04, IR08 or IR1B
  - MENU: one of the other two

  Pressing DISP should show IR0C; that's a quick check that the display works.

  With FN's code I'll make the final build: FN toggles remaining time, MENU goes
  back to doing nothing, and line 1 shows the track number again. In
  build_patch.py that's just setting FN_IR and turning IR_DIAG_ON off.

  Files in patch/

  I removed my earlier _all.hex and _remaining.hex; the final build will replace
  them.

  ┌──────────────────────────────────────┬────────────────┬─────────────────┐
  │                                      │                │ Lines differing │
  │                 File                 │    Contains    │    from the     │
  │                                      │                │    original     │
  ├──────────────────────────────────────┼────────────────┼─────────────────┤
  │                                      │ all 6 patches  │                 │
  │ IAP_PL100_1v1_b250219_all_irtest.hex │ + IR‑code      │ 68              │
  │                                      │ display        │                 │
  ├──────────────────────────────────────┼────────────────┼─────────────────┤
  │ IAP_PL100_1v1_b250219_patch.hex      │ yours,         │ 30              │
  │                                      │ untouched      │                 │
  └──────────────────────────────────────┴────────────────┴─────────────────┘

❯ Brightness toggle works! The code shown for the different buttons is:         
  MENU: IR04                                                                    
  FN: IR08                                                                      
  DISP: IR0C                                                                    

⏺ The final build is ready: patch/IAP_PL100_1v1_b250219_all.hex, with all six
  patches and the IR‑code display removed. I re‑ran the emulator checks on this
  exact image; it still needs the check on the player.

  Remote buttons now

  ┌────────┬────────┬───────────────────────────────────────────────────────┐
  │ Button │  IR    │                         Does                          │
  │        │  code  │                                                       │
  ├────────┼────────┼───────────────────────────────────────────────────────┤
  │ DISP   │ 0x0C   │ cycles backlight brightness: 10 → 20 → 35 → 55 → 65 → │
  │        │        │  100 %, saved                                         │
  ├────────┼────────┼───────────────────────────────────────────────────────┤
  │ FN     │ 0x08   │ toggles elapsed (white) / track remaining (red)       │
  ├────────┼────────┼───────────────────────────────────────────────────────┤
  │ MENU   │ 0x04   │ nothing (remapped to a key with no function)          │
  └────────┴────────┴───────────────────────────────────────────────────────┘

  Line 1 shows the track number again (01/09).

  The six patches in this build

  1. Track display 01/09
  2. Backlight fully off in standby
  3. Correct total time after a disc change
  4. Play pressed during loading is queued, then starts once loading finishes
  5. Remaining track time in red on FN
  6. Brightness on DISP

  Emulator checks on the final image

  - DISP steps the brightness and schedules a save.
  - Every other key passes through untouched, and the IR code is no longer
    recorded.
  - FN toggles the mode, the countdown reads 03.41 for 0:31 into a 4:12 track,
    and the label turns red while playing.
  - A saved brightness of 0–5 loads back as saved; anything else becomes the
    default 3.

  Files and build script

  - IAP_PL100_1v1_b250219_all.hex: the final build, 61 lines differ from the
    original, CRLF line endings.
  - I removed the IR‑test file. Your _patch.hex is untouched.
  - In build_patch.py, FN_IR = 0x08 is now set. The diagnostic can be switched
    back on with IR_DIAG_ON = True if you ever want to identify other buttons.

❯ Why is MENU patched/remapped, as it also does nothing in the original         
  firmware?                                                                     

⏺ Because patch 5 reused MENU's own key for the toggle.

  MENU (IR 0x04) is natively key 0x26. In the original firmware the dispatcher's
  case for key 0x26 (0x0800ED42) only sets a short timer (0x20000186 = 2), with
  no visible effect, which is why MENU does nothing. It's 8 bytes long, so it
  was the only one of these "do nothing" cases with room for a call. I replaced
  it with the call to the time toggle and remapped FN's code (0x08, natively key
  0x5C, whose case is a 2‑byte jump with no room) to key 0x26.

  The side effect is that MENU would have become a time toggle too. To keep MENU
  doing nothing, I remapped it to key 0x5C, the no‑op key FN used to have. In
  effect MENU and FN swapped key codes.

  So the remap is there to keep MENU's original behaviour, not to change it.

  A cleaner alternative

  Since patch 6 already intercepts keys in the main loop (that's how DISP
  works), FN's key 0x5C could be caught there too and sent straight to the
  toggle. Then:
  - the IR table would be completely original,
  - key 0x26's case would go back to its original timer code,
  - MENU would be untouched.

  The only cost is that patch 5 would depend on the key hook from patch 6 (the
  build script can add it automatically, as with play and disctime). It behaves
  the same on the device; it just leaves the original firmware more intact. Want
  me to switch to that?

❯ I don't think the red text for track time remaining is a great choice. It     
  makes the time difficult to read from a distance. I want to revert it to the  
  default colour. But it would be nice to have a status indicator for track     
  time remaining. Is it possible to place an icon next to the playing button?   

⏺ I've rebuilt patch 5: the time stays in the normal white style, and a small
  hourglass icon appears next to the play icon when FN switches to remaining
  time. It passes the emulator checks but hasn't been on the player yet.

  Top‑left of the screen while playing in remaining mode

  play ▶ at x 5–44, hourglass at x 52–81, repeat icon at x90 when repeat is on)

  - The icon: a 30×30 hourglass in the same light‑grey line‑art style and colour
    as the repeat icon (#E8E8E8, anti‑aliased). It's generated by the new
    patch/icons.py. I previewed it next to the real play and repeat icons
    decoded from the firmware, and it matches their weight.
  - Where: (52,8), between the play/pause icon (x 5–44) and the repeat icon
    (x 90). It overlaps nothing.
  - When: shown in remaining mode while playing, paused or seeking; hidden in
    elapsed mode and when stopped.
  - The time text: I removed all the colour handling, and the four style calls
    I'd redirected are back to their original bytes.

  How it works

  - No new screen object: it reuses the firmware's shuffle icon object (+0x24),
    which the PL100 never shows. A wrapper around setup_ui gives that object the
    hourglass image and moves it into place at start‑up.
  - No constant redraws: the hook before each display update reads the object's
    "hidden" bit and only calls lv_obj_set_hidden when the state needs to
    change.

  Emulator checks

  - Setup: the image, position (52,8) and size 30×30 are set on the right
    object. The descriptor is in the firmware's own format, and the icon
    rendered back from the final image is correct.
  - Visibility: shown for playing, paused and seeking in remaining mode; hidden
    when stopped and in elapsed mode; no repeated calls on later refreshes.
  - Countdown: unchanged (00.31 → 03.41 for a 4:12 track).

  One change to flag

  The icon adds about 2.7 KB, so the patched image now ends at 0x0807504B
  instead of inside the original's last flash page. The extra pages were empty
  in the original, are well below the settings page at 0x0807FC00, and don't
  touch the bootloader, so the recovery situation is the same as before. The ISP
  tool will just erase and write a few more pages.

  File

  patch/IAP_PL100_1v1_b250219_all.hex: all six patches. 228 lines differ from
  the original, mostly the icon's pixel data. CRLF line endings as before.

  If you'd like a different symbol (a clock with a minus, a down arrow, or "−"
  text), or the icon a bit to the left or right, it's a small change in icons.py
  or the ICON_X/ICON_Y constants.

❯ Add an option to hide the hourglass icon, similar to the IR_DIAG_ON variable. 

⏺ I've added the option, next to IR_DIAG_ON in patch/build_patch.py:

  IR_DIAG_ON = False         # show the last IR command as "IRxx" on line 1 
  (diagnostic)
  REMAINING_ICON_ON = True   # hourglass icon next to the play icon in 
  remaining-time mode

  With REMAINING_ICON_ON = False, the icon is left out completely, not just
  hidden:
  - Code and data: the visibility check, the ui_setup wrapper and the 2.7 KB
    image aren't assembled. Patch 5 shrinks from 2,944 to 120 bytes, and the
    image ends at 0x08074543, back inside the original's last flash page.
  - Hooks: the setup_ui call in main keeps its original bytes. The
    display‑update call does too, unless IR_DIAG_ON is on, since the diagnostic
    uses the same hook.
  - The time toggle is unchanged: FN still switches to remaining time; there's
    just no indicator.

  Checks

  - Icon on (default): output is byte‑for‑byte identical to the
    IAP_PL100_1v1_b250219_all.hex you have.
  - Icon off: both hook sites keep their original bytes, and the countdown still
    works in the emulator (00.31 elapsed, 03.41 remaining).
  - Icon off + IR diagnostic on: builds correctly.

  My first edit for this duplicated part of the script; I repaired it before
  running any build. The byte‑for‑byte match with your current build confirms
  the repair didn't change anything else.

  To build without the icon, set REMAINING_ICON_ON = False and run python3 
  build_patch.py ../IAP_PL100_1v1_b250219.hex out.hex. I left the default on, so
  IAP_PL100_1v1_b250219_all.hex is unchanged.

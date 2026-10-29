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

❯ During boot time it shows the SMSL logo and below that "ver 1.1". Is is       
  possible to add an additional line "patch vYYYY-MM-DD"? The vYYYY-MM-DD       
  should be an option given to the python build, so the release workflow can    
  automatically add the tag as the version shown during boot                    

⏺ I've added a --version option: with it, the boot screen shows a patch 
  <version> line under "Ver 1.1". It works in the emulator; it hasn't been
  tested on the player yet. The release workflow now passes the tag:

  python3 build_patch.py --version v2026-10-25 IAP_PL100_1v1_b250219.hex out.hex

  The emulator render shows the result:
  - Without --version: the original boot screen.
  - With --version v2026-10-25:
    - "Ver 1.1" moves up 18 px to make room.
    - The new line goes below it, centred and in the same font, ending at about
      x 216, inside the visible area.

  Limits and how it's drawn:
  - Characters: the boot font has A–Z, a–z, 0–9 and  .:-+=<>/, so no _.
  - Length: at most 18 characters including "patch ", so a version of up to 12
    characters.
  - Spacing: the original text routine uses 13 px per character, which would
    have pushed patch v2026-10-25 past the visible edge. I draw the line myself
    at 12 px per character instead.
  - Bad input: the build stops with a clear message for a version that's too
    long or uses an unsupported character.

  Checks:
  - No --version: the output is byte‑identical to your
    IAP_PL100_1v1_b250219_all.hex.
  - With --version: only 6 bytes of the original change (at 0x08004B18), plus 66
    new bytes at the end of the image. Python 3.9 gives the same output.
  - Workflow step: running its build command locally with
    GITHUB_REF_NAME=v2026-10-25 works.

  Changes:
  - build_patch.py: the --version option and the new boot‑screen code,
    documented in the docstring.
  - thumbasm.py: three new instruction encodings that the new code needs.
  - README.md: the build section describes --version.
  - .github/workflows/release.yml:
    - Passes --version "$GITHUB_REF_NAME".
    - Uses python3.
    - The plain checkout step is enough.
    - Only runs for tags starting with v, so a tag without the v won't create a
      release.

  Nothing is committed or pushed. To try it on the player, build with --version
  into patch/; .hex files are git‑ignored, so it won't end up in the repo.

❯ This doesn't work. When loading this firmware in the flash program            
  ispV24.exe, there is an error "Index was outside the bounds of the array"     

⏺ I've changed the build so the image always ends on a whole 4‑byte word, and
  rebuilt patch/IAP_PL100_1v1_b250219_patch_v2026-10-25.hex. That replaced the
  copy that failed to load. I haven't been able to confirm the fix in
  ispV2.4.exe; please load the new file in it.

  The cause isn't proven, but the evidence points one way:
  - The failing file is valid: checksums, record format and CRLF line endings
    are all correct.
  - Its size is the only difference: your earlier builds and the original image
    all end on a 4‑byte boundary. The version text made this one end 2 bytes
    into a word (it ended at …508D).

  What the build does now:
  - Padding: after patching, it pads the image with 0xFF (what empty flash
    contains) up to the next 4‑byte boundary.
  - Applies to every build: this covers any version text or patch combination,
    including the release workflow.
  - No change otherwise: builds that already ended on a word are unaffected; the
    default build is still identical to the _all.hex you flashed.
  - Version lengths: v1, v1.2, v2026-10-25 and v2026-10-25b all now end on a
    word boundary.
  - Boot screen: the emulated boot screen is unchanged.

  If the tool still shows the error, tell me. The next step would be to pad to
  16 bytes so there's no partial record at all.

❯ For the time remaining display, there are 3 somewhat weird behaviours,        
  although eventually they all resolve automatically and the remaining time is  
  displayed correctly. Are these inherent to the hardware implementation, or    
  bugs introduced in the patch? All 3 assume the mode is set to time remaining. 
  1. When inserting a disc and pressing play, the hourglass icon shows, but it  
  is first time elapsed. It can take anywhere between 10 - 60 seconds to show   
  the time remaining.                                                           
  2. When a new track starts playing, sometimes it starts from the track length 
  of the previous track. After a while it corrects to the time for the current  
  track.                                                                        
  3. When the player is off with a disc in the player, switching it on and      
  pressing play, it first displays the remaining time for the whole disc, and   
  after a while it switches to the time remaining for the track.                

⏺ The time math in the patch is correct. All three effects come from how the
  original firmware stores the track length the countdown subtracts from, so
  they aren't hardware limits. I see three things the patch could improve.

  How the firmware gets the track length

  The CD module sends a message type 0x20 with a minutes/seconds value; the
  handler is at 0x0800DE02. The same message is used for two things, and the
  firmware guesses which one it is:
  - If the disc total (+0x110) is still 0, the value is taken as the disc total.
  - Otherwise, it's taken as the track length (+0x108/+0x10C).

  Nothing else in the firmware writes the track length or clears it, not even a
  track change or standby. The original firmware never displayed the track
  length, so these quirks were invisible until the countdown used it.

  1. Hourglass shown, but the time counts up

  After a disc is inserted, the first 0x20 message is the disc total, and the
  track length is still 0. To avoid showing a nonsense countdown, the patch then
  falls back to elapsed time. The module only sends the track length later; you
  saw 10–60 s.

  The bug in the patch is that the icon doesn't check this. It shows whenever
  remaining mode is on and the player is playing, even while elapsed time is on
  screen.

  2. New track starts from the previous track's length

  The firmware keeps the old track length until the module sends the new one.
  Until then, the patch counts down from the old length. This is stale data that
  the patch takes at face value.

  3. After switching on, the disc's remaining time is shown

  Standby doesn't clear the disc total. When the player wakes up, the module
  re‑reads the disc and sends the disc total again. Because the disc total is
  already set, the firmware's guess files it as the track length, so the
  countdown runs from the whole disc's length until the real track length
  arrives.

  What the patch can fix

  ┌───────────────────────────────┬─────────────────────────────────────────┐
  │              Fix              │                 Effect                  │
  ├───────────────────────────────┼─────────────────────────────────────────┤
  │ Show the hourglass only when  │                                         │
  │ remaining time is actually on │ Fixes 1: icon and time always agree     │
  │  screen                       │                                         │
  ├───────────────────────────────┼─────────────────────────────────────────┤
  │ Forget the track length when  │ Fixes 2: shows elapsed (no hourglass)   │
  │ the track number changes      │ until the new length arrives, instead   │
  │                               │ of a wrong countdown                    │
  ├───────────────────────────────┼─────────────────────────────────────────┤
  │ Ignore a 0x20 value equal to  │ Fixes 3; a single‑track disc, where     │
  │ the disc total when storing   │ both are equal anyway, is unaffected    │
  │ the track length              │                                         │
  └───────────────────────────────┴─────────────────────────────────────────┘

  None of these makes the countdown start sooner. The wait depends on when the
  module sends the track length, which I can't control without knowing the
  module's protocol better. It's possible the regular time message also carries
  the track length or the disc position in bytes the firmware ignores. The
  raw‑bytes diagnostic I offered earlier would show that, and could lead to an
  immediate countdown.

  Should I implement the three fixes, the diagnostic first, or both?

❯ all 3 don't really fix the underlying problem, so a small dyagnistic build    
  that shows raw-bytes might prove a better path forward.                       

⏺ The diagnostic build is ready: patch/IAP_PL100_1v1_b250219_cd_diag.hex. I
  checked it in the emulator with fake messages; it hasn't run on the player
  yet. It has all six patches, but the normal display is replaced by the raw
  messages from the CD module, so it's only for investigating. Flash _all.hex
  back afterwards.

  This is the emulator's render with made‑up data
  (/private/tmp/claude-501/-Users-daniel-Projects-github-pl100/88cfedcb-82b1-4be
  2-85a7-f37443209b40/scratchpad/out/diag_screen.png):

  ┌──────┬───────────────────────────────────────────────────────────────────┐
  │ Line │                               Shows                               │
  ├──────┼───────────────────────────────────────────────────────────────────┤
  │ 1–2  │ last time message (starts 04 21)                                  │
  ├──────┼───────────────────────────────────────────────────────────────────┤
  │ 3–4  │ last length message (starts 04 20)                                │
  ├──────┼───────────────────────────────────────────────────────────────────┤
  │ 5–6  │ last other message from the same group, e.g. track info (04 26)   │
  ├──────┼───────────────────────────────────────────────────────────────────┤
  │ 7    │ last message of any other kind, e.g. disc/tray status             │
  ├──────┼───────────────────────────────────────────────────────────────────┤
  │ 8    │ OK received messages, ER messages dropped for a bad checksum      │
  │      │ (hex)                                                             │
  └──────┴───────────────────────────────────────────────────────────────────┘

  Bytes are in hex, alternating white/yellow so each pair is easy to tell apart.
  The playback controls still work as usual.

  What to film: short videos of the screen, ideally with the remote in view,
  during:
  1. Inserting a disc and pressing Play, until the length line shows the track's
     length (the 10–60 s case).
  2. A track change, including the moment the new track starts.
  3. Player off → on with the disc inside → Play.
  4. Optionally, a minute of normal playback. If ER goes up, that confirms the
     one‑second skips come from dropped messages.

  I can read the bytes from the video. What I'm looking for is whether the time
  message, or another frequent message, already carries the track length or the
  disc position in bytes the firmware ignores. If it does, the countdown can
  start straight away and the three quirks go away.

  Checks:
  - Default build unchanged: without --cd-diag the output is still
    byte‑identical to _all.hex.
  - Image size: this file ends on a word boundary, so it avoids the flash‑tool
    error from before.
  - Build:
    - New --cd-diag flag in build_patch.py.
    - Two new instruction encodings in thumbasm.py.
    - Python 3.9 gives the same output.

  Possible issues:
  - Text size: the 12×16 text is small, so film close up.
  - Screen edges: if the top or bottom line is hidden behind the front panel
    window, tell me and I'll move the lines.

❯ For test 1, the film is in the file diag_01.mov Is this good, and can it      
  already provide some indication. Based on this, what can be deducted? And     
  does it make sense to film the other diagnostic cases?                        

⏺ Yes, the video works. At 640×360 the bytes are still readable once I crop the
  display out of each frame. If you can, film at 1080p; a few frames were
  borderline.

  What the video shows

  ┌────────────────┬────────────────────────────────────────────────────────┐
  │ Time in video  │              Messages from the CD module               │
  ├────────────────┼────────────────────────────────────────────────────────┤
  │ 5–9 s          │ Length message 04 20 01 01 00 FF FF 00 2E 27 22 =      │
  │ (loading)      │ 46:39, the whole disc. Track count: 9.                 │
  ├────────────────┼────────────────────────────────────────────────────────┤
  │ 10 s (playback │ First time message, track 1 at 0:01. A new length      │
  │  starts)       │ message at the same moment: 04 20 01 01 01 00 01 00 06 │
  │                │  16 0C = 6:22, track 1                                 │
  ├────────────────┼────────────────────────────────────────────────────────┤
  │ 10–89 s        │ Time message once per second (0:11, 0:36, 1:01,        │
  │                │ 1:19…), nothing else changes                           │
  ├────────────────┼────────────────────────────────────────────────────────┤
  │ End            │ OK 0x89, ER 0006                                       │
  └────────────────┴────────────────────────────────────────────────────────┘

  What can be concluded

  1. The length message says which track it's for. The byte the firmware ignores
     (buffer +0x93) is 00 for the whole‑disc length and 01 for track 1. The
     bytes after it also differ (FF FF vs 00 01). So the firmware's guess ("if
     no disc total yet, it's the disc total") isn't needed; the patch could read
     the message directly. That would fix quirk 3 (the disc total misread as
     the track length after switching on). It would also prevent quirk 2: a
     length that belongs to another track would simply not be used. This needs
     confirming on a track change, where the byte should read 02 for track 2.
  2. The module sends very little: about one message per second in total, almost
     all time messages. There's no "remaining" or disc‑position field in the
     first 18 bytes of the time message, which is as much as the diagnostic
     shows. Bytes 14–17 stay 00 00 FF FF.
  3. The one‑second skips are explained. 6 of about 85 messages (~7 %) failed
     the checksum and were dropped. A dropped time message means the display
     jumps 2 seconds.
  4. Quirk 1 didn't happen here. The track length arrived together with the
     first time message, so the countdown would have started almost right away.
     The 10–60 s delay you've seen probably happens when that one length message
     is among the ~7 % lost. The module then seems to send it again later, but
     I can't confirm that yet.
  5. The firmware has a command to request a length message. It's command 0x21,
     which sends class 4 / type 0x20 / 01, and the firmware sends it once after
     loading. If the module also answers it with the current track's length, the
     patch could request it at every track change and on every checksum error,
     and the countdown would never wait.

  Should you film the other cases? Yes, especially the track change (case 2) and
  switching on (case 3). But the current diagnostic has one blind spot: when a
  message repeats with identical content, nothing on screen changes, so I can't
  see whether the length message is re‑sent or how often. I'd first make a small
  change to the diagnostic build, replacing the less useful bottom line:
  - Count length messages and time messages separately, so repeats are visible.
  - Show the track length and disc total as the firmware has stored them,
    exactly what the countdown uses, so a wrong value is visible.
  - Keep the error count.

  With that, one video per case answers the open questions: whether the length
  message is re‑sent, whether the track byte reads 02 on track 2, and what
  happens after switching on.

  Want me to make that version?

❯ yes    

⏺ The updated diagnostic is ready: patch/IAP_PL100_1v1_b250219_cd_diag.hex (same
  file name, replaced). I've checked it in the emulator; it hasn't run on the
  player yet.

  What's on screen now (emulator render with test data:
  /private/tmp/claude-501/-Users-daniel-Projects-github-pl100/88cfedcb-82b1-4be2
  -85a7-f37443209b40/scratchpad/out/diag2_screen.png):

  ┌──────────┬──────────────────────────────────────────────────────────────┐
  │   Line   │                            Shows                             │
  ├──────────┼──────────────────────────────────────────────────────────────┤
  │ 1–2      │ last time message (04 21 …)                                  │
  ├──────────┼──────────────────────────────────────────────────────────────┤
  │ 3–4      │ last length message (04 20 …)                                │
  ├──────────┼──────────────────────────────────────────────────────────────┤
  │ 5–6      │ last other message from the module (e.g. 04 45, 04 24)       │
  ├──────────┼──────────────────────────────────────────────────────────────┤
  │ 7 (cyan) │ 20=xx 21=xx ER=xx: number of length messages, time messages  │
  │          │ and checksum errors (hex)                                    │
  ├──────────┼──────────────────────────────────────────────────────────────┤
  │ 8        │ TR mm:ss DI mm:ss: track length and disc total as the        │
  │ (green)  │ firmware stored them, which is what the countdown uses       │
  └──────────┴──────────────────────────────────────────────────────────────┘

  Lines 7 and 8 update with every message. If 20= goes up while lines 3–4 stay
  the same, the module has re‑sent the length message.

  A bug I caught before it reached you: my first version of the new counters
  overwrote a register. Incoming messages would have been copied to a wrong RAM
  address, which could corrupt memory on the player. The emulator showed it as
  missing hex lines. It's fixed, and the emulator now also checks that the
  diagnostic writes nothing outside its own RAM area and the stack.

  Checks:
  - The normal build is still byte‑identical to _all.hex.
  - The diagnostic file matches the emulated build.
  - Python 3.9 gives the same output.

  What to film (1080p if possible, start a few seconds before each action):
  1. Track change: let a track run out, or press Next. Keep filming until line
     8's TR shows the new track's length, however long that takes. This shows
     whether the length message arrives at the start of the new track or only
     after the module re‑sends it.
  2. Switching on: player off with a disc inside → on → Play. This shows what
     the module sends after wake‑up, and whether DI ends up in TR.
  3. Optional, case 1 again: insert a disc and press Play while it's still
     loading, the way the 10–60 s delay happened before.

  Watch ER during these. A length message lost to a checksum error is my main
  suspect for the long waits.

❯ Video in diag_02.mp4. This starts playing at track 4 and changes to track 5   

⏺ I read the video second by second; here's what happens.

  ┌─────────┬───────────────────────────────┬──────────────────────────────┐
  │ Video   │             Event             │    Length messages (20=)     │
  │  time   │                               │                              │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ 1–4 s   │ Stopped, disc loaded          │ #1: whole disc, 45:06 (byte  │
  │         │                               │ 4 = 00, track = FF)          │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ 5 s     │ Play, track 4 starts          │                              │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ 7 s     │                               │ #2: track 4, 0:32            │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ ≈28 s   │                               │ #3: track 4 again, 0:32      │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ 35–39 s │ Gap before track 5: time      │                              │
  │         │ counts down 0:03 → 0:00       │                              │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ 40 s    │ Track 5 at 0:00               │ TR still shows 0:32          │
  ├─────────┼───────────────────────────────┼──────────────────────────────┤
  │ ≈51 s   │ Track 5 at 0:11               │ #4: track 5, 1:12            │
  └─────────┴───────────────────────────────┴──────────────────────────────┘

  ER stayed at 01 throughout, so no length message was lost.

  What this tells us

  1. The module sends the track length on a timer, about every 22 s (t = 7,
     28, 51). It doesn't send it when a track starts. At the start of track 4 a
     timer tick happened to come 2 s after Play. Track 5 had to wait 11 s, plus
     the 4 s gap. That fully explains the behaviour you saw:
     - Case 2: the previous track's length is kept for up to about 22 s (here 15
       s).
     - Case 1: the same wait. Up to about 22 s normally, roughly 44 s or more if
       a tick is lost to a checksum error (about 7 % of messages are).
  2. The length message says what it describes. Byte 4 is 00 for the whole disc
     and 01 for a track, and byte 6 is the track number (FF for the disc, 04,
     05). In video 1, byte 6 was 01 for track 1 as well. The firmware ignores
     both bytes and just guesses, which is what causes case 3. The patch can
     read them and file each length correctly.
  3. Time message: byte 10 is the track and bytes 12/13/14 are min/sec/frames.
     In the gap before a track, the time counts down. There's still nothing that
     holds the remaining time or the position on the disc.

  Two ways to fix it

  - A. Correct but slow (certain to work): use bytes 4 and 6. Only use a length
    when it belongs to the current track. On a track change, show elapsed time
    without the hourglass until the right length arrives. Nothing wrong is ever
    shown, but after each track change you see elapsed time for up to about 22
    s.
  - B. Ask the module (needs one more test): the firmware has a command that
    sends [04 20 01], matching the length message. It already sends it once
    after loading, and the module then replies with the disc total. If the patch
    sends it at every track change and the module replies straight away with
    the current track's length, the countdown starts within a second. I don't
    know yet whether it answers with the track or always with the disc total.

  Next step: one more diagnostic build, v3, that sends this request whenever the
  track number changes. Film one track change. If 20= goes up within a second
  and line 3 shows the new track number, B works and I'll build the real fix
  around it. Otherwise, I'll build A.

  The test is low‑risk, because it's a command the original firmware already
  sends to the module. If you also film switching on with a disc inside (case 3)
  in the same session, that confirms point 2.

  Should I build v3?

❯ yes, build v3                                                                 

⏺ Diagnostic v3 is ready: patch/IAP_PL100_1v1_b250219_cd_diag.hex (replaced). It
  works in the emulator; it hasn't run on the player yet.

  What's new: whenever the current track number changes, including the first
  Play, it sends the module one request ([04 20 01]). That's the firmware's own
  command, which it normally only sends after loading a disc. Line 7 now reads
  20=xx 21=xx Exx Rx:
  - R counts the requests sent.
  - E is the checksum‑error count; it used to be ER=.
  - The OK count is gone; it wasn't needed any more.

  What to film:
  1. A track change, e.g. by pressing Next, or let a short track run out like in
     the last video. Start a few seconds before.
  2. Switching on with a disc inside, then Play (case 3).

  How to read the result: watch R go up, then look at the next second or two:
  - The request works: 20= also goes up and line 3 shows 04 20 01 01 01 00 <new 
    track> …. Then the fixed patch can always fetch the length straight away.
  - The module returns the disc total: 20= goes up, but line 3 shows … 00 FF FF 
    …. Then the request only returns the disc total, and I'll build the fix that
    reads the track number from each length message instead. Wrong lengths go
    away, but you'll still sometimes see elapsed time for up to ~22 s after a
    track change.
  - No answer: 20= doesn't move until the regular ~22‑second message. Same fix
    as above.

  Checks:
  - Emulator:
    - On the track sequence 0 → 4 → 4 → 5 → 5 → 5 → 1, a request is sent exactly
      at 4, 5 and 1.
    - Nothing is written outside the diagnostic's own RAM area or the stack.
  - Builds:
    - The normal build is still byte‑identical to _all.hex.
    - The flashed file matches the emulated one.
    - Python 3.9 gives the same output.

  Building it hit two limits of my small assembler: data constants have to sit
  within 1 KB of the code using them, and byte offsets can't exceed 31. The
  script now places a copy of the constants after each section. Both limits made
  the build stop with an error rather than produce wrong code.

❯ The videos are ready. Case 1 is diag_v3_01.mp4, case 2 is diag_v3_02.mp4. For 
  case 1 it plays track #4 and goes to track #5. For case 2 it starts at the    
  beginning with track #1.                                                      
  Some information about the cd, from a computer cd player. The disc contains   
  50 tracks. Track #1 is 01:02, track #4 is 00:34, track #5 is 01:14. The total 
  length is 45:07.                                                              

⏺ Both videos answer the question, and the answer is no: the request doesn't
  produce the track length.

  What happened

  Video: 1 (track 4 → 5)
  Moment: Each request (R goes up)
  Length messages: The module answers within ~1 s, but always with the disc 
  total
  (… 00 FF FF 00 2D 06 46 = 45:06). The firmware then files it as the track
  length: TR 45:06.
  ────────────────────────────────────────
  Video:
  Moment: Around 26–30 s (track 4) / 47 s (track 5, 8 s in)
  Length messages: The real track lengths 0:32 and 1:12 arrive only with the
  module's own periodic message
  ────────────────────────────────────────
  Video: 2 (switching on)
  Moment: 6 s, just after the logo
  Length messages: Disc entry with time 00 00 00 (module still starting up)
  ────────────────────────────────────────
  Video:
  Moment: 10 s
  Length messages: Disc total 45:06 → filed as the track length: TR 45:06. This
  is exactly your case 3.
  ────────────────────────────────────────
  Video:
  Moment: Track 1 plays from about 12 s; the request at that point got no answer

  at all
  Length messages:
  ────────────────────────────────────────
  Video:
  Moment: About 33–36 s, 22 s into track 1
  Length messages: First real length: track 1, 1:00

  Conclusions

  1. Asking the module doesn't help. Command 0x21 only returns the disc total,
     and the original firmware has no other command that asks for a track
     length. I could try guessing variants of the command, but I don't recommend
     sending made‑up commands to the CD module.
  2. The track length only comes with the periodic message, about every 22 s. So
     after a track starts, it takes 0–22 s before the right length is known;
     video 2 shows the worst case. This is how the module works and the patch
     can't speed it up.
  3. All three quirks come from the firmware's guesswork. Each length message
     says what it describes: byte 4 is 00 for the disc and 01 for a track, and
     byte 6 is the track number. The firmware ignores this. Using it fixes cases
     2 and 3 completely.
  4. The module's lengths are 2 s shorter than your computer's (0:32 vs 0:34,
     1:12 vs 1:14, 1:00 vs 1:02). The module counts up to the start of the 2 s
     gap before the next track, while the computer includes the gap. So the
     countdown reaches 0:00, and then the next track's gap counts down 0:02 →
     0:00 (we saw that in the video). That's correct.

  Proposed fix: replaces the current guesswork in the remaining patch
  - Disc total: filed only from messages with byte 4 = 00.
  - Track length: filed only from messages with byte 4 = 01, together with their
    track number.
  - The countdown and hourglass only appear when the stored length belongs to
    the track that's playing. Otherwise you see the normal elapsed time without
    the hourglass. So:
    - Case 1: elapsed until the length arrives (0–22 s), then the countdown with
      the hourglass. Never a wrong number.
    - Case 2: the previous track's length is never used.
    - Case 3: the disc total never ends up as the track length.
  - Optional: remember each length per track number in spare RAM. Replaying a
    track, e.g. with repeat or Previous, then counts down immediately.

  The remaining compromise is the elapsed time shown at the start of each track.
  Instead of elapsed time, it could show --:-- until the length is known. Which
  do you prefer, and should I build the fix?

❯ Then it's best to leave it as it was. If remaining time is activated, the     
  icon always shows, and at the beginning the time can be incorrect. So the     
  hourglass icon indicates the mode that is currently active, not necessarily   
  the information that is displayed on the screen.                              
  But I do need another change. I want to swap the functions of the DISP and FN 
  buttons. DISP should toggle elapsed/remaining time, and FN should change      
  brightness.                                                                   

⏺ The buttons are swapped: DISP now toggles elapsed/remaining time and FN cycles
  the brightness. The new build is patch/IAP_PL100_1v1_b250219_all_v2.hex; I
  haven't tried it on the player. Your current _all.hex is unchanged, so you can
  go back to it.

  I left the countdown and hourglass as they are, as you decided.

  What changed in build_patch.py
  - Settings: FN_IR is replaced by one setting per function, next to the other
    options:
  TIME_IR = 0x0C             # elapsed / remaining time toggle: DISP
  BRIGHT_IR = 0x08           # brightness cycle: FN
  - Remap: a new remap_buttons() builds the whole IR remap from those two
    settings. Any other button that would trigger one of the two functions is
    mapped to a do‑nothing key; this keeps MENU unused.
  - Swapping back: exchange the two values. The time and brightness code itself
    didn't change.

  Resulting mapping

  ┌────────────────┬───────────────────┬───────────────────┐
  │     Button     │ Original firmware │     New build     │
  ├────────────────┼───────────────────┼───────────────────┤
  │ MENU (IR 0x04) │ key 0x26          │ no function       │
  ├────────────────┼───────────────────┼───────────────────┤
  │ FN (IR 0x08)   │ no function       │ brightness        │
  ├────────────────┼───────────────────┼───────────────────┤
  │ DISP (IR 0x0C) │ no function       │ elapsed/remaining │
  └────────────────┴───────────────────┴───────────────────┘

  Checks
  - With the old assignment (FN = time, DISP = brightness), the script still
    produces your current _all.hex byte for byte.
  - The new build differs from _all.hex in exactly two bytes, the IR table
    entries for FN and DISP. The size is the same and the line endings are CRLF.
  - Building with only brightness or only remaining also maps the buttons
    correctly.
  - Python 3.9 gives the same output.

  Also updated: the README's feature list (FN = brightness, DISP = time toggle,
  and the hourglass shows whenever remaining‑time mode is on) and the docstring.

  Not changed: the diagnostic build (--cd-diag) still contains the
  length‑request experiment from v3. It's only built when the flag is given, so
  it doesn't affect the normal firmware. I can remove it or reset it to the v2
  behaviour if you'd like it cleaned up before you commit.

❯ Add the diagnostic build to a git branch so it is saved. Commit this with the 
  message "Diagnostic build for remaining time". Then remove the diagnostic     
  changes for the main branch. No need to commit on main just yet.              

⏺ The diagnostic build is committed on its own branch, and main now has only the
  DISP/FN swap, uncommitted.

  Branch diagnostic-remaining-time (commit 82b04f8, "Diagnostic build for
  remaining time"):
  - Contents: the diagnostic exactly as you tested it, based on the last main
    commit, without the button swap. It changes build_patch.py and thumbasm.py;
    the latter gets two extra instruction encodings the diagnostic needs.
  - Checks: this version rebuilds the _cd_diag.hex you flashed for the v3 videos
    byte for byte, and its normal build is identical to your original _all.hex.

  main (no commit):
  - Contents: README.md and build_patch.py hold only the DISP/FN swap. All
    diagnostic code and the --cd-diag option are removed, and thumbasm.py is
    back to the last commit.
  - Checks: the normal build reproduces _all_v2.hex. --cd-diag is now rejected,
    and --version still works.

  Nothing was pushed; the branch exists only locally. Copies of the files from
  before the split are in /private/tmp/claude-501/-Users-daniel-Projects-github-
  pl100/88cfedcb-82b1-4be2-85a7-f37443209b40/scratchpad/gitwork/full/. The .hex
  files in patch/ are git‑ignored, so _cd_diag.hex and _all_v2.hex stay where
  they are, outside the repo.


❯ For future changes, no need to change README.md, I'll do that myself          

⏺ Understood. From now on I'll leave README.md alone; if a change affects what
  it describes, I'll say so in my reply instead. I've saved this as a note for
  future sessions too.

  The README edit I already made for the DISP/FN swap is still uncommitted on
  main (the button descriptions in the feature list). Keep it, adjust it, or
  undo it with git checkout README.md.

❯ For the brightness change, is there anything in the existing settings menu    
  that shows a UI when the brightness is changed? It would be good to show      
  something on the screen what the brightness setting is after pressing the     
  button. If the settngs menu already has something, maybe this can be reused.  

⏺ After each FN press, line 1 (where 03/09 normally is) now shows the new
  brightness as a percentage for about 2 seconds. The build is
  patch/IAP_PL100_1v1_b250219_all_v3.hex. I tested it in the emulator; it hasn't
  run on the player yet.

  What the existing firmware had
  - Menu brightness screen: the settings menu has one ("LEVEL1"…"LEVEL9"), but
    nothing calls it. It also draws straight to the LCD the old way, and LVGL
    would immediately draw over it, so I couldn't reuse it.
  - Reused instead: the way volume is shown, a temporary value in the line‑1
    label. I didn't use volume's method of pausing the whole display update,
    because that would also freeze the time. The percentage replaces only line
    1, so the time keeps running.

  How it works
  - On a press: besides stepping the level, FN starts a counter of 250 display
    updates, about 2 seconds. Each press restarts it.
  - While the counter runs: right after each display update, a small hook puts
    the text for the current level into line 1. When the counter runs out, the
    firmware's next update shows the track number again; every path through the
    display update rewrites line 1 each time.
  - Sequence: 35 % → 55 % → 65 % → 100 % → 10 % → 20 % → 35 %, …
  - Spare RAM: two bytes of the dead settings menu's cursor (0x20000294), which
    are 0 after boot.

  Checks
  - Emulator:
    - Each press shows the right text on the line‑1 label.
    - The text is set for 249 ticks after a press, then never again, and before
      any press it's never set.
    - The firmware's own timer check still gets its original argument, and its
      result is passed back unchanged.
    - Other keys pass through, and in standby FN does nothing.
    - Nothing is written outside the brightness setting, the counter and the
      stack.
  - Build: compared with _all_v2.hex, only brightness code changed: the patch's
    code in the free flash area, the new hook (0x0800E0BC), and one call that
    points to code which moved. Python 3.9 gives the same output.

  Things to check on the device
  - Duration: the timer tick is somewhere between 7.5 and 10 ms, so the text
    shows for 1.9–2.5 s. If you want it longer or shorter, change
    BRIGHT_OSD_TICKS = 250.
  - Position: 100% is the widest text. It should fit in the space that 03/09
    uses, but tell me if it gets cut off.

  All changes are in build_patch.py and thumbasm.py (two new instruction
  encodings). Nothing is committed. The README's feature list doesn't mention
  the on‑screen percentage yet; I've left that to you.

❯ It works, but the brightness stays on the screen for around 10 seconds. Can   
  be less, like the 2.5s mentioned. So maybe something about the timing was     
  wrong?                                                                        

⏺ Yes, the timing assumption was wrong, and it's fixed. The new build is
  patch/IAP_PL100_1v1_b250219_all_v4.hex; I tested it in the emulator, not yet
  on the player.

  What was wrong: I counted display updates and assumed one per 7.5–10 ms timer
  tick. But the display update runs only once per pass of the firmware's main
  loop, and a pass takes about 40 ms, mostly the screen drawing. Ticks that
  happen in between are merged into one. So 250 updates came to about 10 s,
  which matches what you saw.

  The fix: the duration is now measured on a real clock instead of counting
  updates.
  - Clock: the timer interrupt runs every 7.5 ms (96 MHz / 72 / 10000, from the
    start‑up clock settings) and already advances a counter (0x20000560) every
    10 ticks, so every 75 ms. Nothing else writes that counter.
  - On FN press: store "end = clock + 33" (33 × 75 ms ≈ 2.5 s) and set an
    "active" flag.
  - On each display update: show the percentage until the end time is reached,
    then clear the flag so the track number comes back. The duration no longer
    depends on how fast the main loop runs.
  - Clock wrap: the counter wraps every 81 minutes. The flag stops the text from
    flashing up at that moment, and a press just before the wrap also works.

  Checks:
  - Emulator, with the clock simulated: after a press the text shows for exactly
    33 clock steps (2.475 s), with several display updates per step, and never
    after that. The flag is cleared. The same holds for a press just before the
    clock wraps. Nothing is shown at boot or at a later wrap without a press,
    and nothing is written outside the brightness setting, the timer bytes and
    the stack.
  - Build: compared with v3, only brightness code changed. The written file
    matches the emulated build, and Python 3.9 gives the same output.

  To change the duration, adjust BRIGHT_OSD_STEPS = 33 (steps of 75 ms). Nothing
  is committed.

❯ There is a small issue with "Patch 4 - Play pressed while the disc is still   
  loading is lost." when booting the player. It first shows the SMSL logo boot  
  screen, and then Load, and Read. If play is pressed during Load/Read, the     
  play icon does appear on the screen when loading is finished, but it never    
  actually starts playing. The screen just has the total disc time and the play 
  icon. That is similar to the behaviour that was previously there when         
  inserting a new disc.                                                         

⏺ This was a gap in patch 4, and it's fixed in
  patch/IAP_PL100_1v1_b250219_all_v5.hex. I tested it in the emulator; it hasn't
  run on the player yet.

  The cause
  - Standby: it doesn't just turn off the screen. It switches off the CD module
    completely, and switching on powers it up again, which is why it reloads the
    disc ("Load", "Read").
  - The MCU's memory: standby doesn't reset it. So after switching on, it still
    held the state from before: "disc ready", track count and disc total, and a
    play state of "playing" if you were playing.
  - Result: patch 4 thought the disc was ready and let Play through straight
    away. The module was still loading and ignored it, the same as the original
    bug.
  - Cold start: switching on at the mains goes through the same path. The
    firmware runs the standby routine once at start‑up.

  The fix
  On entering standby, which patch 4 already hooks, the CD state is reset:
  - Play state "stopped", tray status "Load".
  - The same disc‑info reset patch 3 does when the tray opens; I reused that
    code through a second entry point.

  After switching on, a Play press is queued exactly as after inserting a new
  disc, and it starts once the reloaded disc is ready.

  Emulator results (state as left by playing, then standby, then Play during
  Load):
  - v4: Play goes out immediately and is lost, which reproduces your bug.
  - v5: Play is queued and goes out once the module has reported TOC done, the
    track count and the disc total.
  - Patch 3: opening the tray still behaves as before.
  - Build: Python 3.9 gives the same output.

  Probably also fixed: after switching on, the countdown showed the whole disc's
  remaining time (case 3). The disc total is now stored fresh after power‑on
  instead of being taken for the track length. Please keep an eye on it; it's a
  side effect I haven't seen on the device yet.

  The change is only in build_patch.py and isn't committed.

❯ Are there any other changes or improvements to the firmware that could make   
  sense?                                                                        

⏺ Yes, several. Ordered by how useful I think they are and how much is already
  known:

  Worth doing

  1. Fix the one‑second time skips. The diagnostic showed about 7 % of CD‑module
     messages failing the checksum, so every lost time message makes the
     display jump 2 s. The MCU reads the module through software‑driven I2C with
     hard‑coded delays. Two possible fixes:
     - Cause: slow the bit timing slightly, if the failures come from marginal
       timing.
     - Symptom: if a time message is missing, advance the displayed time by one
       second itself; the next good message corrects it anyway.

     The first needs a short test with the diagnostic (count E before and
     after). The second is simple and certain to work.
  2. Show the gap between tracks as negative time. Before each track the module
     counts down 0:02/0:03 → 0:00 (we saw that in the videos), and the display
     shows it as ordinary time counting backwards. Showing -0:03 … -0:01 would
     make clear the next track hasn't started yet. It's small and low‑risk,
     since the information is already in the time message.
  3. Resume after standby. The module forgets everything when switched off. The
     patch could remember track and position at standby, and after power‑on and
     Play continue there. The firmware already has a "play from track/time"
     command (cmd 4, with track, min, sec). It needs one test of whether the
     module honours the time part. A setting could switch it off.

  Possible, with some uncertainty

  4. Screen dims after a while. The firmware has a working but switched‑off
     "Dimmer" (display timeout, setting 0x200004D5, default "Display always
     ON"). A build option could turn it on, e.g. off after 1 minute while
     stopped or paused, and on again with any key. Untested on the PL100, and
     how it interacts with the new brightness levels needs checking.
  5. Give MENU a function. It's the last unused button. Candidates:
     - Screen off / on while playing (complements 4).
     - Repeat or shuffle, if the module supports them; there's an unused shuffle
       icon in the UI. That needs finding the module command, so it's more
       investigation.
  6. Start playing automatically after loading a disc. This would be a build
     option. Patch 4's queue already does most of the work.

  Not recommended

  - Remaining time for the whole disc: the module never reports the position on
    the disc.
  - Faster countdown start: shown to be impossible; the module only sends track
    lengths every ~22 s.
  - The settings menu: half‑ported DAC code with mostly irrelevant settings.

  My suggestion: 1 and 2 first, because they fix things you see every day. Which
  ones interest you?

❯ #1 (always advance 1s when missing), #2, and #6 are nice additions to have.   
  please add them to the patch, again each with a config option to switch them  
  off                                                                           

⏺ I've added all three features, each with its own on/off setting. The build is
  patch/IAP_PL100_1v1_b250219_all_v6.hex. I tested it in the emulator only, not
  yet on the player.

  The new settings sit next to the existing ones in build_patch.py:
  TIME_FILL_ON = True        # advance the time by 1 s when a time message of 
  the CD module is lost
  PREGAP_MINUS_ON = True     # show the gap before a track as "-0.02" (needs the
  remaining patch)
  AUTOPLAY_ON = True         # start playing when a disc has loaded after the 
  tray was opened

  1. No more 2‑second jumps (new patch cdtime)
  - How it works: the patch notes when each time message from the CD module
    arrives. If it's playing and no message has come for 1.275 s, the display
    advances one second, and again every second while messages stay missing. The
    next message that arrives sets the module's own time again.
  - When it doesn't act: paused, seeking, or before the first time message after
    pressing Play.

  2. The gap before a track as negative time
  - What you see: while the module counts down to the next track, the display
    shows -0.03, -0.02, -0.01, then 00.00 when the track starts. The value is
    rounded up, so the last one is -0.01. This applies in both elapsed and
    remaining mode.
  - How a gap is recognised: the videos showed that only time messages from the
    gap carry a non‑zero "frames" byte; I also require minutes = 0. That's based
    on the two discs we filmed. If another disc behaves differently, the worst
    case is a missing or brief stray -.
  - Dependency: it's part of the time display in the remaining patch, which
    pulls in cdtime automatically.

  6. Autoplay after loading a disc
  - How it works: opening the tray arms it. When the next disc load starts, a
    Play is queued, and the existing queue from patch 4 starts playback once the
    disc is ready.
  - Power‑on: switching on from standby or at the mains doesn't autoplay; only
    opening the tray arms it.
  - Limitation: pressing Stop while the disc loads doesn't cancel the autoplay.
    A queued Play from patch 4 behaves the same way.

  Change to the structure: the brightness percentage and the time fill both need
  to run after every display update, and only one patch can hook that spot.
  That spot is now a small chain that the script builds from whichever patches
  register for it.

  Checks:
  - Emulator, all features on:
    - Lost messages at 2, 5 and 6 s are filled, so 10…18 counts up by one second
      at a time. The minute rollover (0:59 → 1:00) works.
    - Pause and "no message yet" leave the time alone, and in the gap it counts
      down.
    - The display shows 01.23 normally, 02.18 in remaining mode, and -0.03 and
      -0.01 in the gap.
    - Autoplay: tray open → close → load queues Play, and it's sent once the
      disc is ready. Power‑on doesn't.
    - Brightness still shows 55% for 2.475 s.
  - Each option off, and all off: the build and the emulator show that feature's
    old behaviour. With all three off, the time‑message code stays original.
  - Builds: selecting patches individually works, and dependencies are added
    automatically. --version works, and Python 3.9 gives the same output.
  - Not checked: the RAM‑write check covers the new code, but an allow‑list
    error in my test hid the result for the all‑on build. The four single‑option
    builds with the corrected test all came out clean.

  Worth checking on the device:
  1. Do the occasional 2‑second jumps disappear?
  2. Does the gap show as -0.0x between tracks?
  3. Does it start playing by itself after inserting a disc, but not after
     switching on?

  There's a new patch name (cdtime) and three new options, which you may want to
  mention in the README. The change is in build_patch.py only and isn't
  committed.

❯ For the negative time, this does also show occasioanlly during normal play.   
  E.g. the display has 00.09, 00:10, -0:10, 00:11.                              
  And for the auto play when inserting, one missing use case is switching on    
  the player without a disc, and then insering a disc. It doesn't start, but    
  logically I feel it should start.                                             

⏺ Both issues are fixed in patch/IAP_PL100_1v1_b250219_all_v7.hex. I've tested
  it in the emulator, not yet on the player.

  1. Stray -0:10 during normal play
  - Cause: the module sometimes sends a second message for the same second, and
    that second message carries a non‑zero frame count. My gap detection treated
    that as a gap.
  - Fix: a message only counts as gap time if it also counts down:
    - the player is playing, minutes are 0, and the frame count isn't 0;
    - and either the track number has just changed, or the seconds are lower
      than in the previous message.
    - A repeat of the same second keeps whatever state it had.
  - Emulator: your sequence 0:09, 0:10, 0:10 (with frames), 0:11 shows no -. A
    real gap before a track still shows -0.03 … -0.01, including when a second
    repeats in the gap.
  - Remaining edge case: if the first message after pressing Next happens to
    carry a frame count, -0.01 can flash for one second.

  2. Autoplay after switching on without a disc
  - Cause: the PL100 has a slot, not a tray, which I hadn't taken into account.
    "Eject" only happens when a disc is ejected, so with an empty slot at
    power‑on, autoplay was never armed.
  - Fix: an empty slot now also arms autoplay. The firmware shows that state as
    "Disc", status 3. It only counts once it has lasted a second, so a brief "no
    disc" while loading a disc that's already inside doesn't make the player
    autoplay at power‑on.
  - Emulator:
    - Switch on without a disc → after 1 s armed → insert a disc → Load/Read →
      plays once ready.
    - Switch on with a disc and a brief "no disc" → no autoplay.
    - Eject → insert the next disc → plays, as before.

  Checks:
  - Time fill: still works.
  - Each option off: gives the old behaviour.
  - Builds: the written file matches the tested build, and Python 3.9 gives the
    same output.

  Worth checking on the device:
  1. No more stray - during normal play, but still -0.0x between tracks.
  2. Switch on without a disc, insert one: it should start by itself.
  3. Switch on with a disc inside: it should not start by itself. That relies on
     the module not reporting "no disc" for a full second while loading. If it
     does autoplay, tell me and I'll make the arming stricter.

  The change is only in build_patch.py and isn't committed.

❯ Switching on with no disc and then inserting a disc doesn't start playing     
  yet.

⏺ I've changed how autoplay arms for an empty slot. The new build is
  patch/IAP_PL100_1v1_b250219_all_v8.hex, tested in the emulator only.

  The cause
  The firmware shows "Disc" for two different states. Status 3 comes from an
  ordinary status message. Status 6 is set when the module reports an error
  code, which an empty slot most likely is. v7 only armed on status 3. It also
  restarted the 1‑second wait whenever another status came in between, which
  also fails if the module keeps retrying with an empty slot.

  The fix: new arming rule
  - Start: the first "Disc" (status 3 or 6) starts the timer.
  - Arm: a "Disc" at least 1 second later arms autoplay. "Load" or "Read" in
    between, from retries, doesn't reset the timer.
  - Cancel: if a disc becomes ready while the timer is running, autoplay isn't
    armed. That's the case when you switch on with a disc inside and "Disc" only
    flashes briefly.
  - Eject: still arms immediately, as before.

  Emulator results

  ┌──────────────────────────────────────┬──────────────────────────────────┐
  │               Scenario               │              Result              │
  ├──────────────────────────────────────┼──────────────────────────────────┤
  │ Switched on, empty slot (status 6),  │ armed after 1.3 s, Play queued   │
  │ disc inserted 5 s later              │ at Load, plays once ready        │
  ├──────────────────────────────────────┼──────────────────────────────────┤
  │ Empty slot with retries (Disc/Load   │ armed, plays                     │
  │ alternating)                         │                                  │
  ├──────────────────────────────────────┼──────────────────────────────────┤
  │ Empty slot reported as status 3      │ armed, plays                     │
  ├──────────────────────────────────────┼──────────────────────────────────┤
  │ Switched on with a disc, brief       │ no autoplay                      │
  │ "Disc" while loading                 │                                  │
  ├──────────────────────────────────────┼──────────────────────────────────┤
  │ Eject → insert the next disc         │ plays                            │
  ├──────────────────────────────────────┼──────────────────────────────────┤
  │ Autoplay switched off                │ never queues                     │
  └──────────────────────────────────────┴──────────────────────────────────┘

  The gap detection and time fill behave as before, and Python 3.9 gives the
  same output.

  One limit to watch: if the module shows "Disc" twice, more than a second
  apart, while loading a disc that's already inside, the player would autoplay
  at power‑on. If you see that, tell me. The fix would then be to only arm after
  "Disc" has lasted longer, or to arm only when no disc was present at
  power‑on.

  To test on the device:
  1. Switch on without a disc, wait until "Disc" shows, insert a disc. It should
     start by itself.
  2. Switch on with a disc inside. It should not start by itself.

  The change is only in build_patch.py and isn't committed.

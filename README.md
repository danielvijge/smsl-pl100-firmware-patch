# Patched firmware for the SMSL PL100 CD player

This repository contains patched firmware for the SMSL PL100 CD player.
It adds the following fixes and enhancements:

**Enhancements:**
1. Instead of `Tr03` display `03/09`, where `09` is the total number of tracks on the CD.
2. Option to change the brightness of the display using six settings using the remote's DISP button.
3. Toggle between elapsed time and remaining time of a track using the remote's FN button. When displaying remaining time it displays an hourglass icon. (If you don't like the icon, it can be toggled off in the python script.)

**Bug fixes:**
1. When the device is in standby the display is fully off instead of the lowest standby.
2. Always display the correct time of the disc when inserting it. Sometimes it would display the time of the previous disc.
3. Pressing play while the disc is still loading queues the play action. Previously it would just hang and do nothing.

## Original firmware

All patches are based on firmware version 1.1 that was [shared by forum user _minuscule_ on the Audio Science Review forum](https://www.audiosciencereview.com/forum/index.php?threads/smsl-vmv-pl100-cd-player-%C2%A3110.59679/post-2255348).
A firmware version was never officially posted by SMSL on their website. But this version works and updates the firmware
from the default 1.0 to 1.1. It's not known what things 1.1 fixes compared to 1.0.
The original firmware is added to this repository as [IAP_PL100_1v1_b250219.hex](IAP_PL100_1v1_b250219.hex).

## Patching the original firmware

⚠ All patches are written by AI (Claude Opus 5.5). It has been tested but the code is not reviewed.

With the help of AI the original firmware was analysed. AI then patched the firmware based on the instructions.
Instead of directly patching the firmware it produced a python script to patch the firmware. This allows anyone
to patch the original firmware using the python script. It also allows to easily disable some of the patches
if you don't want them.

All relevant prompts and answers of the chat session used to produce these patches are available in
[claude-pl100-patch-chat.md](claude-pl100-patch-chat.md).

## Building your own firmware, selecting which patches to use

It is possible to only apply some patches to the original firmware if you do not want all patches.
Clone this repository and run:

```
build_patch.py [--version VERSION] <original.hex> <patched.hex> [patch,...]
```

Options for patches are: track, backlight, disctime, play, remaining, brightness. When nothing is
specified, all patches are applied.

Optionally a version can be supplied. When supplied this version is shown on the splash screen during
boot, below the SMSL logo and "Ver 1.1". When omitted the splash screen remains unchanged.

## Preparation before flashing

To flash the firmware you need a Windows PC and a good USB-C cable. At least the connector that goes into
the CD player needs to be USB-C, the end that connects to your PC can be anything. I tried different USB
cable and only quality ones work correctly. Lesser quality can power the CD player, but the PC will not
connect to the player.

Before flashing your CD player can be at version 1.0 or 1.1. It should not be needed to first flash the original
version 1.1. The version installed is shown when powering on the player, below the SMSL logo.

## Steps to flash the patched firmware

⚠ Flash firmware at your own risk. In my testing it was all safe. The firmware itself does not contain the code
to flash the firmware, this is on a different chip. So even if flashing fails you should always be able to flash
the original firmware again. However, do understand that this is not a guarantee. You accept the risk by flashing
this patched firmware.

1. Download the firmware from the [release page](https://github.com/danielvijge/smsl-pl100-firmware-patch/releases).
2. Download the [flash utility from SMSL](https://www.smsl-audio.com/upload/portal/undefined/SMSLPL200MCUFW24126.zip). This is the firmware for a different CD player (PL200), but we only need the flash utility contained in the zip file.
3. Open the zip file. Inside is another zip file named _ISP_PC_EN2.zip_. All these files are needed, so extract them somewhere. There is no need to actually install the program.
4. Open the program  _ispV2.4.exe_.
5. Ensure the following settings:
   * `SelfIncreaseAddress`: `08010000`
   * `Device`: `IAP`
   * `SelfIncreaseID`: `00000084`
   * `Baudrate`: `115200`
   * `Run_Prog`: selected, all other checkboxes should not be selected
6. Click the menu _File > Open_ and select the patched firmware downloaded in step 1. It can take a while (30s - 2 minutes)
   to load the firmware. Once the fields for `Code Address`, `Code Size`, and `CheckSum` change from 0 to actual values the
   firmware is loaded.
7. With the CD player off, press and hold the Stop/Eject button, connect the USB cable and keep holding the button for 5-10
   seconds. Nothing appears to happen; the screen doesn't turn on. This is normal.
8. Click the menu _Options > Connect_. Now on the bottom left the text `Disconnect` should change into `Connected`.
9. Click the `Start Program` button. Flashing should take 1-2 minutes. Once it reaches 100% the player should start normally.

## Licence

The original firmware [IAP_PL100_1v1_b250219.hex](IAP_PL100_1v1_b250219.hex) owned by SMSL and does not fall under any open source licence.
All other files are licensed under the MIT License. See [LICENSE-MIT](LICENSE-MIT).

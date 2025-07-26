# A small script to help flash MEC1633/MEC1663 with OpenOCD

This was done as a very quick hack to fix my Thinkpad x250. The 'proper' way of doing things would be to fork OpenOCD and write a proper driver for this.

You have to find an OpenOCD capable of communicating with MEC1633. [This](https://gist.github.com/four0four/680e1fa70e7c216baac2afbd459d03d8) gist might help you.

The interface (adapter) could be any which OpenOCD supports. I used FT2232 mini module which is perhaps the most common USB->JTAG tool.

Guts of this logic were taken from Glasgow Interface Explorer which support older MEC1618. Interface seem to be exactly the same, though.

WARNING: I used that tool, like, twice, and it was written in a rush over my dead laptop. Please be aware that it's not great.

## Flashing MEC1663 (added by [@tearandfix](https://github.com/tearandfix))

The original script is located [here](https://github.com/dossalab/mec16xx-simple-flash).
I've added missing EEPROM functions based on [glasgow applet implementation](https://github.com/GlasgowEmbedded/glasgow/blob/main/software/glasgow/applet/program/mec16xx/__init__.py).
To flash MEC1663 I used up-to-date OpenOCD with Raspberry PI 4.

Raspberry PI wiring:
```
pin 23, GPIO_11 -> TCK
pin 24, GPIO_8  -> TMS
pin 19, GPIO_10 -> TDI
pin 21, GPIO_9  -> TDO
```

OpenOCD configuration, init.cfg:
```
adapter_khz 1000
source [find cpu/arc/v2.tcl]

transport select jtag

set _CHIPNAME arcv2
set _TARGETNAME $_CHIPNAME.cpu

jtag newtap $_CHIPNAME cpu -irlen 4 -ircapture 0x1 -expected-id 0x200024b1

target create $_TARGETNAME arcv2 -chain-position $_TARGETNAME
arc_v2_init_regs
```

OpenOCD command:
```
openocd -f interface/raspberrypi-native.cfg -f init.cfg
```

All this thing works pretty unreliably. Sometimes I had to restart the board after OpenOCD initialized to get it to work.
But in the end I was able to program the flash and EEPROM of MEC1663 in my Thinkpad T14 gen1.
Thanks [@dossalab](https://github.com/dossalab) for the original work!

## A small script to help flash MEC1633 with OpenOCD

This was done as a very quick hack to fix my Thinkpad x250. The 'proper' way of doing things would be to fork OpenOCD and write a proper driver for this.

You have to find an OpenOCD capable of communicating with MEC1633. [This](https://gist.github.com/four0four/680e1fa70e7c216baac2afbd459d03d8) gist might help you.

The interface (adapter) could be any which OpenOCD supports. I used FT2232 mini module which is perhaps the most common USB->JTAG tool.

Guts of this logic were taken from Glasgow Interface Explorer which support older MEC1618. Interface seem to be exactly the same, though.

WARNING: I used that tool, like, twice, and it was written in a rush over my dead laptop. Please be aware that it's not great.

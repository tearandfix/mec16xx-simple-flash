#!/usr/bin/env python3

# Based on Glasgow applet

# Ref: Microchip MEC1618 Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Accession: G00005
# Ref: Microchip MEC1609 Mixed Signal Mobile Embedded Flash ARC EC BC-Link/VLPC Base Component
# Document Number: DS00002485A
# Accession: G00006

import logging as log
import argparse
import struct
from telnetlib import Telnet
from stuff import bitstruct
import time
from OpenOCD import OpenOCD

oocd = OpenOCD()
oocd.Halt()

FIRMWARE_SIZE = 0x30_000

Flash_Config = bitstruct.bitstruct("Flash_Config", 32, [
    ("Reg_Ctl_En",      1),
    ("Host_Ctl",        1),
    ("Boot_Lock",       1),
    ("Boot_Protect_En", 1),
    ("Data_Protect",    1),
    ("Inhibit_JTAG",    1),
    (None,              2),
    ("EEPROM_Access",   1),
    ("EEPROM_Protect",  1),
    ("EEPROM_Force_Block", 1),
    (None,             21),
])

Flash_Command = bitstruct.bitstruct("Flash_Command", 32, [
    ("Flash_Mode",  2),
    ("Burst",       1),
    ("EC_Int",      1),
    (None,          4),
    ("Reg_Ctl",     1),
    (None,         23),
])

Flash_Status = bitstruct.bitstruct("Flash_Status", 32, [
    ("Busy",            1),
    ("Data_Full",       1),
    ("Address_Full",    1),
    ("Boot_Lock",       1),
    (None,              1),
    ("Boot_Block",      1),
    ("Data_Block",      1),
    ("EEPROM_Block",    1),
    ("Busy_Err",        1),
    ("CMD_Err",         1),
    ("Protect_Err",     1),
    (None,             21),
])

Flash_Mode_Standby  = 0
Flash_Mode_Read     = 1
Flash_Mode_Program  = 2
Flash_Mode_Erase    = 3
Flash_base_addr     = 0xff_3800

Flash_Mbx_Index_addr = Flash_base_addr + 0x00
Flash_Mbx_Data_addr  = Flash_base_addr + 0x04

Flash_Data_addr     = Flash_base_addr + 0x100
Flash_Address_addr  = Flash_base_addr + 0x104
Flash_Command_addr  = Flash_base_addr + 0x108
Flash_Status_addr   = Flash_base_addr + 0x10c
Flash_Config_addr   = Flash_base_addr + 0x110
Flash_Init_addr     = Flash_base_addr + 0x114

def read_reg(addr, space):
    log.info(f'reading from {hex(addr)}')
    return oocd.ReadMem32(addr)

def write_reg(addr, data, space, words=False):
    log.info(f'writing word to {hex(addr)} value {hex(data)}')
    oocd.WriteMem32(addr, data)

def enable_flash_access(enabled):
    # Enable access to Reg_Ctl bit.
    flash_config = Flash_Config(Reg_Ctl_En=enabled)
    log.info("write Flash_Config %s", flash_config.bits_repr(omit_zero=True))
    write_reg(Flash_Config_addr, flash_config.to_int(), space="memory")

    if not enabled:
        # Clearing Reg_Ctl_En automatically clears Reg_Ctl.
        return

    # Enable access to Flash controller registers. Also, bring Flash controller to standby
    # mode if it wasn't already in it, since otherwise it will refuse commands.
    flash_command = Flash_Command(Reg_Ctl=1, Flash_Mode=Flash_Mode_Standby)
    log.info("(stby) write Flash_Command %s", flash_command.bits_repr(omit_zero=True))

    write_reg(Flash_Command_addr, flash_command.to_int(), space="memory")

    # Clear Flash controller error status.

    # this does weird stuff
    flash_clear_status = Flash_Status(Busy_Err=1, CMD_Err=1, Protect_Err=1)
    log.info("clear Flash_Status %s", flash_clear_status.bits_repr(omit_zero=True))

    write_reg(Flash_Status_addr, flash_clear_status.to_int(), space="memory")

def send_flash_command(mode, address=0, burst=False):
    flash_command = Flash_Command(Reg_Ctl=1, Flash_Mode=mode, Burst=burst)
    log.info("write Flash_Command %s", flash_command.bits_repr(omit_zero=True))

    write_reg(Flash_Command_addr, flash_command.to_int(), space="memory")

    log.info("write Flash_Address=%08x", address)
    write_reg(Flash_Address_addr, address, space="memory")

    flash_status = Flash_Status(Busy=1)
    while flash_status.Busy:
        flash_status = Flash_Status.from_int(
            read_reg(Flash_Status_addr, space="memory"))
        log.info("read Flash_Status %s", flash_status.bits_repr(omit_zero=True))

        if flash_status.Busy_Err or flash_status.CMD_Err or flash_status.Protect_Err:
            raise Exception("Flash command %s failed with status %s"
                               % (flash_command.bits_repr(omit_zero=True),
                                  flash_status.bits_repr(omit_zero=True)))

def read_flash(address, count):
    words = []
    for offset in range(count):
        send_flash_command(mode=Flash_Mode_Read, address=address + offset * 4)
        data_1 = read_reg(Flash_Data_addr, space="memory")
        log.info("read Flash_Address=%05x Flash_Data=%08x",
                  address + offset * 4, data_1)

        # This is hella cursed. In theory, we should be able to just enable Burst in
        # Flash_Command and do a long series of reads from Flash_Data. However, sometimes
        # we silently get zeroes back for no discernible reason. Since data never gets
        # corrupted during programming, the most likely explanation is a silicon bug where
        # the debug interface is not correctly waiting for the Flash memory to acknowledge
        # the read.
        write_reg(Flash_Address_addr, address + offset * 4, space="memory")
        data_2 = read_reg(Flash_Data_addr, space="memory")
        log.info("read Flash_Address=%05x Flash_Data=%08x",
                  address + offset * 4, data_2)

        if data_1 == data_2:
            data = data_1
        else:
            # Third time's the charm.
            write_reg(Flash_Address_addr, address + offset * 4, space="memory")
            data_3 = read_reg(Flash_Data_addr, space="memory")
            log.info("read Flash_Address=%05x Flash_Data=%08x",
                      address + offset * 4, data_3)

            log.warning("read glitch Flash_Address=%05x Flash_Data=%08x/%08x/%08x",
                              address + offset * 4, data_1, data_2, data_3)

            if data_1 == data_2:
                data = data_1
            elif data_2 == data_3:
                data = data_2
            elif data_1 == data_3:
                data = data_3
            else:
                raise MEC16xxError("cannot select a read by majority")

        words.append(data)
    return words

def erase_flash(address=0b11111 << 19):
    send_flash_command(mode=Flash_Mode_Erase, address=address)

def program_flash(address, words):
    send_flash_command(mode=Flash_Mode_Program, address=address, burst=1)

    for offset, data in enumerate(words):
        write_reg(Flash_Data_addr, data, space="memory")
        log.debug("program Flash_Address=%05x Flash_Data=%08x", address + offset * 4, data)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--erase', action='store_true')

    return parser.parse_args()

def main():
    log.basicConfig(level=log.INFO)
    args = parse_args()

    if args.read:
        enable_flash_access(enabled=True)
        words = read_flash(0, FIRMWARE_SIZE // 4)
        enable_flash_access(enabled=False)

        with open(args.filename, 'wb') as file:
            for word in words:
                file.write(struct.pack("<L", word))

    if args.write:
        words = []

        with open(args.filename, 'rb') as file:
            for _ in range(FIRMWARE_SIZE // 4):
                word, = struct.unpack("<L", file.read(4))
                words.append(word)

        enable_flash_access(enabled=True)
        # erase_flash()
        program_flash(0, words)
        enable_flash_access(enabled=False)

if __name__ == '__main__':
    main()

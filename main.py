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

FIRMWARE_SIZE = 0x40_000        # for MEC1663
#FIRMWARE_SIZE = 0x30_000       # for MEC1633
EEPROM_SIZE = 2048

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


EEPROM_base_addr    = 0xf0_2c00

EEPROM_Data_addr = EEPROM_base_addr + 0x00
EEPROM_Address_addr = EEPROM_base_addr + 0x04
EEPROM_Command_addr = EEPROM_base_addr + 0x08
EEPROM_Status_addr = EEPROM_base_addr + 0x0c
EEPROM_Configuration_addr = EEPROM_base_addr + 0x10
EEPROM_Unlock_addr = EEPROM_base_addr + 0x20

EEPROM_Command = bitstruct.bitstruct("EEPROM_Command", 32, [
    ("EEPROM_Mode", 2),
    ("Burst",       1),
    (None,         29),
])

EEPROM_Status = bitstruct.bitstruct("EEPROM_Status", 32, [
    ("Busy",            1),
    ("Data_Full",       1),
    ("Address_Full",    1),
    (None,              4),
    ("EEPROM_Block",    1),
    ("Busy_Err",        1),
    ("CMD_Err",         1),
    (None,             22),
])

EEPROM_Mode_Standby  = 0
EEPROM_Mode_Read     = 1
EEPROM_Mode_Program  = 2
EEPROM_Mode_Erase    = 3

class MEC16xxError(Exception):
    pass

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
    send_flash_command(mode=Flash_Mode_Program, address=address, burst=True)

    for offset, data in enumerate(words):
        write_reg(Flash_Data_addr, data, space="memory")
        log.debug("program Flash_Address=%05x Flash_Data=%08x", address + offset * 4, data)

def is_eeprom_blocked():
    eeprom_status = EEPROM_Status.from_int(read_reg(EEPROM_Status_addr, space="memory"))
    return eeprom_status.EEPROM_Block

def eeprom_clean_start():
    if is_eeprom_blocked():
        raise MEC16xxError(f"Error: EEPROM is blocked, no EEPROM operations are possible.")
    eeprom_command = EEPROM_Command(EEPROM_Mode=EEPROM_Mode_Standby)
    log.debug("write EEPROM_Command %s", eeprom_command.bits_repr(omit_zero=True))
    write_reg(EEPROM_Command_addr, eeprom_command.to_int(), space="memory")

    # Clear EEPROM controller error status.
    eeprom_clear_status = EEPROM_Status(Busy_Err=1, CMD_Err=1)
    log.debug("clear EEPROM_Status %s", eeprom_clear_status.bits_repr(omit_zero=True))
    write_reg(EEPROM_Status_addr, eeprom_clear_status.to_int(), space="memory")

def eeprom_wait_for_not_busy(fail_msg="Failure detected"):
    eeprom_status = EEPROM_Status(Busy=1)
    while eeprom_status.Busy:
        eeprom_status = EEPROM_Status.from_int(read_reg(EEPROM_Status_addr, space="memory"))
        log.debug("read EEPROM_Status %s", eeprom_status.bits_repr(omit_zero=True))

        if eeprom_status.Busy_Err or eeprom_status.CMD_Err:
            raise MEC16xxError("%s with status %s"
                                % (fail_msg,
                                    eeprom_status.bits_repr(omit_zero=True)))
    
def eeprom_command(mode, address=0, burst=False):
    eeprom_command = EEPROM_Command(EEPROM_Mode=mode, Burst=burst)
    log.debug("write EEPROM_Command %s", eeprom_command.bits_repr(omit_zero=True))
    write_reg(EEPROM_Command_addr, eeprom_command.to_int(), space="memory")

    if mode != EEPROM_Mode_Standby:
        log.debug("write EEPROM_Address=%08x", address)
        write_reg(EEPROM_Address_addr, address, space="memory")

    eeprom_wait_for_not_busy(f"EEPROM command {eeprom_command.bits_repr(omit_zero=True)} failed")

def read_eeprom(address=0, count=EEPROM_SIZE):
    """Read all of the embedded 2KiB eeprom.

    Arguments:
    address -- byte address of first eeprom address
    count -- number of bytes to read
    """
    eeprom_clean_start()
    eeprom_command(EEPROM_Mode_Read, address = address, burst=True)
    bytes = []
    for offset in range(count):
        data = read_reg(EEPROM_Data_addr, space="memory")
        log.debug("read address=%05x EEPROM_Data=%08x",
                    address + offset, data)
        bytes.append(data)
    eeprom_command(mode=EEPROM_Mode_Standby)
    return bytes

def erase_eeprom(address=0b11111 << 11):
    """Erase all or part of the embedded 2KiB eeprom.

    Arguments:
    address -- The default value of 0b11111 << 11 is a magic number that erases
                the entire EEPROM. Otherwise one can specify the byte address of
                a 8-byte page. The lower 3 bits must always be zero.
    """
    eeprom_clean_start()
    eeprom_command(mode=EEPROM_Mode_Erase, address=address)
    eeprom_command(mode=EEPROM_Mode_Standby)

def eeprom_wait_for_data_not_full(fail_msg="Failure detected"):
    eeprom_status = EEPROM_Status(Data_Full=1)
    while eeprom_status.Data_Full:
        eeprom_status = EEPROM_Status.from_int(
            read_reg(EEPROM_Status_addr, space="memory"))
        log.debug("read EEPROM_Status %s", eeprom_status.bits_repr(omit_zero=True))

        if eeprom_status.Busy_Err or eeprom_status.CMD_Err:
            raise MEC16xxError("%s with status %s"
                                % (fail_msg,
                                    eeprom_status.bits_repr(omit_zero=True)))

def program_eeprom(address, bytes):
    """ Program eeprom.

    Assumes that the area has already been erased.
    """
    eeprom_clean_start()
    eeprom_command(mode=EEPROM_Mode_Program, address=address, burst=True)
    for offset, data in enumerate(bytes):
        eeprom_wait_for_data_not_full()
        write_reg(EEPROM_Data_addr, data, space="memory")
        log.debug("program EEPROM_Address=%05x EEPROM_Data=%08x", address + offset * 4, data)
    eeprom_wait_for_not_busy()
    eeprom_command(mode=EEPROM_Mode_Standby)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--erase', action='store_true')
    parser.add_argument('--read-eeprom', action='store_true')
    parser.add_argument('--write-eeprom', action='store_true')
    parser.add_argument('--erase-eeprom', action='store_true')

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
    elif args.read_eeprom:
        data = bytes(read_eeprom(0))
        with open(args.filename, 'wb') as file:
            file.write(data)
    elif args.erase_eeprom:
        erase_eeprom()
    elif args.write_eeprom:
        with open(args.filename, 'rb') as file:
            data = file.read()
            if len(data) != EEPROM_SIZE:
                raise MEC16xxError(f"Error: given eeprom file size ({len(data)} bytes) is different from the physical EEPROM size ({EEPROM_SIZE} bytes)")
            erase_eeprom()
            program_eeprom(0, data)
    elif args.write:
        words = []

        with open(args.filename, 'rb') as file:
            for _ in range(FIRMWARE_SIZE // 4):
                word, = struct.unpack("<L", file.read(4))
                words.append(word)

        enable_flash_access(enabled=True)
        #erase_flash()
        program_flash(0, words)
        enable_flash_access(enabled=False)

if __name__ == '__main__':
    main()

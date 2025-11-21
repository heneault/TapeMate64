#!/usr/bin/env python3
# ===================================================================================
# Project:   TapeMate64 - Python Script for Command Line Interface - Flash Firmware
# Version:   v1.0
# Year:      2025
# Author:    Yannick Heneault (Based on work of Stefan Wagner)
# Github:    https://github.com/heneault/TapeMate64
# License:   http://creativecommons.org/licenses/by-sa/3.0/
# ===================================================================================
#
# Description:
# ------------
# Flashes firmware for the TapeMate64 adapter.
#
# Operating Instructions:
# -----------------------
# - Connect the adapter to a USB port of your PC
# - Execute this script: python flash-firmware.py


import sys
from intelhex import IntelHex
from intelhex import AddressOverlapError, HexRecordError

from libs.arduinobootloader import ArduinoBootloader

# Firmware file
FIRMWARE_HEX   = 'libs/firmware.hex'

# ===================================================================================
# Error Class - Raise an Error
# ===================================================================================

class PrgError(Exception):
    def __init__(self, msg='Something went wrong'):
        super(PrgError, self).__init__(msg)
        sys.stderr.write('ERROR: ' + msg + '\n')
        sys.exit(1)

# Print Header
print('')
print('-------------------------------------------------------------')
print('TapeMate64 - Python Command Line Interface v1.0')
print('(C) 2025 by Yannick Heneault - github.com/heneault/TapeMate64')
print('-------------------------------------------------------------')


# Establish serial connection
ab = ArduinoBootloader()
prg = ab.select_programmer("Stk500v1")
if not prg.open():
    raise PrgError('Device not found')

# Enter progmode
print('Entering programming mode ...')
if not prg.board_request():
    prg.close()
    raise PrgError("Error with board request")

if not prg.cpu_signature():
    prg.close()
    raise PrgError("Unknown or unsupported device!")

# Reading firmware file
ih = IntelHex()

try:
    ih.fromfile(FIRMWARE_HEX, format='hex')
except FileNotFoundError:
    prg.close()
    raise PrgError("file not found")
except (AddressOverlapError, HexRecordError):
    prg.close()
    raise PrgError("file format not supported")

# Flash firmware
print('Flashing firmware ...')

try:
    for address in range(0, ih.maxaddr(), ab.cpu_page_size):
        buffer = ih.tobinarray(start=address, size=ab.cpu_page_size)
        if not prg.write_memory(buffer, address):
            raise PrgError('Write error')
except:
    prg.leave_bootloader()
    prg.close()
    raise PrgError('Failed to flash firmware')

# Finish all up
prg.leave_bootloader()
prg.close()
print('Done.')

print('')

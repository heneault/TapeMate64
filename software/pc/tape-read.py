#!/usr/bin/env python3
# ===================================================================================
# Project:   TapeMate64 - Python Script for Command Line Interface - READ
# Version:   v1.0.1
# Year:      2025,2026
# Author:    Yannick Heneault (Based on work of Stefan Wagner)
# Github:    https://github.com/heneault/TapeMate64
# License:   http://creativecommons.org/licenses/by-sa/3.0/
# ===================================================================================
#
# Description:
# ------------
# TapeMate64 is a simple and inexpensive adapter that can interface a Commodore
# Datasette to your computer via USB in order to read from or write to tapes.
# This script reads a tape image from Datasette to TAP file.
##
# Operating Instructions:
# -----------------------
# - Connect your TapeMate64 to your Commodore Datasette
# - Connect your TapeMate64 to a USB port of your PC
# - Execute this script: python tape-read.py outputfile.tap
# - Press PLAY on your Datasette when prompted
# - The dumping is done fully automatically. It stops when the end of the cassette
#   is reached, when there are no more signals on the tape for a certain time or
#   when the STOP button on the Datasette is pressed.


import sys
import time
from libs.adapter import *
from libs.util import crc16_update

# Print Header
print('')
print('-------------------------------------------------------------')
print('TapeMate64 - Python Command Line Interface v1.0.1')
print('(C) 2025 by Yannick Heneault - github.com/heneault/TapeMate64')
print('-------------------------------------------------------------')

# Get and check command line arguments
try:
    fileName = sys.argv[1]
except:
    raise AdpError('Missing output file name')

# Establish serial connection
print('Connecting to TapeMate64 ...')
tapemate = Adapter()
if not tapemate.is_open:
    raise AdpError('Adapter not found')
print('Device found on port', tapemate.port)
print('Firmware version:', tapemate.getversion())


# Open output file
print('Opening', fileName, 'for writing ...')
try:
    f = open(fileName, 'wb')
except:
    tapemate.close()
    raise AdpError('Failed to open ' + fileName)


# Write TAP file header
f.write(b'C64-TAPE-RAW\x01\x00\x00\x00\x00\x00\x00\x00')


# Send read command to TapeMate64 and wait for PLAY pressed
print('PRESS PLAY ON TAPE')
data = None
tapemate.sendcommand(CMD_READTAPE)
while 1:
    data = tapemate.read(1)
    if data:
        break
    sys.stdout.write('#')
    sys.stdout.flush()

print('\r', ' ' * 50, end='\r')
if data[0] > 0:
    f.close()
    tapemate.close()
    raise AdpError('Timeout waiting for PLAY')

print('OK')
print('Searching ...')


# Receive data from TapeMate64 and write to output file
count     = 0
fsize     = 0
checksum  = 0xFFFF
taptime   = 0
startflag = 0
starttime = time.time()
msgtime   = time.time()

clk_adjust = 985248.0 / 1000000

while 1:
    data = tapemate.read(3)
    if data:
        dataval = int.from_bytes(data, byteorder='little')
        if dataval == 0:
            break

        dataval = int(dataval * clk_adjust + 0.5)
        if dataval > 0xFFFFFF:
            dataval = 0xFFFFFF

        if startflag == 0 and dataval > int(32 * 8 * clk_adjust + 0.5) and dataval < int(64 * 8 * clk_adjust + 0.5):
            print('Loading ...')
            startflag = 1
        if startflag == 1:
            if dataval > int(255 * 8 * clk_adjust + 0.5):
                f.write(b'\x00')
                f.write((dataval).to_bytes(3, byteorder='little'))
                fsize += 4
            else:
                f.write((dataval>>3).to_bytes(1, byteorder='little'))
                fsize += 1
            count += 1
            if time.time() - msgtime > 0.5:
                sys.stdout.write('\rPulses: ' + str(count))
                msgtime = time.time()
            taptime += dataval
        checksum = crc16_update(checksum, data[0])
        checksum = crc16_update(checksum, data[1])
        checksum = crc16_update(checksum, data[2])

duration = round(time.time() - starttime)
taptime  = taptime // 985248 + 1

f.seek(16)
f.write(fsize.to_bytes(4, byteorder='little'))
testsum  = int.from_bytes(tapemate.read(2), byteorder='little')
overflow = tapemate.read(1)[0]
print(' ' * 50, end='\r')


# Close output file and serial connection
f.close()
tapemate.close()


# Validate data and checksum, print infos, exit
if count == 0:
    raise AdpError('Timeout waiting for pulses')

print('Dumping finished')
print('---------------------------------------------------------')
print('Total pulses:      ', count)
print('Total TAP time:    ', taptime//60, 'min', taptime%60, 'sec')
print('Transfer duration: ', duration//60, 'min', duration%60, 'sec')

errors = 0
if overflow == 0:
    print('Buffer status:     ', 'OK')
else:
    print('Buffer status:     ', 'OVERFLOW ERROR')
    errors = 1
if checksum == testsum:
    print('Checksum:          ', 'OK')
else:
    print('Checksum:          ', 'MISMATCH ERROR')
    errors = 1

print('---------------------------------------------------------')

if errors > 0:
    raise AdpError('Dumping failed')

print('Dumping successful')
print('')
sys.exit(0)

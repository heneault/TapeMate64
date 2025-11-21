#!/usr/bin/env python3
# ===================================================================================
# Project:   TapeMate64 - Python Script for Command Line Interface - WRITE
# Version:   v1.0
# Year:      2025
# Author:    Yannick Heneault (Based on work of Stefan Wagner)
# Github:    https://github.com/heneault/TapeMate64
# License:   http://creativecommons.org/licenses/by-sa/3.0/
# ===================================================================================
#
# Description:
# ------------
# TapeMate64 is a simple and inexpensive adapter that can interface a Commodore
# Datasette to your computer via USB in order to read from or write to tapes.
# This script writes a TAP image to Datasette tape.
#
# Operating Instructions:
# -----------------------
# - Connect your TapeMate64 to your Commodore Datasette
# - Connect your TapeMate64 to a USB port of your PC
# - Execute this script: python tape-write.py inputfile.tap
# - Press RECORD & PLAY on your Datasette when prompted
# - The writing is done fully automatically. It stops when the file is recorded,
#   the end of the cassette is reached or when the STOP button on the Datasette
#   is pressed.


import sys
import os
from libs.adapter import *
from libs.util import crc16_update

# ===================================================================================
# Progress bar
# ===================================================================================

def progress(percent=0, width=50):
    left = width * percent // 100
    right = width - left
    sys.stdout.write('\r[' + '#' * left + '-' * right + '] ' + str(percent) + '%')
    sys.stdout.flush()


# ===================================================================================
# Main Function
# ===================================================================================

# Print Header
print('')
print('-------------------------------------------------------------')
print('TapeMate64 - Python Command Line Interface v1.0')
print('(C) 2025 by Yannick Heneault - github.com/heneault/TapeMate64')
print('-------------------------------------------------------------')


# Get and check command line arguments
try:
    fileName = sys.argv[1]
except:
    raise AdpError('Missing input file name')

# Establish serial connection
print('Connecting to TapeMate64 ...')
tapemate = Adapter()
if not tapemate.is_open:
    raise AdpError('Adapter not found')
print('Device found on port', tapemate.port)
print('Firmware version:', tapemate.getversion())


# Open input file
print('Opening', fileName, 'for reading ...')
try:
    fileSize = os.stat(fileName).st_size
    f = open(fileName, 'rb')
except:
    raise AdpError('Failed to open ' + fileName)


# Check file header
if fileSize < 20 or not f.read(12) == b'C64-TAPE-RAW':
    tapemate.close()
    f.close()
    raise AdpError('Wrong file header')


# Check TAP version
tapversion = f.read(1)[0]
if tapversion > 1:
    tapemate.close()
    f.close()
    raise AdpError('Unsupported TAP version')


# Check size of data area
f.seek(16)
datasize = int.from_bytes(f.read(4), byteorder='little')
if not (datasize + 20) == fileSize:
    tapemate.close()
    f.close()
    raise AdpError('File size does not match header entry')


# Print TAP file information
print('File header: OK')
print('File size:   OK')
print('TAP version:', tapversion)


# Preparing data and store it in temp file
print('Preparing data ...')

try:
    t = open('tapemate.tmp', 'wb')
except:
    tapemate.close()
    f.close()
    raise AdpError('Failed to create temp file')

fcount  = datasize
tcount  = 0
taptime = 0

clk_adjust = 1000000.0 / 985248

while fcount > 0:
    dataval = f.read(1)[0]
    fcount -= 1
    if dataval > 0:
        dataval = int(dataval * 8 * clk_adjust + 0.5)
        t.write(dataval.to_bytes(3, byteorder='little'))
        tcount  += 3
        taptime += dataval
    else:
        if tapversion == 1:
            dataval = int.from_bytes(f.read(3), byteorder='little')
            dataval = int(dataval * clk_adjust + 0.5)
            if dataval > 0xFFFFFF:
                dataval = 0xFFFFFF
            t.write(dataval.to_bytes(3, byteorder='little'))
            taptime += dataval
            fcount  -= 3
            tcount  += 3
        else:
            dataval = int(256 * 8 * clk_adjust + 0.5)
            t.write(dataval.to_bytes(3, byteorder='little'))
            tcount  += 3
            taptime += dataval

f.close()
t.close()
datasize = tcount
taptime  = taptime // 1000000 + 1
print('Estimated recording time:', taptime//60, 'min', taptime%60, 'sec')


# Send write command to TapeMate64 and wait for RECORD pressed
print('PRESS RECORD & PLAY ON TAPE')
tapemate.sendcommand(CMD_WRITETAPE)

while 1:
    response = tapemate.read(1)
    if response:
        break
    sys.stdout.write('#')
    sys.stdout.flush()
print('\r', ' ' * 50, end='\r')
if response[0] > 0:
    tapemate.close()
    raise AdpError('Timeout waiting for RECORD')
else:
    print('OK')
    print('Start recording ...')


# Read data from temp file and write to tape
t = open('tapemate.tmp', 'rb')
checksum = 0xFFFF

while 1:
    response = tapemate.read(1)
    if response:
        packsize = response[0]
        if packsize == 0:
            break
        if tcount <= 0:
            tapemate.write(b'\x00\x00\x00')
        while packsize > 0 and tcount > 0:
            data = t.read(3)
            tcount -= 3
            tapemate.write(data)
            packsize -= 1
            checksum = crc16_update(checksum, data[0])
            checksum = crc16_update(checksum, data[1])
            checksum = crc16_update(checksum, data[2])
            if packsize > 0 and tcount <= 0:
                tapemate.write(b'\x00\x00\x00')
        progress((datasize - tcount) * 100 // datasize)

print('')
testsum  = int.from_bytes(tapemate.read(2), byteorder='little')
underrun = tapemate.read(1)[0]
stopped  = tapemate.read(1)[0]


# Close temp file and serial connection
t.close()
tapemate.close()


# Validate data and checksum and print infos
if underrun > 0:
    sys.stderr.write('ERROR: Buffer underrun occured\n')
if tcount > 0 or stopped > 0:
    raise AdpError('Recording was stopped before completion')

print('Recording finished.')

if not checksum == testsum:
    raise AdpError('Checksum mismatch')

print('Checksum:       OK')
print('Buffer status:  OK')
print('Recording successful!')
print('PRESS STOP ON TAPE')
print('')


# Delete temp file and exit
try:
    os.remove('tapemate.tmp')
except:
    sys.stderr.write('ERROR: Could not delete temp file\n')

sys.exit(0)

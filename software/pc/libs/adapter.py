#!/usr/bin/env python3
# ===================================================================================
# Project:   TapeMate64 - Python Script - Adapter Library
# Version:   v1.0
# Year:      2025
# Author:    Yannick Heneault (Based on work of Stefan Wagner)
# Github:    https://github.com/heneault/TapeMate64
# License:   http://creativecommons.org/licenses/by-sa/3.0/
# ===================================================================================

import os
import sys
import time
from serial import Serial
from serial.tools.list_ports import comports

# ===================================================================================
# Adapter Class - Basic Communication with the Device via USB to Serial Converter
# ===================================================================================

class Adapter(Serial):
    def __init__(self, ident='TapeMate64'):
        super().__init__(baudrate = 250000, timeout = None, write_timeout = None)
        self.identify(ident)

    # Identify the com port of the adapter
    def identify(self, ident):
        vid = '1A86'
        pid = '7523'
        for p in comports():
            if vid and pid in p.hwid:
                self.port = p.device

                try:
                    self.open()
                    time.sleep(2)
                    fd = self.fileno()
                    if os.name == "posix":
                        import termios
                        attrs = termios.tcgetattr(fd)
                        attrs[2] &= ~termios.HUPCL
                        termios.tcsetattr(fd, termios.TCSANOW, attrs)
                    self.dtr = False
                except:
                    continue

                try:
                    self.sendcommand(CMD_GETIDENT)
                    data = self.getline()
                except:
                    self.close()
                    continue

                if data == ident:
                    break
                else:
                    self.close()

    # Send a command to the adapter
    def sendcommand(self, cmd):
        self.write(cmd.encode())

    # Get a reply string from the adapter
    def getline(self):
        return self.read_until().decode().rstrip('\r\n')

    # Get firmware version of the adapter
    def getversion(self):
        self.sendcommand(CMD_GETVERSION)
        version = self.getline()
        return version


# ===================================================================================
# Error Class - Raise an Error
# ===================================================================================

class AdpError(Exception):
    def __init__(self, msg='Something went wrong'):
        super(AdpError, self).__init__(msg)
        sys.stderr.write('ERROR: ' + msg + '\n\n')
        sys.exit(1)


# ===================================================================================
# Adapter Commands
# ===================================================================================

CMD_GETIDENT   = 'i'
CMD_GETVERSION = 'v'
CMD_READTAPE   = 'r'
CMD_WRITETAPE  = 'w'

#!/usr/bin/env python3
# ===================================================================================
# Project:   TapeMate64 - Graphical Front End written in Python
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
#
#
# Operating Instructions:
# -----------------------
# - Connect your TapeMate64 to your Commodore Datasette
# - Connect your TapeMate64 to a USB port of your PC
# - Execute this script: python tape-gui.py


import os
import queue
import threading
from tkinter import *
from tkinter import messagebox, filedialog
from tkinter.ttk import *
from intelhex import IntelHex
from intelhex import AddressOverlapError, HexRecordError
from libs.adapter import *
from libs.arduinobootloader import ArduinoBootloader
from libs.util import crc16_update

# Firmware file
FIRMWARE_HEX   = 'libs/firmware.hex'

tapemate = None
tcount = 0
progress = None
checksum = 0xFFFF
datasize = 0
tapfile = None
taptime = 0
contentWindow = None
fsize = 0
canvas = None
text1 = None
line1 = None
pcount = 0
point = []

# ===================================================================================
# Progress Box Class - Shows a Progress Bar
# ===================================================================================

class Progressbox(Toplevel):
    def __init__(self, root = None, title = 'Please wait !',
                activity = 'Doing stuff ...', value = 0):
        Toplevel.__init__(self, root)
        self.__step = IntVar()
        self.__step.set(value)
        self.__act = StringVar()
        self.__act.set(activity)
        self.title(title)
        self.resizable(width=False, height=False)
        self.transient(root)
        self.grab_set()
        Label(self, textvariable = self.__act).pack(padx = 20, pady = 10)
        Progressbar(self, orient = HORIZONTAL, length = 200,
                variable = self.__step, mode = 'determinate').pack(
                padx = 10, pady = 10)
        self.update()

    def setactivity(self, activity):
        self.__act.set(activity)
        self.update()

    def setvalue(self, value):
        if not value == self.__step.get():
            self.__step.set(value)
            self.update()


# ===================================================================================
# Show File Content (HEX View)
# ===================================================================================

def showContent():
    global tapfile, contentWindow
    fileName = filedialog.askopenfilename(title = 'Select file for HEX view',
                filetypes = (("TAP files","*.tap"), ('All files','*.*')))
    if not fileName:
        return

    try:
        tapfile = open(fileName, 'rb')
    except:
        messagebox.showerror('Error', 'Could not open file !')
        return

    fileSize = os.stat(fileName).st_size

    contentWindow = Toplevel(mainWindow)
    contentWindow.title('File content')
    contentWindow.minsize(200, 100)
    contentWindow.resizable(width=False, height=True)
    contentWindow.transient(mainWindow)
    contentWindow.grab_set()

    l = Listbox(contentWindow, font = 'TkFixedFont', height = 36, width = 73)
    l.pack(side='left', fill=BOTH)
    s = Scrollbar(contentWindow, orient = VERTICAL, command = l.yview)
    l['yscrollcommand'] = s.set
    s.pack(side='right', fill='y')

    startAddr = 0

    while startAddr < fileSize:
        bytesline = '%06X: ' % startAddr
        asciiline = ' '
        i = 0
        while i < 16:
            if startAddr + i < fileSize:
                data = tapfile.read(1)
                bytesline += '%02X ' % data[0]
                if data[0] > 31:
                    asciiline += chr(data[0])
                else: asciiline += '.'
            else:
                bytesline += '   '
                asciiline += ' '
            i += 1
        l.insert('end', bytesline + asciiline)
        startAddr += 16
    tapfile.close()

    contentWindow.mainloop()
    contentWindow.quit()


# ===================================================================================
# Tape Read Function
# ===================================================================================
def tapeRead():
    # Establish serial connection
    global tapfile, tapemate, contentWindow, canvas, text1, line1, pcount, point
    tapemate = Adapter()
    if not tapemate.is_open:
        messagebox.showerror('Error', 'TapeMate64 Adapter not found !')
        return


    # Open output file and write file header
    fileName = filedialog.asksaveasfilename(title = 'Select output file',
                filetypes = (("TAP files","*.tap"), ('All files','*.*')))

    if not fileName:
        return

    try:
        tapfile = open(fileName, 'wb')
    except:
        messagebox.showerror('Error', 'Could not create output file !')
        tapemate.close()
        return

    tapfile.write(b'C64-TAPE-RAW\x01\x00\x00\x00\x00\x00\x00\x00')


    # Create information window
    contentWindow = Toplevel(mainWindow)
    contentWindow.title('TapeMate64 - Reading from tape')
    contentWindow.resizable(width=False, height=False)
    contentWindow.transient(mainWindow)
    contentWindow.grab_set()

    canvas = Canvas(contentWindow, width=256, height=172)
    canvas.pack()
    canvas.create_rectangle(0, 0, 256, 128, fill="white")


    # Send read command to TapeMate64 and wait for PLAY pressed
    text1 = canvas.create_text(128, 150, text='PRESS PLAY ON TAPE', fill='black', anchor='c', font=('Helvetica', 12, 'bold'))
    contentWindow.update()
    tapemate.sendcommand(CMD_READTAPE)
    while 1:
        response = tapemate.read(1)
        if response:
            break

    if response[0] > 0:
        tapfile.close()
        tapemate.close()
        contentWindow.destroy()
        messagebox.showerror('Timeout', 'Timeout waiting for PLAY')
        return

    canvas.delete(text1)
    text1 = canvas.create_text(128, 150, text='SEARCHING', fill='black', anchor='c', font=('Helvetica', 12, 'bold'))
    line1 = canvas.create_line(0, 0, 0, 128, fill='black')
    contentWindow.update()

    # Receive data from TapeMate64 and write to output file
    pcount    = 0
    point     = []

    threading.Thread(target=tapReadLoop(), daemon=True).start()

def tapReadProcessEvent(event):
    global text1, line1, pcount
    while not tap_read_data_queue.empty():
        op, count, dataval = tap_read_data_queue.get()

        if op == 0:
            x = (count // 32) % 256
            y = dataval >> 3
            i = pcount % 8000
            if pcount >= 8000:
                canvas.delete(point[i])
                point[i] = canvas.create_line(x, y, x+1, y, fill='black')
            else:
                point.append(canvas.create_line(x, y, x+1, y, fill='black'))
            pcount += 1
        elif op == 1:
            if count == 1:
                canvas.delete(text1)
                text1 = canvas.create_text(128, 150, text='READING FROM TAPE', fill='black', anchor='c', font=('Helvetica', 12, 'bold'))
                contentWindow.update()
            if count % 32 == 0:
                x = (count // 32 + 2) % 256
                canvas.delete(line1)
                line1 = canvas.create_line(x, 0, x, 128, fill='black')
                contentWindow.update()
        elif op == 2:
            tapReadFinish()

def tapReadFinish():
    global taptime
    taptime  = taptime // 985248 + 1
    tapfile.seek(16)
    tapfile.write(fsize.to_bytes(4, byteorder='little'))
    testsum  = int.from_bytes(tapemate.read(2), byteorder='little')
    overflow = tapemate.read(1)[0]

    # Close output file and serial connection
    tapfile.close()
    tapemate.close()
    contentWindow.destroy()

    # Validate data and checksum, print infos, exit
    if taptime == 0:
        messagebox.showerror('Timeout', 'No data received !')
    elif overflow > 0:
        messagebox.showerror('Error', 'Buffer overflow occured !')
    elif not checksum == testsum:
        messagebox.showerror('Error', 'Checksum mismatch !')
    else:
        messagebox.showinfo('Mission accomplished',
                'Dumping successful !\nTAP time: ' + str(taptime//60) + ' min ' + str(taptime%60) + ' sec')


def tapReadLoop():
    global taptime, checksum, fsize
    count = 0
    taptime = 0
    fsize = 0
    checksum = 0xFFFF
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

            if dataval > int(255 * 8 * clk_adjust + 0.5):
                tapfile.write(b'\x00')
                tapfile.write((dataval).to_bytes(3, byteorder='little'))
                fsize += 4
            else:
                tapfile.write((dataval>>3).to_bytes(1, byteorder='little'))
                fsize += 1
                if dataval < int(128 * 8 * clk_adjust + 0.5):
                    tap_read_data_queue.put((0, count, dataval))
            count    += 1
            checksum = crc16_update(checksum, data[0])
            checksum = crc16_update(checksum, data[1])
            checksum = crc16_update(checksum, data[2])
            taptime  += dataval
            tap_read_data_queue.put((1, count, None))
            if count == 1 or count % 32 == 0:
                mainWindow.event_generate("<<tapReadEvent>>")
    tap_read_data_queue.put((2, None, None))
    mainWindow.event_generate("<<tapReadEvent>>")

# ===================================================================================
# Tape Write Function
# ===================================================================================
def tapeWrite():
    # Establish serial connection
    global tapemate, taptime, tcount, progress, datasize
    tapemate = Adapter()
    if not tapemate.is_open:
        messagebox.showerror('Error', 'TapeMate64 Adapter not found !')
        return


    # Open input file
    fileName = filedialog.askopenfilename(title = 'Select input file',
                filetypes = (("TAP files","*.tap"), ('All files','*.*')))

    if not fileName:
        return

    try:
        fileSize = os.stat(fileName).st_size
        f = open(fileName, 'rb')
    except:
        messagebox.showerror('Error', 'Could not open input file !')
        tapemate.close()
        return


    # Check file header
    if fileSize < 20 or not f.read(12) == b'C64-TAPE-RAW':
        messagebox.showerror('Error', 'Wrong file header !')
        tapemate.close()
        f.close()
        return


    # Check TAP version
    tapversion = f.read(1)[0]
    if tapversion > 1:
        messagebox.showerror('Error', 'Unsupported TAP version !')
        tapemate.close()
        f.close()
        return


    # Check size of data area
    f.seek(16)
    datasize = int.from_bytes(f.read(4), byteorder='little')
    if not (datasize + 20) == fileSize:
        messagebox.showerror('Error', 'File size does not match header entry !')
        tapemate.close()
        f.close()
        return


    # Preparing data and store it in temp file
    try:
        t = open('tapemate.tmp', 'wb')
    except:
        messagebox.showerror('Error', 'Could not create temp file !')
        tapemate.close()
        f.close()
        return

    fcount  = datasize
    tcount  = 0
    taptime = 0

    clk_adjust = 1000000.0 / 985248

    progress = Progressbox(mainWindow, 'TapeMate64 - Writing to tape', 'Preparing data ...')

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
                dataval  = int.from_bytes(f.read(3), byteorder='little')
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
        progress.setvalue((datasize - fcount) * 100 // datasize)

    f.close()
    t.close()
    datasize = tcount
    taptime  = taptime // 1000000 + 1


    # Send write command to TapeMate64 and wait for RECORD pressed
    progress.setvalue(0)
    progress.setactivity('Recording time: ' + str(taptime//60) + ' min ' + str(taptime%60) + ' sec\n\nPRESS RECORD & PLAY ON TAPE')
    tapemate.sendcommand(CMD_WRITETAPE)

    count = 0
    while 1:
        response = tapemate.read(1)
        if response:
            break
        count += 10
        progress.setvalue(count)

    if response[0] > 0:
        f.close()
        tapemate.close()
        progress.destroy()
        messagebox.showerror('Timeout', 'Timeout waiting for RECORD')
        return


    # Read data from temp file and write to tape
    progress.setvalue(0)
    progress.setactivity('Recording in progress ...')

    threading.Thread(target=tapWriteLoop(), daemon=True).start()

def tapWriteProcessEvent(event):
    while not tap_write_data_queue.empty():
        finished, progress_value = tap_write_data_queue.get()
        progress.setvalue(progress_value)

    if finished == 1:
        tapWriteFinish()

def tapWriteFinish():
    testsum  = int.from_bytes(tapemate.read(2), byteorder='little')
    underrun = tapemate.read(1)[0]
    stopped  = tapemate.read(1)[0]

    # Close temp file and serial connection
    tapemate.close()
    progress.destroy()


    # Validate data and checksum and print infos
    if underrun > 0:
        messagebox.showerror('Error', 'Buffer underrun occured !')

    elif tcount > 0 or stopped > 0:
        messagebox.showerror('Error', 'Recording was stopped before completion !')

    elif not checksum == testsum:
        messagebox.showerror('Error', 'Checksum mismatch !')

    else:
        messagebox.showinfo('Mission accomplished',
                'Recording successful !\nPRESS STOP ON TAPE')

    os.remove('tapemate.tmp')

def tapWriteLoop():
    global tcount, checksum
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
            tap_write_data_queue.put((0, (datasize - tcount) * 100 // datasize))
            mainWindow.event_generate("<<tapWriteEvent>>")
    t.close()
    tap_write_data_queue.put((1, 100))
    mainWindow.event_generate("<<tapWriteEvent>>")


# ===================================================================================
# Flash Firmware
# ===================================================================================

def flashFirmware():
    global progress
    # Show info
    messagebox.showinfo('Flash Firmware',
            'Connect the device')

    # Establish serial connection
    progress = Progressbox(mainWindow, 'TapeMate64 - Flashing firmware', 'Connecting to device ...')
    ab = ArduinoBootloader()
    prg = ab.select_programmer("Stk500v1")
    if not prg.open():
        progress.destroy()
        messagebox.showerror('Error', 'Device not found!')
        return

    # Enter progmode
    progress.setactivity('Pinging target MCU ...')

    if not prg.board_request():
        prg.close()
        progress.destroy()
        messagebox.showerror('Error', "Error with board request")
        return

    if not prg.cpu_signature():
        prg.close()
        progress.destroy()
        messagebox.showerror('Error', 'Unknown or unsupported device!')
        return

    ih = IntelHex()

    try:
        ih.fromfile(FIRMWARE_HEX, format='hex')
    except FileNotFoundError:
        prg.close()
        progress.destroy()
        messagebox.showerror('Error', "file not found")
        return
    except (AddressOverlapError, HexRecordError):
        prg.close()
        progress.destroy()
        messagebox.showerror('Error', "file format not supported")
        return

    # Flash firmware
    progress.setactivity('Flashing firmware ...')

    try:
        for address in range(0, ih.maxaddr(), ab.cpu_page_size):
            buffer = ih.tobinarray(start=address, size=ab.cpu_page_size)
            if not prg.write_memory(buffer, address):
                raise Exception()
            progress.setvalue(address * 100 / ih.maxaddr())
    except:
        prg.leave_bootloader()
        prg.close()
        progress.destroy()
        messagebox.showerror('Error', 'Flashing firmware failed!')
        return

    progress.setvalue(100)
    prg.leave_bootloader()
    prg.close()

    # Show info
    messagebox.showinfo('Mission accomplished',
            'Firmware successfully flashed!')
    progress.destroy()


# ===================================================================================
# Main Function
# ===================================================================================

mainWindow = Tk()
mainWindow.title('TapeMate64')
mainWindow.resizable(width=False, height=False)
mainWindow.minsize(200, 100)

tapeFrame = Frame(mainWindow, borderwidth = 2, relief = 'groove')
Label(tapeFrame, text = 'Tape Functions:').pack(pady = 5)
Button(tapeFrame, text = 'Read from tape to TAP file', command = tapeRead).pack(padx = 10, pady = 2, fill = 'x')
Button(tapeFrame, text = 'Write TAP file to tape', command = tapeWrite).pack(padx = 10, pady = 2, fill = 'x')
tapeFrame.pack(padx = 10, pady = 10, ipadx = 5, ipady = 5, fill = 'x')

specialFrame = Frame(mainWindow, borderwidth = 2, relief = 'groove')
Label(specialFrame, text = 'Additional Functions:').pack(pady = 5)
Button(specialFrame, text = 'Show File Content (hex)', command = showContent).pack(padx = 10, pady = 2, fill = 'x')
Button(specialFrame, text = 'Flash firmware', command = flashFirmware).pack(padx = 10, pady = 2, fill = 'x')
specialFrame.pack(padx = 10, pady = 5, ipadx = 5, ipady = 5, fill = 'x')

Button(mainWindow, text = 'Exit', command = mainWindow.quit).pack(pady = 10)

tap_read_data_queue = queue.Queue()
mainWindow.bind("<<tapReadEvent>>", tapReadProcessEvent)
tap_write_data_queue = queue.Queue()
mainWindow.bind("<<tapWriteEvent>>", tapWriteProcessEvent)

mainWindow.mainloop()

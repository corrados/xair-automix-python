#!/usr/bin/env python3

#*******************************************************************************
# Copyright (c) 2024-2024
# Author(s): Volker Fischer
#*******************************************************************************
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA
#*******************************************************************************

# Perform auto mixing based on measured signal levels for the Behringer X-AIR mixers.
# protocol: https://wiki.munichmakerlab.de/images/1/17/UNOFFICIAL_X32_OSC_REMOTE_PROTOCOL_%281%29.pdf
# https://mediadl.musictribe.com/download/software/behringer/XAIR/X%20AIR%20Remote%20Control%20Protocol.pdf

import sys, threading, time, socket, struct
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
import numpy as np
from pythonx32 import x32
from collections import deque
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import tkinter as tk
from tkinter import ttk

found_addr   = -1
channel      = 12; # TEST
len_meter2   = 18  # ALL INPUTS (16 mic, 2 aux, 18 usb = 36 values total but we only need the mic inputs)
len_meter4   = 100 # RTA100 (100 bins RTA = 100 values)
is_XR16      = False
exit_threads = False
file_path    = "test.dat"
#queue_len_s  = 20 * 60 # 20 minutes
queue_len_s = 30 # TEST

# create queues and fill completely with zeros for initialization
queue_len = int(queue_len_s / 0.05) # update cycle frequency for meter data is 50 ms
all_raw_inputs_queue = deque()
all_inputs_queue     = deque([[-128] * len_meter2] * queue_len)
rta_queue            = deque([[-128] * len_meter4] * queue_len)
queue_mutex          = threading.Lock()


def main():
  global found_addr, found_port, fader_init_val, bus_init_val, mixer, exit_threads, is_XR16

  # search for a mixer and initialize the connection to the mixer
  local_port  = 10300
  addr_subnet = '.'.join(get_ip().split('.')[0:3]) # only use first three numbers of local IP address
  while found_addr < 0:
    for j in range(10024, 10022, -1): # X32:10023, XAIR:10024 -> check both
      if found_addr < 0:
        for i in range(2, 255):
          threading.Thread(target = try_to_ping_mixer, args = (addr_subnet, local_port + 1, i, j, )).start()
          if found_addr >= 0:
            break
      if found_addr < 0:
        time.sleep(2) # time-out is 1 second -> wait two-times the time-out

  mixer   = x32.BehringerX32(f"{addr_subnet}.{found_addr}", local_port, False, 10, found_port)
  is_XR16 = "XR16" in mixer.get_value("/info")[2]

  #basic_setup_mixer(mixer)

  # separate threads: sending meters queries; receiving meter updates; storing input levels in file
  threading.Timer(0.0, send_meters_request_message).start()
  threading.Timer(0.0, receive_meter_messages).start()
  threading.Timer(0.0, store_input_levels_in_file).start()

  # TEST configure RTA
  configure_rta(channel) # note: zero-based channel number
  #configure_rta(31) # 31: MainLR on XAIR16

  window = tk.Tk()
  window.title("XR Auto Mix")
  input_bars = []
  rta_bars   = []
  inputs_f   = tk.Frame(window)
  inputs_f.pack()
  for i in range(0, len_meter2):
    f = tk.Frame(inputs_f)
    f.pack(side="left", pady='5')
    tk.Label(f, text=f"L{i + 1:^2}").pack()
    input_bars.append(tk.DoubleVar(window))
    ttk.Progressbar(f, orient=tk.VERTICAL, variable=input_bars[i]).pack()

  canvas_height  = 100
  rta_line_width = 3
  canvas_width   = 100 * rta_line_width + 100
  rta = tk.Canvas(window, width=canvas_width, height=canvas_height)
  rta.pack()

  for test in range(0, 50):
    with queue_mutex:
      input_values = all_inputs_queue[len(all_inputs_queue) - 1]
      input_rta    = rta_queue[len(rta_queue) - 1]
    for i in range(0, len_meter2):
      input_bars[i].set((input_values[i] / 128 + 1) * 100)

    rta.delete("all")
    for i in range(0, len_meter4):
      x = rta_line_width + i * rta_line_width + i
      y = (input_rta[i] / 128 + 1) * canvas_height
      rta.create_line(x, canvas_height, x, canvas_height - y, fill="#476042", width=rta_line_width)

    window.update()
    time.sleep(0.05)

  ## TEST
  #with queue_mutex:
  #  max_all_inputs  = np.matrix.max(np.mat(list(all_inputs_queue)), axis=0)
  #  mean_all_inputs = np.matrix.mean(np.mat(list(all_inputs_queue)), axis=0)
  #print(max_all_inputs)
  #print(mean_all_inputs)

  exit_threads = True


def basic_setup_mixer(mixer):
  vocal   = [ 9 - 8]
  guitar  = [11 - 8]
  bass    = [10 - 8]
  edrums  = [13 - 8]
  drums   = [12 - 8]
  special = [0]
  channel_dict = { 0:["Click",      0, special, ["NOMIX"]], \
                   1:["E-Git Mono", 0, guitar], \
                   2:["Stefan",     0, vocal], \
                   3:["Miguel",     0, vocal], \
                   4:["Chris",      0, vocal], \
                   5:["Bass",       0, bass], \
                   6:["E-Git L",    0, guitar], \
                   7:["E-Git R",    0, guitar], \
                   8:["A-Git",      0, guitar], \
                   9:["Kick",       0, drums, ["PHANT"]], \
                  10:["Snare",      0, drums], \
                  11:["Tom1",       0, drums], \
                  12:["Tom2",       0, drums], \
                  13:["Overhead",   0, drums, ["PHANT"]], \
                  14:["E-Drum L",   0, edrums], \
                  15:["E-Drum R",   0, edrums]}
  for ch in channel_dict:
    inst_group = channel_dict[ch][2]
    mixer.set_value(f"/ch/{ch + 1:#02}/config/color", [inst_group[0]], True)
    mixer.set_value(f"/ch/{ch + 1:#02}/config/name", [channel_dict[ch][0]], True)
    set_gain(ch, channel_dict[ch][1])
    mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [1], True)       # default: send to LR master
    mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [0], True) # default: no phantom power
    mixer.set_value(f"/ch/{ch + 1:#02}/mix/pan", [0.5], True)    # default: middle position per default
    if len(channel_dict[ch]) > 3: # special channel settings
      if "NOMIX" in channel_dict[ch][3]:
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [0], True)
      if "PHANT" in channel_dict[ch][3]:
        mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [1], True)

  # stereo link E-Git and E-Drum
  mixer.set_value("/config/chlink/7-8", [1], True)   # stereo E-Git
  mixer.set_value("/config/chlink/15-16", [1], True) # stereo E-Drums


def configure_rta(channel):
  global mixer
  mixer.set_value("/-prefs/rta/decay", [0], True) # fastest possible decay
  mixer.set_value("/-prefs/rta/det", [0], True) # 0: peak, 1: RMS
  mixer.set_value("/-stat/rta/source", [channel], True) # note: zero-based channel number


def send_meters_request_message():
  global mixer
  while not exit_threads:
    #mixer.set_value(f'/meters', ['/meters/0', channel], False) # 8 channel meters
    #mixer.set_value(f'/meters', ['/meters/1'], False)          # ALL CHANNELS
    mixer.set_value(f'/meters', ['/meters/2'], False)           # ALL INPUTS
    mixer.set_value(f'/meters', ['/meters/4'], False)           # RTA100
    #mixer.set_value(f'/meters', ['/meters/5'], False)          # ALL OUTPUTS
    if not exit_threads: time.sleep(1) # every second update meters request


def receive_meter_messages():
  global mixer
  while not exit_threads:
    cur_message = mixer.get_msg_from_queue()
    mixer_cmd   = cur_message.address

    if mixer_cmd == "/meters/2" or mixer_cmd == "/meters/4":
      mixer_data = bytearray(cur_message.data[0])
      num_bytes = len(mixer_data)
      if num_bytes >= 4:
        size = struct.unpack('i', mixer_data[0:4])[0]
        raw_values = [0] * size
        values     = [0] * size
        for i in range(0, size):
          cur_byte = mixer_data[4 + i * 2:4 + i * 2 + 2]
          raw_values[i] = struct.unpack('h', cur_byte)[0] # signed integer 16 bit
          values[i] = raw_values[i] / 256                 # resolution 1/256 dB

        with queue_mutex:
          if mixer_cmd == "/meters/2":
            all_raw_inputs_queue.append(raw_values[0:len_meter2])
            all_inputs_queue.popleft()
            all_inputs_queue.append(values[0:len_meter2])
          elif mixer_cmd == "/meters/4":
            rta_queue.popleft()
            rta_queue.append(values)
    else:
      # no meters message, put it back on queue
      mixer.put_msg_on_queue(cur_message)


def store_input_levels_in_file():
  # Octave: h=fopen('test.dat','rb');x=fread(h,Inf,'int16');fclose(h);x=reshape(x,18,[])/256;close all;plot(x.')
  while not exit_threads:
    with queue_mutex:
      cur_list_data = [] # just do copy in mutex and not the actual file storage
      while all_raw_inputs_queue:
        cur_list_data.append(all_raw_inputs_queue.popleft())
    with open(file_path, "ab") as file:
      for data in cur_list_data:
        file.write(struct.pack('%sh' % len(data), *data))
    if not exit_threads: time.sleep(1) # every second append logging file


def set_gain(ch, x):
  if ch >= 8 and is_XR16:
    mixer.set_value(f"/headamp/{ch + 9:#02}/gain", [(x + 12) / (20 - (-12))], False) # TODO readback does not work because of rounding effects
  else:
    mixer.set_value(f"/headamp/{ch + 1:#02}/gain", [(x + 12) / (60 - (-12))], False) # TODO readback does not work because of rounding effects


def try_to_ping_mixer(addr_subnet, start_port, i, j):
  global found_addr, found_port
  #print(f"{addr_subnet}.{i}:{start_port + i + j}")
  search_mixer = x32.BehringerX32(f"{addr_subnet}.{i}", start_port + i + j, False, 1, j) # just one second time-out
  try:
    search_mixer.ping()
    search_mixer.__del__() # important to delete object before changing found_addr
    found_addr = i
    found_port = j
  except:
    search_mixer.__del__()


# taken from stack overflow "Finding local IP addresses using Python's stdlib"
def get_ip():
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.settimeout(0)
  try:
    # doesn't even have to be reachable
    s.connect(('10.255.255.255', 1))
    IP = s.getsockname()[0]
  except Exception:
    IP = '127.0.0.1'
  finally:
    s.close()
  return IP


if __name__ == '__main__':
  main()


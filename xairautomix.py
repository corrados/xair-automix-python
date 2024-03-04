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
# According to https://www.youtube.com/watch?v=EilVDp39A9g -> input gain level should be -18 dB
#                                                          -> high pass on guitar/vocal at 100 Hz, bass at 20-30 Hz


import sys, threading, time, socket, struct, numpy
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
from pythonx32 import x32
from collections import deque
import matplotlib.pyplot as plt # TODO somehow needed for "messagebox.askyesno"?
import tkinter as tk
from tkinter import ttk

# custom mixer channel setup
vocal   = [1]
guitar  = [3]
bass    = [2]
edrums  = [5]
drums   = [4]
special = [0]
channel_dict = { 0:["Click",      0, special, ["NOMIX"]], \
                 1:["E-Git Mono", 0, guitar], \
                 2:["Stefan",     0, vocal], \
                 3:["Miguel",     0, vocal], \
                 4:["Chris",      0, vocal], \
                 5:["Bass",       0, bass], \
                 6:["E-Git L",    0, guitar], \
                 7:["E-Git R",    0, guitar, ["LINK"]], \
                 8:["A-Git",      0, guitar], \
                 9:["Kick",       0, drums, ["PHANT"]], \
                10:["Snare",      0, drums], \
                11:["Tom1",       0, drums], \
                12:["Tom2",       0, drums], \
                13:["Overhead",   0, drums, ["PHANT"]], \
                14:["E-Drum L",   0, edrums], \
                15:["E-Drum R",   0, edrums, ["LINK"]]}
busses_dict = { 0:["Stefan Mon"], \
                1:["Chris Mon"], \
                2:["Miguel Mon L"], \
                3:["Miguel Mon R", ["LINK"]], \
                4:["Volker Mon L"], \
                5:["Volker Mon R", ["LINK"]]}

local_port       = 10300
found_addr       = -1
channel          = -1  # initialize with invalid channel
len_meter2       = 18  # ALL INPUTS (16 mic, 2 aux, 18 usb = 36 values total but we only need the mic inputs)
len_meter4       = 100 # RTA100 (100 bins RTA = 100 values)
hist_len         = 128 # histogram bins
rta_hist_height  = 120
meter_update_s   = 0.05 # update cycle frequency for meter data is 50 ms
rta_line_width   = 3
hist_line_width  = 3
target_max_gain  = -15 # dB
input_threshold  = -50 # dB
max_allowed_gain = 40 # dB
is_XR16          = False
exit_threads     = False
file_path        = "test.dat"
queue_len_s      = 5 * 60 # 5 minutes

# TEST
use_recorded_data = False


# global initializations
all_raw_inputs_queue = deque()
queue_mutex          = threading.Lock()


def main():
  global found_addr, found_port, fader_init_val, bus_init_val, mixer, is_XR16
  reset_buffers()

  # search for a mixer and initialize the connection to the mixer
  addr_subnet = search_mixer()
  mixer       = x32.BehringerX32(f"{addr_subnet}.{found_addr}", local_port, False, 10, found_port)
  is_XR16     = "XR16" in mixer.get_value("/info")[2]

  # get current input gains
  for ch in channel_dict:
    channel_dict[ch][1] = get_gain(ch)

  # start separate threads
  threading.Timer(0.0, send_meters_request_message).start()
  threading.Timer(0.0, receive_meter_messages).start()
  threading.Timer(0.0, store_input_levels_in_file).start()
  threading.Timer(0.0, gui_thread).start()


def set_gains():
  with queue_mutex:
    for i in range(len_meter2):
      if i < len(channel_dict):
        (histogram_normalized, max_index, max_data_index, max_data_value) = analyze_histogram(histograms[i])
        new_gain = round((channel_dict[i][1] - (max_data_value - target_max_gain)) * 2) / 2 # round to 0.5
        if new_gain < max_allowed_gain and max_data_value > input_threshold:
          channel_dict[i][1] = set_gain(i, new_gain)
        else:
          channel_dict[i][1] = set_gain(i, 0) # in case channel is not connected, set to 0 dB input gain
  reset_buffers() # history needs to be reset on updated gain settings


def basic_setup_mixer(mixer):
  if tk.messagebox.askyesno(message='Are you sure to reset all mixer settings?'):
    for i in range(6):
      mixer.set_value(f"/bus/{i + 1}/config/name", [busses_dict[i][0]], True)
      #/bus/1/config/name

      # TODO support ["LINK"] in busses_dict

    # TODO this does not work -> FX channels do not seem to update to any settings parameter...
    #for i in range(4):
    #  mixer.set_value(f"/fxsend/{i + 1}/mix/fader", [0], True)  # default: 
    #  #/fxsend/1/mix/fader
    #  print(mixer.get_value(f"/fxsend/{i + 1}/config/name"))
    #  mixer.set_value(f"/fxsend/{i + 1}/config/name", ["test"], True)  # default: 
    #  #/fxsend/1/config/name

    for ch in channel_dict:
      inst_group = channel_dict[ch][2]
      mixer.set_value(f"/ch/{ch + 1:#02}/config/color", [inst_group[0]], True)
      mixer.set_value(f"/ch/{ch + 1:#02}/config/name", [channel_dict[ch][0]], True)
      mixer.set_value(f"/ch/{ch + 1:#02}/config/insrc", [ch], True) # default: linear in/out mapping
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [1], True)        # default: send to LR master
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/on", [1], True)        # default: unmute channel
      mixer.set_value(f"/ch/{ch + 1:#02}/grp/mute", [0], True)      # default: no mute group
      mixer.set_value(f"/-stat/solosw/{ch + 1:#02}", [0], True)     # default: no Solo
      mixer.set_value(f"/ch/{ch + 1:#02}/grp/dca", [0], True)       # default: no DCA group
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/fader", [0], True)     # default: fader to lowest value
      mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [0], True)  # default: no phantom power
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/pan", [0.5], True)     # default: middle position
      mixer.set_value(f"/ch/{ch + 1:#02}/gate/on", [0], True)       # default: gate off
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/on", [0], True)        # default: compressor off
      mixer.set_value(f"/ch/{ch + 1:#02}/eq/on", [1], True)         # default: EQ on
      mixer.set_value(f"/ch/{ch + 1:#02}/preamp/hpon", [0], True)   # default: high-pass off
      for i in range(4):
        mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/type", [2], True) # default: EQ, PEQ
        mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/g", [0.5], True)  # default: EQ, 0 dB gain
      for i in range(9):
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/0{i + 1}/level", [0], True) # default: sends to lowest value
      if ch % 2 == 1:
        mixer.set_value(f"/config/chlink/{ch}-{ch + 1}", [0], True) # default: no stereo link
      if len(channel_dict[ch]) > 3: # special channel settings
        if "NOMIX" in channel_dict[ch][3]:
          mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [0], True)
        if "PHANT" in channel_dict[ch][3]:
          mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [1], True)
        if "LINK" in channel_dict[ch][3] and ch % 2 == 1:
          mixer.set_value(f"/config/chlink/{ch}-{ch + 1}", [1], True)


def configure_rta(channel):
  global mixer
  mixer.set_value("/-prefs/rta/decay", [0], True)       # fastest possible decay
  mixer.set_value("/-prefs/rta/det", [0], True)         # 0: peak, 1: RMS
  mixer.set_value("/-stat/rta/source", [channel], True) # note: zero-based channel number


def get_gain(ch):
  if ch >= 8 and is_XR16:
    return mixer.get_value(f"/headamp/{ch + 9:#02}/gain")[0] * (20 - (-12)) - 12
  else:
    return mixer.get_value(f"/headamp/{ch + 1:#02}/gain")[0] * (60 - (-12)) - 12


def set_gain(ch, x):
  if ch >= 8 and is_XR16:
    value = max(0, min(1, (x + 12) / (20 - (-12))))
    mixer.set_value(f"/headamp/{ch + 9:#02}/gain", [value], True)
    return value * (20 - (-12)) - 12
  else:
    value = max(0, min(1, (x + 12) / (60 - (-12))))
    mixer.set_value(f"/headamp/{ch + 1:#02}/gain", [value], True)
    return value * (60 - (-12)) - 12


def send_meters_request_message():
  global mixer
  while not exit_threads:
    #mixer.set_value(f'/meters', ['/meters/0', channel], False) # 8 channel meters
    #mixer.set_value(f'/meters', ['/meters/1'], False)          # ALL CHANNELS
    mixer.set_value(f'/meters', ['/meters/2'], False)           # ALL INPUTS
    mixer.set_value(f'/meters', ['/meters/4'], False)           # RTA100
    #mixer.set_value(f'/meters', ['/meters/5'], False)          # ALL OUTPUTS
    if not exit_threads: time.sleep(1) # every second update meters request


# TEST
if use_recorded_data:
  f = open("_test.dat", mode="rb")
  data1 = numpy.reshape(numpy.fromfile(f, dtype=numpy.int16), (-1, 18))
  count = 60000
  f.close()


def receive_meter_messages():
  global mixer, count
  while not exit_threads:
    cur_message = mixer.get_msg_from_queue()
    mixer_cmd   = cur_message.address

    if mixer_cmd == "/meters/2" or mixer_cmd == "/meters/4":
      mixer_data = bytearray(cur_message.data[0])
      num_bytes  = len(mixer_data)
      if num_bytes >= 4:
        size = struct.unpack('i', mixer_data[0:4])[0]
        raw_values = [0] * size
        values     = [0] * size
        for i in range(size):
          cur_byte      = mixer_data[4 + i * 2:4 + i * 2 + 2]
          raw_values[i] = struct.unpack('h', cur_byte)[0] # signed integer 16 bit
          values[i]     = raw_values[i] / 256             # resolution 1/256 dB

        with queue_mutex:
          if mixer_cmd == "/meters/2":

            # TEST NOTE: "global count" can be removed as soon as the TEST code is removed
            if use_recorded_data:
              values = data1[count] / 256
              count += 1

            all_raw_inputs_queue.append(raw_values[0:len_meter2])
            old_values = all_inputs_queue.popleft()
            cur_values = values[0:len_meter2]
            calc_histograms(old_values, cur_values)
            all_inputs_queue.append(cur_values)
          elif mixer_cmd == "/meters/4":
            rta_queue.popleft()
            rta_queue.append(values)
    else:
      # no meters message, put it back on queue and give other thread some time to process message
      mixer.put_msg_on_queue(cur_message)
      time.sleep(0.02)


def analyze_histogram(histogram):
  max_index      = numpy.argmax(histogram)
  max_data_index = len(histogram) - 1 # start value
  while histogram[max_data_index] == 0 and max_data_index > 0: max_data_index -= 1
  max_data_value = int(max_data_index / hist_len * 129 - 128)
  max_hist = max(histograms[channel])
  if max_hist > 0:
    histogram_normalized = [x / max_hist for x in histograms[channel]]
  else:
    histogram_normalized = [0] * len(histogram)
  return (histogram_normalized, max_index, max_data_index, max_data_value)


def calc_histograms(old_values, cur_values):
  for i in range(len_meter2):
    old_value = old_values[i]
    cur_value = cur_values[i]
    if old_value > -200: # check for invalid initialization value
      old_hist_idx = int((old_value + 128) / 129 * hist_len)
      histograms[i][old_hist_idx] -= 1 # histogram with moving time window
    cur_hist_idx = int((cur_value + 128) / 129 * hist_len)
    histograms[i][cur_hist_idx] += 1


def reset_buffers():
  global all_inputs_queue, rta_queue, histograms
  with queue_mutex:
    queue_len        = int(queue_len_s / meter_update_s)
    all_inputs_queue = deque([[-200] * len_meter2] * queue_len) # using invalid initialization value of -200 dB
    rta_queue        = deque([[-200] * len_meter4] * queue_len) # using invalid initialization value of -200 dB
    histograms       = [[0] * hist_len for i in range(len_meter2)]


def gui_thread():
  global exit_threads, channel
  window       = tk.Tk(className="XR Auto Mix")
  window_color = window.cget("bg")
  (input_bars, input_labels, rta_bars) = ([], [], [])
  (buttons_f, inputs_f, selection_f)   = (tk.Frame(window), tk.Frame(window), tk.Frame(window))
  buttons_f.pack()
  inputs_f.pack()
  selection_f.pack()

  # buttons
  tk.Button(buttons_f, text="Reset Buffers",command=lambda: reset_buffers()).pack(side='left')
  tk.Button(buttons_f, text="Apply Gains",command=lambda: set_gains()).pack(side='left')
  tk.Button(buttons_f, text="Apply Faders",command=lambda: print("Button Apply Faders pressed")).pack(side='left')
  tk.Button(buttons_f, text="Reset All",command=lambda: basic_setup_mixer(mixer)).pack(side='left')

  # input level meters
  for i in range(len_meter2):
    f = tk.Frame(inputs_f)
    f.pack(side="left", pady='5')
    if i < len(channel_dict):
      tk.Label(f, text=f"L{i + 1:^2}\n{channel_dict[i][0]} |").pack()
    else:
      tk.Label(f, text=f"L{i + 1:^2}\n").pack()
    input_bars.append(tk.DoubleVar(window))
    ttk.Progressbar(f, orient=tk.VERTICAL, variable=input_bars[i]).pack()
    input_labels.append(tk.Label(f))
    input_labels[i].pack()

  # channel selection
  tk.Label(selection_f, text="Channel Selection:").pack(side='left')
  channel_sel = ttk.Combobox(selection_f)
  channel_sel['values'] = [f"{x}" for x in range(1, len_meter2 + 1)]
  channel_sel.current(13)#0)
  channel_sel.pack()

  # RTA/histogram
  rta = tk.Canvas(window, width=len_meter4 * rta_line_width + len_meter4, height=rta_hist_height)
  rta.pack()
  hist = tk.Canvas(window, width=hist_len * hist_line_width + hist_len, height=rta_hist_height)
  hist.pack()

  while not exit_threads:
    try:
      with queue_mutex:
        input_values = all_inputs_queue[len(all_inputs_queue) - 1]
        input_rta    = rta_queue[len(rta_queue) - 1]
      for i in range(len_meter2):
        input_bars[i].set((input_values[i] / 128 + 1) * 100)
        (histogram_normalized, max_index, max_data_index, max_data_value) = analyze_histogram(histograms[i])
        if max_data_value > target_max_gain + 6:
          input_labels[i].config(text=max_data_value, bg="red")
        else:
          if max_data_value > target_max_gain:
            input_labels[i].config(text=max_data_value, bg="yellow")
          else:
            input_labels[i].config(text=max_data_value, bg=window_color)

      rta.delete("all")
      for i in range(len_meter4):
        x = rta_line_width + i * rta_line_width + i
        y = (input_rta[i] / 128 + 1) * rta_hist_height
        rta.create_line(x, rta_hist_height, x, rta_hist_height - y, fill="#476042", width=rta_line_width)

      (histogram_normalized, max_index, max_data_index, max_data_value) = analyze_histogram(histograms[channel])
      hist.delete("all")
      for i in range(hist_len):
        x = hist_line_width + i * hist_line_width + i
        y = histogram_normalized[i] * rta_hist_height
        color = "blue" if i == max_index else "red" if i == max_data_index else "#476042"
        hist.create_line(x, rta_hist_height, x, rta_hist_height - y, fill=color, width=hist_line_width)

      if int(channel_sel.get()) - 1 is not channel:
        channel = int(channel_sel.get()) - 1
        configure_rta(channel) # configure_rta(31) # 31: MainLR on XAIR16

      window.update()
      time.sleep(meter_update_s)
    except:
      exit_threads = True


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


def search_mixer():
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
  return addr_subnet


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


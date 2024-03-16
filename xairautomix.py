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
#           https://behringer.world/wiki/doku.php?id=x-air_osc
#           https://mediadl.musictribe.com/download/software/behringer/XAIR/X%20AIR%20Remote%20Control%20Protocol.pdf
# According to https://www.youtube.com/watch?v=EilVDp39A9g -> input gain level should be -18 dB
#                                                          -> high pass on guitar/vocal at 100 Hz, bass at 20-30 Hz
# According to https://www.youtube.com/watch?v=nF0uezOA4UA&t=386s -> vocal high pass at 120-180 Hz,
# -> vocal compression: ratio:3, attack: 10 ms, hold: 0 ms, release: 50 ms, gain: +6 dB, gain reduction meter: approx. -6 dB
# Behringer: vocal compression: ratio:3, attach: 10 ms, hold: 10 ms, release: 151 ms, gain: +6 dB, self filter: type: 3,
#                               frequency 611 Hz

import sys, threading, time, struct, numpy
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
from pythonx32 import x32
from collections import deque
import matplotlib.pyplot as plt # TODO somehow needed for "messagebox.askyesno"?
import tkinter as tk
from tkinter import ttk

# mixer channel setup, channel_dict: [name, fader, gain, HP, group, special]
special = [0]
vocal   = [1, ["VOCALDYN"]]
bass    = [2]
guitar  = [3]
drums   = [4]
edrums  = [5]
channel_dict = {0:["Click",    -90, 1.5, 101, [], special, ["NOMIX"]], \
                1:["",         -90,  -6, 101, [], special], \
                2:["Stefan",     0,  23, 121, [], vocal], \
                3:["Miguel",    -2,  29, 121, [[4, 124.7, 1], [-3.5, 2340, 2]], vocal], \
                4:["Chris",     -2,  18, 121, [[1.25, 1260, 2], [1.75, 3680, 2]], vocal], \
                5:["Bass",      -2,   6,  25, [], bass], \
                6:["E-Git L",   -2,  13, 101, [], guitar], \
                7:["E-Git R",   -2,  13, 101, [], guitar, ["LINK"]], \
                8:["A-Git",     -5, -12, 101, [], guitar], \
                9:["Kick",      -2,  -2,  25, [[3, 58.3, 2], [-3.75, 158.9, 1.4], [5.75, 3090, 2]], drums, ["PHANT"]], \
               10:["Snare",     -2,  -9, 101, [[-3, 232.3, 3.1], [-2.5, 990.9, 3.5], [3, 7090, 2.8]], drums], \
               11:["Tom1",      -2,  -5,  40, [[3, 133.7, 1.8], [-6.25, 701.5, 1.1], [4.5, 3200, 1.7]], drums], \
               12:["Tom2",      -2,  -5,  25, [[4, 85.3, 2], [-6.75, 550.8, 0.7], [4.25, 3430, 2]], drums], \
               13:["Overhead",  -5,  -5, 101, [[0, 1490]], drums, ["PHANT"]], \
               14:["E-Drum L",  -2,  -5,  25, [], edrums], \
               15:["E-Drum R",  -2,  -5,  25, [], edrums, ["LINK"]]}
busses_dict = {0:["Stefan Mon",   [-90, -90, -90,  0,   0,  0,   0,   0, -90, -3, -6, -6, -6, -3, -3, -3], -10          ], \
               1:["Chris Mon",    [-90, -90,   0,  0, -90,  0, -90, -90,   0, -3, -6, -6, -6, -3, -3, -3], -10          ], \
               2:["Miguel Mon L", [-90, -90,  -6, -3,  -6,  0,  -6,  -6,  -6, -3, -6, -6, -6, -3, -3, -3], -10          ], \
               3:["Miguel Mon R", [-90, -90,  -6, -3,  -6,  0,  -6,  -6,  -6, -3, -6, -6, -6, -3, -3, -3], -10, ["LINK"]], \
               4:["Volker Mon L", [-90, -90,  -6, -6,  -6, -6,  -6,  -6,  -6,  0,  0,  0,  0,  0,  0,  0], -10          ], \
               5:["Volker Mon R", [  0, -90,  -6, -6,  -6, -6,  -6,  -6,  -6,  0,  0,  0,  0,  0,  0,  0], -10, ["LINK"]]}
busses_pan_dict = {2:[0, 0, -30, 60, -94, 44, -100,  32, -40, 0, 0,   0,  0, -46, -100, 100], \
                   4:[0, 0,  20, 42, -50,  0, -100, 100,  40, 0, 0, -18, 18,   0, -100, 100]}

use_recorded_data = False # TEST
target_max_gain  = -15 # dB
input_threshold  = -50 # dB
max_allowed_gain =  40 # dB

channel              = -1   # initialize with invalid channel
is_input_hist        = True # histogram of inputs per default
len_meter2           = 18   # ALL INPUTS (16 mic, 2 aux, 18 usb = 36 values total but we only need the mic inputs)
len_meter4           = 100  # RTA100 (100 bins RTA = 100 values)
len_meter6           = 16   # ALL DYN (16 gate, 16 dyn(ch), 6 dyn(bus), dyn(lr) = 39 values total but we want 16 dyn only)
hist_len             = 128  # histogram bins
rta_hist_height      = 120
meter_update_s       = 0.05 # update cycle frequency for meter data is 50 ms
rta_line_width       = 3
hist_line_width      = 3
is_XR16              = False
exit_threads         = False
file_path            = "test.dat"
input_values         = [0] * len_meter2
gatedyn_values       = [0] * len_meter6
input_rta            = [0] * len_meter4
all_raw_inputs_queue = deque()
data_mutex           = threading.Lock()


def main():
  global mixer, is_XR16
  reset_histograms()
  mixer   = x32.BehringerX32([], 10300, False, 10) # search for a mixer
  is_XR16 = "XR16" in mixer.get_value("/info")[2]
  configure_rta(31) # 31: MainLR on XAIR16
  # start separate threads
  threading.Timer(0.0, send_meters_request_message).start()
  threading.Timer(0.0, receive_meter_messages).start()
  threading.Timer(0.0, store_input_levels_in_file).start()
  threading.Timer(0.0, gui_thread).start()


def apply_optimal_gains():
  with data_mutex:
    for ch in range(len(channel_dict)):
      (max_data_index, max_data_value) = analyze_histogram(input_histograms[ch])
      new_gain = get_gain(ch) - (max_data_value - target_max_gain)
      if new_gain < max_allowed_gain and max_data_value > input_threshold:
        set_gain(ch, new_gain)
  reset_histograms() # history needs to be reset on updated gain settings


def get_gain(ch):
  if ch >= 8 and is_XR16:
    return mixer.get_value(f"/headamp/{ch + 9:#02}/gain")[0] * (20 - (-12)) - 12
  else:
    return mixer.get_value(f"/headamp/{ch + 1:#02}/gain")[0] * (60 - (-12)) - 12


def set_gain(ch, x):
  x = round(x * 2) / 2 # round to 0.5
  if ch >= 8 and is_XR16:
    value = max(0, min(0.984375, (x + 12) / (20 - (-12))))
    mixer.set_value(f"/headamp/{ch + 9:#02}/gain", [value])
    return value * (20 - (-12)) - 12
  else:
    value = max(0, min(1, (x + 12) / (60 - (-12))))
    mixer.set_value(f"/headamp/{ch + 1:#02}/gain", [value])
    return value * (60 - (-12)) - 12


def basic_setup_mixer(mixer):
  if tk.messagebox.askyesno(message='Are you sure to reset all mixer settings?'):
    mixer.set_value("/lr/mix/fader", [0]) # default: main LR fader to minimum
    for bus in range(6):
      mixer.set_value(f"/bus/{bus + 1}/config/name", [busses_dict[bus][0]])
      mixer.set_value(f"/bus/{bus + 1}/mix/fader", [mixer.db_to_float(busses_dict[bus][2])])
      mixer.set_value(f"/bus/{bus + 1}/config/color", [3]) # default: monitor busses are in yellow
      mixer.set_value(f"/bus/{bus + 1}/eq/on", [0])        # default: bus EQ off
      if len(busses_dict[bus]) > 3: # special bus settings
        if "LINK" in busses_dict[bus][3] and bus % 2 == 1:
          mixer.set_value(f"/config/buslink/{bus}-{bus + 1}", [1])
      for rtn in range(4):
        mixer.set_value(f"/rtn/{rtn + 1}/mix/{bus + 1:#02}/level", [0]) # default: FX level to lowest value
    for ch in channel_dict:
      inst_group = channel_dict[ch][5]
      set_gain(ch, channel_dict[ch][2])
      mixer.set_value(f"/ch/{ch + 1:#02}/config/color", [inst_group[0]])
      mixer.set_value(f"/ch/{ch + 1:#02}/config/name", [channel_dict[ch][0]])
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/fader", [mixer.db_to_float(channel_dict[ch][1])])
      mixer.set_value(f"/ch/{ch + 1:#02}/config/insrc", [ch]) # default: linear in/out mapping
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [1])        # default: send to LR master
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/on", [1])        # default: unmute channel
      mixer.set_value(f"/ch/{ch + 1:#02}/grp/mute", [0])      # default: no mute group
      mixer.set_value(f"/-stat/solosw/{ch + 1:#02}", [0])     # default: no Solo
      mixer.set_value(f"/ch/{ch + 1:#02}/grp/dca", [0])       # default: no DCA group
      mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [0])  # default: no phantom power
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/pan", [0.5])     # default: middle position
      mixer.set_value(f"/ch/{ch + 1:#02}/gate/on", [0])       # default: gate off
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/on", [0])        # default: compressor off
      mixer.set_value(f"/ch/{ch + 1:#02}/eq/on", [1])         # default: EQ on
      mixer.set_value(f"/ch/{ch + 1:#02}/preamp/hpon", [1])   # default: high-pass on
      mixer.set_value(f"/ch/{ch + 1:#02}/preamp/hpf", [mixer.freq_to_float(channel_dict[ch][3], 400)], False)
      for i in range(4):
        mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/type", [2]) # default: EQ, PEQ
        mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/g", [0.5])  # default: EQ, 0 dB gain
      for i in range(len(channel_dict[ch][4])): # individual channel EQ settings
        if len(channel_dict[ch][4][i]) > 2:
          mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/g", [(channel_dict[ch][4][i][0] + 15) / 30])
          mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/f", [mixer.freq_to_float(channel_dict[ch][4][i][1])])
          mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/q", [mixer.q_to_float(channel_dict[ch][4][i][2])])
        else: # special case: type and frequency
          mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/type", [channel_dict[ch][4][i][0]])
          mixer.set_value(f"/ch/{ch + 1:#02}/eq/{i + 1}/f", [mixer.freq_to_float(channel_dict[ch][4][i][1])])
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/keysrc", [0])            # default comp: key source SELF
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/mode", [0])              # default comp: compresser mode
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/auto", [0])              # default comp: auto compresser off
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/knee", [0.4])            # default comp: knee 2
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/det", [0])               # default comp: det PEAK
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/env", [1])               # default comp: env LOG
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/mix", [1.0])             # default comp: mix 100 %
      mixer.set_value(f"/ch/{ch + 1:#02}/dyn/thr", [1.0])             # default comp: threshold 0 dB
      if len(inst_group) > 1 and "VOCALDYN" in inst_group[1]:         # vocal dynamic presets:
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/on", [1])              # vocal default: compresser on
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/ratio", [5])           # vocal default: ratio 3
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/mgain", [0.25])        # vocal default: gain 6 dB
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/attack", [0.08333333]) # vocal default: attack 10 ms
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/hold", [0.54])         # vocal default: hold 10 ms
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/release", [0.45])      # vocal default: release 101 ms
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/filter/on", [1])       # vocal default: filter on
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/filter/type", [6])     # vocal default: filter type 3
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/filter/f", [0.495])    # vocal default: filter 611 Hz
      for bus in range(9):
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/{bus + 1:#02}/tap", [3]) # default: bus Pre Fader
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/{bus + 1:#02}/level", [0])
        if bus in busses_dict:
          mixer.set_value(f"/ch/{ch + 1:#02}/mix/{bus + 1:#02}/level", [mixer.db_to_float(busses_dict[bus][1][ch], True)])
      for bus in range(0, 6, 2): # adjust pan in send busses per channel (every second bus)
        if bus in busses_pan_dict:
          mixer.set_value(f"/ch/{ch + 1:#02}/mix/{bus + 1:#02}/pan", [(int(busses_pan_dict[bus][ch] / 2) + 50) / 100])
        else:
          mixer.set_value(f"/ch/{ch + 1:#02}/mix/{bus + 1:#02}/pan", [0.5]) # default: middle position
      if ch % 2 == 1:
        mixer.set_value(f"/config/chlink/{ch}-{ch + 1}", [0]) # default: no stereo link
      if len(channel_dict[ch]) > 6: # special channel settings
        if "NOMIX" in channel_dict[ch][6]:
          mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [0])
        if "PHANT" in channel_dict[ch][6]:
          mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [1])
        if "LINK" in channel_dict[ch][6] and ch % 2 == 1:
          mixer.set_value(f"/config/chlink/{ch}-{ch + 1}", [1])


def configure_rta(channel):
  mixer.set_value("/-prefs/rta/decay", [0])       # fastest possible decay
  mixer.set_value("/-prefs/rta/det", [0])         # 0: peak, 1: RMS
  mixer.set_value("/-stat/rta/source", [channel]) # note: zero-based channel number


def send_meters_request_message():
  while not exit_threads:
    mixer.set_value(f'/meters', ['/meters/2'], False) # ALL INPUTS
    mixer.set_value(f'/meters', ['/meters/4'], False) # RTA100
    mixer.set_value(f'/meters', ['/meters/6'], False) # ALL DYN
    if not exit_threads: time.sleep(1) # every second update meters request


# TEST
if use_recorded_data:
  f = open("_test.dat", mode="rb")
  data1 = numpy.reshape(numpy.fromfile(f, dtype=numpy.int16), (-1, 18))
  count = 60000
  f.close()


def receive_meter_messages():
  global mixer, input_values, input_rta, gatedyn_values, count
  while not exit_threads:
    message = mixer.get_msg_from_queue()
    if message.address == "/meters/2" or message.address == "/meters/4" or message.address == "/meters/6":
      data = bytearray(message.data[0])
      if len(data) >= 4:
        size = struct.unpack('i', data[:4])[0]
        (values, raw_values) = ([0] * size, [0] * size)
        for i in range(size):
          raw_values[i] = struct.unpack('h', data[4 + i * 2:4 + i * 2 + 2])[0] # signed integer 16 bit
          values[i]     = raw_values[i] / 256                                  # resolution 1/256 dB

        with data_mutex:
          if message.address == "/meters/2":

            # TEST NOTE: "global count" can be removed as soon as the TEST code is removed
            if use_recorded_data:
              values = data1[count] / 256
              count += 1

            all_raw_inputs_queue.append(raw_values[:len_meter2])
            input_values = values[:len_meter2]
            calc_histograms(input_values, input_histograms)
          elif message.address == "/meters/4":
            input_rta = values
          elif message.address == "/meters/6":
            gatedyn_values = values[16:16 + len_meter6] # note: cut out only dyn values -> offset of 16
            gatedyn_values = [-x - 128 for x in gatedyn_values] # invert values for max in histogram
            calc_histograms(gatedyn_values, gatedyn_histograms)
    else:
      # no meters message, put it back on queue and give other thread some time to process message
      mixer.put_msg_on_queue(message)
      time.sleep(0.01)


def calc_histograms(values, histograms):
  for i in range(len(values)):
    #values[i] = -128
    #print(int((values[i] + 128) / 129 * hist_len))
    histograms[i][int((values[i] + 128) / 129 * hist_len)] += 1

def analyze_histogram(histogram):
  max_data_index = len(histogram) - 1 # start value
  while histogram[max_data_index] == 0 and max_data_index > 0: max_data_index -= 1
  return (max_data_index, int(max_data_index / hist_len * 129 - 128))

def reset_histograms():
  global input_histograms, gatedyn_histograms
  with data_mutex:
    input_histograms   = [[0] * hist_len for i in range(len_meter2)]
    gatedyn_histograms = [[0] * hist_len for i in range(len_meter6)]




# TEST
def detect_feedback():
  with data_mutex: # lock mutex as short as possible
    input_rta_copy = input_rta
  max_index = numpy.argmax(input_rta_copy)
  if max_index > 1 and max_index < len(input_rta_copy) - 2:
    threshold_dB = 35
    max_value = input_rta_copy[max_index]
    if (input_rta_copy[max_index + 2] < max_value - threshold_dB and
        input_rta_copy[max_index - 2] < max_value - threshold_dB):
      # TODO check for how long the same max index is present (> 1 second, e.g.)
      print((max_value, max_index))




def gui_thread():
  global exit_threads, channel, is_input_hist
  window = tk.Tk(className="XR Auto Mix")
  window_color = window.cget("bg")
  (input_bars, input_labels, dyn_labels, rta_bars) = ([], [], [], [])
  (buttons_f, inputs_f, selection_f) = (tk.Frame(window), tk.Frame(window), tk.Frame(window))
  buttons_f.pack()
  inputs_f.pack()
  selection_f.pack()

  # buttons
  tk.Button(buttons_f, text="Reset Histograms",command=lambda: reset_histograms()).pack(side='left')
  tk.Button(buttons_f, text="Apply Gains",command=lambda: apply_optimal_gains()).pack(side='left')
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
    dyn_labels.append(tk.Label(f))
    dyn_labels[i].pack()

  # channel selection
  tk.Label(selection_f, text="Channel Selection:").pack(side='left')
  channel_sel = ttk.Combobox(selection_f)
  channel_sel['values'] = [f"{x}" for x in range(1, len_meter2 + 1)]
  channel_sel.current(13)#0)
  channel_sel.pack(side='left')
  tk.Label(selection_f, text="Histogram Input:").pack(side='left')
  hist_in_sel = ttk.Combobox(selection_f, values=("input", "dyn"))
  hist_in_sel.current(0)
  hist_in_sel.pack(side='left')

  # RTA/histogram
  rta = tk.Canvas(window, width=len_meter4 * rta_line_width + len_meter4, height=rta_hist_height)
  rta.pack()
  hist = tk.Canvas(window, width=hist_len * hist_line_width + hist_len, height=rta_hist_height)
  hist.pack()

  while not exit_threads:
    try:
      with data_mutex: # lock mutex as short as possible
        input_values_copy = input_values
        input_rta_copy    = input_rta
      for i in range(len_meter2):
        input_bars[i].set((input_values_copy[i] / 128 + 1) * 100)
        (max_data_index, max_data_value) = analyze_histogram(input_histograms[i])
        if max_data_value > target_max_gain + 6:
          input_labels[i].config(text=max_data_value, bg="red")
        else:
          if max_data_value > target_max_gain:
            input_labels[i].config(text=max_data_value, bg="yellow")
          else:
            input_labels[i].config(text=max_data_value, bg=window_color)
      for i in range(len_meter6):
        (max_data_index, max_data_value) = analyze_histogram(gatedyn_histograms[i])
        max_data_value = 128 + max_data_value # values were inverted
        if max_data_value > 9:
          dyn_labels[i].config(text=max_data_value, bg="red")
        else:
          if max_data_value > 6:
            dyn_labels[i].config(text=max_data_value, bg="yellow")
          elif max_data_value > 0: # do not show any number if dyn is not used
            dyn_labels[i].config(text=max_data_value, bg=window_color)

      rta.delete("all")
      for i in range(len_meter4):
        x = rta_line_width + i * rta_line_width + i
        y = (input_rta_copy[i] / 128 + 1) * rta_hist_height
        rta.create_line(x, rta_hist_height, x, rta_hist_height - y, fill="#476042", width=rta_line_width)

      if is_input_hist:
        histogram = input_histograms[channel]
      else:
        histogram = gatedyn_histograms[min(len_meter6 - 1, channel)]
      (max_data_index, max_data_value) = analyze_histogram(histogram)
      max_hist  = max(histogram)
      max_index = numpy.argmax(histogram)
      if max_hist > 0:
        hist.delete("all")
        for i in range(hist_len):
          x = hist_line_width + i * hist_line_width + i
          y = histogram[i] * rta_hist_height / max_hist
          color = "blue" if i == max_index else "red" if i == max_data_index else "#476042"
          hist.create_line(x, rta_hist_height, x, rta_hist_height - y, fill=color, width=hist_line_width)

      if int(channel_sel.get()) - 1 is not channel:
        channel = int(channel_sel.get()) - 1
        #configure_rta(channel) # configure_rta(31) # 31: MainLR on XAIR16
      if (hist_in_sel.get() == "input") is not is_input_hist:
        is_input_hist = bool(hist_in_sel.get() == "input")

      # TEST
      detect_feedback()

      window.update()
      time.sleep(meter_update_s)
    except:
      exit_threads = True


def store_input_levels_in_file():
  # Octave: h=fopen('test.dat','rb');x=fread(h,Inf,'int16');fclose(h);x=reshape(x,18,[])/256;close all;plot(x.')
  while not exit_threads:
    with data_mutex:
      cur_list_data = [] # just do copy in mutex and not the actual file storage
      while all_raw_inputs_queue:
        cur_list_data.append(all_raw_inputs_queue.popleft())
    with open(file_path, "ab") as file:
      for data in cur_list_data:
        file.write(struct.pack('%sh' % len(data), *data))
    if not exit_threads: time.sleep(1) # every second append logging file


if __name__ == '__main__':
  main()


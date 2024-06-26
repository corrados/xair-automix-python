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

import sys, threading, time, struct, numpy, easygui
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
channel_dict = { \
   0:["Click",      -90,  1.5, 101, [],                                                       special, ["NOMIX"]], \
   1:["E-Git Mono", -90,   11, 101, [],                                                       guitar], \
   2:["Stefan",       0,   26, 121, [],                                                       vocal], \
   3:["Miguel",      -2,   28, 121, [[4, 124.7, 1], [-3.5, 2340, 2]],                         vocal], \
   4:["Chris",       -2, 18.5, 121, [[1.25, 1260, 2], [1.75, 3680, 2]],                       vocal], \
   5:["E-Bass",       0,    0,  25, [],                                                       bass], \
   6:["E-Git L",     -2,    9, 101, [],                                                       guitar], \
   7:["E-Git R",     -2,    9, 101, [],                                                       guitar, ["LINK"]], \
   8:["Akustik",     -5,    1, 101, [],                                                       guitar], \
   9:["Kick",         0,    6,  25, [[3, 58.3, 2], [-3.75, 158.9, 1.4], [5.75, 3090, 2]],     drums, ["PHANT"]], \
  10:["Snare",        0,    3, 101, [[-3, 232.3, 3.1], [-2.5, 990.9, 3.5], [3, 7090, 2]],     drums], \
  11:["Tom1",         0,    3,  40, [[3, 133.7, 1.8], [-6.25, 701.5, 1.1], [4.5, 3200, 1.7]], drums], \
  12:["Tom2",         0,    3,  25, [[4, 85.3, 2], [-6.75, 550.8, 0.7], [4.25, 3430, 2]],     drums], \
  13:["OverH",       -2,  7.5, 101, [[0, 1490]],                                              drums, ["PHANT"]], \
  14:["E-Drum(L)",    0,    5,  25, [],                                                       edrums], \
  15:["E-Drum(R)",    0,    5,  25, [],                                                       edrums, ["LINK"]]}
#                     Cli  E-M  Stef  Mig Chri Bass E-L  E-R A-Git Kick Snare T1   T2   OvH ED-L ED-R
busses_dict = { \
  0:["Stefan Mon",   [-90,  -4, -90,   0,   0,   0, -90, -90, -90, -12, -17, -17, -17, -12,  -6,  -6], -10          ], \
  1:["Chris Mon",    [-90, -90,  -7,  -7, -90, -10, -90, -90,  -4,  -4,  -8,  -8,  -8,  -4,  -4,  -4], -10          ], \
  2:["Miguel Mon L", [-90, -90, -17, -11, -15,   0, -25, -25, -25, -11, -50, -50, -50, -23, -20, -20], -10          ], \
  3:["Miguel Mon R", [-90, -90, -17, -11, -15,   0, -25, -25, -25, -11, -50, -50, -50, -23, -20, -20], -10, ["LINK"]], \
  4:["Volker Mon L", [  0, -90, -15, -15, -15, -17, -17, -17, -22,   0,   0,   0,   0,   0,   0,   0], -10          ], \
  5:["Volker Mon R", [  0, -90, -15, -15, -15, -17, -17, -17, -22,   0,   0,   0,   0,   0,   0,   0], -10, ["LINK"]], \
  6:["FX1",          [-90, -90, -90, -19, -24, -90, -90, -90, -90, -90, -90, -90, -90, -32, -90, -90],   0          ], \
  7:["FX2",          [-90, -90, -90, -90, -90, -90, -90, -90, -90, -21,  -8,  -6,  -6, -90, -90, -90],   0          ]}
busses_pan_dict = { \
  2:[0, 0, -30, 60, -94, 44, -100,  32, -40, 0, 0,   0,  0, -46, -100, 100], \
  4:[0, 0,  20, 42, -50,  0, -100, 100,  40, 0, 0, -18, 18,   0, -100, 100]}

use_recorded_data     = False # TEST
target_max_gain       = -15 # dB
set_gain_input_thresh = -50 # dB
no_input_threshold    = -80 # dB
dyn_thresh            = target_max_gain - 6 - 10 # target -6 dB reduction minus additional "magic number"
feedback_threshold_dB = 30

channel              = 0    # initialization value for channel selection
len_meter2           = 18   # ALL INPUTS (16 mic, 2 aux, 18 usb = 36 values total but we only need the mic inputs)
len_meter4           = 100  # RTA100 (100 bins RTA = 100 values)
len_meter6           = 16   # ALL DYN (16 gate, 16 dyn(ch), 6 dyn(bus), dyn(lr) = 39 values total but we want 16 dyn only)
hist_len             = 128  # histogram bins
rta_hist_height      = 120
meter_update_s       = 0.05 # update cycle frequency for meter data is 50 ms
min_feedback_count   = 0.4 / meter_update_s # minimum 0.4 s feedback duration
rta_line_width       = 3
hist_line_width      = 3
is_XR16              = False
exit_threads         = False
do_feedback_cancel   = False
file_path            = "test.dat"
input_values         = [0] * len_meter2
input_rta            = [0] * len_meter4
feedback_count       = [0] * len_meter4
all_raw_inputs_queue = deque()
data_mutex           = threading.Lock()


def main():
  global mixer, is_XR16
  reset_histograms()
  mixer   = x32.BehringerX32([], 10300, False, 4) # initialized and search for a mixer
  is_XR16 = "XR16" in mixer.get_value("/info")[2]
  configure_rta(31) # 31: MainLR on XAIR16
  # start separate threads
  threading.Timer(0.0, send_meters_request_message).start()
  threading.Timer(0.0, receive_meter_messages).start()
  threading.Timer(0.0, store_input_levels_in_file).start()
  threading.Timer(0.0, gui_thread).start()


def apply_optimal_gain(ch, reset=True):
  with data_mutex:
    max_value = input_max_values[ch]
    if max_value > no_input_threshold:
      mixer.set_value(f"/ch/{ch + 1:#02}/mix/on", [1]) # unmute channel
      if max_value > set_gain_input_thresh:
        set_gain(ch, float(get_gain(ch) - (max_value - target_max_gain)))
    else:
      pass # disabled mute for now
      #mixer.set_value(f"/ch/{ch + 1:#02}/mix/on", [0]) # mute channel with no input level
  if reset:
    reset_histograms(ch) # history needs to be reset on updated gain settings


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
    value = max(0, min(0.9861111, (x + 12) / (60 - (-12))))
    mixer.set_value(f"/headamp/{ch + 1:#02}/gain", [value])
    return value * (60 - (-12)) - 12


def basic_setup_mixer(mixer):
  if easygui.ynbox('Are you sure to reset all mixer settings?', 'Reset All Check', ['Yes', 'No']):
    try:
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
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/on", [1])        # default: unmute channel
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/fader", [mixer.db_to_float(channel_dict[ch][1])]) # note: unmute necessary
        mixer.set_value(f"/ch/{ch + 1:#02}/config/insrc", [ch]) # default: linear in/out mapping
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [1])        # default: send to LR master
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
        mixer.set_value(f"/ch/{ch + 1:#02}/dyn/thr", [(dyn_thresh + 60) / 60]) # default comp: pre-defined threshold
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
        for bus in range(10):
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
        mixer.set_value("/fx/1/type", [0])                # default: FX1 Hall Reverb (for vocals)
        mixer.set_value("/fx/1/par/01", [0.1])            # default: FX1 PRE DEL 20 ms
        mixer.set_value("/fx/1/par/02", [0.64])           # default: FX1 DECAY 1.57 s
        mixer.set_value("/fx/1/par/03", [0.59183675])     # default: FX1 SIZE 60
        mixer.set_value("/fx/1/par/04", [0.58333333])     # default: FX1 DAMP 5k74 Hz
        mixer.set_value("/fx/1/par/05", [0.82758623])     # default: FX1 DIFF 25
        mixer.set_value("/fx/1/par/06", [0.5])            # default: FX1 LEVEL 0 dB
        mixer.set_value("/fx/2/type", [3])                # default: FX2 Room Reverb (for drums)
        mixer.set_value("/fx/2/par/01", [0.03])           # default: FX2 PRE DEL 6 ms
        mixer.set_value("/fx/2/par/02", [0.08])           # default: FX2 DECAY 0.43 s
        mixer.set_value("/fx/2/par/03", [0.19444444])     # default: FX2 SIZE 18 m
        mixer.set_value("/fx/2/par/04", [0.45833334])     # default: FX2 DAMP 3k94 Hz
        mixer.set_value("/fx/2/par/05", [0.68])           # default: FX2 DIFF 68 %
        mixer.set_value("/fx/2/par/06", [0.5])            # default: FX2 LEVEL 0 dB
        mixer.set_value("/rtn/1/mix/fader", [0.74975562]) # default:   0 dB return level for FX1 (vocal)
        mixer.set_value("/rtn/2/mix/fader", [0.74975562]) # default:   0 dB return level for FX2 (drums)
        mixer.set_value("/rtn/3/mix/fader", [0])          # default: -90 dB return level for FX3 (not used)
        mixer.set_value("/rtn/4/mix/fader", [0])          # default: -90 dB return level for FX4 (not used)
        mixer.set_value("/config/solo/source", [14])      # default: monitor source BUS 5/6 (monitor Volker)
        mixer.set_value("/lr/eq/on", [0])                 # default: master EQ off
        mixer.set_value("/lr/eq/mode", [0])               # default: PEQ for master EQ, needed for feedback cancellation
        for i in range(6):
          mixer.set_value(f"/lr/eq/{i + 1}/g", [0.5])     # default: master EQ Gain 0 dB
        if len(channel_dict[ch]) > 6: # special channel settings
          if "NOMIX" in channel_dict[ch][6]:
            mixer.set_value(f"/ch/{ch + 1:#02}/mix/lr", [0])
          if "PHANT" in channel_dict[ch][6]:
            mixer.set_value(f"/headamp/{ch + 1:#02}/phantom", [1])
          if "LINK" in channel_dict[ch][6] and ch % 2 == 1:
            mixer.set_value(f"/config/chlink/{ch}-{ch + 1}", [1])
    except:
      easygui.msgbox('Reset failed!')


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
  global mixer, input_values, input_max_values, input_rta, gatedyn_min_values, count
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
            input_max_values = numpy.maximum(input_max_values, input_values)
            calc_histograms(input_values, input_histograms)
          elif message.address == "/meters/4":
            input_rta = values
          elif message.address == "/meters/6":
            gatedyn_min_values = numpy.minimum(gatedyn_min_values, values[16:16 + len_meter6]) # dyn: 16..31
    else:
      # no meters message, put it back on queue and give other thread some time to process message
      mixer.put_msg_on_queue(message)
      time.sleep(0.01)


def calc_histograms(values, histograms):
  for i in range(len(values)):
    histograms[i][min(127, round((values[i] + 128) / 128 * hist_len))] += 1

def reset_histograms(ch = []):
  global input_histograms, input_max_values, gatedyn_min_values
  with data_mutex:
    if ch:
      input_histograms[ch]   = [0] * hist_len
      input_max_values[ch]   = -128
      gatedyn_min_values[ch] = 0
    else:
      input_histograms   = [[0] * hist_len for i in range(len_meter2)]
      input_max_values   = [-128] * len_meter2
      gatedyn_min_values = [0] * len_meter6


def switch_feedback_cancellation():
  global do_feedback_cancel
  do_feedback_cancel = not do_feedback_cancel


def detect_and_cancel_feedback():
  global feedback_count
  with data_mutex: # lock mutex as short as possible
    input_rta_copy = input_rta # TODO access to vectdor is arbitrary, queue would be better (would require a loop here)
  max_index = numpy.argmax(input_rta_copy)
  if max_index > 1 and max_index < len_meter4 - 2:
    max_value = input_rta_copy[max_index]
    if (input_rta_copy[max_index + 2] < max_value - feedback_threshold_dB and
        input_rta_copy[max_index - 2] < max_value - feedback_threshold_dB):
      feedback_count[max_index] += 1
      if any(x >= min_feedback_count for x in feedback_count):
        f = numpy.exp(max_index / len_meter4 * numpy.log(20000 / 20)) * 20 # inverse of mixer.freq_to_float
        for i in range(6):
          if mixer.get_value(f"/lr/eq/{i + 1}/g")[0] == 0.5: # find free EQ band
            print(f"Feedback cancelled at frequency: {f}")
            mixer.set_value(f"/lr/eq/{i + 1}/type", [2]) # PEQ
            mixer.set_value(f"/lr/eq/{i + 1}/q", [0])    # EQ Quality 10 (minimum width)
            mixer.set_value(f"/lr/eq/{i + 1}/g", [0.4])  # gain to -3 dB
            mixer.set_value(f"/lr/eq/{i + 1}/f", [mixer.freq_to_float(f)])
            mixer.set_value("/lr/eq/on", [1])
            break;
        feedback_count = [0 for x in feedback_count] # clear all counts
    else:
      feedback_count = [0 for x in feedback_count] # clear all counts


def change_channel(c):
  global channel
  channel = int(c)


def apply_optimal_gains():
  for ch in range(len(channel_dict)):
    apply_optimal_gain(ch, reset=False)
  reset_histograms() # history needs to be reset on updated gain settings


def gui_thread():
  global exit_threads, channel
  window = tk.Tk(className="XR Auto Mix")
  window_color = window.cget("bg")
  (input_bars, input_labels, dyn_labels, rta_bars) = ([], [], [], [])
  radio_button_var = tk.StringVar(window, channel)
  (buttons_f, inputs_f, selection_f) = (tk.Frame(window), tk.Frame(window), tk.Frame(window))
  buttons_f.pack()
  inputs_f.pack()
  selection_f.pack()

  # buttons
  tk.Button(buttons_f, text="Reset Histograms", command=lambda: reset_histograms()).pack(side='left')
  tk.Button(buttons_f, text="Apply All Gains", command=lambda: apply_optimal_gains()).pack(side='left')
  tk.Button(buttons_f, text="Apply Selected Gain", command=lambda: apply_optimal_gain(channel)).pack(side='left')
  b_feedback = tk.Button(buttons_f, text="Feedback Cancellation", command=lambda: switch_feedback_cancellation())
  b_feedback.pack(side='left')
  tk.Button(buttons_f, text="Reset All", command=lambda: basic_setup_mixer(mixer)).pack(side='left')

  # input level meters
  for i in range(len_meter2):
    f = tk.Frame(inputs_f)
    f.pack(side="left", pady='5')
    if i < len(channel_dict):
      tk.Radiobutton(f, value=i, indicatoron=0, variable=radio_button_var, \
        command=lambda: change_channel(radio_button_var.get()), text=f"{i + 1}\n{channel_dict[i][0]}").pack()
    else:
      tk.Radiobutton(f, value=i, indicatoron=0, variable=radio_button_var, \
        command=lambda: change_channel(radio_button_var.get()), text=f"{i + 1}\n").pack()
    input_bars.append(tk.DoubleVar(window))
    ttk.Progressbar(f, orient=tk.VERTICAL, variable=input_bars[i]).pack()
    input_labels.append(tk.Label(f))
    input_labels[i].pack()
    dyn_labels.append(tk.Label(f))
    dyn_labels[i].pack()

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
      for ch in range(len_meter2):
        input_bars[ch].set((input_values_copy[ch] / 128 + 1) * 100)
        max_value = int(numpy.ceil(input_max_values[ch]))
        if max_value > target_max_gain + 6:
          input_labels[ch].config(text=max_value, bg="red")
        else:
          if (max_value > set_gain_input_thresh and max_value < target_max_gain - 6) or max_value > target_max_gain + 3:
            input_labels[ch].config(text=max_value, bg="yellow")
          else:
            input_labels[ch].config(text=max_value, bg=window_color)
      for ch in range(len_meter6):
        max_value = int(numpy.round(-gatedyn_min_values[ch]))
        if max_value > 9:
          dyn_labels[ch].config(text=max_value, bg="red")
        else:
          if max_value > 6:
            dyn_labels[ch].config(text=max_value, bg="yellow")
          elif max_value > 0:
            dyn_labels[ch].config(text=max_value, bg=window_color)
          else: # do not show any number if dyn is not used
            dyn_labels[ch].config(text="", bg=window_color)

      rta.delete("all")
      for i in range(len_meter4):
        x = rta_line_width + i * rta_line_width + i
        y = (input_rta_copy[i] / 128 + 1) * rta_hist_height
        rta.create_line(x, rta_hist_height, x, rta_hist_height - y, fill="#476042", width=rta_line_width)

      max_hist  = max(input_histograms[channel])
      max_index = numpy.argmax(input_histograms[channel])
      if max_hist > 0:
        hist.delete("all")
        for i in range(hist_len):
          x = hist_line_width + i * hist_line_width + i
          y = input_histograms[channel][i] * rta_hist_height / max_hist
          color = "blue" if i == max_index else "#476042"
          hist.create_line(x, rta_hist_height, x, rta_hist_height - y, fill=color, width=hist_line_width)

      if do_feedback_cancel:
        b_feedback.config(bg="red")
        detect_and_cancel_feedback()
      else:
        b_feedback.config(bg=window_color)

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


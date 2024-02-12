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

import sys, threading, time, socket, struct, queue
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
import numpy as np
from pythonx32 import x32
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

found_addr = -1
channel = 10; # TEST


def main():
  global found_addr, found_port, fader_init_val, bus_init_val, mixer

  # search for a mixer and initialize the connection to the mixer
  local_port  = 10300
  #addr_subnet = '.'.join(get_ip().split('.')[0:3]) # only use first three numbers of local IP address
  #while found_addr < 0:
  #  for j in range(10024, 10022, -1): # X32:10023, XAIR:10024 -> check both
  #    if found_addr < 0:
  #      for i in range(2, 255):
  #        threading.Thread(target = try_to_ping_mixer, args = (addr_subnet, local_port + 1, i, j, )).start()
  #        if found_addr >= 0:
  #          break
  #    if found_addr < 0:
  #      time.sleep(2) # time-out is 1 second -> wait two-times the time-out

  # TEST
  found_port = 10023
  addr_subnet = '127.0.0'
  found_addr = '1'

  mixer = x32.BehringerX32(f"{addr_subnet}.{found_addr}", local_port, False, 10, found_port)

  basic_setup_mixer(mixer)

  # separate thread for sending meters queries every second
  threading.Timer(0.0, send_meters_request_message).start()

  fig = plt.figure(tight_layout=True)
  gs  = gridspec.GridSpec(2, 1)
  ax0 = fig.add_subplot(gs[0, 0])
  ax1 = fig.add_subplot(gs[1, 0])
  plt.ion()
  all_inputs_queue = queue.Queue()
  rta_queue        = queue.Queue()

  for i in range(0, 10):
    cur_message = mixer.get_msg_from_queue()
    mixer_cmd = cur_message.address
    mixer_data = bytearray(cur_message.data[0])

    num_bytes = len(mixer_data)
    if num_bytes >= 4:
      size = struct.unpack('i', mixer_data[0:4])[0]
      values = [0] * size
      for i in range(0, size):
        cur_bytes = mixer_data[4 + i * 2:4 + i * 2 + 2]
        values[i] = struct.unpack('h', cur_bytes)[0] / 256 # signed integer 16 bit, resolution 1/256 dB

      if mixer_cmd == "/meters/2":
        all_inputs_queue.put(values)
        ax0.cla()
        ax0.set_title("ALL INPUTS")
        cur_ax = ax0
      elif mixer_cmd == "/meters/4":
        rta_queue.put(values)
        ax1.cla()
        ax1.set_title("RTA100")
        cur_ax = ax1
      #cur_ax.plot(values)
      cur_ax.bar(range(0, size), values)
      cur_ax.grid(True)
      #cur_ax.set_ylim(ymin=0, ymax=1)
      plt.show()
      plt.pause(0.01)

  # TEST
  print(list(all_inputs_queue.queue))

  del mixer # to exit other thread


def basic_setup_mixer(mixer):
  vocal   = [9]
  guitar  = [11]
  bass    = [10]
  edrums  = [13]
  drums   = [12]
  special = [0]
  channel_dict = { 0:["Click", special, ["NOMIX"]], 1:["E-Git Mono", guitar], \
                   2:["Stefan", vocal],             3:["Miguel", vocal],           4:["Chris", vocal], \
                   5:["Bass", bass],                6:["E-Git L", guitar],         7:["E-Git R", guitar], \
                   8:["A-Git", guitar],             9:["Kick", drums, ["PHANT"]], 10:["Snare", drums], \
                  11:["Tom1", drums],              12:["Tom2", drums],            13:["Overhead", drums, ["PHANT"]], \
                  14:["E-Drum L", edrums],         15:["E-Drum R", edrums]}
  for ch in channel_dict:
    inst_group = channel_dict[ch][1]
    mixer.set_value(f"/ch/{ch + 1:#02}/config/color", [inst_group[0]], True)
    mixer.set_value(f"/ch/{ch + 1:#02}/config/name", [channel_dict[ch][0]], True)
    if len(channel_dict[ch]) > 2: # special channel settings
      if "NOMIX" in channel_dict[ch][2]:
        mixer.set_value(f"/ch/{ch + 1:#02}/mix/st", [0], True)
      if "PHANT" in channel_dict[ch][2]:
        pass#mixer.set_value(f"/ch/{ch + 1:#02}/TODO", [0], True) # TODO find out command for phantom power

    # TODO do a factory preset instead of resetting parameters manually
    mixer.set_value(f"/ch/{ch + 1:#02}/mix/pan", [0.5], True) # middle position per default

  # stereo link E-Git and E-Drum
  mixer.set_value(f"/config/chlink/7-8", [1], True)   # stereo E-Git
  mixer.set_value(f"/config/chlink/15-16", [1], True) # stereo E-Drums

def send_meters_request_message():
  global mixer
  try:
    while True:
      #mixer.set_value(f'/meters', ['/meters/0', channel], False) # 8 channel meters
      #mixer.set_value(f'/meters', ['/meters/1'], False)          # ALL CHANNELS
      mixer.set_value(f'/meters', ['/meters/2'], False)          # ALL INPUTS
      mixer.set_value(f'/meters', ['/meters/4'], False)          # RTA100
      #mixer.set_value(f'/meters', ['/meters/5'], False)          # ALL OUTPUTS
      time.sleep(1) # every second update meters request
  except:
    pass


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


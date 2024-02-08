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

import sys, threading, time, socket, struct
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
import numpy as np
from pythonx32 import x32
import matplotlib.pyplot as plt

found_addr = -1
channel = 10; # TEST

def main():
  global found_addr, found_port, fader_init_val, bus_init_val, mixer

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

  mixer = x32.BehringerX32(f"{addr_subnet}.{found_addr}", local_port, False, 10, found_port)

  # separate thread for sending meters queries every second
  threading.Timer(0.0, send_meters_request_message).start()

  fig, ax = plt.subplots()
  plt.ion()
  for i in range(0, 30):
    mixerdata = mixer.get_msg_from_queue().data
    mixerdata1 = bytearray(mixer.get_msg_from_queue().data[0])

    num_bytes = int(len(mixerdata[0]) / 4)
    values = [0] * num_bytes
    for i in range(1, num_bytes):
      cur_bytes = mixerdata1[i * 4:i * 4 + 4]
      values[i] = struct.unpack('i', cur_bytes)[0] / 2147483647 + 1

    ax.cla()
    #ax.plot(values)
    ax.bar(range(0, num_bytes), values)
    ax.grid(True)
    ax.set_ylim(ymin=0, ymax=1)
    plt.show()
    plt.pause(0.02)

  del mixer # to exit other thread


def send_meters_request_message():
  global mixer
  try:
    while True:
      #mixer.set_value(f'/meters', ['/meters/1'], False)             # 21 vs 96
      mixer.set_value(f'/meters', ['/meters/2'], False)             # 19 vs 49    -> all channels?
      #mixer.set_value(f'/meters', ['/meters/3'], False)             # 29 vs 22
      #mixer.set_value(f'/meters', ['/meters/4'], False)             # 51 vs 82    -> RTA?
      #mixer.set_value(f'/meters', ['/meters/5', channel, 0], False) # 23 vs 27
      #mixer.set_value(f'/meters', ['/meters/6', channel], False)    # 20.5 vs 4
      #mixer.set_value(f'/meters', ['/meters/7'], False)             # 9 vs 16
      #mixer.set_value(f'/meters', ['/meters/8'], False)             # 3 vs 6
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


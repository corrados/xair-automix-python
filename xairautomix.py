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

import sys
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
import threading
import time
import socket
import numpy as np
from pythonx32 import x32
import struct
import matplotlib.pyplot as plt

found_addr = -1

def main():
  global found_addr, found_port, fader_init_val, bus_init_val

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

  #print(addr_subnet)
  #print(found_addr)
  mixer = x32.BehringerX32(f"{addr_subnet}.{found_addr}", local_port, False, 10, found_port)

  bus_ch = 5; # define here the bus channel you want to control
  channel = 10; # TEST
  value = 0.5; # TEST

  # TEST
  #query_all_faders(mixer, bus_ch)
  #print(fader_init_val)
  #print(bus_init_val)

  # TEST
  #mixer.set_value(f'/ch/{channel:#02}/mix/fader', [value], False)
  #mixer.set_value(f'/ch/{channel:#02}/mix/{bus_ch:#02}/level', [value], False)
  #mixer.set_value(f'/ch/{channel:#02}/mix/pan', [value], False)

  #mixer.set_value(f'/meters', ['/meters/1'], False)             # 21 vs 96
  mixer.set_value(f'/meters', ['/meters/2'], False)             # 19 vs 49
  #mixer.set_value(f'/meters', ['/meters/3'], False)             # 29 vs 22
  #mixer.set_value(f'/meters', ['/meters/4'], False)             # 51 vs 82    -> RTA?
  #mixer.set_value(f'/meters', ['/meters/5', channel, 0], False) # 23 vs 27
  #mixer.set_value(f'/meters', ['/meters/6', channel], False)    # 20.5 vs 4
  #mixer.set_value(f'/meters', ['/meters/7'], False)             # 9 vs 16
  #mixer.set_value(f'/meters', ['/meters/8'], False)             # 3 vs 6


  fig, ax = plt.subplots()
  plt.ion()
  for i in range(0, 30):
    #print(mixer.get_msg_from_queue().address)
    mixerdata = mixer.get_msg_from_queue().data
    mixerdata1 = bytearray(mixer.get_msg_from_queue().data[0])

    #print('{:08b}'.format(105))
    #print(int('{:08b}'.format(105), 2))
    #print('{:08b}'.format(105)[::-1])
    #print(int('{:08b}'.format(105)[::-1], 2))

    #cur_byte = 105
    #cur_byte_bit_reversed = bit_reverse_cur_byte(cur_byte) # int('{:08b}'.format(cur_byte)[::-1], 2)
    #print(cur_byte)
    #print(cur_byte_bit_reversed)
    #print(mixerdata1[0:4].hex())

    #print(mixerdata1.hex())
    #for cnt in range(0, len(mixerdata1)): # reverse bits in one byte
    #  mixerdata1[cnt] = bit_reverse_cur_byte(mixerdata1[cnt])
    #print(mixerdata1.hex())
    #for cnt in range(0, int(len(mixerdata1) / 4)): # reverse 4 bytes
    #  s = cnt * 4
    #  tmp = mixerdata1[s]
    #  mixerdata1[s] = mixerdata1[s + 3]
    #  mixerdata1[s + 3] = tmp
    #  tmp = mixerdata1[s + 1]
    #  mixerdata1[s + 1] = mixerdata1[s + 2]
    #  mixerdata1[s + 2] = tmp
    #print(mixerdata1.hex())


    #print(len(mixerdata))
    num_bytes = int(len(mixerdata[0]) / 4)
    #print(num_bytes)
    #print(mixerdata[0].hex())
    #print(mixerdata[0][0])
    #for cur_byte in mixerdata[0]:
    #  print(cur_byte.hex())
    offset = 0
    values = [0] * (num_bytes - offset)
    for i in range(1, num_bytes - offset):
      cur_bytes = mixerdata1[offset + i * 4:offset + i * 4 + 4]
      #cur_bytes = mixerdata[0][offset + i * 4:offset + i * 4 + 4]
      #cur_bytes = cur_bytes[::-1]
      #cur_bytes = bytearray(b'\x3e\xed\xfa\x44')
      #print(cur_bytes.hex())
      # from OSC library: struct.unpack(">f", data[0:4])[0]
      values[i] = struct.unpack('i', cur_bytes)[0] / 2147483647 + 1
      #print(values[i])
    #print(values)

    ## TEST
    #values = [0] * num_bytes
    #for i in range(0, num_bytes):
    #  values[i] = struct.unpack('f', mixerdata[0][i * 4:i * 4 + 4])[0]

    # TEST
    #print('***')
    #print(struct.unpack('>f', bytes.fromhex('00800080')))
    ax.cla()
    #ax.plot(10 * np.log10(-np.array(values)))
    #ax.plot(values)
    ax.bar(range(0, num_bytes - offset), values)
    ax.grid(True)
    ax.set_ylim(ymin=0, ymax=1)
    plt.show()
    plt.pause(0.2)


  # TEST
  #query_all_faders(mixer, bus_ch)
  #print(fader_init_val)
  #print(bus_init_val)


def bit_reverse_cur_byte(data):
  return int('{:08b}'.format(data)[::-1], 2)

def query_all_faders(mixer, bus_ch): # query all current fader values
    global fader_init_val, bus_init_val
    fader_init_val = [0] * 9 # nanoKONTROL has 9 faders
    bus_init_val   = [0] * 9
    for i in range(8):
      fader_init_val[i] = mixer.get_value(f'/ch/{i + 1:#02}/mix/fader')[0]
      bus_init_val[i]   = mixer.get_value(f'/ch/{i + 1:#02}/mix/{bus_ch:#02}/level')[0]

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



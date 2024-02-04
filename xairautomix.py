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
from pythonx32 import x32
import struct

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

  print(addr_subnet)
  print(found_addr)
  mixer = x32.BehringerX32(f"{addr_subnet}.{found_addr}", local_port, False, 10, found_port)

  bus_ch = 5; # define here the bus channel you want to control
  channel = 0; # TEST
  value = 0.5; # TEST

  # TEST
  query_all_faders(mixer, bus_ch)
  print(fader_init_val)
  print(bus_init_val)

  # TEST
  #mixer.set_value(f'/ch/{channel:#02}/mix/fader', [value], False)
  #mixer.set_value(f'/ch/{channel:#02}/mix/{bus_ch:#02}/level', [value], False)
  #mixer.set_value(f'/ch/{channel:#02}/mix/pan', [value], False)

  #mixer.set_value(f'/meters', ['/meters/1'], False)             # 21 vs 96
  #mixer.set_value(f'/meters', ['/meters/2'], False)             # 19 vs 49
  #mixer.set_value(f'/meters', ['/meters/3'], False)             # 29 vs 22
  #mixer.set_value(f'/meters', ['/meters/4'], False)             # 51 vs 82
  #mixer.set_value(f'/meters', ['/meters/5', channel, 0], False) # 23 vs 27
  mixer.set_value(f'/meters', ['/meters/6', channel], False)     # 20.5 vs 4
  #mixer.set_value(f'/meters', ['/meters/7'], False)             # 9 vs 16
  #mixer.set_value(f'/meters', ['/meters/8'], False)             # 3 vs 6
  print(mixer.get_msg_from_queue().address)
  mixerdata = mixer.get_msg_from_queue().data
  print(len(mixerdata))
  print(len(mixerdata[0]) / 4)
  print(mixerdata)
  #for i in range(0, int(len(mixerdata[0]) / 4)):
  #  print(struct.unpack('f', mixerdata[0][i * 4:i * 4 + 4]))

  # TEST
  #query_all_faders(mixer, bus_ch)
  #print(fader_init_val)
  #print(bus_init_val)


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



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

import sys
sys.path.append('python-x32/src')
sys.path.append('python-x32/src/pythonx32')
import threading
import time
import socket
from pythonx32 import x32

found_addr = -1

def main():
  global found_addr, found_port, fader_init_val, bus_init_val

  try:
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

    # parse MIDI inevents
    bus_ch          = 5; # define here the bus channel you want to control
    MIDI_table      = nanoKONTROL_MIDI_lookup() # create MIDI table for nanoKONTROL
    MIDI_statusbyte = 0
    cur_SCENE       = -1
    while True:
      try:
        event = client.event_input(prefer_bytes = True)
      except KeyboardInterrupt:
          raise KeyboardInterrupt
      except:
        client.drop_input() # fix "ALSAError: No space left on device"
        continue # avoid "UnboundLocalError: local variable 'event' referenced before assignment"

      if event is not None and isinstance(event, MidiBytesEvent):
        if len(event.midi_bytes) == 3:
          # status byte has changed
          MIDI_statusbyte = event.midi_bytes[0]
          MIDI_databyte1  = event.midi_bytes[1]
          MIDI_databyte2  = event.midi_bytes[2]
        elif len(event.midi_bytes) == 2:
          MIDI_databyte1  = event.midi_bytes[0]
          MIDI_databyte2  = event.midi_bytes[1]

        if len(event.midi_bytes) == 2 or len(event.midi_bytes) == 3:
          # send corresponding OSC commands to the mixer
          c = (MIDI_statusbyte, MIDI_databyte1)
          if c in MIDI_table:
            channel = MIDI_table[c][2] + 1
            value   = MIDI_databyte2 / 127
            # reset fader init values if SCENE has changed
            if cur_SCENE is not MIDI_table[c][0]:
              query_all_faders(mixer, bus_ch)
              cur_SCENE = MIDI_table[c][0]

            if MIDI_table[c][0] == 0 and MIDI_table[c][1] == "f": # fader in first SCENE
              ini_value = fader_init_val[channel - 1]
              # only apply value if current fader value is not too far off
              if ini_value < 0 or (ini_value >= 0 and abs(ini_value - value) < 0.01):
                fader_init_val[channel - 1] = -1 # invalidate initial value
                mixer.set_value(f'/ch/{channel:#02}/mix/fader', [value], False)
                threading.Thread(target = switch_pi_board_led, args = (False, )).start() # takes time to process
              else:
                threading.Thread(target = switch_pi_board_led, args = (True, )).start() # takes time to process

            if MIDI_table[c][0] == 1 and MIDI_table[c][1] == "f": # bus fader in second SCENE
              ini_value = bus_init_val[channel - 1]
              # only apply value if current fader value is not too far off
              if ini_value < 0 or (ini_value >= 0 and abs(ini_value - value) < 0.01):
                bus_init_val[channel - 1] = -1 # invalidate initial value
                mixer.set_value(f'/ch/{channel:#02}/mix/{bus_ch:#02}/level', [value], False)
                threading.Thread(target = switch_pi_board_led, args = (False, )).start() # takes time to process
              else:
                threading.Thread(target = switch_pi_board_led, args = (True, )).start() # takes time to process

            if MIDI_table[c][0] == 3 and MIDI_table[c][1] == "d": # dial in last SCENE
              mixer.set_value(f'/ch/{channel:#02}/mix/pan', [value], False)

        #event_s = " ".join(f"{b}" for b in event.midi_bytes)
        #print(f"{event_s}")
  except KeyboardInterrupt:
    pass

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



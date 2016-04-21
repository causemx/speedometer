import pdb
import time
import sys
import os
import string
import math
import re


__usage__ = """
Usage: speedometer [options] tap [[-c] tap]...
Monitor network traffic or speed/progress of a file transfer.  At least one
tap must be entered.  -c starts a new column, otherwise taps are piled
vertically.

Taps:
  -r network-interface        display bytes received on network-interface
  -t network-interface        display bytes transmitted on network-interface

Options:
  -x                          exit when files reach their expected size
"""

INITIAL_DELAY = 0.5 # seconds
INTERVAL_DELAY = 1.0 # seconds


class Speedometer:
    def __init__(self,maxlog=5):
        """speedometer(maxlog=5)
        maxlog is the number of readings that will be stored"""
        self.log = []
        self.start = None
        self.maxlog = maxlog

    def get_log(self):
        return self.log

    def update(self, bytes):
        """update(bytes) => None
        add a byte reading to the log"""
        t = time.time()
        reading = (t,bytes)
        if not self.start: self.start = reading
        self.log.append(reading)
        self.log = self.log[ - (self.maxlog+1):]

    def delta(self, readings=0, skip=0):
        """delta(readings=0) -> time passed, byte increase
        if readings is 0, time since start is given
        don't include the last 'skip' readings
        None is returned if not enough data available"""
        assert readings >= 0
        assert readings <= self.maxlog, "Log is not long enough to satisfy request"
        assert skip >= 0
        if skip > 0: assert readings > 0, "Can't skip when reading all"

        if skip > len(self.log)-1: return # not enough data
        current = self.log[-1 -skip]
        target = None
        if readings == 0: target = self.start
        elif len(self.log) > readings+skip:
            target = self.log[-(readings+skip+1)]
        if not target: return  # not enough data
        if target == current: return
        byte_increase = current[1]-target[1]
        time_passed = current[0]-target[0]
        return time_passed, byte_increase

    def speed(self, *l, **d):
        d = self.delta(*l, **d)
        if d:
            return delta_to_speed(d)

class NetworkTap:
    def __init__(self, rxtx, interface):
        self.ftype = rxtx
        self.interface = interface
        self.feed = network_feed(interface, rxtx)

    def description(self):
        return self.ftype+": "+self.interface

    def wait_creation(self):
        if self.feed() is None:
            sys.stdout.write("Waiting for network statistics from "
                "interface '%s'...\n" % self.interface)
            while self.feed() == None:
                time.sleep(1)


def network_feed(device,rxtx):
    """network_feed(device,rxtx) -> function that returns given device stream speed
    rxtx is "RX" or "TX"
    """
    assert rxtx in ["RX","TX"]
    r = re.compile(r"^\s*"  +re.escape(device) + r":(.*)$", re.MULTILINE)
    def networkfn(devre=r,rxtx=rxtx):
        f = open('/proc/net/dev')
        dev_lines = f.read()
        f.close()
        match = devre.search(dev_lines)

        if not match:
            return None

        parts = match.group(1).split()
        if rxtx == 'RX':
            return long(parts[0])
        else:
            return long(parts[8])

    return networkfn

def wait_all(cols):
    for c in cols:
        for tap in c:
            tap.wait_creation()

def parse_args():
    args = sys.argv[1:]
    tap = None
    cols = []
    taps = []

    def push_tap(tap, taps):
        if tap is None: return
        taps.append(tap)

    i = 0
    while i < len(args):
        op = args[i]
        if op in ("-h","--help"):
            raise ArgumentError
        elif op in ("-i","-r","-rx","-t","-tx","-f","-k","-m","-n"):
            # combine two part arguments with the following argument
            try:
                if op != "-f": # keep support for -f being optional
                    args[i+1] = op + args[i+1]
            except IndexError:
                raise ArgumentError
            push_tap(tap, taps)
            tap = None    
        elif op.startswith("-rx"):
            push_tap(tap, taps)
            tap = NetworkTap("RX", op[3:])
        elif op.startswith("-r"):
            push_tap(tap, taps)
            tap = NetworkTap("RX", op[2:])
        elif op.startswith("-tx"):
            push_tap(tap, taps)
            tap = NetworkTap("TX", op[3:])
        elif op.startswith("-t"):
            push_tap(tap, taps)
            tap = NetworkTap("TX", op[2:])
        elif tap == None:
            tap = FileTap(op)
        else:
            raise ArgumentError

        i += 1

    push_tap(tap, taps)
    cols.append(taps)
    return cols

class ArgumentError(Exception):
    pass

def console():
    try:
        cols = parse_args()
    except ArgumentError:
        sys.stderr.write(__usage__)
        return

    try:
        wait_all(cols)
    except KeyboardInterrupt:
        return

    [[tap]] = cols
    do_simple(tap.feed)

def do_simple(feed):
    try:
        spd = Speedometer(6)
        f = feed()
        if f is None: return
        spd.update(f)
        time.sleep(INITIAL_DELAY)
        while True:
            f = feed()
            if f is None: return
            spd.update(f)
            s = spd.speed(1) # last sample
            c = curve(spd) # "curved" reading
            a = spd.speed() # running average
            show(s,c,a)
            time.sleep(INTERVAL_DELAY)
    except KeyboardInterrupt:
        pass

def delta_to_speed(delta):
    """delta_to_speed(delta) -> speed in bytes per second"""
    time_passed, byte_increase = delta
    if time_passed <= 0: return 0
    if long(time_passed*1000) == 0: return 0

    return long(byte_increase*1000)/long(time_passed*1000)

def readable_speed(speed):
    """
    readable_speed(speed) -> string
    speed is in bytes per second
    returns a readable version of the speed given
    """

    if speed == None or speed < 0: speed = 0

    units = "B/s", "KiB/s", "MiB/s", "GiB/s", "TiB/s"
    step = 1L

    for u in units:

        if step > 1:
            s = "%4.2f " %(float(speed)/step)
            if len(s) <= 5: return s + u
            s = "%4.1f " %(float(speed)/step)
            if len(s) <= 5: return s + u

        if speed/step < 1024:
            return "%4d " %(speed/step) + u

        step = step * 1024L

    return "%4d " % (speed/(step/1024)) + units[-1]

def curve(spd):
    """Try to smooth speed fluctuations"""
    val = [6, 5, 4, 3, 2, 1] # speed sampling relative weights
    wtot = 0 # total weighting
    ws = 0.0 # weighted speed
    for i in range(len(val)):
        d = spd.delta(1,i)
        if d==None:
            break # ran out of data
        t, b = d
        v = val[i]
        wtot += v
        ws += float(b)*v/t
    return delta_to_speed((wtot, ws))

def show(s, c, a, out = sys.stdout.write):
    out(readable_speed(s))
    out("  c:" + readable_speed(c))
    out("  A:" + readable_speed(a))
    out("  (" + graphic_speed(s)+")")
    out('\n')

def graphic_speed(speed):
    """graphic_speed(speed) -> string
    speed is bytes per second
    returns a graphic representing given speed"""

    if speed == None: speed = 0

    speed_val = [0]+[int(2**(x*5.0/3)) for x in range(20)]

    speed_gfx = [
        r"\                    ",
        r".\                   ",
        r"..\                  ",
        r"...\                 ",
        r"...:\                ",
        r"...::\               ",
        r"...:::\              ",
        r"...:::+|             ",
        r"...:::++|            ",
        r"...:::+++|           ",
        r"...:::+++#|          ",
        r"...:::+++##|         ",
        r"...:::+++###|        ",
        r"...:::+++###%|       ",
        r"...:::+++###%%/      ",
        r"...:::+++###%%%/     ",
        r"...:::+++###%%%//    ",
        r"...:::+++###%%%///   ",
        r"...:::+++###%%%////  ",
        r"...:::+++###%%%///// ",
        r"...:::+++###%%%//////",
        ]


    for i in range(len(speed_val)-1):
        low, high = speed_val[i], speed_val[i+1]
        if speed > high: continue
        if speed - low < high - speed:
            return speed_gfx[i]
        else:
            return speed_gfx[i+1]

    return speed_gfx[-1]

if __name__ == "__main__":
	console()
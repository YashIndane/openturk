#!/usr/bin/env python3
"""
Smooth XY Stepper Motion Controller
Waveshare Stepper HAT (HR8825) + Raspberry Pi Zero + pigpio

Hardware:
    Motor 1 (X axis): STEP=GPIO19, DIR=GPIO13, EN=GPIO12
    Motor 2 (Y axis): STEP=GPIO18, DIR=GPIO24, EN=GPIO4
    Belt/pulley: GT2, 20-tooth, 2mm pitch -> 40mm travel per revolution
    Microstepping: 1/8 step, set via HAT DIP switches
        Motor 1: D0=1, D1=1, D2=0
        Motor 2: D3=1, D4=1, D5=0
    Enable: confirmed ACTIVE-HIGH on this board (EN=1 -> energized)

Why pigpio instead of time.sleep():
    A Raspberry Pi Zero running plain Python + time.sleep() to bit-bang
    STEP pulses is subject to OS scheduling jitter, which shows up as
    uneven, "juddery" motion at the pulse rates 1/8-microstepping
    requires for medium speed (2000-3000+ pulses/sec). pigpio instead
    builds a waveform of exact pulse timings and has the Pi's DMA
    hardware clock it out, completely independent of what Python is
    doing at that instant. Same wiring, same GPIO pins -- just far
    more consistent timing, which is what actually makes motion look
    smooth.

Setup required on the Pi (one-time):
    sudo apt install pigpio python3-pigpio
    sudo pigpiod              # start the daemon (or enable it at boot)

Run:
    python3 xy_stepper_driver.py
"""

import pigpio
import time
import math
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MOTOR1 = {"step": 19, "dir": 13, "en": 12}   # X axis
MOTOR2 = {"step": 18, "dir": 24, "en": 4}    # Y axis

ENABLE_ACTIVE_LOW = False    # confirmed active-HIGH on this board

MICROSTEP = 8
FULL_STEPS_PER_REV = 200
STEPS_PER_REV = FULL_STEPS_PER_REV * MICROSTEP        # 1600

PULLEY_TEETH = 20
BELT_PITCH_MM = 2
MM_PER_REV = PULLEY_TEETH * BELT_PITCH_MM             # 40mm
STEPS_PER_MM = STEPS_PER_REV / MM_PER_REV             # 40 steps/mm

DIR_POS = 1     # arbitrary logical "positive" direction per axis
DIR_NEG = 0

STEP_PULSE_US = 5   # HIGH pulse width per step, comfortably above HR8825 min (~1.9us)

DEFAULT_MAX_SPEED_MMS = 60.0    # medium cruise speed (mm/s)
DEFAULT_ACCEL_MMS2 = 250.0      # acceleration ramp rate (mm/s^2)

# pigpio has an internal limit on how many pulses fit in a single waveform
# (~12000 by default). Longer/simultaneous moves easily exceed this, which
# crashes the daemon connection. We stay safely under that by splitting
# long moves into chunks and chaining them together with wave_chain(),
# which plays them back-to-back with no gap -- motion looks identical to
# one continuous wave.
MAX_PULSES_PER_CHUNK = 2000


# ---------------------------------------------------------------------------
# Low-level setup
# ---------------------------------------------------------------------------

def connect():
    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: could not connect to the pigpio daemon.")
        print("Run 'sudo pigpiod' first, then try again.")
        sys.exit(1)

    for motor in (MOTOR1, MOTOR2):
        pi.set_mode(motor["step"], pigpio.OUTPUT)
        pi.set_mode(motor["dir"], pigpio.OUTPUT)
        pi.set_mode(motor["en"], pigpio.OUTPUT)
        pi.write(motor["step"], 0)
        disable_motor(pi, motor)

    return pi


def enable_motor(pi, motor):
    pi.write(motor["en"], 0 if ENABLE_ACTIVE_LOW else 1)


def disable_motor(pi, motor):
    pi.write(motor["en"], 1 if ENABLE_ACTIVE_LOW else 0)


def set_direction(pi, motor, direction):
    pi.write(motor["dir"], direction)


# ---------------------------------------------------------------------------
# Motion profile: simplified trapezoidal accel / cruise / decel
# ---------------------------------------------------------------------------

def build_step_delays(total_steps, max_speed_mms, accel_mms2):
    """
    Returns a list of per-step delays (seconds), one entry per step,
    implementing a trapezoidal velocity profile: ramp up to max speed,
    cruise, ramp back down. If the move is too short to ever reach max
    speed, this automatically falls back to a triangular profile instead.

    This is a simplified model (good enough for smooth medium-speed
    motion) -- not a full real-time CNC-grade motion planner.
    """
    if total_steps <= 0:
        return []

    max_speed_steps_s = max_speed_mms * STEPS_PER_MM
    accel_steps_s2 = accel_mms2 * STEPS_PER_MM

    accel_steps = int((max_speed_steps_s ** 2) / (2 * accel_steps_s2))
    if accel_steps * 2 > total_steps:
        accel_steps = total_steps // 2   # triangular profile

    cruise_steps = total_steps - 2 * accel_steps
    cruise_delay = 1.0 / max_speed_steps_s

    accel_delays = []
    for i in range(1, accel_steps + 1):
        v = math.sqrt(2 * accel_steps_s2 * i)   # steps/sec reached by step i
        v = max(v, 1.0)                          # avoid divide-by-zero on step 1
        accel_delays.append(1.0 / v)

    delays = accel_delays + [cruise_delay] * cruise_steps + list(reversed(accel_delays))

    # rounding may leave us a step or two short/long -- pad or trim to match exactly
    while len(delays) < total_steps:
        delays.append(cruise_delay)
    while len(delays) > total_steps:
        delays.pop()

    return delays


# ---------------------------------------------------------------------------
# Wave-based motion: builds one pigpio waveform covering all moving axes
# ---------------------------------------------------------------------------

def move_axes(pi, moves, max_speed_mms=DEFAULT_MAX_SPEED_MMS, accel_mms2=DEFAULT_ACCEL_MMS2):
    """
    Move one or more axes using a single hardware-timed pigpio waveform.

    moves: list of (motor_dict, distance_mm, direction) tuples.

    Note: each axis gets its own trapezoidal ramp based on its own
    distance. If axes travel different distances in the same call
    (e.g. a diagonal move), the shorter axis will finish first rather
    than both arriving together -- fine for a pick-and-place, but
    worth knowing if you later want true synchronized diagonal moves.
    """
    pi.wave_clear()
    events = {}   # time_in_microseconds -> [on_mask, off_mask]
    active_motors = []

    for motor, distance_mm, direction in moves:
        steps = int(round(abs(distance_mm) * STEPS_PER_MM))
        if steps == 0:
            continue

        enable_motor(pi, motor)
        set_direction(pi, motor, direction)
        active_motors.append(motor)

        delays = build_step_delays(steps, max_speed_mms, accel_mms2)
        step_mask = 1 << motor["step"]

        t = 0.0
        for d in delays:
            t_on = int(round(t * 1_000_000))
            t_off = t_on + STEP_PULSE_US
            events.setdefault(t_on, [0, 0])
            events[t_on][0] |= step_mask
            events.setdefault(t_off, [0, 0])
            events[t_off][1] |= step_mask
            t += d

    if not events:
        return

    time.sleep(0.002)   # let DIR/EN lines settle before the first pulse

    sorted_times = sorted(events.keys())
    pulses = []
    for i, ts in enumerate(sorted_times):
        on_mask, off_mask = events[ts]
        next_ts = sorted_times[i + 1] if i + 1 < len(sorted_times) else ts
        delay = max(next_ts - ts, 1)   # pigpio requires a delay of at least 1us
        pulses.append(pigpio.pulse(on_mask, off_mask, delay))

    # Split into chunks and create one wave per chunk, staying under
    # pigpio's per-wave pulse limit.
    wave_ids = []
    try:
        for start in range(0, len(pulses), MAX_PULSES_PER_CHUNK):
            chunk = pulses[start:start + MAX_PULSES_PER_CHUNK]
            pi.wave_add_generic(chunk)
            wave_ids.append(pi.wave_create())

        # Chain all the chunk-waves together, played once each, back-to-back.
        pi.wave_chain(wave_ids)

        while pi.wave_tx_busy():
            time.sleep(0.001)

    finally:
        for wid in wave_ids:
            pi.wave_delete(wid)
        for motor in active_motors:
            disable_motor(pi, motor)


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def move_x(pi, distance_mm, max_speed_mms=DEFAULT_MAX_SPEED_MMS, accel_mms2=DEFAULT_ACCEL_MMS2):
    direction = DIR_POS if distance_mm >= 0 else DIR_NEG
    move_axes(pi, [(MOTOR1, distance_mm, direction)], max_speed_mms, accel_mms2)


def move_y(pi, distance_mm, max_speed_mms=DEFAULT_MAX_SPEED_MMS, accel_mms2=DEFAULT_ACCEL_MMS2):
    direction = DIR_POS if distance_mm >= 0 else DIR_NEG
    move_axes(pi, [(MOTOR2, distance_mm, direction)], max_speed_mms, accel_mms2)


def move_xy(pi, x_mm, y_mm, max_speed_mms=DEFAULT_MAX_SPEED_MMS, accel_mms2=DEFAULT_ACCEL_MMS2):
    moves = []
    if x_mm != 0:
        moves.append((MOTOR1, x_mm, DIR_POS if x_mm >= 0 else DIR_NEG))
    if y_mm != 0:
        moves.append((MOTOR2, y_mm, DIR_POS if y_mm >= 0 else DIR_NEG))
    move_axes(pi, moves, max_speed_mms, accel_mms2)


# ---------------------------------------------------------------------------
# Demo / test sequence
# ---------------------------------------------------------------------------

def main():
    pi = connect()
    try:
        print("Motor 1 (X) individually: 50mm out, 50mm back")
        move_x(pi, 50)
        time.sleep(0.3)
        move_x(pi, -50)
        time.sleep(0.5)

        print("Motor 2 (Y) individually: 50mm out, 50mm back")
        move_y(pi, 50)
        time.sleep(0.3)
        move_y(pi, -50)
        time.sleep(0.5)

        print("Both motors simultaneously: 80mm diagonal out and back")
        move_xy(pi, 80, 80)
        time.sleep(0.3)
        move_xy(pi, -80, -80)

        print("All moves complete.")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    finally:
        disable_motor(pi, MOTOR1)
        disable_motor(pi, MOTOR2)
        pi.stop()
        print("pigpio connection closed. Exiting.")


if __name__ == "__main__":
    main()

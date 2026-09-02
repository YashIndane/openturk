#!/usr/bin/env python3
"""
Chess Picker Move Controller
Builds on the pigpio-based smooth XY motion approach from
xy_stepper_driver3.py to execute full chess pick-and-place sequences
given algebraic move strings.

Hardware:
    - 2x NEMA-17 bipolar stepper motors, 4.2kg-cm, 4-wire
    - Raspberry Pi Zero + Waveshare Stepper HAT (DRV8825 drivers)
    - Motor 1 (RANK axis): STEP=GPIO19, DIR=GPIO13, EN=GPIO12
    - Motor 2 (FILE axis): STEP=GPIO18, DIR=GPIO24, EN=GPIO4
    - Belt/pulley: GT2, 20-tooth, 2mm pitch -> 40mm travel per revolution
    - Microstepping: 1/8 step, set via HAT DIP switches
        Motor 1: D0=1, D1=1, D2=0
        Motor 2: D3=1, D4=1, D5=0
    - Enable: confirmed ACTIVE-HIGH on this board (EN=1 -> energized)

Board / picker geometry:
    - Square size: 37mm x 37mm (SQUARE_SIZE_MM below -- adjustable)
    - The picker parks at the centre of a virtual square defined by
      ORIGIN_FILE_IDX / ORIGIN_RANK_IDX (currently "d10"). This is
      exposed as PARK_SQUARE, and every move sequence starts and ends
      there -- change those two indices (never a hardcoded square name)
      if you physically relocate the park position.
    - "X" is the fixed drop-off point for captured pieces. It is NOT a
      real board square -- confirmed from the board layout photo to sit
      directly above file f, on the same margin row as the park square,
      with one empty square-width (file e) between them. See
      X_FILE_IDX / X_RANK_IDX below; update those two indices if you
      ever reposition it physically.
    - Both the park square and X are centres of imaginary 37mm x 37mm
      squares in that same margin row, so both are computed with the
      identical grid formula used for every real square.

Motor-to-board mapping (as described):
    - Motor 1 drives the RANK axis (rank 8 <-> rank 1)
    - Motor 2 drives the FILE axis (file A <-> file H)
    - Motor1 CCW moves the picker from rank 8 toward rank 1
    - Motor2 CCW moves the picker from file A toward file H
    These CCW facts describe the mechanical behaviour, but which way
    move_x()/move_y()-equivalent calls actually send each motor depends
    on how your coils are wired (deliberately left flexible when the
    original driver was built). RANK_SIGN / FILE_SIGN below are what
    the software actually uses -- run `python3 chess_picker.py
    --calibrate` once on real hardware and flip either constant if a
    test move goes the wrong way before trusting real sequences.

Setup required on the Pi (one-time, same as xy_stepper_driver3.py):
    sudo apt install pigpio python3-pigpio
    sudo pigpiod

Usage as a script:
    python3 chess_picker.py e8e7                # normal move
    python3 chess_picker.py e8e7 --capture       # capture move
    python3 chess_picker.py --calibrate          # verify axis directions

Usage as a module:
    from chess_picker import move_picker
    move_picker('e8e7', capture=False)
    move_picker('d5e6', capture=True)
"""

import time
import math
import re
import sys
import argparse
import atexit
import pigpio
import zaxis_control

from gripper import Servo


# ---------------------------------------------------------------------------
# Hardware config (mirrors xy_stepper_driver3.py)
# ---------------------------------------------------------------------------

MOTOR1 = {"step": 19, "dir": 13, "en": 12}   # RANK axis
MOTOR2 = {"step": 18, "dir": 24, "en": 4}    # FILE axis

ENABLE_ACTIVE_LOW = False   # confirmed active-HIGH on this board

MICROSTEP = 8
FULL_STEPS_PER_REV = 200
STEPS_PER_REV = FULL_STEPS_PER_REV * MICROSTEP        # 1600

PULLEY_TEETH = 20
BELT_PITCH_MM = 2
MM_PER_REV = PULLEY_TEETH * BELT_PITCH_MM             # 40mm
STEPS_PER_MM = STEPS_PER_REV / MM_PER_REV             # 40 steps/mm

DIR_POS = 1
DIR_NEG = 0

STEP_PULSE_US = 5
BASE_MAX_PULSES_PER_CHUNK = 2500   # safe chunk size for single-axis moves

DEFAULT_MAX_SPEED_MMS = 60.0    # medium cruise speed, same as the test driver
DEFAULT_ACCEL_MMS2 = 250.0

HOLD_DELAY_S = 0.3   # pause after every move leg, per the requested sequence

# ---------------------------------------------------------------------------
# Board / picker geometry -- EDIT FOR YOUR BUILD
# ---------------------------------------------------------------------------

SQUARE_SIZE_MM = 40.0   # adjustable board square pitch

ORIGIN_FILE_IDX = 4    # 'd' -- park square file
ORIGIN_RANK_IDX = 10   # park square rank (one row further out than the board edge)

# The name of the park square, always kept in sync with the two indices
# above -- never hardcode 'd9' (or any other literal) elsewhere in this
# file. Changing ORIGIN_FILE_IDX/ORIGIN_RANK_IDX automatically updates
# every place that refers to "home."
PARK_SQUARE = f"{chr(ord('a') + ORIGIN_FILE_IDX - 1)}{ORIGIN_RANK_IDX}"

# X drop-off point -- confirmed from the board layout photo: it sits
# directly above file f, on the same margin row as the park square, with
# one empty square-width (file e) between them. Expressed as (file,
# rank) indices rather than a raw mm offset so it automatically stays
# correct if SQUARE_SIZE_MM -- or the park square's row -- ever changes.
X_FILE_IDX = 6    # 'f'
X_RANK_IDX = 10   # same margin row as the park square

X_DROP_POSITION_MM = (
    (X_FILE_IDX - ORIGIN_FILE_IDX) * SQUARE_SIZE_MM,
    (X_RANK_IDX - ORIGIN_RANK_IDX) * SQUARE_SIZE_MM,
)

# ---------------------------------------------------------------------------
# CALIBRATION -- verify with --calibrate before trusting real sequences
# ---------------------------------------------------------------------------

RANK_SIGN = 1   # flip to -1 if a +1 rank-axis test move goes toward rank1 instead of rank8
FILE_SIGN = -1   # flip to -1 if a +1 file-axis test move goes toward file A instead of file H


# ---------------------------------------------------------------------------
# Low-level motor control (same approach as xy_stepper_driver3.py)
# ---------------------------------------------------------------------------

def connect():
    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: could not connect to the pigpio daemon.")
        print("Run 'sudo pigpiod' first, then try again.")
        sys.exit(1)

    # pigpio's waveform storage (and its control-block pool) is shared
    # across the whole daemon, not per-connection. If any past run --
    # crashed, killed, or otherwise interrupted before this script had
    # hardened cleanup -- left waves undeleted, they stay parked in the
    # daemon forever, invisible to this run, silently eating into the
    # same shared pool until it's exhausted ("No more CBs for
    # waveform"). wave_clear() wipes every waveform the daemon knows
    # about, regardless of which session created it, so each fresh run
    # of this script starts from a guaranteed-clean slate instead of
    # depending on someone remembering to restart pigpiod by hand.
    pi.wave_clear()

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
# Motion profile (same trapezoidal model as xy_stepper_driver3.py)
# ---------------------------------------------------------------------------

def build_step_delays(total_steps, max_speed_mms, accel_mms2):
    """
    Returns a list of per-step delays (seconds), one entry per step,
    implementing a trapezoidal velocity profile: ramp up to max speed,
    cruise, ramp back down. Falls back to a triangular profile
    automatically if the move is too short to ever reach max speed.
    """
    if total_steps <= 0:
        return []

    max_speed_steps_s = max_speed_mms * STEPS_PER_MM
    accel_steps_s2 = accel_mms2 * STEPS_PER_MM

    accel_steps = int((max_speed_steps_s ** 2) / (2 * accel_steps_s2))
    if accel_steps * 2 > total_steps:
        accel_steps = total_steps // 2

    cruise_steps = total_steps - 2 * accel_steps
    cruise_delay = 1.0 / max_speed_steps_s

    accel_delays = []
    for i in range(1, accel_steps + 1):
        v = math.sqrt(2 * accel_steps_s2 * i)
        v = max(v, 1.0)
        accel_delays.append(1.0 / v)

    delays = accel_delays + [cruise_delay] * cruise_steps + list(reversed(accel_delays))

    while len(delays) < total_steps:
        delays.append(cruise_delay)
    while len(delays) > total_steps:
        delays.pop()

    return delays


def _create_wave(pi, chunk):
    pi.wave_add_generic(chunk)
    return pi.wave_create()


def _play_pulses_streaming(pi, pulses, max_pulses_per_chunk=BASE_MAX_PULSES_PER_CHUNK):
    """Double-buffered chunked playback -- see xy_stepper_driver3.py for
    the full explanation. Keeps only two chunks' worth of DMA control
    blocks alive at once, so any move length works without gaps.

    max_pulses_per_chunk should be smaller for moves where more than
    one motor is active simultaneously -- a pulse that has to turn one
    GPIO pin on and a different one off in the same instant costs more
    control blocks than a single-axis pulse that only ever does one or
    the other, so the same chunk size that's safe for one axis isn't
    automatically safe for two.

    Every wave id created here is tracked in `active_wids` and
    guaranteed to be deleted in the finally block, no matter where an
    error occurs -- this prevents leaked waves from slowly exhausting
    pigpio's control-block pool across repeated runs (which shows up
    as 'No more CBs for waveform' on a later, unrelated move)."""
    if not pulses:
        return

    chunks = [pulses[i:i + max_pulses_per_chunk]
              for i in range(0, len(pulses), max_pulses_per_chunk)]

    active_wids = set()

    try:
        current_wid = _create_wave(pi, chunks[0])
        active_wids.add(current_wid)
        pi.wave_send_once(current_wid)
        next_index = 1
        next_wid = None

        while True:
            if next_wid is None and next_index < len(chunks):
                next_wid = _create_wave(pi, chunks[next_index])
                active_wids.add(next_wid)
                next_index += 1

            if not pi.wave_tx_busy():
                pi.wave_delete(current_wid)
                active_wids.discard(current_wid)
                if next_wid is not None:
                    pi.wave_send_once(next_wid)
                    current_wid = next_wid
                    next_wid = None
                else:
                    break
            else:
                time.sleep(0.0002)
    finally:
        for wid in active_wids:
            try:
                pi.wave_delete(wid)
            except Exception:
                pass   # daemon connection may already be broken; nothing more we can do


# ---------------------------------------------------------------------------
# Synchronized two-axis moves (shortest path, matched arrival time)
# ---------------------------------------------------------------------------

def _axis_time(distance_mm, max_speed_mms, accel_mms2):
    """Time (s) for a single axis to trapezoidally travel distance_mm."""
    if distance_mm <= 0:
        return 0.0
    v, a, d = max_speed_mms, accel_mms2, distance_mm
    if (v * v) / a <= d:
        return v / a + d / v            # reaches cruise speed
    return 2.0 * math.sqrt(d / a)       # triangular, never reaches v


def _required_speed_for_time(distance_mm, target_time, accel_mms2):
    """Cruise speed needed for an axis to take exactly target_time to
    travel distance_mm, given fixed acceleration -- used to slow the
    shorter axis down so both arrive together."""
    d, a, t = distance_mm, accel_mms2, target_time
    if d <= 0 or t <= 0:
        return accel_mms2
    min_time = 2.0 * math.sqrt(d / a)
    if t <= min_time:
        return math.sqrt(a * d)         # already as slow as useful (triangular)
    disc = max((a * t) ** 2 - 4 * a * d, 0.0)
    v = (a * t - math.sqrt(disc)) / 2.0
    return max(v, 0.5)


def _run_moves(pi, moves, accel_mms2):
    """moves: list of (motor, distance_mm, direction, max_speed_mms).
    Builds one merged waveform across all axes and streams it."""
    events = {}
    active_motors = []

    for motor, distance_mm, direction, speed_mms in moves:
        steps = int(round(distance_mm * STEPS_PER_MM))
        if steps == 0:
            continue

        enable_motor(pi, motor)
        set_direction(pi, motor, direction)
        active_motors.append(motor)

        delays = build_step_delays(steps, speed_mms, accel_mms2)
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

    time.sleep(0.002)

    sorted_times = sorted(events.keys())
    pulses = []
    for i, ts in enumerate(sorted_times):
        on_mask, off_mask = events[ts]
        next_ts = sorted_times[i + 1] if i + 1 < len(sorted_times) else ts
        delay = max(next_ts - ts, 1)
        pulses.append(pigpio.pulse(on_mask, off_mask, delay))

    # A pulse that sets one motor's STEP pin and clears another's in the
    # same instant costs more control blocks than a single-axis pulse
    # that only ever does one or the other -- so a chunk size safe for
    # one active motor isn't automatically safe for two. Shrink it
    # proportionally to the number of motors actually moving this time.
    chunk_size = BASE_MAX_PULSES_PER_CHUNK // max(1, len(active_motors))

    try:
        _play_pulses_streaming(pi, pulses, chunk_size)
    finally:
        for motor in active_motors:
            disable_motor(pi, motor)


def move_synced(pi, rank_delta_mm, file_delta_mm,
                 max_speed_mms=DEFAULT_MAX_SPEED_MMS,
                 accel_mms2=DEFAULT_ACCEL_MMS2):
    """
    Moves both axes together in a straight line -- diagonal if both
    deltas are non-zero -- synchronized so they start and finish at the
    same time rather than the shorter axis finishing early. Since both
    axes move concurrently rather than sequentially, this is also the
    shortest path/time between any two points.
    """
    hw_rank_mm = RANK_SIGN * rank_delta_mm
    hw_file_mm = FILE_SIGN * file_delta_mm

    dist_rank = abs(hw_rank_mm)
    dist_file = abs(hw_file_mm)

    if dist_rank == 0 and dist_file == 0:
        return

    time_rank = _axis_time(dist_rank, max_speed_mms, accel_mms2) if dist_rank else 0.0
    time_file = _axis_time(dist_file, max_speed_mms, accel_mms2) if dist_file else 0.0
    target_time = max(time_rank, time_file)

    speed_rank = max_speed_mms
    speed_file = max_speed_mms
    if dist_rank and time_rank < target_time:
        speed_rank = _required_speed_for_time(dist_rank, target_time, accel_mms2)
    if dist_file and time_file < target_time:
        speed_file = _required_speed_for_time(dist_file, target_time, accel_mms2)

    moves = []
    if dist_rank:
        direction = DIR_POS if hw_rank_mm >= 0 else DIR_NEG
        moves.append((MOTOR1, dist_rank, direction, speed_rank))
    if dist_file:
        direction = DIR_POS if hw_file_mm >= 0 else DIR_NEG
        moves.append((MOTOR2, dist_file, direction, speed_file))

    _run_moves(pi, moves, accel_mms2)


# ---------------------------------------------------------------------------
# Board coordinate handling
# ---------------------------------------------------------------------------

def square_to_position_mm(square):
    """
    Returns (file_axis_mm, rank_axis_mm) for a square, relative to the
    centre of d9 (the origin). Accepts real board squares ('a1'-'h8'),
    the parking square 'd9', or the literal 'X' drop-off point.
    """
    if square.upper() == 'X':
        return X_DROP_POSITION_MM

    match = re.fullmatch(r'([a-hA-H])(\d+)', square)
    if not match:
        raise ValueError(f"Invalid square: {square!r}")

    file_char, rank_str = match.groups()
    file_idx = ord(file_char.lower()) - ord('a') + 1   # a=1 .. h=8
    rank_idx = int(rank_str)                            # 1-8, or 9 for d9

    file_axis_mm = (file_idx - ORIGIN_FILE_IDX) * SQUARE_SIZE_MM
    rank_axis_mm = (rank_idx - ORIGIN_RANK_IDX) * SQUARE_SIZE_MM
    return (file_axis_mm, rank_axis_mm)


def move_between(pi, from_square, to_square,
                  max_speed_mms=DEFAULT_MAX_SPEED_MMS,
                  accel_mms2=DEFAULT_ACCEL_MMS2):
    """Moves the picker in one synchronized straight line from the
    centre of from_square to the centre of to_square."""
    file_a, rank_a = square_to_position_mm(from_square)
    file_b, rank_b = square_to_position_mm(to_square)
    move_synced(pi, rank_b - rank_a, file_b - file_a, max_speed_mms, accel_mms2)


# ---------------------------------------------------------------------------
# Gripper / lift placeholders -- replace with real servo/electromagnet code
# ---------------------------------------------------------------------------

#def pick_up(gripper):
#    """Placeholder for the gripper/lift mechanism: lower, grip, raise."""
#    print("down/hold/up")



#def place_down(gripper):
#    """Placeholder for the gripper/lift mechanism: lower, release, raise."""
#    print("down/release/up")


# ---------------------------------------------------------------------------
# Module-level connection management, so move_picker() can be called
# directly (matching the requested move_picker(coor, capture) signature)
# without the caller having to manage a pigpio connection.
# ---------------------------------------------------------------------------

_pi = None


def _get_pi():
    global _pi
    if _pi is None:
        _pi = connect()
    return _pi


def shutdown():
    global _pi
    if _pi is not None:
        try:
            disable_motor(_pi, MOTOR1)
            disable_motor(_pi, MOTOR2)
            _pi.stop()
        except Exception:
            pass   # connection may already be broken from an earlier error --
                    # nothing more we can do, and this shouldn't mask the
                    # original exception with a confusing secondary one
        _pi = None


atexit.register(shutdown)


# ---------------------------------------------------------------------------
# Top-level move sequence
# ---------------------------------------------------------------------------

def move_picker(coor, capture=False,
                 max_speed_mms=DEFAULT_MAX_SPEED_MMS,
                 accel_mms2=DEFAULT_ACCEL_MMS2):
    """
    Executes a full pick-and-place sequence for a move given as
    'e8e7' (source square + destination square), starting and ending
    with the picker parked at PARK_SQUARE.

    capture=False:
        PARK_SQUARE->src, pick up, src->dst, place down, dst->PARK_SQUARE

    capture=True (an opponent piece already sits on dst and must be
    cleared first):
        PARK_SQUARE->dst, pick up, dst->X, place down (discard captured piece),
        X->src, pick up, src->dst, place down, dst->PARK_SQUARE
    """
    match = re.fullmatch(r'([a-hA-H][1-8])([a-hA-H][1-8])', coor)
    if not match:
        raise ValueError(f"Invalid coordinate string: {coor!r} (expected e.g. 'e8e7')")

    src, dst = match.groups()
    pi = _get_pi()

    # Fully reset pigpio's waveform store before this move. Even with
    # every wave properly deleted after use, repeated create/delete
    # cycles across the several legs of a move sequence -- and across
    # multiple move_picker() calls in one long-running session -- can
    # fragment the control-block pool over time (free space scattered
    # in small non-contiguous pieces rather than lost). A later wave
    # can then fail to allocate even though nothing actually leaked.
    # wave_clear() resets to one clean contiguous block every time,
    # which eliminates fragmentation the same way it eliminates leaks.
    pi.wave_clear()

    def go(a, b):
        move_between(pi, a, b, max_speed_mms, accel_mms2)
        time.sleep(HOLD_DELAY_S)

    servo_gripper = Servo(
        pi, pin=25,
        min_pulse=200, max_pulse=1500,
        min_angle=-180, max_angle=180,
        reverse=False,
    )

    if not capture:
        go(PARK_SQUARE, src)                        # move
        zaxis_control.drop()                                # gripper down
        zaxis_control.stopm()
        time.sleep(.3)
        servo_gripper.move_to(115)                  # grab the piece
        zaxis_control.lift()                                # gripper up
        zaxis_control.stopm()
        time.sleep(.3)
        go(src, dst)                                # move
        zaxis_control.drop()                                # gripper down
        zaxis_control.stopm()
        time.sleep(.3)
        servo_gripper.release()                     # release hold
        servo_gripper.move_without_hold(80)         # release piece
        zaxis_control.lift()                                # gripper up
        zaxis_control.stopm()
        time.sleep(.3)
        go(dst, PARK_SQUARE)                        # move

    else:
        go(PARK_SQUARE, dst)                        # move
        zaxis_control.drop()                                            # gripper down
        zaxis_control.stopm()
        time.sleep(.3)
        servo_gripper.move_to(115)                  # grab the piece
        zaxis_control.lift()                                            # gripper up
        zaxis_control.stopm()
        time.sleep(.3)
        go(dst, PARK_SQUARE)                                # move
        servo_gripper.release()                     # release hold
        servo_gripper.move_without_hold(80)        # release piece
        go(PARK_SQUARE, src)                                # move
        zaxis_control.drop()                                # gripper down
        zaxis_control.stopm()
        time.sleep(.3)
        servo_gripper.move_to(115)                  # grab the piece
        zaxis_control.lift()                                            # gripper up
        zaxis_control.stopm()
        time.sleep(.3)
        go(src, dst)                                # move
        zaxis_control.drop()                                            # gripper down
        zaxis_control.stopm()
        time.sleep(.3)
        servo_gripper.release()                     # release hold
        servo_gripper.move_without_hold(80)        # release piece
        zaxis_control.lift()                               # gripper up
        zaxis_control.stopm()
        time.sleep(.3)
        go(dst, PARK_SQUARE)                        # move



# ---------------------------------------------------------------------------
# Calibration helper
# ---------------------------------------------------------------------------

def calibrate():
    """
    Moves +1 square (37mm) on each axis, one at a time, so you can watch
    which way the picker actually goes and confirm RANK_SIGN / FILE_SIGN
    at the top of this file are set correctly before trusting a real
    move sequence.
    """
    pi = _get_pi()
    pi.wave_clear()

    print("Moving RANK axis +1 square... watch which way it goes.")
    move_synced(pi, SQUARE_SIZE_MM, 0)
    time.sleep(0.5)
    print("  -> If it moved TOWARD rank 8, RANK_SIGN is correct.")
    print("  -> If it moved TOWARD rank 1, flip RANK_SIGN to -1 and re-run.")
    move_synced(pi, -SQUARE_SIZE_MM, 0)
    time.sleep(0.5)

    print("\nMoving FILE axis +1 square... watch which way it goes.")
    move_synced(pi, 0, SQUARE_SIZE_MM)
    time.sleep(0.5)
    print("  -> If it moved TOWARD file H, FILE_SIGN is correct.")
    print("  -> If it moved TOWARD file A, flip FILE_SIGN to -1 and re-run.")
    move_synced(pi, 0, -SQUARE_SIZE_MM)
    time.sleep(0.5)

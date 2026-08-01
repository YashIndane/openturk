#!/usr/bin/env python3
"""
Dual NEMA-17 Stepper Motor Test Script
WaveShare Raspberry Pi Stepper HAT (Full-step mode, DIP switches OFF [0])

Power Supply: 24V 3A DC
Stepper Imax ~ 1.4 Volts
Vref = 0.7 Volts

Wiring:
    Motor 1: Blue->A1, Red->A2, Black->B1, Green->B2
    Motor 2: Blue->A3, Red->A4, Black->B3, Green->B4

Wiring (per user):
    Motor 1: STEP=GPIO19, DIR=GPIO13, EN=GPIO12  [BCM]
    Motor 2: STEP=GPIO18, DIR=GPIO24, EN=GPIO4   [BCM]

Notes:
    - Enable pins on THIS HAT are ACTIVE HIGH (HIGH = enabled/energized),
      confirmed by testing. This is the opposite of the more common
      active-low convention used on most standalone stepper driver
      boards, so don't assume it carries over to other hardware.
    - Full-step mode (no microstepping) => 200 steps = 1 full revolution
      for a standard 1.8 deg/step NEMA17.
    - Power: 24V/3A supply on the HAT's motor power input, Pi powered
      separately via USB as usual. Do NOT power the HAT logic from the
      24V rail.

Run:
    python3 dual_stepper_test.py
"""

import RPi.GPIO as GPIO
import time
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MOTOR1 = {"step": 19, "dir": 13, "en": 12}
MOTOR2 = {"step": 18, "dir": 24, "en": 4}

STEPS_PER_REV = 200          # full-step mode, 1.8 deg/step motor
ENABLE_ACTIVE_LOW = False    # this HAT enables the motor on HIGH, not LOW

DIR_CW = GPIO.HIGH
DIR_CCW = GPIO.LOW

STEP_DELAY = 0.005          # seconds between step pulse edges (~speed)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for motor in (MOTOR1, MOTOR2):
        GPIO.setup(motor["step"], GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(motor["dir"], GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(
            motor["en"], GPIO.OUT,
            initial=GPIO.HIGH if ENABLE_ACTIVE_LOW else GPIO.LOW
        )
    disable_motor(MOTOR1)
    disable_motor(MOTOR2)


def enable_motor(motor):
    GPIO.output(motor["en"], GPIO.LOW if ENABLE_ACTIVE_LOW else GPIO.HIGH)


def disable_motor(motor):
    GPIO.output(motor["en"], GPIO.HIGH if ENABLE_ACTIVE_LOW else GPIO.LOW)


def set_direction(motor, direction):
    GPIO.output(motor["dir"], direction)


def step_pulse(motor):
    GPIO.output(motor["step"], GPIO.HIGH)
    time.sleep(STEP_DELAY)
    GPIO.output(motor["step"], GPIO.LOW)
    time.sleep(STEP_DELAY)


# ---------------------------------------------------------------------------
# Test routines
# ---------------------------------------------------------------------------

def run_motor(motor, steps, direction, label=""):
    """Run a single motor for a given number of steps."""
    enable_motor(motor)
    set_direction(motor, direction)
    time.sleep(0.005)  # brief settle time after enabling/direction change
    for _ in range(steps):
        step_pulse(motor)
    disable_motor(motor)
    print(f"  {label} done: {steps} steps, "
          f"{'CW' if direction == DIR_CW else 'CCW'}")


def test_individual():
    print("\n--- Individual Motor Test ---")

    print("Motor 1: one full revolution CW")
    run_motor(MOTOR1, STEPS_PER_REV, DIR_CW, "Motor 1")
    time.sleep(0.5)

    print("Motor 1: one full revolution CCW")
    run_motor(MOTOR1, STEPS_PER_REV, DIR_CCW, "Motor 1")
    time.sleep(0.5)

    print("Motor 2: one full revolution CW")
    run_motor(MOTOR2, STEPS_PER_REV, DIR_CW, "Motor 2")
    time.sleep(0.5)

    print("Motor 2: one full revolution CCW")
    run_motor(MOTOR2, STEPS_PER_REV, DIR_CCW, "Motor 2")
    time.sleep(0.5)


def test_simultaneous(steps=STEPS_PER_REV, dir1=DIR_CW, dir2=DIR_CW):
    """
    Run both motors at the same time by interleaving step pulses in a
    single loop. This keeps timing synchronized without needing threads
    (software threading in Python doesn't give reliable simultaneous
    GPIO timing anyway).
    """
    print("\n--- Simultaneous Motor Test ---")
    print(f"Both motors: {steps} steps "
          f"(M1={'CW' if dir1 == DIR_CW else 'CCW'}, "
          f"M2={'CW' if dir2 == DIR_CW else 'CCW'})")

    enable_motor(MOTOR1)
    enable_motor(MOTOR2)
    set_direction(MOTOR1, dir1)
    set_direction(MOTOR2, dir2)
    time.sleep(0.005)

    for _ in range(steps):
        GPIO.output(MOTOR1["step"], GPIO.HIGH)
        GPIO.output(MOTOR2["step"], GPIO.HIGH)
        time.sleep(STEP_DELAY)
        GPIO.output(MOTOR1["step"], GPIO.LOW)
        GPIO.output(MOTOR2["step"], GPIO.LOW)
        time.sleep(STEP_DELAY)

    disable_motor(MOTOR1)
    disable_motor(MOTOR2)
    print("  Simultaneous run complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        setup()
        print("GPIO initialized. Starting stepper test sequence...")

        test_individual()
        time.sleep(1)

        # Both motors same direction
        test_simultaneous(STEPS_PER_REV, DIR_CW, DIR_CW)
        time.sleep(0.5)

        # Both motors opposite directions (e.g. for a gripper/mirrored axis)
        test_simultaneous(STEPS_PER_REV, DIR_CW, DIR_CCW)

        print("\nAll tests complete.")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    finally:
        disable_motor(MOTOR1)
        disable_motor(MOTOR2)
        GPIO.cleanup()
        print("GPIO cleaned up. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()

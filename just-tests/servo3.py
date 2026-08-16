import pigpio
import time

class Servo:
    """
    Robust servo controller for pigpio.

    Angle convention: signed, relative to center (0 = center position).
    Calibrate min_pulse/max_pulse/min_angle/max_angle against YOUR servo
    (see calibration script) rather than trusting datasheet defaults.
    """

    def __init__(self, pi, pin,
                 min_pulse=500, max_pulse=2500,
                 min_angle=-90, max_angle=90,
                 reverse=False):
        if not pi.connected:
            raise RuntimeError("pigpio daemon not connected — run 'sudo pigpiod' first")
        if min_pulse >= max_pulse:
            raise ValueError("min_pulse must be less than max_pulse")
        if min_angle >= max_angle:
            raise ValueError("min_angle must be less than max_angle")

        self.pi = pi
        self.pin = pin
        self.min_pulse = min_pulse
        self.max_pulse = max_pulse
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.reverse = reverse
        self.current_angle = None  # None = released / not holding

        self.pi.set_mode(self.pin, pigpio.OUTPUT)

    def _angle_to_pulse(self, angle):
        """Clamp angle to valid range, map linearly to a pulse width."""
        angle = max(self.min_angle, min(self.max_angle, angle))
        if self.reverse:
            angle = self.max_angle - (angle - self.min_angle)

        span_angle = self.max_angle - self.min_angle
        span_pulse = self.max_pulse - self.min_pulse
        pulse = self.min_pulse + (angle - self.min_angle) / span_angle * span_pulse

        # Safety clamp — never send outside calibrated pulse range,
        # even if float rounding pushes it slightly past.
        pulse = max(self.min_pulse, min(self.max_pulse, pulse))
        return pulse

    def move_to(self, angle):
        """Move to angle and hold there indefinitely (pigpio keeps pulsing)."""
        requested = max(self.min_angle, min(self.max_angle, angle))
        pulse = self._angle_to_pulse(angle)
        self.pi.set_servo_pulsewidth(self.pin, pulse)
        self.current_angle = requested
        return requested

    def move_without_hold(self, angle, settle_time=0.3):
        """Move to angle, wait for it to arrive, then release (no holding torque)."""
        actual = self.move_to(angle)
        time.sleep(settle_time)
        self.release()
        return actual

    def release(self):
        """Stop sending pulses — servo goes limp, no holding torque."""
        self.pi.set_servo_pulsewidth(self.pin, 0)
        self.current_angle = None

    def is_holding(self):
        return self.current_angle is not None

    def cleanup(self):
        """Call on shutdown to make sure the pin isn't left pulsing."""
        self.release()


# ---------------- Example usage ----------------
if __name__ == "__main__":
    pi = pigpio.pi()  # reuse the same connection your stepper code uses, if possible

    # Plug in YOUR calibrated numbers here
    servo = Servo(
        pi, pin=25,
        min_pulse=200, max_pulse=1500,
        min_angle=-180, max_angle=180,
        reverse=False,
    )

    def move_steppers():
        print("steppers moving...")
        time.sleep(5)  # placeholder for your real stepper move
        print("steppers done")

    try:
        servo.move_to(123)       # grip at 123, release at 100
        move_steppers()          # servo holds at +45 while steppers run
        servo.release()
        #servo.move_without_hold(100)

        #servo.move_without_hold(0)  # tap back to center, then release
    finally:
        pi.stop()

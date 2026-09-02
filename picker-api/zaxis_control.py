import RPi.GPIO as GPIO
from time import sleep, time

# --- Configuration ---
PIN_IN1 = 5
PIN_IN2 = 6
IR_PIN = 17  # bottom sensor OUT pin

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_IN1, GPIO.OUT)
GPIO.setup(PIN_IN2, GPIO.OUT)
GPIO.setup(IR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Tune this once the carriage always starts a lift from the same known bottom
LIFT_TIME = 12

HOME_TIMEOUT = 20  # seconds, safety cutoff if sensor never triggers


def motor_up():
    print("Motor: UP")
    GPIO.output(PIN_IN1, GPIO.HIGH)
    GPIO.output(PIN_IN2, GPIO.LOW)


def motor_down():
    print("Motor: DOWN")
    GPIO.output(PIN_IN1, GPIO.LOW)
    GPIO.output(PIN_IN2, GPIO.HIGH)


def stopm():
    print("Motor: STOP")
    GPIO.output(PIN_IN1, GPIO.HIGH)
    GPIO.output(PIN_IN2, GPIO.HIGH)
    sleep(0.5)  # short brake settle time; tune as needed


def go_home(timeout=HOME_TIMEOUT):
    """Drive down until IR beam breaks (LOW) at bottom position."""
    motor_down()
    start = time()
    while GPIO.input(IR_PIN) == GPIO.HIGH:  # HIGH = beam clear, keep going
        if time() - start > timeout:
            stopm()
            print("WARNING: home sensor timeout — check wiring/obstruction")
            return False
        sleep(0.01)
    print("Homed at bottom")
    return True


def lift():
    """Move up a fixed duration from the known home position."""
    motor_up()
    sleep(LIFT_TIME)


def drop():
    """Always return to bottom via sensor, not timing."""
    go_home()


def clean():
    print("Cleaning up GPIO resources")
    GPIO.cleanup()

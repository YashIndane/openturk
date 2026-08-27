import RPi.GPIO as GPIO
from time import sleep

# Set up pin numbering mode to BCM (GPIO numbers, not physical pins)
GPIO.setmode(GPIO.BCM)

# Define your control pins
PIN_IN1 = 5
PIN_IN2 = 6

# Configure pins as outputs
GPIO.setup(PIN_IN1, GPIO.OUT)
GPIO.setup(PIN_IN2, GPIO.OUT)

BASE = 13.5

def lift():
    print("Turning motor forward")
    GPIO.output(PIN_IN1, GPIO.HIGH)
    GPIO.output(PIN_IN2, GPIO.LOW)
    sleep(BASE-0.30)

def stopm():
    print("Stopping motor")
    GPIO.output(PIN_IN1, GPIO.HIGH)
    GPIO.output(PIN_IN2, GPIO.HIGH)
    sleep(1)

def drop():
    print("Turning motor backward")
    GPIO.output(PIN_IN1, GPIO.LOW)
    GPIO.output(PIN_IN2, GPIO.HIGH)
    sleep(BASE+0.25)

def clean():
    print("Cleaning up GPIO resources")
    GPIO.cleanup()  # Safely resets pins to input mode to protect hardware

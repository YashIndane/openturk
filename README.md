## Usage
```
$ sudo python3 app.py --apikey="<OPENAI-API-KEY>" 
```

## Prerequisites
```
$ sudo pip3 install -r requirements.txt
```

## Hardware
```
Dual NEMA-17 Stepper Motors
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
    - Enable pins on THIS HAT are ACTIVE HIGH (HIGH = enabled/energized)
```

## Rpi
```
Add gpio=4=ip,pd at the EOF in /boot/firmware/config.txt
```

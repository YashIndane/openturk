## Usage
```
Starting the main app on WSL:
    $ sudo python3 app.py --apikey="<OPENAI-API-KEY>" --pickerip="<IPV4-OF-PICKER-10.x.x.x>"

Network config (Powershell Admin):
    $ netsh interface portproxy add v4tov4 listenport=5000 listenaddress=0.0.0.0 connectport=5000 connectaddress=<IPV4-OF-WSL-172.x.x.x>
    $ New-NetFirewallRule -DisplayName "Flask Hotspot 5000" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow

Starting the API on Rpi:
    $ cd picker-api
    $ sudo python3 app.py
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
Stepping: 1/8

Wiring:
    Motor 1: Blue->A1, Red->A2, Black->B1, Green->B2
    Motor 2: Blue->A3, Red->A4, Black->B3, Green->B4

Wiring (per user):
    Motor 1: STEP=GPIO19, DIR=GPIO13, EN=GPIO12  [BCM]
    Motor 2: STEP=GPIO18, DIR=GPIO24, EN=GPIO4   [BCM]

Notes:
    - Enable pins on THIS HAT are ACTIVE HIGH (HIGH = enabled/energized)
    - DIP positions on HAT for 1/8 stepping:
        D0: 1, D1: 1, D2: 0, D3: 1, D4: 1, D5: 0
```

## Rpi
```
1. Add gpio=4=ip,pd at the EOF in /boot/firmware/config.txt

2. Run `iwconfig` — if `Power Management:on`, the Pi's WiFi radio may be sleeping between requests.
Disable with `sudo iw wlan0 set power_save off`.

3. Installing pigpio and running it's daemon:
    $ sudo apt update
    $ sudo apt install -y python3-setuptools python3-full git
    $ sudo wget https://github.com/joan2937/pigpio/archive/refs/tags/v79.tar.gz
    $ sudo tar zxf v79.tar.gz
    $ cd pigpio-79
    $ sudo make
    $ sudo make install
    $ sudo ldconfig
    $ sudo pip3 install pigpio
    $ cd pigpio-79
    $ sudo pigpiod
```

#!/usr/bin/env python3
"""
RetroPhone GPIO Monitor
-----------------------
Dieses Skript zeigt in Echtzeit die Zustände der relevanten GPIO-Pins:
- HOOK  (GPIO 18)
- PULSE (GPIO 23)
- POS1  (GPIO 24)

Verwendung:
  1. Phone-Daemon stoppen:
       sudo systemctl stop phone-daemon.service
  2. Dieses Skript starten:
       sudo python3 /usr/local/retrophone/gpio_monitor.py
  3. Beobachte die Anzeige beim Wählen oder Hörer bewegen.
  4. Beenden mit STRG + C
"""

import RPi.GPIO as GPIO
import time
import os

# --- GPIO Definitionen ---
PIN_PULSE = 23   # Impulsleitung Wählscheibe
PIN_HOOK  = 18   # Hörer-Kontakt
PIN_POS1  = 24   # Rücklaufkontakt

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for p in (PIN_PULSE, PIN_HOOK, PIN_POS1):
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"GPIO initialisiert (BCM): PULSE={PIN_PULSE}, HOOK={PIN_HOOK}, POS1={PIN_POS1}")
    print("-------------------------------------------------------------")

def read_states():
    hook  = GPIO.input(PIN_HOOK)
    pulse = GPIO.input(PIN_PULSE)
    pos1  = GPIO.input(PIN_POS1)
    return hook, pulse, pos1

def describe_state(hook, pulse, pos1):
    hook_state  = "OFFHOOK" if hook == 0 else "ONHOOK"
    pulse_state = "LOW" if pulse == 0 else "HIGH"
    pos1_state  = "RUECKLAUF" if pos1 == 0 else "RUHE"
    return f"HOOK={hook} ({hook_state})  PULSE={pulse} ({pulse_state})  POS1={pos1} ({pos1_state})"

def main():
    os.system("clear")
    print("Starte RetroPhone GPIO-Monitor")
    print("Drücke STRG+C zum Beenden.\n")
    setup_gpio()
    try:
        while True:
            hook, pulse, pos1 = read_states()
            text = describe_state(hook, pulse, pos1)
            print(text, end="\r", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nBeendet durch Benutzer.")
    finally:
        GPIO.cleanup()
        print("GPIO cleanup abgeschlossen.")

if __name__ == "__main__":
    main()

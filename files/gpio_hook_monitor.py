#!/usr/bin/env python3
"""
RetroPhone HOOK-Monitor
-----------------------
Zeigt in Echtzeit den Zustand von GPIO 18 (HOOK-Kontakt).
0 = Hörer abgehoben (OFFHOOK)
1 = Hörer aufgelegt (ONHOOK)
"""

import RPi.GPIO as GPIO
import time
import os

PIN_HOOK = 18

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN_HOOK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"GPIO {PIN_HOOK} initialisiert (HOOK)")
    print("----------------------------------")

def main():
    os.system("clear")
    print("Starte HOOK-Monitor (GPIO 18)")
    print("Drücke STRG+C zum Beenden.\n")
    setup_gpio()
    try:
        while True:
            hook = GPIO.input(PIN_HOOK)
            state = "OFFHOOK" if hook == 0 else "ONHOOK"
            print(f"HOOK={hook}  ({state})", end="\r", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nBeendet durch Benutzer.")
    finally:
        GPIO.cleanup()
        print("GPIO cleanup abgeschlossen.")

if __name__ == "__main__":
    main()

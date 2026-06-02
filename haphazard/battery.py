"""
SunFounder PiPower 5 UPS battery monitor.

The PiPower 5's onboard MCU exposes battery telemetry over I2C. On this unit it
answers at address 0x5c (SunFounder docs say 0x5a — verify with `i2cdetect -y 1`).
Values are LITTLE-endian. The MCU runs the fuel gauge, so percentage and charging
state are read directly. Requires SunFounder's device-tree overlay
(`dtoverlay=sunfounder-pipower5` in config.txt) so the MCU's I2C reaches the Pi's
GPIO bus — AND the PiPower 5 must sit directly on the GPIO (a HAT between it and
the Pi that doesn't pass GPIO 2/3 through will leave the bus empty).

Talks over raw /dev/i2c-1 (pure stdlib, no deps). Off-Pi, read() returns mock
data with "mock": True so the UI still renders.
"""

import fcntl
import os
import time

I2C_BUS = 1
PIPOWER_ADDR = 0x5c
_I2C_SLAVE = 0x0703

# register map (little-endian; mV / mA / % / 0|1)
R_INPUT_MV = 0
R_OUTPUT_MV = 4
R_BATT_MV = 8
R_BATT_MA = 10      # signed: + = charging into the pack
R_PERCENT = 12      # u8
R_CAPACITY = 13     # u16 mAh
R_CHARGING = 18     # u8 (0 = no, 1 = yes)


def _signed16(v):
    return v - 65536 if v > 32767 else v


class _PiPower:
    def __init__(self, bus, addr=PIPOWER_ADDR):
        self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        fcntl.ioctl(self._fd, _I2C_SLAVE, addr)

    def word(self, reg):   # little-endian 16-bit
        os.write(self._fd, bytes([reg & 0xFF]))
        d = os.read(self._fd, 2)
        return d[0] | (d[1] << 8)

    def byte(self, reg):
        os.write(self._fd, bytes([reg & 0xFF]))
        return os.read(self._fd, 1)[0]


_dev = None
_dev_failed = False


def _device():
    global _dev, _dev_failed
    if _dev is None and not _dev_failed:
        try:
            _dev = _PiPower(I2C_BUS)
        except Exception:
            _dev_failed = True
    return _dev


def _runtime_min(pct, draw_ma, cap_mah):
    if not draw_ma or draw_ma < 1 or not cap_mah:
        return None
    return int(cap_mah * pct / 100.0 / draw_ma * 60)


def read():
    """Return battery state dict. Never raises."""
    dev = _device()
    if dev is None:
        t = time.time() % 600
        pct = 55 + 40 * (t / 600.0)
        return {
            "mock": True, "voltage": round(7.0 + 1.4 * pct / 100, 2),
            "current_ma": -420.0, "power_w": 3.3, "percent": round(pct, 1),
            "charging": False, "runtime_min": _runtime_min(pct, 420, 5000),
        }
    try:
        v = dev.word(R_BATT_MV) / 1000.0
        i = float(_signed16(dev.word(R_BATT_MA)))
        pct = float(dev.byte(R_PERCENT))
        charging = dev.byte(R_CHARGING) == 1
        cap = dev.word(R_CAPACITY)
        return {
            "mock": False,
            "voltage": round(v, 2),
            "current_ma": round(i, 1),
            "power_w": round(v * abs(i) / 1000.0, 2),
            "percent": pct,
            "charging": charging,
            "runtime_min": None if charging else _runtime_min(pct, abs(i), cap),
        }
    except Exception:
        return {"mock": True, "voltage": None, "current_ma": None,
                "power_w": None, "percent": None, "charging": False,
                "runtime_min": None, "error": "i2c read failed"}

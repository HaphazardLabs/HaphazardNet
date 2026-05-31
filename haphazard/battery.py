"""
SEENGREAT Pi Zero UPS HAT (A) battery monitor.

Hardware: onboard INA219 current/voltage sensor on I2C bus 1 at address 0x43
(confirmed via SEENGREAT wiki + `i2cdetect -y 1`). 3.7V LiPo, ~1.8A out,
1500mAh stock cell (~9h standby).

Talks to the INA219 over RAW /dev/i2c-1 ioctl (pure stdlib: os + fcntl) so the
panel has ZERO pip dependencies — important because the field kit is offline and
we can't pip-install on it. Calibration matches the SEENGREAT/Waveshare "32V_2A"
reference so numbers line up with their bundled INA219.py demo. If the bus/chip
isn't there (e.g. running the UI on a dev laptop), read() returns mock data with
"mock": True so the web UI still renders.
"""

import fcntl
import os
import time

I2C_BUS = 1
INA219_ADDR = 0x43          # SEENGREAT UPS HAT (A)
BATTERY_CAPACITY_MAH = 1500  # stock cell; change if you swap batteries

_I2C_SLAVE = 0x0703         # linux/i2c-dev.h ioctl: set slave address

# INA219 register map
_REG_CONFIG = 0x00
_REG_SHUNTVOLTAGE = 0x01
_REG_BUSVOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05

# LiPo voltage window used for the % estimate (3.0V empty .. 4.2V full)
_V_EMPTY = 3.0
_V_FULL = 4.2


def _to_signed(val):
    """16-bit two's complement -> signed int."""
    if val > 32767:
        val -= 65536
    return val


class _INA219:
    """Minimal INA219 driver over raw /dev/i2c-N, 32V/2A calibration."""

    def __init__(self, bus, addr=INA219_ADDR):
        self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        fcntl.ioctl(self._fd, _I2C_SLAVE, addr)
        self._current_lsb = 0.1      # 100uA per bit
        self._power_lsb = 0.002      # 2mW per bit
        self._cal_value = 4096
        self._calibrate()

    def _write(self, reg, value):
        os.write(self._fd, bytes([reg & 0xFF, (value >> 8) & 0xFF, value & 0xFF]))

    def _read(self, reg):
        os.write(self._fd, bytes([reg & 0xFF]))
        data = os.read(self._fd, 2)
        return (data[0] << 8) | data[1]

    def _calibrate(self):
        self._write(_REG_CALIBRATION, self._cal_value)
        # bus 32V range, gain /8 (320mV), 12-bit bus+shunt ADC, continuous
        config = (0x01 << 13) | (0x03 << 11) | (0x03 << 7) | (0x03 << 3) | 0x07
        self._write(_REG_CONFIG, config)

    def bus_voltage_v(self):
        self._write(_REG_CALIBRATION, self._cal_value)
        raw = self._read(_REG_BUSVOLTAGE)
        return (raw >> 3) * 0.004

    def current_ma(self):
        self._write(_REG_CALIBRATION, self._cal_value)
        return _to_signed(self._read(_REG_CURRENT)) * self._current_lsb

    def power_w(self):
        self._write(_REG_CALIBRATION, self._cal_value)
        return self._read(_REG_POWER) * self._power_lsb

    def close(self):
        try:
            os.close(self._fd)
        except Exception:
            pass


_dev = None
_dev_failed = False


def _device():
    global _dev, _dev_failed
    if _dev is None and not _dev_failed:
        try:
            _dev = _INA219(I2C_BUS)
        except Exception:
            _dev_failed = True  # no bus / no chip -> mock from here on
    return _dev


def _percent(voltage):
    pct = (voltage - _V_EMPTY) / (_V_FULL - _V_EMPTY) * 100.0
    return max(0.0, min(100.0, pct))


def read():
    """Return a dict describing battery state. Never raises."""
    dev = _device()
    if dev is None:
        # Mock data for off-Pi preview. Slow sawtooth so the UI looks alive.
        t = time.time() % 600
        pct = 55 + 40 * (t / 600.0)
        return {
            "mock": True,
            "voltage": round(_V_EMPTY + (_V_FULL - _V_EMPTY) * pct / 100, 2),
            "current_ma": -420.0,
            "power_w": 1.7,
            "percent": round(pct, 1),
            "charging": False,
            "runtime_min": _runtime_min(pct, 420.0),
        }
    try:
        v = dev.bus_voltage_v()
        i = dev.current_ma()
        p = dev.power_w()
        pct = _percent(v)
        charging = i > 30  # positive current into the pack = charging
        return {
            "mock": False,
            "voltage": round(v, 2),
            "current_ma": round(i, 1),
            "power_w": round(p, 2),
            "percent": round(pct, 1),
            "charging": charging,
            "runtime_min": None if charging else _runtime_min(pct, abs(i)),
        }
    except Exception:
        return {"mock": True, "voltage": None, "current_ma": None,
                "power_w": None, "percent": None, "charging": False,
                "runtime_min": None, "error": "i2c read failed"}


def _runtime_min(pct, draw_ma):
    """Rough remaining runtime in minutes at the current draw."""
    if not draw_ma or draw_ma < 1:
        return None
    remaining_mah = BATTERY_CAPACITY_MAH * pct / 100.0
    return int(remaining_mah / draw_ma * 60)

#!/usr/bin/env python3
"""Schreibt empfangene EnOcean-4BS-Telegramme in eine Diagnose-CSV."""
import csv
import os
import time
from pathlib import Path

import serial

from esp3 import bytes_to_hex, read_esp3_frame

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/serial0")
BAUDRATE = int(os.environ.get("BAUDRATE", "57600"))

LOGFILE = Path(os.environ.get("ENOCEAN_LOGFILE", "/var/log/enocean_all_a5.csv"))


def main():
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not LOGFILE.exists()

    with LOGFILE.open("a", newline="", encoding="utf-8") as f, \
            serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1) as ser:

        writer = csv.writer(f)
        if new_file:
            writer.writerow([
                "timestamp",
                "sender_id",
                "rorg",
                "db3",
                "db2",
                "db1",
                "db0",
                "status",
                "data_hex",
                "opt_hex",
            ])

        print(f"Logge alle A5-Telegramme nach {LOGFILE}")
        print("Strg+C zum Abbrechen.\n")

        while True:
            frame = read_esp3_frame(ser)
            if frame is None:
                continue

            packet_type, data, opt_data = frame

            if packet_type != 0x01:  # nur RADIO_ERP1
                continue
            if len(data) < 10:
                continue

            rorg = data[0]
            if rorg != 0xA5:
                continue  # nur 4BS

            db3, db2, db1, db0 = data[1], data[2], data[3], data[4]
            sender_id = data[5:9]
            status = data[9]

            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            writer.writerow([
                ts_str,
                bytes_to_hex(sender_id),
                f"{rorg:02X}",
                f"{db3:02X}",
                f"{db2:02X}",
                f"{db1:02X}",
                f"{db0:02X}",
                f"{status:02X}",
                bytes_to_hex(data),
                bytes_to_hex(opt_data),
            ])
            f.flush()

            print(
                f"{ts_str} ID={bytes_to_hex(sender_id)} "
                f"RORG={rorg:02X} DB3..0={db3:02X} {db2:02X} {db1:02X} {db0:02X} "
                f"ST={status:02X}"
            )


if __name__ == "__main__":
    main()

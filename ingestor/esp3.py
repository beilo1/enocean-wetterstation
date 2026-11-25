"""Gemeinsamer ESP3-Frame-Reader für Ingestor und Diagnose."""

def read_esp3_frame(ser):
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b[0] == 0x55:
            break

    header = ser.read(4)
    if len(header) < 4:
        return None

    data_len = (header[0] << 8) | header[1]
    opt_len = header[2]
    packet_type = header[3]

    crc_header = ser.read(1)
    if len(crc_header) < 1:
        return None

    data = ser.read(data_len)
    if len(data) < data_len:
        return None

    opt_data = ser.read(opt_len)
    if len(opt_data) < opt_len:
        return None

    crc_data = ser.read(1)
    if len(crc_data) < 1:
        return None

    return packet_type, data, opt_data


def bytes_to_hex(b: bytes) -> str:
    return b.hex().upper()

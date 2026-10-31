#!/usr/bin/env python3
"""Preserve complete captures and cautiously interpret COOLIX-shaped frames."""
import argparse
import json
from pathlib import Path
import re

from coolix_states import decode


def analyze_raw(raw):
    frames = []
    offset = 0

    def incomplete(reason):
        return {"format": "partial COOLIX-shaped capture" if frames else "unclassified",
                "complete": False, "reason": reason, "frames": frames,
                "frames_identical": None, "carrier_measured": False}

    while offset < len(raw):
        part = raw[offset:offset + 99]
        if len(part) != 99 or not (3900 <= part[0] <= 5300 and 3800 <= part[1] <= 5000):
            return incomplete("Unexpected header/frame length")
        if not all(250 <= value <= 850 for value in part[2::2]):
            return incomplete("Unexpected data mark duration")
        spaces = part[3:98:2]
        if not all(250 <= value <= 900 or 1150 <= value <= 2200 for value in spaces):
            return incomplete("Ambiguous data space")
        bits = [int(value > 1000) for value in spaces]
        octets = [sum(bit << (7 - j) for j, bit in enumerate(bits[i:i + 8])) for i in range(0, 48, 8)]
        inverse_valid = all(octets[i] ^ octets[i + 1] == 255 for i in (0, 2, 4))
        frame = {"wire_hex": " ".join(f"{x:02X}" for x in octets), "inverse_valid": inverse_valid}
        if inverse_valid:
            code = octets[0] << 16 | octets[2] << 8 | octets[4]
            frame["code"] = f"0x{code:06X}"
            try:
                frame["normal_state"] = decode(code)
            except ValueError:
                frame["normal_state"] = None
                frame["note"] = "Special command or state outside the current normal-state subset"
        frames.append(frame)
        offset += 99
        if offset < len(raw):
            if not 3500 <= raw[offset] <= 15000:
                return incomplete("Unexpected inter-frame gap")
            offset += 1
            if offset == len(raw):
                return incomplete("Trailing gap without following frame")
    return {
        "format": "COOLIX-compatible" if all(f["inverse_valid"] for f in frames) else "COOLIX48-shaped; parity differs",
        "complete": True,
        "frames": frames,
        "frames_identical": len({frame["wire_hex"] for frame in frames}) == 1 if len(frames) > 1 else None,
        "carrier_measured": False,
    }


def parse_log(text):
    result = []
    for index, match in enumerate(re.finditer(r"\[([^\]]+)\] BEGIN_CAPTURE(.*?)END_CAPTURE", text, re.S), 1):
        stamp, body = match.groups()
        raw = [int(value) for value in re.search(r"RAW_US=([\d,]+)", body).group(1).split(",")]
        count = int(re.search(r"COUNT=(\d+)", body).group(1))
        if count != len(raw) or not raw or len(raw) % 2 != 1 or any(value <= 0 for value in raw):
            raise ValueError(f"Invalid raw capture at {stamp}")
        capture_id = re.search(r"CAPTURE_ID=(\d+)", body)
        result.append({
            "log_index": index, "device_capture_id": int(capture_id.group(1)) if capture_id else None,
            "captured_at": stamp.replace(" ", "T") + "+08:00",
            "count": count, "raw_us": raw, "analysis": analyze_raw(raw),
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = args.log.read_text(errors="replace")
    captures = parse_log(text)
    result = {"source_log": str(args.log), "captures": captures,
              "device_errors": re.findall(r"\[[^\]]+\] ERROR[^\r\n]+", text),
              "note": "Decoded state is separate from the user's physical button/position annotation"}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for capture in captures:
        analysis = capture["analysis"]
        frames = analysis.get("frames", [])
        first = frames[0] if frames else {}
        print(json.dumps({"id": capture["device_capture_id"], "time": capture["captured_at"],
                          "count": capture["count"], "format": analysis["format"],
                          "code": first.get("code"), "state": first.get("normal_state"),
                          "repeats_identical": analysis.get("frames_identical")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

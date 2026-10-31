#!/usr/bin/env python3
"""Generate RG94A/BGEF candidate states; this tool does not transmit IR.

Field definitions and Celsius mapping:
https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.h
Mode restrictions and fan-only encoding:
https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.cpp
"""
import argparse
import json
from pathlib import Path

TEMP_CODES = (0, 1, 3, 2, 6, 7, 5, 4, 12, 13, 9, 8, 10, 11)
FANS = {"low": 4, "medium": 2, "high": 1, "auto": 5}
MODES = {"cool": 0, "dry": 1, "auto": 2, "heat": 3, "fan": 1}
ROOT = Path(__file__).resolve().parents[1]


def capture_index():
    """Index complete matching original-remote samples, excluding partials."""
    result = {}
    sources = ("captures/2026-11-01-york-rg94a.json",
               "captures/york-remote-characterization.json")
    for source in sources:
        path = ROOT / source
        if not path.exists():
            continue
        for capture in json.loads(path.read_text())["captures"]:
            analysis = capture["analysis"]
            if "state_hex" in analysis:
                valid = analysis.get("complement_pairs_valid") and analysis.get("two_frames_identical")
                code = analysis["state_hex"]
                capture_id = capture["id"]
            else:
                frames = analysis.get("frames", [])
                valid = (analysis.get("complete") and analysis.get("frames_identical")
                         and len(frames) >= 2 and all(f.get("inverse_valid") for f in frames))
                code = frames[0].get("code") if frames else None
                capture_id = capture["device_capture_id"]
            if valid and code:
                result.setdefault(code, []).append({"file": source, "capture_id": capture_id})
    return result


def encode(mode, temperature, fan):
    if mode not in MODES or fan not in FANS:
        raise ValueError("Unknown mode or fan")
    if mode in ("auto", "dry") and fan != "auto":
        raise ValueError("RG94A/BGEF AUTO/DRY modes use automatic fan only")
    if mode == "fan":
        if temperature is not None:
            raise ValueError("Fan-only mode has no temperature setting")
        temp_code = 14
    else:
        if type(temperature) is not int or not 17 <= temperature <= 30:
            raise ValueError("Temperature must be an integer from 17 to 30 C")
        temp_code = TEMP_CODES[temperature - 17]
    fan_code = 0 if mode in ("auto", "dry") else FANS[fan]
    # B2 prefix; ignore the remote's temperature sensor (0x1F); zone-follow off.
    return 0xB21F00 | (fan_code << 13) | (temp_code << 4) | (MODES[mode] << 2)


def decode(code):
    if type(code) is not int or code & 0xFF1F03 != 0xB21F00 or code > 0xFFFFFF:
        raise ValueError("Not a supported normal state; special commands need separate decoding")
    mode_code = (code >> 2) & 3
    temp_code = (code >> 4) & 15
    fan_code = (code >> 13) & 7
    mode = ("cool", "dry", "auto", "heat")[mode_code]
    if mode == "dry" and temp_code == 14:
        mode, temperature = "fan", None
    else:
        if temp_code not in TEMP_CODES:
            raise ValueError("Invalid Celsius temperature encoding")
        temperature = 17 + TEMP_CODES.index(temp_code)
    if mode in ("auto", "dry"):
        if fan_code != 0:
            raise ValueError("Noncanonical AUTO/DRY fan setting")
        fan = "auto"
    else:
        reverse_fans = {value: key for key, value in FANS.items()}
        if fan_code not in reverse_fans:
            raise ValueError("Unsupported fan setting")
        fan = reverse_fans[fan_code]
    return {"mode": mode, "temperature_celsius": temperature, "fan": fan}


def wire_bytes(code):
    result = []
    for shift in (16, 8, 0):
        byte = (code >> shift) & 255
        result.extend((byte, byte ^ 255))
    return result


def state_record(mode, temperature, fan, capture_evidence=None):
    code = encode(mode, temperature, fan)
    replayed = mode == "cool" and fan == "high" and temperature == 25
    if capture_evidence is None:
        capture_evidence = capture_index()
    references = capture_evidence.get(f"0x{code:06X}", [])
    locked_fan = mode in ("auto", "dry")
    return {
        "id": f"{mode}-{temperature if temperature is not None else 'none'}-{fan}",
        **decode(code),
        "fan_field": (code >> 13) & 7,
        "user_fan_label_zh": ("模式锁定，不可调" if locked_fan else
                              {"auto": "微风（用户称呼）", "low": "低", "medium": "中", "high": "高"}[fan]),
        "manual_fan_adjustable": not locked_fan,
        "code": f"0x{code:06X}",
        "wire_bytes_hex": " ".join(f"{byte:02X}" for byte in wire_bytes(code)),
        "evidence": {
            "remote_capture": bool(references),
            "remote_capture_references": references,
            "raw_replay_user_confirmed": replayed,
            "generated_waveform_validation": "See captures/york-state-validation.json",
        },
        "appliance_heat_support": "unknown" if mode == "heat" else None,
    }


def catalog():
    states = []
    capture_evidence = capture_index()
    for mode in ("cool", "heat", "dry", "auto", "fan"):
        temperatures = (None,) if mode == "fan" else range(17, 31)
        fans = ("auto",) if mode in ("dry", "auto") else FANS
        for temperature in temperatures:
            for fan in fans:
                states.append(state_record(mode, temperature, fan, capture_evidence))
    return {
        "remote": "YORK RG94A/BGEF",
        "protocol": "COOLIX-compatible normal states",
        "state_count": len(states),
        "carrier_setting_khz": 38,
        "status": "Generated candidate codes, not a claim that all combinations were captured or tested",
        "validation_file": "captures/york-state-validation.json",
        "fan_naming_note": "Internal auto follows the protocol library: field 5 is the first selectable level, called 微风 by the user; field 0 is locked in AUTO/DRY. Actual airflow is not measured.",
        "scope": "Normal on-state temperature/mode/fan only; no timers, swing, sleep, turbo, ion, clock or follow-me",
        "sources": [
            "https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.h",
            "https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.cpp",
            "https://cdn.jseducation.se/files/pages/anva_ndarmanual-york-fja_rr_18.pdf",
        ],
        "states": states,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    state_parser = sub.add_parser("state")
    state_parser.add_argument("--mode", choices=MODES, required=True)
    state_parser.add_argument("--temperature", type=int)
    state_parser.add_argument("--fan", choices=FANS, required=True)
    state_parser.add_argument("--sequence", type=int, default=1)
    button_parser = sub.add_parser("button", help="Preview one captured-button replay; does not send")
    button_parser.add_argument("--name", required=True)
    button_parser.add_argument("--sequence", type=int, default=1)
    catalog_parser = sub.add_parser("catalog")
    catalog_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "catalog":
        result = catalog()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"Saved {result['state_count']} candidate states to {args.output}")
    else:
        try:
            if not 1 <= args.sequence <= 0xFFFFFFFF:
                raise ValueError("Sequence must be from 1 to 4294967295")
            if args.action == "button":
                index_path = ROOT / 'captures/york-replay-index.json'
                index = json.loads(index_path.read_text())
                matches = [b for b in index['buttons'] if b['id'] == args.name]
                if not matches:
                    raise ValueError('Unknown/unconfirmed button. Available: ' + ', '.join(b['id'] for b in index['buttons']))
                result = dict(matches[0])
                result['expected_catalog_tag'] = index['catalog_tag']
                result['serial_command'] = f"PRESS {args.sequence} {result['index']}"
            else:
                result = state_record(args.mode, args.temperature, args.fan)
                result["serial_command"] = f"SEND {args.sequence} {result['code'][2:]}"
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

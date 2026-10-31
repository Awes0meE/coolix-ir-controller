// SEND generates normal two-frame states; PRESS replays one captured button burst.
// Original frame counts and inter-frame gaps are preserved. Boot never sends.
#define IR_SEND_PIN 3
#define IR_SEND_DUTY_CYCLE_PERCENT 30
#define DISABLE_CODE_FOR_RECEIVER
#define NO_LED_FEEDBACK_CODE
#include <IRremote.hpp>
#include "CapturedButtons.h"
#include <stdio.h>
#include <string.h>

uint32_t lastSequence = 0;
uint32_t lastSentAt = 0;
bool cycle24Attempted = false;
constexpr uint32_t MIN_INTERVAL_MS = 2000;
char command[40];
uint8_t commandLength = 0;
bool commandOverflow = false;

bool validNormalState(uint32_t code) {
    if (code > 0xFFFFFFUL || (code & 0xFF1F03UL) != 0xB21F00UL) return false;
    const uint8_t mode = (code >> 2) & 3;
    const uint8_t temperature = (code >> 4) & 15;
    const uint8_t fan = (code >> 13) & 7;
    const bool fanOnly = mode == 1 && temperature == 14;
    if (!fanOnly && temperature > 13) return false;
    if (!fanOnly && (mode == 1 || mode == 2)) return fan == 0;
    return fan == 1 || fan == 2 || fan == 4 || fan == 5;
}

void sendByte(uint8_t value) {
    for (uint8_t mask = 0x80; mask != 0; mask >>= 1) {
        IrSender.mark(552);
        IrSender.space(value & mask ? 1656 : 552);
    }
}

void sendState(uint32_t code) {
    // Nominal COOLIX timings from the referenced protocol implementation.
    IrSender.enableIROut(38);
    for (uint8_t frame = 0; frame < 2; ++frame) {
        IrSender.mark(4692);
        IrSender.space(4416);
        for (int8_t shift = 16; shift >= 0; shift -= 8) {
            const uint8_t value = (code >> shift) & 0xFF;
            sendByte(value);
            sendByte(value ^ 0xFF);
        }
        IrSender.mark(552);
        if (frame == 0) IrSender.space(5244);
    }
    digitalWrite(IR_SEND_PIN, LOW);
}

void sendCapturedButton(uint8_t index) {
    const uint16_t *timings = reinterpret_cast<const uint16_t *>(
        pgm_read_ptr(&kCapturedButtons[index - 1].timings));
    const uint16_t count = pgm_read_word(&kCapturedButtons[index - 1].count);
    IrSender.sendRaw_P(timings, count, 38);
    digitalWrite(IR_SEND_PIN, LOW);
}

void printStatus() {
    Serial.print(F("STATUS last_seq="));
    Serial.print(lastSequence);
    Serial.print(F(" D3="));
    Serial.print(digitalRead(IR_SEND_PIN) == LOW ? F("LOW") : F("HIGH"));
    Serial.print(F(" uptime_ms="));
    Serial.print(millis());
    Serial.print(F(" buttons="));
    Serial.print(kCapturedButtonCount);
    Serial.print(F(" catalog="));
    Serial.print(F(BUTTON_CATALOG_TAG));
    Serial.print(F(" min_interval_ms="));
    Serial.print(MIN_INTERVAL_MS);
    Serial.print(F(" cycle24_attempted="));
    Serial.println(cycle24Attempted ? 1 : 0);
}

void handleCommand() {
    if (!commandLength) return;
    if (strcmp(command, "STATUS") == 0) {
        printStatus();
        return;
    }
    unsigned long sequence, code = 0, buttonIndex = 0;
    char extra;
    const bool normal = sscanf(command, "SEND %lu %lx %c", &sequence, &code, &extra) == 2;
    const bool captured = !normal &&
        sscanf(command, "PRESS %lu %lu %c", &sequence, &buttonIndex, &extra) == 2;
    const bool cycle24 = !normal && !captured &&
        sscanf(command, "CYCLE24 %lu %c", &sequence, &extra) == 1;
    if ((!normal && !captured && !cycle24) || sequence == 0 ||
        (normal && !validNormalState(code)) ||
        (captured && (buttonIndex == 0 || buttonIndex > kCapturedButtonCount))) {
        Serial.println(F("REJECTED. Use SEND <seq> <hex-state>, PRESS <seq> <button-index>, CYCLE24 <seq>."));
        return;
    }
    if (cycle24 && cycle24Attempted) {
        Serial.println(F("REJECTED CYCLE24 already attempted this boot; no retry."));
        return;
    }
    if (sequence <= lastSequence) {
        Serial.println(F("REJECTED duplicate/stale sequence; no transmission."));
        return;
    }
    if (lastSequence && millis() - lastSentAt < MIN_INTERVAL_MS) {
        Serial.println(F("REJECTED cooldown; no automatic retry."));
        return;
    }
    lastSequence = sequence; // Consume sequence before emitting.
    Serial.print(F("TX_BEGIN seq="));
    Serial.print(sequence);
    if (normal) {
        Serial.print(F(" code=0x"));
        Serial.println(code, HEX);
    } else if (captured) {
        Serial.print(F(" button="));
        Serial.println(buttonIndex);
    } else {
        cycle24Attempted = true;
        Serial.println(F(" CYCLE24 off=B27BE0 off_end_to_on_start_us=1000000 on=B23F40"));
    }
    Serial.flush();
    if (normal) {
        sendState(code);
    } else if (captured) {
        sendCapturedButton(buttonIndex);
    } else {
        // One explicitly requested pair; ordinary commands retain their 2s limit.
        // No serial writes or host round trips between the off burst and on burst.
        sendCapturedButton(BUTTON_INDEX_POWER_OFF);
        const uint32_t offEndMicros = micros();
        while (uint32_t(micros() - offEndMicros) < 1000000UL) { }
        const uint32_t onStartMicros = micros();
        sendState(0xB23F40UL);  // On, COOL, 24 C, high fan.
        Serial.print(F("CYCLE24_DONE off_end_us="));
        Serial.print(offEndMicros);
        Serial.print(F(" on_start_us="));
        Serial.print(onStartMicros);
        Serial.print(F(" gap_us="));
        Serial.println(uint32_t(onStartMicros - offEndMicros));
    }
    lastSentAt = millis();
    Serial.print(F("TX_DONE seq="));
    Serial.println(sequence);
    printStatus();
}

void setup() {
    digitalWrite(IR_SEND_PIN, LOW);
    pinMode(IR_SEND_PIN, OUTPUT);
    IrSender.begin();
    Serial.begin(115200);
    Serial.println(F("BOOT ACStateControl; D3 idle LOW; no automatic transmission."));
    Serial.println(F("SEND <seq> <hex-state>; PRESS <seq> <button-index>; CYCLE24 <seq>; STATUS."));
    Serial.println(F("CYCLE24: off, wait 1s, on COOL/24C/high; once per boot. Other commands: 2s interval."));
    printStatus();
}

void loop() {
    while (Serial.available()) {
        const char ch = Serial.read();
        if (ch == '\r' || ch == '\n') {
            if (!commandOverflow) {
                command[commandLength] = '\0';
                handleCommand();
            } else {
                Serial.println(F("REJECTED overlong command."));
            }
            commandLength = 0;
            commandOverflow = false;
        } else if (commandLength < sizeof(command) - 1) {
            command[commandLength++] = ch;
        } else {
            commandOverflow = true;
        }
    }
}

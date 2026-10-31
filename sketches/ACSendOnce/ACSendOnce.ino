// User-authorized one-shot test: transmitter IN -> D3, +5V -> UNO 5V, common GND.
// Boot never sends. Only the exact serial line SEND25ONCE triggers one burst.
// A RAM latch prevents any further sends until reset; reset still never auto-sends.
#define IR_SEND_PIN 3
#define IR_SEND_DUTY_CYCLE_PERCENT 30
#define DISABLE_CODE_FOR_RECEIVER
#define NO_LED_FEEDBACK_CODE
#include <IRremote.hpp>
#include "Captured25.h"
#include <string.h>

bool attempted = false;
char command[16];
uint8_t commandLength = 0;
bool commandOverflow = false;

void printStatus() {
    Serial.print(F("STATUS attempted="));
    Serial.print(attempted ? 1 : 0);
    Serial.print(F(" D3="));
    Serial.print(digitalRead(IR_SEND_PIN) == LOW ? F("LOW") : F("HIGH"));
    Serial.print(F(" uptime_ms="));
    Serial.println(millis());
}

void handleCommand() {
    if (strcmp(command, "STATUS") == 0) {
        printStatus();
    } else if (strcmp(command, "SEND25ONCE") == 0) {
        if (attempted) {
            Serial.println(F("BLOCKED: this boot already attempted its one burst."));
            return;
        }
        attempted = true; // Consume the one-shot before touching the emitter.
        Serial.println(F("TX_BEGIN 0xB23FC0 COOL MAX_FAN 25C; one captured burst, 38kHz/30%."));
        Serial.flush();
        IrSender.sendRaw_P(kCaptured25Micros, kCaptured25Length, 38);
        digitalWrite(IR_SEND_PIN, LOW);
        Serial.println(F("TX_DONE; further SEND25ONCE commands are blocked until reset."));
        printStatus();
    } else if (commandLength != 0) {
        Serial.println(F("Unknown command. Use STATUS or SEND25ONCE."));
    }
}

void setup() {
    digitalWrite(IR_SEND_PIN, LOW);
    pinMode(IR_SEND_PIN, OUTPUT);
    IrSender.begin();
    Serial.begin(115200);
    Serial.println(F("BOOT ACSendOnce; D3 idle LOW; NO automatic transmission."));
    Serial.println(F("Commands: STATUS, SEND25ONCE. One burst maximum per boot."));
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
                Serial.println(F("Ignored overlong command."));
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

// Confirm the receiver's voltage and pinout before connecting it.
// Only the receiver signal assignment is fixed here: OUT/S -> UNO D2.
#define IR_RECEIVE_PIN 2
#define RAW_BUFFER_LENGTH 200
#include <IRremote.hpp>

void setup() {
    Serial.begin(115200);
    IrReceiver.begin(IR_RECEIVE_PIN, ENABLE_LED_FEEDBACK);
    Serial.println(F("IR Hub receive probe; IRremote " VERSION_IRREMOTE));
    Serial.println(F("Receiver OUT/S: D2. Serial: 115200 baud."));
    Serial.println(F("Press and release one remote button; wait 1 second between tests."));
}

void loop() {
    if (!IrReceiver.decode()) {
        return;
    }

    if (IrReceiver.decodedIRData.flags & IRDATA_FLAGS_WAS_OVERFLOW) {
        Serial.println(F("OVERFLOW: frame too long; capture is incomplete."));
        Serial.println(F("Review RAW_BUFFER_LENGTH and available RAM before increasing it."));
        IrReceiver.resume();
        return;
    }

    IrReceiver.printIRResultShort(&Serial);
    if (!(IrReceiver.decodedIRData.flags & IRDATA_FLAGS_IS_REPEAT)) {
        IrReceiver.printIRSendUsage(&Serial);
        IrReceiver.printIRResultRawFormatted(&Serial, true);
        Serial.println();
    }
    // Printing raw timings may miss repeat frames. This is a diagnostic probe.
    IrReceiver.resume();
}

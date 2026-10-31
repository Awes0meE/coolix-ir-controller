// UNO R3 + 1838B receiver: S -> D2, VCC -> 5V, GND -> GND.
// Capture only. D3 is held LOW to inhibit the connected active-high transmitter.
// IRremote 4.7.1: use 16-bit ticks so long spaces are not clipped at 12.75 ms.
#define IR_RECEIVE_PIN 2
#define RAW_BUFFER_LENGTH 640
#define RECORD_GAP_MICROS 120000UL
#define USE_16_BIT_TIMING_BUFFER
#define DECODE_HASH
#define NO_LED_FEEDBACK_CODE
#include <IRremote.hpp>

static_assert(sizeof(IRRawbufType) == 2, "Long gaps require 16-bit timing storage");

bool captureArmed = false;
bool continuousCapture = false;
uint16_t captureNumber = 0;
uint32_t armedAtMillis = 0;
constexpr uint32_t CAPTURE_TIMEOUT_MS = 60000;

void printReceiverLevel() {
    Serial.print(F("RX_D2="));
    Serial.println(digitalRead(IR_RECEIVE_PIN) == HIGH ? F("HIGH") : F("LOW"));
    Serial.println(F("A connected 1838B normally reads HIGH between IR bursts."));
}

void armCapture() {
    IrReceiver.stop();
    // Reset a previous partial capture after a timeout or manual re-arm.
    // These fields belong to the pinned IRremote 4.7.1 receiver API.
    IrReceiver.irparams.StateForISR = IR_REC_STATE_STOP;
    IrReceiver.irparams.TickCounterForISR = 0;
    IrReceiver.irparams.rawlen = 0;
    IrReceiver.irparams.OverflowFlag = false;
    Serial.println(F("READY: wait 1 second, then briefly press ONE remote button."));
    Serial.flush();
    IrReceiver.start();
    captureArmed = true;
    armedAtMillis = millis();
}

void printCapture() {
    const IRRawlenType length = IrReceiver.irparams.rawlen;
    if (IrReceiver.irparams.OverflowFlag || length >= RAW_BUFFER_LENGTH - 1) {
        Serial.println(F("ERROR OVERFLOW: capture incomplete; do not replay it."));
        return;
    }
    if (length < 4) {
        Serial.println(F("ERROR TOO_SHORT: likely noise; retry."));
        return;
    }

    Serial.println(F("BEGIN_CAPTURE"));
    Serial.print(F("CAPTURE_ID="));
    Serial.println(++captureNumber);
    Serial.print(F("COUNT="));
    Serial.println(length - 1);
    Serial.println(F("END_GAP_US=120000"));
    // Start with a mark; alternate mark, space. Exclude leading/trailing silence.
    // Output the measured envelope without guessed carrier or compensation.
    Serial.print(F("RAW_US="));
    for (IRRawlenType i = 1; i < length; ++i) {
        const uint32_t duration = static_cast<uint32_t>(IrReceiver.irparams.rawbuf[i]) * MICROS_PER_TICK;
        if (i != 1) {
            Serial.print(',');
        }
        Serial.print(duration);
    }
    Serial.println();
    Serial.println(F("END_CAPTURE"));
    Serial.println(F("Candidate burst only: gaps >=120 ms end capture. Carrier is not measured."));
}

void setup() {
    digitalWrite(3, LOW);
    pinMode(3, OUTPUT);
    Serial.begin(115200);
    IrReceiver.begin(IR_RECEIVE_PIN, DISABLE_LED_FEEDBACK);
    IrReceiver.stop();
    Serial.println(F("IR Hub AC capture / UNO R3 / IRremote " VERSION_IRREMOTE));
    Serial.println(F("Receiver S=D2, VCC=5V, GND=GND. Transmitter D3 held LOW."));
    Serial.println(F("c: one capture; a: continuous captures; x: stop; p: idle D2. Never transmits."));
    printReceiverLevel();
}

void loop() {
    if (Serial.available()) {
        const char command = Serial.read();
        if (command == 'c' || command == 'C') {
            continuousCapture = false;
            armCapture();
        } else if (command == 'a' || command == 'A') {
            continuousCapture = true;
            armCapture();
        } else if (command == 'x' || command == 'X') {
            IrReceiver.stop();
            captureArmed = false;
            continuousCapture = false;
            Serial.println(F("STOPPED; D3 remains LOW."));
        } else if ((command == 'p' || command == 'P') && !captureArmed) {
            printReceiverLevel();
        }
    }
    if (!captureArmed) {
        return;
    }
    if (IrReceiver.available()) {
        IrReceiver.stop();
        captureArmed = false;
        printCapture();
        if (continuousCapture) {
            armCapture();
        } else {
            Serial.println(F("Send c to capture again."));
        }
    } else if (millis() - armedAtMillis >= CAPTURE_TIMEOUT_MS) {
        IrReceiver.stop();
        captureArmed = false;
        continuousCapture = false;
        Serial.println(F("ERROR TIMEOUT: no finished burst in 60 seconds. Send c to retry."));
        printReceiverLevel();
    }
}

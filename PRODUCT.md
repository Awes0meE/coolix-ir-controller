# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Alvin uses a phone to control his YORK air conditioner through his own domain.

## Product Purpose

A mobile remote on the owner’s own domain, backed by a Mac and a USB-connected UNO. All captured remote functions must be accessible, with honest state reporting.

## Operating Context

UNO R3 compatible board, receiver D2 and transmitter D3. The Mac must remain awake and connected. Existing Cloudflare sites and routes must continue working. Personal controller access is the implementation default; it is not a public shared appliance.

## Capabilities and Constraints

- Five modes; 17–30°C; four selectable fan values, called 微风 / 低 / 中 / 高 by the user. AUTO/DRY lock the fan. FAN mode has no setpoint.
- Normal state generation and 11 recorded button samples are available in the project.
- No appliance feedback channel. State means last requested/sent state, with uncertainty for toggles. Never show measured room temperature or claim actual actuator confirmation from a serial ACK.
- Vertical swing is relative stepping, 12 steps per user observation; absolute angle unknown.
- LED cycles display/audible combinations; order unknown. Follow Me short press has no observed output; long press has a captured command, purpose unknown.
- Sleep samples include COOL 25°C and fan field 5. UI must disclose this before sending. Heating support is unverified.
- One-shot on/off timers use either a countdown or a phone-local date/time. The Mac stores and runs tasks after the browser closes.
- One-tap precooling sends COOL 24°C/high immediately, then DRY 24°C/auto after 10 minutes. Dry mode continues until another control action. Manual control or a due timer cancels the remaining precooling stage; cancelling alone does not power off.
- Missed timers and uncertain transmissions are not replayed. Future tasks survive service restart, but the Mac must remain awake with the UNO connected.
- Ordinary firmware commands require 2 seconds between transmissions. No automatic retries on ambiguous transmit outcomes.

## Evidence on Hand

`captures/york-state-catalog.json`, `captures/york-button-catalog.json`, `captures/york-replay-index.json`, `captures/york-full-control-run.json`.

## Implementation Decisions

Assistant-selected implementation for the authorized build: a small Python serial/API service and a self-contained HTML/CSS/JS interface; no frontend build step. Each deployment supplies its own origin, serial port and private tunnel token.

# Controller design

An everyday mobile operating surface. The design should feel calm, tactile and precise, with clear touch targets and immediate command feedback.

- Cool porcelain ground, deep blue ink, one saturated blue for selected controls and primary actions. Blue is a design choice inspired by the supplied 66ccff domain, not an established brand guideline.
- Mobile first: compact identity and connection status, room/device title and power control, a large temperature adjustment area, five mode choices, four fan choices, then secondary functions and recent activity.
- Desktop uses a two-column workspace instead of stretching the phone layout. A small live summary sits beside the primary controls.
- Use one readable sans family, tabular numeric settings, consistent 1.75px SVG line icons, 12–16px surfaces. No decorative charts, stock images, gradients or nested cards.
- A temperature arc represents the actual 17–30 range and supports keyboard input; +/- controls remain the simple primary adjustment.
- Pending edits stay visible until Apply. Never emit multiple IR commands as the user explores the temperature or mode controls.
- All interactive targets at least 44px, visible focus, restrained 180ms transitions, reduced-motion support, no page entrance animation.
- State language: 已发送的设定, 待应用, 未知, 控制器离线, 发送结果未确认. Device connection is not appliance feedback.
- Phone authentication is a lightweight private access screen. The secret stays outside public static assets.

Guidance consulted: Impeccable source skill and Operate/craft-floor references. Its launcher was unavailable; existing repository evidence and the user's brief supply project context.

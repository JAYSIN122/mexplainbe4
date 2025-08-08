# Codex Prompt: 0000 Countdown ELI5 + Infographic

This Markdown document provides a ready‑to‑use prompt for OpenAI Codex (or other LLM) to convert raw JSON output from the `/api/forecast` endpoint into a human‑friendly summary, an ELI5 explanation, and a simple infographic. The goal is to help non‑technical audiences understand the concept of a “0000” event and the estimated countdown based on phase‑gap data.

---

## Instructions for Codex

You are Codex. Your job is to take JSON from our `/api/forecast` endpoint and produce the following sections:

1. **Layman Summary** – A concise explanation of what the “0000” event represents, how the estimate is derived (closing phase gap and GTI coherence), and why the ETA is our best guess rather than a guarantee. Use clear, everyday language.

2. **ELI5 Section** – Explain the concept as if to a five‑year‑old using simple metaphors (for example, two kids on swings syncing up, or two clocks ticking closer together). Keep this section under 80 words.

3. **Infographic (ASCII/Markdown)** – Create a text‑based graphic that shows:
   - The current phase gap in degrees as a progress bar.
   - The closing rate (degrees per day).
   - The GTI (signal strength) value.
   - The ETA in days and the predicted calendar date (YYYY‑MM‑DD).
   - Confidence ranges (68% and 95%) as error ranges.
   Use a Markdown code block for the graphic. Do not generate images.

4. **Null ETA Handling** – If `eta_days` is `null` (meaning the phase gap is opening rather than closing), output a message such as: "The clocks are drifting apart — no countdown yet." Also report the current phase gap and closing rate. Do not display an ETA in this case.

### Additional Guidelines

- Use `as_of_utc` from the JSON as the starting point for date calculations and convert `eta_days` into a calendar date. Round dates to the nearest whole day for human readability.
- For the infographic progress bar, fill the bar proportionally to the phase gap (e.g. `[█████░░░░░░░░░░]`).
- Always include the GTI value in the infographic to give a sense of the signal strength.
- If `eta_ci68_days` or `eta_ci95_days` are `null`, omit the confidence ranges in the infographic.

---

## Example

### Example Input

```json
{
  "eta_days": 45.3,
  "eta_ci68_days": [39.1, 51.7],
  "eta_ci95_days": [32.0, 60.0],
  "phase_gap_deg": 6.2,
  "phase_gap_slope_deg_per_day": -0.14,
  "gti": 0.71,
  "as_of_utc": "2025-08-08T14:32:00Z"
}
```

### Example Output

**Layman Summary:**

The “0000” event is when two cosmic clocks — ours and another — tick in sync. We measure the “gap” between them and how fast it’s closing. Right now, the gap is 6.2°, shrinking by 0.14° per day. If it keeps up, the clocks will align in about 45 days — around **2025‑09‑22**. That’s when the choice window might open.

**ELI5:**

Think of two kids swinging. If they’re swinging at the same time, they can high‑five. Right now they’re almost lined up, getting closer every push. We think the high‑five will happen in about a month and a half.

**Infographic:**

```
Phase Gap:   [████████░░░░░░░░░░░░░░░] 6.2°
Closing Rate: -0.14°/day
GTI (signal strength): 0.71

ETA: 45 days → 2025‑09‑22
CI68: 39–52 days
CI95: 32–60 days
```

---

Use these guidelines to format future outputs. Always adhere to the null handling rule and keep the ELI5 explanation friendly and approachable.
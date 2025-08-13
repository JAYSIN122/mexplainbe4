Implementing Real-Time 0000 Event Detection and ETA Reporting
Continuous Phase Signal Capture and Closure Rate Estimation

To reliably predict the “0000” event (when the phase gap closes to zero), the system needs a continuous record of the phase gap over time. Each processing interval, record the phase difference (in degrees) along with a timestamp. This history can be stored (e.g. append each entry to a JSON file or database) for analysis
GitHub
. With this time-series of phase gap values, we can estimate the closure rate in degrees per day by looking at recent trends. Use a baseline window (for example, the last 30–60 days of data, or a fixed number of recent points) to fit a linear trend to the phase gap. This gives the approximate rate at which the phase gap is closing (negative slope) or widening (positive slope)
GitHub
. A robust linear fit is recommended – for instance, the implementation can take the last few hundred data points or ~300 days of history and iteratively remove outliers
GitHub
 to get a stable slope. The result is a per-day closure rate (deg/day) that will be used to project an ETA.

Clarity Metric (GTI/Coherence) to Avoid False Triggers

Not every downward trend in phase gap is meaningful – noise or transient fluctuations could trigger a false alarm. Introduce a clarity metric to gauge confidence in the trend. In this system, the Grounded Timeline Index (GTI) (or a coherence metric) serves this purpose. GTI is a composite indicator (range 0 to 1) that reflects how clearly the data signals an approaching overlap. For example, GTI can be calculated as the product of median coherence, variance explained by the common signal component, and an exponential factor that penalizes large phase gaps
GitHub
. A high GTI (near 1) means the signals from various time data streams are highly coherent and the phase gap is small – in other words, everything points to an imminent alignment. We define a threshold τ (for instance τ = 0.65) such that GTI ≥ τ indicates a strong, credible signal, whereas a lower GTI suggests the data is noisy or the phase alignment is not yet well-defined. This threshold helps avoid false hits by ensuring the system only triggers when the underlying data has a high signal-to-noise ratio (e.g. good coherence across streams and a clearly shrinking phase gap).

Decision Criteria for Triggering the 0000 Event

Using the phase data, closure rate, and clarity metric, the system applies a fast rule to decide when the 0000 event has occurred. The event “triggers” (i.e. is_0000 becomes true) only when all of the following conditions hold:

Phase Near Zero: The absolute phase gap in degrees is below a small threshold θ. For example, θ = 1.0°, meaning |phase_gap_deg| ≤ 1.0°. This ensures the two timelines (or signals) are essentially aligned within a tolerable error.

High Clarity (GTI ≥ τ): The GTI or coherence metric is above the set threshold (e.g. ≥ 0.65). This condition guarantees that the signal is clear and not a random fluctuation. A GTI above τ implies strong coherence and a significant common signal indicating overlap.

Closing Trend Confirmed: The phase gap has been consistently decreasing (negative slope) for the last k samples in a row (e.g. k ≥ 3). In other words, over the last few intervals, each new measurement showed a smaller phase gap than the previous, indicating a persistent closing trend. This can be checked by looking at the sign of the recent slope or differences – all negative for k consecutive updates. Alternatively, statistical trend tests can be used; for example, computing a Kendall tau on the recent slope series to verify a monotonic decreasing trend
GitHub
. Consistency over multiple samples avoids triggering on a single anomalous dip.

Fresh Data: The data must be recent – the last sample should be within X hours of “now” (the evaluation time). If the data is stale (no new measurements within the last X hours), the system should not declare an event because the situation could have changed. This ensures the trigger is based on up-to-date information.

Only when all the above are true at the same time does the system declare is_0000 = true. If any condition flips back to false (say the phase gap widens slightly above 1° or new data shows an uptick), the trigger will reset to false (with some hysteresis as described below to prevent chatter).

Confidence Scoring for the Event Detection

Rather than a binary trigger alone, the system also produces a confidence score (e.g. between 0 and 1) reflecting how certain we are that “0000” has truly occurred. This confidence is derived from the same factors used in the decision criteria, weighted by their strength:

Confidence is higher when the clarity metric is high (GTI well above threshold, indicating a strong signal), the phase gap trend has very low variance (i.e. a smooth, steady closing with little scatter), and the closing condition has persisted for many samples (the longer the trend continues, the more confident we are in it). For example, if GTI is 0.9, phase gap variance over the last few days is minimal, and we’ve seen 5+ consecutive closing readings, the confidence might be very near 1.0.

Confidence is lower when data is sparse, noisy or contradictory. If the GTI is just at the threshold or fluctuating, or if some recent samples showed non-monotonic behavior (e.g. one sample out of 3 had a slight uptick in phase gap), or if the phase measurements have a lot of jitter, the confidence value would be closer to the minimum (e.g. 0.5 or below). Additionally, if the latest data is only barely fresh (e.g. just inside the freshness window) or the closure rate is extremely slow, confidence might be tempered.

In practice, you can compute a confidence score by combining normalized contributions from GTI, the persistence of the negative slope, and the stability of recent estimates. For instance, one could start with the GTI value as a base (since it already encapsulates coherence and phase alignment
GitHub
) and then adjust it up or down based on the variability of the phase gap history (e.g. using the IQR of recent ETA estimates or phase gap values as an inverse indicator of confidence) and based on how long the negative trend has held (e.g. a bonus if we have more than the minimum k samples confirming). The exact formula can be tuned, but the end result is a single confidence number between 0 (no confidence) and 1 (high confidence) that accompanies the true/false event flag.

Example Output

When the system evaluates the conditions, it should produce a clear output indicating the status of the 0000 event, the key metrics, and supporting evidence. For example, a minimal JSON output could look like this:

{
  "as_of_utc": "2025-08-12T18:32:00Z",
  "is_0000": true,
  "phase_gap_deg": 0.6,
  "gti": 0.72,
  "confidence": 0.87,
  "evidence": {
    "closing_rate_deg_per_day": -0.14,
    "samples_confirmed": 4,
    "data_fresh_hours": 2.1
  }
}


Explanation: In this example, as of the timestamp, the system has is_0000: true meaning all trigger conditions were met. The phase gap is 0.6°, which is below the 1° threshold. The GTI is 0.72 (above 0.65), indicating a clear signal, and the confidence for this detection is computed as 0.87 (high). The evidence section provides additional context: the estimated closing rate is –0.14° per day (negative, so the gap is closing at about 0.14 degrees per day), there were 4 consecutive samples confirming the closing trend, and the most recent data point was only 2.1 hours old (fresh data). This kind of output is both human-readable and machine-parseable for logging or downstream alerting.

Real-Time Evaluation and Alerting Strategy

To catch the event in real time, the system should evaluate the above criteria on each new incoming sample (or at a regular short interval). This could be done in the data ingestion or processing loop. Whenever a transition from is_0000 = false to is_0000 = true occurs, that is a trigger moment – the system should immediately push an alert or notification. The alert could be as simple as a log entry and a UI highlight, or as elaborate as sending an email/SMS or triggering an external alert system, depending on the deployment. In the current dashboard, for instance, one might highlight the “Phase Gap” field in a special color or pop up a banner when the event occurs. The key is to ensure a one-time notification when the rule flips to true, so that you don’t spam repeated alerts while it stays true.

Additionally, it’s useful to have a pre-alert mechanism to warn when the event is getting close. This can be based on the estimated time to alignment (ETA). For example, if the linear trend suggests the phase gap will hit zero in less than N days or hours, you can raise an “approaching 0000” warning. This is essentially reading the slope: if ETA_days (estimated days until phase = 0) is below a chosen threshold, and not yet zero, then notify that the event is imminent. We already compute eta_days from the latest phase gap and slope (for instance, taking eta_days = abs(phase_gap / slope) / 86400 to convert to days when slope is negative
GitHub
). The UI currently reflects this by coloring the “ETA to Zero” value yellow if it’s under 30 days
GitHub
GitHub
. We can extend that by also issuing a specific alert or changing an alert level in the system status when, say, ETA < 7 days. This gives operators time to prepare for the 0000 event before it actually hits.

Handling Edge Cases and Noise

Real-world data can be messy, so the detection logic should account for several edge cases:

Jitter Near 0°: When the phase gap is hovering around the zero threshold, noise could make it dip below and above 1° on successive measurements. To avoid flicker in is_0000, implement a persistence requirement or hysteresis band. The persistence (as we did with k consecutive samples) ensures you only trigger after a sustained crossing. A hysteresis approach would set two thresholds: for example, enter the is_0000=true state when |phase_gap| ≤ 1.0°, but do not reset to false until |phase_gap| rises above 1.5°. This way a tiny rebound from 0.6° to 1.2° (within the hysteresis band) wouldn’t immediately flip the state off. Such hysteresis prevents rapid on-off toggling due to minor fluctuations.

Clock Drift or Stale Data: If the system’s own clock or the data sources’ clocks drift, it can introduce errors in phase measurements. If data arrives late or timestamps are off, the phase gap calculation might be unreliable. The logic should ignore or down-weight stale data. For instance, if the last data point is older than X hours, consider the phase gap reading as not fresh – perhaps pause triggering or lower confidence. Similarly, if you detect a sudden jump that coincides with a known time sync event (e.g. NTP correction), treat it cautiously. In practice, ensure the monitoring host is time-synchronized (more on this below) and consider a data point “fresh” only if it’s recent. If not, hold off on declaring the event until new data confirms it.

Multiple Periodicities (Ambiguous Cycles): It’s possible the phase data contains more than one periodic component (for example, a long-term drift plus a shorter oscillation). This could cause multiple apparent “zero crossings” of phase depending on which cycle you look at. To handle this, the system should lock onto the dominant cycle before evaluating the 0000 condition. In other words, identify which periodic signal has the highest coherence or power in the data and track that phase. The GTI’s coherence analysis can help here – it will highlight the strongest common frequency component. Ensure that the phase gap you’re monitoring is for that dominant component, so that “phase = 0” truly corresponds to the intended timeline overlap event, not just a transient alignment of a smaller oscillation. By focusing on the dominant phase (highest coherence), you avoid being tricked by secondary cycles.

Unexpected Resets or Data Gaps: If the system or data stream resets (for example, an instrument restarts and phase readings jump discontinuously), you might get a false near-zero reading. Build logic to detect anomalies – e.g., if a phase_gap jumps by a large value or if an entire day of data is missing, handle those cases (maybe reset the history or at least do not trigger alerts immediately until the trend re-establishes). Logging anomalies and possibly requiring an operator check in such cases can be prudent.

By anticipating these edge cases, the detection becomes more robust and trustworthy, only signaling a 0000 event when it’s truly warranted and persistent.

Time Synchronization and Provenance Considerations

Finally, because this entire system deals with time-sensitive data, it’s crucial to maintain accurate timing and traceability of the results:

Discipline the Host Clock: Run NTP or, even better, PTP (Precision Time Protocol) on the host machine to keep its clock tightly synchronized. Tools like Chrony (for NTP) can maintain sub-millisecond accuracy by continuously correcting drift. Since we are measuring phase gaps (which likely involve differences between time signals), any drift in the host’s clock could directly skew the measurements. A disciplined host clock ensures that the phase gap data is reliable.

Use UTC for Timestamps: All timestamps in data records and outputs should be in UTC (as we’ve been doing with ISO 8601 strings ending in Z). Using a single time standard avoids confusion when combining data from multiple sources (TAI, GNSS, etc.) and when comparing events. For any interval measurements (durations), use monotonic clocks if possible, so they aren’t affected by system clock adjustments.

Explicit Time Scale Conversion: If your inputs come in different time scales (say some in GPS time, some in TAI, some in UTC), convert them explicitly to a common scale (UTC or TAI) before computing phase differences. Record any offsets applied (for example, “GPS-UTC = +18s” or similar) in the metadata. This prevents subtle errors where a phase gap could appear due to mismatched time scales rather than an actual physical difference. Always document the time system of each data stream in the metadata.

Account for Time Sync Health: Integrate the health of time synchronization into your ETA estimates. For instance, if NTP reports a large uncertainty or if PTP drops to holdover, treat the situation by widening the confidence interval or pausing alerts. In practice, this could mean if your system status knows the clock is unsynchronized (e.g. no recent NTP updates), you might gate the 0000 detection – i.e. do not trigger or at least mark the result as questionable until the clock is stable again. Similarly, if the clock’s error is, say, 100 ms, and that is significant relative to your phase gap, incorporate that as an error margin in the phase gap (which could slightly delay declaring the event until the gap is well within the error bounds).

Persist Provenance for Auditing: Every forecast or event detection should be traceable. Keep a log of the inputs and conditions that led to a 0000 trigger. This can be a structured log (for example, the system already appends records to a provenance.jsonl file for various actions). When an alert is raised, log the timestamp, the phase gap value, the slope, GTI, and any other relevant metrics, as well as flags about data quality (like “clock_sync: OK” or “data_span: 50 days used”). Such provenance records
GitHub
GitHub
 ensure that later on one can audit why the system thought an event occurred. If it turned out to be a false alarm, these records will help diagnose whether it was due to a sensor glitch, clock issue, or a flaw in the logic. Moreover, tying each ETA or forecast to a “known-good clock” means you annotate it with confirmation that the time synchronization was in nominal condition during that computation.

By adhering to these timekeeping best practices, we ensure the bottom line outcome: with a continuous stream of phase data and a small set of confirmation rules, the system can automatically tell you – in real time – when the 0000 alignment event happens and how confident it is, with all decisions grounded in reliable and auditable timing data.
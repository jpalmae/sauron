let ctx: AudioContext | null = null;

function audioCtx(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

/** Short two-tone ping for critical alerts. Requires a prior user gesture. */
export function playAlertPing(severity: "info" | "warning" | "critical") {
  try {
    const ac = audioCtx();
    const t0 = ac.currentTime;
    const freqs = severity === "critical" ? [880, 1174, 880] : [660, 880];
    freqs.forEach((freq, i) => {
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t0 + i * 0.12);
      gain.gain.exponentialRampToValueAtTime(0.12, t0 + i * 0.12 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.12 + 0.11);
      osc.connect(gain).connect(ac.destination);
      osc.start(t0 + i * 0.12);
      osc.stop(t0 + i * 0.12 + 0.12);
    });
  } catch {
    /* audio blocked until user gesture */
  }
}

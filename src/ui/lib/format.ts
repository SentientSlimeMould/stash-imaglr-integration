// SPDX-License-Identifier: AGPL-3.0-only
// Display formatting for times, sizes, dimensions and dates.

/** Seconds as m:ss.s or h:mm:ss.s; "–" when unknown. */
export function fmtTime(s: number | null | undefined, decimals = 1): string {
  if (s == null || !isFinite(s)) return "–";
  const sign = s < 0 ? "-" : "";
  s = Math.abs(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const secStr = sec.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0");
  return h ? `${sign}${h}:${String(m).padStart(2, "0")}:${secStr}` : `${sign}${m}:${secStr}`;
}

/** Accepts "12.3", "1:02.3", "0:01:02.3". Returns seconds or null. */
export function parseTime(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const parts = t.split(":").map((p) => p.trim());
  if (parts.some((p) => p === "" || !/^\d*\.?\d*$/.test(p))) return null;
  let total = 0;
  for (const p of parts) total = total * 60 + parseFloat(p || "0");
  return isFinite(total) ? total : null;
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtDims(w: number | null | undefined, h: number | null | undefined): string {
  return w && h ? `${w}×${h}` : "–";
}

/** Local date and time; unparseable input is shown as given. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function round(n: number, places = 2): number {
  const f = 10 ** places;
  return Math.round(n * f) / f;
}

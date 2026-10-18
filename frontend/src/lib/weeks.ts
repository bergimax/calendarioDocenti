import type { Week } from "@/lib/types";

/** "2026-10-19" -> "19/10/26" */
const shortDate = (iso: string) => {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${(y ?? "").slice(2)}`;
};

/** "Sett. 6 (19/10/26 → 23/10/26)" */
export const weekLabel = (w: Week) =>
  `Sett. ${w.week_num} (${shortDate(w.start)} → ${shortDate(w.end)})`;

/** Etichetta della settimana che inizia a `start`, se presente nell'elenco. */
export const weekLabelFor = (weeks: Week[] | undefined, start: string) => {
  const w = weeks?.find((x) => x.start === start);
  return w ? weekLabel(w) : start;
};

const isoLocal = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * The week to open by default: the one after the week in progress. Saturday
 * and Sunday already count as the next week (on Sunday 18/10 the week in
 * progress is the one starting tomorrow, 19/10, so this returns 26/10; on
 * Wednesday 21/10 it also returns 26/10). Falls back to the last week of the
 * year, or "" with no weeks.
 */
export function defaultWeek(weeks: Week[] | undefined, today: Date = new Date()): string {
  if (!weeks?.length) return "";
  const dow = today.getDay(); // 0 = Sunday .. 6 = Saturday
  const toMonday = dow === 0 ? 1 : dow === 6 ? 2 : 1 - dow;
  const target = isoLocal(
    new Date(today.getFullYear(), today.getMonth(), today.getDate() + toMonday + 7),
  );
  const found = weeks.find((w) => w.start >= target);
  return (found ?? weeks[weeks.length - 1])!.start;
}

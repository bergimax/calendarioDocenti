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

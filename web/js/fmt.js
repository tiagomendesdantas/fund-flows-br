// Formatting. Times arrive in UTC ("YYYY-MM-DDTHH:MM") and days as ISO dates; everything is shown
// in Brasília time. Money arrives in reais and is shown in billions or trillions.
export const TZ = "America/Sao_Paulo";
export const TZ_LABEL = "Brasília (UTC−3)";
// Brazil has had no daylight saving time since 2019; local midnight is 03:00 UTC.
export const BRT_OFFSET_MS = 3 * 3600e3;

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
export const toDate = (s) => new Date(s.length === 16 ? `${s}:00Z` : s.endsWith("Z") ? s : `${s}Z`);
const make = (opts) => new Intl.DateTimeFormat("en-GB", { timeZone: TZ, ...opts });
const F = {
  time: make({ hour: "2-digit", minute: "2-digit" }),
  dayTime: make({ weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
  day: make({ weekday: "short", day: "numeric", month: "short" }),
  date: make({ day: "numeric", month: "short", year: "numeric" }),
  month: make({ month: "short", year: "numeric" }),
};
const d = (x) => (x instanceof Date ? x : toDate(x));
export const fmtTime = (x) => F.time.format(d(x));
export const fmtDayTime = (x) => F.dayTime.format(d(x)).replace(",", "");
export const fmtDay = (x) => F.day.format(d(x)).replace(",", "");
export const fmtDate = (x) => F.date.format(d(x));
export const fmtMonth = (x) => F.month.format(d(x));
// An ISO date (a local day) placed at local midday, so charts and formatters keep its day.
export const dayAt = (iso) => `${iso}T15:00`;
export const dateOnly = (iso) => F.date.format(new Date(`${iso}T15:00:00Z`));
export const dayOnly = (iso) => F.day.format(new Date(`${iso}T15:00:00Z`)).replace(",", "");
export const monthOnly = (ym) => F.month.format(new Date(`${ym}-15T15:00:00Z`));

const num = (v, digits) => v.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const bn = (v, digits = 1) => (v == null || Number.isNaN(v) ? "–" : num(v / 1e9, digits));
export const sbn = (v, digits = 1) => (v == null || Number.isNaN(v) ? "–" : `${v >= 0 ? "+" : "−"}${num(Math.abs(v) / 1e9, digits)}`);
export const tn = (v, digits = 2) => (v == null || Number.isNaN(v) ? "–" : num(v / 1e12, digits));
export const millions = (v, digits = 1) => (v == null ? "–" : num(v / 1e6, digits));
export const pct = (x, digits = 1) => (x == null || Number.isNaN(x) ? "–" : `${(x * 100).toFixed(digits)}%`);
export const spct = (x, digits = 2) => (x == null || Number.isNaN(x) ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(digits)}%`);

// Segments (flows.totals): the headline leaves funds of funds out, so each flow counts once.
export const SEGMENTS = [
  ["direct", "All funds, without funds of funds"],
  ["direct:Renda Fixa", "Renda Fixa"],
  ["direct:Multimercado", "Multimercado"],
  ["direct:Ações", "Ações"],
  ["direct:Cambial", "Cambial"],
  ["direct:FMP-FGTS", "FMP-FGTS"],
  ["direct:Unclassified", "Unclassified"],
  ["all", "All funds, with funds of funds (counted twice)"],
];
export const segmentName = (s) => (SEGMENTS.find((x) => x[0] === s) || [s, s])[1];
export const CATEGORY_SEGMENTS = SEGMENTS.filter(([s]) => s.startsWith("direct:"));

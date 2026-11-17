// Russian formatting: °C with a decimal comma, dates and times in the site's time zone.
import type { EquipmentKind, PointStatus } from "./api/types";

export function formatTemperature(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 2 })} °C`;
}

export function formatDateTime(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatTime(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru-RU", { timeZone, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function formatDay(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day ?? ""}.${month ?? ""}.${year ?? ""}`;
}

export function formatAge(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "нет данных";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "только что";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} ч назад`;
  return `${Math.round(hours / 24)} дн назад`;
}

export function formatDuration(seconds: number): string {
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600} ч`;
  if (seconds % 60 === 0) return `${seconds / 60} мин`;
  return `${seconds} с`;
}

export const STATUS_LABELS: Record<PointStatus, string> = {
  normal: "Норма",
  pending: "Отклонение, ожидание подтверждения",
  alarm: "Температурная тревога",
  sensor_error: "Ошибка датчика",
  offline: "Нет связи",
  no_data: "Нет данных после установки",
};

export const EQUIPMENT_KINDS: Record<EquipmentKind, string> = {
  refrigerator: "Холодильник",
  freezer: "Морозильник",
  combined: "Холодильник с морозильной камерой",
  cold_room: "Холодильная камера",
  display: "Витрина",
  other: "Другое",
};

/** Local date (YYYY-MM-DD) `daysAgo` days back in the browser's zone, for default journal periods. */
export function localDate(daysAgo = 0): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** First and last local date of a `YYYY-MM` month; the current month ends today (no future days). */
export function monthRange(month: string): { first: string; last: string } {
  const [year = 1970, monthNumber = 1] = month.split("-").map(Number);
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const end = `${month}-${String(daysInMonth).padStart(2, "0")}`;
  const today = localDate(0);
  return { first: `${month}-01`, last: end < today ? end : today };
}

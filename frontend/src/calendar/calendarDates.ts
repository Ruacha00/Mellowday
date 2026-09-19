import { DateTime } from "luxon";
export function localInput(value: string, zone?: string) {
  return DateTime.fromISO(value, { zone: zone || "local" }).toFormat(
    "yyyy-MM-dd'T'HH:mm",
  );
}
export function instant(value: string, zone: string) {
  const d = DateTime.fromISO(value, { zone });
  if (!d.isValid || d.toFormat("yyyy-MM-dd'T'HH:mm") !== value)
    throw new Error("此时区下的时间无效，请检查时区或夏令时切换。");
  return d.toISO()!;
}

export function followingDate(value: string) {
  return DateTime.fromISO(value).plus({ days: 1 }).toFormat("yyyy-MM-dd");
}

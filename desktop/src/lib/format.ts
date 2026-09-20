export function finiteNumber(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function fixedNumber(value: unknown, digits: number): string {
  return finiteNumber(value).toFixed(digits);
}

export function errorMessage(value: unknown, fallback: string): string {
  if (value instanceof Error && value.message.trim()) return value.message;
  if (typeof value === "string" && value.trim()) return value;
  return fallback;
}

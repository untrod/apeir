/** Small presentation icons; inherit the same text and status palette. */
const paths = {
  add: "M8 3v10M3 8h10",
  edit: "m10 3 3 3M3 10l7-7 3 3-7 7H3v-3Z",
  check: "m3 8 3 3 7-7",
  refresh: "M13 7a5 5 0 1 0-1 4M13 3v4H9",
  settings: "M8 2v2M8 12v2M2 8h2M12 8h2M4 4l1 1M11 11l1 1M4 12l1-1M11 5l1-1M11 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  copy: "M6 6h7v7H6V6ZM10 4V2H2v8h2",
  close: "m4 4 8 8M12 4l-8 8",
  arrow: "M4 12 12 4M5 4h7v7",
} as const;
export function StudioIcon({ name }: { name: keyof typeof paths }) {
  return <svg className="studio-icon" aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>;
}

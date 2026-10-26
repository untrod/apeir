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
  chat: "M3 3h10v7H7l-4 3V3Z",
  files: "M2 4h5l2 2h5v7H2V4Z",
  workflow: "M2 2h4v4H2V2ZM10 10h4v4h-4v-4ZM6 4h6v6",
  tasks: "M6 4h7M6 8h7M6 12h7M2 4h1M2 8h1M2 12h1",
  dashboard: "M2 2h5v5H2V2ZM10 2h4v5h-4V2ZM2 10h5v4H2v-4ZM10 10h4v4h-4v-4Z",
  model: "m8 2 6 6-6 6-6-6 6-6ZM5 8h6M8 5v6",
  node: "M2 2h12v4H2V2ZM2 10h12v4H2v-4ZM4 4h1M4 12h1M8 6v4",
  evidence: "M3 2h7l3 3v9H3V2ZM10 2v4h3M5 10l2 2 4-4",
  history: "M2 7a6 6 0 1 1 1 5M2 3v4h4M8 4v4l3 2",
  more: "M3 7v2M8 7v2M13 7v2",
  maximize: "M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4",
  restore: "M5 2h9v9M2 5h9v9H2V5Z",
  split: "M2 2h12v12H2V2ZM8 2v12",
} as const;
export function StudioIcon({ name }: { name: keyof typeof paths }) {
  return <svg className="studio-icon" aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>;
}

import type { CSSProperties } from "react";
const paths: Record<string, string> = {
  run: "m9 5 10 7-10 7Z",
  stop: "M6 6h12v12H6Z",
  resume: "m10 6 8 6-8 6ZM5 6v12",
  check: "m5 12 5 5L20 6",
  cross: "m6 6 12 12M18 6 6 18",
  question: "M9 8a3 3 0 1 1 5 3c-2 1-2 2-2 3m0 3v1",
  config: "M5 6h14M5 12h14M5 18h14M9 3v6m6 0v6m-7 0v6",
  members:
    "M6 16a4 4 0 0 1 8 0m-1-5a3 3 0 1 0-6 0m9-2a2 2 0 1 1 0 4m0 2a3 3 0 0 1 4 3",
  plan: "M5 20V4h14v16ZM8 8h8M8 12h8M8 16h4",
  ingest: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  extract: "M6 3h9l4 4v14H6Zm8 0v5h5M9 12h7M9 16h4",
  aggregate: "M4 18v-5h4v5m2 0V8h4v10m2 0V4h4v14",
  gate: "m4 5 8 8v7m0-7 8-8M4 5h16",
  publish: "M4 5h16v14H4Zm4 5 3 3 5-6",
  suppressed: "M5 5h14v14H5ZM5 5l14 14",
  model: "m12 3 9 5v8l-9 5-9-5V8Zm0 0v18M3 8l9 5 9-5",
  cache:
    "M4 6c0-4 16-4 16 0s-16 4-16 0m0 0v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0",
  limiter: "M4 17a9 9 0 1 1 16 0m-8-4 5-5m-5 5v3",
  validate: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Zm-4 9 3 3 5-6",
  parse: "m8 6-5 6 5 6m8-12 5 6-5 6m-3-15-2 18",
  review: "M4 4h16v12H9l-5 5Zm4 4h8m-8 4h5",
  lightning: "m13 2-9 12h7l-1 8 10-13h-8Z",
  plus: "M12 4v16M4 12h16",
  minus: "M4 12h16",
  fit: "M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6",
  lens: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 0v18",
  privacy:
    "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm7 0a3 3 0 1 0 6 0 3 3 0 0 0-6 0",
  theme: "M12 3v18a9 9 0 0 0 0-18Z",
  help: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm-3 6a3 3 0 1 1 5 2l-2 2m0 3v1",
  table: "M3 4h18v16H3Zm0 5h18M9 4v16M3 14h18",
  json: "M8 3H6v6l-3 3 3 3v6h2m8-18h2v6l3 3-3 3v6h-2",
  schema: "M4 5h16M4 12h8M4 19h12",
  diff: "M8 4v16m-4-8h8m4-8v16m-3-8h6",
  evidence: "M3 4h13v16H3Zm13 9 5 5m-1-9a5 5 0 1 0-10 0 5 5 0 0 0 10 0",
  copy: "M8 8h12v13H8Zm-4 8V3h12",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  previous: "m15 5-7 7 7 7",
  next: "m9 5 7 7-7 7",
  close: "m6 6 12 12M18 6 6 18",
  export: "M12 16V3m-5 5 5-5 5 5M4 14v7h16v-7",
  import: "M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4",
  chart: "M4 20V5m0 15h17M7 16l4-7 5 3 4-8",
  flask: "M9 3h6m-5 0v7L4 20h16l-6-10V3M7 15h10",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 3v6l4 2",
  calendar: "M4 5h16v16H4ZM4 10h16M8 3v4m8-4v4",
  search: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6",
};
export function Icon({
  name,
  size = 20,
  style,
}: {
  name: string;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name] ?? paths.extract} />
    </svg>
  );
}

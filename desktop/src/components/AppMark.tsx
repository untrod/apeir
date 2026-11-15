import source from "../../src-tauri/app-icon.svg?raw";
import "./Startup.css";

function shape(id: string): Record<string, string> {
  const tag = source.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0];
  if (!tag) throw new Error(`Missing application icon shape: ${id}`);
  return Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(match => [match[1], match[2]]));
}
const paper = shape("paper-tile"), left = shape("frame-left"), right = shape("frame-right");

/** Native icons, favicon and animated fragments share the same vector source. */
export function AppMark({ size = 24, className = "", opening = false, part }: {
  size?: number;
  className?: string;
  opening?: boolean;
  part?: "left" | "right";
}) {
  return <svg width={size} height={size} viewBox="0 0 1024 1024" aria-hidden="true" focusable="false"
    className={`app-mark ${opening ? "app-mark--opening" : ""} ${className}`}>
    {!part && <rect x={paper.x} y={paper.y} width={paper.width} height={paper.height} rx={paper.rx} fill={paper.fill} stroke={paper.stroke} strokeWidth={paper["stroke-width"]} />}
    {(!part || part === "left") && <g className="app-mark-left"><path d={left.d} fill={left.fill} /></g>}
    {(!part || part === "right") && <g className="app-mark-right"><path d={right.d} fill={right.fill} /></g>}
  </svg>;
}

import { useEffect, useState, type ReactNode } from "react";
import { AppMark } from "./AppMark";

/** Presentation only: children mount once and remain interactive during entry. */
export function StudioEntrance({ children, animate, onEntered }: {
  children: ReactNode;
  animate: boolean;
  onEntered: () => void;
}) {
  const [opening] = useState(animate);
  useEffect(onEntered, [onEntered]);
  return <div className="studio-entrance">
    {children}
    {opening && <div className="studio-entrance-mask" aria-hidden="true">
      <AppMark size={160} part="left" className="studio-entrance-left" />
      <AppMark size={160} part="right" className="studio-entrance-right" />
    </div>}
  </div>;
}

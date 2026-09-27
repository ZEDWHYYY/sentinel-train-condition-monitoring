"use client";

import { useEffect, useRef, useState } from "react";

/** Width of a container element, kept up to date with ResizeObserver, so SVG charts can size their
 *  coordinate system to the space they actually have (readable text at 400 px, no horizontal scroll). */
export function useContainerWidth<T extends HTMLElement>(fallback = 900): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw && Math.abs(cw - w) > 1) setW(Math.max(280, Math.round(cw)));
    });
    ro.observe(el);
    setW(Math.max(280, Math.round(el.getBoundingClientRect().width) || fallback));
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [ref, w];
}

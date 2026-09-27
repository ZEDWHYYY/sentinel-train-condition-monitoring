"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
export default function Header() {
  const path = usePathname();
  return (
    <header className="app-header">
      <div className="header-inner">
        <Link href="/analyze" className="brand">
          SENTINEL<span>Train diagnostics</span>
        </Link>
        <nav aria-label="Primary">
          {[
            ["/analyze", "New analysis"],
            ["/history", "Past analyses"],
            ["/learn", "Learn"],
            ["/method", "Methods"],
          ].map(([href, label]) => (
            <Link
              key={href}
              href={href}
              aria-current={path === href ? "page" : undefined}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

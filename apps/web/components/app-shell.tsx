"use client";

import { Activity, Clapperboard, Sparkles, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { href: "/styles", label: "Styles", icon: Sparkles },
  { href: "/projects", label: "Projects", icon: Clapperboard },
  { href: "/health", label: "System", icon: Activity },
];

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-dvh">
      {/* Desktop: sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-card px-3 py-5 md:flex">
        <Link href="/styles" className="mb-6 px-2 text-lg font-semibold tracking-tight">
          Style<span className="text-accent">Cut</span>
        </Link>
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-lg px-2 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                isActive(pathname, href) && "bg-muted font-medium text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile: top bar */}
        <header className="border-b border-border bg-card px-4 py-3 md:hidden">
          <Link href="/styles" className="text-lg font-semibold tracking-tight">
            Style<span className="text-accent">Cut</span>
          </Link>
        </header>

        <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-24 pt-6 md:px-8 md:pb-10">
          {children}
        </main>
      </div>

      {/* Mobile: bottom tab bar, sized for one-handed use on set */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-3 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={isActive(pathname, href) ? "page" : undefined}
            className={cn(
              "flex min-h-14 flex-col items-center justify-center gap-1 text-xs text-muted-foreground",
              isActive(pathname, href) && "font-medium text-foreground",
            )}
          >
            <Icon className="size-5" aria-hidden />
            {label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

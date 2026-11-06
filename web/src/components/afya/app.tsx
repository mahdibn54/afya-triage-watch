"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useState } from "react";

import type { Me } from "@/api/contract";
import { Wordmark } from "@/components/afya/logo";
import { SignIn } from "@/components/afya/sign-in";
import { UserSwitcher } from "@/components/afya/user-switcher";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/queries";
import { cn } from "@/lib/utils";

export type View = "board" | "audit";

export function App() {
  const me = useMe();
  if (me.isPending) return <Splash />;
  if (me.error instanceof ApiError && me.error.status === 401) return <SignIn />;
  if (me.isError) return <Splash failed onRetry={() => me.refetch()} />;
  return <Shell me={me.data} />;
}

function Splash({ failed, onRetry }: { failed?: boolean; onRetry?: () => void }) {
  return (
    <main className="paper-grain flex min-h-dvh flex-1 flex-col items-center justify-center gap-4">
      <Wordmark className={cn(!failed && "animate-pulse")} />
      {failed && (
        <div className="text-center text-sm text-muted-foreground">
          <p>Can&apos;t reach the server.</p>
          <button className="mt-2 font-medium text-foreground underline underline-offset-4" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
    </main>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  return (
    <button
      type="button"
      aria-label={dark ? "Day theme" : "Night theme"}
      title={dark ? "Day theme" : "Night theme (for night shifts)"}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="grid size-11 place-items-center rounded-xl border bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <Sun className="hidden size-[18px] dark:block" />
      <Moon className="size-[18px] dark:hidden" />
    </button>
  );
}

export function Shell({ me }: { me: Me }) {
  const [view, setView] = useState<View>("board");
  return (
    <div className="flex min-h-dvh flex-1 flex-col">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-4 px-4 sm:px-6">
          <Wordmark />
          <nav className="ml-2 hidden items-center gap-1 rounded-xl bg-muted p-1 md:flex" aria-label="Main">
            {(
              [
                ["board", "Waiting room"],
                ["audit", "Audit log"],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                aria-current={view === v ? "page" : undefined}
                className={cn(
                  "h-9 rounded-lg px-3.5 text-sm font-medium text-muted-foreground transition",
                  view === v && "bg-card text-foreground shadow-sm",
                )}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <UserSwitcher me={me} />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6">
        <p className="text-muted-foreground">Signed in as {me.name}.</p>
      </main>
    </div>
  );
}

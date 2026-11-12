"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import type { Me, QueuePatient } from "@/api/contract";
import { AuditView } from "@/components/afya/audit-view";
import { DemoDirector } from "@/components/afya/demo-director";
import { preloadDictation } from "@/components/afya/dictate-button";
import { Board } from "@/components/afya/board";
import { Wordmark } from "@/components/afya/logo";
import { SignIn } from "@/components/afya/sign-in";
import { UserSwitcher } from "@/components/afya/user-switcher";
import { VisitPanel } from "@/components/afya/visit-panel";
import { VitalsDialog } from "@/components/afya/vitals-dialog";
import { WallBoard } from "@/components/afya/wall-board";
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
      className="hidden size-11 place-items-center rounded-xl border bg-card text-muted-foreground sm:grid hover:bg-muted hover:text-foreground"
    >
      <Sun className="hidden size-[18px] dark:block" />
      <Moon className="size-[18px] dark:hidden" />
    </button>
  );
}

export function Shell({ me }: { me: Me }) {
  const [view, setView] = useState<View>("board");
  const [openVisit, setOpenVisit] = useState<string | null>(null);
  const [recordFor, setRecordFor] = useState<QueuePatient | null>(null);
  const [wall, setWall] = useState(false);
  useEffect(() => preloadDictation(), []); // E7-16: fetch the speech model in the background after sign-in
  if (wall) return <WallBoard onExit={() => setWall(false)} />;
  return (
    <div className="flex min-h-dvh flex-1 flex-col">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-4 px-4 sm:px-6">
          <Wordmark className="whitespace-nowrap [&>span:last-child]:hidden lg:[&>span:last-child]:inline" />
          <nav className="ml-1 flex items-center gap-1 rounded-xl bg-muted p-1 sm:ml-2" aria-label="Main">
            {(
              [
                ["board", "Waiting room", "Board"],
                ["audit", "Audit log", "Audit"],
              ] as const
            ).map(([v, label, short]) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                aria-current={view === v ? "page" : undefined}
                className={cn(
                  "h-9 rounded-lg px-2.5 text-sm whitespace-nowrap sm:px-3.5 font-medium text-muted-foreground transition",
                  view === v && "bg-card text-foreground shadow-sm",
                )}
              >
                <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden">{short}</span>
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            {view === "board" && <button type="button" onClick={() => setWall(true)} className="h-11 whitespace-nowrap rounded-xl border bg-card px-3 text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2">Wall mode</button>}
            <ThemeToggle />
            <UserSwitcher me={me} />
          </div>
        </div>
      </header>
      <main className={cn("mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6", me.demo && me.role !== "manager" && "pb-20")}>
        {view === "board" && <Board me={me} openVisit={openVisit} onOpen={setOpenVisit} onRecord={setRecordFor} />}
        {view === "audit" && <AuditView />}
      </main>
      <DemoDirector
        me={me}
        onOpen={(v) => {
          setView("board");
          setOpenVisit(v);
        }}
      />
      <VisitPanel me={me} visitId={openVisit} onClose={() => setOpenVisit(null)} onRecord={setRecordFor} />
      <VitalsDialog me={me} patient={recordFor} onClose={() => setRecordFor(null)} />
    </div>
  );
}

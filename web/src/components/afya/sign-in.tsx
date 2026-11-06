"use client";

import { ArrowRight, Eye, Loader2, ShieldCheck, Stethoscope, UserRound } from "lucide-react";
import { useState } from "react";

import type { Role, User } from "@/api/contract";
import { DemoBadge } from "@/components/afya/demo-badge";
import { Wordmark } from "@/components/afya/logo";
import { ApiError } from "@/lib/api";
import { useDemoUsers, useLoginAs } from "@/lib/queries";
import { cn } from "@/lib/utils";

export const ROLE: Record<Role, { title: string; can: string; icon: React.ComponentType<{ className?: string }> }> = {
  nurse: { title: "Triage nurse", can: "Record vitals, review and confirm second looks", icon: UserRound },
  clinician: { title: "Clinician on duty", can: "Review and confirm second looks, receive reminders", icon: Stethoscope },
  manager: { title: "Manager", can: "Read only: board, agent trace and audit log", icon: Eye },
};

/** First screen. DEMO_MODE only: there is no real authentication (a known, stated gap). */
export function SignIn() {
  const users = useDemoUsers();
  const login = useLoginAs();
  const [picked, setPicked] = useState<string | null>(null);

  const notDemo = users.error instanceof ApiError && users.error.status === 404;

  return (
    <main className="paper-grain relative flex min-h-dvh flex-1 flex-col">
      <header className="flex items-center justify-between px-6 py-5 sm:px-10">
        <Wordmark />
        <DemoBadge />
      </header>

      <div className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-12 px-6 pb-16 sm:px-10 lg:grid-cols-[1.1fr_1fr]">
        <section className="animate-rise">
          <p className="mb-5 inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs font-medium text-muted-foreground shadow-xs">
            <span className="size-1.5 rounded-full bg-agent animate-pulse-ring" />
            Decision support for trained triage staff
          </p>
          <h1 className="font-display text-5xl leading-[1.02] tracking-tight text-balance sm:text-6xl">
            Every waiting patient, <em className="text-agent">watched.</em>
            <br />
            Every change, confirmed by a nurse.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-pretty">
            Afya re-scores the waiting room with the South African Triage Scale and flags patients for a second look,
            citing the exact readings. It proposes; a nurse or clinician confirms. Nothing moves until they do.
          </p>
          <ul className="mt-8 grid max-w-xl gap-3 text-sm sm:grid-cols-3">
            {[
              ["Cites the readings", "Every flag links to its records"],
              ["Proposes only", "A person confirms each change"],
              ["Fully logged", "Every step is in the audit log"],
            ].map(([t, d]) => (
              <li key={t} className="rounded-xl border bg-card/70 p-3 backdrop-blur">
                <p className="font-semibold">{t}</p>
                <p className="mt-0.5 text-muted-foreground">{d}</p>
              </li>
            ))}
          </ul>
        </section>

        <section
          aria-labelledby="signin-title"
          className="animate-rise rounded-3xl border bg-card p-6 shadow-[0_1px_0_oklch(0_0_0/0.03),0_24px_60px_-28px_oklch(0.3_0.04_262/0.35)] sm:p-8"
          style={{ animationDelay: "80ms" }}
        >
          <div className="flex items-center justify-between">
            <h2 id="signin-title" className="text-lg font-semibold">
              Sign in as…
            </h2>
            <DemoBadge compact />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Pick a person to try the demo. No password in demo mode.</p>

          <div className="mt-6 grid gap-3">
            {users.isPending &&
              [0, 1, 2].map((i) => <div key={i} className="h-[76px] animate-pulse rounded-2xl bg-muted" />)}
            {notDemo && (
              <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
                Demo sign-in is off on this server (DEMO_MODE=0).
              </p>
            )}
            {users.isError && !notDemo && (
              <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
                Can&apos;t reach the server. Retrying…
              </p>
            )}
            {users.data?.map((u: User) => {
              const r = ROLE[u.role];
              const Icon = r.icon;
              const busy = login.isPending && picked === u.id;
              return (
                <button
                  key={u.id}
                  type="button"
                  data-testid={`login-${u.id}`}
                  disabled={login.isPending}
                  onClick={() => {
                    setPicked(u.id);
                    login.mutate(u.id);
                  }}
                  className={cn(
                    "group flex min-h-[76px] items-center gap-4 rounded-2xl border bg-background p-4 text-left transition",
                    "hover:border-foreground/25 hover:bg-card hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/40 focus-visible:outline-none",
                    "disabled:opacity-60",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-11 shrink-0 place-items-center rounded-xl",
                      u.role === "manager" ? "bg-muted text-muted-foreground" : "bg-primary text-primary-foreground",
                    )}
                  >
                    <Icon className="size-5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="font-semibold">{u.name}</span>
                      <span className="text-xs text-muted-foreground">{r.title}</span>
                    </span>
                    <span className="mt-0.5 block text-sm text-muted-foreground">{r.can}</span>
                  </span>
                  {busy ? (
                    <Loader2 className="size-5 animate-spin text-muted-foreground" />
                  ) : (
                    <ArrowRight className="size-5 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-foreground" />
                  )}
                </button>
              );
            })}
          </div>
          {login.isError && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {login.error.message}
            </p>
          )}

          <p className="mt-6 flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" />
            Research prototype on synthetic data. Not clinically validated; not assessed or cleared as a medical device.
          </p>
        </section>
      </div>
    </main>
  );
}

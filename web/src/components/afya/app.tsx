"use client";

import { useQuery } from "@tanstack/react-query";

import { Wordmark } from "@/components/afya/logo";
import { api } from "@/lib/api";

export function App() {
  const health = useQuery({ queryKey: ["healthz"], queryFn: () => api<{ status: string }>("/healthz") });
  return (
    <main className="paper-grain flex flex-1 flex-col items-center justify-center gap-4 p-8">
      <Wordmark />
      <p className="text-sm text-muted-foreground">
        API: <span data-testid="health">{health.isPending ? "checking…" : health.isError ? "unreachable" : health.data.status}</span>
      </p>
    </main>
  );
}

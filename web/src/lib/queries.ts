"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  ApproveRequest,
  ApproveResponse,
  AuditRow,
  Gate,
  Me,
  Proposal,
  Queue,
  Timeline,
  TraceStep,
  User,
  VitalsRequest,
  VitalsResponse,
} from "@/api/contract";
import { api, ApiError } from "@/lib/api";
import { learnServerTime } from "@/lib/time";

/** The board polls every 3 s (web/README.md). */
export const POLL_MS = 3000;

export const keys = {
  me: ["me"] as const,
  users: ["demo-users"] as const,
  queue: ["queue"] as const,
  proposals: (status: string) => ["proposals", status] as const,
  timeline: (visit: string) => ["timeline", visit] as const,
  trace: (run: string) => ["trace", run] as const,
  gates: (id: string) => ["gates", id] as const,
  audit: (q: string) => ["audit", q] as const,
};

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api<Me>("/me"),
    retry: (n, e) => !(e instanceof ApiError && e.status === 401) && n < 2,
    staleTime: 60_000,
  });
}

export function useDemoUsers(enabled = true) {
  return useQuery({ queryKey: keys.users, queryFn: () => api<User[]>("/demo/users"), enabled, staleTime: Infinity, retry: 1 });
}

/** Lookup "nurse-a" → "Nurse A." for audit and gate rows. */
export function useUserName() {
  const { data } = useDemoUsers();
  return (id: string | null | undefined) => {
    if (!id) return "";
    if (id === "agent") return "Watch agent";
    if (id === "system") return "System";
    return data?.find((u) => u.id === id)?.name ?? id;
  };
}

export function useLoginAs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (user_id: string) => api<User>("/login-as", { method: "POST", body: { user_id } }),
    onSuccess: async () => {
      // Everything a user sees depends on who they are: reset (and refetch) all but the user list.
      await qc.resetQueries({ predicate: (q) => q.queryKey[0] !== "demo-users" });
    },
  });
}

export function useQueue(enabled = true) {
  return useQuery({
    queryKey: keys.queue,
    queryFn: async () => {
      const q = await api<Queue>("/queue");
      learnServerTime(q.as_of, Date.now());
      return q;
    },
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
    enabled,
  });
}

export function useProposals(status: "pending" | "superseded" | "all" = "pending", enabled = true) {
  return useQuery({
    queryKey: keys.proposals(status),
    queryFn: () => api<Proposal[]>(`/proposals?status=${status}`),
    refetchInterval: POLL_MS,
    enabled,
  });
}

export function useTimeline(visitId: string | null) {
  return useQuery({
    queryKey: keys.timeline(visitId ?? ""),
    queryFn: () => api<Timeline>(`/visits/${encodeURIComponent(visitId!)}/timeline`),
    enabled: !!visitId,
    refetchInterval: POLL_MS,
  });
}

export function useTrace(runId: string | null, live = true) {
  return useQuery({
    queryKey: keys.trace(runId ?? ""),
    queryFn: () => api<TraceStep[]>(`/runs/${encodeURIComponent(runId!)}/trace`),
    enabled: !!runId,
    // A 404 (no such run) will not change by polling every second; check again slowly.
    refetchInterval: (q) => (!live ? false : q.state.error instanceof ApiError && q.state.error.status === 404 ? 15_000 : 1000),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
}

export function useGates(proposalId: string | null, live = true) {
  return useQuery({
    queryKey: keys.gates(proposalId ?? ""),
    queryFn: () => api<Gate[]>(`/proposals/${proposalId}/gates`),
    enabled: !!proposalId,
    refetchInterval: (q) => (!live || q.state.data?.every((g) => g.at) ? false : 1000),
  });
}

export function useAudit(params: { visit_id?: string; run_id?: string; limit?: number } = {}) {
  const q = new URLSearchParams();
  if (params.visit_id) q.set("visit_id", params.visit_id);
  if (params.run_id) q.set("run_id", params.run_id);
  q.set("limit", String(params.limit ?? 100));
  const qs = q.toString();
  return useQuery({ queryKey: keys.audit(qs), queryFn: () => api<AuditRow[]>(`/audit?${qs}`), refetchInterval: POLL_MS });
}

function useRefreshAll() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: keys.queue }),
      qc.invalidateQueries({ queryKey: ["proposals"] }),
      qc.invalidateQueries({ queryKey: ["timeline"] }),
      qc.invalidateQueries({ queryKey: ["gates"] }),
      qc.invalidateQueries({ queryKey: ["audit"] }),
    ]);
}

export function useRecordVitals() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (body: VitalsRequest) => api<VitalsResponse>("/vitals", { method: "POST", body }),
    onSettled: refresh,
  });
}

export function useApprove(proposalId: string) {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (body: ApproveRequest) =>
      api<ApproveResponse>(`/proposals/${proposalId}/approve`, { method: "POST", body }),
    onSettled: refresh,
  });
}

export function useReject(proposalId: string) {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (reason: string) =>
      api<{ proposal_id: string; status: "rejected" }>(`/proposals/${proposalId}/reject`, { method: "POST", body: { reason } }),
    onSettled: refresh,
  });
}

export function useAcknowledgeProposal() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (id: string) => api(`/proposals/${id}/acknowledge`, { method: "POST" }),
    onSettled: refresh,
  });
}

export function useAcknowledgeNotice() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (id: string) => api(`/notifications/${id}/acknowledge`, { method: "POST" }),
    onSettled: refresh,
  });
}

export function useDemo() {
  const qc = useQueryClient();
  const refresh = useRefreshAll();
  const load = useMutation({
    mutationFn: () => api<{ visit_id: string }>("/demo/scenario", { method: "POST", body: { name: "p014" } }),
    onSettled: async () => {
      qc.removeQueries({ queryKey: ["trace"] });
      await refresh();
    },
  });
  const next = useMutation({
    mutationFn: () => api<{ obs_id: string }>("/demo/scenario/next", { method: "POST" }),
    onSettled: refresh,
  });
  return { load, next };
}

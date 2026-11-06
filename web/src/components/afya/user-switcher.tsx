"use client";

import { Check, ChevronDown } from "lucide-react";

import type { Me } from "@/api/contract";
import { DemoBadge } from "@/components/afya/demo-badge";
import { ROLE } from "@/components/afya/sign-in";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDemoUsers, useLoginAs } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

function Initials({ name, role }: { name: string; role: string }) {
  const ini = name.replace(/[^A-Za-z ]/g, "").split(" ").filter(Boolean).map((p) => p[0]).join("").slice(0, 2);
  return (
    <span
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-full text-xs font-bold",
        role === "manager" ? "bg-muted text-muted-foreground ring-1 ring-border" : "bg-primary text-primary-foreground",
      )}
    >
      {ini}
    </span>
  );
}

/** "Sign in as…" switcher (E7-6). Only rendered when the API says demo mode is on. */
export function UserSwitcher({ me }: { me: Me }) {
  const users = useDemoUsers(me.demo);
  const login = useLoginAs();
  return (
    <div className="flex items-center gap-2">
      {me.demo && <DemoBadge compact />}
      <DropdownMenu>
        <DropdownMenuTrigger
          data-testid="user-switcher"
          className="flex h-11 items-center gap-2.5 rounded-xl border bg-card pr-2.5 pl-1.5 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/40"
        >
          <Initials name={me.name} role={me.role} />
          <span className="hidden leading-tight sm:block">
            <span className="block text-sm font-semibold">{me.name}</span>
            <span className="block text-[11px] text-muted-foreground">{ROLE[me.role].title}</span>
          </span>
          <ChevronDown className="size-4 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-80">
          <DropdownMenuGroup>
            <DropdownMenuLabel className="flex items-center justify-between">
              Sign in as… {me.demo && <DemoBadge compact />}
            </DropdownMenuLabel>
            {users.data?.map((u) => (
              <DropdownMenuItem
                key={u.id}
                data-testid={`switch-${u.id}`}
                className="gap-3 py-2"
                onClick={() => {
                  if (u.id === me.id) return;
                  login.mutate(u.id, { onSuccess: () => toast.success(`Signed in as ${u.name}`, { description: ROLE[u.role].can }) });
                }}
              >
                <Initials name={u.name} role={u.role} />
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block font-medium">{u.name}</span>
                  <span className="block text-xs text-muted-foreground">{ROLE[u.role].title}</span>
                </span>
                {u.id === me.id && <Check className="size-4" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <p className="px-2 py-1.5 text-xs text-muted-foreground">
            Demo mode has no real authentication. A manager can read everything but confirm nothing.
          </p>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

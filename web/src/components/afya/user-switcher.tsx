"use client";

import { Check, ChevronDown, Loader2, LogOut } from "lucide-react";

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
import { useDemoUsers, useLoginAs, useLogout } from "@/lib/queries";
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

/** User menu with sign-out; role switching is available only in demo mode (E7-6). */
export function UserSwitcher({ me }: { me: Me }) {
  const users = useDemoUsers(me.demo);
  const login = useLoginAs();
  const logout = useLogout();
  return (
    <div className="flex items-center gap-2">
      {me.demo && <DemoBadge compact />}
      <DropdownMenu>
        <DropdownMenuTrigger
          data-testid="user-switcher"
          aria-label={`User menu for ${me.name}`}
          className="flex h-11 items-center gap-2.5 rounded-xl border bg-card pr-2.5 pl-1.5 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/40"
        >
          <Initials name={me.name} role={me.role} />
          <span className="hidden whitespace-nowrap leading-tight lg:block">
            <span className="block text-sm font-semibold">{me.name}</span>
            <span className="block text-2xs text-muted-foreground">{ROLE[me.role].title}</span>
          </span>
          <ChevronDown className="size-4 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-80">
          {me.demo && (
            <DropdownMenuGroup>
              <DropdownMenuLabel className="flex items-center justify-between">
                Sign in as… <DemoBadge compact />
              </DropdownMenuLabel>
              {users.data?.map((u) => (
                <DropdownMenuItem
                  key={u.id}
                  data-testid={`switch-${u.id}`}
                  className="gap-3 py-2"
                  disabled={login.isPending || logout.isPending}
                  onClick={() => {
                    if (u.id === me.id) return;
                    login.mutate(u.id, {
                      onSuccess: () => toast.success(`Signed in as ${u.name}`, { description: ROLE[u.role].can }),
                      onError: (e) => toast.error("Could not switch user", { description: e.message }),
                    });
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
          )}
          {me.demo && <DropdownMenuSeparator />}
          <DropdownMenuItem
            data-testid="logout"
            disabled={logout.isPending || login.isPending}
            className="min-h-11 gap-3"
            onClick={() => logout.mutate(undefined, {
              onError: (e) => toast.error("Could not sign out", { description: `${e.message} Try again from the user menu.` }),
            })}
          >
            {logout.isPending ? <Loader2 className="size-4 animate-spin" /> : <LogOut className="size-4" />}
            {logout.isPending ? "Signing out…" : "Sign out"}
          </DropdownMenuItem>
          {me.demo && (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              Demo mode has no real authentication. A manager can read everything but confirm nothing.
            </p>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

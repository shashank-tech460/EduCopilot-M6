"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/store/useToastStore";

export interface WorkspaceSummary {
  id: string;
  name: string;
  createdAt: string;
}

interface WorkspaceDashboardProps {
  userName: string;
  initialWorkspaces: WorkspaceSummary[];
}

/**
 * Client component handling all interactive dashboard behavior (create,
 * delete). Initial data comes from the server component parent
 * (app/(dashboard)/dashboard/page.tsx), which queries MongoDB directly —
 * this component re-syncs with the server via router.refresh() after each
 * mutation rather than reloading the page, so state stays correct without a
 * full navigation.
 *
 * Deletion requires confirmation via AlertDialog (destructive, irreversible
 * — it cascade-deletes every file/conversation/message in the workspace on
 * the server) rather than firing immediately from a click.
 */
export function WorkspaceDashboard({ userName, initialWorkspaces }: WorkspaceDashboardProps) {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState(initialWorkspaces);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<WorkspaceSummary | null>(null);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);
    setIsSubmitting(true);

    try {
      const response = await fetch("/api/workspaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await response.json();

      if (!response.ok) {
        setCreateError(data?.error ?? "Something went wrong.");
        return;
      }

      setWorkspaces((prev) => [data, ...prev]);
      setName("");
      setDialogOpen(false);
      toast({ title: "Workspace created", description: data.name, variant: "success" });
      router.refresh();
    } catch {
      setCreateError("Something went wrong. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) return;
    const { id, name: workspaceName } = pendingDelete;
    setDeletingId(id);

    try {
      const response = await fetch(`/api/workspaces/${id}`, { method: "DELETE" });

      if (!response.ok) {
        toast({
          title: "Couldn't delete workspace",
          description: "Please try again.",
          variant: "destructive",
        });
        return;
      }

      setWorkspaces((prev) => prev.filter((workspace) => workspace.id !== id));
      toast({ title: "Workspace deleted", description: workspaceName, variant: "default" });
      router.refresh();
    } catch {
      toast({
        title: "Couldn't delete workspace",
        description: "Please try again.",
        variant: "destructive",
      });
    } finally {
      setDeletingId(null);
      setPendingDelete(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome, {userName}</h1>
        <p className="text-sm text-muted-foreground">
          {workspaces.length === 0
            ? "You don't have any workspaces yet."
            : `${workspaces.length} workspace${workspaces.length === 1 ? "" : "s"}.`}
        </p>
      </div>

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Your Workspaces</h2>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="h-4 w-4" />
              Create Workspace
            </Button>
          </DialogTrigger>
          <DialogContent>
            <form onSubmit={handleCreate}>
              <DialogHeader>
                <DialogTitle>Create workspace</DialogTitle>
                <DialogDescription>
                  Give it a name, like a course or subject.
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-1.5 py-4">
                <Label htmlFor="workspace-name">Workspace name</Label>
                <Input
                  id="workspace-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={60}
                  autoFocus
                  aria-invalid={!!createError}
                />
                {createError ? (
                  <p className="text-xs text-destructive">{createError}</p>
                ) : null}
              </div>
              <DialogFooter>
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Creating…" : "Create Workspace"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {workspaces.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
            <p className="text-sm font-medium">No workspaces yet</p>
            <p className="max-w-xs text-sm text-muted-foreground">
              Create one for a course or subject to start uploading material.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {workspaces.map((workspace) => (
            <Card key={workspace.id}>
              <CardHeader>
                <CardTitle>{workspace.name}</CardTitle>
              </CardHeader>
              <CardFooter className="flex gap-2">
                <Button asChild variant="outline" size="sm">
                  <Link href={`/workspace/${workspace.id}`}>Open</Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPendingDelete(workspace)}
                  disabled={deletingId === workspace.id}
                >
                  <Trash2 className="h-4 w-4" />
                  {deletingId === workspace.id ? "Deleting…" : "Delete"}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      <AlertDialog
        open={!!pendingDelete}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &quot;{pendingDelete?.name}&quot;?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the workspace and everything in it —
              all uploaded files, conversations, and messages. This cannot
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={!!deletingId}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              disabled={!!deletingId}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deletingId ? "Deleting…" : "Delete workspace"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

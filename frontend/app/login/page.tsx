"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Bot, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, authApi } from "@/lib/api";
import { safeNextPath } from "@/lib/navigation";

function organizationChoices(err: unknown): string[] | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = err.detail as { organizations?: unknown } | undefined;
  const orgs = detail?.organizations;
  return Array.isArray(orgs) && orgs.every((o) => typeof o === "string") ? orgs : null;
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // Filled only when the same email + password exists in several organizations.
  const [organizations, setOrganizations] = useState<string[] | null>(null);
  const [organization, setOrganization] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await authApi.login(email, password, organization || undefined);
      // Only ever redirect within this site (open-redirect protection).
      router.replace(safeNextPath(searchParams.get("next"), window.location.origin));
    } catch (err) {
      const choices = organizationChoices(err);
      if (choices) {
        setOrganizations(choices);
        setOrganization(choices[0]);
        setError(null);
      } else {
        setError(err instanceof ApiError ? err.message : "Could not reach the server.");
      }
      setPending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="text-center">
        <div className="mx-auto mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Bot className="size-5" aria-hidden />
        </div>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>Support Knowledge Platform</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid gap-4" noValidate>
          {error && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {organizations && (
            <div className="grid gap-2">
              <Label htmlFor="organization">Organization</Label>
              <select
                id="organization"
                className="h-9 rounded-md border bg-transparent px-3 text-sm shadow-xs"
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
              >
                {organizations.map((slug) => (
                  <option key={slug} value={slug}>
                    {slug}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                Your account exists in several organizations. Choose one.
              </p>
            </div>
          )}
          <Button type="submit" disabled={pending || !email || !password}>
            {pending && <Loader2 className="animate-spin" aria-hidden />}
            Sign in
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <main className="flex flex-1 items-center justify-center bg-muted/40 p-4">
      {/* useSearchParams needs a Suspense boundary */}
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}

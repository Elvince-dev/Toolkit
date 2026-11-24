import { useState } from "react";
import { ArrowRight, Check, LockKeyhole, Table2 } from "lucide-react";
import { BrandMark, DataIllustration } from "./Brand";

type AuthView = "landing" | "sign-in" | "sign-up" | "forgot-password" | "reset-password";

interface Props {
  isSubmitting: boolean;
  isResettingPassword: boolean;
  message: string;
  error: string;
  onSignIn: (email: string, password: string) => Promise<void>;
  onSignUp: (email: string, password: string) => Promise<void>;
  onRequestPasswordReset: (email: string) => Promise<void>;
  onSetPassword: (password: string) => Promise<void>;
}

export default function SignInPage({
  isSubmitting,
  isResettingPassword,
  message,
  error,
  onSignIn,
  onSignUp,
  onRequestPasswordReset,
  onSetPassword,
}: Props) {
  const [view, setView] = useState<AuthView>("landing");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const activeView = isResettingPassword ? "reset-password" : view;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (activeView === "sign-in") {
      await onSignIn(email.trim(), password);
    } else if (activeView === "sign-up") {
      if (password !== confirmPassword) return;
      await onSignUp(email.trim(), password);
    } else if (activeView === "forgot-password") {
      await onRequestPasswordReset(email.trim());
    } else if (activeView === "reset-password") {
      if (password !== confirmPassword) return;
      await onSetPassword(password);
    }
  };

  const title =
    activeView === "sign-up"
      ? "Create your account"
      : activeView === "forgot-password"
        ? "Reset your password"
        : activeView === "reset-password"
          ? "Choose a new password"
          : "Welcome back";

  return (
    <div className="min-h-screen bg-[#FAF9F5] px-5 text-ink">
      <div className="mx-auto flex min-h-screen max-w-[1160px] flex-col">
        <header className="flex h-16 items-center justify-between border-b border-border">
          <BrandMark />
          <span className="text-[11px] text-muted">A little clarity, every day.</span>
        </header>

        <main className="grid flex-1 items-center gap-8 py-12 md:grid-cols-2 md:py-16 md:pl-12">
          <div className="max-w-[510px]">
            <p className="mb-5 text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
              A little less work. A lot more clarity.
            </p>
            <h1 className="font-serif text-[clamp(2.5rem,5vw,3.5rem)] leading-[1.03] tracking-tight text-primary">
              Ask anything
              <br />
              about your data.
            </h1>
            <p className="mt-5 max-w-[390px] text-sm leading-6 text-muted">
              Bring a spreadsheet, connect your inbox, and let the questions flow.
            </p>

            {activeView === "landing" ? (
              <div className="mt-7 flex flex-wrap items-center gap-x-5 gap-y-3">
                <button
                  onClick={() => setView("sign-in")}
                  className="inline-flex items-center gap-8 rounded-lg bg-primary px-4 py-3 text-xs font-medium text-white transition-colors hover:bg-primary/90"
                >
                  Get started <ArrowRight size={15} />
                </button>
                <button
                  onClick={() => setView("sign-up")}
                  className="text-[11px] text-muted underline-offset-4 hover:text-primary hover:underline"
                >
                  Create an account
                </button>
              </div>
            ) : (
              <form onSubmit={submit} className="mt-7 max-w-[400px]">
                <h2 className="mb-4 font-serif text-2xl text-primary">{title}</h2>
                {activeView !== "reset-password" && (
                  <>
                    <label htmlFor="auth-email" className="mb-1.5 block text-xs font-medium text-ink">
                      Email address
                    </label>
                    <input
                      id="auth-email"
                      type="email"
                      autoComplete="email"
                      placeholder="you@example.com"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      required
                      disabled={isSubmitting}
                      className="mb-3 w-full rounded-lg border border-border bg-white px-3 py-3 text-sm outline-none transition focus:border-primary/50"
                    />
                  </>
                )}

                {(activeView === "sign-in" ||
                  activeView === "sign-up" ||
                  activeView === "reset-password") && (
                  <>
                    <label htmlFor="auth-password" className="mb-1.5 block text-xs font-medium text-ink">
                      {activeView === "reset-password" ? "New password" : "Password"}
                    </label>
                    <input
                      id="auth-password"
                      type="password"
                      autoComplete={activeView === "sign-in" ? "current-password" : "new-password"}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      minLength={activeView === "sign-in" ? undefined : 6}
                      required
                      disabled={isSubmitting}
                      className="mb-3 w-full rounded-lg border border-border bg-white px-3 py-3 text-sm outline-none transition focus:border-primary/50"
                    />
                    {activeView !== "sign-in" && (
                      <>
                        <label htmlFor="auth-confirm-password" className="mb-1.5 block text-xs font-medium text-ink">
                          Confirm password
                        </label>
                        <input
                          id="auth-confirm-password"
                          type="password"
                          autoComplete="new-password"
                          value={confirmPassword}
                          onChange={(event) => setConfirmPassword(event.target.value)}
                          minLength={6}
                          required
                          disabled={isSubmitting}
                          className="mb-2 w-full rounded-lg border border-border bg-white px-3 py-3 text-sm outline-none transition focus:border-primary/50"
                        />
                        {confirmPassword && password !== confirmPassword && (
                          <p role="alert" className="mb-2 text-xs text-red-600">
                            The passwords do not match.
                          </p>
                        )}
                        <p className="mb-3 text-[10px] leading-4 text-muted">
                          Use at least 6 characters. You’ll confirm your email once after signing up.
                        </p>
                      </>
                    )}
                  </>
                )}

                {activeView === "forgot-password" && (
                  <p className="mb-3 text-xs leading-5 text-muted">
                    Enter your account email and we’ll send a password reset link.
                  </p>
                )}

                <button
                  type="submit"
                  disabled={
                    isSubmitting ||
                    ((activeView === "sign-up" || activeView === "reset-password") &&
                      password !== confirmPassword)
                  }
                  className="w-full rounded-lg bg-primary px-4 py-3 text-xs font-medium text-white transition hover:bg-primary/90 disabled:opacity-60"
                >
                  {isSubmitting
                    ? "Please wait..."
                    : activeView === "sign-up"
                      ? "Create account"
                      : activeView === "forgot-password"
                        ? "Send reset link"
                        : activeView === "reset-password"
                          ? "Save new password"
                          : "Sign in"}
                </button>
                {message && <p role="status" className="mt-3 text-sm text-primary">{message}</p>}
                {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}

                <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-muted">
                  {activeView === "sign-in" && (
                    <>
                      <button type="button" onClick={() => setView("sign-up")} className="hover:text-primary">
                        Create an account
                      </button>
                      <button type="button" onClick={() => setView("forgot-password")} className="hover:text-primary">
                        Forgot password?
                      </button>
                    </>
                  )}
                  {activeView === "sign-up" && (
                    <button type="button" onClick={() => setView("sign-in")} className="hover:text-primary">
                      Already have an account? Sign in
                    </button>
                  )}
                  {(activeView === "forgot-password" || activeView === "reset-password") && (
                    <button type="button" onClick={() => setView("sign-in")} className="hover:text-primary">
                      Back to sign in
                    </button>
                  )}
                </div>
              </form>
            )}
          </div>

          <DataIllustration />
        </main>

        <footer className="grid grid-cols-3 gap-3 border-t border-border py-6 text-[10px] text-muted sm:gap-6">
          <div className="flex items-center justify-center gap-2"><LockKeyhole size={13} className="text-primary" />Private by default</div>
          <div className="flex items-center justify-center gap-2"><Table2 size={13} className="text-primary" />CSV spreadsheets</div>
          <div className="flex items-center justify-center gap-2"><Check size={13} className="text-primary" />Your data, your rules</div>
        </footer>
      </div>
    </div>
  );
}

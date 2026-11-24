import { Check, LockKeyhole, Mail, Table2 } from "lucide-react";
import type { Dataset } from "../types";

interface Props {
  datasets: Dataset[];
  email: string;
  onSelectDataset: (dataset: Dataset) => void;
}

export default function SettingsPage({ datasets, email, onSelectDataset }: Props) {
  return (
    <div className="h-full overflow-y-auto px-5 py-9 md:px-10">
      <div className="mx-auto max-w-[540px]">
        <div className="mb-7 text-center">
          <h1 className="font-serif text-3xl text-primary md:text-4xl">Make yourself at home.</h1>
          <p className="mt-2 text-xs text-muted">A few simple preferences. Everything in your control.</p>
        </div>

        <section className="mb-4 rounded-2xl border border-border bg-surface p-5 shadow-sm">
          <h2 className="font-serif text-xl text-primary">Your datasets</h2>
          <p className="mt-1 text-[11px] text-muted">The things you’re making sense of.</p>
          <div className="mt-4 divide-y divide-border">
            {datasets.map((dataset) => (
              <button
                key={dataset.id}
                onClick={() => onSelectDataset(dataset)}
                className="flex w-full items-center gap-3 py-3 text-left hover:bg-background/70"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sage text-primary">
                  <Table2 size={15} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-ink">{dataset.name}</span>
                  <span className="mt-1 block text-[10px] text-muted">
                    {dataset.row_count.toLocaleString()} rows · Private
                  </span>
                </span>
                <span className="text-[10px] text-muted">open</span>
              </button>
            ))}
            {datasets.length === 0 && (
              <p className="py-4 text-xs text-muted">You haven’t added a dataset yet.</p>
            )}
          </div>
        </section>

        <section className="mb-4 flex items-center gap-4 rounded-2xl border border-border bg-surface p-5 shadow-sm">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sage text-primary">
            <LockKeyhole size={17} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-xl text-primary">Privacy</h2>
            <p className="mt-1 text-xs font-medium text-ink">Your data stays private.</p>
            <p className="mt-1 text-[10px] leading-4 text-muted">
              Only your signed-in account can access your datasets and conversations.
            </p>
          </div>
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-sage px-2.5 py-1 text-[10px] font-medium text-primary">
            <Check size={11} /> On
          </span>
        </section>

        <section className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
          <h2 className="font-serif text-xl text-primary">Your account</h2>
          <div className="mt-4 flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sage text-primary">
              <Mail size={15} />
            </span>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-ink">{email}</p>
              <p className="mt-1 text-[10px] text-muted">Signed in with a secure email link</p>
            </div>
          </div>
        </section>

        <p className="mt-5 flex items-center justify-center gap-1.5 text-[10px] text-muted">
          <Check size={11} /> Your preferences save automatically.
        </p>
      </div>
    </div>
  );
}

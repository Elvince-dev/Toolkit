import { useState } from "react";
import { Database, Shield, Upload, Zap } from "lucide-react";
import { apiErrorMessage, authenticatedFetch } from "../api";
import type { Dataset } from "../types";
import { BrandMark, DataIllustration } from "./Brand";

interface Props {
  datasets: Dataset[];
  error: string;
  email: string;
  onSelectDataset: (dataset: Dataset) => void;
  onUploadSuccess: (dataset: Dataset) => void;
  onSignOut: () => void;
}

export default function WelcomeScreen({
  datasets,
  error,
  email,
  onSelectDataset,
  onUploadSuccess,
  onSignOut,
}: Props) {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError("");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await authenticatedFetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      const dataset: Dataset = await response.json();
      onUploadSuccess(dataset);
    } catch (cause) {
      console.error("Upload failed", cause);
      setUploadError(cause instanceof Error ? cause.message : "Unable to upload this CSV.");
    } finally {
      setIsUploading(false);
      event.target.value = "";
    }
  };

  return (
    <div className="min-h-screen bg-[#FAF9F5] px-5 text-ink">
      <div className="mx-auto flex min-h-screen max-w-[1160px] flex-col">
        <header className="flex h-16 items-center justify-between border-b border-border">
          <BrandMark />
          <div className="flex items-center gap-4">
            <span className="hidden text-[11px] text-muted sm:inline">{email}</span>
            <button onClick={onSignOut} className="text-[11px] text-muted hover:text-primary">
              Sign out
            </button>
          </div>
        </header>

        <main className="grid flex-1 items-center gap-6 py-10 md:grid-cols-2 md:py-12 md:pl-12">
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

            <label className="mt-7 inline-flex cursor-pointer items-center gap-8 rounded-lg bg-primary px-4 py-3 text-xs font-medium text-white transition-colors hover:bg-primary/90">
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={handleFileUpload}
                disabled={isUploading}
                className="sr-only"
              />
              {isUploading ? "Uploading..." : "Get started"}
              <Upload size={14} />
            </label>
            <p className="mt-3 text-[11px] text-muted">
              {datasets.length > 0
                ? "Or continue with one of your saved datasets below."
                : "Start with a CSV spreadsheet."}
            </p>
            {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
            {uploadError && <p role="alert" className="mt-3 text-sm text-red-600">{uploadError}</p>}
          </div>

          <DataIllustration />
        </main>

        {datasets.length > 0 && (
          <section className="mb-8 border-t border-border pt-5">
            <h2 className="mb-3 text-[9px] font-semibold uppercase tracking-[0.18em] text-muted">
              Your datasets
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {datasets.map((dataset) => (
                <button
                  key={dataset.id}
                  onClick={() => onSelectDataset(dataset)}
                  className="flex items-center gap-3 rounded-xl border border-border bg-white/80 p-3 text-left transition hover:border-primary/30 hover:bg-white"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sage text-primary">
                    <Database size={15} />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium text-ink">{dataset.name}</span>
                    <span className="text-[10px] text-muted">{dataset.row_count.toLocaleString()} rows</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        )}

        <footer className="grid grid-cols-3 gap-3 border-t border-border py-6 text-[10px] text-muted sm:gap-6">
          <div className="flex items-center justify-center gap-2"><Shield size={13} className="text-primary" />Private by default</div>
          <div className="flex items-center justify-center gap-2"><Database size={13} className="text-primary" />CSV spreadsheets</div>
          <div className="flex items-center justify-center gap-2"><Zap size={13} className="text-primary" />Your data, your rules</div>
        </footer>
      </div>
    </div>
  );
}

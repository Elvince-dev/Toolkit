import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { apiErrorMessage, authenticatedFetch } from "../api";
import type { Dataset } from "../types";

interface Column {
  name: string;
  type: string;
  unique: number;
}

interface Data {
  name: string;
  row_count: number;
  columns: Column[];
  rows: string[][];
}

interface Props {
  dataset: Dataset;
}

const PAGE_SIZE = 10;

export default function DataView({ dataset }: Props) {
  const [data, setData] = useState<Data | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    authenticatedFetch(`/api/datasets/${encodeURIComponent(dataset.id)}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiErrorMessage(response));
        return response.json() as Promise<Data>;
      })
      .then(setData)
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "Unable to load this dataset.");
      });
    return () => controller.abort();
  }, [dataset.id]);

  const filteredRows = useMemo(
    () =>
      (data?.rows ?? []).filter((row) =>
        row.some((cell) => String(cell).toLowerCase().includes(search.toLowerCase())),
      ),
    [data?.rows, search],
  );
  const pageCount = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const exportCsv = () => {
    if (!data) return;
    const escapeCell = (value: string) => `"${String(value).replace(/"/g, '""')}"`;
    const csv = [data.columns.map((column) => column.name), ...filteredRows]
      .map((row) => row.map(escapeCell).join(","))
      .join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${data.name}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (error) {
    return (
      <div className="p-8 text-center">
        <p role="alert" className="text-sm text-red-600">{error}</p>
      </div>
    );
  }
  if (!data) {
    return <div className="p-8 text-center text-sm text-muted">Loading your dataset...</div>;
  }

  const previewEnd = page * PAGE_SIZE + pageRows.length;

  return (
    <div className="flex h-full min-w-0 overflow-hidden">
      <section className="min-w-0 flex-1 overflow-auto px-5 py-7 md:px-8">
        <div className="mb-5">
          <h1 className="font-serif text-3xl text-primary">Your data, at a glance.</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-muted">
            <span className="font-medium text-primary">{data.name}</span>
            <span aria-hidden="true">·</span>
            <span>{data.row_count.toLocaleString()} rows</span>
            <span aria-hidden="true">·</span>
            <span>{data.columns.length} columns</span>
            <span aria-hidden="true">·</span>
            <span>
              Added{" "}
              {new Date(dataset.created_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              })}
            </span>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <label className="relative block w-full max-w-[280px]">
            <Search className="absolute left-3 top-2.5 text-muted" size={14} />
            <input
              type="search"
              placeholder="Search this dataset..."
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
              className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-[11px] outline-none focus:border-primary/40"
            />
          </label>
          <button
            onClick={exportCsv}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-[10px] font-medium text-white transition hover:bg-primary/90"
          >
            Export <Download size={13} />
          </button>
        </div>

        <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-sm">
          <table className="w-full min-w-[560px] text-left text-[11px]">
            <thead className="bg-[#F3F0EA] text-[9px] uppercase tracking-[0.14em] text-muted">
              <tr>
                {data.columns.map((column) => (
                  <th key={column.name} className="border-b border-border px-3 py-3 font-semibold md:px-4">
                    {column.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {pageRows.map((row, rowIndex) => (
                <tr
                  key={`${page}-${rowIndex}`}
                  className={rowIndex === 2 ? "bg-[#E8ECE4]" : "hover:bg-[#F6F7F2]"}
                >
                  {data.columns.map((column, columnIndex) => (
                    <td key={`${column.name}-${columnIndex}`} className="whitespace-nowrap px-3 py-3 text-ink md:px-4">
                      {row[columnIndex] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={Math.max(1, data.columns.length)} className="px-4 py-8 text-center text-muted">
                    No rows match your search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[9px] text-muted">
          <span>
            Showing {filteredRows.length ? page * PAGE_SIZE + 1 : 0}–{previewEnd} of{" "}
            {filteredRows.length} preview rows · {data.row_count.toLocaleString()} total
          </span>
          <div className="flex items-center gap-2">
            <button
              aria-label="Previous preview page"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              className="rounded border border-border p-1.5 disabled:opacity-40"
            >
              <ChevronLeft size={13} />
            </button>
            <span>
              {page + 1} of {pageCount}
            </span>
            <button
              aria-label="Next preview page"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
              className="rounded border border-border p-1.5 disabled:opacity-40"
            >
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      </section>

      <aside className="hidden w-[230px] shrink-0 overflow-y-auto border-l border-border bg-[#F7F5F0] px-4 py-7 lg:block">
        <p className="mb-5 text-[9px] font-semibold uppercase tracking-[0.16em] text-muted">
          About your columns
        </p>
        <div className="space-y-2.5">
          {data.columns.map((column) => (
            <div key={column.name} className="rounded-xl border border-border bg-surface p-3.5">
              <div className="flex items-start justify-between gap-2">
                <span className="text-[11px] font-medium text-ink">{column.name}</span>
                <span className="rounded bg-background px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-muted">
                  {column.type}
                </span>
              </div>
              <p className="mt-3 text-[10px] text-muted">{column.unique.toLocaleString()} unique values</p>
            </div>
          ))}
        </div>
        <p className="mt-7 flex items-center gap-2 text-[9px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" /> Private. Always in your control.
        </p>
      </aside>
    </div>
  );
}

import { useEffect, useState } from "react";
import { ArrowLeft, Download, Search } from "lucide-react";

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
  datasetName: string;
  onBack: () => void;
}

export default function DataView({ datasetName, onBack }: Props) {
  const [data, setData] = useState<Data | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`http://localhost:8000/api/dataset?dataset=${encodeURIComponent(datasetName)}`, {
      signal: controller.signal,
    })
      .then(async (res) => {
        const result = await res.json();
        if (!res.ok) throw new Error(result.detail || "Unable to load this dataset.");
        setData(result);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "Unable to load this dataset.");
      });
    return () => controller.abort();
  }, [datasetName]);

  if (error) {
    return (
      <div className="p-8 text-center text-red-600">
        <p role="alert">{error}</p>
        <button onClick={onBack} className="mt-4 text-sm text-primary hover:underline">
          Back to conversation
        </button>
      </div>
    );
  }
  if (!data) return <div className="p-8 text-center text-muted">Loading data...</div>;

  const filteredRows = data.rows.filter((row) =>
    row.some((cell) => String(cell).toLowerCase().includes(search.toLowerCase())),
  );
  const exportCsv = () => {
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

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="h-14 border-b border-border flex items-center px-6 bg-background">
        <button onClick={onBack} className="flex items-center gap-2 text-sm font-medium text-muted hover:text-ink mr-4">
          <ArrowLeft size={16} /> Back
        </button>
        <div className="font-serif text-xl text-primary">{data.name} · Your data, at a glance.</div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Table Area */}
        <div className="flex-1 p-6 overflow-auto">
          <div className="flex items-center justify-between mb-4">
            <div className="relative w-64">
              <Search className="absolute left-3 top-2.5 text-muted" size={16} />
              <input 
                type="text" 
                placeholder="Search this dataset..." 
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="w-full pl-9 pr-4 py-2 border border-border rounded-lg bg-surface text-sm focus:outline-none focus:border-primary/50"
              />
            </div>
            <button onClick={exportCsv} className="flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity">
              <Download size={16} /> Export
            </button>
          </div>

          <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#F5F3EF] text-muted text-xs uppercase tracking-wider">
                <tr>
                  {data.columns.map((col) => (
                    <th key={col.name} className="px-4 py-3 font-semibold border-b border-border">
                      {col.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredRows.map((row, i) => (
                  <tr key={i} className="hover:bg-sage/20 transition-colors">
                    {row.map((cell, j) => (
                      <td key={j} className="px-4 py-3 text-ink whitespace-nowrap">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 text-xs text-muted">
            Showing {filteredRows.length} of {data.row_count} preview rows
          </div>
        </div>

        {/* Context Panel */}
        <div className="w-80 border-l border-border bg-surface p-6 overflow-y-auto">
          <h2 className="font-serif text-xl text-primary mb-1">A little context</h2>
          <p className="text-sm text-muted mb-6">Get to know what's inside.</p>
          
          <div className="space-y-3">
            {data.columns.map((col) => (
              <div key={col.name} className="border border-border rounded-lg p-3">
                <div className="flex justify-between items-start mb-1">
                  <span className="font-medium text-sm text-ink">{col.name}</span>
                  <span className="text-[10px] uppercase tracking-wider font-bold text-muted bg-background px-2 py-0.5 rounded">
                    {col.type}
                  </span>
                </div>
                <div className="text-xs text-muted">
                  {col.unique} unique values
                </div>
              </div>
            ))}
          </div>
          
          <div className="mt-8 text-xs text-muted flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-primary" />
            Private. Always in your control.
          </div>
        </div>
      </div>
    </div>
  );
}
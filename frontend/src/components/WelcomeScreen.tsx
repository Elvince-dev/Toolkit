import { useState } from "react";
import { Upload, ArrowRight, Shield, Zap, Database } from "lucide-react";

interface Props {
  onUploadSuccess: (filename: string) => void;
}

export default function WelcomeScreen({ onUploadSuccess }: Props) {
  const [isUploading, setIsUploading] = useState(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      onUploadSuccess(data.filename);
    } catch (error) {
      console.error("Upload failed", error);
      alert("Upload failed. Is the Python server running?");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-background">
      <div className="max-w-2xl w-full text-center space-y-8">
        
        {/* Header */}
        <div className="space-y-4">
          <h1 className="font-serif text-5xl text-primary tracking-tight">
            Ask anything about your data.
          </h1>
          <p className="text-muted text-lg">
            Bring a spreadsheet, connect your inbox, and let the questions flow.
          </p>
        </div>

        {/* Upload Box */}
        <div className="relative group">
          <input
            type="file"
            accept=".csv"
            onChange={handleFileUpload}
            disabled={isUploading}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
          />
          <div className="border-2 border-dashed border-border rounded-2xl p-12 bg-surface group-hover:border-primary/40 transition-colors shadow-sm">
            <div className="w-12 h-12 bg-sage rounded-full flex items-center justify-center mx-auto mb-4">
              <Upload className="text-primary" size={24} />
            </div>
            <h3 className="text-lg font-medium text-ink mb-1">
              {isUploading ? "Uploading and reading..." : "Drop a CSV here, or click to upload"}
            </h3>
            <p className="text-sm text-muted">CSV, Excel, or a Google Sheet URL</p>
          </div>
        </div>

        {/* Trust Badges */}
        <div className="grid grid-cols-3 gap-4 pt-8">
          <div className="flex flex-col items-center text-center space-y-2">
            <Shield size={20} className="text-muted" />
            <span className="text-xs text-muted font-medium">Private by default</span>
          </div>
          <div className="flex flex-col items-center text-center space-y-2">
            <Database size={20} className="text-muted" />
            <span className="text-xs text-muted font-medium">Any format</span>
          </div>
          <div className="flex flex-col items-center text-center space-y-2">
            <Zap size={20} className="text-muted" />
            <span className="text-xs text-muted font-medium">Your data, your rules</span>
          </div>
        </div>
      </div>
    </div>
  );
}
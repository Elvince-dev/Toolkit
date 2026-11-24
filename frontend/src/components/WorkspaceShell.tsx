import { useState } from "react";
import {
  ChevronDown,
  LogOut,
  Menu,
  Plus,
  Settings,
  Table2,
  X,
} from "lucide-react";
import type { Conversation, Dataset } from "../types";
import { BrandMark } from "./Brand";

type WorkspacePage = "chat" | "data" | "settings";

interface Props {
  children: React.ReactNode;
  datasets: Dataset[];
  dataset: Dataset;
  conversations: Conversation[];
  activeConversationId: string | null;
  page: WorkspacePage;
  userEmail: string;
  onSelectDataset: (dataset: Dataset) => void;
  onSelectConversation: (conversationId: string) => void;
  onNewConversation: () => void;
  onAddDataset: () => void;
  onOpenData: () => void;
  onOpenChat: () => void;
  onOpenSettings: () => void;
  onSignOut: () => void;
}

function updatedLabel(value: string) {
  const updatedAt = new Date(value);
  if (Number.isNaN(updatedAt.valueOf())) return "";
  const ageInDays = Math.floor((Date.now() - updatedAt.valueOf()) / 86_400_000);
  if (ageInDays <= 0) return "Just now";
  if (ageInDays === 1) return "Yesterday";
  return updatedAt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function WorkspaceShell({
  children,
  datasets,
  dataset,
  conversations,
  activeConversationId,
  page,
  userEmail,
  onSelectDataset,
  onSelectConversation,
  onNewConversation,
  onAddDataset,
  onOpenData,
  onOpenChat,
  onOpenSettings,
  onSignOut,
}: Props) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const initials = userEmail.trim().charAt(0).toUpperCase() || "U";
  const pageLabel =
    page === "chat"
      ? dataset.name
      : page === "data"
        ? `Your workspace / ${dataset.name}`
        : "Your workspace / Settings";

  const closeMobileNav = () => setMobileNavOpen(false);

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background">
      <header className="z-20 flex h-16 shrink-0 items-center border-b border-border bg-background">
        <div className="flex h-full w-[190px] shrink-0 items-center gap-3 px-5">
          <button
            className="rounded-md p-1 text-muted hover:bg-black/5 md:hidden"
            aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            {mobileNavOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <BrandMark />
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-between px-4 md:px-6">
          {page === "chat" ? (
            <button
              onClick={onOpenData}
              className="flex min-w-0 items-center gap-2 font-serif text-base text-primary hover:text-primary/80 md:text-lg"
            >
              <span className="truncate">{pageLabel}</span>
              <ChevronDown size={14} className="shrink-0 text-muted" />
            </button>
          ) : (
            <div className="flex min-w-0 items-center gap-2 font-serif text-base text-primary md:text-lg">
              <button onClick={onOpenChat} className="shrink-0 hover:underline">
                Your workspace
              </button>
              <span className="text-muted">/</span>
              <span className="truncate">{page === "data" ? dataset.name : "Settings"}</span>
            </div>
          )}
          <button
            onClick={onOpenSettings}
            className="ml-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#E4ECE4] text-xs font-semibold text-primary ring-2 ring-white"
            aria-label={`Open settings for ${userEmail}`}
            title={userEmail}
          >
            {initials}
          </button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1">
        {mobileNavOpen && (
          <button
            className="absolute inset-0 z-20 bg-black/20 md:hidden"
            onClick={closeMobileNav}
            aria-label="Close navigation"
          />
        )}
        <aside
          className={`${
            mobileNavOpen ? "flex" : "hidden"
          } absolute inset-y-0 left-0 z-30 w-[240px] flex-col border-r border-border bg-[#F3F0EA] md:static md:flex md:w-[190px] md:shrink-0`}
        >
          <div className="flex-1 overflow-y-auto px-3 py-5">
            <div className="mb-7">
              <div className="mb-2 flex items-center justify-between px-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-muted">
                <span>Your datasets</span>
                <button
                  onClick={() => {
                    onAddDataset();
                    closeMobileNav();
                  }}
                  aria-label="Add a dataset"
                  className="rounded p-1 hover:bg-white/70 hover:text-primary"
                >
                  <Plus size={14} />
                </button>
              </div>
              <div className="space-y-1">
                {datasets.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => {
                      onSelectDataset(item);
                      closeMobileNav();
                    }}
                    className={`w-full rounded-xl px-2.5 py-2 text-left transition-colors ${
                      item.id === dataset.id ? "bg-white shadow-sm" : "hover:bg-white/60"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-[13px] font-medium text-primary">
                      <Table2 size={13} className="shrink-0" />
                      <span className="truncate">{item.name}</span>
                    </span>
                    <span className="ml-5 mt-1 block text-[10px] text-muted">
                      {item.row_count.toLocaleString()} rows
                    </span>
                  </button>
                ))}
                <button
                  onClick={() => {
                    onAddDataset();
                    closeMobileNav();
                  }}
                  className="mt-2 flex w-full items-center gap-2 rounded-lg border border-border/80 px-2.5 py-2 text-[10px] text-muted hover:border-primary/30 hover:text-primary"
                >
                  <Plus size={13} /> Add a dataset
                </button>
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between px-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-muted">
                <span>Conversations</span>
                <button
                  onClick={() => {
                    onNewConversation();
                    closeMobileNav();
                  }}
                  aria-label="New conversation"
                  className="rounded p-1 hover:bg-white/70 hover:text-primary"
                >
                  <Plus size={14} />
                </button>
              </div>
              <div className="space-y-1">
                {conversations.map((conversation) => (
                  <button
                    key={conversation.id}
                    onClick={() => {
                      onSelectConversation(conversation.id);
                      closeMobileNav();
                    }}
                    className={`w-full rounded-lg px-2.5 py-2 text-left ${
                      conversation.id === activeConversationId
                        ? "bg-[#E7EBE2]"
                        : "hover:bg-white/50"
                    }`}
                  >
                    <span className="block truncate text-[11px] font-medium text-primary">
                      {conversation.title}
                    </span>
                    <span className="mt-1 block text-[9px] text-muted">
                      {updatedLabel(conversation.updated_at)}
                    </span>
                  </button>
                ))}
                {conversations.length === 0 && (
                  <p className="px-2.5 py-2 text-[10px] leading-4 text-muted">
                    Your conversations will appear here.
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className="space-y-1 border-t border-border/80 p-3">
            <button
              onClick={() => {
                onOpenSettings();
                closeMobileNav();
              }}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-[11px] ${
                page === "settings"
                  ? "bg-white text-primary"
                  : "text-muted hover:bg-white/60 hover:text-primary"
              }`}
            >
              <Settings size={14} /> Settings
            </button>
            <button
              onClick={onSignOut}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-[11px] text-muted hover:bg-white/60 hover:text-primary"
            >
              <LogOut size={14} /> Sign out
            </button>
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}

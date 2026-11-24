// import ReactMarkdown from "react-markdown";
// import remarkGfm from "remark-gfm";
import { useState, useRef, useEffect } from "react";
import { ArrowUp, Check, Plus } from "lucide-react";
import DataView from "./DataView";
import SettingsPage from "./SettingsPage";
import WorkspaceShell from "./WorkspaceShell";
import { apiErrorMessage, authenticatedFetch } from "../api";
import type { ChatMessage, Conversation, Dataset } from "../types";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool?: string;
};

interface Props {
  dataset: Dataset;
  datasets: Dataset[];
  email: string;
  onAddDataset: () => void;
  onSelectDataset: (dataset: Dataset) => void;
  onSignOut: () => void;
}

export default function ChatPage({
  dataset,
  datasets,
  email,
  onAddDataset,
  onSelectDataset,
  onSignOut,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const [page, setPage] = useState<"chat" | "data" | "settings">("chat");

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading, activeConversationId]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    authenticatedFetch(`/api/conversations?dataset_id=${encodeURIComponent(dataset.id)}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiErrorMessage(response));
        return response.json() as Promise<{ conversations: Conversation[] }>;
      })
      .then(async ({ conversations: loaded }) => {
        if (!active) return;
        if (loaded.length > 0) {
          setConversations(loaded);
          setActiveConversationId(loaded[0].id);
          return;
        }

        const response = await authenticatedFetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dataset_id: dataset.id }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(await apiErrorMessage(response));
        const conversation: Conversation = await response.json();
        if (active) {
          setConversations([conversation]);
          setActiveConversationId(conversation.id);
        }
      })
      .catch((cause: unknown) => {
        if (active && !(cause instanceof DOMException && cause.name === "AbortError")) {
          setError(cause instanceof Error ? cause.message : "Unable to load conversations.");
          setIsLoadingHistory(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [dataset.id]);

  useEffect(() => {
    if (!activeConversationId) return;
    const controller = new AbortController();
    let active = true;
    authenticatedFetch(
      `/api/conversations/${encodeURIComponent(activeConversationId)}/messages`,
      { signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiErrorMessage(response));
        return response.json() as Promise<{ messages: ChatMessage[] }>;
      })
      .then(({ messages: loaded }) => {
        if (active) {
          setMessages(loaded.map((message) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            tool: message.tool_used || undefined,
          })));
        }
      })
      .catch((cause: unknown) => {
        if (active && !(cause instanceof DOMException && cause.name === "AbortError")) {
          setError(cause instanceof Error ? cause.message : "Unable to load this conversation.");
        }
      })
      .finally(() => {
        if (active) setIsLoadingHistory(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [activeConversationId]);

  const createConversation = async () => {
    setError("");
    setPage("chat");
    try {
      const response = await authenticatedFetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset_id: dataset.id }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      const conversation: Conversation = await response.json();
      setMessages([]);
      setIsLoadingHistory(true);
      setConversations((current) => [conversation, ...current]);
      setActiveConversationId(conversation.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create a conversation.");
    }
  };

  const selectConversation = (conversationId: string) => {
    setPage("chat");
    if (conversationId === activeConversationId) return;
    setMessages([]);
    setError("");
    setIsLoadingHistory(true);
    setActiveConversationId(conversationId);
  };

  const openDataset = (selected: Dataset) => {
    setPage("chat");
    onSelectDataset(selected);
  };

  const sendMessage = async () => {
    if (!input.trim() || isLoading || !activeConversationId) return;

    const userMsg: Message = { id: Date.now().toString(), role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const res = await authenticatedFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg.content,
          conversation_id: activeConversationId,
          dataset_id: dataset.id,
        }),
      });
      
      if (!res.ok) throw new Error(await apiErrorMessage(res));
      
      const data = await res.json();
      
      const botMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: data.answer,
        tool: data.tool_used || undefined,
      };
      setMessages((prev) => [...prev, botMsg]);
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === activeConversationId &&
          conversation.title === "New conversation"
            ? { ...conversation, title: userMsg.content.slice(0, 120) }
            : conversation,
        ),
      );
    } catch (error) {
      console.error(error);
      setMessages((prev) => [
        ...prev,
        { 
          id: Date.now().toString(), 
          role: "assistant", 
          content: error instanceof Error ? error.message : "The request failed. Please try again."
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <WorkspaceShell
      datasets={datasets}
      dataset={dataset}
      conversations={conversations}
      activeConversationId={activeConversationId}
      page={page}
      userEmail={email}
      onSelectDataset={openDataset}
      onSelectConversation={selectConversation}
      onNewConversation={createConversation}
      onAddDataset={onAddDataset}
      onOpenData={() => setPage("data")}
      onOpenChat={() => setPage("chat")}
      onOpenSettings={() => setPage("settings")}
      onSignOut={onSignOut}
    >
      {page === "chat" && (
        <div className="flex h-full flex-col bg-background">
          <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-7">
            <div className="mx-auto max-w-[860px] space-y-7">
              <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-muted">
                Today
              </p>
            {error && <p role="alert" className="text-center text-sm text-red-600">{error}</p>}
            {messages.length === 0 && activeConversationId && !isLoadingHistory && (
              <div className="py-16 text-center">
                <h1 className="font-serif text-3xl text-primary">Your data is ready.</h1>
                <p className="mt-2 text-sm text-muted">
                  Ask a question about {dataset.name} to get started.
                </p>
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                <div className="mb-2 flex items-center gap-2 px-1 text-[9px] font-semibold uppercase tracking-[0.16em] text-muted">
                  {msg.role === "user" ? "You" : "Toolkit"}
                </div>
                
                {msg.role === "user" ? (
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-[#E7EEE4] px-5 py-3 text-[13px] leading-relaxed text-primary shadow-sm">
                    {msg.content}
                  </div>
                ) : (
                  <div className="w-full max-w-[95%] rounded-xl border border-border bg-surface px-5 py-4 shadow-sm md:px-6">
                    <div className="mb-2 font-serif text-xl text-primary">
                      {msg.content.split('\n')[0]}
                    </div>
                    <div className="text-[15px] text-ink leading-relaxed whitespace-pre-wrap">
                      {msg.content.split('\n').slice(1).join('\n')}
                    </div>
                    
                    {msg.tool && (
                      <div className="mt-4 flex items-center gap-2">
                        <div className="inline-flex items-center gap-1.5 rounded-lg bg-[#F1F2EC] px-3 py-1.5 text-[10px] font-medium text-primary">
                          <Check size={12} strokeWidth={3} />
                          {msg.tool.replace(/_/g, ' ')}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            
            {isLoading && (
              <div className="flex flex-col items-start">
                <div className="mb-2 px-1 text-[9px] font-semibold uppercase tracking-[0.16em] text-muted">Toolkit</div>
                <div className="flex h-12 items-center gap-1 rounded-xl border border-border bg-surface px-4 shadow-sm">
                  <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce" />
                  <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:-.15s]" />
                  <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:-.3s]" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="bg-gradient-to-t from-background via-background to-transparent px-4 pb-5 pt-2 md:px-8">
          <div className="mx-auto max-w-[860px]">
            <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
              {["Show me the first few rows", "What's the total sales?", "Chart this by month"].map((chip) => (
                <button 
                  key={chip}
                  onClick={() => setInput(chip)}
                  className="whitespace-nowrap rounded-md border border-border bg-[#F1F0EA] px-3 py-1.5 text-[10px] font-medium text-muted transition-colors hover:border-primary/30 hover:text-primary"
                >
                  {chip}
                </button>
              ))}
            </div>

            <div className="relative flex items-end rounded-2xl border border-border bg-surface shadow-sm transition-all focus-within:border-primary/40 focus-within:ring-1 focus-within:ring-primary/20">
              <button
                onClick={onAddDataset}
                aria-label="Add a dataset"
                className="mb-0.5 p-3 text-muted transition-colors hover:text-primary"
              >
                <Plus size={20} />
              </button>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
                placeholder={`Ask anything about ${dataset.name}...`}
                className="max-h-32 min-h-[52px] flex-1 resize-none border-0 bg-transparent px-1 py-3.5 text-[13px] outline-none focus:ring-0"
                rows={1}
              />
              <button 
                onClick={sendMessage}
                disabled={!input.trim() || isLoading || !activeConversationId || isLoadingHistory}
                className="m-2 rounded-full bg-primary p-2.5 text-white transition-all hover:opacity-90 disabled:opacity-50"
              >
                <ArrowUp size={18} />
              </button>
            </div>
            
            <div className="mt-3 flex items-center justify-center gap-1 text-center text-[9px] text-muted">
              <Check size={10} /> Only you can see this conversation.
            </div>
          </div>
        </div>
        </div>
      )}
      {page === "data" && <DataView dataset={dataset} />}
      {page === "settings" && (
        <SettingsPage datasets={datasets} email={email} onSelectDataset={openDataset} />
      )}
    </WorkspaceShell>
  );
}
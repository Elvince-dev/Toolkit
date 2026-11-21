// import ReactMarkdown from "react-markdown";
// import remarkGfm from "remark-gfm";
import { useState, useRef, useEffect } from "react";
import { ArrowUp, Check, ChevronDown, Plus, Settings, Table } from "lucide-react";
import DataView from "./DataView";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool?: string;
};

interface Props {
  datasetName: string;
  onAddDataset: () => void;
}

export default function ChatPage({ datasetName, onAddDataset }: Props) {
  const chatStorageKey = `toolkit_chat_${datasetName}`;
  const [messages, setMessages] = useState<Message[]>(() => {
    const saved = localStorage.getItem(chatStorageKey);
    return saved ? JSON.parse(saved) : [];
  });

  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [showData, setShowData] = useState(false);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Persist messages to localStorage
  useEffect(() => {
    localStorage.setItem(chatStorageKey, JSON.stringify(messages));
  }, [chatStorageKey, messages]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMsg: Message = { id: Date.now().toString(), role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const res = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg.content }),
      });
      
      if (!res.ok) throw new Error("Network response was not ok");
      
      const data = await res.json();
      
      const botMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: data.answer,
        tool: data.tool_used || undefined,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (error) {
      console.error(error);
      setMessages((prev) => [
        ...prev,
        { 
          id: Date.now().toString(), 
          role: "assistant", 
          content: "Sorry, I couldn't connect to the Python server. Is it running?" 
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  if (showData) {
    return <DataView datasetName={datasetName} onBack={() => setShowData(false)} />;
  }

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* --- Sidebar --- */}
      <aside className="w-64 bg-[#F5F3EF] border-r border-border flex flex-col flex-shrink-0 hidden md:flex">
        <div className="p-4 flex items-center gap-2 mb-4">
          <div className="w-6 h-6 bg-primary rounded-md flex items-center justify-center text-white text-xs font-bold">t</div>
          <span className="font-serif font-bold text-xl tracking-tight">Toolkit</span>
        </div>

        <div className="flex-1 overflow-y-auto px-3">
          <div className="mb-6">
            <div className="flex items-center justify-between text-[10px] font-bold tracking-widest text-muted uppercase mb-2 px-1">
              <span>Your Datasets</span>
              <button onClick={onAddDataset} aria-label="Add a dataset">
                <Plus size={14} className="cursor-pointer hover:text-ink" />
              </button>
            </div>
            <div className="space-y-1">
              <button
                onClick={() => setShowData(true)}
                className="w-full text-left px-3 py-2 bg-white rounded-lg border border-border shadow-sm group"
              >
                <div className="flex items-center gap-2 font-medium text-sm text-ink">
                  <Table size={14} className="text-primary" />
                  <span className="truncate">{datasetName}</span>
                </div>
                <div className="text-xs text-muted mt-1 ml-6 flex items-center gap-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-primary" /> View dataset
                </div>
              </button>
              <button
                onClick={() => setShowData(true)}
                className="text-xs text-primary font-medium hover:underline mt-2 ml-1 block text-left"
              >
                View data table
              </button>
            </div>
          </div>

          <div>
            <div className="text-[10px] font-bold tracking-widest text-muted uppercase mb-2 px-1">Conversations</div>
            <div className="space-y-0.5">
              {messages.some((message) => message.role === "user") && (
                <div className="w-full text-left px-3 py-2 rounded-lg bg-sage/50 text-ink">
                  <div className="text-sm font-medium truncate">
                    {[...messages].reverse().find((message) => message.role === "user")?.content}
                  </div>
                  <div className="text-[11px] text-muted mt-0.5">Current conversation</div>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="p-3 border-t border-border mt-auto">
          <button className="flex items-center gap-2 text-sm font-medium text-muted hover:text-ink w-full px-2 py-2 rounded-md hover:bg-black/5 transition-colors">
            <Settings size={16} /> Settings
          </button>
        </div>
      </aside>

      {/* --- Main Chat Area --- */}
      <main className="flex-1 flex flex-col bg-background relative">
        {/* Header */}
        <header className="h-14 border-b border-border flex items-center px-6 bg-background/80 backdrop-blur-sm sticky top-0 z-10">
          <div className="flex items-center gap-1 font-medium text-sm cursor-pointer hover:bg-black/5 px-2 py-1 rounded-md transition-colors">
            {datasetName} <ChevronDown size={14} className="text-muted" />
          </div>
        </header>

        {/* Thread */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-8">
          <div className="max-w-3xl mx-auto space-y-8">
            {messages.length === 0 && (
              <div className="py-16 text-center">
                <h1 className="font-serif text-3xl text-primary">Your data is ready.</h1>
                <p className="mt-2 text-sm text-muted">
                  Ask a question about {datasetName} to get started.
                </p>
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                <div className="text-[10px] font-bold tracking-widest text-muted uppercase mb-2 px-1 flex items-center gap-2">
                  {msg.role === "user" ? "You" : "Toolkit"}
                </div>
                
                {msg.role === "user" ? (
                  <div className="bg-sage text-ink px-5 py-3 rounded-2xl rounded-tr-sm max-w-[85%] text-[15px] leading-relaxed shadow-sm">
                    {msg.content}
                  </div>
                ) : (
                  <div className="bg-surface border border-border px-6 py-5 rounded-2xl rounded-tl-sm max-w-[90%] shadow-sm w-full">
                    {/* Serif for the headline (first line) */}
                    <div className="font-serif text-xl text-primary mb-3">
                      {msg.content.split('\n')[0]}
                    </div>
                    {/* Sans for the rest */}
                    <div className="text-[15px] text-ink leading-relaxed whitespace-pre-wrap">
                      {msg.content.split('\n').slice(1).join('\n')}
                    </div>
                    
                    {/* Tool Pill */}
                    {msg.tool && (
                      <div className="mt-4 flex items-center gap-2">
                        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-sage/50 text-[11px] font-medium text-primary border border-primary/10">
                          <Check size={12} strokeWidth={3} />
                          {msg.tool.replace(/_/g, ' ')}
                          <span className="text-muted ml-1 pl-2 border-l border-primary/20 cursor-pointer hover:underline">See details</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            
            {isLoading && (
              <div className="flex flex-col items-start">
                <div className="text-[10px] font-bold tracking-widest text-muted uppercase mb-2 px-1">Toolkit</div>
                <div className="bg-surface border border-border px-4 py-3 rounded-2xl rounded-tl-sm shadow-sm flex gap-1 items-center h-12">
                  <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce" />
                  <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:-.15s]" />
                  <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:-.3s]" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="px-4 md:px-8 pb-6 pt-2 bg-gradient-to-t from-background via-background to-transparent">
          <div className="max-w-3xl mx-auto">
            <div className="flex gap-2 mb-3 overflow-x-auto pb-1 scrollbar-hide">
              {["Show me the first few rows", "What's the total sales?", "Chart this by month", "what is an outlier?"].map((chip) => (
                <button 
                  key={chip}
                  onClick={() => setInput(chip)}
                  className="whitespace-nowrap px-3 py-1.5 bg-surface border border-border rounded-full text-xs font-medium text-muted hover:text-ink hover:border-primary/30 transition-colors shadow-sm"
                >
                  {chip}
                </button>
              ))}
            </div>

            <div className="relative flex items-end bg-surface border border-border rounded-2xl shadow-sm focus-within:border-primary/40 focus-within:ring-1 focus-within:ring-primary/20 transition-all">
              <button className="p-3 text-muted hover:text-ink transition-colors mb-0.5">
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
                placeholder={`Ask anything about ${datasetName}...`}
                className="flex-1 bg-transparent border-0 focus:ring-0 resize-none py-3.5 px-1 text-[15px] max-h-32 min-h-[52px] outline-none"
                rows={1}
              />
              <button 
                onClick={sendMessage}
                disabled={!input.trim() || isLoading}
                className="p-2 m-2 bg-primary text-white rounded-xl hover:opacity-90 disabled:opacity-50 transition-all"
              >
                <ArrowUp size={18} />
              </button>
            </div>
            
            <div className="text-center mt-3 flex items-center justify-center gap-1 text-[10px] text-muted">
              <Check size={10} /> Only you can see this conversation.
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
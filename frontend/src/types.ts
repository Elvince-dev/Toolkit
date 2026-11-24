export interface Dataset {
  id: string;
  name: string;
  row_count: number;
  created_at: string;
}

export interface Conversation {
  id: string;
  dataset_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_used?: string | null;
  created_at: string;
}

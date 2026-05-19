"use client";

import { useCallback, useRef, useState } from "react";
import { backendUrl } from "@/lib/api-client";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
}

function extractGenieReplyText(payload: Record<string, unknown>): string {
  const message = payload.message;
  if (message && typeof message === "object") {
    const m = message as Record<string, unknown>;
    const content = m.content ?? m.text ?? m.answer;
    if (typeof content === "string" && content.trim()) return content.trim();
    const attachments = m.attachments;
    if (Array.isArray(attachments)) {
      const texts = attachments
        .map((a) => {
          if (a && typeof a === "object" && "text" in a) return String((a as { text: unknown }).text);
          if (a && typeof a === "object" && "content" in a) return String((a as { content: unknown }).content);
          return "";
        })
        .filter(Boolean);
      if (texts.length) return texts.join("\n\n");
    }
  }
  if (typeof payload.error === "string") return payload.error;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return "Received a response but could not display it.";
  }
}

export interface GenieChatPanelProps {
  ontologyId?: string | null;
}

export default function GenieChatPanel({ ontologyId }: GenieChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const conversationIdRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);
    scrollToBottom();

    try {
      const body: Record<string, string> = {
        content: text,
      };
      if (conversationIdRef.current) {
        body.conversation_id = conversationIdRef.current;
      }
      if (ontologyId) {
        body.ontology_id = ontologyId;
      }

      const res = await fetch(backendUrl("/api/workflow/genie/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });

      const data = (await res.json()) as Record<string, unknown>;
      if (!res.ok || data.ok === false) {
        const errText =
          typeof data.error === "string"
            ? data.error
            : typeof data.message === "string"
              ? data.message
              : `Request failed (${res.status})`;
        setMessages((prev) => [
          ...prev,
          { id: `e-${Date.now()}`, role: "error", text: errText },
        ]);
      } else {
        if (typeof data.conversation_id === "string" && data.conversation_id) {
          conversationIdRef.current = data.conversation_id;
        }
        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            text: extractGenieReplyText(data),
          },
        ]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "error",
          text: err instanceof Error ? err.message : "Network error",
        },
      ]);
    } finally {
      setSending(false);
      scrollToBottom();
    }
  }, [input, ontologyId, scrollToBottom, sending]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  return (
    <div className="h-full flex flex-col bg-white" data-widget="genie-chat">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0"
        aria-label="Chat messages"
      >
        {messages.length === 0 && (
          <p className="text-xs text-gray-500 leading-relaxed">
            Ask Genie about your data catalog or graph. Requires{" "}
            <span className="font-mono text-gray-400">ARANGO_AGENT_BASE_URL</span> and a configured
            Genie space.
            {ontologyId && (
              <>
                {" "}
                Context: ontology <span className="font-mono text-gray-400">{ontologyId}</span>.
              </>
            )}
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`text-xs rounded-lg px-3 py-2 whitespace-pre-wrap break-words ${
              m.role === "user"
                ? "bg-indigo-50 text-indigo-900 ml-4 border border-indigo-100"
                : m.role === "error"
                  ? "bg-red-50 text-red-700 border border-red-100"
                  : "bg-gray-50 text-gray-800 mr-2 border border-gray-200"
            }`}
          >
            {m.text}
          </div>
        ))}
        {sending && (
          <p className="text-xs text-gray-500 animate-pulse">Genie is thinking…</p>
        )}
      </div>
      <div className="flex-shrink-0 border-t border-gray-200 p-2 bg-white">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
          placeholder="Ask Genie…"
          rows={3}
          className="w-full text-xs rounded-md border border-gray-300 bg-white text-gray-900 placeholder-gray-400 px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        <div className="flex justify-end mt-2">
          <button
            type="button"
            onClick={() => void sendMessage()}
            disabled={sending || !input.trim()}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

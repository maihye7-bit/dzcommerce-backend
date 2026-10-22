import { useEffect, useRef } from "react";
import { useConversationTranscript } from "@/hooks/useConversations";
import { Button } from "@/components/ui/button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";

interface ConversationTranscriptDrawerProps {
  conversation: {
    id: string;
    customer_id: string;
  } | null;
  onClose: () => void;
}

export function ConversationTranscriptDrawer({
  conversation,
  onClose,
}: ConversationTranscriptDrawerProps) {
  const transcriptQuery = useConversationTranscript(
    conversation?.id ?? null,
  );
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (conversation && transcriptQuery.data) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [conversation, transcriptQuery.data]);

  if (!conversation) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" role="presentation">
      <button
        className="absolute inset-0 cursor-default"
        aria-label="إغلاق المحادثة"
        onClick={onClose}
      />
      <aside
        aria-labelledby="conversation-title"
        aria-modal="true"
        className="relative flex h-full w-full max-w-xl flex-col bg-background shadow-xl"
        role="dialog"
        dir="rtl"
      >
        <div className="flex items-center justify-between border-b p-5">
          <div className="min-w-0">
            <h2 id="conversation-title" className="font-semibold">
              سجل المحادثة
            </h2>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {conversation.customer_id}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onClose}>
            إغلاق
          </Button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {transcriptQuery.isLoading && <LoadingSpinner />}
          {transcriptQuery.isError && (
            <ErrorMessage
              error={transcriptQuery.error}
              onRetry={() => void transcriptQuery.refetch()}
            />
          )}
          {transcriptQuery.data?.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              لا توجد رسائل في هذه المحادثة.
            </p>
          )}
          {transcriptQuery.data?.map((message) => {
            const isCustomer = message.role.toLowerCase() === "customer";
            return (
              <div
                key={message.id}
                className={`flex ${isCustomer ? "justify-start" : "justify-end"}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                    isCustomer
                      ? "bg-muted text-foreground"
                      : "bg-primary text-primary-foreground"
                  }`}
                >
                  <p className="mb-1 text-xs font-semibold opacity-75">
                    {isCustomer ? "العميل" : "المساعد"}
                  </p>
                  <p className="whitespace-pre-wrap text-sm">{message.content}</p>
                  <p className="mt-2 text-left text-[11px] opacity-70">
                    {new Date(message.created_at).toLocaleString("ar-DZ")}
                  </p>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </aside>
    </div>
  );
}

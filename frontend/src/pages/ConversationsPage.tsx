import { useState } from "react";
import { MessageCircle } from "lucide-react";
import { useConversations } from "@/hooks/useConversations";
import { ConversationTranscriptDrawer } from "@/components/ConversationTranscriptDrawer";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PaginationControls } from "@/components/PaginationControls";
import { Card, CardContent } from "@/components/ui/card";
import { useStoreId } from "@/hooks/useStoreId";
import type { Conversation } from "@/types/api";

const PAGE_SIZE = 20;

export function ConversationsPage() {
  const [page, setPage] = useState(1);
  const [selectedConversation, setSelectedConversation] =
    useState<Conversation | null>(null);
  const storeQuery = useStoreId();
  const conversationsQuery = useConversations({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  return (
    <section className="space-y-6" dir="rtl">
      <div>
        <p className="text-sm font-medium text-primary">تواصل العملاء</p>
        <h1 className="mt-2 text-3xl font-bold">المحادثات</h1>
      </div>
      {storeQuery.isError && (
        <ErrorMessage
          error={storeQuery.error}
          onRetry={() => void storeQuery.refetch()}
        />
      )}
      {(conversationsQuery.isLoading || storeQuery.isLoading) && (
        <LoadingSpinner label="جارٍ تحميل المحادثات..." />
      )}
      {conversationsQuery.isError && (
        <ErrorMessage
          error={conversationsQuery.error}
          onRetry={() => void conversationsQuery.refetch()}
        />
      )}
      {conversationsQuery.data?.items.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            <MessageCircle className="mx-auto mb-3 size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              لا توجد محادثات بعد.
            </p>
          </CardContent>
        </Card>
      )}
      {conversationsQuery.data &&
        conversationsQuery.data.items.length > 0 && (
          <Card>
            <div className="divide-y">
              {conversationsQuery.data.items.map((conversation) => (
                <button
                  key={conversation.id}
                  className="flex w-full items-start gap-4 p-5 text-right transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setSelectedConversation(conversation)}
                >
                  <span className="mt-1 rounded-full bg-primary/10 p-2 text-primary">
                    <MessageCircle size={18} aria-hidden="true" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">
                        العميل{" "}
                        {(
                          conversation.customer_external_id ??
                          conversation.customer_id
                        ).slice(0, 24)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {conversation.updated_at
                          ? new Date(conversation.updated_at).toLocaleString(
                              "ar-DZ",
                            )
                          : "—"}
                      </span>
                    </span>
                    <span className="mt-2 block truncate text-sm text-muted-foreground">
                      {conversation.channel} ·{" "}
                      {conversation.commerce_stage ?? conversation.status}
                    </span>
                    <span className="mt-1 block truncate text-sm text-muted-foreground">
                      {conversation.last_message_preview ||
                        "لا توجد معاينة للرسالة الأخيرة"}
                    </span>
                  </span>
                </button>
              ))}
            </div>
            <PaginationControls
              page={page}
              pageSize={PAGE_SIZE}
              total={conversationsQuery.data.total}
              onPageChange={setPage}
            />
          </Card>
        )}
      <ConversationTranscriptDrawer
        conversation={selectedConversation}
        onClose={() => setSelectedConversation(null)}
      />
    </section>
  );
}

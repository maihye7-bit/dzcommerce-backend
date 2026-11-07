import { useState } from "react";
import { LoaderCircle, MessageCircle, Trash2 } from "lucide-react";
import {
  useConversations,
  useDeleteConversation,
} from "@/hooks/useConversations";
import { ConversationTranscriptDrawer } from "@/components/ConversationTranscriptDrawer";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PaginationControls } from "@/components/PaginationControls";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useStoreId } from "@/hooks/useStoreId";
import type { Conversation } from "@/types/api";

const PAGE_SIZE = 20;

export function ConversationsPage() {
  const [page, setPage] = useState(1);
  const [selectedConversation, setSelectedConversation] =
    useState<Conversation | null>(null);
  const [conversationToDelete, setConversationToDelete] =
    useState<Conversation | null>(null);
  const [deleteOrders, setDeleteOrders] = useState(false);
  const storeQuery = useStoreId();
  const { isOwner } = useCurrentUser();
  const conversationsQuery = useConversations({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });
  const deleteMutation = useDeleteConversation();
  const activeDraftItems = conversationToDelete?.active_draft_json?.items;
  const hasActiveDraft =
    Array.isArray(activeDraftItems) && activeDraftItems.length > 0;

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
                <div
                  key={conversation.id}
                  className="flex items-start gap-3 p-5 transition-colors hover:bg-muted/40"
                >
                  <button
                    className="flex min-w-0 flex-1 items-start gap-4 text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                  {isOwner && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label="حذف المحادثة"
                      onClick={() => {
                        setDeleteOrders(false);
                        setConversationToDelete(conversation);
                      }}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                      حذف
                    </Button>
                  )}
                </div>
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
      {conversationToDelete && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4"
          role="presentation"
        >
          <section
            aria-labelledby="delete-conversation-title"
            aria-modal="true"
            className="w-full max-w-lg space-y-5 rounded-xl border bg-background p-6 shadow-xl"
            dir="rtl"
            role="dialog"
          >
            <div>
              <h2
                id="delete-conversation-title"
                className="text-lg font-semibold"
              >
                حذف المحادثة
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                اختر ما تريد حذفه للمحادثة المحددة.
              </p>
            </div>
            <fieldset className="space-y-3">
              <legend className="sr-only">سياسة حذف الطلبات</legend>
              <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3">
                <input
                  checked={!deleteOrders}
                  className="mt-1"
                  disabled={deleteMutation.isPending}
                  name="conversation-delete-policy"
                  onChange={() => setDeleteOrders(false)}
                  type="radio"
                />
                <span className="text-sm">
                  حذف المحادثة والرسائل فقط — الاحتفاظ بالطلبات.
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3">
                <input
                  checked={deleteOrders}
                  className="mt-1"
                  disabled={deleteMutation.isPending}
                  name="conversation-delete-policy"
                  onChange={() => setDeleteOrders(true)}
                  type="radio"
                />
                <span className="text-sm">
                  حذف المحادثة والرسائل والطلبات المرتبطة بها — بما فيها
                  المسودات والطلبات المعلّقة.
                </span>
              </label>
            </fieldset>
            {hasActiveDraft && (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-800">
                المسودة النشطة محفوظة داخل المحادثة وستُحذف معها. خيار
                الاحتفاظ يبقي صفوف الطلبات المسجلة فقط.
              </p>
            )}
            {deleteOrders && (
              <p
                className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
                role="alert"
              >
                تحذير: حذف الطلبات نهائي ولا يمكن التراجع عنه.
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="outline"
                disabled={deleteMutation.isPending}
                onClick={() => setConversationToDelete(null)}
              >
                إلغاء
              </Button>
              <Button
                variant="destructive"
                disabled={deleteMutation.isPending}
                aria-busy={deleteMutation.isPending}
                onClick={() =>
                  deleteMutation.mutate(
                    {
                      conversationId: conversationToDelete.id,
                      deleteOrders,
                    },
                    {
                      onSuccess: () => {
                        setConversationToDelete(null);
                        if (
                          selectedConversation?.id === conversationToDelete.id
                        ) {
                          setSelectedConversation(null);
                        }
                        if (
                          page > 1 &&
                          conversationsQuery.data?.items.length === 1
                        ) {
                          setPage((currentPage) => currentPage - 1);
                        }
                      },
                    },
                  )
                }
              >
                {deleteMutation.isPending ? (
                  <>
                    <LoaderCircle
                      className="animate-spin"
                      size={15}
                      aria-hidden="true"
                    />
                    جارٍ الحذف...
                  </>
                ) : (
                  "تأكيد الحذف"
                )}
              </Button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/context/useAuth";
import { useStoreId } from "@/hooks/useStoreId";
import type {
  Conversation,
  ConversationPreview,
  Message,
  PaginatedResponse,
} from "@/types/api";

interface Pagination {
  limit: number;
  offset: number;
}

export function useConversations({ limit, offset }: Pagination) {
  const { token } = useAuth();
  const storeQuery = useStoreId();
  const storeId = storeQuery.data?.id;

  return useQuery({
    queryKey: ["dashboard", "conversations", storeId, limit, offset],
    queryFn: async () => {
      const [pageResponse, previewResponse] = await Promise.all([
        api.get<PaginatedResponse<Conversation>>(
          "/api/dashboard/conversations",
          { params: { store_id: storeId, limit, offset } },
        ),
        api.get<ConversationPreview[]>("/api/conversations/", {
          params: { limit: 100 },
        }),
      ]);
      const previews = new Map(
        previewResponse.data.map((conversation) => [
          conversation.id,
          conversation,
        ]),
      );
      return {
        ...pageResponse.data,
        items: pageResponse.data.items.map((conversation) => ({
          ...conversation,
          customer_external_id: previews.get(conversation.id)
            ?.customer_external_id,
          last_message_preview: previews.get(conversation.id)
            ?.last_message_preview,
        })),
      };
    },
    enabled: Boolean(token && storeId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useConversationTranscript(conversationId: string | null) {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["dashboard", "conversation-transcript", conversationId],
    queryFn: async () => {
      const response = await api.get<Message[]>(
        `/api/conversations/${conversationId}/messages`,
      );
      return response.data;
    },
    enabled: Boolean(token && conversationId),
    staleTime: 5 * 60 * 1000,
  });
}

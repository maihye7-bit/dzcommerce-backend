export interface OrderItem {
  id: string;
  product_id: string | null;
  product_name?: string | null;
  variant_id: string | null;
  variant_name?: string | null;
  quantity: number;
  unit_price: number;
  line_total?: number;
}

export interface Order {
  id: string;
  store_id: string;
  customer_id: string | null;
  conversation_id: string | null;
  status: string;
  subtotal: number;
  shipping_cost: number;
  total: number;
  wilaya: string | null;
  shipping_address?: string | null;
  created_at: string | null;
  items: OrderItem[];
}

export interface Conversation {
  id: string;
  store_id: string;
  customer_id: string;
  customer_external_id?: string;
  channel: string;
  last_message_preview?: string;
  status: string;
  commerce_stage: string | null;
  metadata_json: Record<string, unknown>;
  active_draft_json: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface DashboardStats {
  total_orders: number;
  total_revenue: number;
  low_stock_items_count: number;
  orders_today: number;
}

export interface TopProduct {
  product_id: string;
  product_name: string;
  variant_name: string | null;
  count: number;
  revenue: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface StoreSummary {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  role: "owner" | "staff";
}

export interface Product {
  id: string;
  store_id: string;
  name: string;
  description: string | null;
  sku: string | null;
  price: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductCreatePayload {
  name: string;
  description: string | null;
  sku: string | null;
  price: number;
  initial_quantity: number;
}

export interface ProductUpdatePayload {
  name: string;
  description: string | null;
  sku: string | null;
  price: number;
}

export interface InventoryVariant {
  id: string;
  name: string;
  sku: string | null;
  quantity: number;
  inventory_id: string | null;
}

export interface InventoryProduct {
  id: string;
  name: string;
  base_price: number;
  variants: InventoryVariant[];
}

export interface InventoryUpdatePayload {
  quantity: number;
}

export interface StoreProfile {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
}

export interface StoreUpdatePayload {
  name: string;
}

export interface ConversationPreview {
  id: string;
  customer_external_id: string;
  channel: string;
  last_message_preview: string;
  updated_at: string;
}

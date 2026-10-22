import os

base_path = "src/app/(dashboard)"

pages_to_create = {
    "customers": """export default function CustomersPage() {
  return <div className="p-8"><h1 className="text-2xl font-bold">العملاء</h1><p>قريباً...</p></div>
}""",
    "products": """export default function ProductsPage() {
  return <div className="p-8"><h1 className="text-2xl font-bold">المنتجات</h1><p>قريباً...</p></div>
}""",
    "analytics": """export default function AnalyticsPage() {
  return <div className="p-8"><h1 className="text-2xl font-bold">التحليلات</h1><p>قريباً...</p></div>
}"""
}

for folder, content in pages_to_create.items():
    dir_path = os.path.join(base_path, folder)
    file_path = os.path.join(dir_path, "page.tsx")
    
    os.makedirs(dir_path, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ Created: {file_path}")

print("\n🎉 Missing pages fixed!")

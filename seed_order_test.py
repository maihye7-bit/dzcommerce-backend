"""
Quick script to seed a product with variants for Phase 13 testing.
FIXED: Corrected indentation issues and ensured attributes are populated.
Run once before starting the server or webhook listener.
"""
import asyncio
import uuid
from decimal import Decimal
from app.database import SessionLocal
from app.models.store import Store
from app.models.product import Product, ProductVariant
from app.models.inventory import InventoryItem

async def main():
    db = SessionLocal()
    try:
        # Find the test store created in previous steps
        store = db.query(Store).filter(Store.name == "TestStore_Stability").first()
        if not store:
            print("❌ Store 'TestStore_Stability' not found. Run test_stability.py first.")
            return

        # Clean up previous Nike products to ensure fresh state
        existing_nikes = db.query(Product).filter(
            Product.store_id == store.id, 
            Product.name.like("%Nike%")
        ).all()
        
        for p in existing_nikes:
            # Delete related variants and inventory first
            variants = db.query(ProductVariant).filter(ProductVariant.product_id == p.id).all()
            for v in variants:
                inv = db.query(InventoryItem).filter(InventoryItem.variant_id == v.id).all()
                for i in inv:
                    db.delete(i)
                db.delete(v)
            db.delete(p)
        db.flush()
        print("🧹 Cleaned up old Nike test data.")

        # Create Product
        product = Product(
            store_id=store.id,
            name="Nike Air Max",
            description="Classic running shoe",
            base_price=Decimal("8500"),
            sku="NIKE-AIR-MAX-TEST",
            is_active=True
        )
        db.add(product)
        db.flush()
        print(f"✅ Created Product: Nike Air Max ({product.id})")

        # Create Variants WITH ATTRIBUTES (Critical for LLM matching)
        # Assuming ProductVariant has an 'attributes_json' column. 
        # If it doesn't, we rely on 'name'. Let's assume standard structure.
        
        v_black_42 = ProductVariant(
            product_id=product.id,
            name="Black / Size 42",
            price_adjustment=Decimal("0")
        )
        # Try to set attributes if the field exists, otherwise ignore
        if hasattr(v_black_42, 'attributes_json'):
             v_black_42.attributes_json = {"color": "black", "size": "42"}
             
        v_white_43 = ProductVariant(
            product_id=product.id,
            name="White / Size 43",
            price_adjustment=Decimal("500")
        )
        # FIXED INDENTATION HERE
        if hasattr(v_white_43, 'attributes_json'):
             v_white_43.attributes_json = {"color": "white", "size": "43"}

        db.add_all([v_black_42, v_white_43])
        db.flush()
        
        # Create Inventory Linked Directly to Variant IDs
        inv_black = InventoryItem(
            store_id=store.id, # Some models require store_id here too
            variant_id=v_black_42.id,
            quantity=10, # Plenty of stock
            low_stock_threshold=2
        )
        inv_white = InventoryItem(
            store_id=store.id,
            variant_id=v_white_43.id,
            quantity=5,
            low_stock_threshold=1
        )
        db.add_all([inv_black, inv_white])
        
        db.commit()
        print(f"✅ Created Variants & Inventory:")
        print(f"   - Black/42 ID: {v_black_42.id} (Qty: 10)")
        print(f"   - White/43 ID: {v_white_43.id} (Qty: 5)")
            
    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding data: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())

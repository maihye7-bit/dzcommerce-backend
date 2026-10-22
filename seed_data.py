"""
Seed script to create initial Store for testing Webhooks.
Simplified to avoid dependency on specific security utils if names differ.
"""
import uuid
from app.database import SessionLocal, engine
from app.models.store import Store
from app.models.user import User
# Try importing hash function, fallback to simple placeholder if not found
try:
    from app.core.security import hash_password as get_password_hash
except ImportError:
    try:
        from app.core.security import get_password_hash
    except ImportError:
        # Fallback: Define a dummy hasher if neither exists (for seeding only)
        def get_password_hash(password):
            return "dummy_hash_for_seed_only" 

def seed_database():
    db = SessionLocal()
    try:
        # 1. Check if Store already exists
        existing_store = db.query(Store).first()
        if existing_store:
            print(f"✅ Store '{existing_store.name}' already exists. Skipping.")
            return

        # 2. Create a Dummy Admin User (Optional but good for completeness)
        admin_email = "admin@dzcommerce.test"
        existing_user = db.query(User).filter(User.email == admin_email).first()
        
        if not existing_user:
            hashed_pw = get_password_hash("password123") 
            admin_user = User(
                id=uuid.uuid4(),
                email=admin_email,
                full_name="System Admin",
                hashed_password=hashed_pw,
                is_active=True,
                is_superuser=True
            )
            db.add(admin_user)
            db.flush()
            print(f"👤 Created Admin User: {admin_email}")
        else:
            admin_user = existing_user

        # 3. Create the Test Store
        test_store = Store(
            id=uuid.uuid4(),
            name="DzCommerce Test Shop",
            slug="test-shop",
            is_active=True
        )
        db.add(test_store)
        db.flush()
        print(f"🏪 Created Test Store: {test_store.name} (ID: {test_store.id})")

        db.commit()
        print("✨ Database seeded successfully!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding database: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()

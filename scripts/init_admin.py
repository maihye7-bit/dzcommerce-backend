"""
Initialize Super Admin User in Railway Database.
Uses bcrypt directly to ensure compatibility regardless of project-specific wrappers.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import bcrypt  # Direct import of the library used by passlib/bcrypt

# Add project root to path to allow imports from 'app'
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load environment variables
load_dotenv()

from app.database import SessionLocal
from app.models.user import User

# Configuration
ADMIN_EMAIL = "admin@dzcommerce.com" 
ADMIN_PASSWORD = "SecurePass123!"   # Change this to your desired strong password
IS_SUPER_ADMIN = True

def get_bcrypt_hash(password: str) -> str:
    """Generates a bcrypt hash compatible with standard FastAPI/SQLAlchemy setups."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def init_admin():
    db: Session = SessionLocal()
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        
        # Generate the hash using the direct method
        hashed_pw = get_bcrypt_hash(ADMIN_PASSWORD)
        
        if existing_user:
            print(f"⚠️ User '{ADMIN_EMAIL}' already exists.")
            # Update password and permissions
            # NOTE: Adjust attribute names below if your User model uses different names 
            # (e.g., 'password_hash' instead of 'hashed_password')
            existing_user.hashed_password = hashed_pw 
            existing_user.is_super_admin = IS_SUPER_ADMIN
            existing_user.is_superuser = IS_SUPER_ADMIN
            existing_user.is_active = True
            db.commit()
            print("✅ Updated existing user with new password and admin rights.")
        else:
            # Create new user
            print(f"🆕 Creating new Super Admin user: {ADMIN_EMAIL}")
            new_user = User(
                email=ADMIN_EMAIL,
                hashed_password=hashed_pw, # Ensure this matches your DB column name
                is_super_admin=IS_SUPER_ADMIN,
                is_superuser=IS_SUPER_ADMIN,
                is_active=True,
                name="Super Admin"
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            print(f"🎉 Created new Super Admin user: {ADMIN_EMAIL}")
            
    except Exception as e:
        db.rollback()
        print(f"❌ Error initializing admin: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    print("Initializing Super Admin on Railway DB...")
    init_admin()
    print("Done.")

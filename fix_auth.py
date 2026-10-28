import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password

def setup_admin():
    email = 'admin@example.com'
    password = 'admin123'
    db = SessionLocal()
    try:
        normalized = email.strip().casefold()
        user = db.query(User).filter(User.email == normalized).first()
        if not user:
            user = User(
                email=normalized,
                hashed_password=hash_password(password),
                full_name='Super Admin',
                is_active=True,
                is_superuser=True,
                is_super_admin=True
            )
            db.add(user)
            db.commit()
            print(f'Created new Super Admin user {normalized}.')
        else:
            user.hashed_password = hash_password(password)
            user.is_super_admin = True
            user.is_superuser = True
            user.is_active = True
            db.commit()
            print(f'Successfully updated user {normalized} as Super Admin.')
    except Exception as e:
        db.rollback()
        print(f'Error setting up admin: {e}')
    finally:
        db.close()

setup_admin()

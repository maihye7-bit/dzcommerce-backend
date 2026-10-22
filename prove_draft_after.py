from app.database import SessionLocal
from app.models import Conversation
import json
db = SessionLocal()
c = db.query(Conversation).order_by(Conversation.updated_at.desc()).first()
print('=' * 60)
print('STEP 2: DRAFT AFTER CONFIRMATION')
print('=' * 60)
print('DRAFT_IS_NONE:', c.active_draft_json is None)
print('DRAFT:', c.active_draft_json)
print('METADATA_HAS_CONFIRMED:', (c.metadata_json or {}).get('has_confirmed_order'))
print('=' * 60)
db.close()

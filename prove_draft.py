from app.database import SessionLocal
from app.models import Conversation
import json
db = SessionLocal()
c = db.query(Conversation).order_by(Conversation.updated_at.desc()).first()
draft = c.active_draft_json
print('=' * 60)
print('STEP 1: DRAFT AFTER CREATION (before confirmation)')
print('=' * 60)
print('CONV_ID:', c.id)
print('DRAFT_TYPE:', type(draft).__name__)
print('DRAFT_IS_NONE:', draft is None)
if draft is not None:
    print('DRAFT_KEYS:', list(draft.keys()) if isinstance(draft, dict) else 'not a dict')
    print('DRAFT_FULL:', json.dumps(draft, ensure_ascii=False, indent=2, default=str))
else:
    print('❌ FAIL: Draft is None — persistence failed!')
print('=' * 60)
db.close()

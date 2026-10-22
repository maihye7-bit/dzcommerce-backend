from app.database import SessionLocal
from app.models import Conversation
import json
db = SessionLocal()
c = db.query(Conversation).order_by(Conversation.updated_at.desc()).first()
m = c.metadata_json or {}
print('=' * 60)
print('CURRENT STATE:')
print('=' * 60)
print('COMMERCE_STAGE:', m.get('commerce_stage'))
print('LAST_Q:', m.get('last_question_type'))
print('LAST_INTENT:', m.get('last_intent'))
print('SELECTED_PRODUCT:', m.get('selected_product_name'))
print('LAST_SEARCHED:', m.get('last_searched_product'))
print('=' * 60)
db.close()

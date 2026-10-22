from app.database import SessionLocal
from app.models import Conversation, Message
db = SessionLocal()
conv = db.query(Conversation).order_by(Conversation.updated_at.desc()).first()
if conv:
    print('Deleting conversation:', conv.id)
    # حذف الرسائل المرتبطة ولا (ذا كان هناك قيد FK)
    msgs = db.query(Message).filter(Message.conversation_id == conv.id).all()
    for m in msgs:
        db.delete(m)
    # حذف المحادثة نفسها
    db.delete(conv)
    db.commit()
    print('✅ Conversation deleted — next message will start fresh!')
else:
    print('No conversations found')
db.close()

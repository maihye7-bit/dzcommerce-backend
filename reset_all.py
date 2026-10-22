from app.database import SessionLocal
from app.models import Conversation, Message

db = SessionLocal()
msgs = db.query(Message).count()
convs = db.query(Conversation).count()

for m in db.query(Message).all():
    db.delete(m)
for c in db.query(Conversation).all():
    db.delete(c)

db.commit()
print(f'✅ Clean slate: {convs} conversations + {msgs} messages deleted')
db.close()

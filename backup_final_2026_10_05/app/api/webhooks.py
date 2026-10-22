"""
Webhook endpoints - Integrated with ConversationEngine & Tool Registry.
Phase 12-D + Idempotency Fix: Robust duplicate webhook handling.
CRITICAL: Implements safe INSERT-or-SKIP logic for incoming messages.
"""
import json
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.customer import Customer
from app.models.store import Store
# Imports for Phase 12-D Integration
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.qwen_provider import QwenLLMProvider
from app.agent.tools import tool_registry

router = APIRouter(prefix="/webhooks", tags=["social-webhooks"])

# Initialize Components Once at Module Load Time
_llm_provider = QwenLLMProvider()
_engine = ConversationEngine(llm_provider=_llm_provider, tool_registry=tool_registry)


@router.post("/meta")
async def meta_webhook(request: Request, db: Session = Depends(get_db)):
    body_bytes = await request.body()
    try:
        payload_str = body_bytes.decode("utf-8")
        payload = json.loads(payload_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    entries = payload.get("entry", [])
    processed_count = 0
    skipped_duplicates = 0

    print("\n" + "=" * 60)
    print("📨 RECEIVED META WEBHOOK EVENT (AGENT PROCESSING)")
    print("=" * 60)

    for entry in entries:
        messaging_events = entry.get("messaging", [])
        for event in messaging_events:
            sender_id = event["sender"]["id"]
            
            if "message" not in event or "text" not in event["message"]:
                continue

            text = event["message"]["text"]
            external_mid = event.get("message", {}).get("mid")

            # --- SAFETY NET: Ensure clean transaction state before starting ---
            try:
                if db.in_transaction():
                    db.rollback()
            except Exception:
                pass

            ai_reply = ""
            conv_id_for_log = None

            try:
                # 1. Identify Store (Trusted Context Source)
                store = db.query(Store).filter(Store.is_active == True).first()
                if not store:
                    print("⚠️ No active store found.")
                    continue

                # 2. Identify/Create Customer
                customer = db.query(Customer).filter(
                    Customer.phone == sender_id,
                    Customer.store_id == store.id
                ).first()

                if not customer:
                    customer = Customer(
                        store_id=store.id,
                        name=f"FB User {sender_id[-6:]}",
                        phone=sender_id,
                        email=None,
                    )
                    db.add(customer)
                    db.flush()

                # 3. Identify/Create Active Conversation
                conv = db.query(Conversation).filter(
                    Conversation.customer_id == customer.id,
                    Conversation.status == ConversationStatus.ACTIVE
                ).first()

                if not conv:
                    conv = Conversation(
                        store_id=store.id,
                        customer_id=customer.id,
                        channel="facebook",
                        status=ConversationStatus.ACTIVE,
                    )
                    db.add(conv)
                    db.flush()

                conv_id_for_log = conv.id

                # ============================================================
                # IDEMPOTENCY CHECK: Save Incoming User Message Safely
                # Strategy: Attempt INSERT. If UNIQUE constraint fails, 
                # it means this message was already received/processed.
                # We SKIP AI processing to prevent double-charging/double-ordering.
                # ============================================================
                
                is_duplicate = False
                
                if external_mid:
                    # Pre-check: Does a message with this ID already exist?
                    existing_msg = db.query(Message).filter(
                        Message.external_message_id == external_mid
                    ).first()
                    
                    if existing_msg:
                        print(f"♻️ Duplicate detected (pre-check): mid={external_mid}. Skipping AI processing.")
                        is_duplicate = True
                        skipped_duplicates += 1
                    else:
                        # Not found in pre-check. Try to insert.
                        # Race condition protection relies on DB UNIQUE constraint.
                        user_msg = Message(
                            conversation_id=conv.id,
                            role=MessageRole.CUSTOMER,
                            content=text,
                            external_message_id=external_mid,
                        )
                        db.add(user_msg)
                        
                        try:
                            db.commit() # Commit immediately to secure the slot
                        except IntegrityError:
                            # RACE CONDITION HANDLED: Another thread/process inserted it first.
                            db.rollback() # CRITICAL: Clear aborted session state
                            print(f"♻️ Duplicate detected (race-condition): mid={external_mid}. Rolled back and skipping.")
                            is_duplicate = True
                            skipped_duplicates += 1
                else:
                    # No external ID provided (unlikely for Meta, but handle gracefully)
                    # Treat as new message without deduplication capability
                    user_msg = Message(
                        conversation_id=conv.id,
                        role=MessageRole.CUSTOMER,
                        content=text,
                        external_message_id=None,
                    )
                    db.add(user_msg)
                    db.commit()

                # If duplicate, skip the rest of the processing for this event
                if is_duplicate:
                    continue

                # 5. Process via Engine (Only for NEW messages)
                result = await _engine.process_message(
                    db=db,
                    store_id=store.id,
                    customer_id=customer.id,
                    conversation_id=conv.id,
                    channel="facebook",
                    user_message=text,
                )
                ai_reply = result.get("response", "")

                # Log tool usage
                if result.get("tool_calls"):
                    tools_used = [tc['name'] for tc in result['tool_calls']]
                    print(f"🔧 Tools Executed: {tools_used}")

            except Exception as engine_err:
                print(f"❌ Engine/AI Error: {str(engine_err)}")
                # CRITICAL: Rollback to clear any poisoned session state
                try:
                    db.rollback()
                except Exception:
                    pass
                # Set fallback reply ONLY if we haven't already committed the user msg
                # Note: If user msg was committed successfully above, we still want to reply.
                ai_reply = "عذراَ، حدث خطأ تقني مؤقت. سأحاول مساعدتك لاحقاَ."

            # 6. Save Bot Reply (With Recovery Logic)
            if ai_reply and conv_id_for_log:
                try:
                    # Check if session is usable again after potential rollback
                    if db.in_transaction():
                        db.rollback()

                    bot_msg = Message(
                        conversation_id=conv_id_for_log,
                        role=MessageRole.AGENT,
                        content=ai_reply,
                        # Do NOT set external_message_id for bot replies unless tracking them specifically
                    )
                    db.add(bot_msg)
                    db.commit()
                    print(f"💾 Saved Conv {conv_id_for_log}: User='{text[:20]}...' | Bot='{ai_reply[:20]}...'")
                    processed_count += 1
                except Exception as save_err:
                    print(f"❌ Failed to save bot reply even after recovery: {save_err}")

    print(f"✅ Processed: {processed_count} | ♻️ Skipped Duplicates: {skipped_duplicates}")
    print("=" * 60 + "\n")
    return {"status": "processed", "count": processed_count, "skipped": skipped_duplicates}


@router.get("/meta")
@router.get("/whatsapp")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    expected_token = os.getenv("FACEBOOK_VERIFY_TOKEN", "dzcommerce_test_2026")

    if mode == "subscribe" and token == expected_token:
        return int(challenge) if challenge and challenge.isdigit() else challenge
    raise HTTPException(status_code=403, detail="Invalid verification token")

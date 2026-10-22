"""
Manual Test Script for Phase 13 Order Flow + Idempotency Verification.
Generates unique IDs automatically to allow repeated runs.
Includes explicit duplicate delivery test.
"""
import requests
import json
import time
import uuid

BASE_URL = "http://localhost:8000/webhooks/meta"
HEADERS = {"Content-Type": "application/json; charset=utf-8"}

def send_message(text, mid=None):
    """Constructs and sends a Meta Webhook payload."""
    # Auto-generate unique MID if not provided
    if mid is None:
        mid = f"AUTO_{uuid.uuid4().hex[:8]}"
        
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "PAGE_ID_TEST",
                "time": int(time.time()),
                "messaging": [
                    {
                        "sender": {"id": "USER_FB_123"},
                        "recipient": {"id": "PAGE_ID_TEST"},
                        "timestamp": int(time.time()),
                        "message": {
                            "mid": mid,
                            "text": text
                        }
                    }
                ]
            }
        ]
    }
    
    print(f"\n📤 Sending: '{text}' (MID: {mid})")
    try:
        response = requests.post(
            BASE_URL, 
            headers=HEADERS, 
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8')
        )
        
        if response.status_code == 200:
            resp_json = response.json()
            skipped = resp_json.get("skipped", 0)
            if skipped > 0:
                print(f"   ♻️ Server reported {skipped} duplicate(s) skipped.")
            else:
                print("   ✅ Server Received & Processed New Message.")
        else:
            print(f"   ❌ Error: {response.status_code} - {response.text[:100]}")
            
    except Exception as e:
        print(f"   💥 Connection Failed: {e}")
        
    time.sleep(5) # Wait for async processing logs

if __name__ == "__main__":
    print("="*50)
    print("STARTING MANUAL ORDER FLOW TEST (WITH IDEMPOTENCY CHECK)")
    print("Make sure 'uvicorn app.main:app --reload' is running!")
    print("="*50)
    
    # Generate a fixed MID for the duplication test
    DUP_MID = f"DUP_TEST_{uuid.uuid4().hex[:6]}"
    
    # Step 1: Search
    send_message("سلام، عندكم Nike؟")
    
    # Step 2: Select Variant
    send_message("نحب الأسود حجم 42")
    
    # Step 3: Create Draft
    send_message("ديرلي طلب")
    
    # Step 4: Confirm
    send_message("أكد")
    
    # ==========================================
    # STEP 5: IDEMPOTENCY VERIFICATION TEST
    # Send the SAME message twice using the same MID
    # ==========================================
    print("\n" + "-"*50)
    print("🔄 TESTING DUPLICATE DELIVERY HANDLING...")
    print("-"*50)
    
    # First delivery (Should process normally)
    send_message("اختبار التكرار", mid=DUP_MID)
    
    # Second delivery (Same MID, should be SKIPPED silently)
    send_message("اختبار التكرار", mid=DUP_MID)
    
    print("\n" + "="*50)
    print("TEST SEQUENCE FINISHED.")
    print("Check Uvicorn Logs:")
    print("1. Normal messages should show 'Tools Executed'.")
    print("2. The second 'DUP_TEST' message should show 'Duplicate detected... Skipping'.")
    print("3. NO errors like UniqueViolation or InFailedSqlTransaction.")
    print("="*50)

import sys
sys.stdout.reconfigure(encoding='utf-8')

from app.agent.classifier import ConversationClassifier, INTENT_PRICE_INQUIRY, INTENT_AMBIGUOUS, INTENT_GENERAL_CHAT

# Test price inquiry messages
test_messages = [
    ("بشحال?", None),  # Arabic, no context
    ("Combien coûte ce produit？", None),  # Mixed French/Arabic, no context
    ("بشحال?", "EMPTY"),  # Arabic, EMPTY context
    ("Combien coûte ce produit？", "EMPTY"),  # Mixed, EMPTY context
]

for msg, commerce_stage in test_messages:
    result = ConversationClassifier.classify(
        msg,
        commerce_stage=commerce_stage,
        selected_product_name=None,
    )
    print(f'Message: "{msg}"')
    print(f'  commerce_stage: {commerce_stage}')
    print(f'  Intent: {result.intent}')
    print(f'  Confidence: {result.confidence}')
    print(f'  Tools needed: {result.commerce_tools_needed}')
    print(f'  Clarification needed: {result.clarification_needed}')
    print()
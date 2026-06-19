from src.classifier import classify_customer_persona

samples = [
    "Can you explain the API authentication failure and provide header requirements?",
    "I've tried everything and nothing works! Your app keeps failing and I need this fixed now!",
    "How does this issue affect operations, and when can we expect resolution?"
]

for msg in samples:
    result = classify_customer_persona(msg)
    print("\nMESSAGE:", msg)
    print("RESULT:", result)
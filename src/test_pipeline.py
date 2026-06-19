from src.rag_pipeline import RAGPipeline

rag = RAGPipeline()

queries = [
    "How do I reset my password?",
    "I keep getting signed out of the website",
    "Webhook delivery failed",
    "I want a refund immediately",
    "How does the outage affect operations?"
]

for query in queries:

    print("\n" + "="*60)
    print("QUERY:", query)

    results = rag.retrieve_context(query)

    for r in results:
        print(f"\nSOURCE: {r['source']}")
        print(f"SCORE: {r['score']}")
        print(r['text'][:150])
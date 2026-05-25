"""Mock retriever for tutor context."""


class Retriever:
    def retrieve(self, query: str) -> list[str]:
        return [
            f"Core concept requested: {query}",
            "Use a simple definition, example, and step-by-step explanation.",
        ]

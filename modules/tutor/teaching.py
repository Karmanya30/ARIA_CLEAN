"""Simple teaching helpers."""


class TeachingAgent:
    def teach(self, docs: list[str]) -> dict[str, list[str]]:
        return {
            "outline": docs,
            "style": ["simple explanation", "worked example", "quick recap"],
        }

    def generate_quiz(self, lesson: dict[str, list[str]]) -> list[dict[str, str]]:
        return [
            {
                "question": "What is the main idea?",
                "answer": "The key concept explained in the lesson.",
            }
        ]

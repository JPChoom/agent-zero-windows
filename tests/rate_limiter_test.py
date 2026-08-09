
# Manual/dev script, not a pytest test: it makes a real live call to
# OpenRouter and has no assertions. Guarded behind __main__ so pytest
# collecting tests/ (matches *_test.py) doesn't execute it - previously
# this ran unconditionally at import time and failed collection for the
# whole suite whenever no OPENROUTER_API_KEY was configured.
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    import models

    provider = "openrouter"
    name = "deepseek/deepseek-r1"

    model = models.get_chat_model(
        provider=provider,
        name=name,
        model_config=models.ModelConfig(
            type=models.ModelType.CHAT,
            provider=provider,
            name=name,
            limit_requests=5,
            limit_input=15000,
            limit_output=1000,
        )
    )

    async def run():
        response, reasoning = await model.unified_call(
            user_message="Tell me a joke"
        )
        print("Response: ", response)
        print("Reasoning: ", reasoning)

    import asyncio
    asyncio.run(run())


if __name__ == "__main__":
    main()
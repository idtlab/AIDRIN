import os

from openai import OpenAI


openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_API_BASE")
aidrin_model = os.getenv("AIDRIN_MODEL", "google/gemini:latest")


def comment(description, base64_image):
    if openai_api_key:
        if openai_base_url:
            client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)
        else:
            client = OpenAI(api_key=openai_api_key)

        print("OpenAI client initialized successfully.")
    else:
        print("OPENAI_API_KEY environment variable not set.")

        return None

    response = client.chat.completions.create(
        model=aidrin_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are a statistician and data analyst expert. You a given a plot. "
                            "{description} Provide a short summary of they key observations for this "
                            "image in one sentence. Include a second sentence giving an insight if "
                            "this data were to be used by AI or ML."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                    },
                ],
            }
        ]
    )

    # TODO: move to logging
    print(f"({aidrin_model}): {response.choices[0].message.content}")

    return response.choices[0].message.content

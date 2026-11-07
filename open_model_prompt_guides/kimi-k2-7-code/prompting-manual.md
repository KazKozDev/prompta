# Kimi K2.7 Code — official prompting materials

Source: https://huggingface.co/moonshotai/Kimi-K2.7-Code/blob/74797c9c62378b951a1f6fcf5c4631024e9b8bef/README.md

Revision: `74797c9c62378b951a1f6fcf5c4631024e9b8bef`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: 5. Deployment (README line 149)

## 5. Deployment

> [!Note]
> You can access Kimi-K2.7-Code's API on https://platform.moonshot.ai and we provide OpenAI/Anthropic-compatible API for you.
Currently, Kimi-K2.7-Code is recommended to run on the following inference engines:
* vLLM
* SGLang
* KTransformers

Kimi-K2.7-Code has the same architecture as Kimi-K2.5/Kimi-K2.6, and the deployment method can be directly reused.

The version requirement for `transformers` is `>=4.57.1, <5.0.0`.

Deployment examples can be found in the [Model Deployment Guide](docs/deploy_guidance.md).


---

---

Source section: 6. Model Usage (README line 166)

## 6. Model Usage

The usage demos below demonstrate how to call our official API. Note that Kimi-K2.7-Code forces thinking and preserve_thinking as True.

For third-party APIs deployed with vLLM or SGLang, please note that:
> [!Note]
> - Chat with video content is an experimental feature and is only supported in our official API for now.
> 
> - The recommended `temperature` will be `1.0` for Thinking mode.
> 
> - The recommended `top_p` is `0.95`.
> 
> - Instant mode is not supported.


---

Source section: Chat Completion (README line 180)

### Chat Completion

This is a simple chat completion script which shows how to call K2.7-Code API in Thinking mode.

```python
import openai
import base64
import requests
def simple_chat(client: openai.OpenAI, model_name: str):
    messages = [
        {'role': 'system', 'content': 'You are Kimi, an AI assistant created by Moonshot AI.'},
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'which one is bigger, 9.11 or 9.9? think carefully.'}
            ],
        },
    ]
    response = client.chat.completions.create(
        model=model_name, messages=messages, stream=False, max_tokens=4096
    )
    print('====== Below is reasoning content in Thinking Mode ======')
    print(f'reasoning content: {response.choices[0].message.reasoning}')
    print('====== Below is response in Thinking Mode ======')
    print(f'response: {response.choices[0].message.content}')
```



---

Source section: Chat Completion with visual content (README line 208)

### Chat Completion with visual content

K2.7-Code supports Image and Video input.

The following example demonstrates how to call K2.7-Code API with image input:

```python
import openai
import base64
import requests

def chat_with_image(client: openai.OpenAI, model_name: str):
    url = 'https://huggingface.co/moonshotai/Kimi-K2.7-Code/resolve/main/figures/kimi-logo.png'
    image_base64 = base64.b64encode(requests.get(url).content).decode()
    messages = [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'Describe this image in detail.'},
                {
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/png;base64,{image_base64}'},
                },
            ],
        }
    ]

    response = client.chat.completions.create(
        model=model_name, messages=messages, stream=False, max_tokens=8192
    )
    print('====== Below is reasoning content in Thinking Mode ======')
    print(f'reasoning content: {response.choices[0].message.reasoning}')
    print('====== Below is response in Thinking Mode ======')
    print(f'response: {response.choices[0].message.content}')
```

The following example demonstrates how to call K2.7-Code API with video input:

```python
import openai
import base64
import requests

def chat_with_video(client: openai.OpenAI, model_name:str):
    url = 'https://huggingface.co/moonshotai/Kimi-K2.7-Code/resolve/main/figures/demo_video.mp4'
    video_base64 = base64.b64encode(requests.get(url).content).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text","text": "Describe the video in detail."},
                {
                    "type": "video_url",
                    "video_url": {"url": f"data:video/mp4;base64,{video_base64}"},
                },
            ],
        }
    ]

    response = client.chat.completions.create(model=model_name, messages=messages)
    print('====== Below is reasoning content in Thinking Mode ======')
    print(f'reasoning content: {response.choices[0].message.reasoning}')
    print('====== Below is response in Thinking Mode ======')
    print(f'response: {response.choices[0].message.content}')
```


---

Source section: Preserve Thinking (README line 274)

### Preserve Thinking
Kimi K2.7 Code forces `preserve_thinking` mode, which retains full reasoning content across multi-turn interactions and enhances performance in coding agent scenarios.

This feature is enabled by default and can't be disabled. The following example demonstrates how to call K2.7-Code API in `preserve_thinking` mode:

```python
def chat_with_preserve_thinking(client: openai.OpenAI, model_name: str):
    messages = [
        {
            "role": "user",
            "content": "Tell me three random numbers."
        },
        {
            "role": "assistant",
            "reasoning_content": "I'll start by listing five numbers: 473, 921, 235, 215, 222, and I'll tell you the first three.",
            # Some API (e.g. vLLM) may not support reasoning_content, you can try reasoning instead
            "content": "473, 921, 235"
        },
        {
            "role": "user",
            "content": "What are the other two numbers you have in mind?"
        }
    ]

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=False,
        max_tokens=4096,
    )
    # the assistant should mention 215 and 222 that appear in the prior reasoning content
    print(f"response: {response.choices[0].message.reasoning}")
    return response.choices[0].message.content

```


---

Source section: Interleaved Thinking and Multi-Step Tool Call (README line 310)

### Interleaved Thinking and Multi-Step Tool Call

K2.7-Code shares the same design of Interleaved Thinking and Multi-Step Tool Call as K2 Thinking. For usage example, please refer to the [K2 Thinking documentation](https://platform.moonshot.ai/docs/guide/use-kimi-k2-thinking-model#complete-example).

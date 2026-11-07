# Qwen3.8 2.4T A95B — official prompting materials

Source: https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B/blob/207bd685a7e3696cfaff12ded7c6a7ea0f88c996/README.md

Revision: `207bd685a7e3696cfaff12ded7c6a7ea0f88c996`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Quickstart (README line 332)

## Quickstart

For streamlined integration, we recommend using Qwen3.8 via APIs.


---

Source section: API Usage (README line 350)

### API Usage

> [!Important]
> Qwen3.8-2.4T-A95B is a text-only model that requires thinking mode for all interactions. Multimodal inputs are not supported, and thinking cannot be disabled. Every response will automatically begin with reasoning enclosed in `<think>\n...</think>\n\n` before the final output.

> [!Tip]
> We recommend using the following set of sampling parameters for generation:
> - `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repetition_penalty=1.0`
>
> Please note that the support for sampling parameters varies according to inference frameworks.


Qwen3.8 comes with official support for `reasoning_effort`, which can be used to adjust reasoning depth and control cost:  
  - `xhigh` (default): for complex tasks demanding thorough analysis
  - `medium`: balancing accuracy and speed
  - `low`: efficient reasoning optimizing for speed and cost

In addition, `preserve_thinking` is enabled by default for all workloads for the best out-of-the-box experience.



---

Source section: Chat Completions API (README line 370)

#### Chat Completions API

The Chat Completions API can be used with most inference frameworks, as well as [Qwen Cloud](https://www.qwencloud.com).
Before starting, make sure the OpenAI Python SDK is installed and the API key and the API base URL are configured, e.g.:
```shell
pip install -U openai

# Set the following accordingly
export OPENAI_BASE_URL='your-base-url'
export OPENAI_API_KEY='your-api-key'
```

##### Text-Only Input

```python
from openai import OpenAI
# Configured by environment variables
client = OpenAI()

messages = [{"role": "user", "content": "Write a Python function to merge two sorted linked lists."}]

completion = client.chat.completions.create(
    model="Qwen/Qwen3.8-2.4T-A95B",
    messages=messages,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": True,  # on by default; should not be turned off
            "preserve_thinking": True, # on by default
        },
    },
    reasoning_effort="xhigh",  # xhigh by default; supported levels are xhigh, medium, and low
    stream=True,
    stream_options={"include_usage": True},
)

reasoning_content = ""
answer_content = ""
is_answering = False
print("\n" + "=" * 20 + "Reasoning" + "=" * 20 + "\n")

for chunk in completion:
    if not chunk.choices:
        print("\nUsage:")
        print(chunk.usage)
        continue

    delta = chunk.choices[0].delta

    if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
        if not is_answering:
            print(delta.reasoning_content, end="", flush=True)
        reasoning_content += delta.reasoning_content

    if hasattr(delta, "content") and delta.content:
        if not is_answering:
            print("\n" + "=" * 20 + "Answer" + "=" * 20 + "\n")
            is_answering = True
        print(delta.content, end="", flush=True)
        answer_content += delta.content
```

> [!Note]
> If you are using APIs from Qwen Cloud, in addition to changing `model`, please pass `extra_body={"enable_thinking": True, "preserve_thinking": True}` instead of `extra_body={"chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True}}`.



---

Source section: Best Practices (README line 435)

## Best Practices

To achieve optimal performance, we recommend the following settings:

1. **Sampling Parameters**:  
   - We suggest using the following set of sampling parameters:  
     - `temperature=1.0`, `top_p=0.95`, `top_k=20`, `min_p=0.0`, `presence_penalty=0.0`, `repetition_penalty=1.0`  
   - For supported frameworks, you can adjust the `presence_penalty` parameter between 0 and 2 to reduce endless repetition. However, using a higher value may occasionally result in language mixing and a slight decrease in model performance.

2. **Adequate Output Length**: To optimize performance on agentic tasks, we recommend allocating sufficient output length to allow the model to generate detailed and comprehensive responses. For frameworks that support separate token limits for internal reasoning and final outputs, we suggest the following configuration within the 1M context length:
   - **Reasoning Content:** Set the maximum output length to 262,144 tokens.
   - **Final Response:** Set the maximum output length to 131,072 tokens.

   These settings provide the necessary capacity for complex reasoning while ensuring ample space for high-quality final deliverables.

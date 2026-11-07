# Nemotron 3.5 Super VL 120B A12B — official prompting materials

Source: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16/blob/fb0ee0bc6b3f70342afd8d84cb80dbadbaa8a1fe/README.md

Revision: `fb0ee0bc6b3f70342afd8d84cb80dbadbaa8a1fe`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Quick Start (README line 81)

## Quick Start

For efficient inference on DGX Spark or data center GPUs, see the [NVFP4 card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4). The example below serves BF16 on **4× H100**.

Nemotron 3.5 Super VL has configurable reasoning levels: off, on (medium), and on. Selecting on (medium) will reduce the number of tokens generated compared to on, but may impact accuracy. You can learn about the reasoning budget [here](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16#text-and-reasoning)!

Use Docker with NVIDIA GPU support and the `vllm/vllm-openai:nightly-3f1bcfd82bb2e93fcd364fc7a5491718453a77e2` or (`vllm/vllm-openai:v0.32.0`) image. If the model requires authentication, set `HF_TOKEN` in your shell before launching the container.

```bash
export MODEL=nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16
```

```bash
vllm serve $MODEL \
  --served-model-name nemotron-3.5-super-vl \
  --tensor-parallel-size 4 \
  --trust-remote-code \
  --gpu-memory-utilization=0.85 \
  --allowed-local-media-path=/ \
  --max-num-seqs=32 \
  --limit-mm-per-prompt '{"video": 1, "image": 1}' \
  --video-pruning-rate 0.5 \
  --media-io-kwargs '{"video": {"fps": 2, "num_frames": 256}}' \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser nemotron_v3 \
  --speculative_config.method mtp \
  --speculative_config.num_speculative_tokens 3
```

Wait for the server to finish loading the model and compiling kernels, then check the endpoint:

```bash
curl --fail http://localhost:8000/v1/models
```

All vLLM and SGLang examples use port `8000` and the API model name `nemotron-3.5-super-vl`. See the [API Client](#api-client) for text, image, video, and tool-calling examples.


---

Source section: Deployment Geography: Global (README line 183)

### Deployment Geography: Global


---

Source section: Quick Start Guide (README line 270)

## Quick Start Guide


---

Source section: Choose your deployment (README line 272)

### Choose your deployment

| Hardware | Runtime | Configuration |
|:---|:---|:---|
| 4× H100 | vLLM; SGLang | Text, image, and video; TP4; MTP with 5 draft tokens |
| 2× GB200 | vLLM; SGLang | Text, image, and video; TP2; MTP with 5 draft tokens |


---

Source section: Text and reasoning (README line 399)

#### Text and reasoning

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")
model = "nemotron-3.5-super-vl"

response = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Explain why binary search takes logarithmic time."}],
    temperature=1.0,
    top_p=0.95,
    max_tokens=16384,
    extra_body={"chat_template_kwargs": {"enable_thinking": True}},
)
choice = response.choices[0]
if choice.finish_reason == "length":
    raise RuntimeError("The response reached max_tokens; increase the output budget.")
print(choice.message.content)
```

Set `enable_thinking` to `False` to disable reasoning. For medium reasoning effort, use `{"enable_thinking": True, "medium_effort": True}`. Reasoning tokens and the final answer share the `max_tokens` budget.


---

Source section: Tool calling (README line 479)

#### Tool calling

The model requests a tool call; the application executes it and returns the result. This complete example uses a local inventory lookup.

```python
import json
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")
model = "nemotron-3.5-super-vl"
inventory = {"keyboard": 12, "monitor": 5}
tools = [{"type": "function", "function": {
    "name": "get_inventory",
    "description": "Return the inventory count for a product.",
    "parameters": {
        "type": "object",
        "properties": {"product": {"type": "string", "enum": ["keyboard", "monitor"]}},
        "required": ["product"],
        "additionalProperties": False,
    },
}}]
messages = [{"role": "user", "content": "How many keyboards are in stock?"}]

def complete(history, tool_choice="auto"):
    response = client.chat.completions.create(
        model=model,
        messages=history,
        tools=tools,
        tool_choice=tool_choice,
        temperature=1.0,
        top_p=0.95,
        max_tokens=16384,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError("The response was truncated; increase max_tokens.")
    return choice.message

message = complete(messages)
messages.append(message.model_dump(exclude_none=True))
if not message.tool_calls:
    print(message.content)
else:
    for call in message.tool_calls:
        arguments = json.loads(call.function.arguments)
        if (call.function.name != "get_inventory"
                or not isinstance(arguments, dict)
                or set(arguments) != {"product"}
                or not isinstance(arguments["product"], str)
                or arguments["product"] not in inventory):
            raise ValueError("Invalid inventory tool call")
        product = arguments["product"]
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps({"product": product, "count": inventory[product]}),
        })
    print(complete(messages, tool_choice="none").content)
```


---

Source section: Inference (README line 988)

## Inference

* **Acceleration Engine:** PyTorch

* **Test Hardware:**
    * NVIDIA Hopper
        * H100
        * H200
    * NVIDIA Grace Blackwell
        * GB200
        * GB300
    * NVIDIA Blackwell
        * B200
        * B300

The deployment examples above provide configurations for NVIDIA Hopper and Blackwell systems. Choose the precision, context length, and concurrency appropriate for the application and available memory.

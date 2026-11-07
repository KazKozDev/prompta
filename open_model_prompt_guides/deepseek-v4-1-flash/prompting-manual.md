# DeepSeek V4.1 Flash 1017 — official prompting materials

Source: https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/README.md

Revision: `1bae0e1088993b9b82de08f59de5be5a34e42170`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Prompt Encoding (README line 67)

## Prompt Encoding

This release does not include a Jinja-format chat template. The [`encoding`](encoding/README.md) folder contains a self-contained Python reference implementation (`encoding.py`) with test cases for multi-turn conversations, tool calling, thinking mode, numeric reasoning effort, mid-conversation system messages, and interleaved image content.

For production use, we additionally release [deepseek-recipe](https://github.com/deepseek-ai/deepseek-recipe), a set of Rust libraries with Python bindings that provides the same prompt format as a maintained, protocol-aware toolkit. It converts Messages, Chat Completions, and Responses API requests into the Conversation format, encodes them into DeepSeek V4 and V4.1 prompts or token IDs, and parses model output back into complete or streamed responses — covering thinking, tool calls, images, and generation settings. Model inference, tool execution, and HTTP transport are left to the caller.


---

Source section: Minimal Inference (README line 73)

## Minimal Inference

Please refer to the [`inference`](inference/README.md) folder for instructions on weight conversion and running inference locally.

**Recommended sampling parameters:**

| Parameter | Value |
| :--- | :--- |
| `temperature` | 1.0 |
| `top_p` | 1.0 |
| `context_window` | 1M tokens |
| `max_tokens` | ≥ 256K |

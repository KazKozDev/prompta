# Kimi K3.1 Pro — official prompting materials

Source: https://huggingface.co/moonshotai/Kimi-K3.1-Pro/blob/d9e99b0792a5e93b78ea9bea62a68167e36ddd9e/README.md

Revision: `d9e99b0792a5e93b78ea9bea62a68167e36ddd9e`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Reasoning, knowledge, and multimodal benchmarks (README line 632)

#### Reasoning, knowledge, and multimodal benchmarks

1. **GDP.pdf.** Each PDF is provided as page images resized to a longest edge of 1,152 pixels, interleaved with Docling-extracted text in page order. Responses are graded against each rubric criterion using Gemini-3.5-Flash Medium and the official judging prompt. The table reports the strict pass rate among fully scored responses. GLM-5.3 Max and DeepSeek-V4.1-Flash-1017 Max scores are cited from [Artificial Analysis](https://artificialanalysis.ai/).
2. **HLE-Full and HLE-Diamond.** The full evaluation sets contain 2,500 and 1,000 questions, respectively. For scores marked `*`, accuracy is reported on the text-only subset.
3. **Run counts.** GDP.pdf, ZeroBench, and ChartoGraphy are averaged over five runs; other multimodal benchmarks are averaged over four.
4. **MMMU-Pro.** Evaluated using the official protocol, preserving the original input order and prepending images to the text input.
5. **PerceptionBench.** An in-house benchmark focused on atomic visual perception capabilities.
6. **Kimi Hallucination Benchmark.** Evaluates factual accuracy on an internal set of challenging, de-identified prompts drawn from practical work tasks. The table reports claim-level hallucination rates assessed by fact-checking agents.


---

Source section: 4. Deployment and Availability (README line 649)

## 4. Deployment and Availability

> [!Note]
> You can access Kimi K3.1 Pro's API on https://platform.kimi.ai by selecting `kimi-k3.1-pro`, and we provide OpenAI/Anthropic-compatible API for you.
> Currently, Kimi K3.1 Pro is recommended to run on the following inference engines:

- [vLLM](https://github.com/vllm-project/vllm) — see [recipes](https://recipes.vllm.ai/moonshotai/Kimi-K3.1-Pro)
- [SGLang](https://github.com/sgl-project/sglang) — see [cookbook](https://docs.sglang.io/cookbook/autoregressive/Moonshotai/Kimi-K3.1-Pro)
- [TokenSpeed](https://github.com/lightseekorg/tokenspeed) — see [recipes](https://lightseek.org/tokenspeed/recipes/models#kimi-k3-1-pro)

---

---

Source section: 5. Model Usage (README line 660)

## 5. Model Usage
The thinking effort of Kimi K3.1 Pro is configured with the top-level `reasoning_effort` request field, which supports `"low"`, `"high"`, and `"max"` (default `"max"`).

For multi-turn conversations and tool calls, Kimi K3.1 Pro requires the complete assistant message returned by the API to be passed back to `messages` as-is — including `reasoning_content` and `tool_calls`, not just `content`:

```python
import openai

def chat_with_preserved_thinking(client: openai.OpenAI, model_name: str):
    messages = [
        {
            "role": "user",
            "content": "Tell me three random numbers."
        },
        {
            "role": "assistant",
            "reasoning_content": "I'll start by listing five numbers: 473, 921, 235, 215, 222, and I'll tell you the first three.",
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
        reasoning_effort="max",
    )
    # the assistant should mention 215 and 222 that appear in the prior reasoning content
    print(f"response: {response.choices[0].message.reasoning}")
    return response.choices[0].message.content
```
For full guides and examples (vision input, structured output, partial mode, tool choice, dynamic tool loading, context caching), see the [Kimi K3.1 Pro Quickstart](https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart) and [Thinking Effort](https://platform.kimi.ai/docs/guide/use-thinking-effort).


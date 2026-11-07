# Mistral Large 4 — official prompting materials

Source: https://huggingface.co/mistralai/Mistral-Large-4-1T-A52B/blob/af26e7869af601441d5cdf75a1272469ddc3d059/README.md

Revision: `af26e7869af601441d5cdf75a1272469ddc3d059`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Recommended Settings (README line 85)

## Recommended Settings

- **Reasoning Effort**:
  - `'low'` / `'medium'` / `'high'` — default is `'high'`.
  - Use `reasoning_effort="high"` for complex prompts and agentic usage, `'low'` for fast chat replies and `'medium'` for day to day usage.
- **Sampling**: for all reasoning efforts, we recommend the following sampling parameters:
  - `temperature=1.0`
  - `top_p=0.95`
- **System Prompt**: define a clear environment and use case, including guidance on how to effectively leverage tools in agentic systems.
- **Tools**: keep the set of tools well-defined and limit their number to the minimum required for the use case.
- **Context**: the checkpoint supports a 1M context window.


---

Source section: Usage (README line 123)

## Usage

You can find Mistral Large 4 support on multiple libraries for inference and fine-tuning.

We **thank** all the ecosystem folks who helped us throughout this release to integrate Le Chonk into their frameworks.

The model can be deployed with:

- [`vllm (recommended)`](https://github.com/vllm-project/vllm): See [here](#vllm-recommended) or [vLLM's recipes](https://recipes.vllm.ai/mistralai/Mistral-Large-4-1T-A52B).
- [`SGLang`](https://github.com/sgl-project/sglang): See [here](#sglang) or SGLang’s [cookbook](https://docs.sglang.io/cookbook/autoregressive/Mistral/Mistral-Large-4).
- [`transformers`](https://github.com/huggingface/transformers): See [here](#transformers) or [Hugging Face’s blog post](https://huggingface.co/blog/mistral-large4).
- [`llama.cpp`](https://github.com/ggml-org/llama.cpp): See GGUFs and instructions [here](https://huggingface.co/ggml-org/Mistral-Large-4-1T-A52B-GGUF).

Fine-tune the model via:

- [`Axolotl`](https://github.com/axolotl-ai-cloud/axolotl): See [here](https://docs.axolotl.ai/docs/models/mistral-large-4.html).
- [`Unsloth`](https://unsloth.ai/): See [here](https://unsloth.ai/docs/models/mistral-large-4) for a guide and [here](https://huggingface.co/unsloth/Mistral-Large-4-1T-A52B-GGUF) for their GGUFs.
- [`TRL`](https://github.com/huggingface/trl): See [here](https://huggingface.co/blog/mistral-large4#fine-tuning-with-trl).

> [!Note]
> For optimal performance, we recommend using the Mistral AI API if local serving is subpar.


---

Source section: vLLM (Recommended) (README line 145)

## vLLM (Recommended)

We recommend using Mistral Large 4 with the [vLLM library](https://github.com/vllm-project/vllm) for production-ready inference.

See also the [vLLM recipe for Mistral Large 4](https://recipes.vllm.ai/mistralai/Mistral-Large-4-1T-A52B) for ready-made serving configurations.

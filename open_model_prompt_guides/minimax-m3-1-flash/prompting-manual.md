# MiniMax M3.1 Flash — official prompting materials

Source: https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash/blob/ce7f4df87d2e05262f5775f373dac4772f134041/README.md

Revision: `ce7f4df87d2e05262f5775f373dac4772f134041`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: How to Use (README line 254)

## How to Use

- [MiniMax Code](https://agent.minimax.io/)
- [MiniMax API](https://platform.minimax.io/)


---

Source section: Local Deployment (README line 259)

### Local Deployment

Download the model:

```bash
hf download MiniMaxAI/MiniMax-M3.1-Flash --local-dir MiniMax-M3.1-Flash
```

We recommend the following inference frameworks to serve the model:

- [SGLang](https://docs.sglang.io/) — see [SGLang cookbook](https://docs.sglang.io/cookbook/autoregressive/MiniMax/MiniMax-M3.1).
- [vLLM](https://github.com/vllm-project/vllm) — see [vLLM recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-M3.1-Flash).
- [TokenSpeed](https://github.com/lightseekorg/tokenspeed) — see [TokenSpeed recipe](https://lightseek.org/tokenspeed/recipes/models#minimax-m3-1).

Additional integrations in progress: Transformers, KTransformers, unsloth, and ATOM.


---

Source section: Multi-Chip Deployment (README line 275)

### Multi-Chip Deployment

[FlagOS](https://github.com/flagos-ai) — see [Multi-Chip Support and Downloads](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash/blob/main/docs/FlagOS-Multi-Chip-Support-and-Downloads.md).


---

Source section: Inference Settings (README line 279)

## Inference Settings

Recommended sampling settings: `temperature=1.0` and `top_p=0.95`.

For reasoning, set `reasoning_effort` in the chat template: `low`, `medium`, `high`, `xhigh`, or `max`.

The model supports a context window of up to 1M tokens. Usable context length and throughput depend on GPU memory and the serving configuration.

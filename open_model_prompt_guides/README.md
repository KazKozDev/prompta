# Open-weight model prompting library

Verified 2026-11-05. Dated curated set of 15 leading open-weight general/reasoning/coding models, balancing flagship capability, specialization and developer diversity. Not a universal benchmark rank. Ordering is editorial, not numerical performance ranking. Official model repository and weight-file presence are checked. Open-weight is not a claim that training data, code or licenses are fully open source.

The authoritative sources are developer-owned Hugging Face repositories pinned to exact commits, plus official publisher documentation archived with retrieval dates and SHA-256 hashes. Files are original model cards, available official chat templates, generation configurations and licenses. Per-model prompting-manual.md preserves relevant sections verbatim; where no dedicated guide is established this is stated explicitly. Select a model from the main-screen prompting dropdown to compile from its pinned model card. Additional web guides and templates remain inspectable reference material in Library. Existing provider modes are unchanged. Model weights are not downloaded.

- [Kimi K3.1 Pro](https://huggingface.co/moonshotai/Kimi-K3.1-Pro) — Frontier general reasoning; license: other
- [DeepSeek V4.1 Flash 1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017) — General reasoning, coding and agents; license: mit
- [GLM-5.3](https://huggingface.co/zai-org/GLM-5.3) — Frontier coding and agents; license: other
- [Qwen3.8 2.4T A95B](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B) — Large general reasoning model; license: other
- [MiniMax M3.1 Flash](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash) — Agentic and coding model; license: other
- [Mistral Large 4](https://huggingface.co/mistralai/Mistral-Large-4-1T-A52B) — Large general model; license: other
- [Gemma 4 31B IT](https://huggingface.co/google/gemma-4-31B-it) — Efficient general and multimodal model; license: apache-2.0
- [Nemotron 3.5 Super VL 120B A12B](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16) — Multimodal reasoning and agents; license: other
- [gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) — Open-weight reasoning model; license: apache-2.0
- [MiMo V2.6 Pro MOPD](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-MOPD) — Large general and agentic model; license: mit
- [DeepSeek V4 Pro 0813](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813) — Large reasoning model; license: mit
- [Qwen3-Coder-Next](https://huggingface.co/Qwen/Qwen3-Coder-Next) — Coding specialist; license: apache-2.0
- [GLM-5.3 Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) — Fast coding and agentic model; license: mit
- [Kimi K2.7 Code](https://huggingface.co/moonshotai/Kimi-K2.7-Code) — Coding specialist; license: other
- [Qwen3.8 Flash Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) — Efficient general and agentic model; license: other

## Additional official guides

- Gemma 4: https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4
- Mistral family prompting: https://docs.mistral.ai/inference/prompting
- gpt-oss Harmony format: https://developers.openai.com/cookbook/articles/openai-harmony
- GLM 5.3 Flash usage (hosted API scope): https://docs.z.ai/guides/vlm/glm-5.3-flash

Original HTML and readable text are saved alongside each model. These web snapshots are dated, not immutable upstream revisions. Where no separate prompting manual was established, the pinned model card and available template are the source; this is recorded in model.json. Family-wide recommendations are not represented as model-specific guarantees.

# MiMo V2.6 Pro MOPD — official prompting materials

Source: https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-MOPD/blob/da71ee15e76a8849bd1a9610195c452007a79678/README.md

Revision: `da71ee15e76a8849bd1a9610195c452007a79678`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Tool-call repetition (README line 81)

### Tool-call repetition

Following the release of MiMo-V2.6, tool-call repetition emerged as one of the most noticeable issues in agentic settings: the model would sometimes issue the same or highly similar tool calls repeatedly, consuming time and context without making progress. This checkpoint mitigates it.

![Tool-call repetition rate on MiMo-V2.6-Pro before and after MOPD](assets/mimo-repetition-rate-pro-en.png)

*Figure: response-level repetition rate on MiMo-V2.6-Pro, RL-stage versus this checkpoint, across context lengths and agent harnesses.*

The [technical blog](https://mimo.xiaomi.com/blog/mimo-v2-6-tool-call-repetition) has the full diagnosis. The fix is lightweight to train: a short specialized-teacher run that folds into the normal MOPD pass.



---

Source section: 4. Deployment (README line 153)

## 4. Deployment

For best performance, follow the [SGLang MiMo cookbook](https://docs.sglang.io/cookbook/autoregressive/Xiaomi/MiMo-V2.5). Docker image: `lmsysorg/sglang:latest`.


---

Source section: Usage enquiries and complaints (README line 242)

### Usage enquiries and complaints

[mimo-legal@xiaomi.com](mailto:mimo-legal@xiaomi.com). For information on submitting a complaint, please visit the https://mimo.xiaomi.com.
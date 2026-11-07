# Qwen3-Coder-Next — official prompting materials

Source: https://huggingface.co/Qwen/Qwen3-Coder-Next/blob/a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb/README.md

Revision: `a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb`

Prompt-related model-card sections. This file extracts source sections verbatim; it does not invent model-specific recommendations. Consult README.md for the complete official card.

Source section: Quickstart (README line 51)

## Quickstart

We advise you to use the latest version of `transformers`.

The following contains a code snippet illustrating how to use the model generate content based on given inputs. 
```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "Qwen/Qwen3-Coder-Next"

# load the tokenizer and the model
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
  model_name,
  torch_dtype="auto",
  device_map="auto"
)

# prepare the model input
prompt = "Write a quick sort algorithm."
messages = [
  {"role": "user", "content": prompt}
]
text = tokenizer.apply_chat_template(
  messages,
  tokenize=False,
  add_generation_prompt=True,
)
model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

# conduct text completion
generated_ids = model.generate(
    **model_inputs,
    max_new_tokens=65536
)
output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist() 

content = tokenizer.decode(output_ids, skip_special_tokens=True)

print("content:", content)
```

**Note: If you encounter out-of-memory (OOM) issues, consider reducing the context length to a shorter value, such as `32,768`.**

For local use, applications such as Ollama, LMStudio, MLX-LM, llama.cpp, and KTransformers have also supported Qwen3.


---

Source section: Deployment (README line 97)

## Deployment

For deployment, you can use the latest `sglang` or `vllm` to create an OpenAI-compatible API endpoint.


---

Source section: Best Practices (README line 192)

## Best Practices

To achieve optimal performance, we recommend the following sampling parameters: `temperature=1.0`, `top_p=0.95`, `top_k=40`.


# Grok official documentation — selected text and prompting guides

Downloaded from docs.x.ai on 2026-11-05. Six official guides, not the complete documentation website.

Source: https://docs.x.ai/developers/model-capabilities/text/best-practices

#### Model Capabilities

# Best Practices Guide

This guide collects the practices that get the best results from Grok text and reasoning models on the xAI API. It covers which API to use, how to carry reasoning across turns, how to lower cost with prompt caching, how to configure requests, and how to run evaluations.

Start with these settings:

| Setting | Recommendation |
|---|---|
| [API](#use-the-responses-api) | Use the [Responses API](/developers/model-capabilities/text/generate-text). Chat Completions is deprecated. |
| [Multi-turn history](#send-encrypted-reasoning-back-with-every-turn) | Send the encrypted reasoning content back to the API with every turn. |
| [Prompt caching](#use-prompt-caching-to-lower-cost) | Give each conversation its own `prompt_cache_key`, and only append to the conversation. |
| [Reasoning effort](#reasoning-effort) | Set it explicitly on every request, and record it with every result. |
| [Streaming and timeouts](#streaming-and-timeouts) | Prefer streaming. Allow at least 900 seconds per request, and 1800 seconds or more for long-running evals. |
| [Output length](#output-length) | Set `max_output_tokens` above your longest expected answer, or leave it at its 128,000-token default. |
| [Sampling](#sampling-parameters) | Set `temperature` to 0.7 and `top_p` to 0.95, and don't stray far from them. |

## Use the Responses API

Use the Responses API (`POST /v1/responses`) with Grok reasoning models. The Chat Completions API is deprecated, and it has no field for the model's encrypted reasoning, so every multi-turn or tool-calling conversation sent through it discards the model's earlier thinking. New capabilities also arrive on the Responses API first.

If your code already uses Chat Completions, the [comparison guide](/developers/model-capabilities/text/comparison) maps each parameter and response field to its Responses API equivalent.

> [!WARNING]
>
> Chat Completions is offered only as a legacy endpoint. Results from it understate what Grok reasoning models can do, especially across multiple turns and tool calls.

## Send encrypted reasoning back with every turn

Grok reasoning models think before they answer. The Responses API returns that reasoning as an encrypted `reasoning` item in the response's `output` array, alongside the message and any function calls. When you send these items back unchanged in the next request's `input`, the model stays aware of its earlier reasoning traces. This drastically improves performance on multi-turn conversations and agent loops, where each step builds on decisions the model already reasoned through.

There are two ways to keep reasoning in the conversation:

* Chain requests with `previous_response_id` while `store` is on (the default). SpaceXAI stores the reasoning with the response and restores it for you.
* Manage the history yourself with `store: false`. Request the reasoning with `include: ["reasoning.encrypted_content"]` and append every output item to the next request's `input`. Each request is then self-contained and carries the full conversation, which you can log and replay.

`grok-4.7` returns `reasoning.encrypted_content` on every Responses API response, whether or not `include` lists it. Your code still has to send it back. See [Adding encrypted thinking content](/developers/model-capabilities/text/generate-text#adding-encrypted-thinking-content) for the full reference.

The following loop runs a scripted multi-turn conversation. It streams each turn, carries the encrypted reasoning forward, reuses one `prompt_cache_key` for the whole conversation, and prints how many input tokens were served from the cache:

```python customLanguage="pythonOpenAISDK"
import os
import uuid

import httpx
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(900.0),
)

conversation_id = str(uuid.uuid4())
history = [{"role": "system", "content": "You are a careful analyst. Answer concisely."}]

turns = [
    "A train leaves at 9:40 and arrives at 13:05. How long is the trip?",
    "The return trip is 20% faster. When does it arrive if it leaves at 15:00?",
]

for turn in turns:
    history.append({"role": "user", "content": turn})
    stream = client.responses.create(
        model="grok-4.7",
        input=history,
        reasoning={"effort": "high"},
        temperature=0.7,
        top_p=0.95,
        include=["reasoning.encrypted_content"],
        store=False,
        stream=True,
        extra_body={"prompt_cache_key": conversation_id},
    )
    response = None
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
        elif event.type in ("response.completed", "response.incomplete"):
            response = event.response
    print()
    # Append every output item, including reasoning items with encrypted_content.
    history.extend(response.output)
    print(f"Cached tokens: {response.usage.input_tokens_details.cached_tokens}")
```

```javascript customLanguage="javascriptOpenAISDK"
import { randomUUID } from "node:crypto";
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: process.env.XAI_API_KEY,
    baseURL: "https://api.x.ai/v1",
    timeout: 900000,
});

const conversationId = randomUUID();
const history = [
    { role: "system", content: "You are a careful analyst. Answer concisely." },
];

const turns = [
    "A train leaves at 9:40 and arrives at 13:05. How long is the trip?",
    "The return trip is 20% faster. When does it arrive if it leaves at 15:00?",
];

for (const turn of turns) {
    history.push({ role: "user", content: turn });
    const stream = await client.responses.create({
        model: "grok-4.7",
        input: history,
        reasoning: { effort: "high" },
        temperature: 0.7,
        top_p: 0.95,
        include: ["reasoning.encrypted_content"],
        store: false,
        stream: true,
        prompt_cache_key: conversationId,
    });
    let response;
    for await (const event of stream) {
        if (event.type === "response.output_text.delta") {
            process.stdout.write(event.delta);
        } else if (event.type === "response.completed" || event.type === "response.incomplete") {
            response = event.response;
        }
    }
    console.log();
    // Append every output item, including reasoning items with encrypted_content.
    history.push(...response.output);
    console.log(`Cached tokens: ${response.usage.input_tokens_details.cached_tokens}`);
}
```

```python customLanguage="pythonXAI"
import os
import uuid

from xai_sdk import Client
from xai_sdk.chat import system, user

conversation_id = str(uuid.uuid4())

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    timeout=900,
    # Routes every turn of this conversation to the same server for cache reuse.
    metadata=(("x-grok-conv-id", conversation_id),),
)

chat = client.chat.create(
    model="grok-4.7",
    reasoning_effort="high",
    temperature=0.7,
    top_p=0.95,
    store_messages=False,
    use_encrypted_content=True,
)
chat.append(system("You are a careful analyst. Answer concisely."))

turns = [
    "A train leaves at 9:40 and arrives at 13:05. How long is the trip?",
    "The return trip is 20% faster. When does it arrive if it leaves at 15:00?",
]

for turn in turns:
    chat.append(user(turn))
    for response, chunk in chat.stream():
        print(chunk.content, end="", flush=True)
    print()
    # Appending the response also appends its encrypted reasoning.
    chat.append(response)
    print(f"Cached tokens: {response.usage.cached_prompt_text_tokens}")
```

The Vercel AI SDK carries encrypted reasoning automatically when you chain requests with `previousResponseId`; see [Reasoning](/developers/model-capabilities/text/reasoning#encrypted-reasoning-content).

### Keep reasoning in agent loops

Tool-calling workloads need the same treatment. When the model calls a function, its reasoning item arrives in the same `output` array as the `function_call`. Append the whole array, then your `function_call_output` items, so the model resumes with its plan intact when it reads the tool result:

```python customLanguage="pythonOpenAISDK"
import json

# client, tools, task_prompt, run_tool, and conversation_id come from your code.
def stream_turn(input_items):
    stream = client.responses.create(
        model="grok-4.7",
        input=input_items,
        tools=tools,
        reasoning={"effort": "high"},
        temperature=0.7,
        top_p=0.95,
        include=["reasoning.encrypted_content"],
        store=False,
        stream=True,
        extra_body={"prompt_cache_key": conversation_id},
    )
    for event in stream:
        if event.type in ("response.completed", "response.incomplete"):
            return event.response

input_items = [{"role": "user", "content": task_prompt}]

while True:
    response = stream_turn(input_items)
    # Reasoning, messages, and function calls all go back in order.
    input_items.extend(response.output)

    calls = [item for item in response.output if item.type == "function_call"]
    if not calls:
        break

    for call in calls:
        result = run_tool(call.name, json.loads(call.arguments))
        input_items.append({
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(result),
        })

print(response.output_text)
```

Code drops reasoning most often in one of these ways:

* It extracts `output_text` and appends it as a plain assistant message, discarding the reasoning and function call items around it.
* It edits, reorders, or filters output items before sending them back. Pass them back exactly as received.
* It rebuilds the conversation from a transcript in a different format, such as a Chat Completions `messages` array, between turns.

For long agent loops, [WebSocket mode](/developers/advanced-api-usage/websocket-mode) reduces per-turn latency, and [context compaction](/developers/advanced-api-usage/context-compaction) keeps long conversations within the context window.

## Use prompt caching to lower cost

The xAI API caches prompts automatically, and cached input tokens are billed at a lower rate than regular input tokens; see [Pricing](/developers/pricing) for each model's cached token price. The cache matches your input from the start: when a request begins with exactly the same items as an earlier request, that matching prefix is served from the cache, and only the new items are processed. Multi-turn conversations and agent loops benefit the most, because each turn resends everything before it.

To get the most cache hits:

* Give each conversation its own [`prompt_cache_key`](/developers/advanced-api-usage/prompt-caching/maximizing-cache-hits) and reuse it on every turn. Cache entries live on individual servers, and the key routes every turn of the conversation to the same one. A UUID or your application's session ID works well. With the xAI SDK, send the same value as `x-grok-conv-id` gRPC metadata.
* Only append to the conversation. Editing, removing, or reordering earlier items breaks the prefix, and everything after the change is processed at the full price.
* Send the encrypted reasoning back unchanged. For reasoning models, leaving it out is the most common cause of cache misses. Chaining with `previous_response_id` keeps the prefix intact as well.
* Put static content first. System prompts, few-shot examples, and reference documents at the start of the input form a stable prefix that every turn can reuse.

Check `usage.input_tokens_details.cached_tokens` on each response. It should grow with each turn of a conversation; if it stays at 0, check that every turn sends the same `prompt_cache_key` and that earlier items are unchanged. Caching works with streaming and with tool calls, but cache hits are not guaranteed, because entries can be evicted under load. See [What Breaks Caching](/developers/advanced-api-usage/prompt-caching/multi-turn) for examples.

## Configure requests for reasoning models

Reasoning models spend tokens and time thinking before they respond, so reasoning effort, streaming and timeouts, output limits, and sampling parameters all affect your results.

### Reasoning effort

On the Responses API, `reasoning.effort` controls how much the model thinks. The supported values and the default depend on the model; `grok-4.7` defaults to `"high"`, while `grok-4.3` defaults to `"low"` and also accepts `"none"`. Set the effort explicitly on every request so a default never decides your result, and choose the effort you intend to run in production. If cost or latency matters, compare effort levels and weigh quality against tokens and time. See the [`reasoning_effort`](/developers/model-capabilities/text/reasoning#the-reasoning_effort-parameter) parameter for the supported values per model.

### Streaming and timeouts

Prefer [streaming](/developers/model-capabilities/text/streaming) (`stream: true`) to non-streaming requests. A streamed response sends events as the model works, which keeps the connection from dropping during long generations, and the final `response.completed` event carries the full response, including the encrypted reasoning items to send back.

Set the client timeout to at least 900 seconds, as the examples in this guide do. High reasoning effort on complex problems can run for several minutes, and long-running evals such as Humanity's Last Exam (HLE) can take upwards of 1800 seconds per request. Raise the timeout above your longest expected request so slow requests are not recorded as failures.

### Output length

`max_output_tokens` caps only the visible answer; reasoning and function call tokens do not count toward it. When unset, it defaults to 128,000 tokens. A tight cap cuts the answer off, so set the cap above the longest answer you expect, and treat responses with `status: "incomplete"` as truncated.

### Sampling parameters

> [!WARNING]
>
> Set `temperature` to 0.7 and `top_p` to 0.95, and don't deviate far from these values. Grok models don't respond well to other sampling settings, and quality usually drops when you change them.

On [`POST /v1/chat/completions`](/developers/rest-api-reference/inference/chat-completions) and [`POST /v1/responses`](/developers/rest-api-reference/inference/responses), sampling uses at most `temperature` 1 and at most the model's default `top_p`. Current Grok text models default `top_p` to 0.95. The API accepts `temperature` from 0 to 2 and `top_p` up to 1, and a value above a cap is sampled as that cap. The Responses API echoes the values you sent on the response, including values above the cap. Omitting a field uses the model's default for that field.

Set both values explicitly on every request so your results don't depend on server defaults, and use the same values for every model you compare.

### Errors, retries, and rate limits

Separate infrastructure failures from model failures. Retry `429` and `5xx` responses with exponential backoff, and rerun any request that still fails until it gets a response. Large workloads should respect your team's [rate limits](/developers/rate-limits).

## Evaluate Grok models

A good evaluation tells you how a model will behave on your workload, which is rarely the same as how it scores on a public leaderboard. Apply the settings above, then design and run the eval with these practices.

### Design the eval

Start by writing down what success means for your application in terms you can measure. "Answers support questions well" is too vague to test. A testable version is "resolves at least 85% of a 500-ticket sample without inventing a policy, with a median latency under 20 seconds." Most applications need several criteria at once, such as task accuracy, instruction following, format compliance, safety, latency, and cost.

Build the dataset from the work the model will actually do. Production logs, with personal data removed, are the most representative source; add hand-written edge cases, adversarial inputs, and long or multi-turn examples. Check whether public benchmark items might appear in training data, and keep in mind each model's knowledge cutoff (May 2026 for `grok-4.7`) when questions depend on recent events. If the task needs current information, enable [web search](/developers/tools/web-search) and evaluate that configuration directly.

Choose the cheapest grader that is reliable for the criterion:

| Grader | Best for | Watch out for |
|---|---|---|
| Code | Exact answers, unit tests, schema validation, tool-call arguments | Rejecting correct answers in an unexpected format |
| Model as judge | Open-ended quality, rubric scoring, pairwise comparison | Position bias, preference for longer answers, drift from human judgment |
| Human review | Calibrating other graders, high-stakes or subjective tasks | Cost, speed, and disagreement between reviewers |

When you use a model as a judge, give it a specific rubric with examples of each score, ask it to reason before it scores, and randomize the order of answers in pairwise comparisons. Measure its agreement with human labels on a sample before you trust it at scale.

Prompt each model fairly. Grok reasoning models reason before they answer, so state the task, constraints, and output format directly. If you tuned a prompt for another model, spend comparable effort tuning it for Grok before you compare scores.

### Run, measure, and compare

Reasoning models are not deterministic, so a single run can mislead you. Run each item several times, report the mean and spread, and use pass@k where any one correct attempt counts. Treat small differences between models with suspicion until they hold across runs.

If you must exclude an item that keeps failing, exclude it for every model you compare so all of them are scored on the same set, and report how many items you excluded; dropping failures for one model alone inflates its score.

Log the full response for every request, including its `usage` object. `usage.output_tokens_details.reasoning_tokens` reports how many tokens the model spent reasoning, `usage.input_tokens_details.cached_tokens` shows how much of the input came from the cache, and `usage.cost_in_usd_ticks` gives the exact billed cost of each request; together with wall-clock latency, they let you compare quality per dollar and per second. See [Cost Tracking](/developers/cost-tracking) for converting ticks to dollars. Record the model name, reasoning effort, sampling parameters, date, and harness version with every result, because models and harnesses change.

Before you report results, confirm that:

* Every request used the Responses API.
* Multi-turn and tool-calling items carried their encrypted reasoning forward unchanged.
* Reasoning effort, sampling parameters, model name, and harness version are recorded and match across the models you compare.
* Failed requests were retried, any exclusions apply to every model equally, and truncated responses were flagged.

## Related

* [Generate Text](/developers/model-capabilities/text/generate-text): the Responses API, stored conversations, and encrypted thinking content
* [Reasoning](/developers/model-capabilities/text/reasoning): reasoning effort, encrypted reasoning, and reasoning summaries
* [Streaming](/developers/model-capabilities/text/streaming): streaming responses with Server-Sent Events
* [Prompt Caching](/developers/advanced-api-usage/prompt-caching): how caching works and how to maximize cache hits
* [Function Calling](/developers/tools/function-calling): defining tools and handling tool calls
* [Comparison with Chat Completions](/developers/model-capabilities/text/comparison): migrating from Chat Completions


---

Source: https://docs.x.ai/developers/model-capabilities/text/generate-text

#### Model Capabilities

# Generate Text

The Responses API is the preferred way of interacting with our models via API. It allows optional **stateful interactions** with our models,
where **previous input prompts, reasoning content, and model responses are saved and stored on SpaceXSI's servers**. You can continue the interaction by appending new
prompt messages instead of resending the full conversation. This behavior is on by default. If you would like to store your request/response locally, please see [Disable storing previous request/response on server](#disable-storing-previous-requestresponse-on-server).

**The responses will be stored for 30 days, after which they will be removed. This means you can use the response ID to retrieve or continue a conversation within 30 days of sending the request.**
If you want to continue a conversation after 30 days, please store your responses history and the encrypted thinking content locally, and pass them in a new request body.

For Python, we also offer our [xAI SDK](https://github.com/xai-org/xai-sdk-python) which covers all of our features and uses gRPC for optimal performance. It's fine to mix both. The xAI SDK allows you to interact with all our products such as Collections, Voice API, API key management, and more, while the Responses API is more suited for chatbots and usage in RESTful APIs.

## Prerequisites

Create an API key on the [xAI Console API Keys Page](https://console.x.ai/team/default/api-keys?utm_source=docs\&utm_medium=referral\&utm_campaign=developers-model-capabilities-text-generate-text\&utm_content=api-keys). Set your API key in your environment:

```bash
export XAI_API_KEY="your_api_key"
```

## Creating a new model response

Start by creating a response:

```javascript customLanguage="javascriptAISDK"
import { xai } from '@ai-sdk/xai';
import { generateText } from 'ai';

const { text, response } = await generateText({
  model: xai.responses('grok-4.7'),
  system: "You are Grok, an AI agent built to answer helpful questions.",
  prompt: "How big is the universe?",
});

console.log(text);

// The response ID can be used to continue the conversation
console.log(response.id);
```

```python customLanguage="pythonOpenAISDK"
import os
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(3600.0), # Override default timeout with longer timeout for reasoning models
)

response = client.responses.create(
    model="grok-4.7",
    input=[
        {"role": "system", "content": "You are Grok, an AI agent built to answer helpful questions."},
        {"role": "user", "content": "How big is the universe?"},
    ],
)

print(response)

# The response ID that can be used to continue the conversation later

print(response.id)
```

```javascript customLanguage="javascriptOpenAISDK"
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000, // Override default timeout with longer timeout for reasoning models
});

const response = await client.responses.create({
    model: "grok-4.7",
    input: [
        {
            role: "system",
            content: "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            role: "user",
            content: "How big is the universe?"
        },
    ],
});

console.log(response);

// The response ID that can be used to recall the conversation later
console.log(response.id);
```

```bash
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "model": "grok-4.7",
    "input": [
        {
            "role": "system",
            "content": "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            "role": "user",
            "content": "How big is the universe?"
        }
    ]
}'
```

```python customLanguage="pythonXAI"
import os
from xai_sdk import Client
from xai_sdk.chat import user, system

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    management_api_key=os.getenv("XAI_MANAGEMENT_API_KEY"),
    timeout=3600,
)

chat = client.chat.create(model="grok-4.7")
chat.append(system("You are Grok, an AI agent built to answer helpful questions."))
chat.append(user("How big is the universe?"))
response = chat.sample()

print(response)

# The response ID that can be used to continue the conversation later

print(response.id)
```

### Disable storing previous request/response on server

If you do not want to store your previous request/response on the server, you can set `store: false` on the request.

```python customLanguage="pythonOpenAISDK"
import os
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(3600.0), # Override default timeout with longer timeout for reasoning models
)

response = client.responses.create(
    model="grok-4.7",
    input=[
        {"role": "system", "content": "You are Grok, an AI agent built to answer helpful questions."},
        {"role": "user", "content": "How big is the universe?"},
    ],
    store=False
)

print(response)
```

```javascript customLanguage="javascriptOpenAISDK"
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000, // Override default timeout with longer timeout for reasoning models
});

const response = await client.responses.create({
    model: "grok-4.7",
    input: [
        {
            role: "system",
            content: "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            role: "user",
            content: "How big is the universe?"
        },
    ],
    store: false
});

console.log(response);
```

```bash
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "model": "grok-4.7",
    "input": [
        {
            "role": "system",
            "content": "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            "role": "user",
            "content": "How big is the universe?"
        }
    ],
    "store": false
}'
```

```python customLanguage="pythonXAI"
import os
from xai_sdk import Client
from xai_sdk.chat import user, system

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    management_api_key=os.getenv("XAI_MANAGEMENT_API_KEY"),
    timeout=3600,
)

chat = client.chat.create(model="grok-4.7", store_messages=False)
chat.append(system("You are Grok, an AI agent built to answer helpful questions."))
chat.append(user("How big is the universe?"))
response = chat.sample()

print(response)
```

### Returning encrypted thinking content

If you want to return the encrypted thinking traces, you need to specify `use_encrypted_content=True` in xAI SDK or gRPC request message, or `include: ["reasoning.encrypted_content"]` in the request body.

> [!NOTE]
>
> Make sure to use a reasoning model when working with encrypted thinking content.

> [!NOTE]
>
> `grok-4.7` always returns `reasoning.encrypted_content` on the Responses API, whether or not `include` lists it. See [Encrypted reasoning content](/developers/model-capabilities/text/reasoning#encrypted-reasoning-content).

Modify the steps to create a chat client (xAI SDK) or change the request body as following:

```javascript customLanguage="javascriptAISDK"
import { xai } from '@ai-sdk/xai';
import { generateText } from 'ai';

// Encrypted reasoning content is included automatically by the AI SDK
// as long as `store: false` is not set. No extra configuration is needed.
const { text, reasoning } = await generateText({
  model: xai.responses('grok-4.7'),
  system: "You are Grok, an AI agent built to answer helpful questions.",
  prompt: "How big is the universe?",
});

console.log(text);
console.log(reasoning); // Contains encrypted reasoning content
```

```python customLanguage="pythonOpenAISDK"
response = client.responses.create(
    model="grok-4.7",
    input=[
        {"role": "system", "content": "You are Grok, an AI agent built to answer helpful questions."},
        {"role": "user", "content": "How big is the universe?"},
    ],
    include=["reasoning.encrypted_content"]
)
```

```javascript customLanguage="javascriptWithoutSDK"
const response = await client.responses.create({
    model: "grok-4.7",
    input: [
        {"role": "system", "content": "You are Grok, an AI agent built to answer helpful questions."},
        {"role": "user", "content": "How big is the universe?"},
    ],
    include: ["reasoning.encrypted_content"],
});

```

```bash
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "model": "grok-4.7",
    "input": [
        {
            "role": "system",
            "content": "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            "role": "user",
            "content": "How big is the universe?"
        }
    ],
    "include": ["reasoning.encrypted_content"]
}'
```

```python customLanguage="pythonXAI"
chat = client.chat.create(model="grok-4.7",
        use_encrypted_content=True)
```

See [Adding encrypted thinking content](#adding-encrypted-thinking-content) on how to use the returned encrypted thinking content when making a new request.

## Chaining the conversation

We now have the `id` of the first response. With Chat Completions API, we typically send a stateless new request with all the previous messages.

With Responses API, we can send the `id` of the previous response, and the new messages to append to it.

```javascript customLanguage="javascriptAISDK"
import { xai } from '@ai-sdk/xai';
import { generateText } from 'ai';

// First request
const result = await generateText({
  model: xai.responses('grok-4.7'),
  system: "You are Grok, an AI agent built to answer helpful questions.",
  prompt: "How big is the universe?",
});

console.log(result.text);

// Get the response ID from the response object
const responseId = result.response.id;

// Continue the conversation using previousResponseId
const { text: secondResponse } = await generateText({
  model: xai.responses('grok-4.7'),
  prompt: "How do stars form?",
  providerOptions: {
    xai: {
      previousResponseId: responseId,
    },
  },
});

console.log(secondResponse);
```

```python customLanguage="pythonOpenAISDK"
# Previous steps
import os
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(3600.0), # Override default timeout with longer timeout for reasoning models
)

response = client.responses.create(
    model="grok-4.7",
    input=[
        {"role": "system", "content": "You are Grok, an AI agent built to answer helpful questions."},
        {"role": "user", "content": "How big is the universe?"},
    ],
)

print(response)

# The response ID that can be used to continue the conversation later

print(response.id)

# New steps

second_response = client.responses.create(
    model="grok-4.7",
    previous_response_id=response.id,
    input=[
        {"role": "user", "content": "How do stars form?"},
    ],
)

print(second_response)

# The response ID that can be used to continue the conversation later

print(second_response.id)
```

```javascript customLanguage="javascriptWithoutSDK"
// Previous steps
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000, // Override default timeout with longer timeout for reasoning models
});

const response = await client.responses.create({
    model: "grok-4.7",
    input: [
        {
            role: "system",
            content: "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            role: "user",
            content: "How big is the universe?"
        },
    ],
});

console.log(response);

// The response ID that can be used to recall the conversation later
console.log(response.id);

const secondResponse = await client.responses.create({
    model: "grok-4.7",
    previous_response_id: response.id,
    input: [
        {"role": "user", "content": "How do stars form?"},
    ],
});

console.log(secondResponse);

// The response ID that can be used to recall the conversation later
console.log(secondResponse.id);
```

```bash
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "model": "grok-4.7",
    "previous_response_id": "The previous response ID",
    "input": [
        {
            "role": "user",
            "content": "How do stars form?"
        }
    ]
}'
```

```python customLanguage="pythonXAI"
import os
from xai_sdk import Client
from xai_sdk.chat import user, system

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    management_api_key=os.getenv("XAI_MANAGEMENT_API_KEY"),
    timeout=3600,
)

chat = client.chat.create(model="grok-4.7", store_messages=True)
chat.append(system("You are Grok, an AI agent built to answer helpful questions."))
chat.append(user("How big is the universe?"))
response = chat.sample()

print(response)

# The response ID that can be used to continue the conversation later

print(response.id)

# New steps

chat = client.chat.create(
    model="grok-4.7",
    previous_response_id=response.id,
    store_messages=True,
)
chat.append(user("How do stars form?"))
second_response = chat.sample()

print(second_response)

# The response ID that can be used to continue the conversation later

print(second_response.id)
```

### Adding encrypted thinking content

After returning the encrypted thinking content, you can also add it to a new response's input.

> [!NOTE]
>
> Make sure to use a reasoning model when working with encrypted thinking content.

```javascript customLanguage="javascriptAISDK"
import { xai } from '@ai-sdk/xai';
import { generateText } from 'ai';

// First request. Encrypted reasoning content is included automatically
// by the AI SDK as long as `store: false` is not set.
const result = await generateText({
  model: xai.responses('grok-4.7'),
  system: "You are Grok, an AI agent built to answer helpful questions.",
  prompt: "How big is the universe?",
});

console.log(result.text);

// Continue the conversation using previousResponseId
// The encrypted content is automatically included when using previousResponseId
const { text: secondResponse } = await generateText({
  model: xai.responses('grok-4.7'),
  prompt: "How do stars form?",
  providerOptions: {
    xai: {
      previousResponseId: result.response.id,
    },
  },
});

console.log(secondResponse);
```

```python customLanguage="pythonOpenAISDK"
# Previous steps
import os
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(3600.0), # Override default timeout with longer timeout for reasoning models
)

response = client.responses.create(
    model="grok-4.7",
    input=[
        {"role": "system", "content": "You are Grok, an AI agent built to answer helpful questions."},
        {"role": "user", "content": "How big is the universe?"},
    ],
    include=["reasoning.encrypted_content"]
)

print(response)

# The response ID that can be used to continue the conversation later

print(response.id)

# New steps

second_response = client.responses.create(
    model="grok-4.7",
    input=[
        *response.output,  # Use response.output instead of the stored response
        {"role": "user", "content": "How do stars form?"},
    ],
)

print(second_response)

# The response ID that can be used to continue the conversation later

print(second_response.id)
```

```javascript customLanguage="javascriptWithoutSDK"
// Previous steps
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000, // Override default timeout with longer timeout for reasoning models
});

const response = await client.responses.create({
    model: "grok-4.7",
    input: [
        {
            role: "system",
            content: "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            role: "user",
            content: "How big is the universe?"
        },
    ],
    include: ["reasoning.encrypted_content"],
});

console.log(response);

// The response ID that can be used to recall the conversation later
console.log(response.id);

const secondResponse = await client.responses.create({
    model: "grok-4.7",
    input: [
        ...response.output,  // Use response.output instead of the stored response
        {"role": "user", "content": "How do stars form?"},
    ],
});

console.log(secondResponse);

// The response ID that can be used to recall the conversation later
console.log(secondResponse.id);
```

```bash
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "model": "grok-4.7",
    "input": [
        {
            "role": "system",
            "content": "You are Grok, an AI agent built to answer helpful questions."
        },
        {
            "role": "user",
            "content": "How big is the universe?"
        },
        {
            "id": "rs_51abe1aa-599b-80b6-57c8-dddc6263362f_us-east-1",
            "summary": [],
            "type": "reasoning",
            "status": "completed",
            "encrypted_content": "bvV88j99ILvgfHRTHCUSJtw+ISji6txJzPdZNbcSVuDk4OMG2Z9r5wOBBwjd3u3Hhm9XtpCWJO1YgTOlpgbn+g7DZX+pOagYYrCFUpQ19XkWz6Je8bHG9JcSDoGDqNgRbDbAUO8at6RCyqgPupJj5ArBDCt73fGQLTC4G3S0JMK9LsPiWz6GPj6qyzYoRzkj4R6bntRm74E4h8Y+z6u6B7+ixPSv8s1EFs8c+NUAB8TNKZZpXZquj2LXfx1xAie85Syl7qLqxLNtDG1dNBhBnHpYoE4gQzwyXqywf5pF2Q2imzPNzGQhurK+6gaNWgZbxRmjhdsW6TnzO5Kk6pzb5qpfgfcEScQeYHSj5GpD+yDUCNlhdbzhhWnEErH+wuBPpTG6UQhiC7m7yrJ7IY2E8K/BeUPlUvkhMaMwb4dA279pWMJdchNJ+TAxca+JVc80pXMG/PmrQUNJU9qdXRLbNmQbRadBNwV2qkPfgggL3q0yNd7Un9P+atmP3B9keBILif3ufsBDtVUobEniiyGV7YVDvQ/fQRVs7XDxJiOKkogjjQySyHgpjseO8iG5xtb9mrz6B3mDvv2aAuyDL6MHZRM7QDVPjUbgNMzDm5Sm3J7IhtzfR+3eMDws3qeTsxOt1KOslu983Btv1Wx37b5HJqX1pQU1dae/kOSJ7MifFd6wMkQtQBDgVoG3ka9wq5Vxq9Ki8bDOOMcwA2kUXhCcY3TZCXJfDWSKPTcCoNCYIv5LT2NFVdamiSfLIyeOjBNz459BfMvAoOZShFViQyc5YwjnReUQPQ8a18jcz8GoAK1O99e0h91oYxIgDV52EfS+IYrzqvJOEQbKQinB+LJwkPbBEp7ZtgAtiNBzm985hNgLfiBaVFWcRYwI3tNBCT1vkw2YI0NEEG0yOF29x+u64XzqyP1CX1pU6sGXEFn3RPdfYibf6bt/Y1BRqBL5l0CrXWsgDw02SqIFta8OvJ7Iwmq40/4acE/Ew6eWO/z2MHkWgqSpwGNjn7MfeKkTi44foZjfNqN9QOFQt6VG2tY+biKZDo0h9DAftae8Q2Xs2UDvsBYOm7YEahVkput6/uKzxljpXlz269qHk6ckvdN9hKLbaTO3/IZPCCPQ5a/a/sWn/1VOJj72sDk+23RNjBf0FL6bJMXZI5aQdtxbF1zij9mWcP9nJ9FHhj53ytuf1NiKl5xU8ZsaoKmCAJcXUz1n2FZvyWlqvgPYiszc7R8Y5dF6QbW2mlKnXzVy6qRMHNeQqGhCEncyT5nPNSdK5QlUwLokAIg"
        },
        {
            "content": [
                {
                    "type": "output_text",
                    "text": "42\n\nThis is, of course, the iconic answer from Douglas Adams'\'' *The Hitchhiker'\''s Guide to the Galaxy*, where a supercomputer named Deep Thought spends 7.5 million years computing the \"Answer to the Ultimate Question of Life, the Universe, and Everything\"—only to reveal it'\''s 42. (The real challenge, it turns out, is figuring out what the actual *question* was.)\n\nIf you'\''re asking in a more literal or philosophical sense, the universe doesn'\''t have a single tidy answer—it'\''s full of mysteries like quantum mechanics, dark matter, and why cats knock things off tables. But 42? That'\''s as good a starting point as any. What'\''s your take on it?",
                    "logprobs": null,
                    "annotations": []
                }
            ],
            "id": "msg_c2f68a9b-87cd-4f85-a9e9-b6047213a3ce_us-east-1",
            "role": "assistant",
            "type": "message",
            "status": "completed"
        },
        {
            "role": "user",
            "content": "How do stars form?"
        }
    ],
    "include": [
        "reasoning.encrypted_content"
    ]
}'
```

```python customLanguage="pythonXAI"
import os
from xai_sdk import Client
from xai_sdk.chat import user, system

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    management_api_key=os.getenv("XAI_MANAGEMENT_API_KEY"),
    timeout=3600,
)

chat = client.chat.create(model="grok-4.7", store_messages=True, use_encrypted_content=True)
chat.append(system("You are Grok, an AI agent built to answer helpful questions."))
chat.append(user("How big is the universe?"))
response = chat.sample()

print(response)

# The response ID that can be used to continue the conversation later

print(response.id)

# New steps

chat.append(response)  ## Append the response and the SDK will automatically add the outputs from response to message history

chat.append(user("How do stars form?"))
second_response = chat.sample()

print(second_response)

# The response ID that can be used to continue the conversation later

print(second_response.id)
```

## Retrieving a previous model response

If you have a previous response's ID, you can retrieve the content of the response.

```javascript customLanguage="javascriptAISDK"
// Note: The Vercel AI SDK does not provide a method to retrieve previous responses.
// Use the OpenAI SDK as shown above for this functionality.

import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000,
});

const response = await client.responses.retrieve("<The previous response's id>");

console.log(response);
```

```python customLanguage="pythonOpenAISDK"
import os
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(3600.0), # Override default timeout with longer timeout for reasoning models
)

response = client.responses.retrieve("<The previous response's id>")

print(response)
```

```javascript customLanguage="javascriptOpenAISDK"
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000, // Override default timeout with longer timeout for reasoning models
});

const response = await client.responses.retrieve("<The previous response's id>");

console.log(response);
```

```bash
curl https://api.x.ai/v1/responses/{response_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600
```

```python customLanguage="pythonXAI"
import os
from xai_sdk import Client
from xai_sdk.chat import user, system

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    management_api_key=os.getenv("XAI_MANAGEMENT_API_KEY"),
    timeout=3600,
)

response = client.chat.get_stored_completion("<The previous response's id>")

print(response)
```

## Delete a model response

If you no longer want to store the previous model response, you can delete it.

```javascript customLanguage="javascriptAISDK"
// Note: The Vercel AI SDK does not provide a method to delete previous responses.
// Use the OpenAI SDK as shown above for this functionality.

import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000,
});

const response = await client.responses.delete("<The previous response's id>");

console.log(response);
```

```python customLanguage="pythonOpenAISDK"
import os
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
    timeout=httpx.Timeout(3600.0), # Override default timeout with longer timeout for reasoning models
)

response = client.responses.delete("<The previous response's id>")

print(response)
```

```javascript customLanguage="javascriptOpenAISDK"
import OpenAI from "openai";

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
    timeout: 360000, // Override default timeout with longer timeout for reasoning models
});

const response = await client.responses.delete("<The previous response's id>");

console.log(response);
```

```bash
curl -X DELETE https://api.x.ai/v1/responses/{response_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600
```

```python customLanguage="pythonXAI"
import os
from xai_sdk import Client
from xai_sdk.chat import user, system

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    management_api_key=os.getenv("XAI_MANAGEMENT_API_KEY"),
    timeout=3600,
)

response = client.chat.delete_stored_completion("<The previous response's id>")
print(response)
```


---

Source: https://docs.x.ai/developers/model-capabilities/text/reasoning

#### Model Capabilities

# Reasoning

## Key Features

* **Think Before Responding**: Reasoning models think through problems step-by-step before delivering an answer.
* **Math & Quantitative Strength**: Excels at numerical challenges, logic puzzles, and complex analytical tasks.
* **Reasoning Trace**: Usage metrics expose `reasoning_tokens`. Some models can also return encrypted reasoning via `include: ["reasoning.encrypted_content"]` (see below).

### Encrypted Reasoning Content

The reasoning content is encrypted by us and can be returned if you pass `include: ["reasoning.encrypted_content"]` to the Responses API. You can send the encrypted content back to provide more context to a previous conversation. See [Adding encrypted thinking content](/developers/model-capabilities/text/generate-text#adding-encrypted-thinking-content) for more details on how to use the content.

> [!NOTE]
> Always returned for grok-4.7
>
> On the Responses API, `grok-4.7` returns `reasoning.encrypted_content` on every response, whether or not `include` lists it, together with the encrypted outputs of any server-side tools. Reasoning items in the output carry an `encrypted_content` field; pass them back unchanged in the next request's `input` so the model keeps its reasoning across turns even when you manage conversation history yourself. Unlike an explicit `include`, this default does not stop SpaceXSI from storing the thinking trace server-side for rehydration, so clients that ignore the field keep working as before; whether the response itself is stored for `previous_response_id` is governed by `store`, not by this setting. Chat Completions is unaffected; it has no field for the ciphertext.

> [!TIP]
>
> When using the Vercel AI SDK, encrypted reasoning content is automatically included under the hood as long as `store: false` is not specified. No additional configuration is needed.

## The `reasoning_effort` parameter

`grok-4.7`, `grok-4.6`, and `grok-4.5` support the `reasoning_effort` parameter, which controls how much effort the model spends thinking before responding.

If not specified, `reasoning_effort` defaults to `"high"`. Reasoning cannot be disabled.

`presencePenalty`, `frequencyPenalty`, and `stop` cannot be used with reasoning models. Requests that include them return an error.

### Effort levels

| Setting | Description | Best For |
|---|---|---|
| `"low"` | Uses some reasoning tokens, but still fast | Latency-sensitive agentic use and simple tool calling. |
| `"medium"` | More thinking for less-latency sensitive applications | Complex data analysis and long-context reasoning. |
| `"high"` (default) | Uses more reasoning tokens for deeper thinking | Very challenging problems, complex math, multi-step logic, competition-level tasks |
| `"xhigh"` | Maximum reasoning depth, with correspondingly higher latency | The hardest problems, where answer quality matters more than response time |

> [!TIP]
>
> `"xhigh"` is available on `grok-4.6` and later. On models that do not support it, such as `grok-4.5`, requests with `"xhigh"` are treated as `"high"`.

### Setting reasoning effort

The following example sets `reasoning_effort` to `"high"` for a challenging math proof. You can substitute `"low"`, `"medium"`, or (on supported models) `"xhigh"` as needed.

```typescript customLanguage="javascriptAISDK" highlightedLines="9"
import { xai } from '@ai-sdk/xai';
import { generateText } from 'ai';

const result = await generateText({
  model: xai.responses('grok-4.7'),
  system: 'You are a highly intelligent AI assistant.',
  prompt: 'Find all prime numbers p such that p^2 + 2 is also prime. Prove your answer.',
  providerOptions: {
    xai: { reasoningEffort: 'high' },
  },
});

console.log('Final Response:', result.text);
```

```python customLanguage="pythonOpenAISDK" highlightedLines="13"
import os
import httpx
from openai import OpenAI

client = OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=os.getenv("XAI_API_KEY"),
    timeout=httpx.Timeout(3600.0),
)

response = client.responses.create(
    model="grok-4.7",
    reasoning={"effort": "high"},
    input=[
        {"role": "system", "content": "You are a highly intelligent AI assistant."},
        {"role": "user", "content": "Find all prime numbers p such that p^2 + 2 is also prime. Prove your answer."},
    ],
)

message = next(item for item in response.output if item.type == "message")
text = next(c.text for c in message.content if c.type == "output_text")

print("Final Response:")
print(text)
```

```bash customLanguage="bash" highlightedLines="7"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "model": "grok-4.7",
    "reasoning": {"effort": "high"},
    "input": [
        {
            "role": "system",
            "content": "You are a highly intelligent AI assistant."
        },
        {
            "role": "user",
            "content": "Find all prime numbers p such that p^2 + 2 is also prime. Prove your answer."
        }
    ]
}'
```

```python customLanguage="pythonXAI" highlightedLines="13"
import os

from xai_sdk import Client
from xai_sdk.chat import system, user

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    timeout=3600,
)

chat = client.chat.create(
    model="grok-4.7",
    reasoning_effort="high",
    messages=[system("You are a highly intelligent AI assistant.")],
)
chat.append(user("Find all prime numbers p such that p^2 + 2 is also prime. Prove your answer."))

response = chat.sample()

print("Final Response:")
print(response.content)
```

### Multi-agent model

For `grok-4.20-multi-agent`, the `reasoning.effort` parameter controls **how many agents** collaborate on a request rather than reasoning depth. See the [Multi Agent](/developers/model-capabilities/text/multi-agent) documentation for details.

### Summary table

| Model | `reasoning` parameter | Behavior |
|---|---|---|
| `grok-4.7` | `reasoning.effort`: `"low"` / `"medium"` / `"high"` (default) / `"xhigh"` | Controls reasoning depth (cannot be disabled) |
| `grok-4.6` | `reasoning.effort`: `"low"` / `"medium"` / `"high"` (default) / `"xhigh"` | Controls reasoning depth (cannot be disabled) |
| `grok-4.5` | `reasoning.effort`: `"low"` / `"medium"` / `"high"` (default) | Controls reasoning depth (cannot be disabled) |
| `grok-4.20-multi-agent` | `reasoning.effort`: `"low"` / `"medium"` / `"high"` / `"xhigh"` | Controls agent count (4 or 16) |

## Summarized Reasoning Content

For `grok-4.7`, we expose summarizations of the model's internal reasoning. Here's an example of how to stream the reasoning summary deltas alongside the final response:

```typescript customLanguage="javascriptAISDK"
import { xai } from '@ai-sdk/xai';
import { streamText } from 'ai';

const result = streamText({
  model: xai.responses('grok-4.7'),
  system: 'You are a highly intelligent AI assistant.',
  prompt: 'A projectile is launched at 30 m/s at 37° above horizontal from a 45 m cliff. Find its speed on impact. (g=10 m/s²)'
});

console.log("\n\n--------- Reasoning ---------")

for await (const part of result.fullStream) {
  if (part.type === 'reasoning-delta') {
    process.stdout.write(part.text);
  } 
}
```

```python customLanguage="pythonOpenAISDK"
import os
import httpx
from openai import OpenAI

client = OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=os.getenv("XAI_API_KEY"),
    timeout=httpx.Timeout(3600.0),
)

stream = client.responses.create(
    model="grok-4.7",
    input=[
        {"role": "system", "content": "You are a highly intelligent AI assistant."},
        {"role": "user", "content": "A projectile is launched at 30 m/s at 37° above horizontal from a 45 m cliff. Find its speed on impact. (g=10 m/s²)"},
    ],
    stream=True,
)

print("\n\n--------- Reasoning ---------", flush=True)
for event in stream:
    if event.type in ("response.reasoning_text.delta", "response.reasoning_summary_text.delta"):
        print(event.delta, end="", flush=True)
```

```bash customLanguage="bash"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -m 3600 \
  -d '{
    "input": [
        {
            "role": "system",
            "content": "You are a highly intelligent AI assistant."
        },
        {
            "role": "user",
            "content": "A ball is thrown upward at 25 m/s from the top of a 60 m building. Find the maximum height above the ground. (g=10 m/s²)"
        }
    ],
    "model": "grok-4.7",
    "stream": true
}'
```

```python customLanguage="pythonXAI"
import os

from xai_sdk import Client
from xai_sdk.chat import system, user

client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    timeout=3600, # Override default timeout with longer timeout for reasoning models
)

chat = client.chat.create(
    model="grok-4.7",
    messages=[system("You are a highly intelligent AI assistant.")],
)
chat.append(user("A projectile is launched at 30 m/s at 37° above horizontal from a 45 m cliff. Find its speed on impact. (g=10 m/s²)"))

content_started = False

print("\n\n--------- Reasoning ---------", flush=True)

latest_response = None
for response, chunk in chat.stream():
    if chunk.reasoning_content:
        print(chunk.reasoning_content, end="", flush=True)
```

### Sample Output

```output
--------- Reasoning ---------
The problem is: A projectile is launched at 30 m/s at 37° above horizontal from a 45 m cliff. Find its speed on impact. (g=10 m/s²)
I need to find the speed when the projectile hits the ground. It's launched at 30 m/s at 37° from a 45 m cliff, with g=10 m/s².

Conservation of energy is a good approach. The initial kinetic energy is (1/2)mv² with v=30 m/s, and initial potential energy is mgh with h=45 m, taking ground as zero.

At impact, potential energy is zero, so initial KE + initial PE = final KE.

Thus, (1/2)m(30)² + mg(45) = (1/2)m v_f²

v_f² = 900 + 2*10*45 = 900 + 900 = 1800

v_f = sqrt(1800) = 30√2 m/s ≈ 42.4 m/s

The angle doesn't affect the final speed because the initial kinetic energy and potential energy change are the same regardless of direction, as long as the speed and height are the same.

Yes, that makes sense. The final speed is sqrt(v0² + 2gh), independent of the launch angle.
```

When you use a reasoning model, the reasoning tokens are billed as part of your total consumption.


---

Source: https://docs.x.ai/developers/model-capabilities/text/structured-outputs

#### Model Capabilities

# Structured Outputs

Structured Outputs lets the API return responses in a specific format,
for example, a JSON object matching a schema you define instead of free-form
text. This feature is especially useful for tasks like document parsing, entity
extraction, and report generation.

> [!TIP]
>
> When using supported schema features, the response is guaranteed to match your schema.

There are two ways to request structured outputs from the model.

The primary and most flexible method is to use the `response_format` parameter. By setting `response_format.type` to `"json_schema"` and providing your schema under `response_format.json_schema`, you can define exactly what structured output the model should return. The parameter also accepts `"json_object"` for any well-formed JSON when you don't need a specific structure, or `"text"` (the default) for free-form text.

The second way is through tool calling. When you define tools, SpaceXSI models will always generate tool call arguments that strictly conform to the tool’s input JSON Schema (the `strict` flag is implicitly always `true`).

> [!NOTE]
>
> Tool schemas follow the same JSON Schema support rules described on this page. See the [Function Calling](/developers/tools/function-calling) documentation for full details.

You can define schemas using libraries like
[Pydantic](https://pydantic.dev/) or [Zod](https://zod.dev/).

## JSON Schema support

We support a practical subset of JSON Schema. Schemas authored against Draft 2020-12 work best; Draft-07 schemas are also accepted.

### Supported types

* `string`
* `number`
* `integer`
* `boolean`
* `null`
* `enum`
* `const`
* `array`
* `object`
* `anyOf`
* `oneOf` (behaves identically to `anyOf`)
* `allOf` (single subschema only; see [Best-effort keywords](#best-effort-keywords) for multiple)
* `$ref` / `$defs` (non-circular references only)

> [!NOTE]
>
> `additionalProperties` defaults to `false` and must be set to `true` explicitly.

To make a field nullable, use a type array (`{"type": ["string", "null"]}`) or an `anyOf` variant that includes `null`. Fields not listed in `required` are treated as optional.

### String formats

The `format` keyword is enforced for these values:

`date` · `time` · `date-time` · `email` · `uuid` · `ipv4` · `ipv6` · `uri`

Other `format` values are accepted but not enforced (see [Best-effort keywords](#best-effort-keywords)).

### Constraint limits

The following constraints are enforced by the output engine up to
the thresholds below. Schemas exceeding these limits are still accepted,
but conformance relies on model behavior.

| Keyword | Guaranteed up to |
|---|---|
| `minimum` / `maximum` / `exclusiveMinimum` / `exclusiveMaximum` | No limit |
| `minLength` / `maxLength` | 2,048 |
| `minItems` / `maxItems` | 256 |
| `minProperties` / `maxProperties` | 64 |

### Best-effort keywords

These keywords are accepted but not structurally enforced; the model
handles them and does so reliably in practice, but outputs are not
guaranteed to satisfy these constraints. We recommend validating
if strict conformance is required.

* `not`
* `if` / `then` / `else`
* `allOf` with more than one subschema
* `format` values not listed under [String formats](#string-formats)
* Constraints exceeding the limits above

### Rejected schemas

The following will return a `400` error:

* `enum` or `anyOf` with zero variants
* Properties with a schema of `true` or `false`
* `maxContains` / `minContains`
* `items` as an array (use `prefixItems` for tuple validation)

### Regex support (`pattern`)

When using the `pattern` keyword on a string field, we support a practical subset of ECMAScript Regular Expressions (ECMA-262).

**Supported:**

* Literals and character classes (`[abc]`, `[a-z]`, `[^abc]`)
* `.` (matches any Unicode codepoint, including newlines)
* Alternation `|`, grouping `(...)`, and non-capturing groups `(?:...)`
* Quantifiers `*`, `+`, `?` and repetition ranges `{n}`, `{n,}`, `{n,m}`
* Shorthand classes `\d`, `\w`, `\s` (and their negations `\D`, `\W`, `\S`)
* Common escapes: `\n`, `\t`, `\r`, `\f`, `\xHH`, `\uHHHH`, `\u{HHHHHH}`

**Not supported:**

* Backreferences (`\1`, `\k<name>`, etc.)
* Unicode property escapes (`\p{L}`, `\P{Letter}`)
* Word boundaries (`\b`, `\B`)
* Lookahead and lookbehind (`(?=...)`, `(?<=...)`, etc.)
* Inline modifiers (`(?i)`, `(?m)`, etc.)
* Conditional expressions and other advanced constructs

**Semantic differences from standard JavaScript RegExp:**

* `.` matches newlines
* `^` and `$` are *implicit*—the pattern always matches the *entire string* (no need to add them)
* Capturing groups `(...)` have no semantic effect (they behave like non-capturing groups)
* The regex is evaluated with Unicode support

## Example: Invoice Parsing

A common use case for Structured Outputs is parsing raw documents. For example, invoices contain structured data like vendor details, amounts, and dates, but extracting this data from raw text can be error-prone. Structured Outputs ensures the extracted data matches a predefined schema.

Let's say you want to extract the following data from an invoice:

* Vendor name and address
* Invoice number and date
* Line items (description, quantity, price)
* Total amount and currency

We'll use structured outputs to have Grok generate a strongly typed JSON for this.

### Step 1: Defining the Schema

You can use [Pydantic](https://pydantic.dev/) or [Zod](https://zod.dev/) to define your schema.

```pythonWithoutSDK
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"

class LineItem(BaseModel):
    description: str = Field(description="Description of the item or service")
    quantity: int = Field(description="Number of units", ge=1)
    unit_price: float = Field(description="Price per unit", ge=0)

class Address(BaseModel):
    street: str = Field(description="Street address")
    city: str = Field(description="City")
    postal_code: str = Field(description="Postal/ZIP code")
    country: str = Field(description="Country")

class Invoice(BaseModel):
    vendor_name: str = Field(description="Name of the vendor")
    vendor_address: Address = Field(description="Vendor's address")
    invoice_number: str = Field(description="Unique invoice identifier")
    invoice_date: date = Field(description="Date the invoice was issued")
    line_items: list[LineItem] = Field(description="List of purchased items/services")
    total_amount: float = Field(description="Total amount due", ge=0)
    currency: Currency = Field(description="Currency of the invoice")
```

```javascriptWithoutSDK
import { z } from "zod";

const CurrencyEnum = z.enum(["USD", "EUR", "GBP"]);

const LineItemSchema = z.object({
    description: z.string().describe("Description of the item or service"),
    quantity: z.number().int().min(1).describe("Number of units"),
    unit_price: z.number().min(0).describe("Price per unit"),
});

const AddressSchema = z.object({
    street: z.string().describe("Street address"),
    city: z.string().describe("City"),
    postal_code: z.string().describe("Postal/ZIP code"),
    country: z.string().describe("Country"),
});

const InvoiceSchema = z.object({
    vendor_name: z.string().describe("Name of the vendor"),
    vendor_address: AddressSchema.describe("Vendor's address"),
    invoice_number: z.string().describe("Unique invoice identifier"),
    invoice_date: z.string().date().describe("Date the invoice was issued"),
    line_items: z.array(LineItemSchema).describe("List of purchased items/services"),
    total_amount: z.number().min(0).describe("Total amount due"),
    currency: CurrencyEnum.describe("Currency of the invoice"),
});
```

### Step 2: Prepare The Prompts

### System Prompt

The system prompt instructs the model to extract invoice data from text. Since the schema is defined separately, the prompt can focus on the task without explicitly specifying the required fields in the output JSON.

```text
Given a raw invoice, carefully analyze the text and extract the relevant invoice data into JSON format.
```

### Example Invoice Text

```text
Vendor: Acme Corp, 123 Main St, Springfield, IL 62704
Invoice Number: INV-2025-001
Date: 2025-02-10
Items:
- Widget A, 5 units, $10.00 each
- Widget B, 2 units, $15.00 each
Total: $80.00 USD
```

### Step 3: The Final Code

Use the structured outputs feature of the SDK to parse the invoice.

```javascriptAISDK
import { xai } from '@ai-sdk/xai';
import { generateText, Output } from 'ai';
import { z } from 'zod';

const CurrencyEnum = z.enum(['USD', 'EUR', 'GBP']);

const LineItemSchema = z.object({
  description: z.string().describe('Description of the item or service'),
  quantity: z.number().int().min(1).describe('Number of units'),
  unit_price: z.number().min(0).describe('Price per unit'),
});

const AddressSchema = z.object({
  street: z.string().describe('Street address'),
  city: z.string().describe('City'),
  postal_code: z.string().describe('Postal/ZIP code'),
  country: z.string().describe('Country'),
});

const InvoiceSchema = z.object({
  vendor_name: z.string().describe('Name of the vendor'),
  vendor_address: AddressSchema.describe("Vendor's address"),
  invoice_number: z.string().describe('Unique invoice identifier'),
  invoice_date: z.string().date().describe('Date the invoice was issued'),
  line_items: z
    .array(LineItemSchema)
    .describe('List of purchased items/services'),
  total_amount: z.number().min(0).describe('Total amount due'),
  currency: CurrencyEnum.describe('Currency of the invoice'),
});

const result = await generateText({
  model: xai.responses('grok-4.7'),
  output: Output.object({ schema: InvoiceSchema }),
  system:
    'Given a raw invoice, carefully analyze the text and extract the invoice data into JSON format.',
  prompt: \`
  Vendor: Acme Corp, 123 Main St, Springfield, IL 62704
  Invoice Number: INV-2025-001
  Date: 2025-02-10
  Items:

  - Widget A, 5 units, $10.00 each
  - Widget B, 2 units, $15.00 each
    Total: $80.00 USD
    \`,
});

console.log(result._output);
```

```pythonOpenAISDK
from openai import OpenAI

from pydantic import BaseModel, Field
from datetime import date
from enum import Enum

# Pydantic Schemas

class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"

class LineItem(BaseModel):
    description: str = Field(description="Description of the item or service")
    quantity: int = Field(description="Number of units", ge=1)
    unit_price: float = Field(description="Price per unit", ge=0)

class Address(BaseModel):
    street: str = Field(description="Street address")
    city: str = Field(description="City")
    postal_code: str = Field(description="Postal/ZIP code")
    country: str = Field(description="Country")

class Invoice(BaseModel):
    vendor_name: str = Field(description="Name of the vendor")
    vendor_address: Address = Field(description="Vendor's address")
    invoice_number: str = Field(description="Unique invoice identifier")
    invoice_date: date = Field(description="Date the invoice was issued")
    line_items: list[LineItem] = Field(description="List of purchased items/services")
    total_amount: float = Field(description="Total amount due", ge=0)
    currency: Currency = Field(description="Currency of the invoice")

client = OpenAI(
    api_key="<YOUR_XAI_API_KEY_HERE>",
    base_url="https://api.x.ai/v1",
)

completion = client.beta.chat.completions.parse(
    model="grok-4.7",
    messages=[
    {"role": "system", "content": "Given a raw invoice, carefully analyze the text and extract the invoice data into JSON format."},
    {"role": "user", "content": """
    Vendor: Acme Corp, 123 Main St, Springfield, IL 62704
    Invoice Number: INV-2025-001
    Date: 2025-02-10
    Items:

    - Widget A, 5 units, $10.00 each
    - Widget B, 2 units, $15.00 each
      Total: $80.00 USD
      """}
      ],
      response_format=Invoice,
  )

invoice = completion.choices[0].message.parsed
print(invoice)
```

```javascriptOpenAISDK
import OpenAI from "openai";
import { zodResponseFormat } from "openai/helpers/zod";
import { z } from "zod";

const CurrencyEnum = z.enum(["USD", "EUR", "GBP"]);

const LineItemSchema = z.object({
    description: z.string().describe("Description of the item or service"),
    quantity: z.number().int().min(1).describe("Number of units"),
    unit_price: z.number().min(0).describe("Price per unit"),
});

const AddressSchema = z.object({
    street: z.string().describe("Street address"),
    city: z.string().describe("City"),
    postal_code: z.string().describe("Postal/ZIP code"),
    country: z.string().describe("Country"),
});

const InvoiceSchema = z.object({
    vendor_name: z.string().describe("Name of the vendor"),
    vendor_address: AddressSchema.describe("Vendor's address"),
    invoice_number: z.string().describe("Unique invoice identifier"),
    invoice_date: z.string().date().describe("Date the invoice was issued"),
    line_items: z.array(LineItemSchema).describe("List of purchased items/services"),
    total_amount: z.number().min(0).describe("Total amount due"),
    currency: CurrencyEnum.describe("Currency of the invoice"),
});

const client = new OpenAI({
    apiKey: "<api key>",
    baseURL: "https://api.x.ai/v1",
});

const completion = await client.chat.completions.parse({
    model: "grok-4.7",
    messages: [
    { role: "system", content: "Given a raw invoice, carefully analyze the text and extract the invoice data into JSON format." },
    { role: "user", content: \`
    Vendor: Acme Corp, 123 Main St, Springfield, IL 62704
    Invoice Number: INV-2025-001
    Date: 2025-02-10
    Items:

    - Widget A, 5 units, $10.00 each
    - Widget B, 2 units, $15.00 each
      Total: $80.00 USD
      \` },
    ],
    response_format: zodResponseFormat(InvoiceSchema, "invoice"),
});

const invoice = completion.choices[0].message.parsed;
console.log(invoice);
```

```pythonXAI
import os
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from xai_sdk import Client
from xai_sdk.chat import system, user

# Pydantic Schemas

class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"

class LineItem(BaseModel):
    description: str = Field(description="Description of the item or service")
    quantity: int = Field(description="Number of units", ge=1)
    unit_price: float = Field(description="Price per unit", ge=0)

class Address(BaseModel):
    street: str = Field(description="Street address")
    city: str = Field(description="City")
    postal_code: str = Field(description="Postal/ZIP code")
    country: str = Field(description="Country")

class Invoice(BaseModel):
    vendor_name: str = Field(description="Name of the vendor")
    vendor_address: Address = Field(description="Vendor's address")
    invoice_number: str = Field(description="Unique invoice identifier")
    invoice_date: date = Field(description="Date the invoice was issued")
    line_items: list[LineItem] = Field(description="List of purchased items/services")
    total_amount: float = Field(description="Total amount due", ge=0)
    currency: Currency = Field(description="Currency of the invoice")

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(model="grok-4.7")

chat.append(system("Given a raw invoice, carefully analyze the text and extract the invoice data into JSON format."))
chat.append(
user("""
Vendor: Acme Corp, 123 Main St, Springfield, IL 62704
Invoice Number: INV-2025-001
Date: 2025-02-10
Items: - Widget A, 5 units, $10.00 each - Widget B, 2 units, $15.00 each
Total: $80.00 USD
""")
)

# The parse method returns a tuple of the full response object as well as the parsed pydantic object.

response, invoice = chat.parse(Invoice)
assert isinstance(invoice, Invoice)

# Can access fields of the parsed invoice object directly

print(invoice.vendor_name)
print(invoice.invoice_number)
print(invoice.invoice_date)
print(invoice.line_items)
print(invoice.total_amount)
print(invoice.currency)

# Can also access fields from the raw response object such as the content.

# In this case, the content is the JSON schema representation of the parsed invoice object

print(response.content)
```

### Step 4: Type-safe Output

When using supported schema features, the output will be type-safe and respect the input schema.

```json
{
  "vendor_name": "Acme Corp",
  "vendor_address": {
    "street": "123 Main St",
    "city": "Springfield",
    "postal_code": "62704",
    "country": "IL"
  },
  "invoice_number": "INV-2025-001",
  "invoice_date": "2025-02-10",
  "line_items": [
    { "description": "Widget A", "quantity": 5, "unit_price": 10.0 },
    { "description": "Widget B", "quantity": 2, "unit_price": 15.0 }
  ],
  "total_amount": 80.0,
  "currency": "USD"
}
```

## Structured Outputs with Tools

> [!NOTE]
>
> Structured outputs with tools is only available for supported Grok 4 family models.

You can combine structured outputs with tool calling to get type-safe responses from tool-augmented queries. This works with both:

* **[Agentic tool calling](/developers/tools/overview)**: Server-side tools like web search, X search, and code execution that the model orchestrates autonomously.
* **[Function calling](/developers/tools/function-calling)**: User-supplied tools where you define custom functions and handle tool execution yourself.

This combination enables workflows where the model can use tools to gather information and return results in a predictable, strongly typed format.

### Example: Agentic Tools with Structured Output

This example uses web search to find the latest research on a topic and extracts structured data into a schema:

```python customLanguage="pythonWithoutSDK"
from pydantic import BaseModel, Field

class ProofInfo(BaseModel):
    name: str = Field(description="Name of the proof or paper")
    authors: str = Field(description="Authors of the proof")
    year: str = Field(description="Year published")
    summary: str = Field(description="Brief summary of the approach")
```

```javascript customLanguage="javascriptWithoutSDK"
import { z } from "zod";

const ProofInfoSchema = z.object({
    name: z.string().describe("Name of the proof or paper"),
    authors: z.string().describe("Authors of the proof"),
    year: z.string().describe("Year published"),
    summary: z.string().describe("Brief summary of the approach"),
});
```

```python customLanguage="pythonOpenAISDK"
import os
from openai import OpenAI
from pydantic import BaseModel, Field

# ProofInfo schema defined above

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

response = client.responses.parse(
    model="grok-4.7",
    input="Find the latest machine-checked proof of the four color theorem.",
    tools=[
        {"type": "web_search"}
    ],
    text_format=ProofInfo,
)

proof = response.output_parsed
print(f"Name: {proof.name}")
print(f"Authors: {proof.authors}")
print(f"Year: {proof.year}")
print(f"Summary: {proof.summary}")
```

```javascript customLanguage="javascriptOpenAISDK"
import OpenAI from "openai";
import { zodResponseFormat } from "openai/helpers/zod";
import { z } from "zod";

// ProofInfoSchema defined above

const client = new OpenAI({
    apiKey: process.env.XAI_API_KEY,
    baseURL: "https://api.x.ai/v1",
});

// Convert Zod schema to JSON schema format
const format = zodResponseFormat(ProofInfoSchema, "proof_info");

const response = await client.responses.create({
    model: "grok-4.7",
    input: "Find the latest machine-checked proof of the four color theorem.",
    tools: [
        { type: "web_search" }
    ],
    text: {
        format: {
            type: "json_schema",
            name: format.json_schema.name,
            schema: format.json_schema.schema,
            strict: true,
        }
    }
});

// Find the message in the output array
const message = response.output.find((item) => item.type === "message");
const textContent = message?.content?.find((c) => c.type === "output_text");

if (textContent) {
    const proof = JSON.parse(textContent.text);
    console.log(`Name: ${proof.name}`);
    console.log(`Authors: ${proof.authors}`);
    console.log(`Year: ${proof.year}`);
    console.log(`Summary: ${proof.summary}`);
}
```

```python customLanguage="pythonXAI"
import os
from pydantic import BaseModel, Field

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search

# ProofInfo schema defined above

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(
    model="grok-4.7",
    tools=[web_search()],
)

chat.append(user("Find the latest machine-checked proof of the four color theorem."))

response, proof = chat.parse(ProofInfo)

print(f"Name: {proof.name}")
print(f"Authors: {proof.authors}")
print(f"Year: {proof.year}")
print(f"Summary: {proof.summary}")
```

### Example: Client-side Tools with Structured Output

This example uses a client-side function tool to compute Collatz sequence steps and returns the result in a structured format:

```python customLanguage="pythonWithoutSDK"
from pydantic import BaseModel, Field

class CollatzResult(BaseModel):
    starting_number: int = Field(description="The input number")
    steps: int = Field(description="Number of steps to reach 1")
```

```javascript customLanguage="javascriptWithoutSDK"
const CollatzResultSchema = {
    type: "object",
    properties: {
        starting_number: { type: "integer", description: "The input number" },
        steps: { type: "integer", description: "Number of steps to reach 1" },
    },
    required: ["starting_number", "steps"],
    additionalProperties: false,
};
```

```python customLanguage="pythonOpenAISDK"
import os
import json
from openai import OpenAI
from pydantic import BaseModel, Field

# CollatzResult schema defined above

def collatz_steps(n: int) -> int:
    """Returns the number of steps for n to reach 1 in the Collatz sequence."""
    steps = 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "collatz_steps",
            "description": "Compute the number of steps for a number to reach 1 in the Collatz sequence",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "The starting number"},
                },
                "required": ["n"],
            },
        },
    }
]

messages = [
    {"role": "user", "content": "Use the collatz_steps tool to find how many steps it takes for 20250709 to reach 1."}
]

# Handle tool calls until we get a final response
while True:
    completion = client.chat.completions.create(
        model="grok-4.7",
        messages=messages,
        tools=tools,
    )
    
    message = completion.choices[0].message
    
    if not message.tool_calls:
        break
    
    messages.append(message)
    for tc in message.tool_calls:
        args = json.loads(tc.function.arguments)
        result = collatz_steps(args["n"])
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": str(result),
        })

# Final call with structured output
completion = client.beta.chat.completions.parse(
    model="grok-4.7",
    messages=messages,
    response_format=CollatzResult,
)

result = completion.choices[0].message.parsed
print(f"Starting number: {result.starting_number}")
print(f"Steps to reach 1: {result.steps}")
```

```javascript customLanguage="javascriptOpenAISDK"
import OpenAI from "openai";

// CollatzResultSchema defined above

function collatzSteps(n) {
    let steps = 0;
    while (n !== 1) {
        n = n % 2 === 0 ? n / 2 : 3 * n + 1;
        steps++;
    }
    return steps;
}

const client = new OpenAI({
    apiKey: process.env.XAI_API_KEY,
    baseURL: "https://api.x.ai/v1",
});

const tools = [
    {
        type: "function",
        function: {
            name: "collatz_steps",
            description: "Compute the number of steps for a number to reach 1 in the Collatz sequence",
            parameters: {
                type: "object",
                properties: {
                    n: { type: "integer", description: "The starting number" },
                },
                required: ["n"],
            },
        },
    },
];

let messages = [
    { role: "user", content: "Use the collatz_steps tool to find how many steps it takes for 20250709 to reach 1." }
];

// Handle tool calls until we get a final response
while (true) {
    const completion = await client.chat.completions.create({
        model: "grok-4.7",
        messages,
        tools,
    });

    const message = completion.choices[0].message;

    if (!message.tool_calls) {
        break;
    }

    messages.push(message);
    for (const tc of message.tool_calls) {
        const args = JSON.parse(tc.function.arguments);
        const result = collatzSteps(args.n);
        messages.push({
            role: "tool",
            tool_call_id: tc.id,
            content: String(result),
        });
    }
}

// Final call with structured output
const completion = await client.chat.completions.create({
    model: "grok-4.7",
    messages,
    response_format: {
        type: "json_schema",
        json_schema: {
            name: "collatz_result",
            schema: CollatzResultSchema,
            strict: true,
        },
    },
});

const result = JSON.parse(completion.choices[0].message.content);
console.log("Starting number:", result.starting_number);
console.log("Steps to reach 1:", result.steps);
```

```python customLanguage="pythonXAI"
import os
import json
from pydantic import BaseModel, Field

from xai_sdk import Client
from xai_sdk.chat import tool, tool_result, user

# CollatzResult schema defined above

def collatz_steps(n: int) -> int:
    """Returns the number of steps for n to reach 1 in the Collatz sequence."""
    steps = 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps

collatz_tool = tool(
    name="collatz_steps",
    description="Compute the number of steps for a number to reach 1 in the Collatz sequence",
    parameters={
        "type": "object",
        "properties": {
            "n": {"type": "integer", "description": "The starting number"},
        },
        "required": ["n"],
    },
)

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(
    model="grok-4.7",
    tools=[collatz_tool],
)

chat.append(user("Use the collatz_steps tool to find how many steps it takes for 20250709 to reach 1."))

# Handle tool calls until we get a final response
while True:
    response = chat.sample()
    
    if not response.tool_calls:
        break
    
    chat.append(response)
    for tc in response.tool_calls:
        args = json.loads(tc.function.arguments)
        result = collatz_steps(args["n"])
        chat.append(tool_result(str(result)))

# Parse the final response into structured output
response, result = chat.parse(CollatzResult)

print(f"Starting number: {result.starting_number}")
print(f"Steps to reach 1: {result.steps}")
```

## Alternative: Using `response_format` with `sample()` or `stream()`

When using the xAI Python SDK, there's an alternative way to retrieve structured outputs. Instead of using the `parse()` method, you can pass your Pydantic model directly to the `response_format` parameter when creating a chat, and then use `sample()` or `stream()` to get the response.

### How It Works

When you pass a Pydantic model to `response_format`, the SDK automatically:

1. Converts your Pydantic model to a JSON schema
2. Constrains the model's output to conform to that schema
3. Returns the response as a JSON string, that is conforming to the Pydantic model, in `response.content`

You then manually parse the JSON string into your Pydantic model instance.

### Key Differences

| Approach | Method | Returns | Parsing |
|----------|--------|---------|---------|
| **Using `parse()`** | `chat.parse(Model)` | Tuple of `(Response, Model)` | Automatic - SDK parses for you |
| **Using `response_format`** | `chat.sample()` or `chat.stream()` | `Response` with JSON string | Manual - You parse `response.content` |

### When to Use Each Approach

* **Use `parse()`** when you want the simplest, most convenient experience with automatic parsing
* **Use `response_format` + `sample()` or `stream()`** when you:
  * Want more control over the parsing process
  * Need to handle the raw JSON string before parsing
  * Want to use streaming with structured outputs
  * Are integrating with existing code that expects to work with `sample()` or `stream()`

### Example Using `response_format`

```pythonXAI
import os
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field
from xai_sdk import Client
from xai_sdk.chat import system, user

# Pydantic Schemas
class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class LineItem(BaseModel):
    description: str = Field(description="Description of the item or service")
    quantity: int = Field(description="Number of units", ge=1)
    unit_price: float = Field(description="Price per unit", ge=0)


class Address(BaseModel):
    street: str = Field(description="Street address")
    city: str = Field(description="City")
    postal_code: str = Field(description="Postal/ZIP code")
    country: str = Field(description="Country")


class Invoice(BaseModel):
    vendor_name: str = Field(description="Name of the vendor")
    vendor_address: Address = Field(description="Vendor's address")
    invoice_number: str = Field(description="Unique invoice identifier")
    invoice_date: date = Field(description="Date the invoice was issued")
    line_items: list[LineItem] = Field(description="List of purchased items/services")
    total_amount: float = Field(description="Total amount due", ge=0)
    currency: Currency = Field(description="Currency of the invoice")


client = Client(api_key=os.getenv("XAI_API_KEY"))

# Pass the Pydantic model to response_format instead of using parse()
chat = client.chat.create(
    model="grok-4.7",
    response_format=Invoice,  # Pass the Pydantic model here
)

chat.append(system("Given a raw invoice, carefully analyze the text and extract the invoice data into JSON format."))
chat.append(
    user("""
Vendor: Acme Corp, 123 Main St, Springfield, IL 62704
Invoice Number: INV-2025-001
Date: 2025-02-10
Items: - Widget A, 5 units, $10.00 each - Widget B, 2 units, $15.00 each
Total: $80.00 USD
""")
)

# Use sample() instead of parse() - returns Response object
response = chat.sample()

# The response.content is a valid JSON string conforming to your schema
print(response.content)
# Output: {"vendor_name": "Acme Corp", "vendor_address": {...}, ...}

# Manually parse the JSON string into your Pydantic model
invoice = Invoice.model_validate_json(response.content)
assert isinstance(invoice, Invoice)

# Access fields of the parsed invoice object
print(invoice.vendor_name)
print(invoice.invoice_number)
print(invoice.total_amount)
```

### Streaming with Structured Outputs

You can also use `stream()` with `response_format` to get streaming structured output. The chunks will progressively build up the JSON string:

```pythonXAI
import os

from pydantic import BaseModel, Field
from xai_sdk import Client
from xai_sdk.chat import system, user


class Summary(BaseModel):
    title: str = Field(description="A brief title")
    key_points: list[str] = Field(description="Main points from the text")
    sentiment: str = Field(description="Overall sentiment: positive, negative, or neutral")


client = Client(api_key=os.getenv("XAI_API_KEY"))

chat = client.chat.create(
    model="grok-4.7",
    response_format=Summary,  # Pass the Pydantic model here
)

chat.append(system("Analyze the following text and provide a structured summary."))
chat.append(user("The new product launch exceeded expectations with record sales..."))


# Stream the response - chunks contain partial JSON
for response, chunk in chat.stream():
    print(chunk.content, end="", flush=True)


# Parse the complete JSON string into your model
summary = Summary.model_validate_json(response.content)
print(f"Title: {summary.title}")
print(f"Sentiment: {summary.sentiment}")
```


---

Source: https://docs.x.ai/developers/model-capabilities/text/multi-agent

#### Model Capabilities

# Multi Agent

> [!WARNING]
>
> This feature is currently in **beta**. The API interface and behavior may change as we iterate. Please bear in mind that the API interface is not final and may include breaking changes down the line.

Realtime Multi-agent Research enables Grok to orchestrate multiple AI agents that work together in real time to perform deep, multi-step research tasks. Agents specialize in particular aspects of the research (searching the web, analyzing data, synthesizing findings) and collaborate to deliver comprehensive, well-sourced answers.

## Overview

Multi-agent research goes beyond single-turn tool use by coordinating a team of specialized agents that can:

* **Search and gather** information from multiple sources simultaneously
* **Analyze and cross-reference** findings across different domains
* **Synthesize** comprehensive answers with citations and supporting evidence
* **Iterate** on research in real time, refining results based on intermediate findings

## Getting Started

To use Realtime Multi-agent Research, specify `grok-4.20-multi-agent` as the model name in your API requests. This model is optimized for orchestrating multiple agents that collaborate on research tasks.

```typescript customLanguage="javascriptAISDK" highlightedLines="5"
import { xai } from "@ai-sdk/xai";
import { generateText } from "ai";

const { text } = await generateText({
  model: xai.responses("grok-4.20-multi-agent"),
  prompt:
    "Research the latest breakthroughs in quantum computing and summarize the key findings.",
  tools: {
    web_search: xai.tools.webSearch(),
    x_search: xai.tools.xSearch(),
  },
});

console.log(text);
```

```python customLanguage="pythonOpenAISDK" highlightedLines="10"
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

response = client.responses.create(
    model="grok-4.20-multi-agent",
    input=[
        {
            "role": "user",
            "content": "Research the latest breakthroughs in quantum computing and summarize the key findings.",
        },
    ],
    tools=[
        {"type": "web_search"},
        {"type": "x_search"},
    ],
)

print(response)
```

```python customLanguage="pythonRequests" highlightedLines="10"
import os
import requests

url = "https://api.x.ai/v1/responses"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"
}
payload = {
    "model": "grok-4.20-multi-agent",
    "input": [
        {
            "role": "user",
            "content": "Research the latest breakthroughs in quantum computing and summarize the key findings."
        }
    ],
    "tools": [
        {"type": "web_search"},
        {"type": "x_search"}
    ]
}
response = requests.post(url, headers=headers, json=payload)
print(response.json())
```

```bash customLanguage="bash" highlightedLines="5"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{
  "model": "grok-4.20-multi-agent",
  "input": [
    {
      "role": "user",
      "content": "Research the latest breakthroughs in quantum computing and summarize the key findings."
    }
  ],
  "tools": [
    {"type": "web_search"},
    {"type": "x_search"}
  ]
}'
```

```python customLanguage="pythonXAI" highlightedLines="9"
import os

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search, x_search

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(
    model="grok-4.20-multi-agent",
    tools=[web_search(), x_search()],
    include=["verbose_streaming"],
)

chat.append(user("Research the latest breakthroughs in quantum computing and summarize the key findings."))

is_thinking = True
for response, chunk in chat.stream():
    if response.usage.reasoning_tokens and is_thinking:
        print(f"\rThinking... ({response.usage.reasoning_tokens} tokens)", end="", flush=True)
    if chunk.content and is_thinking:
        print("\n\nFinal Response:")
        is_thinking = False
    if chunk.content and not is_thinking:
        print(chunk.content, end="", flush=True)

print("\n\nUsage:")
print(response.usage)
```

## How Multi-agent Works

When you send a request to the multi-agent model, multiple agents are launched to discuss and collaborate on your query. Each agent contributes its own perspective, reasoning, and findings. A designated **leader agent** is responsible for synthesizing the discussion and presenting the final answer back to you.

### Supported Models

* `grok-4.20-multi-agent`

### Built-in Tools Support

SpaceXSI provides a set of built-in tools you can enable in the request to help with the most common use cases, e.g., `web_search`, `x_search`, `code_execution`, `collections_search`. Check out [this doc](/developers/tools/overview) for more information.

Once you enable those tools in the request, the server will perform the agent loop to invoke those tools on the server side based on your query until the final answer is generated.

> [!NOTE]
>
> Using built-in tools will incur an additional cost. Please review the [pricing details for built-in tools](/developers/pricing#tools-pricing).

### Output Behavior

Only the **tool calls** and the **final response** from the leader agent are sent back to the user. All sub-agent state — including their intermediate reasoning, tool calls, and outputs — is encrypted and included in the response only when `use_encrypted_content` is set to `True` in the xAI SDK. This keeps the default response clean and focused while still allowing you to preserve the full multi-agent context for multi-turn conversations.

## Configuration

You can configure how many agents collaborate on a request. The two available setups are **4 agents** and **16 agents**. More agents means deeper, more thorough research at the cost of higher token usage and latency.

| SDK / API | Parameter | 4 Agents | 16 Agents |
|---|---|---|---|
| xAI SDK | `agent_count` | `4` | `16` |
| OpenAI SDK | `reasoning.effort` | `"low"` or `"medium"` | `"high"` or `"xhigh"` |
| Vercel AI SDK | `reasoningEffort` | `"low"` or `"medium"` | `"high"` or `"xhigh"` |
| REST API | `reasoning.effort` | `"low"` or `"medium"` | `"high"` or `"xhigh"` |

**Best For:** Use 4 agents for quick research and focused queries. Use 16 agents for deep research and complex multi-faceted topics.

### 4-Agent Setup

```typescript customLanguage="javascriptAISDK" highlightedLines="5,8"
import { xai } from "@ai-sdk/xai";
import { generateText } from "ai";

const { text } = await generateText({
  model: xai.responses("grok-4.20-multi-agent"),
  prompt: "What are the key differences between TCP and UDP?",
  providerOptions: {
    xai: { reasoningEffort: "low" },
  },
});

console.log(text);
```

```python customLanguage="pythonOpenAISDK" highlightedLines="10,11"
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

response = client.responses.create(
    model="grok-4.20-multi-agent",
    reasoning={"effort": "low"},
    input=[
        {
            "role": "user",
            "content": "What are the key differences between TCP and UDP?",
        },
    ],
)

print(response.output_text)
```

```python customLanguage="pythonRequests" highlightedLines="10,11"
import os
import requests

url = "https://api.x.ai/v1/responses"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"
}
payload = {
    "model": "grok-4.20-multi-agent",
    "reasoning": {"effort": "low"},
    "input": [
        {
            "role": "user",
            "content": "What are the key differences between TCP and UDP?"
        }
    ]
}
response = requests.post(url, headers=headers, json=payload)
print(response.json())
```

```bash customLanguage="bash" highlightedLines="5,6"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{
  "model": "grok-4.20-multi-agent",
  "reasoning": {"effort": "low"},
  "input": [
    {
      "role": "user",
      "content": "What are the key differences between TCP and UDP?"
    }
  ]
}'
```

```python customLanguage="pythonXAI" highlightedLines="8,9"
import os

from xai_sdk import Client
from xai_sdk.chat import user

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(
    model="grok-4.20-multi-agent",
    agent_count=4,
)

chat.append(user("What are the key differences between TCP and UDP?"))
for response, chunk in chat.stream():
    if chunk.content:
        print(chunk.content, end="", flush=True)
```

### 16-Agent Setup

```typescript customLanguage="javascriptAISDK" highlightedLines="5,9"
import { xai } from "@ai-sdk/xai";
import { generateText } from "ai";

const { text } = await generateText({
  model: xai.responses("grok-4.20-multi-agent"),
  prompt:
    "Analyze the design trade-offs in modern programming languages: compare Rust's ownership model, Go's simplicity philosophy, and Haskell's pure functional approach. Cover memory safety, concurrency, developer productivity, and ecosystem maturity.",
  providerOptions: {
    xai: { reasoningEffort: "high" },
  },
});

console.log(text);
```

```python customLanguage="pythonOpenAISDK" highlightedLines="10,11"
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

response = client.responses.create(
    model="grok-4.20-multi-agent",
    reasoning={"effort": "high"},
    input=[
        {
            "role": "user",
            "content": "Analyze the design trade-offs in modern programming languages: compare Rust's ownership model, Go's simplicity philosophy, and Haskell's pure functional approach. Cover memory safety, concurrency, developer productivity, and ecosystem maturity.",
        },
    ],
)

print(response.output_text)
```

```python customLanguage="pythonRequests" highlightedLines="10,11"
import os
import requests

url = "https://api.x.ai/v1/responses"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"
}
payload = {
    "model": "grok-4.20-multi-agent",
    "reasoning": {"effort": "high"},
    "input": [
        {
            "role": "user",
            "content": "Analyze the design trade-offs in modern programming languages: compare Rust's ownership model, Go's simplicity philosophy, and Haskell's pure functional approach. Cover memory safety, concurrency, developer productivity, and ecosystem maturity."
        }
    ]
}
response = requests.post(url, headers=headers, json=payload)
print(response.json())
```

```bash customLanguage="bash" highlightedLines="5,6"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{
  "model": "grok-4.20-multi-agent",
  "reasoning": {"effort": "high"},
  "input": [
    {
      "role": "user",
      "content": "Analyze the design trade-offs in modern programming languages: compare Rust'\''s ownership model, Go'\''s simplicity philosophy, and Haskell'\''s pure functional approach. Cover memory safety, concurrency, developer productivity, and ecosystem maturity."
    }
  ]
}'
```

```python customLanguage="pythonXAI" highlightedLines="8,9"
import os

from xai_sdk import Client
from xai_sdk.chat import user

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(
    model="grok-4.20-multi-agent",
    agent_count=16,
)

chat.append(user("Analyze the design trade-offs in modern programming languages: compare Rust's ownership model, Go's simplicity philosophy, and Haskell's pure functional approach. Cover memory safety, concurrency, developer productivity, and ecosystem maturity."))
for response, chunk in chat.stream():
    if chunk.content:
        print(chunk.content, end="", flush=True)
```

> [!NOTE]
>
> The 16-agent setup uses significantly more tokens than the 4-agent setup. Choose the agent count based on the complexity of your research task — use 4 agents for focused queries and 16 agents when you need comprehensive, multi-perspective analysis.

## Common Patterns

### Without Built-in Tools

Multi-agent works without any built-in tools — the agents rely purely on their collective knowledge and reasoning to collaborate on a response.

```typescript customLanguage="javascriptAISDK"
import { xai } from "@ai-sdk/xai";
import { generateText } from "ai";

const { text } = await generateText({
  model: xai.responses("grok-4.20-multi-agent"),
  prompt:
    "Compare the major approaches to distributed consensus in computer science: Paxos, Raft, and Byzantine fault tolerance. Analyze the trade-offs in safety guarantees, performance, and implementation complexity.",
});

console.log(text);
```

```python customLanguage="pythonOpenAISDK"
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

response = client.responses.create(
    model="grok-4.20-multi-agent",
    input=[
        {
            "role": "user",
            "content": "Compare the major approaches to distributed consensus in computer science: Paxos, Raft, and Byzantine fault tolerance. Analyze the trade-offs in safety guarantees, performance, and implementation complexity.",
        },
    ],
)

print(response)
```

```python customLanguage="pythonRequests"
import os
import requests

url = "https://api.x.ai/v1/responses"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"
}
payload = {
    "model": "grok-4.20-multi-agent",
    "input": [
        {
            "role": "user",
            "content": "Compare the major approaches to distributed consensus in computer science: Paxos, Raft, and Byzantine fault tolerance. Analyze the trade-offs in safety guarantees, performance, and implementation complexity."
        }
    ]
}
response = requests.post(url, headers=headers, json=payload)
print(response.json())
```

```bash customLanguage="bash"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{
  "model": "grok-4.20-multi-agent",
  "input": [
    {
      "role": "user",
      "content": "Compare the major approaches to distributed consensus in computer science: Paxos, Raft, and Byzantine fault tolerance. Analyze the trade-offs in safety guarantees, performance, and implementation complexity."
    }
  ]
}'
```

```python customLanguage="pythonXAI"
import os

from xai_sdk import Client
from xai_sdk.chat import user

client = Client(api_key=os.getenv("XAI_API_KEY"))
chat = client.chat.create(
    model="grok-4.20-multi-agent",
    include=["verbose_streaming"],
)

chat.append(user("Compare the major approaches to distributed consensus in computer science: Paxos, Raft, and Byzantine fault tolerance. Analyze the trade-offs in safety guarantees, performance, and implementation complexity."))

is_thinking = True
for response, chunk in chat.stream():
    if response.usage.reasoning_tokens and is_thinking:
        print(f"\rThinking... ({response.usage.reasoning_tokens} tokens)", end="", flush=True)
    if chunk.content and is_thinking:
        print("\n\nFinal Response:")
        is_thinking = False
    if chunk.content and not is_thinking:
        print(chunk.content, end="", flush=True)

print("\n\nUsage:")
print(response.usage)
```

### Multi-turn Conversation

Multi-agent research supports multi-turn conversations using `previous_response_id`, just like any other model. You can ask follow-up questions to refine or expand on previous research results, and the agents will use the prior context to deliver more targeted answers.

For the full multi-turn conversation pattern with reusable functions and code examples, see [Chaining the conversation](/developers/model-capabilities/text/generate-text#chaining-the-conversation).

## Pricing

All tokens consumed by both the **leader agent** and **sub-agents** are billed, including input tokens, output tokens, and reasoning tokens. Similarly, all **server-side tool calls** made by any agent — whether the leader or a sub-agent — count toward your tool usage and are billed accordingly.

Because multiple agents may run in parallel and each can independently invoke tools, a single multi-agent request may use significantly more tokens and tool calls than a standard single-agent request. You can monitor your usage via the `usage` and `server_side_tool_usage` fields in the response.

For detailed pricing information, see the [Pricing](/developers/pricing) page and the [Tool Pricing](/developers/pricing#tools-pricing) page.

## Prompting Guide

Getting the most out of multi-agent research starts with how you frame your request. Here are patterns that work well:

**Set the scope and depth explicitly**

Rather than asking a broad question, tell the agents exactly what dimensions to cover:

```text
❌  "Tell me about electric vehicles."
✅  "Compare the top 3 EV manufacturers by battery technology, range, charging infrastructure, and 2025 sales projections."
```

**Ask for structured output**

Multi-agent research excels when you request organized, structured responses:

```text
✅  "Research the pros and cons of microservices vs monolithic architecture. Present your findings as a comparison table with categories: scalability, complexity, deployment, and team size requirements."
```

**Specify sources or perspectives**

Guide the agents toward the types of evidence you value:

```text
✅  "Analyze the environmental impact of large language model training, citing recent academic papers and industry reports from 2024-2025."
```

**Break complex research into a conversation**

For deep topics, start broad and narrow down with follow-ups rather than packing everything into one prompt:

```text
Turn 1: "What are the leading approaches to carbon capture technology?"
Turn 2: "Which of those has the best cost-per-ton economics today?"
Turn 3: "What are the main engineering challenges preventing that approach from scaling?"
```

**Provide context when relevant**

If your research builds on prior knowledge or specific constraints, include that context in the prompt:

```text
✅  "I'm building a fintech app targeting Southeast Asian markets. Research the regulatory requirements for digital payments in Singapore, Indonesia, and the Philippines."
```

## Limitations

* **Only leader agent output is exposed:** Only the leader agent's output is returned, including its tool calls and response content. Sub-agent state is encrypted and only included when `use_encrypted_content` is enabled — see [Output Behavior](#output-behavior) for details.
* **No client-side or custom tools:** Client-side tools (function calling) and custom tools are not currently supported by the multi-agent model variant. We do support a set of built-in tools (e.g., `web_search`, `x_search`) and remote MCP tools. See our [built-in tool docs](/developers/tools/overview) for more details.
* **Chat Completions API not supported:** The multi-agent model does **not** work with the OpenAI Chat Completions API. Use the [xAI SDK](https://github.com/xai-org/xai-sdk-python) or the [Responses API](/developers/model-capabilities/text/generate-text) instead.
* **`max_tokens` is not supported:** The `max_tokens` parameter is not currently supported by the multi-agent model variant.


---

Source: https://docs.x.ai/developers/tools/function-calling

#### Tools

# Function Calling

Define custom tools that the model can invoke during a conversation. The model requests the call, you execute it locally, and return the result. This enables integration with databases, APIs, and any external system.

> [!WARNING]
>
> With streaming, the function call is returned in whole in a single chunk, not streamed across chunks.

1. Define tools with a name, description, and JSON schema for parameters
2. Include tools in your request
3. Model returns a `tool_call` when it needs external data
4. Execute the function locally and return the result
5. Model continues with your result

## Quick Start

```javascriptAISDK
import { xai } from '@ai-sdk/xai';
import { streamText, tool, stepCountIs } from 'ai';
import { z } from 'zod';

const result = streamText({
  model: xai.responses('grok-4.7'),
  tools: {
    getTemperature: tool({
      description: 'Get current temperature for a location',
      inputSchema: z.object({
        location: z.string().describe('City name'),
        unit: z.enum(['celsius', 'fahrenheit']).default('fahrenheit'),
      }),
      execute: async ({ location, unit }) => ({
        location,
        temperature: unit === 'fahrenheit' ? 59 : 15,
        unit,
      }),
    }),
  },
  stopWhen: stepCountIs(5),
  prompt: 'What is the temperature in San Francisco?',
});

for await (const chunk of result.fullStream) {
  if (chunk.type === 'text-delta') {
    process.stdout.write(chunk.text);
  }
}
```

```pythonOpenAISDK
import os
import json
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

tools = [
    {
        "type": "function",
        "name": "get_temperature",
        "description": "Get current temperature for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"], "default": "fahrenheit"}
            },
            "required": ["location"]
        },
    },
]

response = client.responses.create(
    model="grok-4.7",
    input=[{"role": "user", "content": "What is the temperature in San Francisco?"}],
    tools=tools,
)

# Handle function calls
for item in response.output:
    if item.type == "function_call":
        args = json.loads(item.arguments)
        result = {"location": args["location"], "temperature": 59, "unit": args.get("unit", "fahrenheit")}

        response = client.responses.create(
            model="grok-4.7",
            input=[{"type": "function_call_output", "call_id": item.call_id, "output": json.dumps(result)}],
            tools=tools,
            previous_response_id=response.id,
        )

for item in response.output:
    if item.type == "message":
        print(item.content[0].text)
```

```bash customLanguage="bash"
curl https://api.x.ai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{
  "model": "grok-4.7",
  "input": [
    {"role": "user", "content": "What is the temperature in San Francisco?"}
  ],
  "tools": [
    {
      "type": "function",
      "name": "get_temperature",
      "description": "Get current temperature for a location",
      "parameters": {
        "type": "object",
        "properties": {
          "location": {"type": "string", "description": "City name"},
          "unit": {"type": "string", "enum": ["celsius", "fahrenheit"], "default": "fahrenheit"}
        },
        "required": ["location"]
      }
    }
  ]
}'
```

```pythonXAI
import os
import json

from xai_sdk import Client
from xai_sdk.chat import user, tool, tool_result

client = Client(api_key=os.getenv("XAI_API_KEY"))

# Define tools
tools = [
    tool(
        name="get_temperature",
        description="Get current temperature for a location",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"], "default": "fahrenheit"}
            },
            "required": ["location"]
        },
    ),
]

chat = client.chat.create(
    model="grok-4.7",
    tools=tools,
)
chat.append(user("What is the temperature in San Francisco?"))
response = chat.sample()

# Handle tool calls
if response.tool_calls:
    chat.append(response)
    for tc in response.tool_calls:
        args = json.loads(tc.function.arguments)
        # Execute your function
        result = {"location": args["location"], "temperature": 59, "unit": args.get("unit", "fahrenheit")}
        chat.append(tool_result(json.dumps(result)))

    response = chat.sample()

print(response.content)
```

## Defining Tools with Pydantic

Use Pydantic models for type-safe parameter schemas:

```pythonOpenAISDK
from typing import Literal
from pydantic import BaseModel, Field

class TemperatureRequest(BaseModel):
    location: str = Field(description="City and state, e.g. San Francisco, CA")
    unit: Literal["celsius", "fahrenheit"] = Field("fahrenheit", description="Temperature unit")

class CeilingRequest(BaseModel):
    location: str = Field(description="City and state, e.g. San Francisco, CA")

tools = [
    {
        "type": "function",
        "name": "get_temperature",
        "description": "Get current temperature for a location",
        "parameters": TemperatureRequest.model_json_schema(),
    },
    {
        "type": "function",
        "name": "get_ceiling",
        "description": "Get current cloud ceiling for a location",
        "parameters": CeilingRequest.model_json_schema(),
    },
]
```

```pythonXAI
from typing import Literal
from pydantic import BaseModel, Field
from xai_sdk.chat import tool

class TemperatureRequest(BaseModel):
    location: str = Field(description="City and state, e.g. San Francisco, CA")
    unit: Literal["celsius", "fahrenheit"] = Field("fahrenheit", description="Temperature unit")

class CeilingRequest(BaseModel):
    location: str = Field(description="City and state, e.g. San Francisco, CA")

# Generate JSON schema from Pydantic models
tools = [
    tool(
        name="get_temperature",
        description="Get current temperature for a location",
        parameters=TemperatureRequest.model_json_schema(),
    ),
    tool(
        name="get_ceiling",
        description="Get current cloud ceiling for a location",
        parameters=CeilingRequest.model_json_schema(),
    ),
]
```

## Handling Tool Calls

When the model wants to use your tool, execute the function and return the result:

```pythonOpenAISDK
import json

def get_temperature(location: str, unit: str = "fahrenheit") -> dict:
    temp = 59 if unit == "fahrenheit" else 15
    return {"location": location, "temperature": temp, "unit": unit}

tools_map = {"get_temperature": get_temperature}

# Process function calls
for item in response.output:
    if item.type == "function_call":
        name = item.name
        args = json.loads(item.arguments)

        if name not in tools_map:
            output = json.dumps({"error": f"Unknown function: {name}"})
        else:
            output = json.dumps(tools_map[name](**args))

        response = client.responses.create(
            model="grok-4.7",
            input=[{"type": "function_call_output", "call_id": item.call_id, "output": output}],
            tools=tools,
            previous_response_id=response.id,
        )

for item in response.output:
    if item.type == "message":
        print(item.content[0].text)
```

```pythonXAI
import json

def get_temperature(location: str, unit: str = "fahrenheit") -> dict:
    # In production, call a real weather API
    temp = 59 if unit == "fahrenheit" else 15
    return {"location": location, "temperature": temp, "unit": unit}

def get_ceiling(location: str) -> dict:
    return {"location": location, "ceiling": 15000, "unit": "ft"}

tools_map = {
    "get_temperature": get_temperature,
    "get_ceiling": get_ceiling,
}

chat.append(user("What's the weather in Denver?"))
response = chat.sample()

# Process tool calls
if response.tool_calls:
    chat.append(response)

    for tool_call in response.tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        result = tools_map[name](**args)
        chat.append(tool_result(json.dumps(result)))

    response = chat.sample()

print(response.content)
```

## Combining with Built-in Tools

Function calling works alongside built-in agentic tools. The model can use web search, then call your custom function:

```pythonOpenAISDK
tools = [
    {"type": "web_search"},          # Built-in
    {"type": "x_search"},            # Built-in
    {                                # Custom
        "type": "function",
        "name": "save_to_database",
        "description": "Save research results to the database",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data to save"}
            },
            "required": ["data"]
        },
    },
]
```

```pythonXAI
from xai_sdk.chat import tool
from xai_sdk.tools import web_search, x_search

tools = [
    web_search(),                    # Built-in: runs on SpaceXSI servers
    x_search(),                      # Built-in: runs on SpaceXSI servers
    tool(                            # Custom: runs on your side
        name="save_to_database",
        description="Save research results to the database",
        parameters={
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data to save"}
            },
            "required": ["data"]
        },
    ),
]

chat = client.chat.create(
    model="grok-4.7",
    tools=tools,
)
```

When mixing tools:

* **Built-in tools** execute automatically on SpaceXSI servers
* **Custom tools** pause execution and return to you for handling

See [Advanced Usage](/developers/tools/advanced-usage#mixing-server-side-and-client-side-tools) for complete examples with tool loops.

## Tool Choice

Control when the model uses tools:

| Value | Behavior |
|-------|----------|
| `"auto"` | Model decides whether to call a tool (default) |
| `"required"` | Model must call at least one tool |
| `"none"` | Disable tool calling |
| `{"type": "function", "function": {"name": "..."}}` | Force a specific tool |

## Parallel Function Calling

By default, parallel function calling is enabled — the model can request multiple tool calls in a single response. Process all of them before continuing:

```pythonWithoutSDK
# response.tool_calls may contain multiple calls
for tool_call in response.tool_calls:
    result = tools_map[tool_call.function.name](**json.loads(tool_call.function.arguments))
    # Append each result...
```

Disable with `parallel_tool_calls: false` in your request.

## Tool Schema Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier (max 350 tools per request) |
| `description` | No | What the tool does. Treated as empty if omitted; a clear description helps the model decide when to use it |
| `parameters` | Yes | JSON Schema defining function inputs |

### Parameter Schema

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string",
      "description": "City name"
    },
    "unit": {
      "type": "string",
      "enum": ["celsius", "fahrenheit"],
      "default": "celsius"
    }
  },
  "required": ["location"]
}
```

The root of a `parameters` schema must be an object (`"type": "object"`); nest any other types inside `properties`. A root `anyOf` or `oneOf` also works when every branch is itself an object, letting you define a tool that accepts one of several object variants:

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "kind": { "const": "email" },
        "address": { "type": "string" }
      },
      "required": ["kind", "address"]
    },
    {
      "type": "object",
      "properties": {
        "kind": { "const": "sms" },
        "phone": { "type": "string" }
      },
      "required": ["kind", "phone"]
    }
  ]
}
```

> [!WARNING]
>
> A tool whose `parameters` root is neither an object nor a union of objects (for example, a scalar, an array, or an `anyOf`/`oneOf` with a non-object branch) cannot be compiled into a tool-call grammar and is rejected with a `400` error that names the tool.

## Complete Vercel AI SDK Example

The Vercel AI SDK handles tool definition, execution, and the request/response loop automatically:

```javascriptAISDK
import { xai } from '@ai-sdk/xai';
import { streamText, tool, stepCountIs } from 'ai';
import { z } from 'zod';

const result = streamText({
  model: xai.responses('grok-4.7'),
  tools: {
    getCurrentTemperature: tool({
      description: 'Get current temperature for a location',
      inputSchema: z.object({
        location: z.string().describe('City and state, e.g. San Francisco, CA'),
        unit: z.enum(['celsius', 'fahrenheit']).default('fahrenheit'),
      }),
      execute: async ({ location, unit }) => ({
        location,
        temperature: unit === 'fahrenheit' ? 59 : 15,
        unit,
      }),
    }),
    getCurrentCeiling: tool({
      description: 'Get current cloud ceiling for a location',
      inputSchema: z.object({
        location: z.string().describe('City and state'),
      }),
      execute: async ({ location }) => ({
        location,
        ceiling: 15000,
        ceiling_type: 'broken',
        unit: 'ft',
      }),
    }),
  },
  stopWhen: stepCountIs(5),
  prompt: "What's the temperature and cloud ceiling in San Francisco?",
});

for await (const chunk of result.fullStream) {
  switch (chunk.type) {
    case 'text-delta':
      process.stdout.write(chunk.text);
      break;
    case 'tool-call':
      console.log(`Tool call: ${chunk.toolName}`, chunk.input);
      break;
    case 'tool-result':
      console.log(`Tool result: ${chunk.toolName}`, chunk.output);
      break;
  }
}
```

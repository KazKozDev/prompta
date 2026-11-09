# Prompta

Prompta turns a rough stream of thoughts into a ready-to-use prompt. The main app is a native desktop
app ([desktop/README.md](desktop/README.md), `python3 desktop/app.py`); the same pipeline is also
available from the terminal (`npm run pipeline`) and to other agents as an MCP server (`npm run mcp`, see [mcp/README.md](mcp/README.md)).

## ✨ Features

- **Thoughts → brief → prompt** — the request is parsed into a brief (goal, format, constraints, assumptions),
  plus up to 3 questions about missing facts; answer them and rebuild for a sharper prompt.
- **Technique catalog** — 89 prompting techniques with sources (`catalog/catalog.json`); for the "Any" target the
  cheapest technique that fits is chosen automatically, or pick techniques by hand.
- **Official guidance targets** — Claude, ChatGPT, Gemini and Grok prompts are built only from saved official
  rule sets with verified source links; open-weight models use their own saved guides.
- **Zero-shot baseline** — every result has a plain zero-shot tab to compare against, and each variant says what
  it adds over it.
- **LLM providers** — Gemini, OpenAI or a local Ollama model write the prompts.

## 🧩 Пайплайн: мысли → промпт (beta)

Отдельно от UI живёт пайплайн `pipeline/`: разбирает сырой поток мыслей в бриф, детерминированно
отсеивает техники по бюджету и применимости, выбирает самую дешёвую подходящую и собирает промпт по
каркасу техники из `catalog/catalog.json` (89 техник: 64 с шаблоном синтеза, 18 процедур с шагами, 7 настроек и рисков).

```bash
npm test               # 49 проверок, офлайн, без ключей
npm run pipeline "…"    # живой прогон (Gemini / OpenAI / Ollama)
npm run eval -- --ids meeting-actions,tickets-classify --repeat 3   # качество и дрейф выбора
node eval/calibrate.ts --hard --provider ollama --model glm-5.3:cloud  # проверка: судья ↔ точность
```

Интерфейс теперь состоит из одного экрана: **«Пайплайн: поток мыслей → промпт»** и компактного блока
настроек модели. Ручной режим с чекбоксами техник удалён — он дублировал пайплайн. Галочка
«без LLM-синтеза» переключает на быстрый офлайн-режим.

Подробности — [pipeline/README.md](pipeline/README.md), схема каталога — [catalog/README.md](catalog/README.md), измерение качества — [eval/README.md](eval/README.md).

## 🎯 Supported Prompt Techniques

### Basic Techniques
- **Zero-Shot Prompting** - Direct queries without examples
- **Few-Shot Prompting** - Learning from input-output examples
- **Role Prompting** - Assigning expert roles to the model

### Advanced Reasoning
- **Chain-of-Thought** - Step-by-step reasoning processes
- **Tree of Thoughts** - Multiple solution path exploration
- **Graph of Thoughts** - Complex dependency modeling
- **ReAct** - Reasoning and Acting in structured cycles

### Meta-Cognitive Approaches
- **Self-Consistency** - Multiple solution verification
- **Self-Critique** - Critical evaluation of responses
- **Metacognitive Prompting** - Thinking about thinking
- **Reflection** - Post-solution analysis

### Modern Techniques (2023-2025)
- **Meta-Prompting** - LM conducting multiple expert queries
- **TextGrad Optimization** - Automatic prompt improvement
- **System Prompt Optimization** - Meta-learning approaches
- **Visual Chain-of-Thought** - Multimodal reasoning

## 🔧 Supported LLM Providers

### 🤖 Google Gemini
- **Models**: `gemini-2.5-flash-preview-04-17`, `gemini-pro`, etc.
- **Setup**: Requires API key from [Google AI Studio](https://makersuite.google.com/)
- **Cost**: Pay-per-use

### 🏠 Ollama (Local)
- **Models**: `llama3.2`, `llama2`, `codellama`, `mistral`, etc.
- **Setup**: Runs locally, no API key required
- **Cost**: Free (after initial setup)
- **Privacy**: Complete data privacy, offline capable

### 🔮 OpenAI
- **Models**: `gpt-4o`, `gpt-4`, `gpt-3.5-turbo`, etc.
- **Setup**: Requires API key from [OpenAI Platform](https://platform.openai.com/)
- **Cost**: Pay-per-use

## 🚀 Quick Start

### Prerequisites
- **Node.js** (v16 or higher)
- **npm** or **yarn**

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/KazKozDev/prompt-engineering-studio.git
   cd prompt-engineering-studio
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Choose your LLM provider and set it up:**

#### Option A: Google Gemini
```bash
# Create .env.local file
echo "GEMINI_API_KEY=your_api_key_here" > .env.local
```

#### Option B: OpenAI
```bash
# Create .env.local file
echo "OPENAI_API_KEY=your_api_key_here" > .env.local
```

#### Option C: Ollama (Local)
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama server
ollama serve

# Pull a model (in another terminal)
ollama pull llama3.2
```

4. **Start the development server**
   ```bash
   npm run dev
   ```

5. **Open in browser**
   ```
   http://localhost:5173
   ```

## 🔧 Usage

1. **Configure LLM Provider**
   - Select your provider (Gemini/Ollama) from the dropdown
   - Enter model name (e.g., `llama3.2` for Ollama)
   - For Gemini: Enter your API key
   - Click "Save LLM Settings"

2. **Enter Your Query**
   - Type your question or task in the text area
   - Example: "Explain quantum computing"

3. **Select Techniques**
   - Choose one or more prompt engineering techniques
   - Use "Select All" for comprehensive analysis

4. **Generate Enhanced Prompts**
   - Click "Generate Enhanced Prompts"
   - Wait for AI to create optimized versions
   - Copy and use the generated prompts with any LLM

## 📊 Example Transformation

**Input Query:**
```
"Explain machine learning"
```

**Chain-of-Thought Enhanced:**
```
You are an expert in machine learning and data science. I need you to explain machine learning in a comprehensive way using step-by-step reasoning.

Please follow this structure:
1. First, define what machine learning is at its core
2. Then, explain the main types of machine learning
3. Provide concrete examples for each type
4. Explain how the learning process works
5. Discuss practical applications
6. Finally, summarize the key concepts

Please think through each step carefully and show your reasoning process as you build up the explanation from basic concepts to more complex applications.
```

## 🧪 Testing

### Test Ollama Connection
```bash
node test-ollama.js
```

### Run in Development
```bash
npm run dev
```

### Build for Production
```bash
npm run build
npm run preview
```

## 📚 Academic References

This project implements techniques from cutting-edge research papers:

- **Chain-of-Thought**: Wei et al. (2022) - [arXiv:2201.11903](https://arxiv.org/abs/2201.11903)
- **Tree of Thoughts**: Yao et al. (2023) - [arXiv:2305.10601](https://arxiv.org/abs/2305.10601)
- **ReAct**: Yao et al. (2022) - [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
- **Meta-Prompting**: Suzgun & Kalai (2024) - [arXiv:2401.12954](https://arxiv.org/abs/2401.12954)
- [... and 22+ more techniques with full citations]

## 🛠️ Tech Stack

- **Frontend**: TypeScript, HTML5, CSS3
- **Build Tool**: Vite
- **LLM Integration**: Google GenAI SDK, Ollama API
- **Styling**: Modern CSS with responsive design
- **Icons**: Material Symbols

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit changes**: `git commit -m 'Add amazing feature'`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request**

### Adding New Techniques
To add a new prompt engineering technique:

1. Add the technique object to `promptTechniques` array in `index.tsx`
2. Include proper academic citation
3. Test with multiple LLM providers
4. Update documentation

### Adding New LLM Providers
1. Extend the `initializeGenAI()` function
2. Add provider-specific UI elements
3. Update configuration handling
4. Add comprehensive error handling

---

If you like this project, please give it a star ⭐

For questions, feedback, or support, reach out to:

[Artem KK](https://www.linkedin.com/in/kazkozdev/) | MIT [LICENSE](LICENSE) 
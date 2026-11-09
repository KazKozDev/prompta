import { useState, useEffect } from "react";
import LoadingScreen from "./LoadingScreen/LoadingScreen.jsx";
import "./LoadingScreen/LoadingScreen.css";
import "./index.css";
import { runPipeline } from './pipeline/index.ts';
import { loadCatalog } from './pipeline/catalog.ts';
import { createLLM } from './pipeline/llm.ts';
import { escapeHtml, renderPipelineResult } from './pipeline/render.ts';
import { generateManualPrompt } from './pipeline/manual.ts';
import catalogJson from './catalog/catalog.json';

const CATALOG = loadCatalog(catalogJson);
const MANUAL_TECHNIQUES = CATALOG.techniques.filter((t) => t.status === 'ready');
const PROCEDURES = CATALOG.techniques.filter((t) => t.status === 'procedure');

let currentProvider: string = 'ollama';
let currentModel: string = '';
let currentApiKey: string = '';

function getLLMConfigFromUI() {
  const providerSelect = document.getElementById('llm-provider') as HTMLSelectElement;
  const modelSelect = document.getElementById('llm-model') as HTMLSelectElement;
  const apiKeyInput = document.getElementById('llm-api-key') as HTMLInputElement;
  
  if (providerSelect && modelSelect && apiKeyInput) {
    const oldProvider = currentProvider;
    currentProvider = providerSelect.value;
    
    // If provider changed or model list is empty, update model options
    if (oldProvider !== currentProvider || modelSelect.options.length === 0) {
      updateModelOptions();
    }
    
    currentModel = modelSelect.value;
    currentApiKey = apiKeyInput.value;
  }
  
  // Показать/скрыть поле API Key в зависимости от провайдера
  toggleApiKeyField();
}

function updateModelOptions() {
  const modelSelect = document.getElementById('llm-model') as HTMLSelectElement;
  if (!modelSelect) return;

  // Clear existing options
  modelSelect.innerHTML = '';

  if (currentProvider === 'gemini') {
    const models = ['gemini-2.5-flash-preview-04-17', 'gemini-1.5-flash', 'gemini-1.5-pro'];
    models.forEach(m => {
      const option = document.createElement('option');
      option.value = m;
      option.textContent = m;
      modelSelect.appendChild(option);
    });
  } else if (currentProvider === 'openai') {
    const models = ['gpt-4o', 'gpt-4o-mini', 'gpt-4', 'gpt-3.5-turbo'];
    models.forEach(m => {
      const option = document.createElement('option');
      option.value = m;
      option.textContent = m;
      modelSelect.appendChild(option);
    });
  } else if (currentProvider === 'ollama') {
    fetchOllamaModels();
  }
}

async function fetchOllamaModels() {
  try {
    const response = await fetch('http://localhost:11434/api/tags');
    const infoDiv = document.getElementById('ollama-models-info');
    const modelSelect = document.getElementById('llm-model') as HTMLSelectElement;
    
    if (!response.ok) {
      if (infoDiv) infoDiv.textContent = 'Ollama server not found.';
      return;
    }
    const data = await response.json();
    const models = data.models || [];
    
    if (modelSelect) {
      modelSelect.innerHTML = '';
      models.forEach((m: any) => {
        const option = document.createElement('option');
        option.value = m.name;
        option.textContent = m.name;
        modelSelect.appendChild(option);
      });

      if (models.length > 0 && !currentModel) {
        currentModel = models[0].name;
      }
    }

    if (infoDiv) {
      if (models.length > 0) {
        const modelNames = models.map((m: any) => m.name).join(', ');
        infoDiv.textContent = `Available: ${modelNames}`;
        infoDiv.title = modelNames; // Show full list on hover
      } else {
        infoDiv.textContent = 'No models found in Ollama.';
      }
    }
  } catch (error) {
    console.error('Failed to fetch Ollama models:', error);
    const infoDiv = document.getElementById('ollama-models-info');
    if (infoDiv) infoDiv.textContent = 'Ollama connection error.';
  }
}

function toggleApiKeyField() {
  const apiKeyContainer = document.getElementById('api-key-container');
  const ollamaInfo = document.getElementById('ollama-models-info');
  
  if (apiKeyContainer) {
    if (currentProvider === 'ollama') {
      apiKeyContainer.classList.add('hidden');
    } else {
      apiKeyContainer.classList.remove('hidden');
    }
  }

  if (ollamaInfo) {
    if (currentProvider === 'ollama') {
      ollamaInfo.style.display = 'block';
    } else {
      ollamaInfo.style.display = 'none';
    }
  }
}

async function saveLLMConfig() {
  getLLMConfigFromUI();
  const statusSpan = document.getElementById('llm-save-status');
  
  if (!currentApiKey && currentProvider !== 'ollama') {
    if (statusSpan) {
      statusSpan.textContent = 'Enter API key.';
      statusSpan.style.color = '#d9534f';
      setTimeout(() => { statusSpan.textContent = ''; }, 2000);
    }
    return;
  }
  
  const success = await checkConnection();
  if (statusSpan) {
    if (success) {
      statusSpan.textContent = 'Settings saved!';
      statusSpan.style.color = '#7c6110';
    } else {
      statusSpan.textContent = 'Error saving settings.';
      statusSpan.style.color = '#d9534f';
    }
    setTimeout(() => { statusSpan.textContent = ''; }, 2000);
  }
}

async function checkConnection(): Promise<boolean> {
  if (currentProvider === 'ollama') {
    try {
      const response = await fetch('http://localhost:11434/api/tags');
      return response.ok;
    } catch (error) {
      displayGlobalError(
        `Cannot connect to Ollama server: ${error instanceof Error ? error.message : String(error)}`,
      );
      return false;
    }
  }
  // Для облачных провайдеров проверяем только наличие ключа: валидность покажет первый запрос.
  return Boolean(currentApiKey);
}

function displayGlobalError(message: string) {
  const resultsContainer = document.getElementById('results-container');
  if (resultsContainer) {
    resultsContainer.innerHTML = `<p class="error-message">${message}</p>`;
  }
  const generateButton = document.getElementById('generate-button') as HTMLButtonElement;
  if(generateButton) generateButton.disabled = true;
}


function renderManualCard(technique: (typeof MANUAL_TECHNIQUES)[number], prompt: string): string {
  const temperature = technique.config.temperature ?? '—';
  return `
    <div class="result-card">
      <h3>${escapeHtml(technique.name)}</h3>
      <strong>Prompt</strong>
      <pre>${escapeHtml(prompt)}</pre>
      <p class="token-count">
        temperature: <strong>${temperature}</strong> ·
        calls: <strong>${technique.cost_calls}</strong> ·
        source: ${escapeHtml(technique.source_ref)}
      </p>
      <button class="copy-button" type="button">Copy</button>
    </div>`;
}

function renderProcedures(): void {
  const host = document.getElementById('procedures-list');
  if (!host) return;
  host.innerHTML = PROCEDURES.map(
    (p) => `
      <details class="procedure-item">
        <summary>
          <span class="procedure-name">${escapeHtml(p.name)}</span>
          <span class="pipeline-chip">${escapeHtml(p.category)}</span>
        </summary>
        <ol>${(p.procedure ?? []).map((step) => `<li>${escapeHtml(step)}</li>`).join('')}</ol>
        <p class="pipeline-note">${escapeHtml(p.when_to_use)}</p>
      </details>`,
  ).join('');
}

function renderManualTechniques(): void {
  const host = document.getElementById('manual-techniques');
  if (!host) return;
  host.innerHTML = '';
  MANUAL_TECHNIQUES.forEach((technique) => {
    const item = document.createElement('div');
    item.className = 'technique-item';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = `manual_${technique.key}`;
    checkbox.name = 'manual-technique';
    checkbox.value = technique.key;

    const label = document.createElement('label');
    label.htmlFor = `manual_${technique.key}`;
    label.textContent = technique.name;

    item.append(checkbox, label);
    host.appendChild(item);
  });
}

async function handleManualGenerate(): Promise<void> {
  getLLMConfigFromUI();
  const thoughts = (document.getElementById('manual-thoughts') as HTMLTextAreaElement | null)?.value.trim() ?? '';
  const out = document.getElementById('manual-results');
  const status = document.getElementById('manual-status');
  const button = document.getElementById('manual-generate') as HTMLButtonElement | null;
  if (!out || !status || !button) return;
  if (['claude', 'chatgpt', 'gemini', 'grok'].some((target) => (document.getElementById(`pipeline-${target}`) as HTMLInputElement | null)?.checked)) {
    status.textContent = 'Official target modes use the main Build prompt button and source rules, not manual techniques.';
    return;
  }

  const selected = Array.from(
    document.querySelectorAll<HTMLInputElement>('#manual-techniques input:checked'),
  ).map((input) => input.value);

  if (!thoughts) {
    status.textContent = 'Enter a task';
    return;
  }
  if (selected.length === 0) {
    status.textContent = 'Select at least one technique';
    return;
  }

  const provider = (currentProvider || 'ollama') as 'gemini' | 'openai' | 'ollama';
  if (provider !== 'ollama' && !currentApiKey) {
    status.textContent = 'An API key is required in model settings';
    return;
  }

  button.disabled = true;
  out.innerHTML = '';
  const llm = createLLM({
    provider,
    model: currentModel,
    apiKey: provider === 'ollama' ? undefined : currentApiKey,
  });

  let done = 0;
  for (const key of selected) {
    const technique = MANUAL_TECHNIQUES.find((t) => t.key === key);
    if (!technique) continue;
    status.textContent = `Generating ${done + 1}/${selected.length}: ${technique.name}…`;
    try {
      const prompt = await generateManualPrompt(thoughts, technique, llm);

      out.insertAdjacentHTML('beforeend', renderManualCard(technique, prompt));
      done += 1;
    } catch (e) {
      out.insertAdjacentHTML(
        'beforeend',
        `<p class="error-message">${escapeHtml(technique.name)}: ${escapeHtml(e instanceof Error ? e.message : String(e))}</p>`,
      );
    }
  }

  status.textContent = `Ready: ${done} of ${selected.length}`;
  button.disabled = false;
}

async function handlePipelineRun() {
  getLLMConfigFromUI();
  const thoughtsEl = document.getElementById('pipeline-thoughts') as HTMLTextAreaElement | null;
  const out = document.getElementById('pipeline-output');
  const statusEl = document.getElementById('pipeline-status');
  const button = document.getElementById('pipeline-run') as HTMLButtonElement | null;
  if (!thoughtsEl || !out || !statusEl || !button) return;

  const thoughts = thoughtsEl.value.trim();
  out.innerHTML = '';
  if (!thoughts) {
    statusEl.textContent = 'Enter your thoughts';
    return;
  }

  const provider = (currentProvider || 'ollama') as 'gemini' | 'openai' | 'ollama';
  if (provider !== 'ollama' && !currentApiKey) {
    statusEl.textContent = 'An API key is required in model settings';
    return;
  }

  const selectedTarget = ['claude', 'chatgpt', 'gemini', 'grok'].find((target) => (document.getElementById(`pipeline-${target}`) as HTMLInputElement | null)?.checked);
  button.disabled = true;
  statusEl.classList.remove('is-error');
  statusEl.textContent = 'Brief → technique selection → synthesis…';
  try {
    const catalog = loadCatalog(catalogJson);
    const llm = createLLM({
      provider,
      model: currentModel,
      apiKey: provider === 'ollama' ? undefined : currentApiKey,
    });
    const result = await runPipeline({
      thoughts,
      claudeOnly: selectedTarget === 'claude',
      chatgptOnly: selectedTarget === 'chatgpt',
      geminiOnly: selectedTarget === 'gemini',
      grokOnly: selectedTarget === 'grok',
      catalog,
      llm,
      mode: 'llm',  // every prompt is written by the model from the downloaded sources
      variants: 3,
    });
    out.innerHTML = renderPipelineResult(result);
    statusEl.textContent = `${result.choice.name} · warnings: ${result.synthesis.warnings.length}`;
  } catch (e) {
    out.innerHTML = `<p class="error-message">${escapeHtml(e instanceof Error ? e.message : String(e))}</p>`;
    statusEl.textContent = 'Error';
    statusEl.classList.add('is-error');
  } finally {
    button.disabled = false;
  }
}

function App() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(false);
    }, 3500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!loading) {
      getLLMConfigFromUI();
      const llmSaveButton = document.getElementById('llm-save-button');
      if (llmSaveButton) {
        llmSaveButton.addEventListener('click', async () => {
          await saveLLMConfig();
        });
      }
      const providerSelect = document.getElementById('llm-provider');
      if (providerSelect) {
        providerSelect.addEventListener('change', getLLMConfigFromUI);
      }
      const modelSelect = document.getElementById('llm-model');
      if (modelSelect) {
        modelSelect.addEventListener('change', getLLMConfigFromUI);
      }
      renderManualTechniques();
      renderProcedures();
      const manualButton = document.getElementById('manual-generate');
      if (manualButton) {
        manualButton.addEventListener('click', handleManualGenerate);
      }
      const manualResults = document.getElementById('manual-results');
      if (manualResults) {
        manualResults.addEventListener('click', async (event) => {
          const button = (event.target as HTMLElement).closest('.copy-button') as HTMLButtonElement | null;
          if (!button) return;
          const card = button.closest('.result-card');
          const pre = card?.querySelector('pre');
          if (!pre) return;
          try {
            await navigator.clipboard.writeText(pre.textContent ?? '');
            button.textContent = 'Copied';
            setTimeout(() => { button.textContent = 'Copy'; }, 1500);
          } catch {
            button.textContent = 'Copy failed';
          }
        });
      }

      const pipelineButton = document.getElementById('pipeline-run');
      if (pipelineButton) {
        pipelineButton.addEventListener('click', handlePipelineRun);
      }
      const targetToggles = ['claude', 'chatgpt', 'gemini', 'grok'].map((key) => document.getElementById(`pipeline-${key}`) as HTMLInputElement | null);
      for (const toggle of targetToggles) {
        toggle?.addEventListener('change', () => {
          if (toggle.checked) targetToggles.forEach((other) => { if (other && other !== toggle) other.checked = false; });
        });
      }
      const pipelineOutput = document.getElementById('pipeline-output');
      if (pipelineOutput) {
        pipelineOutput.addEventListener('click', async (event) => {
          const button = (event.target as HTMLElement).closest('.pipeline-copy') as HTMLButtonElement | null;
          if (!button) return;
          const promptEl = button.closest('.pipeline-prompt-wrap')?.querySelector('.pipeline-prompt');
          if (!promptEl) return;
          try {
            await navigator.clipboard.writeText(promptEl.textContent ?? '');
            const original = button.textContent;
            button.textContent = 'Copied';
            setTimeout(() => { button.textContent = original; }, 1600);
          } catch {
            button.textContent = 'Copy failed';
          }
        });
      }
    }
  }, [loading]);

  return (
    <>
      {loading && <LoadingScreen />}
      {!loading && (
        <>
          <header>
            <h1><span className="material-symbols-outlined">auto_awesome</span> Prompta</h1>
            <p>Thoughts → brief → technique → ready-to-use prompt</p>
          </header>
          <main>
            <section id="pipeline-section" aria-labelledby="pipeline-heading">
              <div className="pipeline-head">
                <h2 id="pipeline-heading">
                  <span className="material-symbols-outlined">route</span>
                  Pipeline: thoughts → prompt
                  <span className="pipeline-badge">beta</span>
                </h2>
                <p className="pipeline-hint">
                  Write freely. The pipeline builds a brief, filters unsuitable techniques
                  using the catalog, and returns a prompt with recommended settings.
                </p>
              </div>

              <div className="pipeline-grid">
                <div className="pipeline-input-col">
                  <label htmlFor="pipeline-thoughts">Thoughts</label>
                  <textarea
                    id="pipeline-thoughts"
                    rows={6}
                    placeholder="I want AI to review my meeting notes and extract decisions, tasks, and owners into a table"
                  />
                  <div className="pipeline-controls">
                    <button id="pipeline-run" className="pipeline-primary" type="button">Build prompt</button>
                    <div className="pipeline-targets">
                    <label className="pipeline-toggle" title="Use saved official Anthropic guidance only; the generator model stays unchanged.">
                      <input type="checkbox" id="pipeline-claude" />
                      <span>For Claude</span>
                    </label>
                    <label className="pipeline-toggle" title="Use saved official OpenAI guidance only; the generator model stays unchanged.">
                      <input type="checkbox" id="pipeline-chatgpt" />
                      <span>For ChatGPT</span>
                    </label>
                    <label className="pipeline-toggle" title="Use saved official Google guidance only; the generator model stays unchanged.">
                      <input type="checkbox" id="pipeline-gemini" />
                      <span>For Gemini</span>
                    </label>
                    <label className="pipeline-toggle">
                      <input type="checkbox" id="pipeline-grok" />
                      <span>For Grok</span>
                    </label>
                    </div>
                  </div>
                  <p id="pipeline-status" className="pipeline-status" aria-live="polite"></p>
                </div>

                <div id="pipeline-output" className="pipeline-output" aria-live="polite">
                  <div className="pipeline-empty">
                    <span className="material-symbols-outlined">auto_awesome</span>
                    <span>Your brief, selected technique, prompt, and settings will appear here</span>
                  </div>
                </div>
              </div>
            </section>

            <section id="manual-section" aria-labelledby="manual-heading">
              <div className="pipeline-head">
                <h2 id="manual-heading">
                  <span className="material-symbols-outlined">checklist</span>
                  Manual mode: choose techniques
                  <span className="pipeline-badge">Ready for synthesis: {MANUAL_TECHNIQUES.length}</span>
                </h2>
                <p className="pipeline-hint">
                  Choose techniques to generate a separate prompt for each. Templates and examples come
                  from the catalog, giving each prompt a distinct structure.
                </p>
              </div>
              <div className="manual-body">
                <label htmlFor="manual-thoughts">Task</label>
                <textarea id="manual-thoughts" rows={3} placeholder="Describe your task in one or two sentences" />
                <div id="manual-techniques" className="techniques-grid"></div>
                <div className="pipeline-controls">
                  <button id="manual-generate" className="pipeline-primary" type="button">
                    Generate selected prompts
                  </button>
                  <span id="manual-status" className="pipeline-status" aria-live="polite"></span>
                </div>
                <div id="manual-results" className="manual-results"></div>
              </div>
            </section>

            <details className="procedures-block">
              <summary>
                <span className="material-symbols-outlined">account_tree</span>
                Procedures: {PROCEDURES.length} techniques with procedural steps instead of prompts
              </summary>
              <div className="procedures-body">
                <p className="pipeline-hint">
                  These are operations on data or models: example selection, ensembles, and RL optimization.
                  Follow these steps in code or manually.
                </p>
                <div id="procedures-list" className="procedures-list"></div>
              </div>
            </details>

            <section id="model-settings" aria-labelledby="model-settings-heading">
              <h2 id="model-settings-heading">
                <span className="material-symbols-outlined">memory</span>
                Model
              </h2>
              <div className="llm-config-row">
                <div className="llm-config-item">
                  <label htmlFor="llm-provider">Provider</label>
                  <select id="llm-provider" defaultValue="ollama">
                    <option value="gemini">Gemini</option>
                    <option value="openai">OpenAI</option>
                    <option value="ollama">Ollama</option>
                  </select>
                </div>
                <div className="llm-config-item">
                  <label htmlFor="llm-model">Model</label>
                  <select id="llm-model">
                  </select>
                  <div id="ollama-models-info" className="model-hint"></div>
                </div>
                <div className="llm-config-item" id="api-key-container">
                  <label htmlFor="llm-api-key">API Key</label>
                  <input id="llm-api-key" type="password" placeholder="Not needed for Ollama" />
                </div>
              </div>
              <div className="model-actions">
                <button id="llm-save-button" type="button">Save</button>
                <span id="llm-save-status"></span>
              </div>
            </section>
          </main>
          <footer>
            {/* Content moved */}
          </footer>
        </>
      )}
    </>
  );
}

export default App;

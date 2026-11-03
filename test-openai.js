// Test OpenAI import
try {
  const OpenAI = require('openai');
  console.log('OpenAI module loaded successfully:', typeof OpenAI);
} catch (error) {
  console.error('Failed to load OpenAI:', error.message);
}

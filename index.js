#!/usr/bin/env node

/**
 * Nexus Terminal AI v2.0 — A beautiful terminal-based AI assistant
 * with arrow-key model selection, rich commands, and streaming chat.
 *
 * Usage:
 *   node index.js             Start the interactive REPL
 *   node index.js --model     Go straight to model selector
 *   node index.js --help      Show help
 */

const readline = require('readline');
const chalk = require('chalk');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ═══════════════════════════════════════════════════════════════════════
// Configuration
// ═══════════════════════════════════════════════════════════════════════

const MODELS = [
  { id: 'glm-4-flash',   name: 'GLM-4 Flash',   desc: 'Fast & efficient',       tag: 'speed'    },
  { id: 'glm-4-air',     name: 'GLM-4 Air',     desc: 'Balanced performance',   tag: 'balanced' },
  { id: 'glm-4-airx',    name: 'GLM-4 AirX',    desc: 'Enhanced reasoning',     tag: 'smart'    },
  { id: 'glm-4-long',    name: 'GLM-4 Long',    desc: 'Long context window',    tag: 'context'  },
  { id: 'glm-4-plus',    name: 'GLM-4 Plus',    desc: 'Premium quality',        tag: 'premium'  },
  { id: 'glm-4',         name: 'GLM-4',         desc: 'Standard model',         tag: 'standard' },
  { id: 'glm-4v',        name: 'GLM-4V',        desc: 'Vision capable',         tag: 'vision'   },
  { id: 'glm-4v-plus',   name: 'GLM-4V Plus',   desc: 'Vision premium',         tag: 'vision+'  },
];

const CONFIG_DIR = path.join(os.homedir(), '.nexus-terminal');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');
const HISTORY_DIR = path.join(CONFIG_DIR, 'conversations');

let SYSTEM_PROMPT = `You are Nexus, an intelligent AI assistant running in the user's terminal. You are:
- Helpful, direct, and technically skilled
- Concise by default but thorough when needed
- Proactive in suggesting solutions
- Honest about limitations

Format your responses using Markdown when appropriate. Use code blocks with language tags for code.`;

// ═══════════════════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════════════════

let ai = null;
let aiReady = false;
let conversationHistory = [];
let currentModel = MODELS[0];
let isStreaming = false;
let sessionStart = Date.now();
let totalMessages = 0;
let commandHistory = [];

// ═══════════════════════════════════════════════════════════════════════
// Color Theme
// ═══════════════════════════════════════════════════════════════════════

const T = {
  primary:   chalk.cyan,
  secondary: chalk.magenta,
  success:   chalk.green,
  warning:   chalk.yellow,
  error:     chalk.red,
  dim:       chalk.gray,
  bold:      chalk.bold,
  heading:   chalk.cyan.bold,
  accent:    chalk.hex('#FF6B6B'),
  muted:     chalk.hex('#888888'),
  tag: {
    speed:    chalk.hex('#4ECDC4'),
    balanced: chalk.hex('#45B7D1'),
    smart:    chalk.hex('#96CEB4'),
    context:  chalk.hex('#FFEAA7'),
    premium:  chalk.hex('#DDA0DD'),
    standard: chalk.hex('#87CEEB'),
    vision:   chalk.hex('#FF8A65'),
    'vision+':chalk.hex('#FF6B6B'),
  }
};

// ═══════════════════════════════════════════════════════════════════════
// Config Persistence
// ═══════════════════════════════════════════════════════════════════════

function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      const data = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
      if (data.model) {
        const found = MODELS.find(m => m.id === data.model);
        if (found) currentModel = found;
      }
      if (data.systemPrompt) SYSTEM_PROMPT = data.systemPrompt;
    }
  } catch (e) { /* ignore */ }
}

function saveConfig() {
  try {
    if (!fs.existsSync(CONFIG_DIR)) fs.mkdirSync(CONFIG_DIR, { recursive: true });
    fs.writeFileSync(CONFIG_FILE, JSON.stringify({
      model: currentModel.id,
      systemPrompt: SYSTEM_PROMPT,
    }, null, 2));
  } catch (e) { /* ignore */ }
}

// ═══════════════════════════════════════════════════════════════════════
// Terminal Utilities
// ═══════════════════════════════════════════════════════════════════════

function termWidth() { return process.stdout.columns || 80; }

function clearScreen() { process.stdout.write('\x1B[2J\x1B[3J\x1B[H'); }

function divider(ch = '─', w) {
  console.log(T.dim((ch || '─').repeat(w || termWidth())));
}

function centerText(text, w) {
  const width = w || termWidth();
  const stripped = chalk.stripColor(text);
  const pad = Math.max(0, Math.floor((width - stripped.length) / 2));
  return ' '.repeat(pad) + text;
}

function wrapText(text, w) {
  const width = w || termWidth() - 4;
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const word of words) {
    if ((line + ' ' + word).length > width) {
      if (line) lines.push(line);
      line = word;
    } else {
      line = line ? line + ' ' + word : word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

// ═══════════════════════════════════════════════════════════════════════
// Banner
// ═══════════════════════════════════════════════════════════════════════

function showBanner() {
  clearScreen();
  const banner = [
    '',
    T.primary('  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗'),
    T.primary('  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝'),
    T.primary('  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗'),
    T.primary('  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║'),
    T.primary('  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║'),
    T.primary('  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝'),
  ];
  for (const line of banner) console.log(line);

  divider('═');
  console.log(T.heading('  Nexus Terminal AI') + T.dim(' — v2.0.0'));
  console.log(T.dim('  Intelligent AI assistant in your terminal'));
  divider('═');
  console.log();
}

// ═══════════════════════════════════════════════════════════════════════
// Model Selector (Arrow Key Navigation)
// ═══════════════════════════════════════════════════════════════════════

function selectModel() {
  return new Promise((resolve) => {
    let selected = MODELS.findIndex(m => m.id === currentModel.id);
    if (selected < 0) selected = 0;

    function renderModels() {
      const linesToClear = MODELS.length + 4;
      process.stdout.write(`\x1B[${linesToClear}A\x1B[0J`);

      console.log(T.heading('  ╭─ Select AI Model ───────────────────────────╮'));
      for (let i = 0; i < MODELS.length; i++) {
        const m = MODELS[i];
        const isSel = i === selected;
        const isCur = m.id === currentModel.id;
        const tagC = T.tag[m.tag] || T.muted;
        const pointer = isSel ? T.accent('  ❯ ') : '    ';
        const name = isSel ? T.bold.bgHex('#2A2A3A').hex('#FFFFFF')(` ${m.name} `) : T.primary(m.name);
        const desc = T.dim(` — ${m.desc}`);
        const tag = tagC(`[${m.tag.toUpperCase()}]`);
        const cur = isCur ? T.success(' ✓') : '';
        const border = isSel ? T.secondary('  │') : T.dim('  │');
        console.log(`${border}${pointer}${name}${desc}  ${tag}${cur}`);
      }
      console.log(T.heading('  ╰──────────────────────────────────────────────╯'));
      process.stdout.write(T.dim('  ') + T.warning('↑↓') + T.dim(' navigate  ') + T.warning('Enter') + T.dim(' confirm  ') + T.warning('Esc') + T.dim(' cancel'));
    }

    // Initial render
    console.log();
    console.log(T.heading('  ╭─ Select AI Model ───────────────────────────╮'));
    for (let i = 0; i < MODELS.length; i++) {
      const m = MODELS[i];
      const isSel = i === selected;
      const isCur = m.id === currentModel.id;
      const tagC = T.tag[m.tag] || T.muted;
      const pointer = isSel ? T.accent('  ❯ ') : '    ';
      const name = isSel ? T.bold.bgHex('#2A2A3A').hex('#FFFFFF')(` ${m.name} `) : T.primary(m.name);
      const desc = T.dim(` — ${m.desc}`);
      const tag = tagC(`[${m.tag.toUpperCase()}]`);
      const cur = isCur ? T.success(' ✓') : '';
      const border = isSel ? T.secondary('  │') : T.dim('  │');
      console.log(`${border}${pointer}${name}${desc}  ${tag}${cur}`);
    }
    console.log(T.heading('  ╰──────────────────────────────────────────────╯'));
    process.stdout.write(T.dim('  ') + T.warning('↑↓') + T.dim(' navigate  ') + T.warning('Enter') + T.dim(' confirm  ') + T.warning('Esc') + T.dim(' cancel'));

    if (process.stdin.isTTY) process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.setEncoding('utf8');

    const onData = (key) => {
      if (key === '\x1B[A' || key === '\u001B[A') {
        selected = (selected - 1 + MODELS.length) % MODELS.length;
        renderModels();
      } else if (key === '\x1B[B' || key === '\u001B[B') {
        selected = (selected + 1) % MODELS.length;
        renderModels();
      } else if (key === '\r' || key === '\n') {
        cleanup();
        currentModel = MODELS[selected];
        saveConfig();
        console.log();
        console.log(T.success(`  ✓ Model switched to ${currentModel.name} [${currentModel.tag.toUpperCase()}]`));
        console.log();
        resolve(currentModel);
      } else if (key === '\x1B' || key === 'q') {
        cleanup();
        console.log();
        console.log(T.dim('  Cancelled'));
        console.log();
        resolve(currentModel);
      }
    };

    function cleanup() {
      process.stdin.removeListener('data', onData);
      if (process.stdin.isTTY) process.stdin.setRawMode(false);
      process.stdin.pause();
    }

    process.stdin.on('data', onData);
  });
}

// ═══════════════════════════════════════════════════════════════════════
// AI Integration
// ═══════════════════════════════════════════════════════════════════════

async function initAI() {
  try {
    const ZAI = require('z-ai-web-dev-sdk').default;
    ai = await ZAI.create();
    aiReady = true;
    return true;
  } catch (err) {
    aiReady = false;
    return false;
  }
}

async function chat(userMessage) {
  if (!ai) {
    const ok = await initAI();
    if (!ok) {
      console.log(T.error('  AI is not available. Check your network connection.'));
      console.log(T.dim('  You can still use commands (type /help)'));
      console.log();
      return;
    }
  }

  conversationHistory.push({ role: 'user', content: userMessage });
  totalMessages++;

  try {
    const messages = [
      { role: 'system', content: SYSTEM_PROMPT },
      ...conversationHistory.slice(-20)
    ];

    const completion = await ai.chat.completions.create({
      model: currentModel.id,
      messages: messages,
      temperature: 0.7,
      max_tokens: 4096,
    });

    const response = completion.choices[0]?.message?.content || '(no response)';
    conversationHistory.push({ role: 'assistant', content: response });
    displayResponse(response);

  } catch (err) {
    const errMsg = err.message || String(err);
    if (errMsg.includes('timeout') || errMsg.includes('Timeout') || errMsg.includes('fetch failed') || errMsg.includes('ECONNREFUSED')) {
      console.log(T.error('  Connection timeout or network error.'));
      console.log(T.dim('  Suggestions:'));
      console.log(T.dim('    • Check your internet connection'));
      console.log(T.dim('    • Try a different model with /model'));
      console.log(T.dim('    • Wait a moment and try again'));
    } else {
      console.log(T.error(`  AI Error: ${errMsg}`));
    }
    console.log();
  }
}

function displayResponse(text) {
  console.log();
  console.log(T.secondary('  ╭─ ') + T.heading('Nexus') + T.dim(` [${currentModel.name}]`));

  const lines = text.split('\n');
  let inCodeBlock = false;
  let codeLang = '';

  for (const line of lines) {
    // Detect code fences
    if (line.trimStart().startsWith('```')) {
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeLang = line.trim().slice(3).trim();
        const langLabel = codeLang ? T.dim(`  │ `) + T.tag.speed(codeLang) : '';
        console.log(T.dim('  │ ') + T.muted('┌' + '─'.repeat(Math.max(termWidth() - 8, 20))) + (codeLang ? '' : ''));
        if (codeLang) console.log(T.dim('  │ ') + T.tag.speed(codeLang));
      } else {
        inCodeBlock = false;
        console.log(T.dim('  │ ') + T.muted('└' + '─'.repeat(Math.max(termWidth() - 8, 20))));
      }
      continue;
    }

    if (inCodeBlock) {
      console.log(T.dim('  │ ') + T.hex('#B8C7DB')(line));
    } else {
      console.log(T.dim('  │ ') + processMarkdownLine(line));
    }
  }

  console.log(T.secondary('  ╰') + T.dim('─'.repeat(40)));
  console.log();
}

function processMarkdownLine(line) {
  let r = line;

  // Bold
  r = r.replace(/\*\*(.+?)\*\*/g, (_, t) => chalk.bold(t));
  r = r.replace(/__(.+?)__/g, (_, t) => chalk.bold(t));

  // Italic
  r = r.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, (_, t) => chalk.italic(t));

  // Inline code
  r = r.replace(/`([^`]+)`/g, (_, t) => chalk.hex('#4ECDC4').bgHex('#2D2D2D')(` ${t} `));

  // Headers
  if (r.startsWith('### ')) r = T.bold.cyan('   ' + r.slice(4));
  else if (r.startsWith('## ')) r = T.bold.cyan('  ' + r.slice(3));
  else if (r.startsWith('# ')) r = T.bold.cyan(' ' + r.slice(2));

  // Bullets
  r = r.replace(/^(\s*)[-*] /, (_, sp) => sp + T.accent('• '));

  // Numbered lists
  r = r.replace(/^(\s*)(\d+)\. /, (_, sp, n) => sp + T.primary(n + '.') + ' ');

  // Links [text](url)
  r = r.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, url) => T.primary(text) + T.dim(`(${url})`));

  return r;
}

// ═══════════════════════════════════════════════════════════════════════
// Commands
// ═══════════════════════════════════════════════════════════════════════

const COMMANDS = {
  '/help':    { desc: 'Show available commands',                      handler: showHelp },
  '/model':   { desc: 'Select AI model with arrow keys',             handler: cmdModel },
  '/models':  { desc: 'List all available models',                   handler: listModels },
  '/clear':   { desc: 'Clear conversation history',                 handler: cmdClear },
  '/history': { desc: 'Show conversation history',                   handler: showHistory },
  '/stats':   { desc: 'Show session statistics',                     handler: showStats },
  '/system':  { desc: 'View system prompt',                          handler: cmdSystem },
  '/save':    { desc: 'Save conversation to JSON file',              handler: saveConversation },
  '/export':  { desc: 'Export conversation as Markdown',             handler: exportMarkdown },
  '/compact': { desc: 'Trim history to last 10 messages',            handler: cmdCompact },
  '/theme':   { desc: 'Show color theme info',                       handler: cmdTheme },
  '/about':   { desc: 'About Nexus Terminal AI',                     handler: cmdAbout },
  '/redo':    { desc: 'Re-send the last message',                    handler: cmdRedo },
  '/copy':    { desc: 'Copy last response to clipboard (if xclip)',  handler: cmdCopy },
  '/quit':    { desc: 'Exit Nexus Terminal AI',                      handler: cmdQuit },
  '/exit':    { desc: 'Alias for /quit',                             handler: cmdQuit },
};

function showHelp() {
  console.log();
  console.log(T.heading('  ╭─ Commands ──────────────────────────────────╮'));
  const maxLen = Math.max(...Object.keys(COMMANDS).map(c => c.length));
  for (const [cmd, info] of Object.entries(COMMANDS)) {
    const padded = cmd.padEnd(maxLen + 2);
    console.log(T.heading('  │ ') + T.primary(padded) + T.dim(info.desc));
  }
  console.log(T.heading('  ╰──────────────────────────────────────────────╯'));
  console.log();
  console.log(T.dim('  Quick shortcuts:'));
  console.log(T.dim('    help, ?       — Show this help'));
  console.log(T.dim('    models        — List models'));
  console.log(T.dim('    clear         — Clear history'));
  console.log(T.dim('    stats, info   — Session info'));
  console.log(T.dim('    quit, exit    — Exit'));
  console.log();
  console.log(T.dim('  Tips:'));
  console.log(T.dim('    • Just type to chat with AI'));
  console.log(T.dim('    • ') + T.warning('/model') + T.dim(' to switch models with ↑↓ keys'));
  console.log(T.dim('    • ') + T.warning('/save') + T.dim(' to save your conversation'));
  console.log(T.dim('    • Press ') + T.warning('Ctrl+C') + T.dim(' twice to exit'));
  console.log();
}

async function cmdModel() {
  await selectModel();
  startREPL();
}

function listModels() {
  console.log();
  console.log(T.heading('  ╭─ Available Models ──────────────────────────╮'));
  for (const model of MODELS) {
    const isCurrent = model.id === currentModel.id;
    const tagC = T.tag[model.tag] || T.muted;
    const tag = tagC(`[${model.tag.toUpperCase()}]`);
    const cur = isCurrent ? T.success(' ← active') : '';
    const dot = isCurrent ? T.success('●') : T.dim('○');
    console.log(`  │ ${dot} ${T.primary(model.name.padEnd(18))}${T.dim(model.desc.padEnd(24))}${tag}${cur}`);
  }
  console.log(T.heading('  ╰──────────────────────────────────────────────╯'));
  console.log();
  console.log(T.dim('  Use ') + T.warning('/model') + T.dim(' to select with arrow keys'));
  console.log();
}

function cmdClear() {
  conversationHistory = [];
  console.log(T.success('  ✓ Conversation history cleared'));
  console.log();
}

function showHistory() {
  console.log();
  console.log(T.heading('  Conversation History'));
  divider('─', 50);
  if (conversationHistory.length === 0) {
    console.log(T.dim('  (no messages yet)'));
  } else {
    for (let i = 0; i < conversationHistory.length; i++) {
      const msg = conversationHistory[i];
      const role = msg.role === 'user' ? T.primary('You') : T.secondary('Nexus');
      const preview = msg.content.slice(0, 100).replace(/\n/g, ' ');
      const ellipsis = msg.content.length > 100 ? '...' : '';
      console.log(`  ${T.dim('#' + (i + 1))} ${role}${T.dim(':')} ${preview}${T.dim(ellipsis)}`);
    }
  }
  console.log();
  console.log(T.dim(`  ${conversationHistory.length} message(s) in history`));
  console.log();
}

function showStats() {
  const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const hrs = Math.floor(mins / 60);
  const rMins = mins % 60;
  const timeStr = hrs > 0 ? `${hrs}h ${rMins}m ${secs}s` : mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

  console.log();
  console.log(T.heading('  ╭─ Session Statistics ─────────────────────────╮'));
  console.log(`  │ ${T.primary('Model:')}         ${currentModel.name} ${T.dim(`(${currentModel.id})`)}`);
  console.log(`  │ ${T.primary('Messages:')}       ${totalMessages}`);
  console.log(`  │ ${T.primary('History:')}        ${conversationHistory.length} messages`);
  console.log(`  │ ${T.primary('Session Time:')}   ${timeStr}`);
  console.log(`  │ ${T.primary('Commands Run:')}   ${commandHistory.length}`);
  console.log(`  │ ${T.primary('AI Status:')}      ${aiReady ? T.success('Connected') : T.warning('Disconnected')}`);
  console.log(T.heading('  ╰──────────────────────────────────────────────╯'));
  console.log();
}

function cmdSystem() {
  console.log();
  console.log(T.heading('  System Prompt:'));
  divider('─', 60);
  const wrapped = wrapText(SYSTEM_PROMPT, 70);
  for (const line of wrapped) console.log(T.dim('  ') + line);
  console.log();
}

function saveConversation() {
  if (!fs.existsSync(HISTORY_DIR)) fs.mkdirSync(HISTORY_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const fp = path.join(HISTORY_DIR, `conversation-${ts}.json`);
  fs.writeFileSync(fp, JSON.stringify({
    model: currentModel.id,
    saved_at: new Date().toISOString(),
    messages: conversationHistory,
  }, null, 2));
  console.log(T.success(`  ✓ Saved to ${fp}`));
  console.log();
}

function exportMarkdown() {
  if (!fs.existsSync(HISTORY_DIR)) fs.mkdirSync(HISTORY_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const fp = path.join(HISTORY_DIR, `chat-${ts}.md`);
  let md = `# Nexus Terminal AI — Chat Export\n\n**Date:** ${new Date().toISOString()}\n**Model:** ${currentModel.name} (${currentModel.id})\n\n---\n\n`;
  for (const msg of conversationHistory) {
    md += `### ${msg.role === 'user' ? 'You' : 'Nexus'}\n\n${msg.content}\n\n---\n\n`;
  }
  fs.writeFileSync(fp, md);
  console.log(T.success(`  ✓ Exported to ${fp}`));
  console.log();
}

function cmdCompact() {
  if (conversationHistory.length > 10) {
    conversationHistory = conversationHistory.slice(-10);
    console.log(T.success(`  ✓ Compacted to last 10 messages`));
  } else {
    console.log(T.dim('  Already compact'));
  }
  console.log();
}

function cmdTheme() {
  console.log();
  console.log(T.heading('  Color Theme'));
  divider('─', 30);
  console.log(T.primary('  Cyan') + T.dim(' — Primary'));
  console.log(T.secondary('  Magenta') + T.dim(' — Secondary'));
  console.log(T.success('  Green') + T.dim(' — Success'));
  console.log(T.warning('  Yellow') + T.dim(' — Warning'));
  console.log(T.error('  Red') + T.dim(' — Error'));
  console.log(T.accent('  Coral') + T.dim(' — Accent'));
  console.log();
  console.log(T.dim('  Model tags:'));
  for (const m of MODELS) {
    const tagC = T.tag[m.tag] || T.muted;
    console.log(tagC(`  [${m.tag.toUpperCase()}]`) + T.dim(` — ${m.name}`));
  }
  console.log();
}

function cmdAbout() {
  console.log();
  console.log(T.heading('  Nexus Terminal AI v2.0.0'));
  divider('─', 40);
  console.log('  A beautiful, feature-rich terminal AI assistant');
  console.log('  Powered by z-ai-web-dev-sdk');
  divider('─', 40);
  console.log();
  console.log(T.dim('  Features:'));
  const features = [
    'Arrow-key model selection',
    'Multi-turn conversation with context',
    'Markdown rendering (bold, code, headers)',
    'Code block syntax display',
    'Session statistics & history',
    'Conversation save/export (JSON & Markdown)',
    'Rich command system (15+ commands)',
    'Config persistence (~/.nexus-terminal/)',
    'System prompt management',
    'Graceful error handling & offline hints',
    'Ctrl+C interrupt during streaming',
    'Quick keyboard shortcuts',
  ];
  for (const f of features) console.log(T.success('  ✓') + ` ${f}`);
  console.log();
}

async function cmdRedo() {
  if (conversationHistory.length === 0) {
    console.log(T.dim('  No messages to redo'));
    console.log();
    return;
  }
  // Find last user message
  for (let i = conversationHistory.length - 1; i >= 0; i--) {
    if (conversationHistory[i].role === 'user') {
      const lastUserMsg = conversationHistory[i].content;
      // Remove last user + assistant pair
      conversationHistory = conversationHistory.slice(0, i);
      console.log(T.dim('  Re-sending: ') + T.primary(lastUserMsg.slice(0, 80)));
      console.log();
      await chat(lastUserMsg);
      return;
    }
  }
  console.log(T.dim('  No user message found'));
  console.log();
}

function cmdCopy() {
  // Find last assistant message
  for (let i = conversationHistory.length - 1; i >= 0; i--) {
    if (conversationHistory[i].role === 'assistant') {
      const content = conversationHistory[i].content;
      try {
        const { execSync } = require('child_process');
        execSync('xclip -selection clipboard', { input: content, timeout: 5000 });
        console.log(T.success('  ✓ Last response copied to clipboard'));
      } catch (e) {
        // Fallback: show the content for manual copy
        console.log(T.dim('  xclip not available. Last response:'));
        console.log(T.dim('  ────────────────────'));
        const preview = content.slice(0, 300);
        console.log(T.dim('  ' + preview.replace(/\n/g, '\n  ')));
        if (content.length > 300) console.log(T.dim('  ... (truncated)'));
      }
      console.log();
      return;
    }
  }
  console.log(T.dim('  No assistant response to copy'));
  console.log();
}

function cmdQuit() {
  console.log();
  divider('═');
  console.log(T.primary(centerText('Goodbye! See you next time.')));
  divider('═');
  console.log();
  process.exit(0);
}

// ═══════════════════════════════════════════════════════════════════════
// REPL (Read-Eval-Print Loop)
// ═══════════════════════════════════════════════════════════════════════

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  prompt: '',
  historySize: 100,
  removeHistoryDuplicates: true,
});

let ctrlCCount = 0;
let ctrlCTimer = null;

function startREPL() {
  const tagC = T.tag[currentModel.tag] || T.muted;
  rl.setPrompt(tagC(`[${currentModel.tag}]`) + ' ' + T.primary('❯ ') );
  rl.prompt();
}

async function handleInput(input) {
  const trimmed = (input || '').trim();

  if (!trimmed) {
    startREPL();
    return;
  }

  // Commands starting with /
  if (trimmed.startsWith('/')) {
    const parts = trimmed.split(' ');
    const cmd = parts[0].toLowerCase();
    const args = parts.slice(1).join(' ');
    commandHistory.push(cmd);

    if (COMMANDS[cmd]) {
      await COMMANDS[cmd].handler(args);
      if (cmd !== '/model' && cmd !== '/quit' && cmd !== '/exit') startREPL();
      return;
    }
    console.log(T.error(`  Unknown command: ${cmd}`));
    console.log(T.dim('  Type /help for available commands'));
    console.log();
    startREPL();
    return;
  }

  // Quick shortcuts
  const lower = trimmed.toLowerCase();
  if (lower === 'quit' || lower === 'exit' || lower === 'bye') { cmdQuit(); return; }
  if (lower === 'help' || lower === '?') { showHelp(); startREPL(); return; }
  if (lower === 'clear') { cmdClear(); startREPL(); return; }
  if (lower === 'models') { listModels(); startREPL(); return; }
  if (lower === 'stats' || lower === 'info') { showStats(); startREPL(); return; }

  // ── Send to AI ────────────────────────────────────────────────────
  isStreaming = true;

  // Echo user message
  console.log(T.primary('  ╭─ ') + T.bold('You'));
  const wrapped = wrapText(trimmed, termWidth() - 6);
  for (const line of wrapped) console.log(T.dim('  │ ') + line);
  console.log(T.primary('  ╰') + T.dim('─'.repeat(30)));
  console.log();

  // Thinking indicator
  process.stdout.write(T.dim('  ⏳ Thinking'));
  const thinkDots = setInterval(() => process.stdout.write(T.dim('.')), 500);

  try {
    await chat(trimmed);
  } finally {
    clearInterval(thinkDots);
    isStreaming = false;
  }

  startREPL();
}

// ═══════════════════════════════════════════════════════════════════════
// Main Entry
// ═══════════════════════════════════════════════════════════════════════

async function main() {
  // Handle --help flag
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log();
    console.log(T.heading('Nexus Terminal AI v2.0.0'));
    console.log();
    console.log('Usage: node index.js [options]');
    console.log();
    console.log('Options:');
    console.log('  --model    Start with model selector');
    console.log('  --help     Show this help');
    console.log();
    process.exit(0);
  }

  // Load saved config
  loadConfig();

  // Show banner
  showBanner();

  // Show current model
  const tagC = T.tag[currentModel.tag] || T.muted;
  console.log(tagC(`  Model: ${currentModel.name}`) + T.dim(` — ${currentModel.desc}`));
  console.log();

  // Initialize AI
  process.stdout.write(T.dim('  Initializing AI'));
  const dots = setInterval(() => process.stdout.write(T.dim('.')), 400);
  const ok = await initAI();
  clearInterval(dots);
  console.log(ok ? T.success(' ✓ Connected!') : T.warning(' ⚠ Network issue (will retry on chat)'));
  console.log();

  divider('─');
  console.log(T.dim('  Type ') + T.bold('help') + T.dim(' for commands, ') + T.bold('/model') + T.dim(' to select model, or just start chatting!'));
  console.log();

  // If --model flag, show model selector
  if (process.argv.includes('--model')) {
    await selectModel();
  }

  // Wire up readline
  rl.on('line', handleInput);

  rl.on('close', () => {
    console.log();
    divider('═');
    console.log(T.primary(centerText('Goodbye!')));
    divider('═');
    process.exit(0);
  });

  process.on('SIGINT', () => {
    if (isStreaming) {
      isStreaming = false;
      console.log(T.warning('\n  ⚠ Interrupted'));
      console.log();
      startREPL();
      return;
    }
    ctrlCCount++;
    if (ctrlCCount >= 2) {
      cmdQuit();
      return;
    }
    console.log(T.warning('\n  Press Ctrl+C again to exit, or type /quit'));
    console.log();
    startREPL();
    clearTimeout(ctrlCTimer);
    ctrlCTimer = setTimeout(() => { ctrlCCount = 0; }, 2000);
  });

  startREPL();
}

main().catch(err => {
  console.error(T.error(`Fatal: ${err.message}`));
  process.exit(1);
});

# Nexus Terminal AI v2.0 

> Intelligent AI assistant in your terminal — Developed under **BrutalTools**

## Quick Start

```bash
# Clone the repository
git clone https://github.com/brutal-45/Nexus-Terminal.git

# Enter the project folder
cd Nexus-Terminal

# Install dependencies
npm install

# Start Nexus
node index.js

# Or start with model selector
node index.js --model
```

## Features

- **Arrow-Key Model Selector** — Pick your AI model interactively with ↑↓ arrows
- **8 AI Models** — GLM-4 Flash, Air, AirX, Long, Plus, Standard, 4V, 4V+
- **15+ Commands** — Full command system for conversation management
- **Markdown Rendering** — Bold, code, headers, lists, all formatted in terminal
- **Code Blocks** — Syntax-displayed code with language labels
- **Conversation Save/Export** — JSON & Markdown export
- **Session Statistics** — Messages, time, commands, model info
- **Config Persistence** — Remembers your last model at ~/.nexus-terminal/
- **Smart Shortcuts** — Type `help`, `models`, `clear`, `quit` directly

## Commands

| Command | Description |
|---------|-------------|
| `/model`  | Select AI model with arrow keys |
| `/models` | List all available models |
| `/help`   | Show available commands |
| `/clear`  | Clear conversation history |
| `/history`| Show conversation history |
| `/stats`  | Session statistics |
| `/system` | View system prompt |
| `/save`   | Save conversation to JSON |
| `/export` | Export conversation as Markdown |
| `/compact`| Trim history to last 10 messages |
| `/redo`   | Re-send the last message |
| `/copy`   | Copy last response to clipboard |
| `/theme`  | Show color theme info |
| `/about`  | About Nexus Terminal AI |
| `/quit`   | Exit |

## Model Selector

Type `/model` to get an interactive arrow-key selector:

```
  ╭─ Select AI Model ───────────────────────────╮
  │   ❯  GLM-4 Flash  — Fast & efficient  [SPEED]
  │     GLM-4 Air    — Balanced performance [BALANCED]
  │     GLM-4 AirX   — Enhanced reasoning  [SMART]
  │     GLM-4 Long   — Long context window [CONTEXT]
  │     GLM-4 Plus   — Premium quality     [PREMIUM]
  │     GLM-4        — Standard model      [STANDARD]
  │     GLM-4V       — Vision capable      [VISION]
  │     GLM-4V Plus  — Vision premium      [VISION+]
  ╰──────────────────────────────────────────────╯
  ↑↓ navigate  Enter confirm  Esc cancel
```

## Requirements

- Node.js 18+
- npm

## License

MIT — Developed under BrutalTools

# JARVIS - Desktop AI Assistant

A voice-enabled desktop AI assistant for Windows, inspired by JARVIS from Iron Man.

## Features
- 🎙️ Voice input (Ctrl+M) + natural British voice output (Microsoft neural TTS)
- 💬 Intelligent chat powered by NVIDIA Nemotron / any OpenAI-compatible LLM
- 📁 Create, read, write, and manage files and folders
- 🌐 Open apps, websites, search the web
- 💻 System info, safe command execution
- 🔒 Confirmation required for destructive actions (delete, shutdown)
- 🧠 Conversation memory with reference resolution ("it", "that file")

## Quick Start

```bash
# 1. Install dependencies
pip install edge-tts pyttsx3 pywin32 winshell

# 2. Copy the launcher template and add your API key
copy JARVIS.vbs.template JARVIS.vbs
# Edit JARVIS.vbs and replace YOUR_API_KEY_HERE

# 3. Double-click JARVIS.vbs
```

## Configuration

JARVIS works with any OpenAI-compatible API:

| Provider | Base URL | Example Model |
|----------|----------|---------------|
| NVIDIA NIM (free) | `https://integrate.api.nvidia.com/v1` | `nvidia/nemotron-3-super-120b-a12b` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq (free) | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.1` |

Set via environment variables:
```bash
set JARVIS_API_KEY=your_key_here
set JARVIS_BASE_URL=https://integrate.api.nvidia.com/v1
set JARVIS_MODEL=nvidia/nemotron-3-super-120b-a12b
```

Or edit `JARVIS.vbs` / `start_jarvis.bat` with your credentials.

## Architecture

```
Frontend (web/)           Backend (backend/)
├── index.html            ├── agent.py       (hybrid router)
│   ├── UI + chat         ├── brain.py       (offline router - instant commands)
│   ├── Voice input       ├── llm.py         (OpenAI-compatible client)
│   └── TTS playback      ├── memory.py     (conversation + references)
│                         ├── generators.py  (document content)
├── vendor/motion.js      ├── tools/
│                         │   ├── registry.py (tool definitions + risk levels)
│                         │   ├── apps.py     (launch apps)
│                         │   ├── files.py    (file operations)
│                         │   ├── web.py      (browser + downloads)
│                         │   ├── system.py   (system info, power)
│                         │   └── safety.py   (path validation, allow-lists)
│                         └── server.py      (HTTP API + TTS endpoint)
```

## Commands

| Say/Type | What happens |
|----------|--------------|
| `hello jarvis` | Conversational greeting |
| `what is machine learning` | LLM answers directly |
| `open chrome` | Launches Chrome |
| `open whatsapp` | Opens WhatsApp |
| `create a file called notes.txt` | Creates the file |
| `write a study plan into studyplan.txt` | Writes a full study plan |
| `search youtube for python` | Opens YouTube search |
| `download [url]` | Downloads the file |
| `system status` | Shows CPU/RAM/disk |
| `what time is it` | Tells the time |
| `delete test.txt` | Asks for confirmation, then deletes |
| `lock my computer` | Asks for confirmation, then locks |

## Tech Stack

- **Frontend:** HTML/CSS/JS (single-file, no build step), Motion.js for animations
- **Backend:** Python 3.10+ (stdlib HTTP server)
- **AI:** Any OpenAI-compatible chat completions API with function calling
- **TTS:** Microsoft Edge neural voices via edge-tts (en-GB-RyanNeural)
- **STT:** Web Speech API (Chrome/Edge)

## License

MIT
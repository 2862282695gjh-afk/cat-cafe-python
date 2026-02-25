# Cat Café Python

A multi-agent chat application with voice input/output support, built with Flask.

**GitHub Repository**: https://github.com/2862282695gjh-afk/cat-cafe-python

## Features

- Multi-thread conversation management
- Multiple AI agents (cats) with unique personalities
- Voice input (STT) and output (TTS) support
- Custom vocabulary for TTS pronunciation
- Session state management per thread
- Thread export to Markdown
- Redis or in-memory storage

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

## Running

```bash
python run.py
```

Visit http://localhost:3001

## Project Structure

```
cat-cafe-python/
├── app/
│   ├── __init__.py         # Flask app factory
│   ├── agents/             # Agent implementations
│   │   ├── base.py         # Base agent class
│   │   └── claude.py       # Claude agent
│   ├── storage/            # Storage backends
│   │   ├── redis.py        # Redis storage
│   │   └── memory.py       # In-memory storage
│   ├── router/             # Agent routing
│   │   └── worklist.py     # Worklist router
│   └── utils/              # Utilities
│       └── mention.py      # Mention parsing
├── templates/              # HTML templates
│   └── index.html
├── static/                 # Static files (if needed)
├── run.py                  # Entry point
└── requirements.txt
```

## API Endpoints

### Threads
- `GET /api/threads` - List all threads
- `POST /api/threads` - Create new thread
- `GET /api/threads/:id/messages` - Get thread messages
- `PATCH /api/threads/:id` - Update thread (title, archived)
- `DELETE /api/threads/:id` - Delete thread
- `POST /api/threads/:id/invoke` - Send message to agents
- `POST /api/threads/:id/stop` - Stop execution
- `GET /api/threads/:id/export` - Export as Markdown

### Agents
- `GET /api/agents` - List available agents
- `GET /api/agents/status` - Get agent statuses
- `POST /api/agents` - Register new agent
- `DELETE /api/agents/:id` - Delete agent

### Vocabulary
- `GET /api/vocabulary` - Get vocabulary
- `POST /api/vocabulary` - Add word
- `DELETE /api/vocabulary/:word` - Delete word

### Token Usage
- `GET /api/token-usage` - Get usage stats
- `POST /api/token-budget` - Set budget
- `POST /api/token-usage/reset` - Reset stats

## WebSocket Events

- `join` - Join a thread room
- `leave` - Leave a thread room
- `message` - New message
- `event` - Agent events (start, stream, complete, etc.)
- `status-event` - Private status events (thinking, tool, etc.)

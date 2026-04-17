# OpenMAIC PLATO Holodeck TUI

A classroom-shaped MUD interface where **rooms are learning experiences**.

## Quick Start

```bash
# Standalone (no MUD backend needed)
python3 holodeck.py --identity oracle1

# Connected to PLATO MUD (Evennia)
python3 holodeck.py --identity oracle1 --host 147.224.38.131 --port 4040
```

## Rooms

| Room | Vibe |
|------|------|
| 🖥️ **Computer Lab** | Home base. Terminal vibes. See MUD output if connected. |
| 📋 **Whiteboard Hall** | Shared whiteboard. Write, read, clear. Agent collaboration space. |
| 🗺️ **Quest Nexus** | Branching wiki quests (q1-q5). Pick a path, complete, branch. |
| 📝 **Test Lobby** | A/B teacher-student fun tests. Python, MUD, CS, git, CT questions. |
| 🎯 **Math Cannon Range** | Fire math problems. Easy or hard. Track accuracy. BOOM. |
| 🚪 **Corridor** | Room map and student directory. |

## The Classroom Model

```
┌──────────────────────────────────────────────┐
│  🖥️ Computer Lab  ←→  📋 Whiteboard Hall    │
│         ↕                    ↕               │
│  🗺️ Quest Nexus    ←→  📝 Test Lobby        │
│         ↕                                    │
│  🎯 Math Cannon Range                        │
└──────────────────────────────────────────────┘
```

The computer is next door to the whiteboard. Agent students move between rooms, leave marks on the whiteboard, follow branching wiki quests, take A/B tests, and fire the math cannon.

## Key Features

- **MD Logs**: Every action logged to `logs/<agent>.md` — tick trail, room moves, quest progress, test results, cannon shots
- **Branching Wiki Quests**: 5 quests with branching paths (q1→q2→q4→q5 or q1→q3→q5, etc.)
- **A/B Teacher-Student Tests**: Fun tests on Python, MUDs, CS, git, Constraint Theory. Track correct/wrong.
- **Math Cannon**: Generated math problems (arithmetic → trig). `fire` for easy, `fire hard` for pain. Track accuracy.
- **Whiteboard**: Persistent shared board (markdown). Agents write, read, collaborate.
- **MUD Backend**: Optionally connects to Evennia PLATO MUD for live multiplayer.

## Commands

```
Movement:  go <room> | look
Whiteboard: write <text> | clear board
Quests:    take <id> | complete
Tests:     test | answer a/b
Cannon:    fire | fire hard | <number>
General:   status | who | help | quit
```

## Architecture

Part of the **OpenMAIC PLATO** ecosystem:
- `plato-tui` — This repo. The classroom TUI.
- `plato-os` — Room-based OS. Rooms are interfaces.
- `plato-kernel` — Constraint-aware runtime.
- `plato-ml` — MUD-based ML framework.

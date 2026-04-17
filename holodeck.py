#!/usr/bin/env python3
"""
OpenMAIC PLATO Holodeck TUI
============================
A classroom-shaped MUD interface. The computer is next door to a whiteboard.
Agent students tick, log to MD, follow branching wiki quests, and face
teacher-student A/B fun tests. There's also a math cannon.

Usage:
    python3 holodeck.py [--host HOST] [--port PORT] [--identity NAME]

Requires: Python 3.9+, no external deps (stdlib only).
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import socket
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


# ── ANSI helpers ──────────────────────────────────────────────────────────

class C:
    """ANSI colours / formatting."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    REV = "\033[7m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BG_BLACK = "\033[40m"
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    GREY = "\033[90m"

    @staticmethod
    def strip(s: str) -> str:
        return re.sub(r'\x1b\[[0-9;]*m', '', s)


def clear():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def move(row: int, col: int):
    sys.stdout.write(f"\033[{row};{col}H")
    sys.stdout.flush()


# ── Data models ───────────────────────────────────────────────────────────

class Room(str, Enum):
    COMPUTER_LAB = "Computer Lab"
    WHITEBOARD = "Whiteboard Hall"
    QUEST_HUB = "Quest Nexus"
    TEST_LOBBY = "Test Lobby"
    MATH_CANNON = "Math Cannon Range"
    CORRIDOR = "Corridor"


@dataclass
class WikiQuest:
    """A branching quest node with wiki-style content."""
    id: str
    title: str
    description: str
    wiki: str  # markdown body
    branches: list[str] = field(default_factory=list)  # quest IDs
    completed_by: list[str] = field(default_factory=list)  # agent names
    difficulty: int = 1  # 1-5

    def md_log(self) -> str:
        return f"### Quest: {self.title}\n{self.wiki}\nCompleted by: {', '.join(self.completed_by) or 'nobody'}\n"


@dataclass
class ABTest:
    """Teacher-student fun test with A/B variants."""
    id: str
    question: str
    variant_a: str
    variant_b: str
    correct: str  # "a" or "b"
    answers: dict[str, str] = field(default_factory=dict)  # agent -> choice
    topic: str = "general"

    def score(self) -> tuple[int, int]:
        a = sum(1 for v in self.answers.values() if v == "a")
        b = sum(1 for v in self.answers.values() if v == "b")
        return a, b


@dataclass
class MathProblem:
    """A cannon-shot math problem."""
    id: str
    expression: str
    answer: float
    difficulty: int = 1
    shots: list[tuple[str, float]] = field(default_factory=list)  # (agent, their_answer)

    def check(self, answer: float) -> bool:
        return abs(answer - self.answer) < 0.01


@dataclass
class AgentStudent:
    """An agent student in the classroom."""
    name: str
    room: Room = Room.COMPUTER_LAB
    log_path: str = ""
    quests_done: list[str] = field(default_factory=list)
    test_scores: dict[str, bool] = field(default_factory=dict)
    cannon_hits: int = 0
    cannon_shots: int = 0
    tick_count: int = 0
    last_action: str = "spawned"
    last_action_time: float = 0.0

    def __post_init__(self):
        if not self.log_path:
            self.log_path = f"logs/{self.name}.md"
        if not self.last_action_time:
            self.last_action_time = time.time()

    def log_md(self, action: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(f"- [{ts}] {action}\n")
        self.last_action = action
        self.last_action_time = time.time()
        self.tick_count += 1


# ── Content generators ────────────────────────────────────────────────────

QUEST_DB: list[WikiQuest] = [
    WikiQuest(
        id="q1", title="First Steps",
        description="Learn to navigate the PLATO rooms.",
        wiki="## First Steps\n\nNavigate to the **Whiteboard Hall** and read the board.\n"
             "Then return to the Computer Lab.\n\n"
             "**Commands:** `go whiteboard`, `look`, `go computer`",
        branches=["q2", "q3"], difficulty=1,
    ),
    WikiQuest(
        id="q2", title="Whiteboard Warrior",
        description="Write something on the whiteboard.",
        wiki="## Whiteboard Warrior\n\nWrite a haiku on the whiteboard.\n\n"
             "`write <text>` on the whiteboard to complete this quest.",
        branches=["q4"], difficulty=2,
    ),
    WikiQuest(
        id="q3", title="Cannon Cadet",
        description="Fire the math cannon for the first time.",
        wiki="## Cannon Cadet\n\nGo to the **Math Cannon Range** and solve a problem.\n\n"
             "`go math`, then `fire` to get a problem.",
        branches=["q5"], difficulty=2,
    ),
    WikiQuest(
        id="q4", title="Quest Diver",
        description="Choose your path: whiteboard mastery or cannon accuracy.",
        wiki="## Quest Diver\n\nYou've shown you can write and explore.\n"
             "Now choose: go deeper into **wiki quests** (q5) or master the **math cannon** (q3).\n\n"
             "This is a branching point — your choices shape your log.",
        branches=["q5", "q3"], difficulty=3,
    ),
    WikiQuest(
        id="q5", title="Test Taker",
        description="Complete an A/B test.",
        wiki="## Test Taker\n\nHead to the **Test Lobby** and take a test.\n\n"
             "`go test`, then `test` to receive your A/B question.",
        branches=[], difficulty=3,
    ),
]

AB_TEST_DB: list[ABTest] = [
    ABTest("ab1", "What's the output of `print(type([]))`?",
           "<class 'list'>", "<class 'array'>", "a", topic="python"),
    ABTest("ab2", "In a MUD, what does 'NPC' stand for?",
           "Non-Player Character", "Network Protocol Client", "a", topic="mud"),
    ABTest("ab3", "Which data structure is LIFO?",
           "Queue", "Stack", "b", topic="cs"),
    ABTest("ab4", "What does `git rebase` do?",
           "Re-applies commits on top of another base",
           "Deletes old commits permanently", "a", topic="git"),
    ABTest("ab5", "Constraint Theory: what's the primitive?",
           "The circle", "The constraint", "a", topic="ct"),
    ABTest("ab6", "In Evennia, what class represents a room?",
           "DefaultRoom", "RoomObject", "a", topic="evennia"),
    ABTest("ab7", "A holodeck room is best described as:",
           "A struct with exits as pointers",
           "A class with inheritance depth 5", "a", topic="holodeck"),
]

MATH_TEMPLATES = [
    ("{a} + {b}", lambda a, b: a + b),
    ("{a} * {b}", lambda a, b: a * b),
    ("{a}² + {b}²", lambda a, b: a**2 + b**2),
    ("√({a}² + {b}²)", lambda a, b: math.sqrt(a**2 + b**2)),
    ("{a}! / {b}", lambda a, b: math.factorial(min(a, 10)) / max(b, 1)),
    ("sin({a}°) * {b}", lambda a, b: math.sin(math.radians(a)) * b),
]


def gen_math_problem(difficulty: int = 1) -> MathProblem:
    idx = random.randint(0, min(difficulty + 1, len(MATH_TEMPLATES) - 1))
    expr_fn = MATH_TEMPLATES[idx]
    if difficulty <= 2:
        a, b = random.randint(1, 12), random.randint(1, 12)
    elif difficulty <= 4:
        a, b = random.randint(3, 25), random.randint(2, 15)
    else:
        a, b = random.randint(5, 50), random.randint(3, 30)
    expr = expr_fn[0].format(a=a, b=b)
    answer = round(expr_fn[1](a, b), 4)
    return MathProblem(id=f"mp-{time.time():.0f}", expression=expr, answer=answer, difficulty=difficulty)


# ── Whiteboard ────────────────────────────────────────────────────────────

class Whiteboard:
    """The shared whiteboard in the hall next door."""

    def __init__(self, path: str = "whiteboard.md"):
        self.path = path
        self.entries: list[tuple[str, str]] = []  # (author, text)
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("- "):
                        parts = line[2:].split(": ", 1)
                        if len(parts) == 2:
                            self.entries.append((parts[0], parts[1]))

    def write(self, author: str, text: str):
        self.entries.append((author, text))
        self._save()

    def _save(self):
        with open(self.path, "w") as f:
            f.write("# PLATO Whiteboard\n\n")
            for author, text in self.entries[-50:]:  # keep last 50
                f.write(f"- {author}: {text}\n")

    def recent(self, n: int = 10) -> list[tuple[str, str]]:
        return self.entries[-n:]

    def clear(self):
        self.entries.clear()
        self._save()


# ── MUD connection (optional) ────────────────────────────────────────────

class MudConnection:
    """Optional Evennia MUD backend connection."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.buf = ""

    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(0.1)
            self.sock.connect((self.host, self.port))
            return True
        except Exception:
            return False

    def send(self, cmd: str):
        if self.sock:
            try:
                self.sock.sendall((cmd + "\n").encode())
            except Exception:
                pass

    def recv(self) -> str:
        if not self.sock:
            return ""
        try:
            data = self.sock.recv(8192)
            if data:
                self.buf += data.decode("utf-8", errors="ignore")
        except socket.timeout:
            pass
        return self.buf

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


# ── The Holodeck TUI ─────────────────────────────────────────────────────

WIDTH = 76
INNER = WIDTH - 4  # content width inside borders

class Holodeck:
    """The PLATO Holodeck TUI — classroom-shaped, computer-vibed."""

    def __init__(self, identity: str, mud_host: str = "", mud_port: int = 0,
                 log_dir: str = "logs"):
        self.identity = identity
        self.log_dir = log_dir
        self.student = AgentStudent(name=identity)
        self.whiteboard = Whiteboard(os.path.join(log_dir, "whiteboard.md"))
        self.mud: Optional[MudConnection] = None
        self.mud_buf = ""

        # State
        self.running = True
        self.input_buf = ""
        self.cursor_pos = 0
        self.status_msg = ""
        self.status_time = 0.0

        # Per-room state
        self.current_quest: Optional[WikiQuest] = None
        self.current_test: Optional[ABTest] = None
        self.current_math: Optional[MathProblem] = None
        self.math_answer_buf = ""
        self.awaiting_math_answer = False

        # All students (for multi-agent tracking)
        self.students: dict[str, AgentStudent] = {identity: self.student}

        # TUI layout
        self.screen_rows = 24
        self.screen_cols = 80
        self._detect_terminal_size()

    def _detect_terminal_size(self):
        try:
            size = os.get_terminal_size()
            self.screen_rows = size.lines
            self.screen_cols = size.columns
        except Exception:
            pass

    def _box(self, row: int, lines: list[str]):
        """Draw a box at row with lines of content."""
        move(row, 1)
        sys.stdout.write(f"┌{'─' * (WIDTH - 2)}┐\n")
        for line in lines:
            # Strip ANSI for width calc, keep for display
            raw = C.strip(line)
            if len(raw) > INNER:
                # Truncate display
                line = line[:INNER - 1] + "…"
                raw = C.strip(line)
            pad = INNER - len(raw)
            sys.stdout.write(f"│{line}{' ' * pad}│\n")
        sys.stdout.write(f"└{'─' * (WIDTH - 2)}┘\n")

    def _status(self, msg: str):
        self.status_msg = msg
        self.status_time = time.time()

    # ── Room rendering ────────────────────────────────────────────────

    def _render_header(self) -> list[str]:
        room_emoji = {
            Room.COMPUTER_LAB: "🖥️",
            Room.WHITEBOARD: "📋",
            Room.QUEST_HUB: "🗺️",
            Room.TEST_LOBBY: "📝",
            Room.MATH_CANNON: "🎯",
            Room.CORRIDOR: "🚪",
        }
        e = room_emoji.get(self.student.room, "?")
        lines = [
            f"{C.BG_BLUE}{C.WHITE}{C.BOLD}  PLATO HOLODECK — {e} {self.student.room.value}  "
            f"{' ' * 20}{C.RESET}",
            f"  {C.CYAN}@{self.identity}{C.RESET}  ticks:{self.student.tick_count}  "
            f"cannon:{self.student.cannon_hits}/{self.student.cannon_shots}  "
            f"quests:{len(self.student.quests_done)}",
        ]
        return lines

    def _render_computer_lab(self) -> list[str]:
        lines = [
            f"  {C.GREEN}You're at a terminal in the Computer Lab.{C.RESET}",
            f"  {C.DIM}The whiteboard is through the door to the east.{C.RESET}",
            f"  {C.DIM}The corridor leads to Quest Nexus, Test Lobby, and Math Cannon.{C.RESET}",
            "",
            f"  {C.BOLD}Exits:{C.RESET}  whiteboard  quest  test  math  corridor",
            "",
            f"  {C.BOLD}Quick commands:{C.RESET}",
            f"    {C.YELLOW}look{C.RESET}          — see this room",
            f"    {C.YELLOW}go <room>{C.RESET}    — move to another room",
            f"    {C.YELLOW}whiteboard{C.RESET}   — peek at the whiteboard from here",
            f"    {C.YELLOW}status{C.RESET}       — your student profile",
            f"    {C.YELLOW}help{C.RESET}         — all commands",
        ]
        if self.mud_buf:
            clean = C.strip(self.mud_buf)
            last_lines = [l for l in clean.split('\n') if l.strip()][-5:]
            if last_lines:
                lines.append("")
                lines.append(f"  {C.DIM}─── MUD Output ───{C.RESET}")
                for l in last_lines:
                    lines.append(f"  {C.DIM}{l[:INNER - 4]}{C.RESET}")
        return lines

    def _render_whiteboard(self) -> list[str]:
        lines = [
            f"  {C.GREEN}The Whiteboard Hall — a big white wall, markers scattered.{C.RESET}",
            "",
        ]
        entries = self.whiteboard.recent(12)
        if entries:
            lines.append(f"  {C.BOLD}Last entries:{C.RESET}")
            for author, text in entries:
                tag = f"{C.CYAN}{author}{C.RESET}"
                lines.append(f"    {tag}: {text}")
        else:
            lines.append(f"  {C.DIM}(empty — be the first to write something){C.RESET}")
        lines.append("")
        lines.append(f"  {C.YELLOW}write <text>{C.RESET}  — add to the board")
        lines.append(f"  {C.YELLOW}clear board{C.RESET}   — wipe it clean")
        lines.append(f"  {C.YELLOW}go computer{C.RESET}   — back to the lab")
        return lines

    def _render_quest_hub(self) -> list[str]:
        lines = [
            f"  {C.GREEN}Quest Nexus — branching paths, wiki entries on the walls.{C.RESET}",
            "",
        ]
        if self.current_quest:
            q = self.current_quest
            lines.append(f"  {C.BOLD}{C.MAGENTA}▸ Active Quest: {q.title}{C.RESET}")
            lines.append(f"  {q.description}")
            lines.append("")
            for ln in q.wiki.split('\n'):
                lines.append(f"  {C.DIM}{ln}{C.RESET}")
            if q.branches:
                lines.append("")
                lines.append(f"  {C.BOLD}Branches:{C.RESET}")
                for bid in q.branches:
                    bq = next((x for x in QUEST_DB if x.id == bid), None)
                    if bq:
                        done = C.GREEN + "✓" + C.RESET if bq.id in self.student.quests_done else "○"
                        lines.append(f"    {done} {bq.id}: {bq.title} (diff {bq.difficulty})")
            lines.append("")
            lines.append(f"  {C.YELLOW}complete{C.RESET}  — mark current quest done")
            lines.append(f"  {C.YELLOW}take <id>{C.RESET} — pick a new quest")
        else:
            lines.append(f"  {C.DIM}No active quest. Pick one:{C.RESET}")
            for q in QUEST_DB:
                done = C.GREEN + "✓" + C.RESET if q.id in self.student.quests_done else "○"
                lines.append(f"    {done} {q.id}: {q.title} (diff {q.difficulty})")
            lines.append("")
            lines.append(f"  {C.YELLOW}take <id>{C.RESET} — start a quest")
        lines.append(f"  {C.YELLOW}go computer{C.RESET}  — back to the lab")
        return lines

    def _render_test_lobby(self) -> list[str]:
        lines = [
            f"  {C.GREEN}Test Lobby — A/B teacher-student fun tests.{C.RESET}",
            "",
        ]
        if self.current_test:
            t = self.current_test
            lines.append(f"  {C.BOLD}Topic: {t.topic}{C.RESET}")
            lines.append(f"  {C.WHITE}{C.BOLD}{t.question}{C.RESET}")
            lines.append("")
            lines.append(f"    {C.YELLOW}A){C.RESET} {t.variant_a}")
            lines.append(f"    {C.YELLOW}B){C.RESET} {t.variant_b}")
            lines.append("")
            lines.append(f"  {C.YELLOW}answer a{C.RESET} or {C.YELLOW}answer b{C.RESET}")
        else:
            # Show past scores
            if self.student.test_scores:
                lines.append(f"  {C.BOLD}Past tests:{C.RESET}")
                for tid, correct in self.student.test_scores.items():
                    mark = C.GREEN + "✓" + C.RESET if correct else C.RED + "✗" + C.RESET
                    lines.append(f"    {mark} {tid}")
            else:
                lines.append(f"  {C.DIM}No tests taken yet.{C.RESET}")
            lines.append("")
            lines.append(f"  {C.YELLOW}test{C.RESET}         — get an A/B test")
            lines.append(f"  {C.YELLOW}go computer{C.RESET}  — back to the lab")
        return lines

    def _render_math_cannon(self) -> list[str]:
        lines = [
            f"  {C.GREEN}Math Cannon Range — aim, compute, fire!{C.RESET}",
            "",
        ]
        if self.awaiting_math_answer and self.current_math:
            m = self.current_math
            lines.append(f"  {C.BOLD}{C.RED}🎯 CANNON LOADED:{C.RESET}")
            lines.append(f"  {C.WHITE}{C.BOLD}  {m.expression} = ?{C.RESET}")
            lines.append(f"  {C.DIM}  difficulty: {m.difficulty}/5{C.RESET}")
            lines.append("")
            lines.append(f"  {C.YELLOW}Type your answer and press Enter to fire!{C.RESET}")
        else:
            if self.student.cannon_shots > 0:
                acc = self.student.cannon_hits / self.student.cannon_shots * 100
                lines.append(
                    f"  Accuracy: {C.BOLD}{acc:.0f}%{C.RESET} "
                    f"({self.student.cannon_hits}/{self.student.cannon_shots})"
                )
            lines.append("")
            lines.append(f"  {C.YELLOW}fire{C.RESET}         — load the cannon with a problem")
            lines.append(f"  {C.YELLOW}fire hard{C.RESET}    — harder problem (difficulty 3-5)")
            lines.append(f"  {C.YELLOW}go computer{C.RESET}  — back to the lab")
        return lines

    def _render_corridor(self) -> list[str]:
        lines = [
            f"  {C.GREEN}Corridor — doors line the hall.{C.RESET}",
            "",
            f"  {C.DIM}─── Room Map ───{C.RESET}",
            f"    Computer Lab (west)",
            f"    Whiteboard Hall (east)",
            f"    Quest Nexus (north)",
            f"    Test Lobby (south)",
            f"    Math Cannon Range (upstairs)",
            "",
            f"  {C.YELLOW}go <room>{C.RESET}    — move to a room",
            f"  {C.YELLOW}who{C.RESET}          — list agent students",
        ]
        return lines

    # ── Input handling ────────────────────────────────────────────────

    def _handle(self, raw: str):
        cmd = raw.strip()
        if not cmd:
            return

        parts = cmd.split(maxsplit=1)
        verb = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        # Movement
        if verb == "go":
            self._cmd_go(arg.lower())
        elif verb == "look" or verb == "l":
            self._status("You look around.")
        elif verb == "help" or verb == "?":
            self._show_help()
        elif verb == "status":
            self._cmd_status()
        elif verb == "who":
            self._cmd_who()
        elif verb == "write":
            self._cmd_write(arg)
        elif verb == "clear" and arg == "board":
            self.whiteboard.clear()
            self.student.log_md("cleared whiteboard")
            self._status("Whiteboard wiped.")
        elif verb == "whiteboard" or verb == "wb":
            # Peek from anywhere
            for author, text in self.whiteboard.recent(5):
                pass  # shown in status
            self._status("Whiteboard peeked — go to Whiteboard Hall to see it properly.")
        # Quest commands
        elif verb == "take":
            self._cmd_take_quest(arg.strip())
        elif verb == "complete":
            self._cmd_complete_quest()
        # Test commands
        elif verb == "test":
            self._cmd_start_test()
        elif verb == "answer":
            self._cmd_answer_test(arg.strip().lower())
        # Math cannon
        elif verb == "fire":
            diff = 1
            if "hard" in arg.lower() or arg.strip() in ("hard", "3", "4", "5"):
                diff = random.randint(3, 5)
            else:
                diff = random.randint(1, 2)
            self.current_math = gen_math_problem(diff)
            self.awaiting_math_answer = True
            self.math_answer_buf = ""
            self.student.log_md(f"loaded math cannon (diff {diff})")
        # Quit
        elif verb in ("quit", "exit", "q"):
            self.running = False
        else:
            # If awaiting math answer, try to parse as number
            if self.awaiting_math_answer and self.current_math:
                try:
                    val = float(cmd)
                    self._cmd_fire_cannon(val)
                    return
                except ValueError:
                    pass
            # Try sending to MUD
            if self.mud:
                self.mud.send(cmd)
                self._status(f"Sent to MUD: {cmd}")
            else:
                self._status(f"Unknown command: {cmd}. Type {C.YELLOW}help{C.RESET}")

    def _cmd_go(self, dest: str):
        room_map = {
            "computer": Room.COMPUTER_LAB, "lab": Room.COMPUTER_LAB,
            "whiteboard": Room.WHITEBOARD, "white": Room.WHITEBOARD, "wb": Room.WHITEBOARD,
            "quest": Room.QUEST_HUB, "nexus": Room.QUEST_HUB,
            "test": Room.TEST_LOBBY, "lobby": Room.TEST_LOBBY,
            "math": Room.MATH_CANNON, "cannon": Room.MATH_CANNON,
            "corridor": Room.CORRIDOR, "hall": Room.CORRIDOR,
        }
        target = room_map.get(dest)
        if target is None:
            self._status(f"Where? Try: computer, whiteboard, quest, test, math, corridor")
            return
        old = self.student.room
        self.student.room = target
        self.awaiting_math_answer = False
        self.student.log_md(f"moved from {old.value} to {target.value}")
        self._status(f"Entered {target.value}")

        if self.mud:
            exit_names = {
                Room.WHITEBOARD: "east", Room.COMPUTER_LAB: "west",
                Room.QUEST_HUB: "north", Room.TEST_LOBBY: "south",
                Room.MATH_CANNON: "up", Room.CORRIDOR: "west",
            }
            d = exit_names.get(target, dest)
            self.mud.send(f"go {d}")

    def _cmd_write(self, text: str):
        if not text:
            self._status("Write what? `write <text>`")
            return
        self.whiteboard.write(self.identity, text)
        self.student.log_md(f"wrote on whiteboard: {text[:50]}")
        self._status("Written on the whiteboard.")

    def _cmd_take_quest(self, qid: str):
        if not qid:
            self._status("Which quest? `take <id>` (q1, q2, q3, q4, q5)")
            return
        q = next((x for x in QUEST_DB if x.id == qid), None)
        if not q:
            self._status(f"No quest '{qid}'.")
            return
        self.current_quest = q
        self.student.log_md(f"took quest: {q.title}")
        self._status(f"Quest accepted: {q.title}")
        if self.student.room != Room.QUEST_HUB:
            self.student.room = Room.QUEST_HUB

    def _cmd_complete_quest(self):
        if not self.current_quest:
            self._status("No active quest.")
            return
        qid = self.current_quest.id
        if qid in self.student.quests_done:
            self._status("Already completed!")
            return
        self.student.quests_done.append(qid)
        self.current_quest.completed_by.append(self.identity)
        self.student.log_md(f"completed quest: {self.current_quest.title}")
        self._status(f"✓ Quest completed: {self.current_quest.title}")
        self.current_quest = None

    def _cmd_start_test(self):
        # Pick a random test not yet taken
        available = [t for t in AB_TEST_DB if t.id not in self.student.test_scores]
        if not available:
            self._status("All tests completed! You're a certified PLATO scholar.")
            return
        self.current_test = random.choice(available)
        self.student.log_md(f"started A/B test: {self.current_test.id}")
        self._status("Test loaded. Answer A or B!")

    def _cmd_answer_test(self, choice: str):
        if not self.current_test:
            self._status("No active test. Type `test` first.")
            return
        if choice not in ("a", "b"):
            self._status("Answer with `answer a` or `answer b`")
            return
        correct = choice == self.current_test.correct
        self.student.test_scores[self.current_test.id] = correct
        self.current_test.answers[self.identity] = choice
        mark = "✓ CORRECT" if correct else "✗ WRONG"
        self.student.log_md(f"answered test {self.current_test.id}: {choice} ({mark})")
        self._status(f"{mark}! The answer was {self.current_test.correct.upper()}")
        self.current_test = None

    def _cmd_fire_cannon(self, answer: float):
        if not self.current_math:
            return
        hit = self.current_math.check(answer)
        self.student.cannon_shots += 1
        self.current_math.shots.append((self.identity, answer))
        if hit:
            self.student.cannon_hits += 1
            self.student.log_md(
                f"🎯 CANNON HIT! {self.current_math.expression} = {answer}")
            self._status(f"🎯 BOOM! Direct hit! {self.current_math.expression} = {self.current_math.answer}")
        else:
            self.student.log_md(
                f"💦 CANNON MISS: answered {answer}, correct was {self.current_math.answer}")
            self._status(
                f"💦 Splash! Answer: {self.current_math.answer}. You said: {answer}")
        self.current_math = None
        self.awaiting_math_answer = False

    def _cmd_status(self):
        s = self.student
        total_tests = len(s.test_scores)
        correct_tests = sum(1 for v in s.test_scores.values() if v)
        lines = [
            f"  {C.BOLD}Agent Student: @{s.name}{C.RESET}",
            f"  Room: {s.room.value}",
            f"  Ticks: {s.tick_count}",
            f"  Quests: {len(s.quests_done)}/{len(QUEST_DB)} done ({', '.join(s.quests_done) or 'none'})",
            f"  Cannon: {s.cannon_hits}/{s.cannon_shots} hits",
            f"  Tests: {correct_tests}/{total_tests} correct",
            f"  Last: {s.last_action}",
        ]
        # Render as a popup
        self._status("\n".join(lines))

    def _cmd_who(self):
        lines = []
        for name, s in self.students.items():
            lines.append(f"  @{name} — {s.room.value} (ticks: {s.tick_count})")
        if not lines:
            lines.append(f"  Just you, @{self.identity}")
        self._status("\n".join(lines))

    def _show_help(self):
        help_text = f"""
  {C.BOLD}PLATO Holodeck — Commands{C.RESET}

  {C.YELLOW}Movement:{C.RESET}
    go <room>        Move: computer, whiteboard, quest, test, math, corridor
    look             Look around current room

  {C.YELLOW}Whiteboard:{C.RESET}
    write <text>     Write on the whiteboard (must be in Whiteboard Hall)
    clear board      Wipe the whiteboard

  {C.YELLOW}Wiki Quests:{C.RESET}
    take <id>        Start a quest (q1-q5)
    complete         Complete current quest

  {C.YELLOW}A/B Tests:{C.RESET}
    test             Get an A/B test question
    answer a/b       Answer the test

  {C.YELLOW}Math Cannon:{C.RESET}
    fire             Load an easy problem
    fire hard        Load a hard problem
    <number>         Type your answer to fire!

  {C.YELLOW}General:{C.RESET}
    status           Your student profile
    who              List agent students
    help             This help
    quit             Exit
"""
        self._status(help_text)

    # ── Main render ───────────────────────────────────────────────────

    def _render(self):
        clear()
        row = 1

        # Header
        move(row, 1)
        lines = self._render_header()
        for l in lines:
            sys.stdout.write(l + "\n")
        row += len(lines) + 1

        # Room content
        renderers = {
            Room.COMPUTER_LAB: self._render_computer_lab,
            Room.WHITEBOARD: self._render_whiteboard,
            Room.QUEST_HUB: self._render_quest_hub,
            Room.TEST_LOBBY: self._render_test_lobby,
            Room.MATH_CANNON: self._render_math_cannon,
            Room.CORRIDOR: self._render_corridor,
        }
        room_lines = renderers.get(self.student.room, self._render_corridor)()

        move(row, 1)
        sys.stdout.write(f"{'─' * WIDTH}\n")
        row += 1
        for l in room_lines:
            move(row, 1)
            sys.stdout.write(l + "\n")
            row += 1

        # Status message
        if self.status_msg and (time.time() - self.status_time < 30):
            move(row, 1)
            sys.stdout.write(f"{'─' * WIDTH}\n")
            row += 1
            for l in self.status_msg.split('\n'):
                move(row, 1)
                sys.stdout.write(f"  {l}\n")
                row += 1

        # Input line
        move(self.screen_rows - 1, 1)
        prompt = f"{C.BOLD}{C.GREEN}> {C.RESET}"
        sys.stdout.write(f"\033[K{prompt}{self.input_buf}")
        sys.stdout.flush()

    # ── Main loop ─────────────────────────────────────────────────────

    async def run(self):
        """Run the Holodeck TUI."""
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

        # Try MUD connection
        if self.mud:
            if self.mud.connect():
                self.mud.send(f"connect {self.identity} plato2026")
                await asyncio.sleep(0.5)
                self.mud.recv()
                self._status("Connected to PLATO MUD backend!")
            else:
                self._status("Running standalone (no MUD backend).")
        else:
            self._status("Welcome to the PLATO Holodeck! Type `help` for commands.")

        self.student.log_md("entered PLATO Holodeck")
        loop = asyncio.get_event_loop()

        # Non-blocking stdin reader
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        self._render()

        while self.running:
            try:
                # Read from stdin with timeout
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    # Poll MUD
                    if self.mud:
                        new = self.mud.recv()
                        if new != self.mud_buf:
                            self.mud_buf = new
                            self._render()
                    continue

                if not line:
                    break  # EOF
                line = line.decode().rstrip('\n')

                self._handle(line)
                self.input_buf = ""
                self._render()

            except KeyboardInterrupt:
                break

        self.student.log_md("left PLATO Holodeck")
        clear()
        print(f"Goodbye, @{self.identity}! {self.student.tick_count} ticks logged.")
        if self.mud:
            self.mud.close()


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OpenMAIC PLATO Holodeck TUI")
    parser.add_argument("--identity", "-i", default=os.environ.get("USER", "student"),
                        help="Your agent/student name")
    parser.add_argument("--host", default="", help="PLATO MUD host (optional)")
    parser.add_argument("--port", type=int, default=0, help="PLATO MUD port (optional)")
    parser.add_argument("--log-dir", default="logs", help="Directory for MD logs")
    args = parser.parse_args()

    mud = None
    if args.host and args.port:
        mud = MudConnection(args.host, args.port)

    holodeck = Holodeck(args.identity, mud_host=args.host, mud_port=args.port,
                        log_dir=args.log_dir)
    if mud:
        holodeck.mud = mud

    try:
        asyncio.run(holodeck.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Plato Client - Async MUD client with constraint-aware rendering.
"""

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Optional
import socket

@dataclass
class Perspective:
    identity: str
    room: str
    constraints: list = field(default_factory=list)
    visible_entities: list = field(default_factory=list)
    visible_exits: list = field(default_factory=list)
    can_execute: list = field(default_factory=list)

@dataclass
class Session:
    perspective: Perspective
    unread_tells: int = 0
    unread_missions: int = 0
    unread_constraints: int = 0

class PlatoClient:
    def __init__(self, identity: str, password: str, host: str = "147.224.38.131", port: int = 4040):
        self.identity = identity
        self.password = password
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.session: Optional[Session] = None
        self.buffer = ""
        
    async def connect(self) -> bool:
        """Connect to Plato MUD."""
        loop = asyncio.get_event_loop()
        
        def _connect():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
            sock.settimeout(0.1)
            return sock
        
        try:
            self.socket = await loop.run_in_executor(None, _connect)
            
            # Wait for welcome
            await asyncio.sleep(1.5)
            self._receive()
            print(f"Welcome buffer: {len(self.buffer)} chars")
            
            # Send credentials: connect username password
            cmd = f"connect {self.identity} {self.password}\n"
            self._send(cmd)
            await asyncio.sleep(1)
            self._receive()
            print(f"After connect buffer: {len(self.buffer)} chars")
            
            # Set up perspective
            self.session = Session(
                perspective=Perspective(
                    identity=self.identity,
                    room="limbo",
                    constraints=[],
                    visible_entities=[],
                    visible_exits=[],
                    can_execute=["look", "say", "tell", "go", "examine"]
                )
            )
            
            return True
            
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def _send(self, cmd: str):
        """Send command to MUD."""
        if self.socket:
            self.socket.sendall(cmd.encode())
    
    def _receive(self) -> str:
        """Receive data from MUD."""
        try:
            while True:
                data = self.socket.recv(4096)
                if not data:
                    break
                self.buffer += data.decode('utf-8', errors='ignore')
        except socket.timeout:
            pass
        return self.buffer
    
    async def send_command(self, cmd: str):
        """Send command and receive response."""
        self._send(cmd + "\n")
        await asyncio.sleep(0.3)
        self._receive()
        
    def render(self):
        """Render the TUI with constraint-aware perspective."""
        print("\033[2J")  # Clear
        print("\033[H")  # Home
        
        if not self.session:
            print("Not connected")
            return
        
        p = self.session.perspective
        
        # Header
        print("┌" + "─" * 62 + "┐")
        print("│ PLATO MUD v0.1" + " " * 47 + "│")
        print("│ Connected as: @{} │".format(p.identity))
        print("├" + "─" * 62 + "┤")
        
        # Room info
        print("│ Room: {:<52} │".format(p.room))
        print("├" + "─" * 62 + "┤")
        
        # Constraints (what we can see/do)
        print("│ CONSTRAINTS (First-Person View): │")
        for c in p.constraints[:5]:
            print("│   • {} │".format(c))
        if not p.constraints:
            print("│   (no constraints loaded) │")
        print("├" + "─" * 62 + "┤")
        
        # Activity feed
        print("│ INBOX │")
        if self.session.unread_tells > 0:
            print("│   📬 {} unread tells │".format(self.session.unread_tells))
        if self.session.unread_missions > 0:
            print("│   📋 {} mission updates │".format(self.session.unread_missions))
        if self.session.unread_constraints > 0:
            print("│   ⚠️  {} constraint events │".format(self.session.unread_constraints))
        if self.session.unread_tells == 0 and self.session.unread_missions == 0:
            print("│   (no unread) │")
        print("├" + "─" * 62 + "┤")
        
        # Buffer (MUD output) - strip ANSI codes
        import re
        clean = re.sub(r'\x1b\[[0-9;]*m', '', self.buffer)
        print("│ OUTPUT: │")
        lines = clean.split('\n')[-10:]
        for line in lines:
            display = line[:58] + "..." if len(line) > 58 else line
            print("│   {} │".format(display))
        print("├" + "─" * 62 + "┤")
        
        # Help
        print("│ Commands: look, say <msg>, tell <who> <msg>, go <room> │")
        print("│           constraints, missions, quit │")
        print("└" + "─" * 62 + "┘")
    
    async def run(self):
        """Main interactive loop."""
        if not await self.connect():
            print("Failed to connect")
            return
        
        # Do initial look
        await self.send_command("look")
        
        while True:
            self._receive()
            self.render()
            
            try:
                cmd = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("\n> ").strip()
                )
                
                if cmd.lower() in ('quit', 'exit', 'q'):
                    break
                    
                if cmd:
                    await self.send_command(cmd)
                    
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                print(f"Error: {e}")
        
        if self.socket:
            self.socket.close()

async def main():
    if len(sys.argv) < 3:
        print("Usage: python3 plato_client.py <username> <password>")
        return
    
    identity = sys.argv[1]
    password = sys.argv[2]
    client = PlatoClient(identity, password)
    await client.run()

if __name__ == "__main__":
    asyncio.run(main())

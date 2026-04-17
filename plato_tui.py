#!/usr/bin/env python3
"""
Plato TUI - Text User Interface for Plato-as-Common-UX
Connects to Plato MUD, shows first-person perspective based on constraints.
"""

import asyncio
import json
import sys
from dataclasses import dataclass, asdict
from typing import Optional
import socket
import time

# Simple telnet to Evennia MUD server
MUD_HOST = "147.224.38.131"
MUD_PORT = 4040

@dataclass
class Perspective:
    identity: str
    room: str
    constraints: list
    visible_entities: list
    can_execute: list

@dataclass 
class Session:
    perspective: Perspective
    unread_tells: int = 0
    mission_status: Optional[str] = None

class PlatoTUI:
    def __init__(self, identity: str):
        self.identity = identity
        self.session: Optional[Session] = None
        self.socket: Optional[socket.socket] = None
        self.buffer = ""
        
    def connect(self) -> bool:
        """Connect to Plato MUD server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((MUD_HOST, MUD_PORT))
            self.socket.settimeout(0.1)
            
            # Wait for welcome message
            time.sleep(1)
            self.receive()
            
            # Send credentials
            self.send(f"{self.identity}\n")
            time.sleep(0.5)
            self.receive()
            
            # Look around
            self.send("look\n")
            time.sleep(0.5)
            self.receive()
            
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def send(self, cmd: str):
        """Send command to MUD."""
        if self.socket:
            self.socket.sendall(cmd.encode())
    
    def receive(self) -> str:
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
    
    def render(self):
        """Render the TUI."""
        print("\033[2J")  # Clear screen
        print("\033[H")  # Home cursor
        
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║ PLATO MUD — Connecting as @{} {:<35} ║".format(
            self.identity[:30], ""))
        print("╠══════════════════════════════════════════════════════════════╣")
        
        if self.buffer:
            # Show last 20 lines of buffer
            lines = self.buffer.split('\n')
            for line in lines[-20:]:
                print(f"║ {line[:60]:<60} ║" if len(line) <= 60 else f"║ {line[:57]}... ║")
        else:
            print("║ {:^60} ║".format("Connecting..."))
        
        print("╠══════════════════════════════════════════════════════════════╣")
        print("║ Command: _")
        print("╚══════════════════════════════════════════════════════════════╝")
    
    def run(self):
        """Main loop."""
        if not self.connect():
            print("Failed to connect to Plato MUD")
            return
        
        while True:
            self.receive()
            self.render()
            
            try:
                cmd = input("\n> ")
                if cmd.lower() in ('quit', 'exit', 'q'):
                    break
                self.send(cmd + "\n")
                time.sleep(0.3)
            except (KeyboardInterrupt, EOFError):
                break
        
        if self.socket:
            self.socket.close()

def main():
    identity = sys.argv[1] if len(sys.argv) > 1 else "fmtest"
    tui = PlatoTUI(identity)
    tui.run()

if __name__ == "__main__":
    main()

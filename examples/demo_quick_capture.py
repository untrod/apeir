#!/usr/bin/env python3
"""Demo 1: Quick Capture — send a thought to Nous inbox from command line."""
import requests
import sys

BRAIN = "http://localhost:8770"
TOKEN = "your_token_here"

def capture(text, loop_type="quick"):
    r = requests.post(f"{BRAIN}/capture?token={TOKEN}", json={
        "content": text,
        "loop_type": loop_type,
    })
    result = r.json()
    if result.get("ok"):
        inbox = result["result"]["inbox"]
        print(f"Captured: {inbox['content'][:60]}")
        print(f"Category: {inbox['category']}")
        print(f"Tags: {inbox['tags']}")
        print(f"Status: {inbox['status']}")
    else:
        print(f"Error: {result}")

if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Review Chapter 3 on limits and continuity"
    capture(text)

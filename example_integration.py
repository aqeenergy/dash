"""How to drop Flammy into an EXISTING app without changing its UI or its code.

Run:  python example_integration.py
"""
import json
import urllib.request
import time

from flammy_agent import FlammyAgent

agent = FlammyAgent(default_gravity="micro")

# 1) Get notified. Your UI decides how to show it (flame colour = advisory.signal).
def on_advice(a):
    print(f"\n>>> FLAMMY [{a.signal.upper()}] {a.headline}\n    {a.summary}")
    for step in a.actions[:2]:
        print("    - " + step)

agent.subscribe(on_advice)

# 2) Hook your EXISTING functions with decorators (their code is untouched).
@agent.watch_simulation
def run_simulation(gravity, material, o2=21, ventilation=None, **other):
    return "simulation result..."

@agent.watch_chat
def ask_chatbot(question):
    return "The battery can enter thermal runaway and release CO and CO2."

run_simulation(gravity="lunar", material="fabric", o2=34, pressure_kpa=56.5)
ask_chatbot("What happens if a laptop overheats in the moon base?")

# 3) Or just tell it what happened.
agent.observe_experiment("saffire")

# 4) Your UI (any language) can read Flammy over HTTP - no UI changes needed.
agent.serve(port=8765, background=True)
time.sleep(0.2) # Dar tiempo al servidor para arrancar

req = urllib.request.Request("http://127.0.0.1:8765/flammy/observe",
                             json.dumps({"type": "simulation", "gravity": "micro", "material": "polymer",
                                         "o2": 30, "ventilation": "none"}).encode(),
                             {"Content-Type": "application/json"})
print("\nHTTP POST /flammy/observe ->", json.loads(urllib.request.urlopen(req).read())["headline"])
print("HTTP GET  /flammy/latest  ->", json.loads(urllib.request.urlopen("http://127.0.0.1:8765/flammy/latest").read())["signal"])
agent.stop()
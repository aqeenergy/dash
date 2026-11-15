"""FlammyAgent: the vigilant advisor you drop into an existing app.

It never touches your UI. It only (1) observes events you feed it - directly or
by wrapping your existing functions - and (2) emits Advisory objects through
whichever channel you choose: callbacks, a queue, polling, or HTTP/SSE.
"""
from __future__ import annotations

import functools
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import knowledge as K
from .engine import Advisory, advise

log = logging.getLogger("flammy")


class FlammyAgent:
    def __init__(self, default_gravity: str = "micro", dedupe_seconds: float = 8.0,
                 max_history: int = 100, extra_rules: Optional[List[Dict[str, Any]]] = None,
                 raise_errors: bool = False):
        """
        default_gravity : used when an event does not say (micro | lunar | earth).
        dedupe_seconds  : an event of the same type with the same hazards inside this
                          window is returned with advisory.repeat=True and NOT pushed to
                          subscribers (stops alert spam while a user drags a slider).
        raise_errors    : False (default) = the agent never breaks your app; errors are logged.
        """
        self.default_gravity = default_gravity
        self.dedupe_seconds = dedupe_seconds
        self.extra_rules = extra_rules or []
        self.raise_errors = raise_errors
        self._lock = threading.RLock()
        self._history: List[Advisory] = []
        self._max = max_history
        self._unread: List[Advisory] = []
        self._callbacks: List[Callable[[Advisory], None]] = []
        self._queues: List["queue.Queue[Advisory]"] = []
        self._last_sig: Dict[str, tuple] = {}
        self._server = None

    # ------------------------------------------------------------ observing
    def observe_simulation(self, params: Optional[Dict[str, Any]] = None, **kwargs) -> Optional[Advisory]:
        """A simulation was run/configured. Pass parameters as a dict and/or keywords:
        gravity, material, o2, pressure_kpa|pressure_psi, ventilation|flow_cm_s, ignition."""
        p = dict(params or {}, **kwargs)
        return self._observe("simulation", params=p)

    def observe_question(self, question: str, answer: str = "") -> Optional[Advisory]:
        """The user asked the general chatbot something (and the AI answered)."""
        return self._observe("question", text=f"{question} . {answer or ''}")

    def observe_experiment(self, experiment: Any, **overrides) -> Optional[Advisory]:
        """An experiment was opened. `experiment` is an id ('fm2', 'luci', 'sofie', 'flare',
        'saffire', 'cir') or a free-text name. Keywords override the experiment's defaults."""
        exp = K.EXPERIMENTS.get(str(experiment).lower()) if not isinstance(experiment, dict) else experiment
        if exp is None:
            return self._observe("experiment", text=str(experiment), params=overrides)
        return self._observe("experiment", params=dict(exp.get("ctx", {}), **overrides), experiment=exp)

    def observe(self, event_type: str, **data) -> Optional[Advisory]:
        """Generic entry point: event_type is simulation | question | experiment."""
        if event_type == "simulation":
            return self.observe_simulation(**data)
        if event_type == "question":
            return self.observe_question(data.get("question", ""), data.get("answer", ""))
        if event_type == "experiment":
            exp = data.pop("experiment", data.pop("id", ""))
            return self.observe_experiment(exp, **data)
        return self._observe("manual", params=data.get("params"), text=data.get("text", ""))

    def advise_only(self, params: Optional[Dict[str, Any]] = None, text: str = "") -> Advisory:
        """Compute an advisory without recording it or notifying anyone."""
        return advise(params, text, "manual", self.default_gravity, extra_rules=self.extra_rules)

    def _observe(self, event_type: str, params=None, text: str = "", experiment=None) -> Optional[Advisory]:
        try:
            a = advise(params, text, event_type, self.default_gravity, experiment, self.extra_rules)
            sig = tuple(h["id"] for h in a.hazards) + (a.context["gravity"],)
            with self._lock:
                a.repeat = (self._last_sig.get(event_type, (None, ()))[1] == sig
                            and time.time() - self._last_sig[event_type][0] < self.dedupe_seconds)
                self._last_sig[event_type] = (time.time(), sig)
                self._history.insert(0, a)
                del self._history[self._max:]
                if not a.repeat:
                    self._unread.append(a)
                cbs, qs = list(self._callbacks), list(self._queues)
            if not a.repeat:
                for cb in cbs:
                    try:
                        cb(a)
                    except Exception:      # a bad subscriber must not break the agent or the app
                        log.exception("Flammy subscriber failed")
                for q in qs:
                    try:
                        q.put_nowait(a)
                    except queue.Full:
                        pass
            return a
        except Exception:
            log.exception("Flammy could not process the event")
            if self.raise_errors:
                raise
            return None

    # ------------------------------------------------- hooking existing code
    def watch_simulation(self, func: Optional[Callable] = None, *, params: Optional[Callable[..., Dict[str, Any]]] = None):
        """Decorator: observe every call of your simulation function, unchanged.
        By default the keyword arguments (and any dict argument) are taken as parameters;
        pass params=lambda *a, **k: {...} to map your own signature."""
        def deco(f):
            @functools.wraps(f)
            def wrapper(*a, **k):
                try:
                    p = params(*a, **k) if params else dict({kk: v for x in a if isinstance(x, dict) for kk, v in x.items()}, **k)
                    self.observe_simulation(p)
                except Exception:
                    log.exception("Flammy watch_simulation failed")
                return f(*a, **k)
            return wrapper
        return deco(func) if func else deco

    def watch_chat(self, func: Optional[Callable] = None, *, question: Optional[Callable[..., str]] = None,
                   answer: Optional[Callable[[Any], str]] = None):
        """Decorator: observe a chatbot function. The question is the first str argument (or
        question=...), the answer is the return value (str, or dict with 'answer'/'text')."""
        def deco(f):
            @functools.wraps(f)
            def wrapper(*a, **k):
                result = f(*a, **k)
                try:
                    q = question(*a, **k) if question else next((x for x in list(a) + list(k.values()) if isinstance(x, str)), "")
                    r = answer(result) if answer else (result.get("answer") or result.get("text") or "") if isinstance(result, dict) else str(result or "")
                    self.observe_question(q, r)
                except Exception:
                    log.exception("Flammy watch_chat failed")
                return result
            return wrapper
        return deco(func) if func else deco

    # ------------------------------------------------------- output channels
    def subscribe(self, callback: Callable[[Advisory], None]) -> Callable[[], None]:
        """Call `callback(advisory)` for every new (non-repeat) advisory. Returns an unsubscribe function."""
        with self._lock:
            self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback) if callback in self._callbacks else None

    def subscribe_queue(self, maxsize: int = 100) -> "queue.Queue[Advisory]":
        """A queue.Queue that receives every new advisory (for threads / SSE / websockets)."""
        q: "queue.Queue[Advisory]" = queue.Queue(maxsize)
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe_queue(self, q) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def latest(self) -> Optional[Advisory]:
        with self._lock:
            return self._history[0] if self._history else None

    def history(self, n: int = 20) -> List[Advisory]:
        with self._lock:
            return list(self._history[:n])

    def pending(self) -> List[Advisory]:
        """Advisories not yet read (oldest first); reading clears them. Handy for polling."""
        with self._lock:
            out, self._unread = self._unread, []
            return out

    def set_default_gravity(self, gravity: str) -> None:
        self.default_gravity = gravity

    # ------------------------------------------------------------ HTTP / SSE
    def serve(self, host: str = "127.0.0.1", port: int = 8765, background: bool = True, cors: str = "*"):
        """Start a tiny dependency-free HTTP server your existing UI can call:
            GET  /flammy/latest   GET /flammy/pending   GET /flammy/history
            GET  /flammy/stream   (Server-Sent Events: new EventSource(url))
            POST /flammy/observe  {"type":"simulation|question|experiment", ...}
        """
        from .server import make_server
        self._server = make_server(self, host, port, cors)
        if background:
            threading.Thread(target=self._server.serve_forever, daemon=True, name="flammy-http").start()
        else:
            self._server.serve_forever()
        return self._server

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

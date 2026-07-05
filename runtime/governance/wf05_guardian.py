"""
wf05_guardian.py v1.1.0
Guardian Control Plane -- WF-05 Budget + Veto + Consensus
EAG: EAG-S282-GUARDIAN-BUDGET-IMPL-001
Patch: EAG-S283-GUARDIAN-WINDOW-FIX-001 (expires_at 검증 제거)
Port: 8450
"""
import json, os, re, threading, time, uuid
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

GUARDIAN_VERSION = "1.1.0"
GUARDIAN_HOST = "127.0.0.1"
GUARDIAN_PORT = 8450
ROOT = "/opt/arss/engine/arss-protocol/runtime/governance"
KST = timezone(timedelta(hours=9))
_lock = threading.Lock()

def _now(): return datetime.now(KST).isoformat()
def _load_json(p):
    with open(p, encoding="utf-8") as f: return json.load(f)
def _save_json(p, d):
    with open(p, "w", encoding="utf-8") as f: json.dump(d, f, indent=2, ensure_ascii=False)
def _append_jsonl(p, e):
    with open(p, "a", encoding="utf-8") as f: f.write(json.dumps(e, ensure_ascii=False)+"\n")

def _load_active_window():
    reg = _load_json(ROOT+"/window_registry.json")
    wid = reg.get("active_window_id", "")
    if not wid: return None, "NO_ACTIVE_WINDOW"
    wp = ROOT+"/"+wid+".json"
    if not os.path.exists(wp): return None, "WINDOW_FILE_NOT_FOUND"
    w = _load_json(wp)
    st = w.get("status", "")
    if st != "ACTIVE": return None, "WINDOW_NOT_ACTIVE:"+st
    # expires_at 검증 제거 (EAG-S283-GUARDIAN-WINDOW-FIX-001)
    # 예산 통제: budget_remaining / Veto: /veto 엔드포인트로 충분
    return w, None

def _load_budget(): return _load_json(ROOT+"/budget/WF05_BUDGET_STATE.json")
def _save_budget(b): _save_json(ROOT+"/budget/WF05_BUDGET_STATE.json", b)
def _load_policy(): return _load_json(ROOT+"/WF05_POLICY.json")

def _emit_alert(severity, event, source, detail=""):
    _append_jsonl(ROOT+"/alerts.jsonl", {"severity":severity,"event":event,"source":source,"detail":detail,"timestamp":_now()})

def _record_consensus(phase, actor, decision, detail=""):
    _append_jsonl(ROOT+"/ledger/consensus_ledger.jsonl", {"phase":phase,"actor":actor,"decision":decision,"detail":detail,"timestamp":_now()})

def handle_authorize(body):
    command = body.get("command", "")
    session = body.get("session", "S000")
    with _lock:
        try: policy = _load_policy()
        except Exception as e: return {"ok":False,"error":"POLICY_LOAD_FAIL:"+str(e)}
        pst = policy.get("status", "")
        if pst != "ACTIVE":
            _emit_alert("HIGH", "POLICY_INACTIVE", "guardian", "status="+pst)
            return {"ok":False,"error":"POLICY_INACTIVE"}
        allowed = policy.get("allowed_commands", [])
        if command and command not in allowed:
            _emit_alert("MEDIUM", "COMMAND_NOT_ALLOWED", "guardian", "command="+command)
            return {"ok":False,"error":"COMMAND_NOT_ALLOWED:"+command}
        window, err = _load_active_window()
        if window is None:
            _emit_alert("HIGH", "WINDOW_INVALID", "guardian", err)
            return {"ok":False,"error":err}
        try: budget = _load_budget()
        except Exception as e: return {"ok":False,"error":"BUDGET_LOAD_FAIL:"+str(e)}
        bst = budget.get("state", "")
        if bst == "LOCKED":
            _emit_alert("HIGH", "BUDGET_LOCKED", "guardian")
            return {"ok":False,"error":"BUDGET_LOCKED"}
        if budget.get("budget_remaining", 0) <= 0:
            budget["state"] = "LOCKED"; budget["updated_at"] = _now()
            _save_budget(budget)
            _emit_alert("HIGH", "BUDGET_EXHAUSTED", "guardian")
            return {"ok":False,"error":"BUDGET_EXHAUSTED"}
        import re as _re
        m = _re.search(r"\d+", session)
        sn = m.group(0) if m else "000"
        ds = datetime.now(KST).strftime("%Y%m%d")
        approval_id = "EAG-S"+sn+"-WF05-WIN-"+ds
        budget["budget_used"] = budget.get("budget_used",0)+1
        budget["budget_remaining"] = budget.get("budget_remaining",0)-1
        budget["last_exec_at"] = _now(); budget["updated_at"] = _now()
        if budget["budget_remaining"] <= 0:
            budget["state"] = "LOCKED"
            _emit_alert("MEDIUM", "BUDGET_LAST_USED", "guardian", "remaining=0")
        _save_budget(budget)
        _record_consensus("AUTHORIZATION", "guardian", "APPROVED", "cmd="+command+" aid="+approval_id)
        return {"ok":True,"approval_id":approval_id,"window_id":window["window_id"],
                "budget_remaining":budget["budget_remaining"],"budget_used":budget["budget_used"]}

def handle_status(body):
    try:
        pol = _load_policy(); bud = _load_budget()
        win, err = _load_active_window()
        return {"ok":True,"version":GUARDIAN_VERSION,
                "policy_status":pol.get("status"),
                "window_id":win["window_id"] if win else None,
                "window_error":err,
                "budget_remaining":bud.get("budget_remaining"),
                "budget_used":bud.get("budget_used"),
                "budget_state":bud.get("state"),
                "timestamp":_now()}
    except Exception as e: return {"ok":False,"error":str(e)}

def handle_veto(body):
    if body.get("issued_by") != "Beo": return {"ok":False,"error":"DENY: veto must be issued by Beo"}
    try:
        p = _load_policy()
        p["status"] = "PAUSED"; p["paused_at"] = _now(); p["paused_by"] = "Beo"
        _save_json(ROOT+"/WF05_POLICY.json", p)
        _emit_alert("CRITICAL", "BEO_VETO_ISSUED", "Beo", body.get("reason",""))
        _record_consensus("VETO", "Beo", "PAUSED", "reason="+body.get("reason",""))
        return {"ok":True,"status":"PAUSED","timestamp":_now()}
    except Exception as e: return {"ok":False,"error":str(e)}

def handle_resume(body):
    if body.get("issued_by") != "Beo": return {"ok":False,"error":"DENY: resume must be issued by Beo"}
    try:
        p = _load_policy()
        p["status"] = "ACTIVE"; p["resumed_at"] = _now()
        _save_json(ROOT+"/WF05_POLICY.json", p)
        _record_consensus("RESUME", "Beo", "ACTIVE")
        return {"ok":True,"status":"ACTIVE","timestamp":_now()}
    except Exception as e: return {"ok":False,"error":str(e)}

class GuardianHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): pass
    def _send_json(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def _read_body(self):
        cl = int(self.headers.get("Content-Length",0))
        raw = self.rfile.read(cl) if cl>0 else b"{}"
        try: return json.loads(raw)
        except: return {}
    def do_GET(self):
        if self.path=="/health": self._send_json(200,{"status":"ok","version":GUARDIAN_VERSION})
        elif self.path=="/status": self._send_json(200,handle_status({}))
        else: self._send_json(404,{"error":"not_found"})
    def do_POST(self):
        body = self._read_body()
        if self.path=="/authorize":
            r = handle_authorize(body)
            self._send_json(200 if r["ok"] else 403, r)
        elif self.path=="/veto":
            r = handle_veto(body)
            self._send_json(200 if r["ok"] else 403, r)
        elif self.path=="/resume":
            r = handle_resume(body)
            self._send_json(200 if r["ok"] else 403, r)
        else: self._send_json(404,{"error":"not_found"})

class ThreadedServer(ThreadingMixIn, HTTPServer): daemon_threads=True

if __name__ == "__main__":
    import signal, sys
    def _shutdown(s,f): sys.exit(0)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    server = ThreadedServer((GUARDIAN_HOST, GUARDIAN_PORT), GuardianHandler)
    server.serve_forever()

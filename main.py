from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
import json, asyncio

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ── Campo Las Pinaillas ───────────────────────────────────────────────────────
STROKE_INDEX = [5,11,17,3,7,1,15,13,9,4,16,8,10,14,6,18,12,2]
PAR          = [4,4,3,5,4,4,3,4,5,4,5,3,4,5,4,4,3,4]

def golpes_hoyo(hcp: int, hi: int) -> int:
    si = STROKE_INDEX[hi]
    return hcp // 18 + (1 if si <= hcp % 18 else 0)

# ── Jugadores ─────────────────────────────────────────────────────────────────
PLAYERS = {
    "Jaime Álvarez-Castells": {"team":"eu","hcp":8},
    "Manuel Carabias":        {"team":"eu","hcp":7},
    "Javier Alkalafi":        {"team":"eu","hcp":8},
    "Mateo Escalante":        {"team":"eu","hcp":16},
    "Álvaro Bermúdez":        {"team":"eu","hcp":18},
    "Jaime Díaz-Pineda":      {"team":"eu","hcp":23},
    "Javier Pérez-Marsá":     {"team":"eu","hcp":30},
    "Jorge Berned":           {"team":"eu","hcp":30},
    "Rafael Gutiérrez":       {"team":"eu","hcp":30},
    "Nacho Peña":             {"team":"eu","hcp":30},
    "Gustavo Aguilar":        {"team":"usa","hcp":5},
    "Justo Lorenzo":          {"team":"usa","hcp":8},
    "Lalo Pérez-Marsá":       {"team":"usa","hcp":17},
    "Fernando García":        {"team":"usa","hcp":9},
    "Lucas González-Pinto":   {"team":"usa","hcp":18},
    "Íñigo Cubo":             {"team":"usa","hcp":27},
    "Ignacio Guldentops":     {"team":"usa","hcp":29},
    "Jaime Aguirre":          {"team":"usa","hcp":30},
    "Lolo Hernández":         {"team":"usa","hcp":30},
    "Ignacio Banegas":        {"team":"usa","hcp":30},
}

# ── 5 Partidas 2v2 ────────────────────────────────────────────────────────────
MATCHES_DEF = [
    {"id":0,"label":"Partida 1","eu":["Jaime Álvarez-Castells","Jorge Berned"],   "usa":["Gustavo Aguilar","Lolo Hernández"]},
    {"id":1,"label":"Partida 2","eu":["Manuel Carabias","Nacho Peña"],            "usa":["Justo Lorenzo","Jaime Aguirre"]},
    {"id":2,"label":"Partida 3","eu":["Mateo Escalante","Javier Pérez-Marsá"],    "usa":["Ignacio Banegas","Lalo Pérez-Marsá"]},
    {"id":3,"label":"Partida 4","eu":["Jaime Díaz-Pineda","Álvaro Bermúdez"],     "usa":["Íñigo Cubo","Fernando García"]},
    {"id":4,"label":"Partida 5","eu":["Rafael Gutiérrez","Javier Alkalafi"],      "usa":["Lucas González-Pinto","Ignacio Guldentops"]},
]

PLAYER_MATCH = {n: md["id"] for md in MATCHES_DEF for n in md["eu"]+md["usa"]}
ADMIN_PASSWORD = "pinaillas2026"

# ── State ─────────────────────────────────────────────────────────────────────
def blank_hole():
    return {"scores":{},"done":False,
            "eu_best":None,"eu_worst":None,"usa_best":None,"usa_worst":None,
            "pts_eu_m":0,"pts_usa_m":0,"pts_eu_p":0,"pts_usa_p":0}

def make_state():
    return {"matches":[
        {"id":m["id"],"label":m["label"],"eu":m["eu"],"usa":m["usa"],
         "holes":[blank_hole() for _ in range(18)]}
        for m in MATCHES_DEF]}

state = make_state()

def calc(match, hi):
    h = match["holes"][hi]
    eu_n = [h["scores"][n]-golpes_hoyo(PLAYERS[n]["hcp"],hi) for n in match["eu"] if n in h["scores"]]
    usa_n= [h["scores"][n]-golpes_hoyo(PLAYERS[n]["hcp"],hi) for n in match["usa"] if n in h["scores"]]
    if not eu_n or not usa_n: h["done"]=False; return
    h["eu_best"],h["eu_worst"]   = min(eu_n),max(eu_n)
    h["usa_best"],h["usa_worst"] = min(usa_n),max(usa_n)
    if   h["eu_best"]  < h["usa_best"]:  h["pts_eu_m"],h["pts_usa_m"]=2,0
    elif h["usa_best"] < h["eu_best"]:   h["pts_eu_m"],h["pts_usa_m"]=0,2
    else:                                h["pts_eu_m"],h["pts_usa_m"]=0,0
    if   h["eu_worst"] > h["usa_worst"]: h["pts_eu_p"],h["pts_usa_p"]=0,1
    elif h["usa_worst"]> h["eu_worst"]:  h["pts_eu_p"],h["pts_usa_p"]=1,0
    else:                                h["pts_eu_p"],h["pts_usa_p"]=0,0
    h["done"]=True

def totals():
    eu=usa=0; mp=[]
    for m in state["matches"]:
        e=sum(h["pts_eu_m"]+h["pts_eu_p"] for h in m["holes"] if h["done"])
        u=sum(h["pts_usa_m"]+h["pts_usa_p"] for h in m["holes"] if h["done"])
        eu+=e; usa+=u; mp.append({"eu":e,"usa":u})
    return eu,usa,mp

def full():
    eu,usa,mp=totals()
    return {**state,"total_eu":eu,"total_usa":usa,"match_pts":mp,
            "players":PLAYERS,"si":STROKE_INDEX,"par":PAR,"pm":PLAYER_MATCH}

# ── WebSocket ─────────────────────────────────────────────────────────────────
class WS:
    def __init__(self): self.conns=[]
    async def add(self,ws): await ws.accept(); self.conns.append(ws)
    def rm(self,ws):
        if ws in self.conns: self.conns.remove(ws)
    async def broadcast(self,d):
        dead=[]
        for ws in self.conns:
            try: await ws.send_json(d)
            except: dead.append(ws)
        for ws in dead: self.rm(ws)

mgr=WS()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/",response_class=HTMLResponse)
async def root(r:Request): return templates.TemplateResponse("index.html",{"request":r})

@app.get("/api/state")
async def get_state(): return full()

class ScoreIn(BaseModel):
    match_id:int; hole:int; player:str; score:Optional[int]

@app.post("/api/score")
async def score(p:ScoreIn):
    m=next((m for m in state["matches"] if m["id"]==p.match_id),None)
    if not m: raise HTTPException(400,"not found")
    if p.score is None: m["holes"][p.hole]["scores"].pop(p.player,None)
    else: m["holes"][p.hole]["scores"][p.player]=p.score
    calc(m,p.hole)
    await mgr.broadcast({"type":"state","data":full()})
    return {"ok":True}

class PwIn(BaseModel):
    password:str

@app.post("/api/admin")
async def admin(p:PwIn):
    if p.password==ADMIN_PASSWORD: return {"ok":True}
    raise HTTPException(403,"wrong")

@app.post("/api/reset")
async def reset():
    global state; state=make_state()
    await mgr.broadcast({"type":"state","data":full()})
    return {"ok":True}

@app.websocket("/ws")
async def ws(ws:WebSocket):
    await mgr.add(ws)
    await ws.send_json({"type":"state","data":full()})
    try:
        while True: await asyncio.sleep(30); await ws.send_json({"type":"ping"})
    except WebSocketDisconnect: mgr.rm(ws)

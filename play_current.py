"""Single-user browser exploration of current split games; one in-memory session."""
import argparse
import json
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from scripts.adaptive_escape import AdaptivePeer
from scripts.coop_original import gv

ROOT = Path(__file__).resolve().parent
GAMES = sorted(p.stem for p in (ROOT/'data/roles').glob('game*-easy.json'))
TITLES = ['거울·작업실','병원·엘리베이터','당구장','주방·숨겨진 방','기숙사·제어실','아파트·서재','상점·사무실','오두막','지하 연구실','밴','창고','세탁실']
LOCK = threading.RLock()
SESSION = None

class Session:
    def __init__(self, game):
        self.temp = tempfile.TemporaryDirectory()
        self.agent = AdaptivePeer(game, self.temp.name, self.call, max_steps=100000)
        self.agent.setup('human', game)
        self.game = game
        self.role = 'A'
        self.action = ''
        self.escaped = False
        self.events = []
        # Human chooses the acting role freely; no automatic 4-decision scheduling.
        self.agent.pick_role = lambda: self.role
    def call(self, step, messages):
        return {'raw': 'Thought: Human action.\nAction: '+self.action, 'messages': messages}
    def state(self, role):
        a=self.agent
        view=a.view(role)
        scene=a.graph.scenes[a.where[role]]
        # Use the same visibility and role-specific movement logic as view().
        from scripts.coop_original import ROLE_VISIBLE
        rel, cache = scene.scene_relations, dict(scene.action_cache)
        home=a.graph.scenes.get(a.role_starts.get(role))
        visible=home.visible if home else None
        try:
            if home and not home.visible: home.visible=ROLE_VISIBLE
            scene.scene_relations=a.role_relations(role,scene.name)
            _, actions=scene.actions(True)
            options=[{'type':kind,'label':label} for kind,label,*_ in actions.values()]
        finally:
            scene.scene_relations,scene.action_cache=rel,cache
            if home: home.visible=visible
        return {'game':self.game,'role':role,'view':view,'options':options,
                'bag':a.bags[role].describe(False), 'tools':list(a.bags[role].tools),
                'events':self.events[-120:], 'cost':a.cost,'escaped':self.escaped}
    def step(self, role, action):
        self.role=role; self.action=action
        self.escaped=self.agent.act(len(self.agent.history))
        h=self.agent.history[-1]
        self.events.append({'role':role,'action':h['action_answer'],'feedback':h['response']})
        return self.state(role)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def response(self,code,value,kind='application/json; charset=utf-8'):
        data=json.dumps(value,ensure_ascii=False).encode() if kind.startswith('application/json') else value
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/':return self.response(200,(ROOT/'web/current.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/api/games':return self.response(200,[{'id':g,'title':t,'warning':g=='game1-4-easy'} for g,t in zip(GAMES,TITLES)])
        self.response(404,{'error':'찾을 수 없습니다.'})
    def do_POST(self):
        global SESSION
        origin=self.headers.get('Origin')
        if origin:
            u=urlparse(origin)
            if u.scheme!='http' or u.hostname not in ('127.0.0.1','localhost') or u.port!=self.server.server_port:
                return self.response(403,{'error':'허용되지 않은 요청입니다.'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=4096:raise ValueError('요청 크기가 올바르지 않습니다.')
            data=json.loads(self.rfile.read(n));role=data.get('role','A')
            if role not in ('A','B'):raise ValueError('역할이 올바르지 않습니다.')
            with LOCK:
                if self.path=='/api/start':
                    game=data.get('game')
                    if game not in GAMES:raise ValueError('문제를 선택하세요.')
                    if SESSION:SESSION.temp.cleanup()
                    SESSION=Session(game)
                    out=SESSION.state(role)
                elif self.path=='/api/state':
                    if SESSION is None:raise ValueError('먼저 게임을 시작하세요.')
                    out=SESSION.state(role)
                elif self.path=='/api/action':
                    if SESSION is None:raise ValueError('먼저 게임을 시작하세요.')
                    action=data.get('action','')
                    if not isinstance(action,str) or not re.fullmatch(r'(click|move|apply|input|craft|send|give)\([^\n\r]*\)',action):raise ValueError('행동 형식이 올바르지 않습니다.')
                    if SESSION.escaped:raise ValueError('이미 탈출했습니다. 새 게임을 시작하세요.')
                    out=SESSION.step(role,action)
                else:return self.response(404,{'error':'찾을 수 없습니다.'})
            self.response(200,out)
        except (ValueError,TypeError,json.JSONDecodeError) as e:self.response(400,{'error':str(e)})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'현재 분할 직접 플레이: http://127.0.0.1:{server.server_port} (종료: Ctrl+C)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()

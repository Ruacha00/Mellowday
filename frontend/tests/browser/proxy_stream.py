"""Verify real Nginx streaming, long wait and disconnect cleanup against fixture."""
import argparse
import json
from pathlib import Path
import time
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:18022')
parser.add_argument('--output', type=Path, default=Path('.scratch/docker-frontend/proxy-stream.json'))
args = parser.parse_args()
URL = args.url.rstrip('/')
checks={}
started=time.monotonic()
received=[]
with httpx.Client(timeout=90) as client:
    with client.stream('POST',URL+'/api/chat',json={'session_id':'proxy-delay','message':'长等待'}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('data: '):
                event=json.loads(line[6:]);received.append(event['type'])
                if event['type']=='text_delta':
                    if 'first_text_seconds' not in checks:checks['first_text_seconds']=round(time.monotonic()-started,3)
                    else:checks['last_text_seconds']=round(time.monotonic()-started,3)
    assert checks['first_text_seconds']<10,checks
    assert checks['last_text_seconds']>=64,checks
    assert received[-1]=='done',received
    checks['long_wait_done']=True
    with client.stream('POST',URL+'/api/chat',json={'session_id':'proxy-stop','message':'慢速'}) as response:
        for line in response.iter_lines():
            if line.startswith('data: ') and json.loads(line[6:])['type']=='text_delta':break
    started=time.monotonic()
    with client.stream('POST',URL+'/api/chat',json={'session_id':'proxy-stop','message':'继续'}) as response:
        kinds=[json.loads(line[6:])['type'] for line in response.iter_lines() if line.startswith('data: ')]
    checks['next_turn_seconds']=round(time.monotonic()-started,3)
    assert checks['next_turn_seconds']<5 and kinds[-1]=='done',checks
    detail=client.get(URL+'/api/sessions/proxy-stop').json()
    assert [m['content'] for m in detail['messages'] if m['role']=='user']==['慢速','继续']
    checks['disconnect_releases_session']=True
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(checks,indent=2),encoding='utf-8')
print(json.dumps(checks,indent=2))

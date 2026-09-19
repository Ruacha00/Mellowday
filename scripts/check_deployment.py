"""Check static/HTTP deployment. Optional writes are for isolated data only."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8021')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--write-test-data', action='store_true')
    args = parser.parse_args()
    url = args.url.rstrip('/')
    checks = {}

    def get(path):
        try:
            with urllib.request.urlopen(url + path, timeout=15) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    status, headers, body = get('/')
    checks['vue_entry'] = status == 200 and b'/assets/' in body and b'type="module"' in body
    checks['html_revalidates'] = 'no-cache' in headers.get('Cache-Control', '')
    status, headers, body = get('/api/health')
    checks['api_healthy'] = status == 200 and json.loads(body).get('ok') is True
    for path in ['/api/not-found', '/api', '/assets/not-found.js', '/runtime/not-found.webp']:
        status, headers, body = get(path)
        checks[path] = status == 404
        if path.startswith('/api'):
            checks[path + '_json'] = 'application/json' in headers.get('Content-Type', '')
    _, _, body = get('/')
    asset = re.search(rb'src="(/assets/[^\"]+\.js)"', body)
    if asset:
        status, headers, _ = get(asset[1].decode())
        checks['hashed_asset_cached'] = status == 200 and 'immutable' in headers.get('Cache-Control', '')
    if args.write_test_data:
        title = f'deployment-probe-{int(time.time())}'
        request = urllib.request.Request(url + '/api/records/notes', data=json.dumps({'title': title, 'detail': 'isolated persistence probe'}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=15) as r:
            record = json.load(r)
        _, _, body = get('/api/records/notes')
        checks['record_readback'] = any(row['id'] == record['id'] for row in json.loads(body)['records'])
    result = {'url': url, 'checks': checks, 'ok': all(checks.values())}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()

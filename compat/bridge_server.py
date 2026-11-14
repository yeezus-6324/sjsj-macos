#!/usr/bin/env python3
"""Loopback-only game adapter for unmodified official resources. Official authentication remains in the login webview."""
import base64, hashlib, json, os, re, secrets, select, socket, struct, sys, threading, time
from collections import OrderedDict, deque
from contextlib import closing
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parent))
def write_event(*args): pass
def start_metrics(*args): pass
import urllib.error, urllib.parse, urllib.request
import sqlite3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import NamedTuple, Optional
ROOT=Path(__file__).resolve().parent
RUNTIME_CONTENT_TYPES = {
 '.js': 'text/javascript; charset=utf-8',
 '.wasm': 'application/wasm',
 '.json': 'application/json',
 '.map': 'application/json',
}
KEY=os.environ['SJSJ_BRIDGE_KEY']
SESSIONS={}; EVENTS=[]; CRITICAL_EVENTS=[]; LOCK=threading.Lock(); CACHE=OrderedDict()
RESOURCE_CACHE_BYTES = 96 * 1024 * 1024
RESOURCE_CACHE_ENTRIES = 1024
DYNAMIC_DISK_BYTES = 256 * 1024 * 1024
DYNAMIC_DISK_ENTRIES = 4096
DISK_REVALIDATION_WINDOW = 7 * 86400
DYNAMIC_DISK_LOCK = threading.Lock()
DYNAMIC_ASSET = re.compile(r'/www_sjsj(?:_s2)?/[0-9]{10}/resource/dynamic/[0-9]+')
VERSIONED_STATIC_ASSET = re.compile(
 r'/www_sjsj(?:_s2)?/[0-9]{10}/(?:[A-Za-z0-9_-]+/)*'
 r'(?:[A-Za-z0-9_-]+\.swf|loadingCfg_[0-9_]+\.data)'
)
RESOURCE_METRICS = dict(cache_hits=0, cache_hit_bytes=0, upstream_gets=0,
                        upstream_get_bytes=0, upstream_get_ms=0,
                        disk_hits=0, disk_hit_bytes=0, disk_revalidations=0, disk_revalidated_bytes=0)
MEMORY_SAMPLES = deque(maxlen=720)
BITMAP_CLASS_SAMPLES = deque(maxlen=180)
STARTED = time.monotonic()
MODE_FILE = ROOT / 'diagnostics-mode.txt'
DIAGNOSTIC_MODE = MODE_FILE.read_text().strip() if MODE_FILE.is_file() else None
DIAGNOSTICS = None
if DIAGNOSTIC_MODE in ('on', 'off', 'early'):
 sys.dont_write_bytecode = True
 from freeze_diagnostics import Diagnostics
 DIAGNOSTICS = Diagnostics()
ALLOWED_SUFFIXES=('wanwan4399.com','4399.com','5054399.com','3304399.net')
def allowed(host):return host and any(host==s or host.endswith('.'+s) for s in ALLOWED_SUFFIXES)

def cache_resource(url, body, content_type, ttl=None):
 with LOCK:
  CACHE[url] = body, content_type, time.monotonic() + ttl if ttl is not None else None
  CACHE.move_to_end(url)
  size = sum(len(entry[0]) for entry in CACHE.values())
  while size > RESOURCE_CACHE_BYTES or len(CACHE) > RESOURCE_CACHE_ENTRIES:
   _, removed = CACHE.popitem(last=False)
   size -= len(removed[0])

def cached_resource(url):
 with LOCK:
  entry = CACHE.get(url)
  if entry is None:
   return None
  body, content_type, expires = entry
  if expires is not None and expires <= time.monotonic():
   del CACHE[url]
   return None
  CACHE.move_to_end(url)
  RESOURCE_METRICS['cache_hits'] += 1
  RESOURCE_METRICS['cache_hit_bytes'] += len(body)
  return body, content_type

def dynamic_asset_ttl(headers, default=None):
 if headers.get('Set-Cookie') is not None or headers.get('Vary'):
  return None
 directives = {directive.strip().lower() for directive in headers.get('Cache-Control', '').split(',')}
 if directives & {'private', 'no-store', 'no-cache'}:
  return None
 ages = [int(match[1]) for directive in directives
         if (match := re.fullmatch(r'max-age\s*=\s*([0-9]{1,10})', directive))]
 if not ages and not any(d.startswith("max-age") for d in directives) and default is not None:
  ages = [default]
 if len(ages) != 1:
  return None
 age = headers.get('Age', '0')
 if not re.fullmatch(r'[0-9]{1,10}', age):
  return None
 return min(3600, max(0, ages[0] - int(age)))

class DiskAsset(NamedTuple):
 body: bytes
 content_type: str
 expires: float
 lifetime: Optional[int]
 etag: Optional[str]
 last_modified: Optional[str]

def dynamic_disk_resource(url, response=None, *, previous=None):
 # Keep the original assets table readable and writable by earlier builds.
 folder = Path.home() / 'Library' / 'Caches' / 'SJSJPublicAssets'
 try:
  with DYNAMIC_DISK_LOCK:
   folder.mkdir(mode=0o700, parents=True, exist_ok=True)
   with closing(sqlite3.connect(folder / 'assets.sqlite3', timeout=0.25)) as db, db:
    db.execute('CREATE TABLE IF NOT EXISTS assets (url TEXT PRIMARY KEY, body BLOB, content_type TEXT, expires REAL, accessed REAL)')
    db.execute("""CREATE TABLE IF NOT EXISTS asset_validators (
               url TEXT PRIMARY KEY, expires REAL, lifetime INTEGER, etag TEXT, last_modified TEXT)""")
    now = time.time()
    if response is None and previous is None:
     row = db.execute("""SELECT a.body, a.content_type, a.expires, v.lifetime, v.etag, v.last_modified
                      FROM assets a LEFT JOIN asset_validators v USING (url, expires)
                      WHERE a.url=? AND (a.expires>? OR
                        (a.expires>? AND (v.etag IS NOT NULL OR v.last_modified IS NOT NULL)))""",
                      (url, now, now - DISK_REVALIDATION_WINDOW)).fetchone()
     if row is not None:
      db.execute('UPDATE assets SET accessed=? WHERE url=? AND expires=?', (now, url, row[2]))
      return DiskAsset(*row)
     return None
    # Compare against the bytes' generation before refreshing or invalidating
    # an entry. Other requests can finish while the network request is pending.
    if previous is not None:
     if response is None:
      db.execute('DELETE FROM assets WHERE url=? AND expires=?', (url, previous.expires))
      db.execute('DELETE FROM asset_validators WHERE url=? AND expires=?', (url, previous.expires))
      return None
     ttl, etag, last_modified = response
     expires = now + ttl
     changed = db.execute('UPDATE assets SET expires=?, accessed=? WHERE url=? AND expires=?',
                          (expires, now, url, previous.expires))
     if changed.rowcount:
      db.execute('INSERT OR REPLACE INTO asset_validators VALUES (?, ?, ?, ?, ?)',
                 (url, expires, ttl, etag, last_modified))
     return None
    body, content_type, ttl, etag, last_modified = response
    expires = now + ttl
    db.execute('INSERT OR REPLACE INTO assets VALUES (?, ?, ?, ?, ?)', (url, body, content_type, expires, now))
    db.execute('INSERT OR REPLACE INTO asset_validators VALUES (?, ?, ?, ?, ?)',
               (url, expires, ttl, etag, last_modified))
    db.execute('DELETE FROM assets WHERE expires<=?', (now - DISK_REVALIDATION_WINDOW,))
    size, count = db.execute('SELECT SUM(LENGTH(body)), COUNT(*) FROM assets').fetchone()
    if size > DYNAMIC_DISK_BYTES or count > DYNAMIC_DISK_ENTRIES:
     for key, length in db.execute('SELECT url, LENGTH(body) FROM assets ORDER BY accessed, url').fetchall():
      db.execute('DELETE FROM assets WHERE url=?', (key,))
      size -= length
      count -= 1
      if size <= DYNAMIC_DISK_BYTES and count <= DYNAMIC_DISK_ENTRIES:
       break
    db.execute("""DELETE FROM asset_validators AS v WHERE NOT EXISTS
               (SELECT 1 FROM assets a WHERE a.url=v.url AND a.expires=v.expires)""")
 except (OSError, sqlite3.Error):
  return None

def event(kind, **fields):
 write_event(kind,fields)
 row=dict(kind=kind,**fields)
 with LOCK:
  if kind=='player' and fields.get('message','').startswith('critical:'):
   # Keep early crash evidence even when later frames emit repeated errors.
   if len(CRITICAL_EVENTS) < 32 and not any(
    prior['message'] == fields['message'] for prior in CRITICAL_EVENTS
   ):
    CRITICAL_EVENTS.append(dict(row, elapsed_seconds=round(time.monotonic() - STARTED, 3)))
  EVENTS.append(row);del EVENTS[:-160]
 # Never write query strings, cookies or account identifiers into diagnostics.
 print(json.dumps(row,ensure_ascii=False),flush=True)
def fetch(url,data=None,method=None,extra_headers=None):
 if not allowed(urllib.parse.urlsplit(url).hostname):raise ValueError('Host not permitted')
 req=urllib.request.Request(url,data=data,method=method,headers={'User-Agent':'Mozilla/5.0 (Macintosh; ARM Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15','Referer':'http://sjsj-client.wanwan4399.com/', **(extra_headers or {})})
 return urllib.request.urlopen(req,timeout=35)
def settings(url):
 u=urllib.parse.urlsplit(url);base=f'{u.scheme}://{u.netloc}'+u.path.rsplit('/',1)[0]+'/'
 page=fetch(base+'game.html').read().decode('utf8')
 version=re.search(r'flashvars.version\s*=\s*["\']([^"\']+)',page).group(1)
 res=re.search(r'var resVersion\s*=\s*["\']([^"\']+)',page).group(1)
 movie=re.search(r'/((?:Loading)[^"\']+\.swf)',page).group(1)
 xml=fetch(base+'resource/cfg/server.xml').read().decode('utf8')
 import xml.etree.ElementTree as ET
 sockets=set()
 for e in ET.fromstring(xml).iter():
  a=e.attrib
  for hk,pk in [('Ip','Port'),('gameIp','gamePort'),('chatIp','chatPort'),('gameIp','chatPort')]:
   if a.get(hk) and a.get(pk) and allowed(a[hk]):sockets.add((a[hk],int(a[pk])))
 params=dict(urllib.parse.parse_qsl(u.query));params.update(version=version,resVersion=res)
 return dict(base=base,movie=base+res+'/'+movie,parameters=params,query=u.query,sockets=sorted(sockets))
class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def handle(self):
  try:super().handle()
  except (ConnectionResetError,BrokenPipeError):pass
 def response(self,status,body,ctype='application/json'):
  if isinstance(body,str):body=body.encode()
  self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length',0))
   if n>16*1024*1024:
    self.close_connection=True
    return self.response(413,'Too large')
   body=self.rfile.read(n)
   if self.path.startswith('/report/'):
    return self.get(body)
   if self.path.startswith('/proxy/'):
    return self.get(body)
   if self.path!='/session' or self.headers.get('Authorization')!='Bearer '+KEY:return self.response(403,'Denied')
   n=int(self.headers.get('Content-Length',0))
   if n>16384:return self.response(413,'Too large')
   url=json.loads(body)['url'];u=urllib.parse.urlsplit(url)
   if u.hostname!='sjsj-client.wanwan4399.com' or u.path not in ('/www_sjsj/game.html','/www_sjsj_s2/game.html'):return self.response(400,'Invalid official game URL')
   s=settings(url);sid=secrets.token_urlsafe(24);SESSIONS[sid]=s
   event('session_created',socket_endpoints=len(s['sockets']))
   self.response(200,json.dumps({'path':'/app/'+sid}))
  except Exception as e:event('session_error',error=type(e).__name__);self.response(502,type(e).__name__)
 def do_GET(self):
  try:self.get()
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception as e:
   event('bridge_error',error=type(e).__name__)
   try:self.response(502,type(e).__name__)
   except:pass
 def get(self,data=None):
  u=urllib.parse.urlsplit(self.path);parts=u.path.split('/')
  if u.path=='/health':return self.response(200,'{"ready":true}')
  if u.path=='/freeze-diagnostics.js' and DIAGNOSTICS is not None:
   return self.response(200, (ROOT/'freeze_diagnostics.js').read_bytes(), 'application/javascript')
  if u.path=='/diagnostics/frames' and DIAGNOSTICS is not None:
   if self.headers.get('Authorization')!='Bearer '+KEY:return self.response(403,'Denied')
   return self.response(200,json.dumps({
    'reclaim': DIAGNOSTIC_MODE,
    'heartbeats': DIAGNOSTICS.recent(STARTED),
    'last_snapshot': DIAGNOSTICS.last_snapshot,
   },ensure_ascii=False))
  if u.path in ('/diagnostics','/diagnostics/patches','/diagnostics/critical','/diagnostics/memory'):
   if self.headers.get('Authorization')!='Bearer '+KEY:return self.response(403,'Denied')
   if u.path.endswith('/patches'):
    return self.response(200,json.dumps({'mode':'original','loaded':0,'applied':0,'misses':[]}))
   with LOCK:
    if u.path.endswith('/memory'):
     rows = list(MEMORY_SAMPLES)
    else:
     rows = list(CRITICAL_EVENTS if u.path.endswith('/critical') else EVENTS)
   return self.response(200,json.dumps(rows,ensure_ascii=False))
  if len(parts)>2 and parts[1] in ('app','frame','socket','proxy','config','report'):
   sid=parts[2];s=SESSIONS.get(sid)
   if not s:return self.response(404,'Session not found')
   route=parts[1]
   if route=='app':
    return self.response(200,'<!doctype html><meta charset=utf-8><title>神将世界 · 原生验证</title><style>html,body,iframe{margin:0;width:100%;height:100%;border:0;background:#000}</style><iframe src="/frame/'+sid+'?'+s['query'].replace('&','&amp;').replace('"','&quot;')+'"></iframe>','text/html; charset=utf-8')
   if route=='config':
    out={k:v for k,v in s.items() if k!='query'};return self.response(200,json.dumps(out))
   if route=='frame':
    page = (ROOT/'player.html').read_bytes()
    if DIAGNOSTICS is not None:
     script = f'<script src="/freeze-diagnostics.js" data-reclaim="{DIAGNOSTIC_MODE}"></script>'
     page = page.replace(b'<script>',script.encode()+b'<script>',1)
    return self.response(200,page,'text/html; charset=utf-8')
   if route=='report':
    message=data.decode('utf8','replace') if data is not None else urllib.parse.parse_qs(u.query).get('message',[''])[0]
    if DIAGNOSTICS is not None and data is not None and message.startswith('bitmap-classes '):
     if len(data)>24_000:return self.response(413,'Too large')
     try:
      sample = json.loads(message[len('bitmap-classes '):])
      tracked, classes = sample['tracked_bytes'], sample['classes']
      packing = {key: sample[key] for key in ('packed_bytes', 'packed_buffers', 'packed_restores')
                 if key in sample}
      if any(type(value) is not int or not 0 <= value <= 2**32 for value in packing.values()):
       raise ValueError
      if (type(tracked) is not int or not 0 <= tracked <= 2**32
          or not isinstance(classes, list) or len(classes) > 24
          or any(not isinstance(row, list) or len(row) != 2
                 or not isinstance(row[0], str) or len(row[0]) > 120
                 or type(row[1]) is not int or not 0 <= row[1] <= tracked for row in classes)):
       raise ValueError
     except (ValueError, KeyError, TypeError):
      return self.response(400,'Invalid bitmap classes')
     with LOCK:
      BITMAP_CLASS_SAMPLES.append({'elapsed_seconds': round(time.monotonic()-STARTED,3),
                                   'tracked_bytes': tracked, 'classes': classes, **packing})
     return self.response(200,'{}')
    if DIAGNOSTICS is not None and data is not None and message.startswith('frame-diag '):
     if len(data)>2048:return self.response(413,'Too large')
     try: sample = json.loads(message[11:])
     except ValueError:return self.response(400,'Invalid heartbeat')
     return self.response(200,'{}') if DIAGNOSTICS.add(sid,sample) else self.response(400,'Invalid heartbeat')
    if sample := re.fullmatch(r'wasm-memory ([0-9]{1,10})', message):
     with LOCK:
      MEMORY_SAMPLES.append({
       'elapsed_seconds': round(time.monotonic() - STARTED, 3),
       'wasm_bytes': int(sample[1]),
      })
     return self.response(200, '{}')
    message=re.sub(r'https?://[^\s"\']+',lambda m:m[0].split('?')[0],message)
    message=re.sub(r'HttpNotOk\(.*', 'HttpNotOk [response details omitted]', message)
    if 'onURLLoaderErrorEvent' in message and not message.startswith('critical:'):return self.response(200,'{}')
    event('player',message=message[:24000])
    if DIAGNOSTICS is not None and message.startswith('critical:') and message!='critical: Unable to lock Ruffle core':
     DIAGNOSTICS.mark_fatal(sid)
    return self.response(200,'{}')
   if route=='socket':
    q=urllib.parse.parse_qs(u.query);host=q.get('host',[''])[0];port=int(q.get('port',['0'])[0])
    if (host,port) not in map(tuple,s['sockets']):return self.response(403,'Endpoint not permitted')
    origin=self.headers.get('Origin','')
    if origin!=f'http://127.0.0.1:{self.server.server_port}':return self.response(403,'Origin not permitted')
    return self.websocket(host,port)
   if route=='proxy':
    if len(parts)<6:return self.response(400,'Bad proxy URL')
    scheme,host=parts[3:5]
    if host=='api.catearsgame.com' and parts[5:]==['game','chat','response']:
     event('chat_review_blocked',scheme=scheme)
    if scheme not in ('http','https') or not allowed(host) or ':' in host:return self.response(403,'Host not permitted')
    remote_path = '/'+'/'.join(parts[5:])
    remote=scheme+'://'+host+remote_path+('?' + u.query if u.query else '')
    public_asset = (data is None and host == 'sjsj-client.wanwan4399.com' and (
                    (DYNAMIC_ASSET.fullmatch(remote_path)
                     and (not u.query or re.fullmatch(r'v=[A-Za-z0-9._-]{1,64}', u.query)))
                    or (not u.query and VERSIONED_STATIC_ASSET.fullmatch(remote_path))))
    if data is None and (cached := cached_resource(remote)) is not None:
     return self.response(200,*cached)
    asset = dynamic_disk_resource(remote) if public_asset else None
    validators = {}
    if asset is not None:
     if asset.expires > time.time():
      with LOCK:
       RESOURCE_METRICS['disk_hits'] += 1
       RESOURCE_METRICS['disk_hit_bytes'] += len(asset.body)
      return self.response(200, asset.body, asset.content_type)
     if asset.etag:
      validators['If-None-Match'] = asset.etag
     elif asset.last_modified:
      validators['If-Modified-Since'] = asset.last_modified
    try:
     started = time.monotonic()
     method = 'POST' if data is not None else None
     try:
      response = fetch(remote, data=data, method=method, extra_headers=validators)
     except urllib.error.HTTPError as error:
      if error.code != 304 or not validators or error.geturl() != remote:
       raise
      with error:
       ttl = dynamic_asset_ttl(error.headers, asset.lifetime)
       if ttl is not None:
        if ttl:
         dynamic_disk_resource(remote, (ttl, error.headers.get('ETag', asset.etag),
                               error.headers.get('Last-Modified', asset.last_modified)), previous=asset)
        else:
         dynamic_disk_resource(remote, previous=asset)
        with LOCK:
         RESOURCE_METRICS['upstream_gets'] += 1
         RESOURCE_METRICS['upstream_get_ms'] += round((time.monotonic() - started) * 1000)
         RESOURCE_METRICS['disk_revalidations'] += 1
         RESOURCE_METRICS['disk_revalidated_bytes'] += len(asset.body)
        return self.response(200, asset.body, asset.content_type)
      # A private or varying response invalidates our public cached copy.
      dynamic_disk_resource(remote, previous=asset)
      asset = None
      response = fetch(remote, data=data, method=method)
     with response as r:
      body=r.read()
      ct=r.headers.get('Content-Type','application/octet-stream')
      ttl = None
      if public_asset and getattr(r, 'status', None) == 200 and r.geturl() == remote:
       ttl = dynamic_asset_ttl(r.headers)
      etag, last_modified = r.headers.get('ETag'), r.headers.get('Last-Modified')
     if data is None:
      with LOCK:
       RESOURCE_METRICS['upstream_gets'] += 1
       RESOURCE_METRICS['upstream_get_bytes'] += len(body)
       RESOURCE_METRICS['upstream_get_ms'] += round((time.monotonic() - started) * 1000)
      if public_asset:
       if ttl and len(body) < 4_000_000:
        dynamic_disk_resource(remote, (body, ct, ttl, etag, last_modified))
       elif asset is not None:
        dynamic_disk_resource(remote, previous=asset)
      elif len(body) < 4_000_000 and u.path.endswith(('.swf','.xml')):
       cache_resource(remote, body, ct)
     event('resource_ok',host=host,path=urllib.parse.urlsplit(remote).path,bytes=len(body))
     return self.response(200,body,ct)
    except urllib.error.HTTPError as e:
     event('resource_failed',host=host,path=urllib.parse.urlsplit(remote).path,status=e.code)
     return self.response(e.code,e.read(),e.headers.get('Content-Type','text/plain'))
  if parts[1]=='runtime':
   rel='/'.join(parts[2:]);p=(ROOT/'web-runtime'/rel).resolve();base=(ROOT/'web-runtime').resolve()
   if base not in p.parents or not p.is_file():return self.response(404,'Not found')
   # Python's system MIME lookup can try to read files outside the app sandbox.
   ct=RUNTIME_CONTENT_TYPES.get(p.suffix, 'application/octet-stream')
   return self.response(200,p.read_bytes(),ct)
  return self.response(404,'Not found')
 def websocket(self,host,port):
  if self.headers.get('Upgrade','').lower()!='websocket':return self.response(400,'WebSocket required')
  try:remote=socket.create_connection((host,port),timeout=12)
  except OSError as e:event('socket_failed',host=host,port=port,error=type(e).__name__);return self.response(502,'Game server unavailable')
  remote.settimeout(None)
  key=self.headers.get('Sec-WebSocket-Key','');accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
  self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade');self.send_header('Sec-WebSocket-Accept',accept)
  if 'binary' in self.headers.get('Sec-WebSocket-Protocol','').split(','):self.send_header('Sec-WebSocket-Protocol','binary')
  self.end_headers();event('socket_connected',host=host,port=port)
  send_lock=threading.Lock()
  def send(data,opcode=2):
   n=len(data);h=bytes([128|opcode,n]) if n<126 else bytes([128|opcode,126])+struct.pack('!H',n) if n<65536 else bytes([128|opcode,127])+struct.pack('!Q',n)
   with send_lock:self.connection.sendall(h+data)
  def exact(n):
   d=b''
   while len(d)<n:
    c=self.rfile.read(n-len(d))
    if not c:raise EOFError()
    d+=c
   return d
  stopped=threading.Event()
  def incoming():
   received=0
   try:
    while not stopped.is_set():
     d=remote.recv(65536)
     if not d:break
     received+=1
     write_event('socket_activity',dict(direction='in',host=host,port=port,bytes=len(d)))
     if received<=5:event('socket_received',host=host,port=port,bytes=len(d),frame=received)
     send(d)
   except OSError:pass
   finally:
    stopped.set()
    try:self.connection.shutdown(socket.SHUT_RDWR)
    except OSError:pass
  t=threading.Thread(target=incoming,daemon=True);t.start()
  sent=0
  try:
   while not stopped.is_set():
    a,b=exact(2);op=a&15;n=b&127
    if n==126:n=struct.unpack('!H',exact(2))[0]
    elif n==127:n=struct.unpack('!Q',exact(8))[0]
    if n>8*1024*1024:break
    mask=exact(4) if b&128 else b'';d=exact(n)
    if mask:d=bytes(v^mask[i%4] for i,v in enumerate(d))
    if op==8:break
    if op==9:send(d,10)
    elif op in (0,1,2):
     sent+=1
     if sent<=5:event('socket_sent',host=host,port=port,bytes=len(d),frame=sent)
     remote.sendall(d)
     write_event('socket_activity',dict(direction='out',host=host,port=port,bytes=len(d)))
  except (OSError,EOFError):pass
  finally:stopped.set();remote.close();self.close_connection=True;event('socket_closed',host=host,port=port)
if __name__=='__main__':
 parent=int(os.environ.get('SJSJ_PARENT_PID','0'))
 if parent:
  def watch_parent():
   while True:
    time.sleep(2)
    try:os.kill(parent,0)
    except ProcessLookupError:os._exit(0)
  threading.Thread(target=watch_parent,daemon=True).start()
 try:server=ThreadingHTTPServer(('127.0.0.1',19140),Handler)
 except OSError:
  print(json.dumps({'kind':'startup_error'}),flush=True);raise SystemExit(1)
 start_metrics(lambda:dict(cache_entries=len(CACHE),cache_bytes=sum(len(v[0]) for v in list(CACHE.values())),sessions=len(SESSIONS),threads=threading.active_count()))
 if DIAGNOSTICS is not None:
  def freeze_context():
   with LOCK:
    memory = list(MEMORY_SAMPLES)
    critical = [{
     'elapsed_seconds': row['elapsed_seconds'],
     'kind': 'oom' if 'rust_oom' in row['message'] else 'validation' if 'validation' in row['message'].lower() else 'runtime',
     'markers': re.findall(r'wgpu Validation Error|Dimension [XYZ] is zero|WebGL context lost|rust_oom|RuntimeError',
                           row['message'], flags=re.IGNORECASE)[:12],
     'stack': [line for line in row['message'].splitlines()
               if '@ruffle_web.wasm:wasm-function[' in line][:96],
    } for row in CRITICAL_EVENTS]
    cached = list(CACHE.values())
    resource_metrics = dict(RESOURCE_METRICS)
    bitmap_classes = list(BITMAP_CLASS_SAMPLES)
   return {'wasm_capacity': memory, 'critical': critical,
           'bridge_cache_entries': len(cached), 'bridge_cache_bytes': sum(len(v[0]) for v in cached),
           'resource_metrics': resource_metrics, 'bitmap_classes': bitmap_classes}
  threading.Thread(target=DIAGNOSTICS.watch,
                   args=(parent or os.getppid(),DIAGNOSTIC_MODE,STARTED,freeze_context),
                   daemon=True).start()
 server.daemon_threads=True
 print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()

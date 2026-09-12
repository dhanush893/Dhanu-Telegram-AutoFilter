import asyncio, os, re, sqlite3
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telegram import Update
from telegram.ext import Application, CommandHandler

load_dotenv()
API_ID=int(os.environ['API_ID']); API_HASH=os.environ['API_HASH']
BOT_TOKEN=os.environ['BOT_TOKEN']; OWNER_USER_ID=int(os.environ['OWNER_USER_ID'])
SOURCE_CHAT=os.environ['SOURCE_CHAT']; DESTINATION_CHAT=os.environ['DESTINATION_CHAT']
SESSION_NAME=os.getenv('SESSION_NAME','user'); DB_PATH=os.getenv('DATABASE_PATH','bot.db')
DOWNLOAD_DIR=Path(os.getenv('DOWNLOAD_DIR','media_tmp')); DOWNLOAD_DIR.mkdir(exist_ok=True)

db=sqlite3.connect(DB_PATH,check_same_thread=False)
db.execute('''CREATE TABLE IF NOT EXISTS processed(source_chat TEXT, source_msg_id INTEGER, fingerprint TEXT, destination_msg_id INTEGER, status TEXT, PRIMARY KEY(source_chat,source_msg_id))''')
db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS filters(keyword TEXT PRIMARY KEY)'); db.commit()

def setting(k,d=''):
    r=db.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone(); return r[0] if r else d

def set_setting(k,v): db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v)); db.commit()
def get_filters(): return [r[0] for r in db.execute('SELECT keyword FROM filters')]
def done(mid): return db.execute('SELECT 1 FROM processed WHERE source_chat=? AND source_msg_id=?',(str(SOURCE_CHAT),mid)).fetchone()
def mark(mid,fp,did,status='sent'):
    db.execute('INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)',(str(SOURCE_CHAT),mid,fp,did,status)); db.commit()

def fingerprint(msg):
    name=''; size=''; doc=getattr(getattr(msg,'media',None),'document',None)
    if doc:
        size=str(getattr(doc,'size',''))
        for a in getattr(doc,'attributes',[]):
            if getattr(a,'file_name',None): name=a.file_name; break
    return f'{name}|{size}|{(msg.raw_text or "").strip().lower()}'

def parse(name):
    stem=Path(name).stem; ext=Path(name).suffix or '.mkv'
    m=re.search(r'\b(?:19|20)\d{2}\b',stem); year=m.group(0) if m else ''
    lang=next((x for x in ['Tamil','Telugu','Hindi','Malayalam','Kannada','English'] if re.search(rf'\b{x}\b',stem,re.I)),'')
    quality=next((x for x in ['2160p','1080p','720p','480p','HDRip','WEB-DL','WEBRip','BluRay','TSRip'] if re.search(rf'\b{re.escape(x)}\b',stem,re.I)),'')
    vc=next((x for x in ['x265','x264','HEVC','AV1'] if re.search(rf'\b{re.escape(x)}\b',stem,re.I)),'')
    ac=next((x for x in ['AAC','AC3','DDP','EAC3','MP3'] if re.search(rf'\b{re.escape(x)}\b',stem,re.I)),'')
    sub='ESub' if re.search(r'\bESub\b',stem,re.I) else ''
    title=stem
    for t in ['Tamil','Telugu','Hindi','Malayalam','Kannada','English','2160p','1080p','720p','480p','HDRip','WEB-DL','WEBRip','BluRay','TSRip','x265','x264','HEVC','AV1','AAC','AC3','DDP','EAC3','MP3','HC','ESub']:
        title=re.sub(rf'\b{re.escape(t)}\b','',title,flags=re.I)
    title=re.sub(r'\b(?:19|20)\d{2}\b','',title); title=re.sub(r'[\[\]\(\)_\-.]+',' ',title); title=re.sub(r'\s+',' ',title).strip()
    return dict(title=title,year=year,language=lang,quality=quality,video_codec=vc,audio_codec=ac,subtitle=sub,ext=ext)

def make_caption(name,size_mb):
    p=parse(name); template=setting('template','{prefix} - {title} ({year}) {language} {quality} - {video_codec} - {audio_codec} - {size} - {subtitle}.{brand}{ext}')
    vals={**p,'prefix':setting('prefix','@SD_MOVIE_ADDA'),'brand':setting('brand','_Ɗʜa֟፝nᴜ ⸙_'),'size':f'{size_mb:.0f}MB'}
    out=template.format(**vals); out=re.sub(r'\(\s*\)','',out); out=re.sub(r'\s+-\s+-',' -',out); return re.sub(r'\s{2,}',' ',out).strip()

client=TelegramClient(SESSION_NAME,API_ID,API_HASH); paused=False

async def process(msg):
    global paused
    if paused or done(msg.id): return
    text=(msg.raw_text or '').lower(); fs=get_filters()
    if fs and not all(k.lower() in text for k in fs): mark(msg.id,fingerprint(msg),None,'filtered'); return
    fprint=fingerprint(msg)
    if db.execute("SELECT 1 FROM processed WHERE fingerprint=? AND status='sent'",(fprint,)).fetchone(): mark(msg.id,fprint,None,'duplicate'); return
    if not msg.media:
        sent=await client.send_message(DESTINATION_CHAT,msg.raw_text or ''); mark(msg.id,fprint,sent.id); return
    path=await client.download_media(msg,file=str(DOWNLOAD_DIR))
    if not path: mark(msg.id,fprint,None,'download_failed'); return
    path=Path(path); original=path.name; doc=getattr(getattr(msg,'media',None),'document',None)
    if doc:
        for a in getattr(doc,'attributes',[]):
            if getattr(a,'file_name',None): original=a.file_name; break
    size=path.stat().st_size/(1024*1024); cap=make_caption(original,size)
    target=path.with_name(re.sub(r'[\\/:*?"<>|]','_',cap))
    try: path.rename(target); path=target
    except OSError: pass
    try:
        sent=await client.send_file(DESTINATION_CHAT,str(path),caption=cap[:4096],force_document=True,supports_streaming=True)
        mark(msg.id,fprint,sent.id)
    finally:
        try: path.unlink()
        except OSError: pass

async def historical_scan(limit):
    n=0
    async for msg in client.iter_messages(SOURCE_CHAT,limit=limit):
        try: await process(msg); n+=1
        except FloodWaitError as e: await asyncio.sleep(e.seconds)
        except Exception as e: print('scan error',msg.id,e)
    return n

async def live(event):
    try: await process(event.message)
    except FloodWaitError as e: await asyncio.sleep(e.seconds)
    except Exception as e: print('live error',e)

def owner(fn):
    async def wrapper(update,context):
        if update.effective_user and update.effective_user.id==OWNER_USER_ID: return await fn(update,context)
    return wrapper

@owner
async def start(u,c): await u.message.reply_text('Dhanu Auto Filter V1 online.\n/status /filters /scan /pause /resume /settings')
@owner
async def status(u,c):
    total=db.execute('SELECT COUNT(*) FROM processed').fetchone()[0]
    def q(s): return db.execute('SELECT COUNT(*) FROM processed WHERE status=?',(s,)).fetchone()[0]
    await u.message.reply_text(f"{'PAUSED' if paused else 'RUNNING'}\nProcessed: {total}\nSent: {q('sent')}\nDuplicate: {q('duplicate')}\nFiltered: {q('filtered')}")
@owner
async def addfilter(u,c):
    k=' '.join(c.args).strip()
    if not k: return await u.message.reply_text('Usage: /addfilter keyword')
    db.execute('INSERT OR IGNORE INTO filters VALUES(?)',(k,)); db.commit(); await u.message.reply_text('Filter added: '+k)
@owner
async def removefilter(u,c):
    k=' '.join(c.args).strip(); db.execute('DELETE FROM filters WHERE keyword=?',(k,)); db.commit(); await u.message.reply_text('Filter removed.')
@owner
async def filters_cmd(u,c): await u.message.reply_text('\n'.join(get_filters()) or 'No filters.')
@owner
async def prefix(u,c): set_setting('prefix',' '.join(c.args).strip()); await u.message.reply_text('Prefix updated.')
@owner
async def brand(u,c): set_setting('brand',' '.join(c.args).strip()); await u.message.reply_text('Brand updated.')
@owner
async def template(u,c): set_setting('template',' '.join(c.args).strip()); await u.message.reply_text('Template updated.')
@owner
async def scan_cmd(u,c):
    n=await historical_scan(int(c.args[0]) if c.args else int(os.getenv('MAX_HISTORY_SCAN','100'))); await u.message.reply_text(f'Checked {n} posts.')
@owner
async def pause(u,c):
    global paused; paused=True; await u.message.reply_text('Paused.')
@owner
async def resume(u,c):
    global paused; paused=False; await u.message.reply_text('Resumed.')
@owner
async def settings_cmd(u,c): await u.message.reply_text(f'Source: {SOURCE_CHAT}\nDestination: {DESTINATION_CHAT}\nPrefix: {setting("prefix","@SD_MOVIE_ADDA")}\nBrand: {setting("brand","_Ɗʜa֟፝nᴜ ⸙_")}')

async def main():
    await client.start(); client.add_event_handler(live,events.NewMessage(chats=SOURCE_CHAT))
    app=Application.builder().token(BOT_TOKEN).build()
    handlers={'start':start,'status':status,'addfilter':addfilter,'removefilter':removefilter,'filters':filters_cmd,'setprefix':prefix,'setbrand':brand,'settemplate':template,'scan':scan_cmd,'pause':pause,'resume':resume,'settings':settings_cmd}
    for cmd,fn in handlers.items(): app.add_handler(CommandHandler(cmd,fn))
    await app.initialize(); await app.start(); await app.updater.start_polling(); print('Running.'); await asyncio.Event().wait()

if __name__=='__main__': asyncio.run(main())

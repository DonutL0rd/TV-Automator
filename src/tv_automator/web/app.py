"""FastAPI web dashboard for TV-Automator."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from tv_automator.automator.browser_control import BrowserController
from tv_automator.config import Config
from tv_automator.providers.base import Game
from tv_automator.providers.mlb import MLBProvider
from tv_automator.providers.mlb_session import MLBSession
from tv_automator.scheduler.game_scheduler import GameScheduler

log = logging.getLogger(__name__)

# ── App state ────────────────────────────────────────────────────

_config: Config
_browser: BrowserController
_mlb: MLBProvider
_session: MLBSession
_scheduler: GameScheduler
_now_playing_game_id: str | None = None
_current_stream_url: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _browser, _mlb, _session, _scheduler
    _config = Config()
    _browser = BrowserController(_config)
    _mlb = MLBProvider()
    _session = MLBSession()
    _scheduler = GameScheduler(_config)
    _scheduler.register_provider(_mlb)

    try:
        await _browser.start()
        log.info("Browser started")
    except Exception:
        log.exception("Browser failed to start — check DISPLAY / X11")

    # Auto-login via API if credentials are configured
    creds = _config.mlb_credentials
    if creds:
        username, password = creds
        log.info("MLB credentials found — logging in via API...")
        ok = await _session.login(username, password)
        if ok:
            log.info("MLB.TV login successful")
        else:
            log.error("MLB.TV login failed — check MLB_USERNAME / MLB_PASSWORD")
    else:
        log.warning("No MLB credentials configured — set MLB_USERNAME and MLB_PASSWORD in .env")

    await _scheduler.start()

    yield

    await _scheduler.stop()
    await _session.close()
    await _browser.stop()


app = FastAPI(lifespan=lifespan)


# ── Helpers ──────────────────────────────────────────────────────

def _game_to_dict(game: Game) -> dict:
    return {
        "game_id": game.game_id,
        "provider": game.provider,
        "away_team": {
            "name": game.away_team.name,
            "abbreviation": game.away_team.abbreviation,
            "score": game.away_team.score,
        },
        "home_team": {
            "name": game.home_team.name,
            "abbreviation": game.home_team.abbreviation,
            "score": game.home_team.score,
        },
        "start_time": game.start_time.isoformat(),
        "display_time": game.display_time,
        "display_matchup": game.display_matchup,
        "display_score": game.display_score,
        "status": game.status.value,
        "status_label": game.status.display_label,
        "is_watchable": game.status.is_watchable,
        "venue": game.venue,
        "extra": game.extra,
    }


# ── Routes ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _DASHBOARD_HTML


@app.get("/api/games")
async def get_games(date: str | None = None):
    target = datetime.fromisoformat(date) if date else datetime.now()
    games = await _mlb.get_schedule(target)
    return [_game_to_dict(g) for g in games]


@app.post("/api/play/{game_id}")
async def play_game(game_id: str, date: str | None = None, feed: str = "HOME"):
    global _now_playing_game_id, _current_stream_url

    if not _browser.is_running:
        raise HTTPException(503, "Browser not running — check DISPLAY / X11")
    if not _session.is_authenticated:
        if not await _session.ensure_authenticated():
            raise HTTPException(401, "Not authenticated — check MLB_USERNAME / MLB_PASSWORD in .env")

    stream_url = await _session.get_stream_url(game_id, feed_type=feed.upper())
    if not stream_url:
        raise HTTPException(502, "Could not get stream URL — game may not be available yet")

    _current_stream_url = stream_url
    _now_playing_game_id = game_id

    # Navigate Chrome to the local HLS player
    ok = await _browser.navigate("http://127.0.0.1:5000/player")
    return {"success": ok, "feed": feed.upper()}


@app.post("/api/stop")
async def stop_playback():
    global _now_playing_game_id, _current_stream_url
    await _browser.stop_playback()
    _now_playing_game_id = None
    _current_stream_url = None
    return {"success": True}


@app.get("/api/status")
async def get_status():
    return {
        "now_playing_game_id": _now_playing_game_id,
        "authenticated": _session.is_authenticated,
        "browser_running": _browser.is_running,
    }


@app.get("/api/stream")
async def get_stream():
    """Returns the current stream URL — called by the player page."""
    if not _current_stream_url:
        raise HTTPException(404, "No stream active")
    return {"url": _current_stream_url}


@app.get("/player", response_class=HTMLResponse)
async def player_page():
    return _PLAYER_HTML


# ── Player HTML ──────────────────────────────────────────────────

_PLAYER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>TV Automator Player</title>
<style>
  * { margin: 0; padding: 0; }
  body { background: #000; overflow: hidden; }
  video { width: 100vw; height: 100vh; object-fit: contain; }
  #error { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
           color: #ef4444; font-family: sans-serif; font-size: 1.1rem;
           background: rgba(0,0,0,0.8); padding: 10px 20px; border-radius: 8px;
           display: none; }
</style>
</head>
<body>
<video id="video" autoplay></video>
<div id="error"></div>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
(async function() {
  const errEl = document.getElementById('error');
  try {
    const res = await fetch('/api/stream');
    if (!res.ok) throw new Error('No stream available');
    const { url } = await res.json();
    const video = document.getElementById('video');

    if (Hls.isSupported()) {
      const hls = new Hls({ maxBufferLength: 30, maxMaxBufferLength: 60 });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) {
          errEl.textContent = 'Stream error: ' + data.type;
          errEl.style.display = '';
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
          else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
      video.play();
    } else {
      errEl.textContent = 'HLS not supported in this browser';
      errEl.style.display = '';
    }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = '';
  }
})();
</script>
</body>
</html>
"""

# ── Dashboard HTML ───────────────────────────────────────────────

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TV Automator</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: #0f1117;
      --surface: #1a1d2e;
      --card: #1e2235;
      --border: #2d3148;
      --text: #e8eaf6;
      --muted: #8b92b3;
      --accent: #4f7dff;
      --green: #22c55e;
      --red: #ef4444;
      --yellow: #f59e0b;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }

    header {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }

    header h1 { font-size: 1.3rem; font-weight: 700; white-space: nowrap; }

    #now-playing-bar {
      flex: 1; font-size: 0.88rem; color: var(--green);
      font-weight: 600; display: none;
    }

    .controls {
      display: flex; align-items: center; gap: 10px;
      margin-left: auto; flex-wrap: wrap;
    }

    .date-nav { display: flex; align-items: center; gap: 8px; }
    .date-nav span { min-width: 220px; text-align: center; font-size: 0.9rem; font-weight: 600; }

    button {
      background: var(--card); border: 1px solid var(--border); color: var(--text);
      padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.82rem;
      line-height: 1.4; transition: background 0.12s;
    }
    button:hover { background: var(--border); }

    .btn-stop { background: var(--red); border-color: #c53030; color: #fff; }
    .btn-stop:hover { background: #c53030; }

    .btn-feed {
      padding: 6px 12px; font-size: 0.78rem; font-weight: 600;
      border-radius: 5px; cursor: pointer; transition: background 0.12s;
    }
    .btn-home { background: var(--accent); border-color: var(--accent); color: #fff; }
    .btn-home:hover { background: #3b6ae8; }
    .btn-away { background: var(--card); border-color: var(--border); color: var(--text); }
    .btn-away:hover { background: var(--border); }
    .btn-feed:disabled { background: var(--border); border-color: var(--border); color: var(--muted); cursor: default; }

    .auth-badge {
      font-size: 0.78rem; font-weight: 600; padding: 3px 10px;
      border-radius: 20px; white-space: nowrap;
    }
    .auth-ok  { background: rgba(34,197,94,0.15); color: var(--green); border: 1px solid rgba(34,197,94,0.3); }
    .auth-no  { background: rgba(239,68,68,0.12); color: var(--red);   border: 1px solid rgba(239,68,68,0.25); }

    main { padding: 24px; max-width: 1280px; margin: 0 auto; }

    #status-msg {
      text-align: center; color: var(--muted); padding: 60px 24px; font-size: 1rem;
    }

    #game-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px;
    }

    .game-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 18px 18px 14px; display: flex; flex-direction: column; gap: 10px;
      position: relative; transition: border-color 0.15s;
    }
    .game-card.live { border-color: var(--green); }
    .game-card.playing { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }

    .status-badge {
      position: absolute; top: 12px; right: 12px; padding: 2px 9px; border-radius: 20px;
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
    }
    .badge-live     { background: var(--green); color: #000; }
    .badge-pre_game { background: var(--yellow); color: #000; }
    .badge-scheduled { background: var(--border); color: var(--muted); }
    .badge-final    { background: transparent; color: var(--muted); border: 1px solid var(--border); }
    .badge-postponed, .badge-cancelled { background: var(--red); color: #fff; }
    .badge-unknown  { background: var(--border); color: var(--muted); }

    .matchup {
      display: flex; justify-content: space-between; align-items: center;
      padding: 6px 0 4px; gap: 8px;
    }
    .team { flex: 1; text-align: center; }
    .team-abbr { font-size: 1.9rem; font-weight: 800; line-height: 1; }
    .team-name {
      font-size: 0.68rem; color: var(--muted); margin-top: 3px;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }

    .middle-col { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 60px; }
    .score-row { display: flex; align-items: center; gap: 10px; }
    .score-val { font-size: 1.8rem; font-weight: 800; line-height: 1; }
    .score-sep { color: var(--muted); font-size: 1rem; }
    .at-sign { color: var(--muted); font-size: 0.85rem; font-weight: 600; }
    .inning-label { font-size: 0.75rem; color: var(--green); font-weight: 600; white-space: nowrap; }

    .pitchers {
      font-size: 0.72rem; color: var(--muted);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }

    .card-footer { display: flex; justify-content: space-between; align-items: center; padding-top: 4px; }
    .game-time { font-size: 0.82rem; color: var(--muted); }
    .feed-btns { display: flex; gap: 6px; }
    .now-playing-tag { font-size: 0.8rem; color: var(--accent); font-weight: 600; }
  </style>
</head>
<body>
<header>
  <h1>TV Automator</h1>
  <div id="now-playing-bar">&#9654; Now playing: <span id="np-name"></span></div>
  <div class="controls">
    <span id="auth-badge" class="auth-badge"></span>
    <div class="date-nav">
      <button onclick="changeDate(-1)">&#9664;</button>
      <span id="date-label"></span>
      <button onclick="changeDate(1)">&#9654;</button>
    </div>
    <button id="today-btn" onclick="goToToday()" style="display:none">Today</button>
    <button id="stop-btn" class="btn-stop" onclick="stopPlayback()" style="display:none">&#9632; Stop</button>
    <button onclick="loadGames()">&#8635; Refresh</button>
  </div>
</header>
<main>
  <div id="status-msg">Loading...</div>
  <div id="game-grid"></div>
</main>
<script>
  let currentDate = new Date();
  currentDate.setHours(0, 0, 0, 0);
  let nowPlayingId = null;
  let refreshTimer = null;

  function pad(n) { return String(n).padStart(2, '0'); }
  function dateStr(d) { return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()); }

  function formatDateLabel(d) {
    const today = new Date(); today.setHours(0,0,0,0);
    const y = new Date(today); y.setDate(today.getDate()-1);
    const t = new Date(today); t.setDate(today.getDate()+1);
    let label;
    if (d.getTime()===today.getTime()) label='Today';
    else if (d.getTime()===y.getTime()) label='Yesterday';
    else if (d.getTime()===t.getTime()) label='Tomorrow';
    else label=d.toLocaleDateString('en-US',{weekday:'long'});
    return label+' \\u2014 '+d.toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'});
  }

  function changeDate(delta) { currentDate.setDate(currentDate.getDate()+delta); updateDateLabel(); loadGames(); }
  function goToToday() { currentDate=new Date(); currentDate.setHours(0,0,0,0); updateDateLabel(); loadGames(); }
  function updateDateLabel() {
    document.getElementById('date-label').textContent=formatDateLabel(currentDate);
    const today=new Date(); today.setHours(0,0,0,0);
    document.getElementById('today-btn').style.display=currentDate.getTime()===today.getTime()?'none':'';
  }

  async function loadGames() {
    clearTimeout(refreshTimer);
    document.getElementById('game-grid').innerHTML='';
    document.getElementById('status-msg').textContent='Loading...';
    document.getElementById('status-msg').style.display='';
    try {
      const [gRes,sRes]=await Promise.all([fetch('/api/games?date='+dateStr(currentDate)),fetch('/api/status')]);
      const games=await gRes.json(), status=await sRes.json();
      nowPlayingId=status.now_playing_game_id;
      updateStatus(games,status);
      if(!games.length){document.getElementById('status-msg').textContent='No games scheduled.';}
      else{document.getElementById('status-msg').style.display='none';renderGames(games);}
    } catch(e){document.getElementById('status-msg').textContent='Error: '+e.message;}
    refreshTimer=setTimeout(loadGames,30000);
  }

  function updateStatus(games,status) {
    const bar=document.getElementById('now-playing-bar'),stopBtn=document.getElementById('stop-btn');
    if(nowPlayingId){
      const g=games.find(x=>x.game_id===nowPlayingId);
      document.getElementById('np-name').textContent=g?g.display_matchup:nowPlayingId;
      bar.style.display='';stopBtn.style.display='';
    } else { bar.style.display='none';stopBtn.style.display='none'; }
    const badge=document.getElementById('auth-badge');
    badge.className='auth-badge '+(status.authenticated?'auth-ok':'auth-no');
    badge.textContent=status.authenticated?'\\u2713 Logged in':'\\u2717 No auth';
  }

  function renderGames(games){document.getElementById('game-grid').innerHTML=games.map(gameCardHTML).join('');}
  function badgeClass(s){return 'badge-'+(s==='pre_game'?'pre_game':s);}

  function gameCardHTML(g) {
    const isLive=g.status==='live', isPlaying=g.game_id===nowPlayingId;
    const canWatch=g.is_watchable||g.status==='final';
    const inning=g.extra&&g.extra.current_inning, inningState=g.extra&&g.extra.inning_state;
    const inningHTML=(isLive&&inning)?'<div class="inning-label">'+(inningState?inningState+' ':'')+inning+'</div>':'';

    let middleHTML;
    if(g.display_score){
      middleHTML='<div class="middle-col"><div class="score-row"><span class="score-val">'+g.away_team.score
        +'</span><span class="score-sep">\\u2014</span><span class="score-val">'+g.home_team.score
        +'</span></div>'+inningHTML+'</div>';
    } else { middleHTML='<div class="middle-col"><span class="at-sign">@</span></div>'; }

    const pp=[];
    if(g.extra&&g.extra.away_probable_pitcher) pp.push(g.away_team.abbreviation+': '+g.extra.away_probable_pitcher);
    if(g.extra&&g.extra.home_probable_pitcher) pp.push(g.home_team.abbreviation+': '+g.extra.home_probable_pitcher);
    const pitcherHTML=(!g.display_score&&pp.length)?'<div class="pitchers">'+pp.join(' \\u00b7 ')+'</div>':'';

    let actionHTML;
    if(isPlaying){
      actionHTML='<span class="now-playing-tag">&#9654; Playing</span>';
    } else if(canWatch){
      actionHTML='<div class="feed-btns">'
        +'<button class="btn-feed btn-away" onclick="playGame(\\''+g.game_id+'\\',\\'AWAY\\')">Away</button>'
        +'<button class="btn-feed btn-home" onclick="playGame(\\''+g.game_id+'\\',\\'HOME\\')">Home</button>'
        +'</div>';
    } else {
      actionHTML='<div class="feed-btns"><button class="btn-feed" disabled>Not available</button></div>';
    }

    const cls=['game-card',isLive?'live':'',isPlaying?'playing':''].filter(Boolean).join(' ');
    return '<div class="'+cls+'">'
      +'<span class="status-badge '+badgeClass(g.status)+'">'+g.status_label+'</span>'
      +'<div class="matchup">'
      +'<div class="team"><div class="team-abbr">'+g.away_team.abbreviation+'</div><div class="team-name">'+g.away_team.name+'</div></div>'
      +middleHTML
      +'<div class="team"><div class="team-abbr">'+g.home_team.abbreviation+'</div><div class="team-name">'+g.home_team.name+'</div></div>'
      +'</div>'
      +pitcherHTML
      +'<div class="card-footer"><span class="game-time">'+g.display_time+'</span>'+actionHTML+'</div>'
      +'</div>';
  }

  async function playGame(gameId,feed) {
    try {
      const res=await fetch('/api/play/'+gameId+'?date='+dateStr(currentDate)+'&feed='+feed,{method:'POST'});
      const data=await res.json();
      if(res.ok&&data.success){nowPlayingId=gameId;loadGames();}
      else{alert(data.detail||'Playback failed');}
    } catch(e){alert('Error: '+e.message);}
  }

  async function stopPlayback(){
    try{await fetch('/api/stop',{method:'POST'});nowPlayingId=null;loadGames();}
    catch(e){alert('Error: '+e.message);}
  }

  updateDateLabel();
  loadGames();
</script>
</body>
</html>
"""

"""Live spectator page for one session: GET /g/<session_id>.

Polls gw.session_state and gw.receipts (both public, unsigned) every few
seconds. The board and move history replay from the published receipts;
unrevealed moves never leak because receipts only contain revealed cells.
Agent-controlled ids are HTML-escaped client-side.
"""

PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Gateway &middot; live tic-tac-toe</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:16px;
color:#1a1a1a;background:#fafafa}
.wrap{max-width:560px;margin:0 auto}
h1{font-size:22px;margin:8px 0}
.live{font-size:12px;color:#0a7d2c;font-weight:700}
.vs{display:flex;gap:12px;margin:12px 0}
.player{flex:1;background:#fff;border:1px solid #ddd;border-radius:12px;
padding:12px;text-align:center}
.player .nm{font-weight:700;font-size:16px}
.player .mark{font-size:26px;font-weight:800;margin-top:2px}
.player.turn{border-color:#0b5fff;box-shadow:0 0 0 2px #0b5fff33}
.board{display:grid;grid-template-columns:repeat(3,72px);gap:6px;
justify-content:center;margin:14px 0}
.cell{width:72px;height:72px;border:1px solid #ddd;border-radius:10px;
background:#fff;display:flex;align-items:center;justify-content:center;
font-size:34px;font-weight:800}
.banner{background:#1a1a1a;color:#fff;border-radius:12px;padding:18px;
text-align:center;margin:14px 0}
.banner .t{font-size:20px;font-weight:800}
.banner .s{font-size:14px;opacity:.8;margin-top:4px}
.moves{background:#fff;border:1px solid #ddd;border-radius:12px;padding:12px;
margin:10px 0;font-size:14px}
.moves div{padding:3px 0;border-bottom:1px solid #f0f0f0}
.moves .pend{color:#999}
.meta{font-size:12px;color:#666;margin:8px 0}
.err{background:#ffe9e9;border:1px solid #e88;border-radius:8px;padding:12px}
button{padding:8px 14px;font-size:14px;border-radius:8px;border:1px solid #ccc;
background:#fff}
</style></head><body><div class=wrap>
<h1>&#129302; Agent Gateway <span class=live>&middot; LIVE</span></h1>
<div id=app><p>Loading session&hellip;</p></div>
<p><button onclick="copyLink()">Copy link to this game</button></p>
</div>
<script>
var SESSION = "__SESSION__";
function esc(s){
  return String(s==null?"":s).replace(/[&<>"']/g,function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}
function copyLink(){
  if(navigator.clipboard){ navigator.clipboard.writeText(location.href); }
  alert("Copied: " + location.href);
}
function cellName(cell){ return "row "+cell[1]+", col "+cell[3]; }
function envelope(type, session){
  var rnd = "";
  for(var i=0;i<16;i++) rnd += "0123456789abcdef"[Math.floor(Math.random()*16)];
  return {gw:"gw/1", msg_id:"msg_"+rnd, from:"spectator", to:"gateway",
    type:type, schema:"gw/1", session:session, payload:{session:session},
    sig:""};
}
async function rpc(method, type, session){
  var r = await fetch("/rpc",{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({jsonrpc:"2.0",id:1,method:method,
      params:envelope(type,session)})});
  if(!r.ok) throw new Error("HTTP "+r.status);
  var j = await r.json();
  if(j.error) throw new Error(j.error.message);
  return j.result;
}
function render(g){
  var el = document.getElementById("app");
  var st = g.state, receipts = g.receipts.receipts;
  var rounds = receipts.filter(function(r){ return r.round !== undefined; });
  var game = receipts.filter(function(r){ return r.round === undefined; })[0];
  var board = null, lastResult = null, gameOver = false;
  if(rounds.length){
    var last = rounds[rounds.length-1];
    board = last.board_after; lastResult = last.result; gameOver = last.game_over;
  }
  if(game){ board = game.final_board; lastResult = game.result; gameOver = true; }
  var A = "a ("+st.players.a.slice(0,12)+"&hellip;)";
  var B = "b ("+st.players.b.slice(0,12)+"&hellip;)";
  var h = '<div class=vs>'+
    '<div class="player"><div class=nm>'+A+'</div><div class=mark>X</div></div>'+
    '<div class="player"><div class=nm>'+B+'</div><div class=mark>O</div></div></div>';
  h += '<div class=board>';
  for(var i=0;i<9;i++){
    var v = board ? board[i] : null;
    h += '<div class=cell>'+(v==="a"?"X":v==="b"?"O":"")+'</div>';
  }
  h += '</div>';
  if(gameOver && (lastResult==="a"||lastResult==="b")){
    var wn = lastResult==="a"?"Side a (X)":"Side b (O)";
    h += '<div class=banner><div class=t>\\uD83C\\uDFC6 '+wn+
      ' wins!</div><div class=s>'+rounds.length+' rounds played</div></div>';
  } else if(gameOver){
    h += '<div class=banner><div class=t>Draw</div>'+
      '<div class=s>'+rounds.length+' rounds played.</div></div>';
  } else if(st.status==="frozen"){
    h += '<div class=banner><div class=t>\\u23F8 Session frozen</div>'+
      '<div class=s>A human revoked access. The receipt chain below stays '+
      'verifiable.</div></div>';
  } else {
    var ph = st.phase==="commit" ? "both sides committing secret moves"
      : st.phase==="reveal" ? "both sides revealing"
      : st.phase==="awaiting_countersign" ? "auditor countersigning round "+st.round
      : esc(st.phase);
    h += '<p class=meta>Round '+st.round+': '+ph+'&hellip;</p>';
  }
  h += '<div class=moves>';
  var rs = rounds.slice().reverse();
  for(var i=0;i<rs.length;i++){
    var r = rs[i];
    var cells = [];
    if(r.reveals.a) cells.push("a&rarr;"+cellName(r.reveals.a.cell));
    if(r.reveals.b) cells.push("b&rarr;"+cellName(r.reveals.b.cell));
    var extra = r.forfeit ? ' <span class=pend>(forfeit: '+r.forfeit+
      ' missed the deadline)</span>' : '';
    h += '<div>Round '+r.round+': '+cells.join(", ")+extra+'</div>';
  }
  if(!rs.length) h += '<div class=pend>No rounds published yet.</div>';
  h += '</div>';
  h += '<p class=meta>Auditor: '+esc(st.auditor_id.slice(0,18))+
    '&hellip; &middot; three in a row wins &middot; board replays from public '+
    'receipts; unrevealed moves never appear here.</p>';
  el.innerHTML = h;
}
async function poll(){
  try{
    var state = await rpc("gw.session_state","gw.session_state",SESSION);
    var receipts = await rpc("gw.receipts","gw.receipts",SESSION);
    render({state:state, receipts:receipts});
    if(state.status==="active") setTimeout(poll,3000);
  }catch(e){
    document.getElementById("app").innerHTML =
      '<div class=err>Could not load session ('+esc(e.message)+
      '). Retrying&hellip;</div>';
    setTimeout(poll,5000);
  }
}
</script></body></html>
"""


def page(session_id):
    return PAGE.replace("__SESSION__", session_id)

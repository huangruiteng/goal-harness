#!/usr/bin/env python3
"""从 viz/data.json + viz/SUMMARY.md + viz/trajectories/_index.json 生成 index.html。

指标仪表盘与总结报告内嵌（离线可开）；逐 trial 轨迹按需 fetch
trajectories/<task>__<arm>.json（在 gh-pages / 本地 http 下可用）。

    _build_viz.py viz/data.json viz/SUMMARY.md viz/index.html
"""
from __future__ import annotations
import json, sys, pathlib

base = pathlib.Path(sys.argv[1]).parent if len(sys.argv) > 1 else pathlib.Path("viz")
data_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "viz/data.json")
md_path   = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "viz/SUMMARY.md")
out_path  = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else "viz/index.html")

data = json.loads(data_path.read_text())
md_raw = md_path.read_text()
idx_path = base / "trajectories" / "_index.json"
traj_idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}

DATA_JSON = json.dumps(data, ensure_ascii=False)
MD_JSON   = json.dumps(md_raw, ensure_ascii=False)
IDX_JSON  = json.dumps(traj_idx, ensure_ascii=False)

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SWE-Marathon · codex × LoopX 总结报告</title>
<style>
:root{--bg:#0f1117;--card:#181b23;--card2:#1f2430;--fg:#e6e9ef;--mut:#9aa4b2;
--line:#2a2f3a;--acc:#7aa2f7;--good:#4ec9b0;--warn:#e0af68;--bad:#f7768e;--vio:#bb9af7;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 -apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--acc)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 6px}
.sub{color:var(--mut);margin:0 0 22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 20px}
h2{font-size:18px;margin:2px 0 14px;display:flex;align-items:center;gap:8px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
tbody tr:hover{background:var(--card2)}
.arm{font-weight:600}
.bar{position:relative}
.bar span{position:absolute;left:0;top:0;bottom:0;background:rgba(122,162,247,.16);border-radius:4px;z-index:0}
.bar b{position:relative;z-index:1;font-weight:600}
.pill{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;font-weight:600}
.p-good{background:rgba(78,201,176,.18);color:var(--good)}
.p-warn{background:rgba(224,175,104,.18);color:var(--warn)}
.p-bad{background:rgba(247,118,142,.18);color:var(--bad)}
.grid-tbl td{text-align:center;cursor:pointer;font-variant-numeric:tabular-nums}
.grid-tbl td:first-child{text-align:left;cursor:default;color:var(--fg)}
.cellv{display:block;font-weight:600}.cellp{display:block;font-size:11px;color:var(--mut)}
.legend{color:var(--mut);font-size:12px;margin-top:10px}
.tabs{display:flex;gap:6px;margin:0 0 16px;flex-wrap:wrap}
.tab{padding:7px 14px;border:1px solid var(--line);border-radius:8px;background:var(--card);
color:var(--mut);cursor:pointer;font-weight:600}
.tab.on{background:var(--acc);color:#0f1117;border-color:var(--acc)}
.hide{display:none}
.md{font-size:14px}
.md h1{font-size:22px;border-bottom:1px solid var(--line);padding-bottom:8px}
.md h2{font-size:17px;margin-top:22px}.md table{margin:12px 0}
.md code{background:var(--card2);padding:1px 5px;border-radius:4px;font-size:12px}
.md pre{background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto}
.md pre code{background:none;padding:0}
.md blockquote{border-left:3px solid var(--acc);margin:12px 0;padding:2px 14px;color:var(--mut)}
.note{color:var(--mut);font-size:12px}
.dl{display:inline-block;margin-top:8px;padding:6px 12px;border:1px solid var(--line);
border-radius:8px;color:var(--acc);text-decoration:none;font-weight:600}
select{background:var(--card2);color:var(--fg);border:1px solid var(--line);border-radius:8px;
padding:7px 10px;font-size:14px;font-weight:600}
.ctrl{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.tmeta{color:var(--mut);font-size:12px;margin-left:auto}
/* 轨迹步骤 */
.step{border:1px solid var(--line);border-radius:9px;margin:8px 0;overflow:hidden}
.step .hd{display:flex;gap:8px;align-items:center;padding:7px 12px;cursor:pointer;font-size:12px}
.step .hd b{font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.step .bd{padding:0 12px 10px;font-size:12.5px;white-space:pre-wrap;word-break:break-word;
font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.step.k-goal{border-color:var(--vio)}.step.k-goal .hd{background:rgba(187,154,247,.14);color:var(--vio)}
.step.k-exec .hd{background:rgba(122,162,247,.12);color:var(--acc)}
.step.k-output .hd{background:rgba(154,164,178,.10);color:var(--mut)}
.step.k-reason .hd{background:transparent;color:var(--mut)}
.step.k-msg .hd{background:rgba(78,201,176,.10);color:var(--good)}
.step.k-event .hd{background:rgba(224,175,104,.12);color:var(--warn)}
.step .n{color:var(--mut);font-weight:600;min-width:34px}
.role{font-size:11px;color:var(--mut)}
.hint{color:var(--mut);font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <h1>SWE-Marathon · codex × LoopX 总结报告</h1>
  <p class="sub" id="sub"></p>

  <div class="tabs">
    <div class="tab on" data-t="overview">总览</div>
    <div class="tab" data-t="grid">逐任务</div>
    <div class="tab" data-t="traj">轨迹浏览</div>
    <div class="tab" data-t="report">总结报告</div>
  </div>

  <div id="overview">
    <div class="card"><h2>五模式汇总 <span class="note">（仅 15 个五模式齐任务）</span></h2>
      <div id="armtbl"></div>
      <div class="legend">reward = 二值（紧预算下多为 0）；partial_score = 任务连续分（主指标）；
        "自己收工" = goal receipt 主动 complete 而非撞死线被砍。
        reward / partial 均值已剔除构建失败的 case（codex-cli 按 14 个任务，其余 15 个）；
        花费 / 自收工 / 续跑 / 解锁按全量。</div></div>
    <div class="card"><h2>模式的角色</h2><div id="roles"></div></div>
  </div>

  <div id="grid" class="hide">
    <div class="card"><h2>逐任务 × 五模式</h2><div id="gridtbl"></div>
      <div class="legend">每格上行 = partial_score，下行 = reward；<span class="p-bad">红</span> = 构建失败归零。
        点任意格 → 跳到该 trial 的轨迹浏览。</div></div>
  </div>

  <div id="traj" class="hide">
    <div class="card">
      <div class="ctrl">
        <label>任务 <select id="selTask"></select></label>
        <label>模式 <select id="selArm"></select></label>
        <span class="tmeta" id="tmeta"></span>
      </div>
      <div class="hint" id="thint">选择任务与模式查看该 trial 的完整执行轨迹。plain 模式没有 <b>goal 注入</b>步；
        goal（codex 原生）与三个 LoopX 模式都有紫色 <b>goal 注入</b>——但只有 LoopX 三模式的 goal body
        带 claim/lease/peer 样板，goal 模式是干净 goal。</div>
      <div id="steps"></div>
    </div>
  </div>

  <div id="report" class="hide">
    <div class="card"><a class="dl" id="dlmd" download="codex-loopx-swe-marathon.md">下载 SUMMARY.md</a>
      <div class="md" id="mdbody"></div></div>
  </div>
</div>

<script id="DATA" type="application/json">__DATA__</script>
<script id="MD" type="application/json">__MD__</script>
<script id="IDX" type="application/json">__IDX__</script>
<script>
const D=JSON.parse(document.getElementById('DATA').textContent);
const MD=JSON.parse(document.getElementById('MD').textContent);
const IDX=JSON.parse(document.getElementById('IDX').textContent);
const ARMS=D.arms;
const fmt=(v,d=3)=>v==null?'—':(+v).toFixed(d);
const usd=v=>'$'+Math.round(v);
const kfmt=n=>n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(0)+'k':(''+n);
const esc=s=>(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

document.getElementById('sub').textContent=
 `${D.bench} · ${D.tasks_full.length} 个五模式齐任务 · ${D.n_trials} trial · 模型 gpt-5.6 · 预算 ~30% · 生成于 ${D.generated_at||''}`;

// 五模式汇总
function armTable(){const S=D.arm_summary;const maxPart=Math.max(...ARMS.map(a=>S[a].partial||0));
 let h='<table><thead><tr><th>模式</th><th>reward</th><th>partial</th><th>花费</th><th>自己收工</th>'
   +'<th>续跑</th><th>解锁</th><th>构建失败</th><th>输出tok</th></tr></thead><tbody>';
 for(const a of ARMS){const s=S[a];const pw=(100*(s.partial||0)/maxPart).toFixed(0);const best=s.partial===maxPart;
  h+=`<tr><td class="arm">${a}</td><td>${fmt(s.reward)}</td>`
   +`<td class="bar"><span style="width:${pw}%"></span><b>${fmt(s.partial)}</b>${best?' <span class="pill p-good">最高</span>':''}</td>`
   +`<td>${usd(s.cost)}</td><td>${scPill(s.self_complete,s.n)}</td><td>${s.cont_total}</td><td>${s.unblock_total}</td>`
   +`<td>${s.build_failed?('<span class="pill p-bad">'+s.build_failed+'/'+s.n+'</span>'):'0/'+s.n}</td><td>${kfmt(s.tok_out)}</td></tr>`;}
 return h+'</tbody></table>';}
function scPill(x,n){const r=x/n;const c=r>=0.8?'p-good':r>=0.5?'p-warn':'p-bad';return `<span class="pill ${c}">${x}/${n}</span>`;}
function roles(){let h='<table><tbody>';for(const a of ARMS)h+=`<tr><td class="arm">${a}</td><td style="text-align:left;color:var(--mut)">${D.arm_role[a]}</td></tr>`;return h+'</tbody></table>';}

// 逐任务热力
function gridTable(){let h='<table class="grid-tbl"><thead><tr><th>任务</th>'+ARMS.map(a=>`<th style="text-align:center">${a}</th>`).join('')+'</tr></thead><tbody>';
 for(const t of D.tasks_all){h+=`<tr><td>${t}</td>`;
  for(const a of ARMS){const c=(D.cells[t]||{})[a];if(!c){h+='<td>—</td>';continue;}
   const p=c.partial;const bg=c.build_failed?'rgba(247,118,142,.22)':heat(p);const rv=c.reward==null?'?':(+c.reward).toFixed(0);
   h+=`<td style="background:${bg}" data-t="${t}" data-a="${a}"><span class="cellv">${p==null?'—':(+p).toFixed(2)}${c.build_failed?'✗':''}</span><span class="cellp">r=${rv}</span></td>`;}
  h+='</tr>';}return h+'</tbody></table>';}
function heat(p){if(p==null)return'transparent';const o=(0.10+0.30*p).toFixed(2);return `rgba(78,201,176,${o})`;}

// ---- 轨迹浏览 ----
function initTraj(){
 const st=document.getElementById('selTask'),sa=document.getElementById('selArm');
 const tasks=Object.keys(IDX).sort();
 st.innerHTML=tasks.map(t=>`<option>${t}</option>`).join('');
 function fillArms(){const t=st.value;const arms=ARMS.filter(a=>IDX[t]&&IDX[t][a]);
   sa.innerHTML=arms.map(a=>`<option>${a}</option>`).join('');}
 st.onchange=()=>{fillArms();loadTraj();};
 sa.onchange=loadTraj;
 fillArms();
}
async function loadTraj(){
 const t=document.getElementById('selTask').value,a=document.getElementById('selArm').value;
 const box=document.getElementById('steps'),meta=document.getElementById('tmeta');
 const c=(D.cells[t]||{})[a]||{};
 meta.innerHTML=`reward=${fmt(c.reward,0)} · partial=${fmt(c.partial)} · $${(c.cost||0).toFixed(2)} · 续跑 ${c.cont==null?'—':c.cont} · 解锁 ${c.unblock==null?'—':c.unblock} · ${IDX[t]&&IDX[t][a]||0} 步`;
 box.innerHTML='<p class="hint">加载中…</p>';
 try{
  const r=await fetch(`trajectories/${t}__${a}.json`);
  if(!r.ok)throw new Error(r.status);
  const j=await r.json();
  box.innerHTML=j.steps.map(renderStep).join('');
 }catch(e){box.innerHTML=`<p class="hint">无法加载轨迹（${e}）。轨迹需在 http/gh-pages 下浏览（file:// 直接打开会被浏览器拦截 fetch）。</p>`;}
}
const KLAB={goal:'goal 注入',exec:'exec',output:'输出',reason:'reasoning',msg:'消息',event:'事件'};
function renderStep(s,i){
 const open=(s.kind==='goal'||s.kind==='msg'||s.kind==='event');
 const label=KLAB[s.kind]||s.kind;
 const role=s.role?`<span class="role">${s.role}</span>`:'';
 const body=s.text?`<div class="bd" ${open?'':'style="display:none"'}>${esc(s.text)}</div>`:'';
 const preview=s.kind==='exec'?esc((s.text||'').split('\n')[0].slice(0,80)):'';
 return `<div class="step k-${s.kind}"><div class="hd" onclick="this.nextElementSibling&&(this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none')">`
  +`<span class="n">${i+1}</span><b>${label}</b>${role}<span style="color:var(--mut);font-weight:400">${preview}</span></div>${body}</div>`;
}

// 极简 markdown
function mdRender(src){const inl=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2">$1</a>');
 const L=src.split('\n');let o=[],i=0;
 while(i<L.length){let l=L[i];
  if(/^```/.test(l)){let b=[];i++;while(i<L.length&&!/^```/.test(L[i])){b.push(esc(L[i]));i++;}i++;o.push('<pre><code>'+b.join('\n')+'</code></pre>');continue;}
  if(/^\|/.test(l)){let tb=[];while(i<L.length&&/^\|/.test(L[i])){tb.push(L[i]);i++;}o.push(mdTable(tb,inl));continue;}
  let m;if(m=l.match(/^(#{1,4})\s+(.*)/)){o.push(`<h${m[1].length}>${inl(m[2])}</h${m[1].length}>`);i++;continue;}
  if(/^>\s?/.test(l)){let b=[];while(i<L.length&&/^>\s?/.test(L[i])){b.push(inl(L[i].replace(/^>\s?/,'')));i++;}o.push('<blockquote>'+b.join('<br>')+'</blockquote>');continue;}
  if(/^\s*\d+\.\s+/.test(l)){let b=[];while(i<L.length&&/^\s*\d+\.\s+/.test(L[i])){b.push('<li>'+inl(L[i].replace(/^\s*\d+\.\s+/,''))+'</li>');i++;}o.push('<ol>'+b.join('')+'</ol>');continue;}
  if(/^(\s*)[-*]\s+/.test(l)){let b=[];while(i<L.length&&/^(\s*)[-*]\s+/.test(L[i])){b.push('<li>'+inl(L[i].replace(/^(\s*)[-*]\s+/,''))+'</li>');i++;}o.push('<ul>'+b.join('')+'</ul>');continue;}
  if(/^(---|\*\*\*)\s*$/.test(l)){o.push('<hr>');i++;continue;}
  if(l.trim()===''){i++;continue;}o.push('<p>'+inl(l)+'</p>');i++;}
 return o.join('\n');}
function mdTable(rows,inl){const cells=r=>r.replace(/^\||\|$/g,'').split('|').map(s=>s.trim());
 const head=cells(rows[0]);const body=rows.slice(2).map(cells);
 let h='<table><thead><tr>'+head.map(c=>`<th>${inl(c)}</th>`).join('')+'</tr></thead><tbody>';
 for(const r of body)h+='<tr>'+r.map(c=>`<td>${inl(c)}</td>`).join('')+'</tr>';return h+'</tbody></table>';}

// 挂载
document.getElementById('armtbl').innerHTML=armTable();
document.getElementById('roles').innerHTML=roles();
document.getElementById('gridtbl').innerHTML=gridTable();
document.getElementById('mdbody').innerHTML=mdRender(MD);
document.getElementById('dlmd').href='data:text/markdown;charset=utf-8,'+encodeURIComponent(MD);
initTraj();loadTraj();

document.getElementById('gridtbl').addEventListener('click',e=>{const td=e.target.closest('td[data-t]');if(!td)return;
 document.getElementById('selTask').value=td.dataset.t;
 document.getElementById('selTask').onchange();
 document.getElementById('selArm').value=td.dataset.a;loadTraj();switchTab('traj');});

function switchTab(name){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x.dataset.t===name));
 for(const id of ['overview','grid','traj','report'])document.getElementById(id).classList.toggle('hide',id!==name);}
document.querySelectorAll('.tab').forEach(tab=>tab.addEventListener('click',()=>switchTab(tab.dataset.t)));
</script>
</body>
</html>
"""

out = HTML.replace("__DATA__", DATA_JSON).replace("__MD__", MD_JSON).replace("__IDX__", IDX_JSON)
out_path.write_text(out)
print(f"写出 {out_path}（{len(out)} 字节）；轨迹索引 {sum(len(v) for v in traj_idx.values())} 条")

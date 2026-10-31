'use strict';
const $ = id => document.getElementById(id);
const modes = {auto:'自动',cool:'制冷',dry:'除湿',heat:'制热',fan:'送风'};
const fans = {breeze:'微风',low:'低风',medium:'中风',high:'大风',auto:'自动风量'};
let csrf = '', snapshot = null, busy = false, dirty = false, initialized = false;
let draft = {mode:'cool',temperature:24,fan:'high'}, manualFan = 'high';
let cooldownEnd = 0, toastTimer, pollTimer, serverOffset = 0;
const icon = name => { const s = document.createElementNS('http://www.w3.org/2000/svg','svg'); const u = document.createElementNS(s.namespaceURI,'use'); u.setAttribute('href','#i-'+name); s.append(u); return s; };
document.querySelectorAll('.button-arrow').forEach(el => { el.textContent=''; el.append(icon('arrow')); });
for(let i=0;i<=26;i++){ const angle=(-138+i*276/26)*Math.PI/180; const tick=document.createElementNS('http://www.w3.org/2000/svg','line'); const x=160,y=130,r=113,len=i%2===0?7:4; tick.setAttribute('x1',x+r*Math.sin(angle));tick.setAttribute('y1',y-r*Math.cos(angle));tick.setAttribute('x2',x+(r-len)*Math.sin(angle));tick.setAttribute('y2',y-(r-len)*Math.cos(angle));tick.setAttribute('stroke','var(--line)');$('dial-ticks').append(tick); }

function toast(message,error=false){ clearTimeout(toastTimer);$('toast').textContent=message;$('toast').className='toast'+(error?' error':'');$('toast').hidden=false;toastTimer=setTimeout(()=>{$('toast').hidden=true},error?6500:3300); }
function setScreen(authenticated){$('loading-screen').hidden=true;$('app-screen').hidden=!authenticated;$('login-screen').hidden=authenticated;if(!authenticated){clearInterval(pollTimer);csrf='';$('connection-text').textContent='专属控制入口';$('connection').className='connection';}}
async function api(path,options={}){const res=await fetch(path,{credentials:'same-origin',...options,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})}});let data;try{data=await res.json()}catch{throw new Error('服务暂时不可用，请稍后重试。')}if(res.status===401&&path!='/api/login'){setScreen(false);throw new Error('登录已过期，请重新解锁。')}if(!res.ok)throw new Error(data.message||'请求失败，请稍后重试。');return data;}
function summary(state){return [modes[state.mode],state.mode!=='fan'&&state.temperature!=null?state.temperature+'°C':null,fans[state.fan]].filter(Boolean).join(' · ');}
function relativeTime(value){if(!value)return '尚未发送';const d=new Date(value);if(Number.isNaN(d.getTime()))return '';const sec=(Date.now()-d)/1000;if(sec<60)return '刚刚';if(sec<3600)return Math.floor(sec/60)+' 分钟前';return d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});}
function renderDraft(){const noTemp=draft.mode==='fan',locked=['auto','dry'].includes(draft.mode);$('temperature').textContent=noTemp?'--':draft.temperature;$('temperature-slider').value=draft.temperature;$('temperature-slider').disabled=noTemp;$('temp-down').disabled=noTemp||draft.temperature<=17;$('temp-up').disabled=noTemp||draft.temperature>=30;$('temperature-note').textContent=noTemp?'送风模式不设定温度':'17–30°C 可调';$('setpoint-caption').textContent=noTemp?'让空气，轻轻流动':'冷暖，恰到好处';$('arc-value').setAttribute('stroke-dasharray',noTemp?'0 100':((draft.temperature-17)/13*100)+' 100');$('mode-summary').replaceChildren(icon(draft.mode),document.createTextNode(modes[draft.mode]+'模式'));document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.mode===draft.mode));document.querySelectorAll('[data-fan]').forEach(b=>{b.disabled=locked;b.setAttribute('aria-pressed',!locked&&b.dataset.fan===draft.fan)});$('fan-note').textContent=locked?'此模式自动调节风量':'四档可调';$('mode-note').textContent=draft.mode==='heat'?'这台室内机是否支持制热，尚未验证。':'';$('apply-summary').textContent=summary(draft);$('draft-badge').textContent=dirty?'待应用':'目标设定';$('draft-badge').className='draft-badge'+(dirty?' pending':'');renderTimerSettings();renderAvailability();}
function edit(change){Object.assign(draft,change);dirty=true;renderDraft();}
function renderAvailability(){const online=Boolean(snapshot?.board?.online),seconds=Math.max(0,Math.ceil((cooldownEnd-Date.now())/1000));const disabled=busy||!online||seconds>0;$('apply').disabled=disabled;$('power').disabled=disabled;document.querySelectorAll('[data-button]').forEach(b=>b.disabled=disabled);$('apply').replaceChildren(document.createTextNode(busy?'正在发送':seconds?seconds+' 秒后可发送':'应用设置'));if(!busy&&!seconds)$('apply').append(icon('arrow'));$('apply-note').textContent=busy?'指令处理中，请稍候':!online?'连接 UNO 后即可控制':seconds?'稍等一下，让上一条指令完成':dirty?'有新的设定等待应用':'调整后点击应用';renderScheduleAvailability(disabled);}
function renderState(data){snapshot=data;serverOffset=(data.server_time||Date.now()/1000)-Date.now()/1000;renderSchedules();cooldownEnd=Date.now()+data.cooldown_ms;const s=data.state,online=data.board.online;$('connection').className='connection '+(online?'online':'offline');$('connection-text').textContent=online?'控制器在线':'控制器离线';$('power-label').textContent=s.power===true?'关机':'开机';$('power').className='power-button'+(s.power===true?' on':'');$('power').setAttribute('aria-label',s.power===true?'关闭空调':'按目标设定开启空调');$('sent-summary').textContent=s.last_sent_at?summary(s):'等待第一次操作';$('sent-time').textContent=relativeTime(s.last_sent_at);$('sent-power').textContent=s.confidence==='unknown'?'状态未确认':s.power===true?'已发送开机':s.power===false?'已发送关机':'开关未知';$('sent-silence').textContent=s.silence?'Silence '+(s.silence==='on'?'开启指令已发':'关闭指令已发'):'Silence 未知';$('vertical-count').textContent='本服务已发送 '+s.vertical_steps+' 次步进；当前绝对角度未知。';if(!dirty&&!busy&&s.last_sent_at){draft={mode:s.mode,temperature:s.temperature??draft.temperature,fan:s.fan};if(!['auto','dry'].includes(s.mode))manualFan=s.fan;}const list=$('history');list.replaceChildren();if(!data.history.length){const li=document.createElement('li');li.className='empty-history';li.textContent='第一次发送后，操作记录会显示在这里。';list.append(li);}for(const h of data.history){const li=document.createElement('li'),mark=document.createElement('span'),label=document.createElement('span'),state=document.createElement('span'),time=document.createElement('time');mark.className='event-icon';mark.append(icon(h.status==='sent'?'check':'auto'));label.className='event-label';label.append(document.createTextNode(h.label));state.className='event-state';state.textContent={sent:'已发送 · 空调无回传',unknown:'结果未确认 · 未自动重发',failed:'未发送成功',pending:'处理中'}[h.status]||h.status;label.append(state);time.dateTime=h.created;time.textContent=relativeTime(h.created);li.append(mark,label,time);list.append(li);}renderDraft();}
async function refresh(quiet=true){try{renderState(await api('/api/state'));initialized=true;}catch(e){if(snapshot){snapshot.board.online=false;$('connection').className='connection offline';$('connection-text').textContent='连接中断';renderAvailability();}if(!quiet)toast(e.message,true);}}
async function start(){setScreen(true);await refresh(false);clearInterval(pollTimer);pollTimer=setInterval(()=>refresh(),4000);}
async function send(payload){if(busy||!snapshot?.board?.online||Date.now()<cooldownEnd)return;busy=true;renderAvailability();try{const id=crypto.randomUUID();const result=await api('/api/command',{method:'POST',headers:{'X-CSRF-Token':csrf,'X-Request-ID':id},body:JSON.stringify(payload)});if(result.status==='sent'){if(payload.action==='climate'||['sleep-first-sample','sleep-second-sample','power-on-sample'].includes(payload.button))dirty=false;toast(result.label+' · 已发送');}else{toast(result.message,true);}await refresh();}catch(e){toast(e.message+' 未自动重发。',true);}finally{busy=false;await refresh();renderAvailability();}}
function serverNow(){return Date.now()/1000+serverOffset;}
function activePrecool(){return (snapshot?.schedules||[]).find(j=>j.kind==='precool'&&['pending','running'].includes(j.status));}
function scheduleTime(stamp){return new Date(stamp*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function renderTimerSettings(){const on=$('timer-action').value==='on';$('timer-setting').textContent=on?'开机时使用：'+summary(draft)+'。添加后保留这组设定。':'到点发送关机指令。';$('timer-submit').textContent=on?'添加定时开机':'添加定时关机';}
function renderScheduleAvailability(disabled){
  const job=activePrecool(),ready=Array.isArray(snapshot?.schedules);
  $('precool-start').disabled=disabled||Boolean(job)||!ready;
  $('precool-start').replaceChildren(icon('cool'),document.createTextNode(job?'预制冷进行中':'一键预制冷'));
  $('precool-cancel').hidden=!job;$('precool-cancel').disabled=busy;
  $('timer-submit').disabled=busy||!ready;
  document.querySelectorAll('[data-cancel-job]').forEach(b=>b.disabled=busy);
  if(job){const seconds=Math.max(0,Math.ceil(job.due_at-serverNow()));$('precool-status').textContent=job.phase==='dry'?'制冷指令已发送 · '+Math.floor(seconds/60)+' 分 '+String(seconds%60).padStart(2,'0')+' 秒后切换除湿 24°C':'正在发送制冷指令…';}
  else {const last=(snapshot?.schedules||[]).find(j=>j.kind==='precool');$('precool-status').textContent=last?last.message:'关闭网页后，服务器会继续计时。';}
}
function renderSchedules(){
  const list=$('schedule-list');list.replaceChildren();
  const jobs=snapshot?.schedules||[];
  if(!jobs.length){const li=document.createElement('li');li.className='empty-schedule';li.textContent='还没有定时任务。';list.append(li);}
  const states={pending:'等待执行',running:'正在执行',completed:'已发送',cancelled:'已取消',missed:'已错过',failed:'执行失败',unknown:'结果未确认'};
  for(const job of jobs){const li=document.createElement('li'),copy=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('small');copy.className='schedule-copy';
    const action=job.kind==='precool'?'预制冷':job.payload.action==='climate'?'定时开机':'定时关机';
    title.textContent=action+' · '+(states[job.status]||job.status);
    detail.textContent=scheduleTime(job.due_at)+' · '+(job.payload.action==='climate'?summary(job.payload)+' · ':'')+job.message;
    copy.append(title,detail);li.append(copy);
    if(job.status==='pending'){const button=document.createElement('button');button.type='button';button.className='text-button';button.dataset.cancelJob=job.id;button.textContent=job.kind==='precool'?'取消切换':'取消';button.setAttribute('aria-label','取消'+action+' '+scheduleTime(job.due_at));button.addEventListener('click',()=>cancelSchedule(job.id));li.append(button);}
    list.append(li);
  }
}
async function scheduleRequest(path,body){
  if(busy)return;busy=true;renderAvailability();
  try{const result=await api(path,{method:'POST',headers:{'X-CSRF-Token':csrf,'X-Request-ID':crypto.randomUUID()},body:JSON.stringify(body)});
    const failed=['failed','unknown','missed'].includes(result.status);const message=result.message||'任务已保存。';
    $('timer-feedback').textContent=message;toast(message,failed);
    if(result.kind==='precool'&&result.status==='pending')dirty=false;
  }catch(e){$('timer-feedback').textContent=e.message+' 未自动重试，请查看任务列表。';toast($('timer-feedback').textContent,true);}
  finally{busy=false;await refresh();renderAvailability();}
}
async function cancelSchedule(id){return scheduleRequest('/api/schedules/'+encodeURIComponent(id)+'/cancel',{});}
$('precool-start').addEventListener('click',()=>scheduleRequest('/api/schedules',{kind:'precool'}));
$('precool-cancel').addEventListener('click',()=>{const job=activePrecool();if(job)cancelSchedule(job.id);});
$('timer-action').addEventListener('change',renderTimerSettings);
$('timer-type').addEventListener('change',()=>{const at=$('timer-type').value==='at';$('timer-delay-field').hidden=at;$('timer-at-field').hidden=!at;$('timer-minutes').required=!at;$('timer-at').required=at;});
$('timer-form').addEventListener('submit',event=>{event.preventDefault();
  const due=$('timer-type').value==='at'?new Date($('timer-at').value).getTime()/1000:serverNow()+Number($('timer-minutes').value)*60;
  if(!Number.isFinite(due)||due<serverNow()+5||due>serverNow()+30*86400){toast('请选择 5 秒后至 30 天内的执行时间。',true);return;}
  scheduleRequest('/api/schedules',{kind:'timer',due_at:due,payload:$('timer-action').value==='on'?climatePayload():{action:'button',button:'power-off'}});
});
const initialTimer=new Date(Date.now()+30*60000);initialTimer.setSeconds(0,0);$('timer-at').value=new Date(initialTimer.getTime()-initialTimer.getTimezoneOffset()*60000).toISOString().slice(0,16);
$('timer-zone').textContent='指定时间按手机时区：'+Intl.DateTimeFormat().resolvedOptions().timeZone;
$('login-form').addEventListener('submit',async event=>{event.preventDefault();$('login-submit').disabled=true;$('login-error').textContent='';try{const data=await api('/api/login',{method:'POST',body:JSON.stringify({code:$('access-code').value})});csrf=data.csrf;$('access-code').value='';await start();}catch(e){$('login-error').textContent=e.message;}finally{$('login-submit').disabled=false;}});
$('temp-down').addEventListener('click',()=>edit({temperature:Math.max(17,draft.temperature-1)}));$('temp-up').addEventListener('click',()=>edit({temperature:Math.min(30,draft.temperature+1)}));$('temperature-slider').addEventListener('input',event=>edit({temperature:Number(event.target.value)}));
document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{const mode=b.dataset.mode;edit({mode,fan:['auto','dry'].includes(mode)?'auto':manualFan});}));
document.querySelectorAll('[data-fan]').forEach(b=>b.addEventListener('click',()=>{manualFan=b.dataset.fan;edit({fan:manualFan});}));
function climatePayload(){return {action:'climate',mode:draft.mode,temperature:draft.mode==='fan'?null:draft.temperature,fan:draft.fan};}
$('apply').addEventListener('click',()=>send(climatePayload()));$('power').addEventListener('click',()=>send(snapshot.state.power===true?{action:'button',button:'power-off'}:climatePayload()));document.querySelectorAll('[data-button]').forEach(b=>b.addEventListener('click',()=>send({action:'button',button:b.dataset.button})));
$('refresh').addEventListener('click',()=>refresh(false));$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',headers:{'X-CSRF-Token':csrf},body:'{}'});setScreen(false);}catch(e){toast(e.message,true);}});
setInterval(renderAvailability,250);document.addEventListener('visibilitychange',()=>{if(!document.hidden&&csrf)refresh();});renderDraft();
(async()=>{try{const data=await api('/api/session');csrf=data.csrf;await start();}catch{setScreen(false);}})();

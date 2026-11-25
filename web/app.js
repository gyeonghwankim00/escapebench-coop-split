const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const names = {
  'room A':'A 방 입구','room B':'B 방 입구','mirror alcove':'거울 구역','A storage':'A 보관함',
  'lamp desk':'램프 책상','A exit panel':'A 출구','B storage':'B 보관함','workbench':'작업대',
  'broken wall':'부서진 벽','safe corner':'금고 구역','records wall':'기록 벽',
  'gold door':'금색 열쇠 문','A workshop':'A 작업실','library':'서가',
  'chair corner':'의자 구역','pool area':'당구대','B exit panel':'B 출구',
  'A bookshelf':'A 책장','bathroom doorway':'욕실 입구','A bathroom':'A 욕실',
  'A locked box':'A 잠긴 상자','B safe':'B 금고','B work area':'B 작업 구역',
  'mirror':'거울','shard_1':'거울 조각 1','shard_2':'거울 조각 2','shard_3':'거울 조각 3',
  'shard_4':'거울 조각 4','toolbox':'공구함','fuse':'퓨즈','screwdriver':'드라이버',
  'desk lamp':'책상 램프','study wall':'서재 벽','flashlight':'손전등','battery':'건전지',
  'safe':'금고','right door to the exit':'출구 문','exit cover':'출구 덮개',
  'exit A':'A 출구','exit B':'B 출구','paper 1':'종이 1','paper 2':'종이 2',
  'black door':'검은 문','book':'책','lockbox':'잠금 상자','gold key':'금색 열쇠',
  'knife':'칼','chair':'의자','pool ball 1':'당구공 1','pool ball 2':'당구공 2',
  'pool ball 3':'당구공 3','pool ball 4':'당구공 4','pockets':'당구대 포켓',
  'key card 1':'키 카드 1','key card 2':'키 카드 2','cashier':'계산대',
  'bottle of wine':'와인병','exit door':'출구 문','scrip 2':'숫자 쪽지',
  'safe 2':'금고 2','picklock':'락픽','bathroom door':'욕실 문',
  'drawer of the cabinet':'캐비닛 서랍','lever':'지렛대','connector':'연결 부품',
  'tool box':'공구 상자','locked box 2':'잠긴 상자 2','round key':'둥근 열쇠',
  'tellurion':'천체 모형','tap':'수도꼭지','pipe':'파이프'
};
const displayName = (value) => names[value] || value;
const icons = {mirror:'◇',book:'▤',chair:'♧',flashlight:'◧',battery:'▥',fuse:'⌁',screwdriver:'⌁',
  'desk lamp':'◒','study wall':'▧',safe:'▣','safe 2':'▣',toolbox:'▣','tool box':'▣',
  pockets:'◌',cashier:'▦',tellurion:'⊛',pipe:'⌁','bottle of wine':'♧'};
function objectIcon(name) {
  if (icons[name]) return icons[name];
  if (/key|card/.test(name)) return '⚿';
  if (/door|exit/.test(name)) return '▯';
  if (/paper|scrip/.test(name)) return '▤';
  if (/ball/.test(name)) return '◉';
  if (/shard/.test(name)) return '◇';
  return '✧';
}

let games = [], selectedGame = '01_mirror_workshop', selectedMode = 'solo';
let auth = null, current = null, currentDialog = null, polling = null, busy = false;
let lastState = '', toastTimer = null;
let drafts = {A:'', B:''};
const STORE = 'escape-room-lab-session-v1';

async function request(path, method = 'GET', payload) {
  const response = await fetch(path, {method, headers: payload ? {'Content-Type':'application/json'} : {},
    body: payload ? JSON.stringify(payload) : undefined, cache:'no-store'});
  let body;
  try { body = await response.json(); } catch { throw new Error('서버 응답을 읽지 못했습니다.'); }
  if (!response.ok) throw new Error(body.error || '요청을 처리하지 못했습니다.');
  return body;
}
function credentials() { return {session:auth.session, actor:auth.actor, key:auth.keys[auth.actor]}; }
function query() { return new URLSearchParams(credentials()).toString(); }
function notify(message) {
  const toast = $('#toast'); toast.textContent = message; toast.classList.remove('hidden');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.add('hidden'), 3000);
}
function openDialog(id) { const dialog = $(id); if (!dialog.open) dialog.showModal(); }
function closeDialog() { if ($('#detail-dialog').open) $('#detail-dialog').close(); currentDialog = null; }

function renderGames() {
  $('#game-options').innerHTML = games.map(g => `<button type="button" class="game-option ${g.id === selectedGame ? 'selected' : ''}" data-game="${escapeHTML(g.id)}" aria-pressed="${g.id === selectedGame}">
    <div class="game-option-top"><span class="game-number">${escapeHTML(g.number)} <span style="font-size:10px;color:#c5cfc0">/ ${games.length.toString().padStart(2, '0')}</span></span><span class="game-radio"></span></div>
    <h3>${escapeHTML(g.title)}</h3><p>${escapeHTML(g.description)}</p><div class="tag-list">${g.tags.map(t => `<span class="tag">${escapeHTML(t)}</span>`).join('')}</div></button>`).join('');
}

function showWelcome() {
  clearInterval(polling); polling = null; current = null; auth = null; lastState = '';
  sessionStorage.removeItem(STORE); history.replaceState({}, '', '/'); drafts = {A:'', B:''};
  $('#message-input').value = '';
  $('#game').classList.add('hidden'); $('#welcome').classList.remove('hidden');
}
function enterGame() {
  $('#welcome').classList.add('hidden'); $('#game').classList.remove('hidden');
  $('#invite-button').classList.toggle('hidden', auth.mode !== 'pair' || !auth.keys.B || auth.actor !== 'A');
  $('#role-switch').classList.toggle('single', auth.mode !== 'solo');
  $('#mode-label').textContent = auth.mode === 'solo' ? '혼자 체험' : '두 사람 플레이';
  if (polling) clearInterval(polling);
  polling = setInterval(() => refresh(true), 1600);
  return refresh(false);
}
async function refresh(quiet = false) {
  if (!auth || busy) return;
  const identity = `${auth.session}:${auth.actor}`;
  try {
    const result = await request('/api/state?' + query());
    if (!auth || identity !== `${auth.session}:${auth.actor}` || busy) return;
    if (current && (result.generation < current.generation ||
        (result.generation === current.generation && result.turn < current.turn))) return;
    render(result);
  } catch (err) {
    if (!quiet) { notify(err.message); if (err.message.includes('권한')) showWelcome(); }
  }
}
function feedback(result) {
  const box = $('#feedback');
  box.classList.remove('hidden'); box.classList.toggle('failure', !result.valid || !result.effect);
  $('#feedback-title').textContent = result.valid && result.effect ? '행동 결과' : '다시 살펴보세요';
  $('#feedback-text').textContent = result.feedback;
}
async function act(action) {
  if (!auth || busy) return false;
  busy = true; const identity = `${auth.session}:${auth.actor}`;
  try {
    const result = await request('/api/action', 'POST', {...credentials(), action});
    if (!auth || identity !== `${auth.session}:${auth.actor}`) return false;
    feedback(result.result); render(result, true);
    return result.result.valid && result.result.effect;
  } catch (err) { notify(err.message); return false; }
  finally { busy = false; }
}
function render(data, force = false) {
  current = data;
  const signature = JSON.stringify([auth.actor, data.observation, data.timeline, data.turn]);
  if (!force && signature === lastState) return;
  lastState = signature;
  const o = data.observation, g = data.game;
  $('#sidebar-game').innerHTML = `${escapeHTML(g.title)}<span>${escapeHTML(g.subtitle)}</span>`;
  $('#chapter-label').textContent = `ROOM ${auth.actor}  /  ${g.subtitle.toUpperCase()}`;
  $('#area-title').textContent = displayName(o.area);
  $('#area-description').textContent = o.description;
  $('#room-badge').textContent = `ROOM ${auth.actor}`;
  $('#turn-count').textContent = String(data.turn).padStart(2, '0');
  $('#areas').innerHTML = o.areas.map((name, i) => `<button type="button" class="area-button ${name === o.area ? 'active' : ''}" data-area="${escapeHTML(name)}" ${name === o.area ? 'aria-current="location"' : ''}><span class="area-index">${String(i+1).padStart(2,'0')}</span><span>${escapeHTML(displayName(name))}</span><span class="area-arrow">→</span></button>`).join('');
  $('#object-count').textContent = `${String(o.objects.length).padStart(2,'0')} OBJECTS`;
  $('#objects').innerHTML = o.objects.map(item => `<button type="button" class="object-card" data-object="${escapeHTML(item.name)}"><span class="object-card-top"><span class="object-icon">${escapeHTML(objectIcon(item.name))}</span><span class="object-type">${item.collectible ? 'COLLECTIBLE' : 'OBJECT'}</span></span><h3>${escapeHTML(displayName(item.name))}</h3><p>${escapeHTML(item.description)}</p><span class="object-card-bottom">자세히 살펴보기 ↗</span></button>`).join('');
  $('#empty-area').classList.toggle('hidden', o.objects.length > 0);
  $('#inventory-count').textContent = o.inventory.length;
  $('#inventory').innerHTML = o.inventory.map(item => `<button type="button" class="inventory-item" data-inventory="${escapeHTML(item.name)}"><span>${escapeHTML(objectIcon(item.name))}</span>${escapeHTML(displayName(item.name))} ↗</button>`).join('');
  $('#empty-inventory').classList.toggle('hidden', o.inventory.length > 0);
  $('#role-avatar').textContent = auth.actor;
  $('#role-title').textContent = `당신은 ${auth.actor} 방에 있어요`;
  $('#role-exit').textContent = o.own_exit_open ? '팀 탈출에 성공했어요' : '팀 탈출 장치를 찾아보세요';
  $$('#role-switch button').forEach(btn => {btn.classList.toggle('active', btn.dataset.role === auth.actor); btn.setAttribute('aria-pressed', String(btn.dataset.role === auth.actor));});
  $('#success-banner').classList.toggle('hidden', !o.team_success);
  renderMessages(data.timeline); renderActivity(data.timeline);
}
function renderMessages(timeline) {
  const container = $('#messages');
  const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
  const messages = timeline.filter(e => e.kind === 'message' || (e.kind === 'own' && e.action.type === 'send'));
  container.innerHTML = messages.length ? messages.map(m => {
    const mine = m.kind === 'own';
    return `<div class="message ${mine ? 'mine' : 'theirs'}"><span class="message-label">${mine ? '나' : '파트너'} · ${m.turn}번째 행동</span>${escapeHTML(mine ? m.action.message : m.text)}</div>`;
  }).join('') : '<div class="message-empty">아직 주고받은 메시지가 없어요.<br>발견한 것을 파트너와 나눠보세요.</div>';
  if (atBottom) container.scrollTop = container.scrollHeight;
}
function actionText(action) {
  const n = (x) => displayName(x);
  switch (action.type) {
    case 'move': return `${n(action.target)}(으)로 이동`;
    case 'click': return `${n(action.target)} 살펴보기 / 조작`;
    case 'apply': return `${n(action.tool)} → ${n(action.target)} 사용`;
    case 'input': return `${n(action.target)}에 값 입력`;
    case 'craft': return `${n(action.first)} + ${n(action.second)} 조합`;
    case 'send': return '파트너에게 메시지 전달';
    case 'pass': return `${n(action.tool)} 해치로 전달`;
    case 'wait': return '잠시 기다리기';
    default: return '주변 살펴보기';
  }
}
function renderActivity(timeline) {
  const entries = timeline.filter(e => e.kind === 'own' || e.kind === 'received').slice(-12).reverse();
  $('#activity').innerHTML = entries.length ? entries.map(e => `<div class="activity-entry"><span class="activity-dot">${e.kind === 'received' ? '↓' : '✳'}</span><p>${escapeHTML(e.kind === 'received' ? `파트너에게 ${displayName(e.tool)} 받음` : actionText(e.action))}<br><small>${e.turn}번째 행동${e.kind === 'own' && (!e.valid || !e.effect) ? ' · 변화 없음' : ''}</small></p></div>`).join('') : '<p class="message-empty">아직 기록된 행동이 없습니다.</p>';
}

function showObject(name) {
  const item = current.observation.objects.find(o => o.name === name); if (!item) return;
  currentDialog = {type:'object', name};
  $('#dialog-kicker').textContent = item.collectible ? 'COLLECTIBLE OBJECT' : 'OBJECT DETAILS';
  $('#dialog-icon').textContent = objectIcon(item.name);
  $('#dialog-title').textContent = displayName(item.name);
  $('#dialog-description').textContent = item.description;
  const inventory = current.observation.inventory;
  let html = '<div class="dialog-actions">';
  if (item.collectible) html += '<button type="button" class="primary" data-action="click-object">물건 줍기 ↗</button>';
  else if (item.interactable) html += '<button type="button" class="primary" data-action="click-object">조작하기 ↗</button>';
  else html += '<span class="inline-note">현재 보이는 설명을 읽을 수 있습니다.</span>';
  html += '</div>';
  if (!item.collectible && item.interactable) {
    html += `<label class="field-label" for="input-value">이곳에 값 입력하기</label><div class="copy-row"><input class="field-input" id="input-value" placeholder="숫자 또는 문자" maxlength="128"><button type="button" class="outline-button" data-action="input-object">입력</button></div>`;
    if (inventory.length) html += `<label class="field-label" for="apply-tool">가진 물건 사용하기</label><select class="field-select" id="apply-tool">${inventory.map(x=>`<option value="${escapeHTML(x.name)}">${escapeHTML(displayName(x.name))}</option>`).join('')}</select><button type="button" class="primary dialog-submit" data-action="apply-object">선택한 물건 사용하기 →</button>`;
  }
  $('#dialog-content').innerHTML = html; openDialog('#detail-dialog');
}
function showInventory(name) {
  const item = current.observation.inventory.find(o => o.name === name); if (!item) return;
  currentDialog = {type:'inventory', name};
  $('#dialog-kicker').textContent = 'YOUR INVENTORY'; $('#dialog-icon').textContent = objectIcon(name);
  $('#dialog-title').textContent = displayName(name); $('#dialog-description').textContent = item.description;
  $('#dialog-content').innerHTML = '<div class="dialog-actions"><button type="button" class="primary" data-action="pass-item">해치로 파트너에게 보내기 ↗</button></div><p class="inline-note">전달하면 내 인벤토리에서 사라지고 파트너가 받습니다.</p>';
  openDialog('#detail-dialog');
}
function showCraft() {
  const inv = current.observation.inventory;
  if (inv.length < 2) return notify('조합하려면 물건이 두 개 이상 필요해요.');
  currentDialog = {type:'craft'};
  $('#dialog-kicker').textContent = 'COMBINE OBJECTS'; $('#dialog-icon').textContent = '＋';
  $('#dialog-title').textContent = '물건 조합하기';
  $('#dialog-description').textContent = '가진 두 물건을 골라 조합해 보세요. 조합할 수 없는 물건일 수도 있습니다.';
  const options = inv.map(x=>`<option value="${escapeHTML(x.name)}">${escapeHTML(displayName(x.name))}</option>`).join('');
  $('#dialog-content').innerHTML = `<label class="field-label" for="craft-first">첫 번째 물건</label><select class="field-select" id="craft-first">${options}</select><label class="field-label" for="craft-second">두 번째 물건</label><select class="field-select" id="craft-second">${options}</select><button type="button" class="primary dialog-submit" data-action="craft">조합해 보기 →</button>`;
  openDialog('#detail-dialog'); $('#craft-second').selectedIndex = 1;
}

$('#game-options').addEventListener('click', e => {const btn=e.target.closest('[data-game]'); if(btn){selectedGame=btn.dataset.game;renderGames();}});
$$('.mode-btn').forEach(btn => btn.addEventListener('click', () => {selectedMode=btn.dataset.mode; $$('.mode-btn').forEach(b=>b.classList.toggle('selected',b===btn));}));
$('#start-button').addEventListener('click', async () => {
  const btn=$('#start-button'); btn.disabled=true;
  try {
    const data=await request('/api/session','POST',{game:selectedGame});
    auth={session:data.session, actor:'A', keys:data.keys, mode:selectedMode};
    sessionStorage.setItem(STORE,JSON.stringify(auth)); await enterGame();
    if(selectedMode==='pair') showInvite();
  } catch(err) { notify(err.message); } finally { btn.disabled=false; }
});
$('#change-game').addEventListener('click', () => {if(confirm('현재 진행을 떠나 문제 선택 화면으로 이동할까요?')) showWelcome();});
$('#areas').addEventListener('click', e => {const b=e.target.closest('[data-area]'); if(b && b.dataset.area!==current.observation.area) act({type:'move',target:b.dataset.area});});
$('#objects').addEventListener('click', e => {const b=e.target.closest('[data-object]'); if(b) showObject(b.dataset.object);});
$('#inventory').addEventListener('click', e => {const b=e.target.closest('[data-inventory]'); if(b) showInventory(b.dataset.inventory);});
$('#craft-button').addEventListener('click', showCraft);
$('#close-feedback').addEventListener('click',()=>$('#feedback').classList.add('hidden'));
$$('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
$('#detail-dialog').addEventListener('close',()=>{currentDialog=null;});
$('#dialog-content').addEventListener('click', async e => {
  const action=e.target.closest('[data-action]')?.dataset.action; if(!action || !currentDialog) return;
  let requestAction;
  if(action==='click-object') requestAction={type:'click',target:currentDialog.name};
  if(action==='input-object') {const value=$('#input-value').value.trim(); if(!value)return notify('입력할 값을 적어주세요.'); requestAction={type:'input',target:currentDialog.name,value};}
  if(action==='apply-object') requestAction={type:'apply',target:currentDialog.name,tool:$('#apply-tool').value};
  if(action==='pass-item') requestAction={type:'pass',tool:currentDialog.name};
  if(action==='craft') {const first=$('#craft-first').value,second=$('#craft-second').value; if(first===second)return notify('서로 다른 두 물건을 선택해 주세요.'); requestAction={type:'craft',first,second};}
  if(requestAction) {closeDialog(); await act(requestAction);}
});
$('#message-form').addEventListener('submit',async e=>{e.preventDefault();const input=$('#message-input'),message=input.value.trim();if(!message)return; if(await act({type:'send',message}))input.value='';});
$('#message-input').addEventListener('keydown',e=>{if(e.key==='Enter' && !e.shiftKey && !e.isComposing){e.preventDefault();$('#message-form').requestSubmit();}});
$('#role-switch').addEventListener('click',async e=>{const btn=e.target.closest('[data-role]');if(!btn||busy||auth.mode!=='solo'||btn.dataset.role===auth.actor)return;drafts[auth.actor]=$('#message-input').value;auth.actor=btn.dataset.role;$('#message-input').value=drafts[auth.actor];sessionStorage.setItem(STORE,JSON.stringify(auth));current=null;lastState='';$('#feedback').classList.add('hidden');closeDialog();await refresh();});
function showInvite(){const url=new URL('/',location.origin);url.searchParams.set('session',auth.session);url.searchParams.set('actor','B');url.searchParams.set('key',auth.keys.B);$('#invite-link').value=url.toString();$('#copy-result').textContent='';openDialog('#invite-dialog');}
$('#invite-button').addEventListener('click',showInvite);
$('#copy-link').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#invite-link').value);$('#copy-result').textContent='링크를 복사했습니다.';}catch{$('#invite-link').select();$('#copy-result').textContent='링크를 선택했습니다. 직접 복사해 주세요.';}});
$('#reset-button').addEventListener('click',async()=>{if(busy||!confirm('양쪽 방의 진행과 기록을 모두 초기화할까요?'))return;busy=true;try{const data=await request('/api/reset','POST',credentials());current=null;lastState='';drafts={A:'',B:''};$('#message-input').value='';$('#feedback').classList.add('hidden');render(data,true);notify('처음부터 다시 시작합니다.');}catch(err){notify(err.message);}finally{busy=false;}});
$('#download-log').addEventListener('click',async()=>{try{const data=await request('/api/log','POST',credentials());const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`escape-room-${data.game}-${data.actor}.json`;link.click();URL.revokeObjectURL(url);}catch(err){notify(err.message);}});

async function init() {
  try {games=await request('/api/games');renderGames();}
  catch(err){notify('로컬 서버에 연결할 수 없습니다.');return;}
  const params=new URLSearchParams(location.search);
  if(params.has('session') && params.has('key') && ['A','B'].includes(params.get('actor'))) {
    const actor=params.get('actor'); auth={session:params.get('session'),actor,keys:{[actor]:params.get('key')},mode:'pair'};
    sessionStorage.setItem(STORE,JSON.stringify(auth));history.replaceState({},'','/');await enterGame();
  } else {
    try {auth=JSON.parse(sessionStorage.getItem(STORE));} catch {auth=null;}
    if(auth && auth.session && auth.keys?.[auth.actor]) await enterGame();
  }
}
init();

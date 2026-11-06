(()=>{'use strict';
const events=window.AGENDA_DATA||[], ids=window.AGENDA_PERSON_IDS||[], names=window.AGENDA_PEOPLE||[];
let member='all',view='pending';
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const owner=id=>names[ids.indexOf(id)]||'Outro membro';
const dateText=iso=>new Date(iso+':00').toLocaleDateString('pt-BR',{weekday:'long',day:'2-digit',month:'long'});
function formPost(url,confirmText){if(confirmText&&!confirm(confirmText))return;const f=document.createElement('form');f.method='post';f.action=url;const i=document.createElement('input');i.type='hidden';i.name='token';i.value=window.CSRF;f.append(i);document.body.append(f);f.submit()}
function render(){
 const search=$('search').value.trim().toLocaleLowerCase('pt-BR');const status=$('status-filter').value;
 const today=new Date().toLocaleDateString('sv-SE');const relevant=events.filter(e=>member==='all'||String(e.owner)===member);
 $('stat-open').textContent=relevant.filter(e=>!e.completed).length;
 $('stat-today').textContent=relevant.filter(e=>!e.completed&&e.start.slice(0,10)===today).length;
 $('stat-done').textContent=relevant.filter(e=>e.completed).length;
 $('count-all').textContent=events.filter(e=>!e.completed).length;
 ids.forEach(id=>{const el=$('count-'+id);if(el)el.textContent=events.filter(e=>!e.completed&&e.owner===id).length});
 const rows=relevant.filter(e=>(status==='all'||(status==='done'?e.completed:!e.completed))&&[e.title,e.description,e.category,e.location,owner(e.owner),e.date].some(v=>String(v).toLocaleLowerCase('pt-BR').includes(search))).sort((a,b)=>a.start.localeCompare(b.start));
 $('event-list').innerHTML='';$('empty').hidden=!!rows.length;
 let last='';for(const e of rows){const day=e.start.slice(0,10);if(day!==last){const heading=document.createElement('div');heading.className='date-group';heading.textContent=dateText(e.start);$('event-list').append(heading);last=day}
 const node=document.createElement('div');node.className='event'+(e.completed?' completed':'');node.innerHTML=`<div class="event-time">${esc(e.time)}</div><span class="event-line"></span><div class="event-main"><strong>${esc(e.title)}</strong><small>${esc(owner(e.owner))} · ${esc(e.category)}${e.location?' · '+esc(e.location):''}${e.description?' · '+esc(e.description):''}</small></div><span class="pill">${e.completed?'Concluído':'Pendente'}</span><div class="event-actions"><button class="mini-btn done" data-action="toggle" data-id="${e.id}">${e.completed?'↶ Reabrir':'✓ Concluir'}</button><button class="mini-btn" data-action="edit" data-id="${e.id}">Editar</button><button class="mini-btn" data-action="delete" data-id="${e.id}">Excluir</button></div>`;$('event-list').append(node)}
}
function openModal(id){$(id).hidden=false;document.body.style.overflow='hidden'}
function closeModal(id){$(id).hidden=true;document.body.style.overflow=''}
$('create-open').onclick=()=>{const f=$('event-form');f.reset();f.action='/events';$('modal-title').textContent='Novo compromisso';openModal('event-modal')};
$('settings-open').onclick=()=>openModal('settings-modal');document.querySelectorAll('[data-close]').forEach(x=>x.onclick=()=>closeModal(x.dataset.close));
document.querySelectorAll('.modal-backdrop').forEach(x=>x.addEventListener('click',e=>{if(e.target===x)closeModal(x.id)}));
document.querySelectorAll('.nav-btn').forEach(btn=>btn.onclick=()=>{view=btn.dataset.view;document.querySelectorAll('.nav-btn').forEach(x=>x.classList.toggle('active',x===btn));$('status-filter').value=view==='history'?'all':'pending';$('view-title').innerHTML=view==='history'?'Histórico <span>completo.</span>':'Nossa agenda <span>em dia.</span>';$('list-title').textContent=view==='history'?'Histórico e pesquisa':'Próximos compromissos';render()});
document.querySelectorAll('.member-link').forEach(btn=>btn.onclick=()=>{member=btn.dataset.member;document.querySelectorAll('.member-link').forEach(x=>x.classList.toggle('active',x===btn));render()});
$('search').oninput=render;$('status-filter').onchange=render;
$('event-list').addEventListener('click',e=>{const btn=e.target.closest('button[data-action]');if(!btn)return;const id=Number(btn.dataset.id),event=events.find(x=>x.id===id);if(!event)return;
 if(btn.dataset.action==='toggle')formPost('/events/'+id+'/toggle');
 if(btn.dataset.action==='delete')formPost('/events/'+id+'/delete','Excluir definitivamente este compromisso?');
 if(btn.dataset.action==='edit'){const f=$('event-form');f.action='/events/'+id+'/edit';$('modal-title').textContent='Editar compromisso';for(const [k,v] of Object.entries({title:event.title,description:event.description,start:event.start,end:event.end,owner_id:event.owner,category:event.category,location:event.location,remind_minutes:event.remind})){if(f.elements.namedItem(k))f.elements.namedItem(k).value=v}openModal('event-modal')}
 });
const today=new Date();$('today-label').textContent=today.toLocaleDateString('pt-BR',{weekday:'long',day:'2-digit',month:'long',year:'numeric'});render();
if('serviceWorker'in navigator)navigator.serviceWorker.register('/service-worker.js').catch(console.warn);
function keyToBytes(base64){const s=atob((base64+'='.repeat((4-base64.length%4)%4)).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(s,c=>c.charCodeAt(0))}
$('push-enable').onclick=async()=>{const info=$('push-info');try{if(!window.isSecureContext||!('serviceWorker'in navigator)||!('PushManager'in window))throw Error('Este dispositivo ou navegador não oferece suporte a notificações push.');if(!window.VAPID_PUBLIC)throw Error('Chaves VAPID não configuradas.');const permission=await Notification.requestPermission();if(permission!=='granted')throw Error('Permissão não concedida.');const worker=await navigator.serviceWorker.ready;let sub=await worker.pushManager.getSubscription();if(!sub)sub=await worker.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyToBytes(window.VAPID_PUBLIC)});const res=await fetch('/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':window.CSRF},body:JSON.stringify(sub)});if(!res.ok)throw Error('Não foi possível registrar este dispositivo.');info.textContent='✓ Notificações ativadas neste dispositivo.'}catch(err){info.textContent=err.message||'Não foi possível ativar as notificações.'}};
})();

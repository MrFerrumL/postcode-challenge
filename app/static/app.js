const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = value => value == null ? '—' : Number(value).toLocaleString('ru-RU',{maximumFractionDigits:1});
let state, activeTab = 'plan';
const titles = {plan:'План квартала',risks:'Риски и ограничения',people:'Карта компетенций',facts:'Факт спринта',data:'Данные и настройки',ml:'Прогноз ML'};
const statuses = {planned:'В плане',deferred:'Перенос',needs_input:'Нужны данные',done:'Завершено'};
function notice(text, success=false){$('notice').textContent=text; $('notice').className=success?'success':''; $('notice').hidden=false;}
async function api(path, body, isForm=false){
  const options = body === undefined ? {} : {method:'POST',body:isForm?body:JSON.stringify(body),headers:isForm?{}:{'Content-Type':'application/json'}};
  const response=await fetch(path, options); const payload=await response.json();
  if(!response.ok) throw new Error(typeof payload.detail==='string'?payload.detail:JSON.stringify(payload.detail));
  return payload;
}
async function action(work, message){
  document.querySelectorAll('button').forEach(b=>b.disabled=true);
  try {await work(); if(message) notice(message,true);} catch(e){notice(e.message);} finally {document.querySelectorAll('button').forEach(b=>b.disabled=false); if(state&&!state.empty) $('baseline').disabled=!!state.baseline;}
}
function table(headers,rows){return `<table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${headers.length}" class="muted">Нет записей</td></tr>`}</tbody></table>`;}
function options(el, values, first){const old=el.value;el.innerHTML=(first?`<option value="">${first}</option>`:'')+values.map(v=>`<option value="${escapeHTML(v)}">${escapeHTML(v)}</option>`).join('');if(values.includes(old))el.value=old;}
function showTab(tab){activeTab=tab;$('page-title').textContent=titles[tab];document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==`tab-${tab}`);document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));

function render(next){
 state=next;$('welcome').hidden=!state.empty;$('workspace').hidden=state.empty;
 $('scenario').innerHTML=state.scenarios.map(s=>`<option value="${escapeHTML(s.id)}">${escapeHTML(s.name)} · ${s.id.slice(0,5)}</option>`).join('');
 if(state.empty)return;$('scenario').value=state.id;
 const plan=state.plan, rows=plan.tasks;
 $('summary').innerHTML=[[rows.filter(t=>t.status==='planned').length,'задач в будущем плане'],[rows.filter(t=>['deferred','needs_input'].includes(t.status)).length,'задач с ограничениями'],[state.stars.engineers.length,'уникальных сотрудников'],[state.dataset.issues.length,'замечаний к данным']].map(([n,t])=>`<div><strong>${n}</strong><span>${t}</span></div>`).join('');
 $('period').textContent=`${new Date(plan.start_date+'T12:00').toLocaleDateString('ru-RU')} — ${new Date(plan.end_date+'T12:00').toLocaleDateString('ru-RU')}`;
 $('mode-note').textContent=(state.baseline?'Исходный план сохранён. ':'Черновик: подтвердите план перед загрузкой факта. ')+(plan.strict_skills?'Проверяются роли, часы и подтверждённые требования к стеку.':'Проверяются роли и часы. Требования к стеку заполнены не для всех задач.');
 $('baseline').textContent=state.baseline?'Исходный план сохранён':'Подтвердить исходный план';$('baseline').disabled=!!state.baseline;
 const teams=Object.keys(plan.capacities).sort();options($('team-filter'),teams,'Все команды');options($('people-team'),teams,'Все команды');
 $('loads').innerHTML=table(['Команда',...Array.from({length:6},(_,i)=>`Спринт ${i+1}`)],teams.map(team=>[escapeHTML(team),...Array.from({length:6},(_,i)=>{const l=plan.loads.find(x=>x.team===team&&x.sprint===i+1);return l?`${num(l.sp)} / ${num(l.capacity)}<div class="bar"><i style="width:${Math.min(100,l.capacity?l.sp/l.capacity*100:0)}%"></i></div>`:'<span class="muted">Закрыт</span>'})]));
 renderSchedule();renderPeople();renderBusFactor(state.id);renderDeferred(state.id);renderDiff(state.id);
 $('initiatives').innerHTML=plan.initiatives.map(i=>`<div class="card"><h3>${escapeHTML(i.id)}</h3><span class="chip ${i.feasible?'':'orange'}">${i.done?'Завершена':i.feasible?'Укладывается в прогноз':'Цель под риском'}</span><p>${i.planned_tasks} задач в будущем плане${i.blocked_tasks.length?` · ${i.blocked_tasks.length} с ограничениями`:''}</p></div>`).join('');
 renderAlerts();
 $('start-date').value=state.settings.start_date;$('start-date').disabled=!!state.baseline;$('strict-skills').checked=state.settings.strict_skills;
 $('issue-count').textContent=`${state.dataset.issues.length} замечаний`;
 $('issues').innerHTML=table(['Задача','Проверка'],state.dataset.issues.map(i=>[escapeHTML(i.task_id||'—'),escapeHTML(i.message)]));
 options($('edit-task'),state.dataset.tasks.filter(t=>t.status!=='Done').map(t=>t.id));renderTaskEditor();
 options($('availability-person'),state.stars.engineers.map(e=>e.id));options($('availability-sprint'),['1','2','3','4','5','6']);renderAvailability();
 const last=Math.max(0,...state.facts.map(f=>f.sprint));options($('fact-sprint'),Array.from(new Set([last,last+1].filter(s=>s>=1&&s<=6))).map(String));$('fact-sprint').value=String(Math.min(6,last+1));
 $('fact-hint').textContent=state.baseline?`Закрыто спринтов: ${last}. Можно исправить последний факт.`:'Сначала подтвердите исходный план.';
 renderMetrics();$('ml-result').innerHTML='';showTab(activeTab);
}
function renderSchedule(){
 const search=$('task-search').value.toLowerCase(),team=$('team-filter').value,mode=$('status-filter').value;
 const tasks=state.plan.tasks.filter(t=>(!team||t.team===team)&&(mode==='all'||mode==='open'&&t.status!=='done'||mode==='planned'&&t.status==='planned')&&`${t.task_id} ${t.title} ${t.initiative}`.toLowerCase().includes(search));
 $('schedule').innerHTML=`<table><thead><tr><th>Задача / объяснение</th>${[1,2,3,4,5,6].map(s=>`<th>Спринт ${s}</th>`).join('')}</tr></thead><tbody>${tasks.length?tasks.map(t=>`<tr><td class="task-cell"><b>${escapeHTML(t.task_id)}</b> <span class="small">${escapeHTML(t.team)}</span><p>${escapeHTML(t.title)}</p><span class="chip ${t.status==='deferred'?'orange':t.status==='needs_input'?'red':''}">${statuses[t.status]}</span><p>${escapeHTML(t.reason)}</p><button class="link" data-explain-task="${escapeHTML(t.task_id)}">Почему так?</button></td>${[1,2,3,4,5,6].map(s=>{const c=t.chunks.find(c=>c.sprint===s);return `<td>${c?`<div class="slot">${num(c.sp)} SP<small>${num(c.hours)} ч</small></div>`:'<span class="empty-slot">—</span>'}</td>`}).join('')}</tr>`).join(''):'<tr><td colspan="7" class="muted">Нет задач по выбранному фильтру. Посмотрите ограничения или измените фильтр.</td></tr>'}</tbody></table>`;
}
function renderPeople(){
 const team=$('people-team').value, search=$('skill-search').value.toLowerCase();
 $('people').innerHTML=state.stars.engineers.filter(e=>!team||e.assignments.some(a=>a.team===team)).map(e=>{
 const loads=[1,2,3,4,5,6].map(s=>num(state.plan.allocations.filter(a=>a.engineer_id===e.id&&a.sprint===s).reduce((n,a)=>n+a.hours,0)));
 return `<div class="card"><h3>${escapeHTML(e.id)} <span class="small">${escapeHTML(e.grade)}</span></h3><p>${escapeHTML(e.role)}</p><p>${e.assignments.map(a=>`${escapeHTML(a.team)} · ${num(a.rate)} ставки · ${num(a.hours_per_sprint)} ч`).join('<br>')}</p><p class="skills">${e.skills.map(escapeHTML).join(' · ')}</p><p class="small">План часов С1–С6: ${loads.join(' / ')}</p></div>`;}).join('');
 const factors=state.stars.skills.filter(s=>s.scope===(team||'Все команды')&&s.skill.includes(search));
 $('skills').innerHTML=table(['Навык','Bus Factor','Сотрудники','Требуется задачам'],factors.map(s=>[escapeHTML(s.skill),`<span class="chip ${s.bus_factor<2?'orange':''}">${s.bus_factor}</span>`,s.engineers.map(escapeHTML).join(', ')||'—',s.tasks.map(escapeHTML).join(', ')||'<span class="muted">Требования не заданы</span>']));
}
async function renderBusFactor(scenario){
 try {
  const report=await api('/api/bus-factor');
  if(state.id!==scenario)return;
  const critical=report.critical_skills.filter(s=>s.risk_level==='critical');
  $('bus-factor').hidden=!!critical.length;
  if(!critical.length)$('bus-factor').innerHTML='<p class="muted">Критических компетенций не найдено</p>';
  const card=s=>{
   const level=s.risk_level==='critical'?'red':s.risk_level==='high'?'orange':'yellow';
   const holder=s.holder_name||s.holder;
   const profile=s.holder_role?`${s.holder_role} · ${num(s.holder_rate)} ставки`:'роль и ставка не определены';
   const holderText=holder?`${holder} · ${profile}`:'Носитель не найден · роль и ставка не определены';
   const explain=s.affected_tasks.length?`<button class="link" data-explain-task="${escapeHTML(s.affected_tasks[0])}">Почему BF=1?</button>`:s.explanation?`<button class="link" data-explain-text="${escapeHTML(s.explanation)}" data-explain-title="${escapeHTML(s.skill)}">Почему BF=1?</button>`:'';
   return `<details class="bus-factor-card risk-${level}"><summary><b>${escapeHTML(s.skill)}</b><span class="chip">${s.affected_tasks.length} задач</span><span class="small">${escapeHTML(s.scope)}</span></summary><div class="bus-factor-body"><p>${escapeHTML(holderText)}</p><p>${escapeHTML(s.explanation)}</p>${s.affected_tasks.length?`<p>Затронуто задач: ${s.affected_tasks.length}</p><div class="task-chips scrollable">${s.affected_tasks.map(task=>`<span class="chip">${escapeHTML(task)}</span>`).join('')}</div>`:''}${s.affected_initiatives.length?`<p>Затронуто инициатив: ${s.affected_initiatives.length}</p><div class="task-chips">${s.affected_initiatives.map(initiative=>`<span class="chip">${escapeHTML(initiative)}</span>`).join('')}</div>`:''}${explain}</div></details>`;
  };
  for(const [category,id] of [['role_deficit','bus-factor-role-deficit'],['unique_skill','bus-factor-unique-skill'],['parttime','bus-factor-parttime']]){
   const items=report.critical_skills.filter(s=>s.risk_category===category);$(id).hidden=!items.length;$(`${id}-items`).innerHTML=items.map(card).join('');
  }
  const potential=report.critical_skills.filter(s=>s.risk_category==='potential');
  $('bus-factor-potential-toggle').hidden=!potential.length;
  $('bus-factor-potential').innerHTML=potential.map(card).join('');
 } catch(e) {$('bus-factor').hidden=false;$('bus-factor').innerHTML='<p class="muted">Не удалось загрузить отчёт Bus Factor.</p>';}
}
function renderAlerts(){
 const alerts=state.alerts, summary=alerts.summary;
 const card=r=>`<div class="risk ${r.level}"><b>${escapeHTML(r.task_id||r.initiative||'Общее')}</b><div><span class="chip ${r.level==='red'?'red':r.level==='orange'?'orange':r.level==='gray'?'gray':''}">${escapeHTML(r.kind)}</span><p>${escapeHTML(r.message)}</p>${r.affected_tasks.length?`<p class="small">Затронутые задачи: ${r.affected_tasks.map(escapeHTML).join(', ')}</p>`:''}${r.affected_initiatives.length?`<p>${r.affected_initiatives.map(i=>`<span class="chip">${escapeHTML(i)}</span>`).join(' ')}</p>`:''}${r.task_id?`<button class="link" data-explain-task="${escapeHTML(r.task_id)}">Объяснить</button>`:''}</div></div>`;
 const group=(id,title,items)=>$(id).innerHTML=items.length?`<h3>${title} (${items.length})</h3>${items.map(card).join('')}`:'';
 $('alerts-summary').innerHTML=`<span>🔴 ${summary.critical}</span><span>🟡 ${summary.cascade}</span><span>🟠 ${summary.resource}</span><span>⚪ ${summary.info}</span>`;
 group('alerts-critical','🔴 Критические',alerts.critical);
 group('alerts-cascade','🟡 Каскадные',alerts.cascade);
 group('alerts-resource','🟠 Ресурсные',alerts.resource);
 $('alerts-info-toggle').hidden=!alerts.info.length;
 $('alerts-info').innerHTML=alerts.info.length?`<h3>⚪ Информационные (${alerts.info.length})</h3>${alerts.info.map(card).join('')}`:'';
 if(!Object.values(summary).some(Boolean))$('alerts-critical').innerHTML='<div class="panel">Ограничений в текущем плане не найдено.</div>';
}
async function renderDeferred(scenario){
 try {
  const report=await api('/api/deferred');
  if(state.id!==scenario)return;
  const total=report.summary.total;$('deferred-section').hidden=!total;
  if(!total)return;
  $('deferred-section').querySelector('h2').textContent=`Что предлагается перенести (${total} задач)`;
  const card=item=>`<div class="diff-item removed"><b>${escapeHTML(item.task_id)}</b> <span class="small">${escapeHTML(item.initiative)} · ${escapeHTML(item.team)}</span>${item.role?`<p>${escapeHTML(item.role)}${item.hours==null?'':` · ${num(item.hours)} ч`}</p>`:''}${item.required_skills?`<p class="small">Навыки: ${escapeHTML(item.required_skills)}</p>`:''}<p>${escapeHTML(item.reason)}</p><button class="link" data-explain-task="${escapeHTML(item.task_id)}">Объяснить</button></div>`;
  const groups=[['missing_role','🔴 Нет роли в команде'],['missing_skills','🔴 Нет навыков'],['horizon','🟠 Не вошло в горизонт'],['dependency','🟡 Зависит от незавершённых']];
  const other=[...report.unknown_skills,...report.unknown_remaining,...report.other];
  $('deferred').innerHTML=groups.filter(([code])=>report[code].length).map(([code,title])=>`<div class="deferred-group"><h3>${title} (${report[code].length})</h3>${report[code].map(card).join('')}</div>`).join('')+(other.length?`<div class="deferred-group"><h3>⚪ Нужны уточнения и прочее (${other.length})</h3>${other.map(card).join('')}</div>`:'');
 } catch(e) {$('deferred-section').hidden=false;$('deferred').innerHTML='<p class="muted">Не удалось загрузить список переносов.</p>';}
}
async function renderDiff(scenario){
 try {
  const report=await api('/api/diff');
  if(state.id!==scenario)return;
  if(report.empty){$('diff').innerHTML=`<div class="panel muted">${escapeHTML(report.message)}</div>`;return;}
  const card=(item,type,text)=>`<div class="diff-item ${type}"><b>${escapeHTML(item.task_id||item.id)}</b><p>${escapeHTML(text(item))}</p>${item.task_id?`<button class="link" data-explain-task="${escapeHTML(item.task_id)}">Объяснить</button>`:''}</div>`;
  const groups=[['shifts','🔀 Сдвинутые задачи','shift',item=>item.reason],['added','➕ Добавленные','added',item=>`${item.initiative}. ${item.reason}`],['removed','➖ Убранные','removed',item=>`${item.initiative}: ${item.old_status} → ${item.new_status}. ${item.reason}`],['initiatives','⚠️ Инициативы','initiative',item=>`${item.was_feasible?'Укладывалась':'Была под риском'} → ${item.now_feasible?'укладывается':'под угрозой'}. Заблокировано: ${item.blocked_tasks.join(', ')||'нет'}`]];
  const s=report.summary, content=groups.filter(([key])=>report[key].length).map(([key,title,type,text])=>`<div class="diff-group"><h3>${title} (${report[key].length})</h3>${report[key].map(item=>card(item,type,text)).join('')}</div>`).join('');
  $('diff').innerHTML=`<div class="diff-summary"><span>🔀 ${s.shifts}</span><span>➕ ${s.added}</span><span>➖ ${s.removed}</span><span>⚠️ ${s.initiatives_affected}</span></div><p class="muted">Пересчёт: ${escapeHTML(report.revision_reason)}</p>`+(content||'<p class="muted">Изменений после пересчёта не найдено.</p>');
 } catch(e) {$('diff').innerHTML='<p class="muted">Не удалось загрузить diff пересчёта.</p>';}
}
async function showExplain(taskId){
 const item=await api(`/api/explain/task/${encodeURIComponent(taskId)}`);
 showExplainContent(`${item.task_id} · ${item.title}`,item.explanation,item.suggested_actions,item.affected_tasks,item.affected_initiatives);
}
function showExplainContent(title,text,actions=[],tasks=[],initiatives=[]){
 $('explain-title').textContent=title;$('explain-text').textContent=text;
 $('explain-actions').innerHTML=actions.map(a=>`<li>${escapeHTML(a)}</li>`).join('')||'<li>Дальнейших действий не требуется.</li>';
 $('explain-affected').innerHTML=[tasks.length&&`Задачи: ${tasks.map(escapeHTML).join(', ')}`,initiatives.length&&`Инициативы: ${initiatives.map(i=>`<span class="chip">${escapeHTML(i)}</span>`).join(' ')}`].filter(Boolean).join('<br>')||'Нет связанных работ';
 $('explain-modal').hidden=false;
}
function closeExplain(){$('explain-modal').hidden=true;}
document.addEventListener('click',async event=>{
 const task=event.target.closest('[data-explain-task]'),text=event.target.closest('[data-explain-text]');
 if(task){try {await showExplain(task.dataset.explainTask);} catch(error){notice(error.message);}}
 if(text)showExplainContent(text.dataset.explainTitle,text.dataset.explainText);
 if(event.target.id==='explain-close'||event.target.id==='explain-modal')closeExplain();
});
function renderMetrics(){const m=state.metrics;if(!m.confirmed){$('metrics').textContent=m.message;return;}
 $('metrics').innerHTML=`<div class="form-row"><div><strong>${num(m.quarter_percent)}%</strong> квартального плана по факту (${m.completed_initiatives}/${m.baseline_initiatives} инициатив)</div><div class="muted">Прогноз: ${num(m.forecast_percent)}%</div></div><p class="muted">${escapeHTML(m.message)}</p>`+table(['Спринт','Исходный план, SP','Факт, SP','Say/Do'],m.sprints.map(s=>[s.sprint,num(s.planned_sp),num(s.actual_sp),s.percent===null?'—':num(s.percent)+'%']));}
function currentRemainder(task){
 const o=state.settings.overrides[task.id]||{};
 let hours=o.remaining_hours??Object.fromEntries(Object.entries(task.roles).map(([r,h])=>[r,Math.max(0,h-(task.spent[r]||0))]));
 let sp=o.remaining_sp??task.sp;
 for(const fact of [...state.facts].sort((a,b)=>a.sprint-b.sprint)){const f=fact.tasks.find(f=>f.task_id===task.id);if(f){hours=f.remaining_hours;sp=f.remaining_sp;}}
 return {hours,sp};
}
function renderTaskEditor(){
 const t=state.dataset.tasks.find(t=>t.id===$('edit-task').value);if(!t)return;
 const o=state.settings.overrides[t.id]||{}, rem=currentRemainder(t);
 const roles=[...new Set([...Object.keys(t.roles).filter(r=>t.roles[r]>0),...Object.keys(rem.hours)])].sort();
 $('edit-task-note').textContent=`${t.title} · ${t.team}. Расчётный остаток по ролям — допущение, пока вы его не уточните.`;
 $('edit-roles').innerHTML=table(['Роль','Остаток, ч','Требуемые навыки через запятую'],roles.map(r=>[escapeHTML(r),`<input class="role-hours" data-role="${escapeHTML(r)}" type="number" min="0" step="0.1" value="${rem.hours[r]||0}" aria-label="Часы ${escapeHTML(r)}">`,`<input class="role-skills" data-role="${escapeHTML(r)}" value="${escapeHTML((o.required_skills?.[r]||[]).join(', '))}" aria-label="Навыки ${escapeHTML(r)}">`]));
 $('remaining-sp').value=rem.sp;$('confirm-skills').checked=roles.every(r=>Object.hasOwn(o.required_skills||{},r));
}
function renderAvailability(){const id=$('availability-person').value,s=$('availability-sprint').value;$('availability-value').value=state.settings.availability[id]?.[s]??1;}
function settings(){return {...structuredClone(state.settings),start_date:$('start-date').value,strict_skills:$('strict-skills').checked};}
async function upload(input){if(!input.files[0])return;const form=new FormData();form.append('file',input.files[0]);await action(async()=>render(await api('/api/upload',form,true)),'Excel загружен в новый сценарий');input.value='';}
$('upload-file').onchange=()=>upload($('upload-file'));$('welcome-file').onchange=()=>upload($('welcome-file'));
$('demo').onclick=$('welcome-demo').onclick=()=>action(async()=>render(await api('/api/demo',{})),'Создан новый сценарий с исходными данными');
$('scenario').onchange=()=>action(async()=>render(await api('/api/scenarios/'+$('scenario').value,{})));
$('baseline').onclick=()=>action(async()=>render(await api('/api/baseline',{})),'Исходный план сохранён. Пересчёты не изменят базу KPI');
$('replan').onclick=()=>action(async()=>render(await api('/api/plan',settings())),'План пересчитан');
['task-search','team-filter','status-filter'].forEach(id=>$(id).oninput=renderSchedule);
['people-team','skill-search'].forEach(id=>$(id).oninput=renderPeople);
$('edit-task').onchange=renderTaskEditor;
['availability-person','availability-sprint'].forEach(id=>$(id).onchange=renderAvailability);
$('save-availability').onclick=()=>action(async()=>{const s=settings(),id=$('availability-person').value;s.availability[id]??={};s.availability[id][$('availability-sprint').value]=Number($('availability-value').value);render(await api('/api/plan',s));},'Доступность обновлена, будущие спринты пересчитаны');
$('save-task').onclick=()=>action(async()=>{
 const id=$('edit-task').value;if(state.facts.some(f=>f.tasks.some(t=>t.task_id===id)))throw new Error('Остаток этой задачи уже задан фактом. Исправьте последний факт спринта.');
 const s=settings(),o=s.overrides[id]??{required_skills:{}};
 o.remaining_hours=Object.fromEntries([...document.querySelectorAll('.role-hours')].map(e=>[e.dataset.role,Number(e.value)]));o.remaining_sp=Number($('remaining-sp').value);
 o.required_skills=$('confirm-skills').checked?Object.fromEntries([...document.querySelectorAll('.role-skills')].map(e=>[e.dataset.role,e.value.split(/,(?![^()]*\))/).map(s=>s.trim()).filter(Boolean)])) : {};
 s.overrides[id]=o;render(await api('/api/plan',s));},'Уточнение сохранено');
$('fact-template').onclick=()=>{
 const sprint=Number($('fact-sprint').value),existing=state.facts.find(f=>f.sprint===sprint);
 const tasks=state.plan.tasks.filter(t=>t.chunks.some(c=>c.sprint===sprint)).map(t=>{const source=state.dataset.tasks.find(x=>x.id===t.task_id),rem=currentRemainder(source);return {task_id:t.task_id,status:'InProgress',remaining_hours:rem.hours,remaining_sp:rem.sp,spent_hours:{}};});
 $('fact-json').value=JSON.stringify(existing||{sprint,tasks},null,2);
 notice('Форма подготовлена с прежними остатками. Замените их фактическими данными перед сохранением.',true);
};
$('save-fact').onclick=()=>action(async()=>{const fact=JSON.parse($('fact-json').value);render(await api('/api/facts',fact));},'Факт сохранён, оставшаяся часть плана пересчитана');
$('fact-file').onchange=()=>action(async()=>{const f=$('fact-file').files[0];if(f){const value=JSON.parse(await f.text());$('fact-json').value=JSON.stringify(value,null,2);}},'Файл прочитан. Проверьте данные и сохраните факт');
$('train-ml').onclick=()=>action(async()=>{const m=await api('/api/ml');$('ml-result').innerHTML=`<p>${escapeHTML(m.message)}</p><p>MAE модели: <b>${num(m.mae)}</b> SP · MAE среднего: <b>${num(m.baseline_mae)}</b> SP · проверено наблюдений: ${m.validation_n}</p>`+table(['Команда','История','Плановые SP для прогноза','Прогноз выполненных SP'],m.teams.map(t=>[escapeHTML(t.team),t.observations,num(t.planned_sp),num(t.predicted_sp)]));});
action(async()=>render(await api('/api/state')));

import {$,$$,el,api,busy,showError,toast,typeNames,field,check,button,formatTime,paginate,requireUser} from './common.js';

const params=new URLSearchParams(location.search);
const targetSurvey=params.get('survey');
let scope='mine',page=1,question=null,versions=[],selectedVersion=null,tab='content',editing=null,dirty=false,newContent=null,generation=0,detailGeneration=0,contentSaving=false;
const requestKeys=new Map();
const pendingSelections=new Map();
const uuid=()=>crypto.randomUUID();
const clone=value=>JSON.parse(JSON.stringify(value));
const keyFor=(operation,payload)=>{const key=operation+JSON.stringify(payload);if(!requestKeys.has(key))requestKeys.set(key,uuid());return {key,requestKey:requestKeys.get(key)};};
const apiId=id=>encodeURIComponent(id);
const path=id=>`/api/library-questions/${apiId(id)}`;
function defaultContent(type='single'){return {type,title:'',required:false,options:['single','multiple'].includes(type)?[{id:uuid(),label:'选项 1'},{id:uuid(),label:'选项 2'}]:[],validation:{}};}
function card(title,...children){return el('section',{class:'card library-card'},title?el('h3',{},title):null,...children);}
function note(text){return el('p',{class:'library-small-note'},text);}
function fail(error){showError($('#library-error'),error);$('#library-error').scrollIntoView({behavior:'smooth',block:'nearest'});}
function selected(){return versions.find(v=>v.id===selectedVersion);}
function selectableVersion(v){return v&&v.selectable!==false&&v.status!=='archived'&&question?.status!=='archived';}
function questionTitle(q){return q.title||q.workingContent?.title||'未命名题目';}
function tags(q){return q.bookmarkTags||q.tags||[];}
async function action(task,label='操作已完成'){try{await task();showError($('#library-error'),null);if(label)toast(label,'success');}catch(error){fail(error);}}
async function writeIdempotent(url,operation,payload){const {key,requestKey}=keyFor(operation,payload);const result=await api(url,{method:'POST',body:{...payload,requestKey}});requestKeys.delete(key);return result;}
async function saveBusy(btn,task){
  if(contentSaving)return;
  contentSaving=true;
  // Keep the form and question selection stable through both the write and
  // its reload, so a late keystroke or second save cannot be silently lost.
  const regions=[$('#main'),...$$('dialog[open]')].filter(Boolean);
  const previous=regions.map(node=>[node,node.inert,node.getAttribute('aria-busy')]);
  regions.forEach(node=>{node.inert=true;node.setAttribute('aria-busy','true');});
  try{return await busy(btn,task);}finally{
    previous.forEach(([node,inert,aria])=>{node.inert=inert;if(aria===null)node.removeAttribute('aria-busy');else node.setAttribute('aria-busy',aria);});
    contentSaving=false;
  }
}

function formFields(host,model,{onChange=()=>{},allowType=true}={}){
  const title=el('input',{value:model.title||'',maxlength:2000,required:true,placeholder:'例如：你的年龄是',oninput:e=>{model.title=e.target.value;onChange();}});
  const type=el('select',{disabled:!allowType,onchange:e=>{const oldTitle=model.title,required=model.required;Object.assign(model,defaultContent(e.target.value),{title:oldTitle,required});onChange();formFields(host,model,{onChange,allowType});}});
  for(const [value,label] of Object.entries(typeNames))type.append(el('option',{value,selected:value===model.type},label));
  host.replaceChildren(field('题目标题',title),el('div',{class:'library-field-grid'},field('题型',type),el('div',{style:'padding-top:25px'},check('此题必答',Boolean(model.required),e=>{model.required=e.target.checked;onChange();}))));
  model.validation??={};model.options??=[];
  if(['single','multiple'].includes(model.type)){
    const list=el('div',{class:'library-form-options'});
    model.options.forEach((option,index)=>list.append(el('div',{class:'library-form-option'},el('span',{class:`option-symbol ${model.type}`,'aria-hidden':'true'}),el('input',{value:option.label||'',maxlength:2000,'aria-label':`选项 ${index+1}`,oninput:e=>{option.label=e.target.value;onChange();}}),button('×',()=>{model.options.splice(index,1);onChange();formFields(host,model,{onChange,allowType});},'icon-btn danger',{'aria-label':`删除选项 ${index+1}`}))));
    host.append(el('p',{class:'hint'},'选项 ID 会保留，修改选项文字不会产生新的选项身份。'),list,button('＋ 添加选项',()=>{model.options.push({id:uuid(),label:`选项 ${model.options.length+1}`});onChange();formFields(host,model,{onChange,allowType});},'btn btn-small',{disabled:model.options.length>=20}));
  }
  function bound(label,name,{integer=false,numeric=false}={}){
    return field(label,el('input',{value:model.validation[name]??'',type:integer?'number':'text',min:integer?0:null,step:integer?1:null,inputmode:numeric?'decimal':null,placeholder:'不限制',oninput:e=>{const value=e.target.value;if(value==='')delete model.validation[name];else model.validation[name]=integer?Number(value):value.trim();onChange();}}));
  }
  if(model.type==='multiple')host.append(el('div',{class:'library-field-grid',style:'margin-top:20px'},bound('最少选择项数','minSelections',{integer:true}),bound('最多选择项数','maxSelections',{integer:true})),note('上下限相同表示恰好选择。最少项数大于0时，空答也不能通过。'));
  if(model.type==='text')host.append(el('div',{class:'library-field-grid'},bound('最少字数','minLength',{integer:true}),bound('最多字数','maxLength',{integer:true})),note('去除首尾空白并规范字符后按字数校验，最多2000字。'));
  if(model.type==='number')host.append(el('div',{class:'library-field-grid'},bound('最小值','minValue',{numeric:true}),bound('最大值','maxValue',{numeric:true})),check('只允许整数',Boolean(model.validation.integerOnly),e=>{model.validation.integerOnly=e.target.checked;onChange();}),note('上下界包含边界。保留十进制字符串，支持科学计数法。'));
}

function preview(content){
  if(!content)return el('p',{class:'muted'},'尚无正式版本，请先保存为新版本。');
  const box=el('div',{class:'library-content-preview'},el('strong',{},content.title||'未命名题目'),el('small',{},`${typeNames[content.type]||content.type} · ${content.required?'必答':'可选答'}`));
  if(content.options?.length)box.append(el('ul',{},content.options.map(o=>el('li',{},o.label))));
  const v=content.validation||{},limits=[];
  if(content.type==='number'){if(v.minValue!=null)limits.push(`最小 ${v.minValue}`);if(v.maxValue!=null)limits.push(`最大 ${v.maxValue}`);if(v.integerOnly)limits.push('仅整数');}
  if(content.type==='multiple'){if(v.minSelections!=null)limits.push(`至少${v.minSelections}项`);if(v.maxSelections!=null)limits.push(`最多${v.maxSelections}项`);}
  if(content.type==='text'){if(v.minLength!=null)limits.push(`至少${v.minLength}字`);if(v.maxLength!=null)limits.push(`最多${v.maxLength}字`);}
  if(limits.length)box.append(el('small',{},limits.join(' · ')));
  return box;
}

async function loadList(){
  const query=new URLSearchParams({scope,page:String(page),pageSize:'15',q:$('#library-query').value.trim(),tag:$('#library-tag').value.trim()});
  const token=++generation;
  try{
    const data=await api(`/api/library-questions?${query}`);if(token!==generation)return;
    $('#library-total').textContent=`共 ${data.total??data.questions?.length??0} 道题目`;
    const rows=data.questions||[];
    $('#library-list').replaceChildren(...rows.map(q=>{
      const item=button([],()=>openQuestion(q.id),`library-list-item ${question?.id===q.id?'is-selected':''}`);
      const meta=el('div',{class:'library-item-meta'},el('span',{class:'type-chip'},typeNames[q.type]||'题目'),q.status==='archived'?el('span',{class:'library-tag'},'已归档'):null,q.visibility==='public'?el('span',{},'公共'):null);
      item.append(meta,el('h3',{},questionTitle(q)),el('div',{class:'library-item-meta'},q.latestVersionNumber?`最新 v${q.latestVersionNumber}`:'仅编辑稿',q.hasUpdate||q.hasNewVersion?el('span',{class:'library-tag'},'有新版本'):null,...tags(q).map(t=>el('span',{class:'library-tag'},t))));
      return item;
    }));
    if(!rows.length)$('#library-list').append(el('div',{class:'card library-card'},el('p',{},'这里还没有题目'),note('可以创建题目、调整搜索条件，或查看共享与公共题目。')));
    $('#library-pagination').replaceChildren(paginate(page,15,data.total??rows.length,value=>{page=value;loadList();}));
  }catch(error){fail(error);$('#library-list').replaceChildren(el('p',{class:'muted'},'读取失败，请点击刷新重试。'));}
}

async function openQuestion(id,{preserveTab=false}={}){
  if(dirty&&!confirm('有尚未保存的编辑，确定切换题目吗？'))return;
  const token=++detailGeneration;
  try{
    const data=await api(path(id));
    const history=await api(path(id)+'/versions');if(token!==detailGeneration)return;
    question=data.question;versions=history.versions||[];
    if(!versions.some(v=>v.id===selectedVersion))selectedVersion=(question.canManage?(question.workingBaseVersionId||question.latestVersionId):question.selectedVersionId)||question.latestSelectableVersionId||versions[0]?.id||null;
    if(!versions.some(v=>v.id===selectedVersion))selectedVersion=versions[0]?.id||null;
    const workingBase=question.workingBaseVersionId||question.latestVersionId||null;
    editing=clone(question.canManage&&selectedVersion===workingBase?question.workingContent:(selected()?.content||question.workingContent||defaultContent(question.type)));dirty=false;
    if(!preserveTab)tab='content';
    const url=new URL(location.href);url.searchParams.set('question',id);historyReplace(url);
    renderDetail();loadList();
  }catch(error){fail(error);}
}
function historyReplace(url){window.history.replaceState({},'',url);}
function changeTab(value){if(dirty&&tab==='content'&&value!==tab&&!confirm('离开编辑区前尚未保存，继续保留当前内容并切换吗？'))return;tab=value;renderDetail();}
function versionSelect(){
  const select=el('select',{'aria-label':'选择题目版本',onchange:e=>{if(dirty&&!confirm('切换版本会替换尚未保存的编辑内容，继续吗？')){e.target.value=selectedVersion||'';return;}selectedVersion=e.target.value;editing=clone(selected()?.content||defaultContent());dirty=false;renderDetail();}});
  if(!versions.length)select.append(el('option',{value:''},'尚无正式版本'));
  for(const v of versions)select.append(el('option',{value:v.id,selected:v.id===selectedVersion},`v${v.versionNumber}${selectableVersion(v)?'':' · 已停止新选用'}`));
  return select;
}
function renderDetail(){
  if(!question)return;const target=$('#library-detail');target.replaceChildren();
  const heading=el('div',{class:'library-detail-header'},el('div',{},el('span',{class:'type-chip'},question.visibility==='public'?'公共题目':'私有 / 共享题目'),el('h2',{},questionTitle(question)),el('p',{class:'muted small'},`${question.status==='archived'?'来源已归档 · ':''}${question.latestVersionNumber?`最新正式版本 v${question.latestVersionNumber}`:'尚未生成正式版本'}`)));
  const actions=el('div',{class:'actions'},button('收藏与标签',bookmarkQuestion,'btn btn-small'));
  if(question.bookmarkRevision!=null)actions.append(button('移除收藏',()=>action(async()=>{await api(`/api/question-bookmarks/${apiId(question.id)}`,{method:'DELETE',body:{}});await openQuestion(question.id,{preserveTab:true});},'已移除收藏，题目与旧问卷保留'),'btn btn-small'));
  if(question.canManage)actions.append(button('归档题目',archiveQuestion,'btn btn-small btn-danger',{disabled:question.status==='archived'}));
  heading.append(actions);target.append(heading);
  const toolbar=el('div',{class:'library-version-toolbar'},versionSelect());
  if(targetSurvey)toolbar.append(button('选入当前问卷',chooseForSurvey,'btn btn-primary',{disabled:!selectableVersion(selected())}));
  else toolbar.append(button('选入我的问卷',chooseForSurvey,'btn btn-primary',{disabled:!selectableVersion(selected())}));
  toolbar.append(button('派生为我的题目',deriveQuestion,'btn',{disabled:!selectableVersion(selected())}));target.append(toolbar);
  target.append(el('div',{class:'library-tabs'},[['content','内容与编辑'],['history','版本历史'],['usage','使用情况'],['statistics','跨卷汇总'],...(question.canManage?[['sharing','共享管理']]:[])].map(([value,label])=>button(label,()=>changeTab(value),`btn ${tab===value?'is-active':''}`))));
  const body=el('div',{id:'library-tab-content'});target.append(body);
  if(tab==='content')renderContent(body);
  if(tab==='history')renderHistory(body);
  if(tab==='usage')loadUsage(body);
  if(tab==='statistics')loadStatistics(body);
  if(tab==='sharing')loadSharing(body);
}
function renderContent(body){
  if(question.canManage&&question.status!=='archived'){
    const fields=el('div'),reason=el('input',{id:'library-change-reason',maxlength:500,placeholder:'简要说明本次修改（可选）'});
    formFields(fields,editing,{onChange:()=>{dirty=true;$('#library-dirty-state').textContent='有未保存的编辑';}});
    const workingBase=question.workingBaseVersionId||question.latestVersionId||null;
    const historicalEdit=selectedVersion!==workingBase;
    const saveDraft=button('保存编辑稿',()=>saveWorking(saveDraft),'btn',{disabled:question.hasPublishedUsage||historicalEdit});
    const saveVersion=button(question.latestVersionNumber?'保存为新版本':'生成正式版本 v1',()=>saveFormal(saveVersion),'btn btn-primary');
    body.append(card('编辑题目',question.hasPublishedUsage?el('div',{class:'alert alert-info'},'这道题已被发布问卷使用。内容修改必须生成新版本，原问卷保持原内容。'):note(historicalEdit?'当前基于历史版本编辑，请保存为新版本以记录准确来源。':'编辑稿可保存和继续修改；问卷只能选用明确的正式版本。'),fields,field('修改说明',reason),el('div',{class:'library-form-action'},saveDraft,saveVersion),el('p',{class:'hint',id:'library-dirty-state'},'编辑内容尚未提交，不会影响已选用问卷。')));
  }else body.append(card('选定版本内容',preview(selected()?.content)));
  body.append(card('当前使用的内容',preview(selected()?.content),note('问卷选用时固化此版本快照。来源随后修改、归档或撤回共享，不会自动替换已有内容。')));
  body.append(card('来源关系',el('div',{class:'library-source-box'},`题目身份：${question.id}`,el('br'),`来源根：${question.rootQuestionId||question.id}`,el('br'),`当前版本：${selectedVersion||'尚无正式版本'}`),note('来源相同只说明派生关系，不代表有访问权或可自动合并统计。')));
}
async function saveWorking(btn){await saveBusy(btn,()=>action(async()=>{await api(path(question.id)+'/working-content',{method:'POST',body:{revision:question.revision,content:editing}});dirty=false;await openQuestion(question.id,{preserveTab:true});},'编辑稿已保存，版本号未推进'));}
async function saveFormal(btn){
  await saveBusy(btn,()=>action(async()=>{const data=await writeIdempotent(path(question.id)+'/versions','version:'+question.id,{revision:question.revision,sourceVersionId:selectedVersion||null,content:editing,reason:$('#library-change-reason')?.value.trim()||''});selectedVersion=data.version?.id||data.question?.latestVersionId||null;dirty=false;await openQuestion(question.id,{preserveTab:true});},'正式版本已保存，既有问卷保持原版本'));
}
function renderHistory(body){
  const box=card('版本历史',note('每个正式版本独立保留。恢复旧内容会创建新版本，不覆盖中间历史。'));
  if(!versions.length)box.append(el('p',{class:'muted'},'尚无正式版本。'));
  versions.forEach(v=>{
    const info=el('div',{},el('strong',{},`v${v.versionNumber}${v.selectable===false?' · 已停止新选用':''}`),el('p',{},v.content?.title||''),el('p',{},v.changeReason||v.reason||'未填写修改说明'),v.createdAt?el('p',{},formatTime(v.createdAt)):null,v.derivedFromVersionId?el('p',{class:'library-history-source'},`直接来源版本：${v.derivedFromVersionId}`):null);
    const controls=el('div',{class:'actions'},button('查看',()=>{selectedVersion=v.id;editing=clone(v.content);tab='content';dirty=false;renderDetail();},'btn btn-small'));
    if(question.canManage&&question.status!=='archived'){
      controls.append(button('恢复为新版',()=>action(async()=>{if(!confirm(`从 v${v.versionNumber} 的内容生成新版本？现有历史与问卷都会保留。`))return;const data=await writeIdempotent(path(question.id)+'/restore','restore:'+question.id,{revision:question.revision,versionId:v.id});selectedVersion=data.version?.id||null;dirty=false;await openQuestion(question.id,{preserveTab:true});},'已从历史内容创建新版本'),'btn btn-small'));
      controls.append(button(v.selectable===false?'允许新选用':'停止新选用',()=>action(async()=>{await api(path(question.id)+`/versions/${apiId(v.id)}/availability`,{method:'POST',body:{revision:v.stateRevision??v.revision??question.revision,selectable:v.selectable===false}});await openQuestion(question.id,{preserveTab:true});},'版本可选状态已更新，原快照不变'),'btn btn-small'));
    }
    box.append(el('div',{class:'library-version-row'},info,controls));
  });body.append(box);
}
async function bookmarkQuestion(){await action(async()=>{const raw=prompt('个人标签，用逗号分隔。标签仅影响你自己的整理。',tags(question).join('，'));if(raw===null)return;const versionId=question.bookmarkRevision!=null&&!selectableVersion(selected())?(question.selectedVersionId||null):(selectedVersion||null);await api('/api/question-bookmarks',{method:'POST',body:{questionId:question.id,versionId,tags:raw.split(/[,，]/).map(x=>x.trim()).filter(Boolean)}});await openQuestion(question.id,{preserveTab:true});},'已保存收藏与个人标签');}
async function deriveQuestion(){await action(async()=>{const data=await writeIdempotent(path(question.id)+'/derive','derive:'+question.id,{versionId:selectedVersion});dirty=false;selectedVersion=null;scope='mine';updateScopeButtons();await openQuestion(data.question.id);},'已完整复制为你拥有的题目');}
async function archiveQuestion(){if(!confirm('归档后将停止新的选用，已使用的问卷和历史版本继续保留。确定归档？'))return;await action(async()=>{await api(path(question.id)+'/archive',{method:'POST',body:{revision:question.revision}});dirty=false;await openQuestion(question.id,{preserveTab:true});},'题目已归档');}

async function chooseForSurvey(){
  await action(async()=>{
    const version=selected();if(!selectableVersion(version))throw new Error('请选择仍可选用的正式版本。');
    let sid=targetSurvey;
    if(!sid){
      const data=await api('/api/surveys?pageSize=100');const drafts=(data.surveys||[]).filter(s=>s.status==='draft');
      if(!drafts.length)throw new Error('你还没有草稿问卷，请先到「我的问卷」创建一份。');
      sid=await chooseDialog('选入哪份草稿问卷？',drafts.map(s=>({id:s.id,label:s.title})));if(!sid)return;
    }
    const selectionKey=sid+':'+version.id;
    if(!pendingSelections.has(selectionKey)){const current=(await api(`/api/surveys/${apiId(sid)}`)).survey;pendingSelections.set(selectionKey,{revision:current.revision,versionId:version.id,requestKey:uuid()});}
    try{await api(`/api/surveys/${apiId(sid)}/library-instances`,{method:'POST',body:pendingSelections.get(selectionKey)});pendingSelections.delete(selectionKey);}catch(error){if(error.status===409)pendingSelections.delete(selectionKey);throw error;}
    if(targetSurvey)location.assign(`/surveys/${apiId(sid)}/edit`);
  },'已把明确版本选入问卷');
}
function chooseDialog(title,items){
  return new Promise(resolve=>{let result=null;const dialog=el('dialog',{class:'modal'}),select=el('select',{'aria-label':title},items.map(item=>el('option',{value:item.id},item.label)));dialog.append(el('div',{class:'modal-heading'},el('h2',{},title)),field('草稿问卷',select),el('div',{class:'modal-actions'},button('取消',()=>dialog.close()),button('确认选用',()=>{result=select.value;dialog.close();},'btn btn-primary')));dialog.addEventListener('close',()=>{dialog.remove();resolve(result);},{once:true});document.body.append(dialog);dialog.showModal();});
}
async function loadUsage(body,usageScope=selectedVersion?'version':'question'){
  body.append(el('div',{class:'loading-state'},'正在读取使用情况…'));
  try{
    const data=await api(path(question.id)+`/usage?scope=${usageScope}${usageScope==='version'&&selectedVersion?'&versionId='+apiId(selectedVersion):''}`);if(tab!=='usage')return;body.replaceChildren();
    const scopeSelect=el('select',{'aria-label':'使用情况范围',onchange:event=>loadUsage(body,event.target.value)});
    [['version','当前精确版本'],['question','本题的所有版本'],['root','我可见的同源题目']].forEach(([value,label])=>scopeSelect.append(el('option',{value,selected:value===usageScope,disabled:value==='version'&&!selectedVersion},label)));
    body.append(field('使用情况范围',scopeSelect),note('明细始终只列本人问卷。同源范围只包含你有权读取的题目；他人累计数仅针对你有权维护的题目，来源相同不会扩大权限。'));
    const usage=data.usage||data,rows=usage.usages||usage.surveys||[];const box=card(usageScope==='root'?'可见同源题在我的问卷中的使用':'我的问卷使用情况',note('这里只显示你有权管理的问卷。相同问卷的多个实例可能分别列出。'));
    if(!rows.length)box.append(el('p',{class:'muted'},'尚未在你的问卷中使用此版本。'));
    rows.forEach(row=>box.append(el('div',{class:'library-version-row'},el('div',{},el('strong',{},row.title||row.surveyTitle||'我的问卷'),el('p',{},[row.status,row.instanceId?`实例 ${row.instanceId}`:'',row.currentInstances!=null?`${Array.isArray(row.currentInstances)?row.currentInstances.length:row.currentInstances} 个当前实例`:(row.isCurrent===false?'历史使用':'当前使用'),row.responseCount!=null?`${row.responseCount} 份答卷`:''].filter(Boolean).join(' · '))),row.surveyId||row.id?el('a',{class:'btn btn-small',href:`/surveys/${apiId(row.surveyId||row.id)}/edit`},'打开问卷'):null)));
    const count=usage.otherHistoricalSurveyCount??usage.otherSurveyCount;
    if(count!==null&&count!==undefined)box.append(el('div',{class:'alert alert-info'},`另有 ${count} 份其他问卷曾使用${usageScope==='root'?'此范围内你可维护的题目':'此题'}。`),note(usage.coverageNote||usage.coverage||'累计范围为迁移时可追溯的存量及之后记录的使用。不显示他人的标题、所有者、时间或答案。'));
    body.append(box);
  }catch(error){body.replaceChildren(card('使用情况',el('p',{class:'muted'},error.message)));}
}
async function loadSharing(body){
  body.append(el('div',{class:'loading-state'},'正在读取共享权限…'));
  try{
    const data=await api(path(question.id)+'/grants');if(tab!=='sharing')return;body.replaceChildren();
    const username=el('input',{placeholder:'对方已注册的用户名',maxlength:100,'aria-label':'接收共享的用户名'});
    const share=button('授予使用权',()=>action(async()=>{await api(path(question.id)+'/grants',{method:'POST',body:{revision:question.revision,username:username.value.trim()}});await openQuestion(question.id,{preserveTab:true});},'已授予题目使用权'),'btn btn-primary');
    const box=card('共享管理',note('授权允许对方选用或派生正式版本，不允许修改原题或查看你的回答。撤回后，已取得的问卷快照继续有效。'),el('div',{class:'library-picker-row'},username,share));
    const grants=data.grants||[];if(!grants.length)box.append(note('尚未向其他用户授予定向使用权。'));
    grants.forEach(grant=>box.append(el('div',{class:'library-grant-row'},el('div',{},el('strong',{},grant.username||grant.granteeUsername||grant.granteeId),el('small',{class:'muted'},grant.active===false?' · 已撤回':' · 使用与派生')),button('撤回共享',()=>action(async()=>{if(!confirm('撤回后对方不能再获取源版本，但已有快照和个人副本会保留。继续？'))return;await api(path(question.id)+`/grants/${apiId(grant.id)}`,{method:'DELETE',body:{revision:question.revision}});await openQuestion(question.id,{preserveTab:true});},'共享已撤回'),'btn btn-small btn-danger',{disabled:grant.active===false}))));
    body.append(box);
  }catch(error){body.replaceChildren(card('共享管理',el('p',{class:'muted'},error.message)));}
}
function statsTable(headers,rows){return el('table',{class:'library-stats-table'},el('thead',{},el('tr',{},headers.map(h=>el('th',{},h)))),el('tbody',{},rows.map(row=>el('tr',{},row.map(value=>el('td',{},value??'—'))))));}
async function loadStatistics(body,statsPage=1){
  if(!selectedVersion){body.replaceChildren(card('跨问卷汇总',note('请先生成或选择正式版本。')));return;}
  body.replaceChildren(el('div',{class:'loading-state'},'正在汇总本人的问卷…'));
  try{
    const data=await api(path(question.id)+`/statistics?versionId=${apiId(selectedVersion)}&page=${statsPage}&pageSize=20`);if(tab!=='statistics')return;const s=data.statistics||data;body.replaceChildren();
    const metrics=[['回答次数',s.answerCount],['有回答的答卷数',s.responseCount??s.submissionCount],['来源问卷数',s.surveyCount]];
    body.append(el('div',{class:'library-stats-grid'},metrics.map(([label,value])=>el('div',{class:'library-stat'},el('span',{},label),el('strong',{},value??0)))));
    const box=card(`v${s.versionNumber??selected()?.versionNumber??''} · 我的问卷汇总`,note('只汇总你拥有的问卷中这一精确版本的答案。同源变体、其他版本和他人的答卷不自动合并。'));
    if(s.type==='number')box.append(statsTable(['平均值','最小值','最大值'],[[s.average,s.min??s.minimum,s.max??s.maximum]]));
    if(s.type==='text')box.append(el('p',{},`不同填写内容：${s.distinctValueCount??s.distinctTextCount??0} 种`),note('此页仅提供汇总。需要查看填写内容，请进入本人单份问卷的统计。'));
    if(s.options?.length)box.append(statsTable(['选项','选择次数'],s.options.map(o=>[o.label,o.count])));
    if(s.distribution?.length)box.append(el('h3',{style:'margin-top:24px'},'数值频数分布'),statsTable(['数值','回答次数'],s.distribution.map(row=>[row.value,row.count])));
    const total=s.distributionTotal??s.distinctValueCount??0;if(s.type==='number'&&total>20)box.append(paginate(statsPage,20,total,value=>loadStatistics(body,value)));
    const bySurvey=s.bySurvey||s.perSurvey||[];
    if(bySurvey.length)box.append(el('h3',{style:'margin-top:24px'},'来源问卷'),statsTable(['问卷','回答次数','答卷数','本卷去重填写账号数'],bySurvey.map(row=>[row.title||row.surveyTitle||'我的问卷',row.answerCount,row.responseCount??row.submissionCount,row.respondentCount])));
    box.append(note('同卷同题的两个实例分别计回答，同一答卷只计一次。匿名填写仍按本卷稳定标识去重；不同问卷的去重人数不能相加成为跨卷独立人数。'),note('不提供跨卷合并答卷明细或导出。数字0是有效答案，空答和被跳过的题不作0处理。'));
    body.append(box);
  }catch(error){body.replaceChildren(card('跨问卷汇总',el('div',{class:'alert alert-error'},error.message),note(error.code==='MIGRATION_INCOMPLETE'?'旧数据尚未完成来源登记，请先按迁移说明完成核对。':'可在自己的单份问卷中继续查看既有统计。')));}
}
function updateScopeButtons(){$$('[data-library-scope]').forEach(btn=>btn.classList.toggle('is-active',btn.dataset.libraryScope===scope));}
$$('[data-library-scope]').forEach(btn=>btn.addEventListener('click',()=>{scope=btn.dataset.libraryScope;page=1;updateScopeButtons();loadList();}));
$('#library-search').addEventListener('submit',event=>{event.preventDefault();page=1;loadList();});
$('#library-refresh').addEventListener('click',()=>{loadList();if(question&&!dirty)openQuestion(question.id,{preserveTab:true});});
$('#library-rename-tag').addEventListener('click',()=>action(async()=>{const oldTag=prompt('要整理的个人标签名称：');if(!oldTag?.trim())return;const newTag=prompt('新标签名称（留空表示移除此标签，不删除题目）：',oldTag);if(newTag===null)return;await api('/api/question-tags',{method:'POST',body:{oldTag:oldTag.trim(),newTag:newTag.trim()||null}});await loadList();},'个人标签已整理'));
$('#library-create').addEventListener('click',()=>{newContent=defaultContent();showError($('#library-create-error'),null);formFields($('#library-create-fields'),newContent);$('#library-create-dialog').showModal();});
$('#library-create-form').addEventListener('submit',event=>{event.preventDefault();saveBusy($('#library-create-submit'),async()=>{try{const data=await writeIdempotent('/api/library-questions','create',{content:newContent,visibility:$('#library-create-visibility').value});$('#library-create-dialog').close();dirty=false;selectedVersion=null;scope='mine';updateScopeButtons();await openQuestion(data.question.id);toast('编辑稿已保存，接下来可生成正式版本','success');}catch(error){showError($('#library-create-error'),error);}});});
$('#library-create-dialog').addEventListener('cancel',event=>{if(contentSaving)event.preventDefault();});
window.addEventListener('beforeunload',event=>{if(dirty||contentSaving){event.preventDefault();event.returnValue='';}});
async function init(){if(!await requireUser())return;if(targetSurvey){$('#library-picker-notice').hidden=false;$('#library-picker-notice').append(document.createTextNode('正在为问卷选题。选择明确版本后，点击「选入当前问卷」。'),el('a',{href:`/surveys/${apiId(targetSurvey)}/edit`,style:'margin-left:12px'},'返回问卷'));}await loadList();if(params.get('question'))await openQuestion(params.get('question'));}
init();

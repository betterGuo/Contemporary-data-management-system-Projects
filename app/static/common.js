export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const typeNames = {single:'单选题',multiple:'多选题',text:'文本填空',number:'数字填空'};
export const statusNames = {draft:'草稿',published:'已发布',closed:'已关闭',expired:'已过期'};
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (key === 'checked' || key === 'disabled' || key === 'hidden' || key === 'required' || key === 'selected') node[key] = Boolean(value);
    else if (key === 'value') node.value = value;
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child !== undefined && child !== null && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
export function cookie(name) {
  const prefix = `${name}=`;
  const value = document.cookie.split(';').map(x => x.trim()).find(x => x.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : '';
}
export function safeNext(value = new URLSearchParams(location.search).get('next')) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/dashboard';
  try { const url = new URL(value, location.origin); return url.origin === location.origin ? url.pathname + url.search + url.hash : '/dashboard'; } catch { return '/dashboard'; }
}
export function loginRedirect() { location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`); }
export class ApiError extends Error {
  constructor(status, payload) { const error = payload?.error || {}; super(error.message || (status === 0 ? '无法连接服务器，请检查网络后重试。' : `请求未完成（${status}）`)); this.status=status; this.code=error.code; this.details=Array.isArray(error.details)?error.details:[]; }
}
export async function api(path, {method = 'GET', body, redirect = true, signal} = {}) {
  const headers = {'Accept':'application/json'};
  if (body !== undefined) headers['Content-Type']='application/json';
  if (!['GET','HEAD','OPTIONS'].includes(method.toUpperCase())) headers['X-CSRF-Token']=cookie('csrf_token');
  let response;
  try { response = await fetch(path, {method,headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body),signal}); } catch(error) { if(error.name==='AbortError') throw error; throw new ApiError(0); }
  let data; try { data=await response.json(); } catch { data={}; }
  if (!response.ok) { if(response.status===401 && redirect) loginRedirect(); throw new ApiError(response.status,data); }
  return data;
}
export function showError(target, error) {
  target.replaceChildren(); target.hidden=!error; if(!error) return;
  target.append(document.createTextNode(typeof error==='string'?error:error.message));
  if(error.details?.length) target.append(el('ul',{class:'validation-errors'},error.details.map(x=>el('li',{},[x.field,x.message].filter(Boolean).join('：')))));
}
export function toast(message, kind = '') { const item=el('div',{class:`toast ${kind}`,role:kind==='error'?'alert':'status'},message); $('#toast-stack').append(item); setTimeout(()=>item.remove(),kind==='error'?7000:4000); }
export async function busy(button, task, label='处理中…') { const before=button.textContent;button.disabled=true;button.textContent=label;try{return await task();}finally{button.disabled=false;button.textContent=before;} }
export function badge(status) {return el('span',{class:`badge badge-${status}`},statusNames[status]||status);}
export function formatTime(value, options={}) {if(!value)return '未设置';const d=new Date(value);if(Number.isNaN(d.getTime()))return '时间未知';return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,...options}).format(d);}
export function localDateTime(value) {if(!value)return '';const d=new Date(value);if(Number.isNaN(d.getTime()))return '';const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(d).map(x=>[x.type,x.value]));return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;}
export function fromLocalDateTime(value) {return value?new Date(`${value}+08:00`).toISOString():null;}
export function shareUrl(survey) {return `${location.origin}/survey/${encodeURIComponent(survey.publicId)}`;}
export async function copyText(value) {try{await navigator.clipboard.writeText(value);toast('分享链接已复制','success');}catch{const box=el('textarea',{value,style:'position:fixed;left:-9999px'});document.body.append(box);box.select();const ok=document.execCommand('copy');box.remove();if(ok)toast('分享链接已复制','success');else toast('暂时无法自动复制，请手动选中链接复制。');}}
export function field(label, control, hint) {if(typeof label==='string'&&control.matches('input,select,textarea')&&!control.hasAttribute('aria-label'))control.setAttribute('aria-label',label);return el('label',{class:'field'},el('span',{},label),control,hint?el('small',{},hint):null);}
export function check(label, checked, onChange, hint) {const control=el('input',{type:'checkbox',checked,onchange:onChange});return el('label',{class:'check-label'},control,el('span',{},label,hint?el('small',{},hint):null));}
export function button(label, onClick, className='btn', attrs={}) {return el('button',{type:'button',class:className,onclick:onClick,...attrs},label);}
export function paginate(page, pageSize, total, onPage) {return el('nav',{class:'pagination','aria-label':'分页'},button('← 上一页',()=>onPage(page-1),'btn btn-small',{disabled:page<=1}),el('span',{},`第 ${page} / ${Math.max(1,Math.ceil(total/pageSize))} 页`),button('下一页 →',()=>onPage(page+1),'btn btn-small',{disabled:page*pageSize>=total}));}
export const sessionReady = (async()=>{try{const data=await api('/api/auth/me',{redirect:false});const user=data.user;if(user){$('#nav-user').textContent=user.username;$('#nav-user').hidden=false;$('#logout').hidden=false;$$('[data-auth-only]').forEach(x=>x.hidden=false);return user;}}catch{}$('#nav-login').hidden=false;return null;})();
export async function requireUser() {const user=await sessionReady;if(!user)loginRedirect();return user;}
$('#logout')?.addEventListener('click',async()=>{try{await busy($('#logout'),()=>api('/api/auth/logout',{method:'POST',body:{}}));location.assign('/login');}catch(error){toast(error.message,'error');}});
$$('[data-close-dialog]').forEach(node=>node.addEventListener('click',()=>document.getElementById(node.dataset.closeDialog)?.close()));

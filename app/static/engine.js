// Decimal comparison keeps JSON decimal strings exact, including exponent notation.
export function decimalParts(value) {
  const raw=String(value);if(raw.length>8192)throw new Error('数字输入过长。');const input=trimWhitespace(raw);const match=/^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(input);if(!match)throw new Error('请输入有效数字。');
  const rawExponent=(match[5]??'0').replace(/^[+-]/,'').replace(/^0+/,'')||'0';if(rawExponent.length>5||BigInt(rawExponent)>16384n)throw new Error('数字指数超出支持范围。');
  const fraction=match[3]??match[4]??'';let digits=((match[2]??'')+fraction).replace(/^0+/,'');let exponent=BigInt(match[5]??'0')-BigInt(fraction.length);
  if(!digits)return {sign:0,digits:'0',exponent:0n};const zeros=/0+$/.exec(digits)?.[0].length??0;if(zeros){digits=digits.slice(0,-zeros);exponent+=BigInt(zeros);}if(digits.length>34||exponent< -6176n||exponent+BigInt(digits.length)-1n>6144n)throw new Error('数字超出 Decimal128 的精确表示范围。');return {sign:match[1]==='-'?-1:1,digits,exponent};
}
export function compareDecimal(a,b) {
  const x=decimalParts(a),y=decimalParts(b);if(x.sign!==y.sign)return x.sign>y.sign?1:-1;if(!x.sign)return 0;
  const xe=BigInt(x.digits.length)+x.exponent,ye=BigInt(y.digits.length)+y.exponent;if(xe!==ye)return (xe>ye?1:-1)*x.sign;
  const length=Math.max(x.digits.length,y.digits.length);const xd=x.digits.padEnd(length,'0'),yd=y.digits.padEnd(length,'0');return (xd===yd?0:xd>yd?1:-1)*x.sign;
}
export function trimWhitespace(value) {return String(value).replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,'');}
export function normalizeText(value) {return trimWhitespace(value??'').normalize('NFC');}
export function normalizeAnswer(q,value) {if(q.type==='text')return normalizeText(value);if(q.type==='number')return trimWhitespace(value??'');if(q.type==='multiple')return Array.isArray(value)?[...new Set(value)]:[];return value??'';}
export function emptyAnswer(q,value) {return value===undefined||value===null||value===''||(Array.isArray(value)&&!value.length);}
export function validateAnswer(q,raw) {
  const value=normalizeAnswer(q,raw),v=q.validation||{};const empty=emptyAnswer(q,value);
  if(empty){if(q.required)return '这道题为必答题，请填写后继续。';if(q.type==='multiple'&&v.minSelections>0)return `请至少选择 ${v.minSelections} 项。`;if(q.type==='text'&&v.minLength>0)return `请至少填写 ${v.minLength} 个字。`;return '';}
  if(q.type==='single'&&!q.options.some(o=>o.id===value))return '请选择一个有效选项。';
  if(q.type==='multiple'){if(value.some(id=>!q.options.some(o=>o.id===id)))return '答案包含无效选项。';if(v.minSelections!=null&&value.length<v.minSelections)return `请至少选择 ${v.minSelections} 项。`;if(v.maxSelections!=null&&value.length>v.maxSelections)return `最多可选择 ${v.maxSelections} 项。`;}
  if(q.type==='text'){const length=[...value].length;if(v.minLength!=null&&length<v.minLength)return `请至少填写 ${v.minLength} 个字，当前 ${length} 字。`;if(v.maxLength!=null&&length>v.maxLength)return `最多填写 ${v.maxLength} 个字，当前 ${length} 字。`;}
  if(q.type==='number'){try{const number=decimalParts(value);if(v.integerOnly&&number.sign&&number.exponent<0n)return '请输入整数。';if(v.minValue!=null&&compareDecimal(value,v.minValue)<0)return `请输入不小于 ${v.minValue} 的数字。`;if(v.maxValue!=null&&compareDecimal(value,v.maxValue)>0)return `请输入不大于 ${v.maxValue} 的数字。`;}catch(error){return error.message||'请输入有效数字，例如 12、3.5 或 -2。';}}
  return '';
}
export const ruleMatchers = new Map();
export function registerRuleMatcher(type, operator, matcher) {
  const key = `${type}:${operator}`;
  if (ruleMatchers.has(key) || typeof matcher !== 'function') throw new Error('跳转匹配器重复或无效');
  ruleMatchers.set(key, matcher);
}
registerRuleMatcher('single', 'eq', (answer, expected) => answer === expected);
registerRuleMatcher('multiple', 'containsAny', (answer, expected) => expected.some(id => answer.includes(id)));
registerRuleMatcher('multiple', 'containsAll', (answer, expected) => expected.every(id => answer.includes(id)));
registerRuleMatcher('multiple', 'equalsSet', (answer, expected) => new Set(answer).size === new Set(expected).size && expected.every(id => answer.includes(id)));
for (const [operator, compare] of Object.entries({eq: c => c === 0, lt: c => c < 0, lte: c => c <= 0, gt: c => c > 0, gte: c => c >= 0})) {
  registerRuleMatcher('number', operator, (answer, expected) => compare(compareDecimal(answer, expected)));
}
registerRuleMatcher('number', 'between', (answer, expected) => compareDecimal(answer, expected[0]) >= 0 && compareDecimal(answer, expected[1]) <= 0);
export function matchesRule(q, value, rule) {
  if (emptyAnswer(q, value)) return false;
  if (q.type === 'multiple' && (!Array.isArray(rule.value) || !rule.value.length)) return false;
  const matcher = ruleMatchers.get(`${q.type}:${rule.operator}`);
  if (!matcher) throw new Error('问卷包含不支持的跳转条件，请联系作者。');
  try { return Boolean(matcher(value, rule.value)); } catch { return false; }
}
export function nextQuestion(survey,index,value) {const q=survey.questions[index];const rule=(q.jumpRules||[]).find(rule=>matchesRule(q,value,rule));if(rule){if(rule.targetQuestionId==='END')return -1;const target=survey.questions.findIndex(x=>x.id===rule.targetQuestionId);if(target<=index)throw new Error('问卷的跳转目标无效，请联系作者。');return target;}return index+1<survey.questions.length?index+1:-1;}
export function questionHint(q) {const v=q.validation||{},parts=[];if(q.required)parts.push('必答');if(q.type==='multiple'){if(v.minSelections!=null&&v.minSelections===v.maxSelections)parts.push(`请选择恰好 ${v.minSelections} 项`);else{if(v.minSelections!=null)parts.push(`至少选择 ${v.minSelections} 项`);if(v.maxSelections!=null)parts.push(`最多选择 ${v.maxSelections} 项`);}}if(q.type==='text'){if(v.minLength!=null)parts.push(`最少 ${v.minLength} 字`);if(v.maxLength!=null)parts.push(`最多 ${v.maxLength} 字`);}if(q.type==='number'){if(v.integerOnly)parts.push('仅限整数');if(v.minValue!=null)parts.push(`最小值 ${v.minValue}`);if(v.maxValue!=null)parts.push(`最大值 ${v.maxValue}`);}return parts.join(' · ')||'选填，可留空继续';}

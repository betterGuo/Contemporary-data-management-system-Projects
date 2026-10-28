/* Three additional real form interactions, restricted to the preview server. */
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');
const base=process.env.STAGE2_BROWSER_URL||'http://127.0.0.1:8001';
const url=new URL(base);
if(!['127.0.0.1','localhost'].includes(url.hostname)||url.port!=='8001')throw new Error('Forms QA may only write to the isolated preview on port 8001.');
const root=path.resolve(__dirname,'..');
const out=path.resolve(process.env.STAGE2_FORMS_OUTPUT||path.join(root,'docs/evidence/stage2/browser-2026-10-26'));
fs.mkdirSync(out,{recursive:true});
const reportFile=path.join(out,'forms-ui.json');
if(fs.existsSync(reportFile))throw new Error('Existing form evidence must not be overwritten. Set STAGE2_FORMS_OUTPUT to a new directory.');
const username=process.env.STAGE2_FORMS_USER||JSON.parse(fs.readFileSync(path.join(root,'docs/evidence/stage2/browser-2026-10-26/attempt-4/browser-results.json'))).fixturePreparation[0].users[0];
const report={status:'running',startedAt:new Date().toISOString(),baseUrl:base,scope:`Isolated ${process.env.STAGE2_BROWSER_DATABASE||'preview'} database only`,username,methods:'Real UI login, create form, persistent draft save and formal version actions. No API writes used for fixtures.',cases:[],pageErrors:[],consoleErrors:[],httpErrors:[],screenshots:[]};
const save=()=>fs.writeFileSync(reportFile,JSON.stringify(report,null,2)+'\n');
let browser,page;
async function ready(){await page.waitForLoadState('networkidle');}
async function post(pathname,click){const waiting=page.waitForResponse(r=>new URL(r.url()).pathname===pathname&&r.request().method()==='POST').then(async r=>{const body=await r.json();assert.ok(r.ok(),JSON.stringify(body));return body;});await click();const result=await waiting;await ready();return result;}
async function screenshot(name){await page.screenshot({path:path.join(out,name),fullPage:true});report.screenshots.push(name);save();}
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-sandbox']});
  page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>report.pageErrors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')report.consoleErrors.push(message.text());});
  page.on('response',response=>{if(response.status()>=400)report.httpErrors.push({url:response.url(),status:response.status(),method:response.request().method()});});
  await page.goto(base+'/login');await page.locator('#username').fill(username);await page.locator('#password').fill(process.env.STAGE2_FORMS_PASSWORD||'SurveyQa2026!');await page.locator('#auth-submit').click();await page.waitForURL('**/dashboard');
  for(const kind of ['single','multiple','text']){
    await page.goto(base+'/library');await ready();await page.locator('#library-create').click();
    const dialog=page.locator('#library-create-dialog');
    await dialog.getByLabel('题型',{exact:true}).selectOption(kind);
    const title=`三题型表单验收 ${kind} ${Date.now().toString(36)}`;
    await dialog.getByLabel('题目标题',{exact:true}).fill(title);
    if(kind!=='text'){
      await dialog.getByRole('textbox',{name:'选项 1',exact:true}).fill('图书馆');
      await dialog.getByRole('textbox',{name:'选项 2',exact:true}).fill('安静的自习室');
      await dialog.getByLabel('此题必答',{exact:true}).check();
    }
    if(kind==='multiple'){
      await dialog.getByRole('button',{name:'＋ 添加选项',exact:true}).click();
      await dialog.getByRole('textbox',{name:'选项 3',exact:true}).fill('宿舍');
      await dialog.getByLabel('最少选择项数',{exact:true}).fill('1');
      await dialog.getByLabel('最多选择项数',{exact:true}).fill('2');
    }
    if(kind==='text'){
      await dialog.getByLabel('最少字数',{exact:true}).fill('2');
      await dialog.getByLabel('最多字数',{exact:true}).fill('100');
    }
    const created=await post('/api/library-questions',()=>page.locator('#library-create-submit').click());
    const question=created.question,qid=question.id;assert.equal(question.latestVersionNumber,0);assert.equal(question.workingContent.type,kind);
    await page.waitForURL(url=>url.searchParams.get('question')===qid);
    await page.waitForFunction(title=>document.querySelector('#library-tab-content input')?.value===title,title);
    let draft=question;
    const initialIds=question.workingContent.options.map(option=>option.id);
    if(kind!=='text'){
      assert.equal(new Set(initialIds).size,initialIds.length);
      assert.ok(initialIds.every(id=>typeof id==='string'&&id.length>0));
      assert.deepEqual(question.workingContent.options.map(option=>option.label),kind==='single'?['图书馆','安静的自习室']:['图书馆','安静的自习室','宿舍']);
      await page.locator('#library-tab-content').getByRole('textbox',{name:'选项 1',exact:true}).fill('校园图书馆');
      const previousContent=await page.locator('#library-tab-content').elementHandle();
      const saved=await post(`/api/library-questions/${qid}/working-content`,()=>page.getByRole('button',{name:'保存编辑稿',exact:true}).click());
      await page.waitForFunction(previous=>!previous.isConnected,previousContent);
      draft=saved.question;assert.equal(draft.latestVersionNumber,0);assert.deepEqual(draft.workingContent.options.map(option=>option.id),initialIds);assert.equal(draft.workingContent.options[0].label,'校园图书馆');
    }
    const previousContent=await page.locator('#library-tab-content').elementHandle();
    const formal=await post(`/api/library-questions/${qid}/versions`,()=>page.getByRole('button',{name:'生成正式版本 v1',exact:true}).click());
    await page.waitForFunction(previous=>!previous.isConnected,previousContent);
    assert.equal(formal.version.versionNumber,1);assert.equal(formal.version.content.type,kind);assert.equal(formal.version.content.title,title);
    assert.deepEqual(formal.version.content.options.map(option=>option.id),initialIds);
    if(kind!=='text')assert.equal(formal.version.content.options[0].label,'校园图书馆');
    if(kind==='multiple')assert.deepEqual(formal.version.content.validation,{minSelections:1,maxSelections:2});
    if(kind==='text')assert.deepEqual(formal.version.content.validation,{minLength:2,maxLength:100});
    await page.locator('.library-list-item.is-selected').getByText('最新 v1',{exact:true}).waitFor();
    report.cases.push({kind,status:'passed',questionId:qid,versionId:formal.version.id,versionNumber:1,content:formal.version.content,optionIdsPreservedAcrossDraftAndVersion:kind==='text'?null:true,note:'Created and saved through visible UI controls.'});
    await screenshot(`forms-${kind}-v1.png`);console.log(kind+' UI PASS');
  }
  report.expectedHttpErrors=report.httpErrors.filter(e=>e.status===401&&new URL(e.url).pathname==='/api/auth/me');
  report.unexpectedHttpErrors=report.httpErrors.filter(e=>!report.expectedHttpErrors.includes(e));
  report.unexpectedConsoleErrors=report.consoleErrors.filter(e=>!/Failed to load resource.*401/.test(e));
  assert.equal(report.pageErrors.length,0);assert.equal(report.unexpectedHttpErrors.length,0,JSON.stringify(report.unexpectedHttpErrors));assert.equal(report.unexpectedConsoleErrors.length,0,JSON.stringify(report.unexpectedConsoleErrors));report.status='passed';report.completedAt=new Date().toISOString();save();await browser.close();console.log(JSON.stringify({status:report.status,cases:report.cases.length,pageErrors:report.pageErrors.length,screenshots:report.screenshots.length}));
})().catch(async error=>{report.status='failed';report.error=error.stack;report.completedAt=new Date().toISOString();if(page)await screenshot('forms-failure.png').catch(()=>{});save();if(browser)await browser.close();console.error(error.stack);process.exitCode=1;});

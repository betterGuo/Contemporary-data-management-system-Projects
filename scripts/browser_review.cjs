#!/usr/bin/env node
/* Optional browser recheck. Dependencies: Playwright and an available Chromium.
 * Run from the project root: node scripts/browser_review.cjs
 * NODE_PATH can point to an existing directory containing playwright.
 * BROWSER_EXECUTABLE_PATH can select a local Chromium executable.
 * The running app defaults to http://127.0.0.1:8000 and seeded demo credentials.
 * Only login reaches a write endpoint. Survey and answer fixtures are GET-only.
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'docs/evidence/stage1/recheck-browser');
const origin = (process.env.BROWSER_REVIEW_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const username = process.env.BROWSER_REVIEW_USERNAME || 'demo_owner';
const password = process.env.BROWSER_REVIEW_PASSWORD || 'Survey2026!';
const python = process.env.BROWSER_REVIEW_PYTHON || (fs.existsSync(path.join(root, '.venv/bin/python')) ? path.join(root, '.venv/bin/python') : 'python3');
// This ID is a display fixture; no corresponding survey is created in MongoDB.
const surveyId = '000000000000000000000030';
const questionId = 'all';
fs.mkdirSync(evidence, { recursive: true });

function save(name, data) {
  fs.writeFileSync(path.join(evidence, name), JSON.stringify(data, null, 2) + '\n');
}

function runPython(source, input) {
  const result = spawnSync(python, ['-c', source], {
    cwd: root,
    input: JSON.stringify(input),
    encoding: 'utf8',
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr || 'Python oracle failed');
  return JSON.parse(result.stdout);
}

function databaseFingerprint() {
  return runPython(`
import hashlib, json
from bson import BSON
from pymongo import MongoClient
from app.config import Settings
settings = Settings()
client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
db = client[settings.mongodb_db]
result = {"database": settings.mongodb_db, "collections": {}}
for name in ("users", "surveys", "responses"):
    digest = hashlib.sha256()
    count = 0
    for document in db[name].find().sort("_id", 1):
        digest.update(BSON.encode(document))
        count += 1
    result["collections"][name] = {"count": count, "sha256": digest.hexdigest()}
client.close()
print(json.dumps(result))
`, null);
}

const cases = [
  { name: 'NFD single e + combining acute', value: 'e\u0301' },
  { name: 'NFC single accented e', value: '\u00e9' },
  { name: 'NFD pair normalizes to two code points', value: 'e\u0301e\u0301' },
  { name: 'NFC pair is exactly two code points', value: '\u00e9\u00e9' },
  { name: 'NFD accented e and Chinese', value: 'e\u0301中' },
  { name: 'Single emoji counts one code point', value: '😀' },
  { name: 'Two emoji count two code points', value: '😀😀' },
  { name: 'Emoji and Chinese count two', value: '😀中' },
  { name: 'Two Chinese characters meet both boundaries', value: '中文' },
  { name: 'One Chinese character is below minimum', value: '中' },
  { name: 'Three Chinese characters exceed maximum', value: '中文字' },
  { name: 'Leading and trailing Python Unicode whitespace', value: '\u0085\u001c\t中文\u3000\u2003\n' },
  { name: 'Only Unicode whitespace normalizes to empty', value: '\u0085\u001c\u3000' },
  { name: 'FEFF is preserved, as in Python str.strip', value: '\ufeff中' },
  { name: 'Emoji family counts seven code points', value: '👨‍👩‍👧‍👦' },
  { name: 'Keycap counts three code points', value: '1\ufe0f\u20e3' },
  { name: 'NFD ring and Chinese normalize to two', value: 'A\u030a中' },
  { name: 'Empty optional input still violates positive minimum', value: '' },
  { name: 'Interior whitespace remains part of length', value: '\u202f中 文\u3000' },
];

const oracle = runPython(`
import json, sys
from app.services.storage_adapters import normalize_text, DomainError
from app.services.answer_validator import normalize_answer
inputs = json.load(sys.stdin)
question = {"id": "unicode-oracle", "type": "text", "title": "Unicode length", "required": False, "options": [], "validation": {"minLength": 2, "maxLength": 2}, "jumpRules": []}
records = []
for item in inputs:
    normalized = normalize_text(item["value"])
    record = {**item, "normalized": normalized, "codePoints": len(normalized)}
    try:
        record["backendAnswer"] = normalize_answer(question, item["value"])
        record["backendAccepted"] = True
    except DomainError as error:
        record["backendAccepted"] = False
        record["backendError"] = {"code": error.code, "message": error.message}
    records.append(record)
print(json.dumps(records, ensure_ascii=False))
`, cases);
save('unicode-python-oracle.json', {
  source: 'Real Python normalize_text and normalize_answer imports, executed by the project Python interpreter.',
  constraints: { type: 'text', required: false, minLength: 2, maxLength: 2 },
  cases: oracle,
});

function surveyFixture() {
  return {
    survey: {
      id: surveyId, publicId: 'browser-fixture-only',
      title: 'Unicode 边界复核 · 独立 GET 展示夹具',
      description: '本页使用浏览器 GET 展示夹具，不在数据库创建问卷或答卷。',
      allowAnonymous: false, allowMultipleSubmissions: false,
      status: 'draft', effectiveStatus: 'draft', closesAt: null,
      revision: 1, definitionVersion: 1,
      questions: [{
        id: questionId, type: 'text', title: '请填写恰好 2 个 Unicode 码点',
        required: false, options: [], validation: { minLength: 2, maxLength: 2 }, jumpRules: [],
      }],
    },
    isPreview: true,
  };
}

function questionStatistics(updated, page = 1) {
  const count = updated ? 22 : 21;
  const start = (page - 1) * 20 + 1;
  const end = Math.min(page * 20, count);
  return {
    questionId, title: '数值分页一致性 · 独立 GET 展示夹具', type: 'number',
    answerCount: count, respondentCount: updated ? 12 : 11,
    unansweredCount: updated ? 1 : 0,
    average: updated ? '11.5' : '11', totalValues: count,
    page, pageSize: 20,
    values: Array.from({ length: Math.max(0, end - start + 1) }, (_, offset) => ({
      responseId: `fixture-${start + offset}`, value: String(start + offset),
      submittedAt: '2026-10-20T06:00:00+00:00',
    })),
  };
}

function statisticsFixture(updated) {
  return {
    statistics: {
      surveyId, title: '分页整卡刷新复核 · 独立 GET 展示夹具', definitionVersion: 1,
      submissionCount: updated ? 23 : 21, respondentCount: updated ? 13 : 11,
      questions: [questionStatistics(updated, 1), {
        questionId: 'second-text-question', title: '第二题 · 范围筛选复核', type: 'text',
        answerCount: 1, respondentCount: 1, unansweredCount: updated ? 22 : 20,
        average: null, totalValues: 1, page: 1, pageSize: 20,
        values: [{ responseId: 'text-fixture', value: '本题用于确认整卷显示两题。', submittedAt: '2026-10-20T06:00:00+00:00' }],
      }],
    },
  };
}

async function unicodeReview(page) {
  const records = [];
  for (const expected of oracle) {
    await page.goto(`${origin}/surveys/${surveyId}/preview`);
    await page.getByRole('button', { name: '开始填写 →' }).click();
    await page.locator('#answer-control').fill(expected.value);
    const displayedCount = await page.locator('#answer-count').innerText();
    assert.equal(displayedCount, `${expected.codePoints} 字`, expected.name);
    if (expected.name === 'Leading and trailing Python Unicode whitespace') {
      await page.screenshot({ path: path.join(evidence, '01-unicode-whitespace-count.png'), fullPage: true, animations: 'disabled' });
    }
    await page.locator('#next-question').click();
    const accepted = await page.locator('.review-card').count() > 0;
    assert.equal(accepted, expected.backendAccepted, expected.name);
    const record = { ...expected, browserDisplayedCount: displayedCount, browserAccepted: accepted };
    if (accepted) {
      record.browserNormalizedAnswer = await page.locator('.review-value').innerText();
      assert.equal(record.browserNormalizedAnswer, expected.backendAnswer, expected.name);
      if (expected.name === 'NFD accented e and Chinese') {
        await page.screenshot({ path: path.join(evidence, '02-unicode-nfd-normalized-review.png'), fullPage: true, animations: 'disabled' });
      }
      // This is preview completion; no response POST is sent.
      await page.locator('#submit-response').click();
      await page.getByRole('heading', { name: '填写流程已走通' }).waitFor();
    } else {
      record.browserError = await page.locator('#answer-error').innerText();
      assert.ok(record.browserError.length > 0);
    }
    records.push(record);
  }
  save('unicode-browser-results.json', {
    case: 'T30', result: 'PASS', count: records.length,
    boundary: 'Actual app preview HTML and static JavaScript; survey JSON is a GET display fixture. Python results come from real backend functions. No formal response submission.',
    cases: records,
  });
  return records.length;
}

async function readStatistics(page) {
  const card = page.locator('[id="stats-all"]');
  return {
    counts: await card.locator('.stats-counts').innerText(),
    average: await card.locator('.stats-average strong').innerText(),
    values: await card.locator('.response-table tbody tr td:first-child').allTextContents(),
    footer: await card.locator('.stats-footnote').last().innerText(),
    page: await card.locator('.pagination').innerText(),
    topMetrics: await page.locator('.metric-value').allTextContents(),
    wholeSurveyNotice: await page.locator('#statistics-updated').innerText(),
    questionNotice: await card.locator('p.muted.small').innerText(),
  };
}

async function statisticsReview(page) {
  await page.goto(`${origin}/surveys/${surveyId}/statistics`);
  await page.locator('[id="stats-all"] .response-table').waitFor();
  assert.equal(await page.locator('.stats-question').count(), 2);
  const before = await readStatistics(page);
  assert.match(before.counts, /有效回答 21 份/);
  assert.match(before.counts, /回答人数 11 人/);
  assert.match(before.counts, /未答 \/ 跳过 0 份/);
  assert.equal(before.average, '11');
  assert.equal(before.values.length, 20);
  await page.screenshot({ path: path.join(evidence, '03-statistics-before-page.png'), fullPage: true, animations: 'disabled' });

  await page.getByRole('button', { name: '下一页 →', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.stats-counts')?.textContent.includes('有效回答 22 份'));
  const after = await readStatistics(page);
  assert.match(after.counts, /有效回答 22 份/);
  assert.match(after.counts, /回答人数 12 人/);
  assert.match(after.counts, /未答 \/ 跳过 1 份/);
  assert.equal(after.average, '11.5');
  assert.deepEqual(after.values, ['21', '22']);
  assert.match(after.footer, /共 22 条有效回答/);
  assert.match(after.page, /第 2 \/ 2 页/);
  assert.deepEqual(after.topMetrics, before.topMetrics);
  assert.match(after.wholeSurveyNotice, /翻页会刷新对应题目/);
  assert.match(after.wholeSurveyNotice, /刷新统计.*更新整卷/);
  assert.match(after.questionNotice, /本题更新于/);
  await page.screenshot({ path: path.join(evidence, '04-statistics-after-page.png'), fullPage: true, animations: 'disabled' });

  // Switching view must retain the freshly fetched question, not stale summary data.
  await page.locator('#question-filter').selectOption(questionId);
  assert.equal(await page.locator('.stats-question').count(), 1);
  const filtered = await readStatistics(page);
  assert.equal(filtered.counts, after.counts);
  assert.equal(filtered.average, after.average);
  await page.screenshot({ path: path.join(evidence, '06-statistics-question-id-all-filtered.png'), fullPage: true, animations: 'disabled' });
  await page.locator('#question-filter').selectOption('');
  assert.equal(await page.locator('.stats-question').count(), 2);
  assert.equal((await readStatistics(page)).counts, after.counts);

  await page.locator('#refresh-statistics').click();
  await page.waitForFunction(() => document.querySelector('.metric-value')?.textContent === '23');
  const refreshed = await readStatistics(page);
  assert.deepEqual(refreshed.topMetrics, ['23', '13', '2']);
  assert.match(refreshed.counts, /有效回答 22 份/);
  assert.equal(refreshed.average, '11.5');
  assert.equal(refreshed.values.length, 20);
  await page.screenshot({ path: path.join(evidence, '05-statistics-whole-survey-refreshed.png'), fullPage: true, animations: 'disabled' });

  save('statistics-browser-results.json', {
    case: 'Statistics pagination complete-card refresh', result: 'PASS',
    boundary: 'GET display fixtures only: initial whole-survey snapshot has 21 submissions; updated question has 22 valid answers and one skipped answer, representing 23 latest submissions. No MongoDB content is inserted or updated.',
    assertions: [
      'One page response refreshes question answer count, respondent count, unanswered count, average, values and total together.',
      'A legitimate questionId=all selects exactly that question; the empty whole-survey sentinel returns both questions and retains latest data.',
      'Whole-survey snapshot stays unchanged on question pagination and refreshes only after the whole-survey refresh button.',
      'Both whole-survey and question update semantics are explained in the page.',
    ],
    before, afterPage: after, afterFilter: filtered, afterWholeSurveyRefresh: refreshed,
  });
}

async function main() {
  const before = databaseFingerprint();
  const errors = [];
  const contentWrites = [];
  const fixtureRequests = [];
  let wholeStatisticsRequests = 0;
  let browser;
  const summary = {
    generatedAt: new Date().toISOString(),
    boundary: 'Real browser, running app templates/static files, genuine Python oracle. Only survey/statistics GET data are display fixtures. Authentication can create one normal session; users/surveys/responses are unchanged.',
    databaseBefore: before,
  };
  try {
    const executablePath = process.env.BROWSER_EXECUTABLE_PATH || [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    ].find(candidate => fs.existsSync(candidate));
    browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
    const context = await browser.newContext({ viewport: { width: 1360, height: 960 } });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await context.route('**/api/**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET' && /^\/api\/(surveys|participation)(\/|$)/.test(url.pathname)) {
        contentWrites.push({ method: request.method(), path: url.pathname });
        await route.abort('blockedbyclient');
        return;
      }
      let data;
      if (url.pathname === `/api/surveys/${surveyId}/preview`) data = surveyFixture();
      if (url.pathname === `/api/surveys/${surveyId}/statistics`) data = statisticsFixture(wholeStatisticsRequests++ > 0);
      if (url.pathname === `/api/surveys/${surveyId}/questions/${questionId}/statistics`) {
        data = { statistics: questionStatistics(true, Number(url.searchParams.get('page') || 1)) };
      }
      if (data) {
        fixtureRequests.push({ method: 'GET', path: url.pathname + url.search });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
      } else await route.continue();
    });
    await page.goto(`${origin}/login`);
    await page.locator('#username').fill(username);
    await page.locator('#password').fill(password);
    await page.locator('#auth-submit').click();
    await page.waitForURL('**/dashboard');
    summary.unicodeCasesPassed = await unicodeReview(page);
    await statisticsReview(page);
    assert.deepEqual(errors, []);
    assert.deepEqual(contentWrites, []);
    summary.result = 'PASS';
  } catch (error) {
    summary.result = 'FAIL';
    summary.failure = error.stack || String(error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    summary.javascriptErrors = errors;
    summary.surveyOrResponseWriteRequests = contentWrites;
    summary.fixtureRequests = fixtureRequests;
    summary.databaseAfter = databaseFingerprint();
    summary.formalCollectionsUnchanged = JSON.stringify(summary.databaseBefore) === JSON.stringify(summary.databaseAfter);
    if (!summary.formalCollectionsUnchanged) {
      summary.result = 'FAIL';
      summary.failure = (summary.failure || '') + '\nFormal users/surveys/responses fingerprint changed during review.';
      process.exitCode = 1;
    }
    save('review-summary.json', summary);
    console.log(JSON.stringify({ result: summary.result, unicodeCasesPassed: summary.unicodeCasesPassed, javascriptErrors: errors.length, surveyOrResponseWriteRequests: contentWrites.length, formalCollectionsUnchanged: summary.formalCollectionsUnchanged, evidenceDirectory: path.relative(root, evidence), ...(summary.failure ? { failure: summary.failure } : {}) }, null, 2));
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });

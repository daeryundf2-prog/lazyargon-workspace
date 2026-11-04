#!/usr/bin/env node
/**
 * slop_guard.mjs — 보고서 문서의 AI 슬롭과 정리 문제를 쓰는 즉시 표시한다. 경고만 하고 막지 않는다.
 *
 * 사용자 결정(2026-11-04): 하이브리드 — 결정적 검토기가 위치를 표시하고, 밀도가 높을 때만
 * humanize-korean 구간 지정 모드로 그 줄만 고치도록 제안한다. 범위는 보고서 파일, 영어 패턴 포함.
 * 보고서 정리 항목(반복 안내문·요지 동어반복·본문 근거 번호·Bytes 병기·파일명 나열·괄호 뒤 띄어쓰기·
 * 벽돌 셀·자리표시·단정 표현)은 사용자가 후임에게 보낸 포렌식 보고서 수정 지시서(2026-11-04)에서 왔다.
 * 패턴 원본: scripts/slop_patterns.json. 인용·코드·표 행은 상투 표현 검사에서 뺀다(철칙 1).
 *
 *   PostToolUse: stdin 페이로드에서 쓴 파일을 찾아 검사 → stderr "[SLOP GUARD] WARN …", stdout {} , exit 0
 *   CLI:         node scripts/slop_guard.mjs --file <path>   → JSON 결과
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SPEC = JSON.parse(fs.readFileSync(path.join(HERE, 'slop_patterns.json'), 'utf8'));
const PATTERNS = SPEC.patterns.map((p) => ({ ...p, rx: new RegExp(p.re, 'gim') }));
const REPORT_NAME_RE = /보고서|감정서|의견서|소견서|초안|report|draft/i;
const TEXT_EXT_RE = /\.(?:md|markdown|txt|html?|json)$/i;
const MIN_WEIGHT = 3; // 이보다 적으면 조용히 넘긴다(한두 개는 사람 글에도 있다)
const SUGGEST_PER_1000 = 2; // 1천 자당 가중치가 이 이상이면 humanize-korean 구간 모드를 제안한다
const BRICK_CELL_CHARS = 300;

const HYGIENE_RULES = {
	'repeat-sentence': ['같은 문장 반복', '처음 나온 곳 1번만 남기고 지운다. 안내문·용어 박스는 1장 한 곳으로 모은다'],
	'summary-echo': ['요지·해설·상세 분석 동어반복', '요지는 결론 2~3문장, 해설은 상세 분석 도입과 합친다'],
	'inline-evidence-ref': ['본문 속 근거 번호', '#번호(근거 n행)는 표의 근거 열로 옮긴다. 표가 없으면 문장 끝에 (#번호)만'],
	'bytes-raw': ['Bytes 원단위 병기', "'약 22.07GB'처럼 큰 단위만 쓴다. 디스크 용량 표·0 Bytes 강조만 예외"],
	'filename-list': ['문장 속 파일명 3개 이상', "대표 1개 + '등 N개(세부는 아래 표)'로 줄인다"],
	'paren-spacing': ['괄호 뒤 띄어쓰기 누락', "')는2026' → ')는 2026'"],
	'brick-cell': [`표 한 칸 ${BRICK_CELL_CHARS}자 넘는 줄글`, '셀을 <br> 3줄 이내로 나누거나 별도 표로 뺀다'],
	'placeholder': ['미입력 자리표시', '값을 채우거나 자리표시를 지운다'],
	'stray-br': ['값 끝 <br> 태그', '이름·값 끝의 <br>을 지운다'],
	'overclaim': ['단정 표현', '확인된 사실과 미확인 범위를 나눠 쓴다(예: 열람 기록 확인, 실제 저장 여부는 미확인)'],
};
// 괄호 뒤 조사 다음에 띄어쓰기가 빠진 경우만 잡는다. (주)·(유) 같은 회사 표기와 '에서·로부터' 같은 겹조사는 뺀다.
const PAREN_GAP_RE = /(?<!\((?:주|유|사|재|株))\)(?:(?:은|는|이|가|을|를|의|에|에는|와|과|로|으로|까지|에서|에게|부터)(?=[0-9A-Za-z])|(?:는|은|을|를|의|에|로|까지|와|과)(?![서게도는만야라요써]|부터|까지)(?=[가-힣]{2})|(?=[0-9]))/;
const FILE_RE = /[^\s'"‘’“”,·()]+\.(?:xlsx?|csv|docx?|pptx?|pdf|hwpx?|md|txt|jpe?g|png|gif|zip|json|py|m?js)(?![A-Za-z0-9])/gi;
const INLINE_REF_RE = /#\d{3,}\s*\(\s*근거|근거E?\s*\d+\s*(?:~\s*\d+\s*)?행/;
const BYTES_RE = /\d{1,3}(?:,\d{3}){2,}\s*Bytes/i;
const PLACEHOLDER_RE = /\bTODO\b|\bTBD\b|입력하세요|입력\s*(?:\.\.\.|…)|\[입력|○○○/;
const OVERCLAIM_RE = /정황입니다|명백히|틀림없이|의도적으로/;

// 상투 표현 검사에서 뺄 줄·구간: 코드 블록, 인용 블록(>), 표 행(|), 인용부호 안, 인라인 코드.
function maskedLines(lines) {
	let inFence = false;
	return lines.map((line) => {
		if (/^\s*(?:```|~~~)/.test(line)) {
			inFence = !inFence;
			return '';
		}
		if (inFence || /^\s*>/.test(line) || /^\s*\|/.test(line)) return '';
		return line.replace(/`[^`]*`/g, ' ').replace(/"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|'[^'\n]{2,}'/g, ' ');
	});
}

const norm = (s) => s.replace(/[\s\p{P}\p{S}]/gu, '');
const numbers = (s) => new Set((s.match(/\d[\d,]*\d/g) || []).map((x) => x.replace(/,/g, '')));
function bigrams(s) {
	const t = norm(s);
	const out = new Set();
	for (let i = 0; i < t.length - 1; i++) out.add(t.slice(i, i + 2));
	return out;
}
function jaccard(a, b) {
	let n = 0;
	for (const x of a) if (b.has(x)) n++;
	return n / (a.size + b.size - n || 1);
}

export function hygiene(lines, extra = []) {
	const out = [...extra];
	const add = (id, line, excerpt) => out.push({ id, line, label: HYGIENE_RULES[id][0], fix: HYGIENE_RULES[id][1], excerpt: String(excerpt).trim().slice(0, 80) });
	const paragraphs = [];
	let para = null;
	const closePara = () => {
		if (para && norm(para.text).length >= 40) paragraphs.push(para);
		para = null;
	};
	const sentences = new Map();
	let inFence = false;
	lines.forEach((raw, i) => {
		const ln = i + 1;
		if (/^\s*(?:```|~~~)/.test(raw)) {
			inFence = !inFence;
			closePara();
			return;
		}
		if (inFence) return;
		const line = raw.replace(/`[^`]*`/g, ' ');
		if (PAREN_GAP_RE.test(line)) add('paren-spacing', ln, line);
		if (BYTES_RE.test(line)) add('bytes-raw', ln, line);
		if (PLACEHOLDER_RE.test(line)) add('placeholder', ln, line);
		if (/^\s*\|/.test(line)) {
			closePara();
			const cell = line.split('|').flatMap((c) => c.split(/<br\s*\/?>/i)).find((c) => c.replace(/<[^>]+>/g, '').trim().length > BRICK_CELL_CHARS);
			if (cell) add('brick-cell', ln, cell);
			return;
		}
		if (/^\s*>/.test(line) || /^\s*#/.test(line) || !line.trim()) {
			closePara();
			return;
		}
		if (INLINE_REF_RE.test(line)) add('inline-evidence-ref', ln, line);
		if ((line.match(FILE_RE) || []).length >= 3) add('filename-list', ln, line);
		if (OVERCLAIM_RE.test(line.replace(/"[^"\n]*"|“[^”\n]*”/g, ' '))) add('overclaim', ln, line);
		for (const s of line.split(/(?<=[.!?。])\s+/)) {
			const key = norm(s);
			if (key.length < 25) continue;
			const seen = sentences.get(key) || { lines: [], text: s };
			seen.lines.push(ln);
			sentences.set(key, seen);
		}
		if (!para) para = { line: ln, text: '' };
		para.text += `${line}\n`;
	});
	closePara();
	for (const { lines: at, text } of sentences.values()) {
		if (at.length >= 2) add('repeat-sentence', at[1], `${at.length}회 (L${at.join(', L')}): ${text}`);
	}
	paragraphs.forEach((p, i) => {
		for (const q of paragraphs.slice(i + 1, i + 3)) {
			const shared = [...numbers(p.text)].filter((n) => numbers(q.text).has(n));
			if (shared.length >= 2 && jaccard(bigrams(p.text), bigrams(q.text)) >= 0.25) {
				add('summary-echo', q.line, `L${p.line}과 같은 수치(${shared.slice(0, 4).join(', ')})를 다시 설명: ${q.text}`);
			}
		}
	});
	return out;
}

export function scan(text) {
	const lines = maskedLines(String(text || '').split(/\r?\n/));
	const chars = lines.join('').replace(/\s/g, '').length;
	const findings = [];
	lines.forEach((line, i) => {
		for (const p of PATTERNS) {
			p.rx.lastIndex = 0;
			const n = (line.match(p.rx) || []).length;
			if (n) findings.push({ id: p.id, line: i + 1, count: n, weight: p.weight * n, label: p.label, excerpt: line.trim().slice(0, 80) });
		}
	});
	const dashes = lines.join('\n').split('—').length - 1;
	if (chars && (dashes / chars) * 1000 > SPEC.em_dash_per_1000) {
		findings.push({ id: 'em-dash-density', line: 0, count: dashes, weight: 2, label: `em dash 과다 (1천 자당 ${((dashes / chars) * 1000).toFixed(1)}개)`, excerpt: '' });
	}
	const weight = findings.reduce((s, f) => s + f.weight, 0);
	const per1000 = chars ? Number(((weight / chars) * 1000).toFixed(2)) : 0;
	return { chars, weight, per1000, findings, suggest_rewrite: weight >= MIN_WEIGHT && per1000 >= SUGGEST_PER_1000 };
}

// HTML은 표 행을 '| a | b |' 줄로, 나머지는 문단 줄로 바꿔 마크다운과 같은 규칙으로 본다.
function htmlToText(raw) {
	const cell = (s) => s.replace(/<br\s*\/?>/gi, '<br>').replace(/<(?!br>)[^>]+>/g, '').replace(/\s+/g, ' ').trim();
	return raw
		.replace(/<(script|style)\b[\s\S]*?<\/\1>/gi, '')
		.replace(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi, (_, row) => `\n| ${[...row.matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((m) => cell(m[1])).join(' | ')} |\n`)
		.replace(/<br\s*\/?>|<\/(?:p|div|li|h[1-6]|blockquote|section)>/gi, '\n')
		.replace(/<(?!br>)[^>]+>/g, '')
		.replace(/&nbsp;/g, ' ')
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.replace(/&amp;/g, '&');
}

// JSON 원고(블록 id → 문자열)는 문자열 값만 줄로 꺼낸다. 'ph' 키는 미입력 자리표시다.
function jsonToText(raw, extra) {
	const lines = [];
	const flag = (id, excerpt) => extra.push({ id, line: 0, label: HYGIENE_RULES[id][0], fix: HYGIENE_RULES[id][1], excerpt: String(excerpt).slice(0, 80) });
	const walk = (v, key) => {
		if (typeof v === 'string') {
			if (key === 'ph') {
				if (v.trim()) flag('placeholder', `ph: ${v}`);
				return;
			}
			if (/<br\s*\/?>\s*$/i.test(v)) flag('stray-br', `${key}: ${v}`);
			lines.push(...v.split(/\r?\n/));
		} else if (Array.isArray(v)) v.forEach((x) => walk(x, key));
		else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) walk(x, k);
	};
	walk(JSON.parse(raw), '');
	return lines.join('\n');
}

export function scanReport(raw, file = 'x.md') {
	const extra = [];
	let text = raw;
	if (/\.html?$/i.test(file)) text = htmlToText(raw);
	else if (/\.json$/i.test(file)) {
		try {
			text = jsonToText(raw, extra);
		} catch {
			text = raw;
		}
	}
	return { ...scan(text), hygiene: hygiene(text.split(/\r?\n/), extra) };
}

function warning(file, res) {
	const parts = [`[SLOP GUARD] WARN — ${path.basename(file)}: AI 상투 표현 ${res.findings.length}곳 (1천 자당 ${res.per1000}) · 보고서 정리 ${res.hygiene.length}건`];
	if (res.weight >= MIN_WEIGHT) {
		const byLine = new Map();
		for (const f of res.findings) byLine.set(f.line, { labels: [...(byLine.get(f.line)?.labels || []), f.label], excerpt: f.excerpt });
		parts.push([...byLine].slice(0, 8).map(([ln, v]) => `- ${ln ? `L${ln} ` : ''}${v.labels.join(' · ')}${v.excerpt ? `\n    ${v.excerpt}` : ''}`).join('\n'));
		parts.push(
			res.suggest_rewrite
				? "상투 표현 밀도가 높다. 사용자에게 humanize-korean '구간 지정 모드'로 위 줄만 고칠지 물어라(인용·수치·고유명사는 그대로 둔다). 자동으로 고치지 않는다."
				: '상투 표현은 해당 문장만 자연스럽게 고칠지 판단하라. 인용·수치·고유명사는 그대로 둔다.',
		);
	}
	if (res.hygiene.length) {
		const byId = new Map();
		for (const h of res.hygiene) byId.set(h.id, [...(byId.get(h.id) || []), h]);
		parts.push('보고서 정리:');
		for (const hs of byId.values()) {
			const at = hs.filter((h) => h.line).map((h) => `L${h.line}`).slice(0, 6).join(', ');
			parts.push(`- ${hs[0].label} ${hs.length}건${at ? ` (${at})` : ''} → ${hs[0].fix}\n    ${hs[0].excerpt}`);
		}
		parts.push('보고서를 쓰는 중이면 위 정리 항목을 해당 줄에서 바로 고쳐라. 반복은 첫 번째만 남기고 지우며, 수치·인용·고유명사·날짜 값은 바꾸지 않는다.');
	}
	return `${parts.join('\n')}\n`;
}

function targetOf(payload) {
	const pools = [payload?.toolCall?.args, payload?.tool_input, payload?.toolInput, payload?.args];
	for (const a of pools) {
		if (!a || typeof a !== 'object') continue;
		for (const k of ['TargetFile', 'file_path', 'filePath', 'Path', 'path', 'AbsolutePath']) {
			if (typeof a[k] === 'string' && a[k]) return a[k];
		}
	}
	return '';
}

function hook() {
	let payload = {};
	try {
		payload = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
	} catch {
		payload = {};
	}
	const file = targetOf(payload);
	if (file && TEXT_EXT_RE.test(file) && REPORT_NAME_RE.test(path.basename(file)) && fs.existsSync(file)) {
		const res = scanReport(fs.readFileSync(file, 'utf8'), file);
		if (res.weight >= MIN_WEIGHT || res.hygiene.length) process.stderr.write(warning(file, res));
	}
	process.stdout.write('{}\n');
}

const isMain = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
const fileArg = process.argv.indexOf('--file');
if (isMain && fileArg >= 0) {
	const f = process.argv[fileArg + 1];
	process.stdout.write(`${JSON.stringify({ file: f, ...scanReport(fs.readFileSync(f, 'utf8'), f) }, null, 1)}\n`);
} else if (isMain) {
	hook();
}

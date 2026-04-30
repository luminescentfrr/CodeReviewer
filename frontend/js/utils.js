// utils.js — Shared utility functions for CodeReview AI frontend

function scoreColor(v) {
  return v >= 80 ? 'var(--green)' : v >= 60 ? 'var(--amber)' : 'var(--red)';
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function markdownToHtml(md) {
  if (!md) return '';
  let html = esc(md);
  html = html.replace(/```[\w]*\n([\s\S]*?)```/g, (_, c) => `<pre><code>${c}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/^---+$/gm, '<hr>');
  html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, s => `<ul>${s}</ul>`);
  html = html.replace(/(\|.+\|\n)+/g, tbl => {
    const rows = tbl.trim().split('\n').filter(r => !/^\|[-| ]+\|$/.test(r));
    const h = rows.map((r, i) => {
      const cells = r.split('|').filter((_,j,a) => j > 0 && j < a.length-1);
      const tag = i === 0 ? 'th' : 'td';
      return '<tr>' + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('') + '</tr>';
    }).join('');
    return `<table>${h}</table>`;
  });
  html = html.replace(/\n\n+/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/<p>(<h[1-4]>|<ul>|<ol>|<table>|<pre>|<code>|<blockquote>|<hr>)/g, '$1');
  html = html.replace(/(<\/h[1-4]>|<\/ul>|<\/ol>|<\/table>|<\/pre>|<\/code>|<\/blockquote>|<hr>)<\/p>/g, '$1');
  return html;
}

function highlightPython(code) {
  const keywords = new Set([
    'False','None','True','and','as','assert','async','await','break','class','continue','def','del',
    'elif','else','except','finally','for','from','global','if','import','in','is','lambda','nonlocal',
    'not','or','pass','raise','return','try','while','with','yield'
  ]);
  const builtins = new Set([
    'abs','all','any','bool','dict','enumerate','float','int','len','list','map','max','min','open',
    'print','range','set','str','sum','super','tuple','zip'
  ]);
  let out = '';
  let i = 0;
  while (i < code.length) {
    const ch = code[i];
    if (ch === '#') {
      const end = code.indexOf('\n', i);
      const stop = end === -1 ? code.length : end;
      out += `<span class="tok-comment">${esc(code.slice(i, stop))}</span>`;
      i = stop;
      continue;
    }
    if (ch === '"' || ch === "'") {
      const quote = ch;
      const triple = code.slice(i, i + 3) === quote.repeat(3);
      let j = i + (triple ? 3 : 1);
      while (j < code.length) {
        if (!triple && code[j] === '\\') { j += 2; continue; }
        if (triple && code.slice(j, j + 3) === quote.repeat(3)) { j += 3; break; }
        if (!triple && code[j] === quote) { j += 1; break; }
        j += 1;
      }
      out += `<span class="tok-string">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    if (ch === '@') {
      const m = code.slice(i).match(/^@[A-Za-z_][A-Za-z0-9_.]*/);
      if (m) { out += `<span class="tok-decorator">${esc(m[0])}</span>`; i += m[0].length; continue; }
    }
    if (/[0-9]/.test(ch)) {
      const m = code.slice(i).match(/^[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);
      if (m) { out += `<span class="tok-number">${m[0]}</span>`; i += m[0].length; continue; }
    }
    if (/[A-Za-z_]/.test(ch)) {
      const m = code.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      const word = m[0];
      if (keywords.has(word)) out += `<span class="tok-keyword">${word}</span>`;
      else if (builtins.has(word)) out += `<span class="tok-builtin">${word}</span>`;
      else out += esc(word);
      i += word.length;
      continue;
    }
    if (/[+\-*/%=<>!&|^~:.,()[\]{}]/.test(ch)) {
      out += `<span class="tok-operator">${esc(ch)}</span>`;
      i += 1;
      continue;
    }
    out += esc(ch);
    i += 1;
  }
  return out;
}
